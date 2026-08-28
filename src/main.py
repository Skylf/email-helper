# -*- coding: utf-8 -*-
# 程序主入口
# 作者：LF
# 创建时间：2026-08-23
# 功能：作为整个邮件助手程序的入口，负责启动 GUI 主程序。
#       普通模式 / 高级模式（后续）的界面与流程均从 MainGUI 的主窗口进入，
#       本文件只承载「创建应用 -> 显示主窗口 -> 进入事件循环」的主流程，
#       具体界面类集中在 src/GUI/MainGUI.py（api），流程层见 src/GUI/runTest.py。

import sys

from PyQt6.QtCore import QTimer, Qt, QRect
from PyQt6.QtGui import QColor, QFont, QPixmap, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QSplashScreen
from path_manager import PathManager

# 统一通过 PathManager 定位源码包根目录（开发=src，打包=_MEIPASS），
# 追加到 sys.path，保证「GUI」「Email」「option」「logger」等包在两种环境下都能被导入。
sys.path.insert(0, str(PathManager.source_root()))

# 日志系统：在导入业务模块之前初始化，使后续所有模块都能直接使用日志
from logger import setupLogging, getLogger
setupLogging()
log = getLogger(__name__)


def createSplash():
    """创建启动闪屏（程序化绘制，无需额外图片资源）

    目的：双击 exe 后让用户第一时间看到「正在加载」反馈，
          避免 PyQt6 / 业务模块加载期黑屏，误以为没点到图标。

    返回：
        QSplashScreen：未 show 的闪屏对象
    """
    # 画布尺寸：适中的横版，顶部主标题、中部副标题
    w, h = 460, 240
    pix = QPixmap(w, h)
    # 主品牌色底（与顶部栏 #1b7bf2 一致）
    pix.fill(QColor(27, 123, 242))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 主标题（加粗白字）
    title_font = QFont('Microsoft YaHei', 18)
    title_font.setBold(True)
    p.setFont(title_font)
    p.setPen(QPen(QColor(255, 255, 255)))
    p.drawText(QRect(0, 60, w, 48), Qt.AlignmentFlag.AlignCenter, 'Lhack 邮箱助手')

    # 副标题（浅色提示）
    sub_font = QFont('Microsoft YaHei', 10)
    p.setFont(sub_font)
    p.setPen(QPen(QColor(225, 239, 255)))
    p.drawText(QRect(0, 130, w, 30), Qt.AlignmentFlag.AlignCenter, '正在加载，请稍候…')
    p.end()
    return QSplashScreen(pix)


def main():
    """主流程：闪屏 -> 事件循环 -> 延迟加载主窗口 -> 进入事件循环

    说明：主窗口及其业务模块 import 较重，改为在事件循环跑起来后
          用单次定时器加载，从而让闪屏第一时间绘制出来，缩短无反馈期。
    调用位置：src/GUI/MainGUI.py 中的 MainWindow（主窗口类）
    """
    log.info('程序启动')
    # 创建应用实例，管理全局事件循环与资源
    app = QApplication(sys.argv)
    # 立即显示启动闪屏：双击后先给用户可见反馈
    splash = createSplash()
    splash.show()
    app.processEvents()
    log.info('启动闪屏已显示')

    def showMainWindow():
        """延迟加载主窗口：事件循环就绪后再导入，避免阻塞闪屏绘制"""
        # 延迟导入，让闪屏先画出来；业务模块加载时间被藏到闪屏之后
        from GUI.MainGUI import MainWindow
        # 创建并显示主窗口（含普通模式/高级模式入口页）
        window = MainWindow()
        window.show()
        # 主窗口就绪后关闭闪屏
        splash.finish(window)
        log.info('主窗口已显示，关闭闪屏')

    # 单次定时器：排队到当前事件循环处理完（闪屏已画出）后再加载主窗口
    QTimer.singleShot(0, showMainWindow)
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