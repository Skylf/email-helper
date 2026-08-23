# Bug: 选择 Excel 收件人文件导致程序闪退

**日期**: 2026-08-23
**版本**: v0.1A 开发版
**优先级**: 高

## 现象
普通模式写信页点击「收件人选择」→ 选择文件（Excel `recipients_test.xlsx`）→ 确认后程序直接闪退（无提示），退出码 `-1073740791 (0xC0000409)`，即 STATUS_STACK_BUFFER_OVERRUN 的 fail-fast 原生崩溃。选择 TXT 文件则一切正常。

## 根因
- `.venv` 虚拟环境缺失 `openpyxl` 依赖（`pip list` 仅显示 PyQt6、setuptools、pip，无 openpyxl）。
- 解析 Excel 时 `_parseXlsx`（src/activity/recipient_bulk.py）执行 `import openpyxl`，因依赖缺失抛 `ModuleNotFoundError`。
- 该异常发生在「收件人选择器」modal 对话框的事件循环里、且在 `QFileDialog` 关闭后的上下文；此处的裸异常未被 Python 层接住，PyQt6 事件循环下最终以原生 fail-fast 崩溃（0xC0000409）收场。
- 之所以 TXT 正常，是因为 TXT 走纯标准库 `open()`，不依赖任何第三方库。

## 修复
1. 在项目 `.venv` 中安装缺失依赖：`pip install openpyxl`（使用清华源避开公司代理 SSL 证书问题）。实测后 Excel 解析与 GUI 展示均正常。
2. 加固异常兜底：`RecipientPickerDialog.onPickFile`（src/GUI/MainGUI.py）对解析异常由仅捕获 `ValueError` 扩展为 `(ValueError, ImportError)`，缺依赖等解析失败时会弹窗友好提示，避免再次走崩溃路径。

## 验证
- 使用 `.venv\Scripts\python.exe` 复现：解析 `recipients_test.xlsx` → 得到 1000 个邮箱，列表 1000 条、默认「已勾选 1000 / 共 1000」，无崩溃。
- 系统 python 与 venv python 下 TXT/XLSX 均检测 1000 邮箱、唯一数 1000。
- `py_compile` 通过。
- 提示：requirements.txt 中 openpyxl 原已有记录，本次为在运行环境补齐安装。