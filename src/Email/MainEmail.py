# -*- coding: utf-8 -*-
# 邮件构建与发送核心类模块
# 作者：LF
# 创建时间：2026-08-23
# 功能：LEmail 类提供统一接口，接收邮件参数后构建标准 MIME 邮件对象，
#       并通过阿里云邮件推送 SMTP 服务完成发送。
#       普通模式与高级模式共用同一套接口：
#       普通模式一次构建一封邮件，高级模式由上层循环调用本类实现批量差异化发送。

import os
import sys
import smtplib
import time
import traceback
from ssl import SSLWantWriteError, SSLWantReadError
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

# 日志系统：引入 logger，记录 SMTP 连接与发送各阶段日志
from logger import getLogger
log = getLogger(__name__)

# SMTP 服务器地址（阿里云邮件推送，华东1 杭州）
SMTP_HOST = 'smtpdm.aliyun.com'
# SMTP SSL 加密端口
SMTP_SSL_PORT = 465
# SMTP 连接超时时间（秒），防止网络波动导致长期挂起
SMTP_TIMEOUT = 30
# 连接失败时的最大重试次数
SMTP_MAX_RETRY = 3
# 每次重试前的间隔时间（秒）
SMTP_RETRY_INTERVAL = 1
# 邮件总大小上限（字节）：阿里云邮件推送对 SMTP 实际发送总大小限制为 15MB
SMTP_MAX_EMAIL_SIZE = 15 * 1024 * 1024
# 单封 SMTP 邮件最多收件人数（to+cc+bcc 合计），官方限制 100
SMTP_MAX_RECIPIENTS = 100
# 单封邮件最多附件个数，官方限制 100
SMTP_MAX_ATTACHMENTS = 100
# base64 编码膨胀系数（4/3≈1.34，预留余量）
BASE64_INFLATE = 1.35
# 邮件头部与 MIME 边界等的额外开销估算（字节）
EMAIL_OVERHEAD = 128 * 1024


# ============ SMTP 凭据防泄漏加固（C 扩展承载解密 + 密钥分片）==================
# 说明：
#   - 真实账号/密码经 store_credentials.py 加密后存于 credentials.enc（不入库）。
#   - 解密逻辑与密钥分片A/盐固化在 src/security/cred_app.pyd（C 二进制）。
#   - 密钥分片B由调用方（本文件）持有，运行期拼装完整密钥后解密，全程内存短存活。
# 这样：源码与仓库中均不存在明文密码，字符串扫描与反编译直接剥离均无法直接取得凭据。
# 密钥分片B（片段，与 store_credentials.py 保持一致，缺片无法还原）
CRED_KEY_PART_B = b'Ua4#p9'


def loadSmtpCredentials():
    """加载 SMTP 账号密码（仅经 C 扩展解密加密凭据，不再读明文配置文件）

    加载优先级：
      1. credentials.enc + cred_app.pyd：真实凭据加密存储，解密后返回（唯一来源）。
      （为满足「程序内不留明文」要求，已移除 config.local/config.example 明文回退）

    返回：
        tuple<str,str>：(发信账号, 密码)；加密凭据缺失或解密失败时返回空串
    """
    # 经 C 扩展解密加密凭据文件（credentials.enc 与 .pyd 同目录于 src/security）
    return _decryptFromCredentialFile() or ('', '')


def _decryptFromCredentialFile():
    """从加密凭据文件读取并解密 SMTP 账号密码（经 C 扩展 cred_app.pyd）

    解密流程：
      1. 定位加密目录：以 cred_app 模块（cred_app.pyd）所在目录为准，
         credentials.enc 与其放于同一目录（src/security）。
      2. 若加密文件或 C 扩展缺失 => 返回 None（走配置回退）。
      3. 读取 base64 密文 -> 调 cred_app.decrypt_credentials 还原明文字节。
      4. 按「账号\\n密码」拆分返回；任一步异常则安全回退 None。

    返回：
        tuple<str,str>|None：解密成功返回 (账号, 密码)；失败返回 None
    """
    # 导入 C 扩展（编译产物 cred_app.pyd，与加密文件同目录；缺失则走回退）
    import base64 as _b64
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../security')
    try:
        import cred_app
        # 加密目录 = .pyd 所在目录；打包后 .pyd 与 .enc 放同目录即可命中
        crypto_dir = os.path.dirname(os.path.abspath(cred_app.__file__))
        enc_path = os.path.join(crypto_dir, 'credentials.enc')
        if not os.path.exists(enc_path):
            return None
        with open(enc_path, 'r', encoding='ascii') as fobj:
            cipher = _b64.b64decode(fobj.read().strip())
        plain = cred_app.decrypt_credentials(cipher, CRED_KEY_PART_B)
        # 密文格式：账号\n密码
        username, password = plain.split('\n', 1)
        if username and password:
            return (username, password)
    except Exception as exc:
        # 解密任一步失败：记录日志并安全回退，避免程序崩溃
        log.warning('SMTP 凭据解密失败，回退明文配置: %s', exc)
    return None


# 发信账号与密码：从本地配置加载（不入库），避免公开 GitHub 仓库泄露凭据
SMTP_USERNAME, SMTP_PASSWORD = loadSmtpCredentials()


class LEmail:
    """邮件构建与发送类

    接收发件人、收件人、正文、附件等参数，
    构建标准 MIME 邮件对象，并通过 SMTP 发送。
    """

    def __init__(self, mode="Normal"):
        """初始化邮件参数字段与模式标志

        参数：
            mode<str>：邮件模式，默认 "Normal"（普通），可选 "High"（高级）
        """
        # 发件人昵称（显示在收件人看到的发件人名称处）
        self.n_name = ""
        # 收件人列表
        self.to = []
        # 抄送人列表
        self.cc = []
        # 密送人列表（收件人互相看不到）
        self.bcc = []
        # 回信地址（收件人回复时发送到这里）
        self.reply_to = ""
        # 退信地址（投递失败时退信发送到这里）
        self.return_email_value = ""
        # 合并所有收件人（单次 SMTP 发送最多 100 人，见 SMTP_MAX_RECIPIENTS）
        self.receivers = []

        # 邮件主题
        self.email_title = ""
        # html 正文内容
        self.html_text = ""
        # 附件文件路径列表
        self.attachment_path = []
        # html 内嵌图片路径列表（content-id 自动使用文件名）
        self.inline_image_path = []

        # 邮件模式字符串
        self.mode = mode
        # 是否为普通模式
        self.is_normal = False
        # 是否为高级模式
        self.is_high = False
        # 初始化时判断并设置模式标志
        self.judgeMode()

    def judgeMode(self):
        """判断邮件模式并设置对应标志"""
        if self.mode == "High":
            self.is_high = True
            self.is_normal = False
        else:
            self.is_normal = True
            self.is_high = False

    def refreshReceivers(self):
        """刷新合并收件人列表（to + cc + bcc）"""
        self.receivers = self.to + self.cc + self.bcc

    @staticmethod
    def toList(value):
        """将参数规整为列表

        参数：
            value<str|list|tuple>：待规整的值

        返回：
            result<list>：规整后的列表
        """
        if isinstance(value, (list, tuple)):
            return list(value)
        if value is None:
            return []
        return [value]

    # ---- setter：接收邮件参数 ----

    def setFrom(self, name):
        """设置发件人昵称

        参数：
            name<str>：发件人昵称
        """
        self.n_name = name

    def setTo(self, to_email):
        """设置收件人

        参数：
            to_email<list[str]>：收件人邮箱地址列表
        """
        self.to = self.toList(to_email)

    def setToCopy(self, cc_email):
        """设置抄送人

        参数：
            cc_email<list[str]>：抄送人邮箱地址列表
        """
        self.cc = self.toList(cc_email)

    def setToBcc(self, bcc_email):
        """设置密送人

        参数：
            bcc_email<list[str]>：密送人邮箱地址列表
        """
        self.bcc = self.toList(bcc_email)

    def setReplyTo(self, reply_email):
        """设置回信地址

        参数：
            reply_email<str>：回信地址
        """
        self.reply_to = reply_email

    def setReturnEmail(self, return_email):
        """设置退信地址

        参数：
            return_email<str>：退信地址
        """
        self.return_email_value = return_email

    def setTitle(self, title):
        """设置邮件主题

        参数：
            title<str>：邮件主题
        """
        self.email_title = title

    def setText(self, html_text):
        """设置 html 正文

        参数：
            html_text<str>：html 格式正文内容
        """
        self.html_text = html_text

    def setFile(self, attachment_path):
        """设置附件

        参数：
            attachment_path<str|list[str]>：附件文件路径（可传单个或列表）
        """
        self.attachment_path = self.toList(attachment_path)

    def setInlineImage(self, inline_image_path):
        """设置 html 内嵌图片

        支持两种形式：
          - 列表/单个路径 <list[str]|str>：content-id 自动使用文件名
          - 映射 <dict<content_id, file_path>>：自定义 content-id，供 GUI
            端「以 cid:xxx 引用 + 重名唯一化」场景保证引用与 Content-ID 一致。

        参数：
            inline_image_path<dict|str|list[str]>：内嵌图片文件路径或 cid 映射
        """
        self.inline_image_path = inline_image_path

    # ---- 构建 MIME 对象 ----

    def buildMessage(self):
        """构建完整 MIME 邮件对象

        根据正文、内嵌图片、附件自动组装 alternative / related / mixed 结构。

        返回：
            msg<MIMEMultipart>：构建完成的邮件对象
        """
        # 先刷新合并收件人列表
        self.refreshReceivers()
        # 构建正文（alternative 结构：纯文本 + html）
        body = self.buildAlternative()
        # 若有内嵌图片，将正文包装进 related 结构
        if self.inline_image_path:
            body = self.buildRelated(body)
        # 若有附件，将正文包装进 mixed 结构
        if self.attachment_path:
            msg = self.buildMixed(body)
        else:
            msg = body
        # 设置邮件头部信息
        self.buildHeaders(msg)
        return msg

    def buildAlternative(self):
        """构建 alternative 结构（纯文本与 html 两个版本正文）

        返回：
            msg<MIMEMultipart>：alternative 结构邮件正文
        """
        msg = MIMEMultipart('alternative')
        # 纯文本版本（供不支持 html 的客户端展示）
        text_plain = MIMEText('请使用支持 HTML 的邮件客户端查看本邮件', 'plain', 'utf-8')
        # html 版本正文
        text_html = MIMEText(self.html_text, 'html', 'utf-8')
        msg.attach(text_plain)
        msg.attach(text_html)
        return msg

    def buildRelated(self, body):
        """构建 related 结构（正文 + html 内嵌图片）

        参数：
            body<MIMEMultipart>：已构建的 alternative 正文

        返回：
            msg<MIMEMultipart>：related 结构邮件正文
        """
        msg = MIMEMultipart('related')
        msg.attach(body)
        # 遍历内嵌图片：映射形式为 {content_id: 路径}，列表形式 cid 用文件名（以 None 占位）
        if isinstance(self.inline_image_path, dict):
            inline_items = list(self.inline_image_path.items())
        else:
            inline_items = [(None, p) for p in self.toList(self.inline_image_path)]
        for content_id, image_path in inline_items:
            with open(image_path, 'rb') as image_file:
                image = MIMEImage(image_file.read())
            # content-id：未显式指定时使用文件名
            if content_id is None:
                content_id = os.path.basename(image_path)
            image.add_header('Content-ID', '<%s>' % content_id)
            image.add_header('Content-Disposition', 'inline',
                             filename=Header(content_id, 'utf-8').encode())
            msg.attach(image)
        return msg

    def buildMixed(self, body):
        """构建 mixed 结构（正文 + 附件）

        参数：
            body<MIMEMultipart>：已构建的正文（alternative 或 related）

        返回：
            msg<MIMEMultipart>：mixed 结构邮件对象
        """
        msg = MIMEMultipart('mixed')
        msg.attach(body)
        # 逐个读取附件并挂载
        for file_path in self.attachment_path:
            with open(file_path, 'rb') as attach_file:
                attachment = MIMEApplication(attach_file.read())
            # 提取文件名（带后缀）
            filename = file_path.split('\\')[-1]
            # 设置附件名（支持中文需 Header 编码）
            attachment.add_header('Content-Disposition', 'attachment',
                                  filename=Header(filename, 'utf-8').encode())
            msg.attach(attachment)
        return msg

    def buildHeaders(self, msg):
        """设置邮件头部信息

        参数：
            msg<MIMEMultipart>：待设置头部的邮件对象
        """
        # 发件人：昵称 + 发信地址
        msg['From'] = formataddr([self.n_name, SMTP_USERNAME])
        # 收件人（密送不写入头部，避免泄露）
        msg['To'] = ','.join(self.to)
        # 抄送人
        if self.cc:
            msg['Cc'] = ','.join(self.cc)
        # 主题（Header 编码支持中文）
        msg['Subject'] = Header(self.email_title, 'utf-8')
        # 回信地址
        if self.reply_to:
            msg['Reply-to'] = self.reply_to
        # 退信地址
        if self.return_email_value:
            msg['Return-Path'] = self.return_email_value
        # 唯一标识邮件（RFC 5322）
        msg['Message-id'] = make_msgid()
        # 发送时间
        msg['Date'] = formatdate()

    # ---- 发送邮件 ----

    def smtpConnect(self):
        """建立 SMTP_SSL 连接（带超时与重试）

        SMTP 连接属易受网络波动影响的操作，此处独立封装：超时控制 + 最多
        重试若干次，均失败则抛出最后一次异常，交给上层捕获打印真实原因。

        返回：
            client<smtplib.SMTP_SSL>：已建立且完成 ehlo 的 SMTP 连接

        抛出：
            Exception：最后一次连接异常
        """
        last_error = None
        # 携带超时反复尝试建立 SSL 连接与 ehlo 握手
        for attempt in range(SMTP_MAX_RETRY):
            try:
                client = smtplib.SMTP_SSL(SMTP_HOST, SMTP_SSL_PORT, timeout=SMTP_TIMEOUT)
                # 主动 ehlo 握手，确保连接可用（避免「Server not connected」）
                client.ehlo()
                return client
            except Exception as error:
                last_error = error
                log.warning('SMTP 连接失败（第 %d/%d 次）: %s',
                            attempt + 1, SMTP_MAX_RETRY, error)
                # 非最后一次尝试前稍作等待后重试
                if attempt < SMTP_MAX_RETRY - 1:
                    time.sleep(SMTP_RETRY_INTERVAL)
        # 抛出最后一次异常以打印完整堆栈
        raise last_error

    def estimateEmailSize(self):
        """估算邮件实际发送总大小（含正文、附件 base64 膨胀与头部开销）

        返回：
            int：估算的总字节数
        """
        # 附件原始字节数之和
        attach_bytes = sum(os.path.getsize(p) for p in self.attachment_path if os.path.exists(p))
        # 正文 + 附件(base64膨胀) + 头部开销
        return len(self.html_text) + int(attach_bytes * BASE64_INFLATE) + EMAIL_OVERHEAD

    def checkEmailSize(self):
        """校验邮件总大小是否超过阿里云邮件推送的上限

        返回：
            tuple(bool, int, int)：(是否超限, 估算大小, 上限)
            返回的估算/上限单位为字节；未超限时第一项为 False。
        """
        size = self.estimateEmailSize()
        return size > SMTP_MAX_EMAIL_SIZE, size, SMTP_MAX_EMAIL_SIZE

    def checkLimits(self):
        """校验收件人数与附件数是否超过阿里云邮件推送的上限

        返回：
            tuple(bool, str)：(是否超限, 提示信息)；未超限时第二项为空字符串
        """
        # 收件人总数（to+cc+bcc）上限校验
        if len(self.receivers) > SMTP_MAX_RECIPIENTS:
            return True, ('收件人数量 %d 超过单封邮件上限 %d，请分批发送。'
                          % (len(self.receivers), SMTP_MAX_RECIPIENTS))
        # 附件数量上限校验
        if len(self.attachment_path) > SMTP_MAX_ATTACHMENTS:
            return True, ('附件数量 %d 超过单封邮件上限 %d，请分批或合并发送。'
                          % (len(self.attachment_path), SMTP_MAX_ATTACHMENTS))
        return False, ""

    def sendMail(self):
        """通过 SMTP 发送邮件

        使用阿里云邮件推送 SSL 端口 465 建立连接、登录并发送。
        发送前先校验邮件总大小（15MB）、收件人数（100）、附件数（100），
        超限不建立连接直接返回失败；连接阶段独立加超时与重试；
        发送阶段对瞬时性错误自动重建连接重试。

        返回：
            bool：发送成功返回 True，失败返回 False
        """
        # 构建完整的 MIME 邮件对象（内部会刷新收件人列表）
        msg = self.buildMessage()
        # 发送前校验收件人数/附件数：超限则不建立连接，直接拒绝
        over_limits, limit_msg = self.checkLimits()
        if over_limits:
            log.error('邮件发送失败（超限）：%s', limit_msg)
            return False
        # 发送前校验邮件总大小：超限则不建立连接，直接拒绝（阿里云限制 15MB）
        over_limit, est_size, max_size = self.checkEmailSize()
        if over_limit:
            log.error('邮件发送失败：不支持发送超大附件。当前邮件约 %.1f MB，'
                      '超过阿里云邮件推送的 %.1f MB 上限。',
                      est_size / 1024 / 1024, max_size / 1024 / 1024)
            return False
        # 记录最后一次瞬时错误（重试耗尽时用于输出完整堆栈）
        last_transient = None
        # 整体尝试多次，覆盖连接与 data 发送阶段
        for attempt in range(SMTP_MAX_RETRY):
            client = None
            try:
                # 建立 SMTP_SSL 连接（内部已完成 ehlo 握手）
                client = self.smtpConnect()
                # 登录（发件人与认证地址必须一致）
                client.login(SMTP_USERNAME, SMTP_PASSWORD)
                # 发送（支持多个收件人）
                client.sendmail(SMTP_USERNAME, self.receivers, msg.as_string())
                # 正常退出 SMTP 会话
                client.quit()
                client = None
                # 日志脱敏：不打印发件人账号与收件人邮箱，仅记录成功与收件人数
                log.info('邮件发送成功，收件人 %d 人', len(self.receivers))
                return True
            except (
                SSLWantWriteError, SSLWantReadError,
                smtplib.SMTPServerDisconnected,
                ConnectionError, TimeoutError,
            ) as error:
                # 瞬时性/网络中断错误：记录并稍后重建连接重试
                last_transient = error
                log.warning('SMTP 发送阶段失败（第 %d/%d 次）: %s',
                            attempt + 1, SMTP_MAX_RETRY, error)
                time.sleep(SMTP_RETRY_INTERVAL)
            except smtplib.SMTPConnectError as error:
                log.error('邮件发送失败，连接失败: %s %s',
                          error.smtp_code, error.smtp_error)
                break
            except smtplib.SMTPAuthenticationError as error:
                log.error('邮件发送失败，认证错误: %s %s',
                          error.smtp_code, error.smtp_error)
                break
            except smtplib.SMTPSenderRefused as error:
                log.error('邮件发送失败，发件人被拒绝: %s %s',
                          error.smtp_code, error.smtp_error)
                break
            except smtplib.SMTPRecipientsRefused as error:
                log.error('邮件发送失败，收件人被拒绝: %s %s',
                          error.smtp_code, error.smtp_error)
                break
            except smtplib.SMTPDataError as error:
                log.error('邮件发送失败，数据接收拒绝: %s %s',
                          error.smtp_code, error.smtp_error)
                break
            except smtplib.SMTPException as error:
                log.error('邮件发送失败(SMTP): %s', str(error), exc_info=True)
                break
            except Exception as error:
                log.error('邮件发送异常: %s', str(error), exc_info=True)
                break
            finally:
                # 出错时确保断开连接，避免残留 socket
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
        # 重试耗尽仍未成功：记录最后一次瞬时错误的完整堆栈
        if last_transient is not None:
            log.error('SMTP 发送重试耗尽，最后一次错误: %s',
                      last_transient, exc_info=True)
        return False

    def _printTraceback(self):
        """输出完整异常堆栈，便于定位发送阶段真实原因"""
        traceback.print_exc()