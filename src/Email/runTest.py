# -*- coding: utf-8 -*-
# LEmail 全流程跑通测试脚本
# 作者：LF
# 创建时间：2026-08-23
# 功能：验证 MainEmail.LEmail 类的参数接收、MIME 构建与 SMTP 发送全流程。
#       覆盖三种场景：普通 HTML 邮件 / 带附件邮件 / 带内嵌图片邮件。
# 运行方式：python src/Email/runTest.py

import os
import struct
import sys
import zlib

from path_manager import PathManager

# 统一通过 PathManager 定位源码包根目录（开发=src，打包=_MEIPASS），
# 追加到 sys.path，保证「GUI」「Email」包在两种环境下都能被导入。
sys.path.insert(0, str(PathManager.source_root()))

# 以包方式导入邮件构建核心类与普通模式交互层（内部均使用包相对导入）
from Email.MainEmail import LEmail
from Email.NormalMode import NormalMode

# 项目根目录（开发态为项目根；打包态为 exe 所在目录）
PROJECT_ROOT = PathManager.root()
# 测试附件路径（复用阿里云邮件推送目录下已存在的 PDF）
ATTACHMENT_PATH = os.path.join(PROJECT_ROOT, '阿里云邮件推送', '测试附件.pdf')
# 测试内嵌图片的临时输出路径（测试结束后删除）
TEST_IMAGE_PATH = os.path.join(PathManager.source_root(), 'Email', 'test_image.png')

# 测试收件人邮箱地址（按需替换为自己的测试邮箱）
TO_EMAILS = ['3209391487@qq.com']
CC_EMAILS = ['3835748268@qq.com']
BCC_EMAILS = ['LF926088@88.com']
REPLY_TO = 'acceptyoufu@qq.com'
RETURN_EMAIL = '3209391487@qq.com'


def makeTestPng(file_path, width=3, height=3, color=(0, 122, 255)):
    """生成一张最小有效 PNG 图片（无第三方依赖，供内嵌图片测试使用）

    参数：
        file_path<str>：输出文件路径
        width<int>：图片宽度
        height<int>：图片高度
        color<tuple>：RGB 颜色 (r, g, b)
    """
    def makeChunk(chunk_type, data):
        # 构造 PNG 数据块：长度 + 类型 + 数据 + CRC32 校验
        length = struct.pack('>I', len(data))
        checksum = struct.pack('>I', zlib.crc32(chunk_type + data) & 0xffffffff)
        return length + chunk_type + data + checksum

    # PNG 文件签名
    signature = b'\x89PNG\r\n\x1a\n'
    # IHDR 头：宽、高、位深(8)、颜色类型(2=RGB)、压缩、滤波、隔行
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    # 像素数据：每行首字节为滤波类型 0，随后依次为 RGB 像素
    raw = b''
    for _ in range(height):
        raw += b'\x00' + bytes(bytearray([color[0], color[1], color[2]])) * width
    # IDAT 数据块为 zlib 压缩后的像素数据
    idat = zlib.compress(raw)
    # 依次写入签名、IHDR、IDAT、IEND，形成完整 PNG
    with open(file_path, 'wb') as png_file:
        png_file.write(signature + makeChunk(b'IHDR', ihdr) + makeChunk(b'IDAT', idat) + makeChunk(b'IEND', b''))


def testNormalHtml():
    """测试1：普通 HTML 邮件（含收件人/抄送/密送/回信/退信）

    返回：
        bool：发送成功返回 True，失败返回 False
    """
    print('\n[测试1] 普通 HTML 邮件 ...')
    mail = LEmail('Normal')
    mail.setFrom('Lhack 邮箱助手')
    mail.setTo(TO_EMAILS)
    mail.setToCopy(CC_EMAILS)
    mail.setToBcc(BCC_EMAILS)
    mail.setReplyTo(REPLY_TO)
    mail.setReturnEmail(RETURN_EMAIL)
    mail.setTitle('LEmail 全流程测试：普通 HTML 邮件')
    mail.setText('<h2>你好！</h2><p>这是一封 <b>HTML</b> 测试邮件。</p>')
    result = mail.sendMail()
    print('[测试1] 结果:', '成功' if result else '失败')
    return result


def testAttachment():
    """测试2：带附件邮件（HTML 正文 + PDF 附件）

    返回：
        bool：发送成功返回 True，失败返回 False
    """
    print('\n[测试2] 带附件邮件 ...')
    mail = LEmail('Normal')
    mail.setFrom('Lhack 邮箱助手')
    mail.setTo(TO_EMAILS)
    mail.setTitle('LEmail 全流程测试：带附件邮件')
    mail.setText('<p>请查收附件。</p>')
    mail.setFile(ATTACHMENT_PATH)
    result = mail.sendMail()
    print('[测试2] 结果:', '成功' if result else '失败')
    return result


def testInlineImage():
    """测试3：带内嵌图片邮件（HTML 正文 + 内嵌图片）

    返回：
        bool：发送成功返回 True，失败返回 False
    """
    print('\n[测试3] 带内嵌图片邮件 ...')
    # 生成本次测试使用的临时图片
    makeTestPng(TEST_IMAGE_PATH, width=3, height=3, color=(0, 122, 255))
    # content-id 与文件名一致（buildRelated 内部使用文件名作为 content-id）
    image_name = os.path.basename(TEST_IMAGE_PATH)
    mail = LEmail('Normal')
    mail.setFrom('Lhack 邮箱助手')
    mail.setTo(TO_EMAILS)
    mail.setTitle('LEmail 全流程测试：带内嵌图片邮件')
    mail.setText('<p>下方是内嵌图片：</p><img src="cid:%s">' % image_name)
    mail.setInlineImage(TEST_IMAGE_PATH)
    result = mail.sendMail()
    # 清理临时图片
    if os.path.exists(TEST_IMAGE_PATH):
        os.remove(TEST_IMAGE_PATH)
    print('[测试3] 结果:', '成功' if result else '失败')
    return result


def normalModeProcess():
    """普通模式交互式发送流程（串联 NormalMode 的 api 完成一次发送）"""
    normal_mode = NormalMode()
    print('=' * 42)
    print(' 普通模式邮件发送（交互流程）')
    print('=' * 42)
    # 依次调用 NormalMode 提供的输入 api，采集各参数
    normal_mode.inputFrom()
    normal_mode.inputRecipients()
    normal_mode.inputReplyTo()
    normal_mode.inputTitle()
    normal_mode.inputBody()
    normal_mode.inputAttachments()
    normal_mode.inputInlineImages()
    # 发送前展示配置摘要
    normal_mode.showSummary()
    # 循环等待合法确认输入
    while True:
        confirm = input('\n是否确认发送？(y/n)：').strip().lower()
        if confirm in ('y', 'yes'):
            normal_mode.send()
            break
        elif confirm in ('n', 'no'):
            print('已取消发送。')
            break
        else:
            print('输入无效，请输入 y 或 n。')


def main():
    """测试流程入口：选择运行 LEmail 自动测试或 NormalMode 交互流程"""
    print('=' * 40)
    print('请选择要运行的流程：')
    print('1. LEmail 底层 API 自动测试（真实发送 3 封）')
    print('2. NormalMode 普通模式交互流程')
    print('=' * 40)
    choice = input('请输入 1 或 2：').strip()
    if choice == '2':
        normalModeProcess()
    else:
        print('开始 LEmail 全流程跑通测试')
        testNormalHtml()
        testAttachment()
        testInlineImage()
        print('全部测试执行完毕')


if __name__ == '__main__':
    main()