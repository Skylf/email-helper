# -*- coding: utf-8 -*-
# GUI 运行入口（流程层）
# 作者：LF
# 创建时间：2026-08-23
# 功能：承载 GUI 程序的启动流程（创建应用与主窗口并进入事件循环）。
#       MainGUI.py 只提供界面类（api），不包含启动流程。
# 运行方式：python src/GUI/runTest.py

import sys

from PyQt6.QtWidgets import QApplication
from path_manager import PathManager

# 统一通过 PathManager 定位源码包根目录（开发=src，打包=_MEIPASS），
# 追加到 sys.path，保证「GUI」「Email」包在两种环境下都能被导入。
sys.path.insert(0, str(PathManager.source_root()))

# 跨文件调用说明：从 src/GUI/MainGUI.py 导入 MainWindow 主窗口类
from GUI.MainGUI import MainWindow


def main():
    """GUI 启动流程：创建应用与主窗口并进入事件循环"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()