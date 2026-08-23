# -*- coding: utf-8 -*-
# 普通模式（NormalMode）：邮件发送用户交互层
# 作者：LF
# 创建时间：2026-08-23
# 功能：负责接收、处理用户输入（发件人昵称、收件人、主题、正文、附件、内嵌图片等），
#       并将其设置到 MainEmail.LEmail 实例中，最终调用 LEmail 的接口完成发送。
#       本模块只做「用户输入 -> 参数设置 -> 调用发送」的上游编排，
#       不重复实现 LEmail 中已有的 MIME 构建与 SMTP 发送逻辑。

import os
import re

# 同包内导入邮件构建与发送核心类；使用包相对导入，不依赖 sys.path，
# 无论在 GUI（包导入）还是 runTest（包方式）下都能正确定位同目录的 MainEmail。
from .MainEmail import LEmail

# 发件人昵称默认值（用户直接回车时使用）
DEFAULT_FROM_NAME = 'Lhack 邮箱助手'


class NormalMode:
    """普通模式邮件发送交互类

    以命令行交互方式依次采集邮件各参数，
    处理后调用 LEmail 接口完成发送。
    """

    def __init__(self):
        # 创建普通模式邮件实例（模式固定为 Normal）
        self.email = LEmail('Normal')

    @staticmethod
    def splitEmails(text):
        """将输入的邮箱地址串拆分为去空后的列表（按逗号/分号/空格等分隔）

        参数：
            text<str>：用户输入的邮箱地址串

        返回：
            list：拆分去空后的邮箱地址列表
        """
        # 正则按逗号、分号、中文逗号/分号、空白拆分，并过滤空项
        return [part for part in re.split(r'[,;，；\s]+', text.strip()) if part]

    @staticmethod
    def splitPaths(text):
        """将输入的路径串拆分为去空后的列表（仅按逗号/分号分隔，避免破坏含空格的路径）

        参数：
            text<str>：用户输入的路径串

        返回：
            list：拆分去空后的路径列表
        """
        # 去除首尾空白与包裹引号后按逗号/分号拆分
        return [part.strip('"\'') for part in re.split(r'[,;，；]', text.strip()) if part.strip()]

    def inputFrom(self):
        """输入发件人昵称（允许为空，使用默认昵称）"""
        print('\n--- 发件人设置 ---')
        name = input('发件人昵称（直接回车使用默认「%s」）：' % DEFAULT_FROM_NAME).strip()
        # 空输入时回退到默认昵称
        self.email.setFrom(name if name else DEFAULT_FROM_NAME)

    def inputRecipients(self):
        """输入收件人 / 抄送 / 密送（收件人必填，抄送与密送可空）"""
        print('\n--- 收件人设置 ---')
        # 收件人为必填项，空输入则循环提示
        to_list = self.splitEmails(input('收件人（多个用逗号/分号分隔，必填）：'))
        while not to_list:
            to_list = self.splitEmails(input('收件人不能为空，请重新输入：'))
        self.email.setTo(to_list)
        # 抄送为可选项
        cc_text = input('抄送（可空，多个用逗号/分号分隔）：')
        if cc_text.strip():
            self.email.setToCopy(self.splitEmails(cc_text))
        # 密送为可选项
        bcc_text = input('密送（可空，多个用逗号/分号分隔）：')
        if bcc_text.strip():
            self.email.setToBcc(self.splitEmails(bcc_text))

    def inputReplyTo(self):
        """输入回信地址与退信地址（均可空）"""
        print('\n--- 回信 / 退信设置（可空）---')
        reply_text = input('回信地址（收件人回复时发送到这里）：')
        if reply_text.strip():
            self.email.setReplyTo(reply_text.strip())
        return_text = input('退信地址（投递失败时退信到这里）：')
        if return_text.strip():
            self.email.setReturnEmail(return_text.strip())

    def inputTitle(self):
        """输入邮件主题"""
        title = input('\n邮件主题：')
        # 空主题时使用占位符，避免发送无主题邮件
        self.email.setTitle(title.strip() if title.strip() else '(无主题)')

    def inputBody(self):
        """输入 HTML 正文（多行输入，独立一行 END 结束）"""
        print('\n--- 正文 ---')
        print('请输入 HTML 正文（支持 html 标签，多行输入，单独一行输入 END 结束）：')
        lines = []
        while True:
            line = input()
            # 独立一行 END 作为正文输入结束标记
            if line.strip().upper() == 'END':
                break
            lines.append(line)
        body = '\n'.join(lines)
        # 空正文时填入一个空段落，保证邮件有正文
        self.email.setText(body if body.strip() else '<p></p>')

    def inputAttachments(self):
        """输入附件路径（可空，多个用逗号/分号分隔，不存在则跳过并告警）"""
        print('\n--- 附件设置（可空）---')
        text = input('附件路径（多个用逗号/分号分隔）：')
        if not text.strip():
            return
        valid_paths = []
        for path in self.splitPaths(text):
            if os.path.exists(path):
                valid_paths.append(path)
            else:
                print('警告：附件不存在，已跳过 ->', path)
        if valid_paths:
            self.email.setFile(valid_paths)

    def inputInlineImages(self):
        """输入 HTML 内嵌图片路径（可空，多个用逗号/分号分隔，不存在则跳过并告警）"""
        print('\n--- 内嵌图片设置（可空）---')
        print('提示：正文中用 <img src="cid:文件名"> 引用内嵌图片。')
        text = input('内嵌图片路径（多个用逗号/分号分隔）：')
        if not text.strip():
            return
        valid_paths = []
        for path in self.splitPaths(text):
            if os.path.exists(path):
                valid_paths.append(path)
            else:
                print('警告：图片不存在，已跳过 ->', path)
        if valid_paths:
            self.email.setInlineImage(valid_paths)

    def showSummary(self):
        """打印当前邮件配置摘要，供用户发送前确认"""
        mail = self.email
        print('\n' + '=' * 42)
        print(' 邮件配置摘要')
        print('=' * 42)
        print(' 发件人昵称 :', mail.n_name)
        print(' 收件人     :', ', '.join(mail.to))
        print(' 抄送       :', ', '.join(mail.cc) if mail.cc else '（无）')
        print(' 密送       :', ', '.join(mail.bcc) if mail.bcc else '（无）')
        print(' 回信地址   :', mail.reply_to or '（无）')
        print(' 退信地址   :', mail.return_email_value or '（无）')
        print(' 主题       :', mail.email_title)
        print(' 附件       :', ', '.join(mail.attachment_path) if mail.attachment_path else '（无）')
        print(' 内嵌图片   :', ', '.join(mail.inline_image_path) if mail.inline_image_path else '（无）')
        print('=' * 42)

    def setConfig(self, n_name, to_list, cc_list=None, bcc_list=None,
                  reply_to='', return_email='', email_title='',
                  html_text='', attachment_paths=None, inline_image_paths=None):
        """程序化配置邮件参数（供 GUI 等非命令行调用端使用）

        说明：本方法替代 CLI 交互式的 inputFrom/inputRecipients 等，
        由调用端直接传入各参数并设置到 email（LEmail）实例。
        其中正文为空时填入空段落，主题为空时使用占位符。

        参数：
            n_name<str>：发件人昵称
            to_list<list>：收件人列表（必填）
            cc_list<list|None>：抄送列表
            bcc_list<list|None>：密送列表
            reply_to<str>：回信地址
            return_email<str>：退信地址
            email_title<str>：主题
            html_text<str>：HTML 正文
            attachment_paths<list|None>：附件路径列表
            inline_image_paths<list|None>：内嵌图片路径列表

        返回：
            bool：配置成功返回 True，收件人为空返回 False
        """
        # 校验收件人必填
        if not to_list:
            return False
        # 依次调用 LEmail 的 setter 设置各参数
        self.email.setFrom(n_name if n_name else DEFAULT_FROM_NAME)
        self.email.setTo(to_list)
        if cc_list:
            self.email.setToCopy(cc_list)
        if bcc_list:
            self.email.setToBcc(bcc_list)
        if reply_to:
            self.email.setReplyTo(reply_to)
        if return_email:
            self.email.setReturnEmail(return_email)
        self.email.setTitle(email_title if email_title else '(无主题)')
        # 正文为空时填入空段落，保证邮件有正文
        self.email.setText(html_text if html_text else '<p></p>')
        if attachment_paths:
            self.email.setFile(attachment_paths)
        if inline_image_paths:
            self.email.setInlineImage(inline_image_paths)
        return True

    def checkSize(self):
        """校验当前已配置邮件的总大小是否超过阿里云上限

        委托底层 LEmail.checkEmailSize() 估算；用于 GUI 在发送前拦截超大附件。

        返回：
            tuple(bool, int, int)：(是否超限, 估算大小字节, 上限字节)
        """
        return self.email.checkEmailSize()

    def checkLimits(self):
        """校验收件人数与附件数是否超过阿里云上限

        委托底层 LEmail.checkLimits()；用于 GUI 发送前拦截。

        返回：
            tuple(bool, str)：(是否超限, 提示信息)
        """
        return self.email.checkLimits()

    def send(self):
        """调用 LEmail 接口发送邮件并输出结果

        返回：
            bool：发送成功返回 True，失败返回 False
        """
        result = self.email.sendMail()
        if result:
            print('\n邮件发送成功！')
        else:
            print('\n邮件发送失败，请检查上面的错误信息。')
        return result