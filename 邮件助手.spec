# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：邮件助手（Windows onedir）
# 用法：pyinstaller 邮件助手.spec
# 说明：项目开发/业务代码全部打包进 _internal；运行期数据(数据库/设置/日志)统一放 exe 同目录，
#       由 PathManager.root() 自适应定位；SMTP 加密凭据与 C 扩展 .pyd 同放入 _internal 保证能解密。

import os

# 项目根（PyInstaller exec 本 spec 时 __file__ 不可用，此处以运行目录为准，需在项目根执行打包）
PROJECT_ROOT = os.getcwd()
SEC = os.path.join(PROJECT_ROOT, 'src', 'security')

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'main.py')],
    pathex=[os.path.join(PROJECT_ROOT, 'src')],
    binaries=[
        # 解密 C 扩展放 _MEIPASS 根，运行期 import cred_app 方能命中
        (os.path.join(SEC, 'cred_app.cp311-win_amd64.pyd'), '.'),
    ],
    datas=[
        # 加密凭据与 .pyd 同目录，MainEmail 按 cred_app.__file__ 目录定位读取
        (os.path.join(SEC, 'credentials.enc'), '.'),
    ],
    hiddenimports=[
        'cred_app',              # 解密扩展
        'option', 'option.settings',
        'logger',
        'activity.recipient_bulk', 'activity.mail_query',
        'database.database',
        'GUI.runTest', 'Email.NormalMode',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'tkinter'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='邮件助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                      # windowed：不显示控制台
    icon=os.path.join(SEC, 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='邮件助手',
)