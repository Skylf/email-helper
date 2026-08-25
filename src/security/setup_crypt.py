# -*- coding: utf-8 -*-
# C 扩展构建脚本：把 cred_app 编译为平台原生扩展
#   Windows -> cred_app.cp311-win_amd64.pyd
#   macOS   -> cred_app.cpython-311-darwin.so
# 作者：LF
# 创建时间：2026-08-25
# 用法：在 src/security 目录下执行  python setup_crypt.py build_ext --inplace
# 说明：优先编译 cred_app.pyx（需 Cython）；若源码为 cred_app.c（Cython 产出的 C），
#       则无需 Cython 直接编译，跨平台复用同一份 C 逻辑，保证 Windows/macOS 解密结果一致。
#       构建产物供 src/Email/MainEmail.py 导入并调用 decrypt_credentials。

import os
import sys

from setuptools import setup
from setuptools.extension import Extension

# 本目录（src/security）
_SEC_DIR = os.path.dirname(os.path.abspath(__file__))
# 是否 Windows：决定编译参数与产物后缀
IS_WINDOWS = sys.platform == 'win32'


def selectSource():
    """选择扩展源码文件：优先 .pyx（需 Cython 预处理），否则直接用 .c（Cython 产物）"""
    pyx_path = os.path.join(_SEC_DIR, 'cred_app.pyx')
    if os.path.exists(pyx_path):
        return 'cred_app.pyx', 'cython'
    c_path = os.path.join(_SEC_DIR, 'cred_app.c')
    if os.path.exists(c_path):
        return 'cred_app.c', 'c'
    raise SystemExit('未找到 cred_app.pyx 或 cred_app.c，无法构建扩展')


def buildExtensions():
    """构建扩展模块列表；.pyx 走 cythonize，.c 直接编译"""
    source, kind = selectSource()
    # 平台相关编译优化参数：Windows 用 MSVC 风格，macOS/Linux 用 GCC/Clang 风格
    compile_args = ['/O2'] if IS_WINDOWS else ['-O2']
    extension = Extension(
        name='cred_app',
        sources=[source],
        # 纯 C 变换，无需外部库；仅用标准 C 库
        libraries=[],
        extra_compile_args=compile_args,
    )
    if kind == 'cython':
        # 需要 Cython：把 .pyx 转为 .c 再由 setuptools 编译
        from Cython.Build import cythonize
        return cythonize([extension], language_level=3)
    # 直接编译既有 .c，无需 Cython
    return [extension]


setup(
    name='cred_app',
    ext_modules=buildExtensions(),
)