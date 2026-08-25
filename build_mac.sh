#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# macOS 构建脚本：在 macOS 上生成 邮件助手.app
# 用法：在项目根目录执行  bash build_mac.sh
# 依赖：已安装 Python 3.11（或检查 3.11），系统已安装 Xcode Command Line Tools（clang）
# 说明：
#   1) 创建/复用 .venv-mac 虚拟环境并安装依赖与 PyInstaller
#   2) 用 setup_crypt.py 把 cred_app.c 编译为 cred_app*.so
#   3) 检查 credentials.enc（gitignore，不入库）与 app_icon.icns（用户制作）
#   4) 用 邮件助手_mac.spec 打包出 dist/邮件助手.app
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

echo "==> [1/5] 检查 Python 环境 ($PYTHON_BIN)"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python3"
"$PYTHON_BIN" -c 'import platform,sys; print(sys.version); print("arch:", platform.machine())'

echo "==> [2/5] 创建虚拟环境并安装依赖"
VENV_DIR="$PROJECT_ROOT/.venv-mac"
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
pip install -r "$PROJECT_ROOT/requirements.txt" "pyinstaller"

echo "==> [3/5] 编译 C 扩展 cred_app -> .so"
cd "$PROJECT_ROOT/src/security"
python setup_crypt.py build_ext --inplace

echo "==> [4/5] 校验凭据与图标"
if [ ! -f "credentials.enc" ]; then
  echo "!! 缺少 credentials.enc（已被 .gitignore，不会随仓库带出）。"
  echo "   若有 config.local，可运行：python store_credentials.py 重新生成；"
  echo "   否则需从可信来源拷贝该文件到本项目目录。"
fi
if [ ! -f "app_icon.icns" ]; then
  echo "!! 缺少 app_icon.icns，请将图标放入 src/security/app_icon.icns 后再打包。"
fi
cd "$PROJECT_ROOT"

echo "==> [5/5] PyInstaller 打包 .app"
pyinstaller --noconfirm --clean "$PROJECT_ROOT/邮件助手_mac.spec"

echo "==> 完成：dist/邮件助手.app"
# 可选：重新签名(即便无签名证书也用 ad-hoc，规避 Gatekeeper 沙盒对内部可写的限制)
codesign --force --deep --sign - "dist/邮件助手.app" 2>/dev/null || echo "（已跳过 ad-hoc 签名）"