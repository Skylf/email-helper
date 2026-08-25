# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：邮件助手（macOS .app bundle）
# 用法：在 macOS 项目根目录执行  pyinstaller 邮件助手_mac.spec
# 前置：1) 已用 setup_crypt.py 编译出 cred_app*.so（见 src/security）
#       2) 已有 app_icon.icns（用户另行制作）
# 说明：BUNDLE 生成 邮件助手.app；运行期用户数据由 PathManager.root() 放到
#       ~/Library/Application Support/EmailHelper/，不写入只读 Bundle。

import glob
import os

# 项目根（PyInstaller 在本 spec 中无 __file__，以运行目录为准，需在项目根执行打包）
PROJECT_ROOT = os.getcwd()
SEC = os.path.join(PROJECT_ROOT, 'src', 'security')

# macOS 下 C 扩展编译产物为 cred_app*.so，取实际生成的那个；未编译则本段为空数组
CRED_SO = glob.glob(os.path.join(SEC, 'cred_app*.so'))
BINARIES = [(CRED_SO[0], '.')] if CRED_SO else []

# 图标：mac 需 .icns（用户制作）；若暂缺则不打包图标，避免出错
ICON = os.path.join(SEC, 'app_icon.icns')
ICON_CFG = ICON if os.path.exists(ICON) else None

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'main.py')],
    pathex=[os.path.join(PROJECT_ROOT, 'src')],
    binaries=BINARIES,            # 解密 C 扩展放 _MEIPASS，运行期 import cred_app 命中
    datas=[
        # 加密凭据与 .so 同目录，MainEmail 按 cred_app.__file__ 目录定位读取
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
    console=False,               # mac 同样为 GUI 程序，不显示终端
    icon=ICON_CFG,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='邮件助手',
)

# 生成 .app bundle；bundle_identifier 用 ASCII，避免中文 ID
app = BUNDLE(
    coll,
    name='邮件助手.app',
    icon=ICON_CFG,
    bundle_identifier='com.skylf.emailhelper',
)