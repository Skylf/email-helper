# Bug: .venv 缺少 PyQt6 且 pip 模块损坏

**日期**: 2026-08-23
**版本**: v0.0.1
**优先级**: 高

## 现象
用户运行 `.venv\Scripts\python.exe src\GUI\runTest.py` 时报错：
`ModuleNotFoundError: No module named 'PyQt6'`。

此前我验证 Python 环境使用的是系统 Python（已装 PyQt6），而项目 `.venv` 虚拟环境并未安装该依赖，
两者依赖不一致，导致用户在项目虚拟环境下无法启动 GUI。

## 根因
1. `.venv` 虚拟环境缺少 PyQt6 依赖（GUI 依赖 PyQt6，而虚拟环境未安装）。
   尝试安装时进一步暴露第二个问题：
2. `.venv` 内的 pip 内部第三方 vendor 包损坏，具体为
   `ImportError: cannot import name 'SeparateBodyFileCache' from 'pip._vendor.cachecontrol.caches'`，
   导致 `pip install` 命令在导入安装子模块时即失败，任何包都无法安装。

## 修复
1. 删除 `.venv/Lib/site-packages` 下损坏的 pip 包目录及 `pip-*.dist-info`，
   使用 `python -m ensurepip --upgrade` 重建 pip（重装为 24.0）。
2. 通过清华镜像安装 PyQt6：
   `python -m pip install PyQt6 -i https://pypi.tuna.tsinghua.edu.cn/simple`（成功安装 6.11.0）。

## 验证
1. `.venv\Scripts\python.exe -m pip --version` 正常输出 `pip 24.0`。
2. 在 `.venv` 下构造主窗口冒烟通过：`MainWindow` 标题正确、堆叠 2 页，说明 GUI 依赖已就绪。