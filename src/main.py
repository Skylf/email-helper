# -*- coding: utf-8 -*-
# 程序主入口
# 作者：LF
# 创建时间：2026-08-23
# 功能：作为整个邮件助手程序的入口，负责启动 GUI 主程序。
#       普通模式 / 高级模式（后续）的界面与流程均从 MainGUI 的主窗口进入，
#       本文件只承载「创建应用 -> 显示主窗口 -> 进入事件循环」的主流程，
#       具体界面类集中在 src/GUI/MainGUI.py（api），流程层见 src/GUI/runTest.py。

import sys

from PyQt6.QtWidgets import QApplication
from path_manager import PathManager

# 统一通过 PathManager 定位源码包根目录（开发=src，打包=_MEIPASS），
# 追加到 sys.path，保证「GUI」「Email」包在两种环境下都能被导入。
sys.path.insert(0, str(PathManager.source_root()))
# 另将项目根目录（source_root 的上一级）加入 sys.path，使项目根下的 option 设置包可被导入。
sys.path.insert(0, str(PathManager.source_root().parent))

# 日志系统：在导入业务模块之前初始化，使后续所有模块都能直接使用日志
from logger import setupLogging, getLogger
setupLogging()
log = getLogger(__name__)

from GUI.MainGUI import MainWindow


def main():
    """主流程：创建 QApplication、主窗口并进入事件循环

    调用位置：src/GUI/MainGUI.py 中的 MainWindow（主窗口类）
    """
    log.info('程序启动')
    # 创建应用实例，管理全局事件循环与资源
    app = QApplication(sys.argv)
    # 创建主窗口（含普通模式/高级模式入口页）
    window = MainWindow()
    # 显示主窗口
    window.show()
    log.info('主窗口已显示，进入事件循环')
    # 进入事件循环，直到窗口关闭后退出，并以返回值作为进程退出码
    ret = app.exec()
    log.info('程序退出，退出码: %s', ret)
    sys.exit(ret)


if __name__ == '__main__':
    try:
        # 启动 GUI 主程序
        main()
    except Exception as e:
        # 主流程异常兜底：记录错误日志并提示用户
        log.critical('程序崩溃: %s', e, exc_info=True)
        print(f"程序出错: {e}")
        # 发生异常时暂停，便于在终端查看错误信息而不闪退
        input("按 Enter 键退出...")