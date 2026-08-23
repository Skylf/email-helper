# -*- coding: utf-8 -*-
# GUI 主脚本
# 作者：LF
# 创建时间：2026-08-23
# 功能：基于 PyQt6 的邮件助手图形界面。
#       主窗口提供「普通模式」「高级模式」两个入口按钮，点击进入对应发信页面。
#       普通模式发信页仿照 QQ 邮箱网页版写邮件布局：
#         顶部操作栏（发送 / 预览 / 附件 ▼ / 发信设置）
#         → 收件人（可展开抄送/密送）→ 主题
#         → 两行富文本工具栏
#         → 正文大输入区 → 左下发件人选择
#       界面使用 PyQt6 默认样式（Windows 原生控件外观），不做额外美化。

import os
import re
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QAction, QColor, QFont, QImage, QPainter, QPen,
    QTextCursor, QTextDocument, QTextImageFormat, QTextListFormat,
)
from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QFontComboBox,
    QComboBox, QListWidget, QListWidgetItem, QFileDialog, QColorDialog, QMessageBox,
    QAbstractItemView, QMenu, QToolButton, QSizePolicy, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QDialog,
    QDateEdit,
)

# 跨文件调用说明：从 src/Email/NormalMode.py 导入 NormalMode 类，
# 由它统一编排参数并对接 LEmail 完成邮件发送（GUI 只负责收集界面输入，
# 不直接操作 LEmail，保证发送逻辑复用普通模式的上游处理）。
# GUI 与 Email 是同级顶层包（src 非包），跨包须用绝对导入；
# 其 sys.path 由启动脚本（main.py / runTest.py）经 PathManager.source_root()
# 统一注入，开发与打包环境均能正确定位。
from Email.NormalMode import NormalMode
# 复用本地配置加载的发信账号作为默认发件邮箱（config.local，不入库）
from Email.MainEmail import SMTP_USERNAME
from database import (
    getDb,
    CATEGORY_DRAFT,
    CATEGORY_SENT,
    CATEGORY_DELETED,
)
# UI 按钮响应之后的业务逻辑收敛在 activity 包中，界面层仅负责调用
from activity.recipient_bulk import (
    parseRecipientFile,
    mergeRecipients,
    sortRecipients,
    filterRecipients,
    splitRecipients,
    validateRecipients,
)
from activity.mail_query import queryEmails

# 发件人昵称默认值（发件人昵称输入框留空时使用）
DEFAULT_FROM_NAME = 'Lhack 邮箱助手'
# SMTP 默认发件邮箱地址：复用本地 config 中加载的发信账号；缺失时用示例占位
DEFAULT_FROM_EMAIL = SMTP_USERNAME or 'your-email@example.com'

# 字号下拉框候选字号列表（单位：磅）
FONT_SIZES = ['8', '9', '10', '11', '12', '14', '16', '18', '20', '24', '28', '32', '36', '48', '72']

# 主窗口左侧菜单：(id, 显示名)，用于左栏列表 + 选中态切换
# 说明：本项目只提供「发信」服务，不收邮件，故无「收件箱/星标/群邮件/记事本/垃圾箱」。
NAV_MENU_ITEMS = [
    ('drafts',    '草稿箱'),
    ('sent',      '已发送'),
    ('deleted',   '已删除'),
]

# 左侧菜单 id 与数据库分类常量映射（列表页读取 / 增写使用）
MENU_TO_CATEGORY = {
    'drafts':  CATEGORY_DRAFT,
    'sent':    CATEGORY_SENT,
    'deleted': CATEGORY_DELETED,
}

# 左栏菜单中可对应到邮件列表页的 id（其分类均有真实列表展示）
LIST_PAGE_MENUS = {'drafts', 'sent', 'deleted'}

# 「已删除」邮件保留天数：到期自动永久删除（默认 30 天）
DELETE_RETENTION_DAYS = 30


def parseEmails(text):
    """将逗号/分号/空白分隔的邮箱串拆分为去空后的列表

    参数：
        text<str>：用户输入的邮箱地址串（可含多个，用逗号/分号/空白分隔）

    返回：
        list：拆分去空后的邮箱地址列表
    """
    # 正则按逗号、分号、中文逗号/分号、空白拆分，并过滤空项
    return [part for part in re.split(r'[,;，；\s]+', text.strip()) if part]


class LoadingOverlay(QWidget):
    """发送中遮罩：半透明覆盖整个窗口，中心绘制旋转加载圆圈，下方显示提示文字

    通过 QTimer 驱动旋转角度，由于实际发送在 SendWorker 线程中执行，
    主线程事件循环保持空闲，转圈动画可正常刷新。
    """

    def __init__(self, parent, message='正在发送中...'):
        super().__init__(parent)
        # 遮罩背景半透明（设置为可样式化背景以便背景色生效）
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet('background-color: rgba(0, 0, 0, 80);')
        # 提示文字与加载圆圈相关参数
        self._message = message
        self._angle = 0
        # 定时器：定时更新旋转角度并触发重绘
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._rotate)
        # 默认隐藏
        self.hide()

    def _rotate(self):
        """定时器回调：旋转角度自增并触发重绘"""
        self._angle = (self._angle + 12) % 360
        self.update()

    def showLoading(self):
        """显示遮罩并覆盖父窗口全部区域，非阻塞式启动动画"""
        parent = self.parentWidget()
        if parent is not None:
            # 覆盖整个父窗口（顶层窗口）区域
            self.setGeometry(parent.rect())
            self.raise_()
        self.show()
        self._timer.start()

    def hideLoading(self):
        """隐藏遮罩并停止动画"""
        self._timer.stop()
        self.hide()

    def paintEvent(self, event):
        """自绘：半透明背景 + 中心旋转圆弧加载圈 + 下方文字"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 1. 绘制半透明遮罩背景
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
        center = self.rect().center()
        # 2. 绘制旋转加载圆环（缺口圆弧，模拟加载转圈）
        radius = 32
        ring_width = 6
        painter.setPen(QPen(QColor(255, 255, 255), ring_width,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(center.x() - radius, center.y() - radius,
                        radius * 2, radius * 2, self._angle * 16, 270 * 16)
        # 3. 在圆圈下方绘制提示文字
        font = painter.font()
        font.setPointSize(13)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(center.x(), center.y() + radius + 30, self._message)
        painter.end()


class SendWorker(QThread):
    """邮件发送工作线程：在后台执行 NormalMode 发送，避免阻塞 GUI 动画主线程

    通过信号将发送结果传回主线程。
    """

    # 发送完成信号：参数为是否发送成功
    finished_signal = pyqtSignal(bool)

    def __init__(self, normal_mode):
        super().__init__()
        # 持有普通模式对象（内含已配置好的 LEmail）
        self.normal_mode = normal_mode

    def run(self):
        """线程体：调用普通模式发送接口并发出结果信号"""
        result = self.normal_mode.send()
        self.finished_signal.emit(result)


class SearchDialog(QDialog):
    """邮件查询对话框：按 主题 / 收件人 / 发件人 / 时间范围 组合搜索

    提供四个筛选条件（均可留空=不限）：
      主题（标题模糊）、收件人、发件人、发送日期区间。
    暂不支持按正文内容搜索。确认后把条件回传给调用方执行查询。
    """

    def __init__(self, category_label, parent=None):
        """初始化查询对话框

        参数：
            category_label<str>：当前分类的中文名（仅提示用途）
            parent<QWidget|None>：父窗口
        """
        super().__init__(parent)
        self.setWindowTitle('查询邮件')
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        # 提示当前查询范围（当前分类）
        tip = QLabel('当前范围：%s（查询主题/收件人/发件人/发送日期，不含正文）' % category_label)
        tip.setStyleSheet('color:#666;')
        v.addWidget(tip)

        # 主题
        self.title_edit = QLineEdit()
        v.addLayout(self._labeledEdit('主题', self.title_edit))
        # 收件人
        self.recipient_edit = QLineEdit()
        v.addLayout(self._labeledEdit('收件人', self.recipient_edit))
        # 发件人
        self.sender_edit = QLineEdit()
        v.addLayout(self._labeledEdit('发件人', self.sender_edit))

        # 时间范围行（由复选框开启，关闭时不参与筛选）
        time_row = QHBoxLayout()
        self.date_check = QCheckBox('限定发送日期')
        self.date_check.toggled.connect(lambda on: self._toggleTimeRange(on))
        time_row.addWidget(self.date_check)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat('yyyy-MM-dd')
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat('yyyy-MM-dd')
        time_row.addWidget(self.date_from)
        time_row.addWidget(QLabel(' 至 '))
        time_row.addWidget(self.date_to)
        time_row.addStretch()
        v.addLayout(time_row)
        # 默认关闭时间范围（避免默认日期把结果筛空）
        self.date_check.setChecked(False)
        self._toggleTimeRange(False)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch()
        clear_btn = QPushButton('清空')
        clear_btn.clicked.connect(self.clearInputs)
        search_btn = QPushButton('查询')
        search_btn.setStyleSheet('QPushButton{background:#1b7bf2;color:#fff;border:0;'
                                 'padding:6px 20px;border-radius:4px;}')
        search_btn.clicked.connect(self.accept)
        btns.addWidget(clear_btn)
        btns.addWidget(search_btn)
        v.addLayout(btns)

    def _labeledEdit(self, label, edit):
        """构造一行「标签 + 输入框」的水平布局

        参数：
            label<str>：左侧标签文字
            edit<QLineEdit>：目标输入框（作为成员传回，取值/清空直接用成员）

        返回：
            QHBoxLayout：标签(定宽) + 输入框 的一行布局
        """
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setFixedWidth(70)
        row.addWidget(lab)
        row.addWidget(edit)
        return row

    def clearInputs(self):
        """清空全部查询条件"""
        self.title_edit.clear()
        self.recipient_edit.clear()
        self.sender_edit.clear()
        # 时间范围恢复默认关闭（避免残留过滤条件）
        self.date_check.setChecked(False)

    def _toggleTimeRange(self, enabled):
        """勾选「限定发送日期」时启用日期控件，否则禁用

        参数：
            enabled<bool>：是否启用日期范围筛选
        """
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)

    def collectConditions(self):
        """收集并返回查询条件（供 MainWindow 执行搜索用）

        返回：
            dict：含 title / recipient / sender / date_from / date_to
                  （date_from/date_to 仅在开启日期限定时有值，否则为 None）
        """
        ret = {
            'title': self.title_edit.text().strip(),
            'recipient': self.recipient_edit.text().strip(),
            'sender': self.sender_edit.text().strip(),
            'date_from': None,
            'date_to': None,
        }
        # 勾选日期限定才返回日期区间；否则不参与筛选，避免默认日期筛空结果
        if self.date_check.isChecked():
            ret['date_from'] = self.date_from.date().toString('yyyy-MM-dd')
            ret['date_to'] = self.date_to.date().toString('yyyy-MM-dd')
        return ret


class MainWindow(QMainWindow):
    """仿 QQ 邮箱网页版主窗口

    结构：[顶部栏: 标题 + 搜索框] | [左栏: 写信按钮 + 导航菜单] | [右栏: 列表/写信页堆叠]
    流程：点击「写信」→ 跳到 ComposeModePage（普通模式 / 高级模式 两按钮）
          → 选择模式 → 跳到具体发信页 → 发送成功后自动返回列表主页
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Lhack 邮箱助手')
        self.resize(1120, 720)
        # 全局数据库引用（邮件记录读写统一走此实例）
        self.db = getDb()

        # 中心容器：一个 QWidget 承载三栏布局；右栏内容用 QStackedWidget 管理多页切换
        center = QWidget()
        self.setCentralWidget(center)
        root = QVBoxLayout(center)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1) 顶部栏：左侧标题、右侧搜索框（查询用）
        root.addWidget(self.buildTopHeader())

        # 2) 主体：左栏（导航） + 右栏（内容堆叠）
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.buildLeftPane(), 0)   # 左栏：固定宽
        # 右栏堆叠容器（4 页：列表主页、模式选择页、普通发信页、高级模式占位页）
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)             # 右栏：占剩余空间
        root.addLayout(body, 1)

        # ---------- 堆叠页装配 ----------
        # 邮件列表主页（切换左侧菜单时复用同一页面，只更新标题与占位行）
        self.list_page = MailListPage(
            db=self.db,
            on_click_compose=self.showComposeModePage,
            on_click_view=self.onRequestView,
            on_click_edit=self.onRequestEdit,
            on_click_delete=self.onRequestDelete,
        )
        self.stack.addWidget(self.list_page)

        # 模式选择页（点写信后出现，展示普通/高级两个按钮）
        self.mode_page = ComposeModePage(
            on_click_normal=self.showNormalPage,
            on_click_high=self.showHighModePlaceholder,
            on_cancel=self.showListPage,
        )
        self.stack.addWidget(self.mode_page)

        # 普通模式发信页：返回动作切回列表主页；发送成功也自动回列表主页
        self.normal_page = NormalPage(db=self.db, on_back=self.showListPage)
        # 注入「恢复」回调（查看已删除时点「恢复」恢复回草稿箱）
        self.normal_page.setRestoreCallback(self.onRequestRestore)
        self.stack.addWidget(self.normal_page)

        # 高级模式占位页（开发中提示）
        self.high_page = HighModePlaceholderPage(on_back=self.showListPage)
        self.stack.addWidget(self.high_page)

        # 默认进入：列表主页 + 左栏默认选中「草稿箱」（本项目只发不收）
        self.setActiveNav('drafts')
        self.stack.setCurrentWidget(self.list_page)
        # 启动时清理已过期的「已删除」邮件（默认保留 30 天）
        self.db.deleteExpired(CATEGORY_DELETED, DELETE_RETENTION_DAYS)

    # ---------------- 顶部栏 ----------------
    def buildTopHeader(self):
        """顶部栏：左侧「Lhack 邮箱」标题、右侧查询输入框（UI 占位，搜索逻辑不做）"""
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.NoFrame)
        # 顶部栏轻背景（QQ邮箱深蓝风格）
        bar.setStyleSheet('QFrame{background:#1b7bf2; color:#fff;}'
                          'QLineEdit{background:#4a9af6; color:#fff; border:1px solid #3f8eee;'
                          'padding:4px 8px; border-radius:4px;}'
                          'QLineEdit::placeholder{color:#d9e8ff;}')
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(16)

        title = QLabel('Lhack 邮箱')
        tf = title.font(); tf.setPointSize(13); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet('color:#fff;')
        h.addWidget(title)
        h.addStretch()

        # 搜索框：回车触发查询
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('搜索邮件（需点击查询）')
        self.search_edit.setMinimumWidth(280)
        self.search_edit.returnPressed.connect(self.onSearch)
        search_btn = QPushButton('查询')
        search_btn.setStyleSheet('QPushButton{background:#fff;color:#1b7bf2;border:0;'
                                 'padding:4px 12px;border-radius:4px;font-weight:bold;}'
                                 'QPushButton:hover{background:#e6efff;}')
        search_btn.clicked.connect(self.onSearch)
        h.addWidget(self.search_edit)
        h.addWidget(search_btn)
        return bar

    def onSearch(self):
        """查询功能实装：弹出查询对话框，按主题/收件人/发件人/时间范围搜索并展示结果

        查询范围限定在当前选中的分类（草稿箱/已发送/已删除）；检索结果直接渲染进列表页。
        对话框内条件全部留空时同样执行（等价于列出该分类全部邮件）。
        """
        # 当前分类中文名（用于对话框提示范围）
        current_label = self._menuName(self._current_menu_id) or '全部'
        dlg = SearchDialog(current_label, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cond = dlg.collectConditions()
        category = MENU_TO_CATEGORY.get(self._current_menu_id)
        # 查询业务委托 activity 层执行（按当前分类 + 传入条件过滤）
        records = queryEmails(self.db, category, cond)
        # 用查询结果渲染列表页（标题后追加「搜索结果」说明当前处于检索模式）
        self.list_page.setTitle('%s（搜索结果 %d 条）' % (current_label, len(records)))
        self.list_page.showRecords(records)
        self.list_page.showTable(bool(records))
        # 处于检索模式时收藏线的「4:剩余暂存」对非已删除品类仍由 showRecords 归为 '-'
        self.stack.setCurrentWidget(self.list_page)

    # ---------------- 左栏 ----------------
    def buildLeftPane(self):
        """左栏：写信大按钮 + 导航列表（收件箱、星标、草稿箱、已发送等）"""
        pane = QFrame()
        pane.setFixedWidth(210)
        pane.setStyleSheet('QFrame{background:#f4f7fb; border-right:1px solid #e1e6ef;}'
                           'QPushButton#compose_btn{background:#1b7bf2; color:#fff;'
                           'border:0; padding:10px 16px; border-radius:6px; font-weight:bold;}'
                           'QPushButton#compose_btn:hover{background:#1567d0;}'
                           'QListWidget{background:transparent; border:0; padding:6px 4px;}'
                           'QListWidget::item{height:30px; padding-left:10px; border-radius:4px;}'
                           'QListWidget::item:selected{background:#dde9fb; color:#1b7bf2;'
                           'font-weight:bold;}')
        v = QVBoxLayout(pane)
        v.setContentsMargins(12, 16, 12, 12)
        v.setSpacing(8)

        # 写信按钮：点击跳到模式选择页（普通/高级）
        compose_btn = QPushButton('＋ 写 信')
        compose_btn.setObjectName('compose_btn')
        compose_btn.setMinimumHeight(40)
        compose_btn.clicked.connect(self.showComposeModePage)
        v.addWidget(compose_btn)

        v.addSpacing(6)

        # 导航菜单
        self.nav_list = QListWidget()
        for mid, mname in NAV_MENU_ITEMS:
            item = QListWidgetItem(mname)
            item.setData(Qt.ItemDataRole.UserRole, mid)
            self.nav_list.addItem(item)
        self.nav_list.setCurrentRow(0)
        self.nav_list.itemClicked.connect(self.onNavItemClicked)
        v.addWidget(self.nav_list, 1)

        v.addStretch()
        return pane

    def setActiveNav(self, menu_id):
        """按 id 设定当前选中的菜单项（高亮并同步列表页标题/数据）"""
        self._current_menu_id = menu_id
        for i in range(self.nav_list.count()):
            item = self.nav_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == menu_id:
                self.nav_list.setCurrentRow(i)
                break
        self._refreshListPageFor(menu_id)

    def onNavItemClicked(self, item):
        """左栏菜单点击：切换到列表主页并按当前菜单刷新标题/占位数据"""
        menu_id = item.data(Qt.ItemDataRole.UserRole)
        self.setActiveNav(menu_id)
        # 点菜单应从写信页回到列表主页
        self.stack.setCurrentWidget(self.list_page)

    def _menuName(self, menu_id):
        """根据菜单 id 取中文名称（用于列表页标题显示）"""
        for mid, mname in NAV_MENU_ITEMS:
            if mid == menu_id:
                return mname
        return ''

    def _refreshListPageFor(self, menu_id):
        """刷新 MailListPage：从数据库读取当前分类的真实邮件并展示

        参数：
            menu_id<str>：左侧菜单 id（drafts/sent/deleted）
        """
        title = self._menuName(menu_id) or '列表'
        # 依据当前菜单控制列表工具条按钮显隐（已删除隐藏删除/再次编辑）
        self.list_page.setCurrentMenu(menu_id)
        if menu_id in LIST_PAGE_MENUS:
            # 从数据库读取该分类下全部记录（时间倒序）
            category = MENU_TO_CATEGORY[menu_id]
            # 正在查看「已删除」时顺带清理过期记录（超过保留期的自动永久删除），
            # 保证应用长时间运行时 30 天清理机制仍生效
            if category == CATEGORY_DELETED:
                self.db.deleteExpired(CATEGORY_DELETED, DELETE_RETENTION_DAYS)
            records = self.db.getMails(category)
            self.list_page.setTitle(title)
            self.list_page.showRecords(records)
            self.list_page.showTable(bool(records))
        else:
            # 非列表菜单（本项目暂无）：显示空白占位提示
            self.list_page.setTitle(title)
            self.list_page.showRecords([])
            self.list_page.showTable(False, '该分类暂无邮件（占位）。')

    # ---------------- 列表：删除 / 再次编辑 实装 ----------------
    def onRequestView(self, mail_id):
        """查看：双击进入只读查看（不提供编辑/发送/删除），已删除可恢复

        参数：
            mail_id<int>：待查看的邮件记录 id
        """
        record = self.db.getMail(mail_id)
        if not record:
            QMessageBox.warning(self, '提示', '记录不存在或已被删除。')
            return
        # 以只读模式回填发信页（fillFromRecord 会先清空并记录来源分类）
        self.normal_page.fillFromRecord(record)
        # 记录当前查看的记录 id（供「恢复」回调回传）
        self.normal_page.view_record_id = mail_id
        # 已删除：进入只读查看模式（显示恢复）；其余只读查看
        self.normal_page.setViewMode(restorable=record['category'] == CATEGORY_DELETED)
        self.stack.setCurrentWidget(self.normal_page)

    def onRequestEdit(self, mail_id):
        """再次编辑：从数据库取回邮件记录，以可编辑模式回填发信页

        草稿箱/已发送可再次编辑；已删除不允许编辑（无此入口）。
        参数：
            mail_id<int>：待编辑的邮件记录 id
        """
        record = self.db.getMail(mail_id)
        if not record:
            QMessageBox.warning(self, '提示', '记录不存在或已被删除。')
            return
        # 已删除的邮件只允许查看/恢复，不允许再次编辑、发送
        if record['category'] == CATEGORY_DELETED:
            QMessageBox.information(self, '提示', '已删除的邮件不支持再次编辑，可恢复后编辑。')
            return
        # 以可编辑模式回填发信页（再次编辑：可发送；草稿箱不提供存草稿）
        self.normal_page.fillFromRecord(record)
        self.normal_page.setEditMode()
        self.normal_page.rememberRecordId(mail_id)
        self.stack.setCurrentWidget(self.normal_page)

    def onRequestRestore(self, mail_id):
        """恢复：把「已删除」记录恢复回「草稿箱」

        参数：
            mail_id<int>：待恢复记录 id
        """
        if mail_id is None:
            return
        self.db.moveToCategory(mail_id, CATEGORY_DRAFT)
        # 刷新当前（已删除）列表并返回
        self._refreshListPageFor(self._current_menu_id)
        QMessageBox.information(self, '恢复成功', '邮件已恢复到草稿箱。')
        self.showListPage()

    def onRequestDelete(self, mail_ids, permanent=False):
        """删除：常规删除将记录移入「已删除」；彻底删除(永久)直接物理删除

        参数：
            mail_ids<list<int>>：待删除的记录 id 列表
            permanent<bool>：True=彻底删除(永久删除，物理删库)；False=移到已删除
        """
        if not mail_ids:
            return
        if permanent:
            # 彻底删除：物理删除数据库记录（不可恢复）
            self.db.deleteMails(mail_ids)
            self._refreshListPageFor(self._current_menu_id)
            QMessageBox.information(self, '彻底删除', '已永久删除 %d 封邮件。' % len(mail_ids))
            return
        # 常规删除：草稿/已发送 → 移入「已删除」
        for mid in mail_ids:
            self.db.moveToCategory(mid, CATEGORY_DELETED)
        # 刷新当前列表
        self._refreshListPageFor(self._current_menu_id)
        QMessageBox.information(self, '删除成功', '已删除 %d 封邮件。' % len(mail_ids))

    # ---------------- 堆叠页切换 ----------------
    def showListPage(self):
        """返回列表主页（发信完成或取消/返回后调用）

        返回时自动刷新当前菜单的列表数据，确保发送成功/存草稿等页面操作
        的改动立即可见，无需用户重新进入该分类。
        """
        # 回到列表前先从数据库重读当前分类的数据（发送/存草稿后内容已变化）
        self._refreshListPageFor(self._current_menu_id)
        self.stack.setCurrentWidget(self.list_page)

    def showComposeModePage(self):
        """点「写信」→ 显示模式选择页（普通模式/高级模式）"""
        self.stack.setCurrentWidget(self.mode_page)

    def showNormalPage(self):
        """选择模式 → 普通模式发信页（新建写信：重置为空白的写信状态）"""
        # 新写信：先清空上次编辑残留（主题/正文/收件人等），再进入写信模式
        self.normal_page.clearForm()
        self.normal_page.setWriteMode()
        # 写信新邮件：清空已编辑记录标记，使「存草稿/发送」走新建逻辑
        self.normal_page.rememberRecordId(None)
        self.stack.setCurrentWidget(self.normal_page)

    def showHighModePlaceholder(self):
        """选择模式 → 高级模式占位页（开发中）"""
        self.stack.setCurrentWidget(self.high_page)


class ComposeModePage(QWidget):
    """写信模式选择页：「普通模式 / 高级模式」两按钮

    用户在主窗口点「写信」先跳到本页，选完模式后才进入具体发信页。
    取消按钮可直接返回列表主页。
    """

    def __init__(self, on_click_normal, on_click_high, on_cancel):
        super().__init__()
        self.on_click_normal = on_click_normal
        self.on_click_high = on_click_high
        self.on_cancel = on_cancel
        self.buildUi()

    def buildUi(self):
        """居中布局：标题 + 两模式卡片大按钮 + 取消按钮"""
        outer = QVBoxLayout(self)
        outer.addStretch()
        wrap = QVBoxLayout()
        outer.addLayout(wrap)
        wrap.setSpacing(18)

        # 标题说明
        title = QLabel('选择写信模式')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tf = title.font(); tf.setPointSize(18); tf.setBold(True); title.setFont(tf)
        tip = QLabel('普通模式：一对一常规写信。\n高级模式：一次性配置，向多人发送差异化内容与附件（开发中）。')
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet('color:#666;')
        wrap.addWidget(title); wrap.addWidget(tip)

        # 两模式按钮行
        row = QHBoxLayout(); row.setSpacing(24)
        row.addStretch()
        normal_btn = QPushButton('普通模式')
        normal_btn.setMinimumSize(200, 96)
        normal_btn.setStyleSheet('QPushButton{background:#1b7bf2;color:#fff;border:0;'
                                 'border-radius:8px;font-size:16px;font-weight:bold;}'
                                 'QPushButton:hover{background:#1567d0;}')
        normal_btn.clicked.connect(self.on_click_normal)
        high_btn = QPushButton('高级模式')
        high_btn.setMinimumSize(200, 96)
        high_btn.setStyleSheet('QPushButton{background:#fff;color:#1b7bf2;border:2px solid #1b7bf2;'
                               'border-radius:8px;font-size:16px;font-weight:bold;}'
                               'QPushButton:hover{background:#e6efff;}')
        high_btn.clicked.connect(self.on_click_high)
        row.addWidget(normal_btn); row.addWidget(high_btn)
        row.addStretch()
        wrap.addLayout(row)

        # 取消返回
        cancel_row = QHBoxLayout(); cancel_row.addStretch()
        cancel_btn = QPushButton('返回')
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.on_cancel)
        cancel_row.addWidget(cancel_btn)
        cancel_row.addStretch()
        wrap.addLayout(cancel_row)
        outer.addStretch()


class HighModePlaceholderPage(QWidget):
    """高级模式占位页：UI 提示开发中，提供返回按钮

    本类只提供 UI；功能逻辑（批量差异化发送）后续补。
    """

    def __init__(self, on_back):
        super().__init__()
        self.on_back = on_back
        v = QVBoxLayout(self); v.addStretch()
        tip = QLabel('高级模式（批量差异化发送）\n开发中，敬请期待。')
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tf = tip.font(); tf.setPointSize(18); tip.setFont(tf)
        tip.setStyleSheet('color:#555;')
        v.addWidget(tip); v.addSpacing(24)
        row = QHBoxLayout(); row.addStretch()
        btn = QPushButton('返回邮件列表')
        btn.setMinimumWidth(140); btn.setMinimumHeight(36)
        btn.clicked.connect(self.on_back)
        row.addWidget(btn); row.addStretch(); v.addLayout(row); v.addStretch()


class MarqueeLabel(QWidget):
    """跑马灯提示条：显示一行循环滚动的提示文字（如已删除保留提示）

    用法：newMarquee = MarqueeLabel(widget) → setText(...) → 通过 show/hide 控制显隐。
    文字超过可视宽度时自动左移循环滚动；不足则静止居中显示。
    """

    # 滚动速度：每 40ms 移动 1 像素
    SCROLL_INTERVAL_MS = 40
    SCROLL_STEP_PX = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        # 提示文字（存放待滚动内容）
        self.text = ''
        # 当前滚动位移（负数表示向左偏移）
        self.offset = 0
        # 是否处于滚动状态（文字宽度 > 可视宽度时为真）
        self.scrolling = False
        # 定时器：驱动滚动动画
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advanceScroll)
        # 默认样式：浅黄提示底色 + 深灰文字
        self.setStyleSheet(
            'QWidget{background:#fff8e1; border:1px solid #ffe082; border-radius:4px;}'
        )

    def setText(self, text):
        """设置跑马灯内容并重算滚动状态

        参数：
            text<str>：要展示的提示文字
        """
        self.text = text or ''
        # 文字变化后重置滚动位置，便于重头开始
        self.offset = 0
        self._updateScrolling()
        self.update()

    def refreshMetrics(self):
        """在窗口大小变化时重算是否需要滚动（防止宽度变化后状态失效）"""
        self._updateScrolling()
        self.update()

    def _updateScrolling(self):
        """根据可视宽度与文字宽度判断是否开启滚动，并启停定时器"""
        fm = self.fontMetrics()
        text_width = fm.horizontalAdvance(self.text) if self.text else 0
        view_width = self.width()
        # 文字宽度大于可视宽度才需要滚动
        needs = text_width > view_width > 0
        if needs and not self.scrolling:
            self.scrolling = True
            self.timer.start(self.SCROLL_INTERVAL_MS)
        elif not needs and self.scrolling:
            self.scrolling = False
            self.timer.stop()
            self.offset = 0

    def advanceScroll(self):
        """定时器回调：每次向左推进一点，滚完全程后回到起点重来"""
        fm = self.fontMetrics()
        text_width = fm.horizontalAdvance(self.text)
        view_width = self.width()
        # 向左累计位移；到达「文字完全滚出（-text_width）」后复位
        self.offset -= self.SCROLL_STEP_PX
        min_offset = -text_width
        if self.offset <= min_offset:
            self.offset = 0
        # 为避免空白停顿，右端距可视区留一定间距
        _ = view_width
        self.update()

    def paintEvent(self, event):
        """自绘滚动文字：按当前 offset 平移绘制，超出可视区部分被裁剪"""
        painter = QPainter(self)
        # 定义文字颜色
        col = QColor('#8a6d3b')
        painter.setPen(col)
        fm = self.fontMetrics()
        view_width = self.width()
        height = self.height()
        text_width = fm.horizontalAdvance(self.text) if self.text else 0
        ty = (height - fm.ascent() - fm.descent()) / 2 + fm.ascent()
        if not self.scrolling:
            # 文字不超宽：居中静止显示
            tx = (view_width - text_width) / 2.0
        else:
            # 滚动：把文字沿 X 轴平移（负 offset 向左滚），再叠加一个周期的副本实现无缝循环
            tx = float(self.offset)
            painter.drawText(QRectF(tx + view_width, ty - fm.ascent(),
                                    text_width, fm.height()), self.text)
        # 绘制主文本（滚动时加副本实现无缝循环）
        painter.drawText(QRectF(tx, ty - fm.ascent(), text_width, fm.height()), self.text)
        painter.end()

    def resizeEvent(self, event):
        """窗口尺寸变化后重新评估滚动状态"""
        super().resizeEvent(event)
        self.refreshMetrics()


class MailListPage(QWidget):
    """邮件列表页：标题 + 工具条（写信 / 转发 / 更多 / 删除 / 再次编辑） + 列表表格

    本页只做 UI 展示与动作信号触发，不含真实数据查询/删除/再次编辑逻辑。
    工具栏/右键/列表均发出信号，由 MainWindow 接收并做占位弹窗。
    """

    def __init__(self, db, on_click_compose, on_click_view, on_click_edit, on_click_delete):
        super().__init__()
        # 数据库引用（用于删除/恢复时移动分类，列表展示数据由 MainWindow 从库读取后传入）
        self.db = db
        # 四个外部回调：写信、查看、再次编辑、删除
        self.on_click_compose = on_click_compose
        self.on_click_view = on_click_view
        self.on_click_edit = on_click_edit
        self.on_click_delete = on_click_delete
        # 当前列表展示的邮件记录（dict 列表，含 id 字段）
        self.records = []
        # 与表格行一一对应的记录 id 列表（删除/再次编辑时回传 id）
        self.mail_ids = []
        self.buildUi()

    def buildUi(self):
        """列表页整体布局：标题 → 工具条 → 表格列表（或占位提示）"""
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 16)
        v.setSpacing(8)

        # 1) 跑马灯提示条（仅「已删除」页面显示，提示保留 30 天自动清理）
        self.marquee = MarqueeLabel(self)
        self.marquee.setText('已删除邮件可在本页暂存 30 天，30 天到期后将自动清理，请及时处理。')
        self.marquee.setFixedHeight(26)
        # 默认隐藏（setCurrentMenu 根据菜单决定是否显示）
        self.marquee.hide()
        v.addWidget(self.marquee)

        # 2) 标题 + 统计文字
        self.title_label = QLabel('草稿箱')
        tf = self.title_label.font(); tf.setPointSize(16); tf.setBold(True)
        self.title_label.setFont(tf)
        self.count_label = QLabel('共 0 封邮件')
        self.count_label.setStyleSheet('color:#666;')
        title_row = QHBoxLayout()
        title_row.addWidget(self.title_label); title_row.addSpacing(8)
        title_row.addWidget(self.count_label); title_row.addStretch()
        v.addLayout(title_row)

        # 2) 工具条：写信/转发/更多/删除/再次编辑
        v.addWidget(self.buildToolbar())

        # 3) 表格 / 占位提示容器
        self.table_container = QStackedWidget()
        v.addWidget(self.table_container, 1)

        # A：邮件表格（0 复选框 / 1 主题 / 2 收件人 / 3 时间 / 4 剩余暂存(仅已删除)）
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['', '主题', '收件人/发件人', '时间', '剩余暂存'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 32)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(2, 320)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 160)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.onTableContextMenu)
        self.table.doubleClicked.connect(self.onTableDoubleClickEdit)
        self.table_container.addWidget(self.table)

        # B：占位提示
        self.placeholder = QLabel('该分类暂无邮件（占位）。')
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet('color:#888; font-size:14px;')
        self.table_container.addWidget(self.placeholder)

    def buildToolbar(self):
        """构建列表工具条（写信/转发/更多/删除/再次编辑）"""
        tb = QFrame()
        tb.setStyleSheet('QFrame{background:#fff; border-bottom:1px solid #e1e6ef;}'
                         'QPushButton{padding:5px 14px; border:1px solid #d0d7e2;'
                         'border-radius:4px; background:#fff;}'
                         'QPushButton:hover{background:#f0f5fd;}')
        h = QHBoxLayout(tb)
        h.setContentsMargins(4, 6, 4, 6)
        h.setSpacing(6)

        def mk_button(text, slot, color='#333', bg='#fff'):
            b = QPushButton(text)
            if bg != '#fff' or color != '#333':
                b.setStyleSheet('QPushButton{background:%s;color:%s;border:0;border-radius:4px;'
                                'padding:5px 14px;} QPushButton:hover{opacity:0.9;}' % (bg, color))
            b.clicked.connect(slot)
            return b

        h.addWidget(mk_button('写 信',      self.on_click_compose, '#fff', '#1b7bf2'))
        # 转发/更多按钮存为成员：只在非「已删除」页面显示（已删除页面改为「彻底删除」）
        self.forward_tool_btn = mk_button('转 发(占)', self._placeholderForward)
        h.addWidget(self.forward_tool_btn)
        self.more_tool_btn = mk_button('更 多(占)', self._placeholderMore)
        h.addWidget(self.more_tool_btn)
        h.addSpacing(12)
        # 删除按钮存为成员，供已删除分类下隐藏（已删除只查看+恢复+彻底删除）
        self.delete_tool_btn = mk_button('删 除', self.onToolbarDelete, '#c0392b', '#fdecea')
        h.addWidget(self.delete_tool_btn)
        # 再次编辑按钮存为成员，供已删除分类下隐藏（已删除不支持再次编辑）
        self.edit_tool_btn = mk_button('再次编辑', self.onToolbarEdit, '#1b7bf2', '#e6efff')
        h.addWidget(self.edit_tool_btn)
        # 彻底删除按钮（永久删除）：仅已删除页面显示，删除前弹窗确认
        self.permanent_delete_btn = mk_button('彻底删除', self.onPermanentDelete, '#c0392b', '#fdecea')
        h.addWidget(self.permanent_delete_btn)
        h.addStretch()
        return tb

    def setCurrentMenu(self, menu_id):
        """记录当前菜单并控制工具条按钮显隐：
        已删除→隐藏 转发/更多/删除/再次编辑，显示「彻底删除」；其余反向。
        参数：
            menu_id<str>：当前左侧菜单 id
        """
        # 判断是否已删除页面
        is_deleted = (menu_id == 'deleted')
        # 写信总是显示；转发/更多在已删除隐藏
        self.forward_tool_btn.setVisible(not is_deleted)
        self.more_tool_btn.setVisible(not is_deleted)
        # 常规「删除」「再次编辑」在已删除隐藏
        self.edit_tool_btn.setVisible(not is_deleted)
        self.delete_tool_btn.setVisible(not is_deleted)
        # 「彻底删除」仅已删除显示
        self.permanent_delete_btn.setVisible(is_deleted)
        # 跑马灯提示条：仅已删除页面显示（提示 30 天自动清理）
        self.marquee.setVisible(is_deleted)

    def setTitle(self, title):
        """设置列表页顶部标题（由 MainWindow 在切换菜单时调用）"""
        self.title_label.setText(title)

    def showRecords(self, records):
        """用数据库邮件记录填充表格（真实数据展示）

        参数：
            records<list<dict>>：一条条邮件记录，需含 id/title/recipient/send_time
        """
        self.records = list(records)
        # 记录与行一一对应的 id，供删除/再次编辑回调回传
        self.mail_ids = [r.get('id') for r in self.records]
        self.table.setRowCount(len(self.records))
        for r_idx, rec in enumerate(self.records):
            # 第 0 列：复选框（用于批量删除）
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(r_idx, 0, check_item)
            # 1:主题 2:收件人 3:时间（取数据库字段）
            row_vals = (rec.get('title', ''), rec.get('recipient', ''), rec.get('send_time', ''))
            for c_idx, val in enumerate(row_vals, start=1):
                item = QTableWidgetItem(str(val))
                if c_idx == 1:
                    # 主题列字体稍粗，增强可读性
                    f = item.font(); f.setBold(True); item.setFont(f)
                self.table.setItem(r_idx, c_idx, item)
            # 4:剩余暂存天数（仅已删除记录展示，其余分类为「-」）
            is_deleted_rec = rec.get('category') == CATEGORY_DELETED
            remain_text = self.formatRemainText(rec) if is_deleted_rec else '-'
            remain_item = QTableWidgetItem(remain_text)
            # 若即将清理，用暖色提示引起注意
            remain_item.setForeground(QColor('#c0392b') if is_deleted_rec and self._isAlmostGone(rec) else QColor('#333'))
            self.table.setItem(r_idx, 4, remain_item)
        self.count_label.setText('共 %d 封邮件' % len(self.records))

    def formatRemainText(self, rec):
        """计算单条邮件「剩余暂存」的可读文本（基于进入已删除的时间）

        以 deleted_at（进入已删除的时间，精确到分、秒为 00）加保留天数得到清理时刻，
        与当前时间相减得到剩余时长（精确到分，秒显示为 :00）。

        参数：
            rec<dict>：单条邮件记录（需含 deleted_at / send_time）

        返回：
            str：如「2天 05:00:00」；无时间或异常返回「-」
        """
        try:
            # 优先用进入已删除的时间；旧数据无 deleted_at 时退化为发送时间
            anchor = (rec.get('deleted_at') or '').strip() or (rec.get('send_time') or '').strip()
            if not anchor:
                return '-'
            # 解析进入时间（兼容到秒/到分两种格式）
            anchor_dt = datetime.strptime(anchor, '%Y-%m-%d %H:%M:%S')
            clear_dt = anchor_dt + timedelta(days=DELETE_RETENTION_DAYS)
            now = datetime.now()
            remain = clear_dt - now
            # 已到期或已过期：提示立即清理
            if remain.total_seconds() <= 0:
                return '已到期，将自动清理'
            # 剩余时长精确到分：去掉秒，秒显示为 00
            total_min = int(remain.total_seconds()) // 60
            days = total_min // (24 * 60)
            hours = (total_min % (24 * 60)) // 60
            minutes = total_min % 60
            return '%d天 %02d:%02d:00' % (days, hours, minutes)
        except (ValueError, TypeError):
            return '-'

    def _isAlmostGone(self, rec):
        """判断某邮件是否临近清理（剩余不足 1 天，用于暖色高亮）

        参数：
            rec<dict>：单条邮件记录

        返回：
            bool：True 表示剩余不足 1 天，即将被自动清理
        """
        try:
            anchor = (rec.get('deleted_at') or '').strip() or (rec.get('send_time') or '').strip()
            if not anchor:
                return False
            anchor_dt = datetime.strptime(anchor, '%Y-%m-%d %H:%M:%S')
            remain = (anchor_dt + timedelta(days=DELETE_RETENTION_DAYS)) - datetime.now()
            return 0 < remain.total_seconds() <= 24 * 3600
        except (ValueError, TypeError):
            return False

    def showTable(self, show, placeholder_text='该分类暂无邮件（占位）。'):
        """切换显示：表格 / 占位提示"""
        if show:
            self.table_container.setCurrentWidget(self.table)
        else:
            self.placeholder.setText(placeholder_text)
            self.table_container.setCurrentWidget(self.placeholder)

    # --------- UI 动作（删除 / 再次编辑 / 右键菜单 / 占位） ---------
    def _checkedRowIndices(self):
        """收集勾选复选框或行选中的行号集合（用于删除时汇总待处理行）"""
        indices = set()
        for r_idx in range(self.table.rowCount()):
            chk = self.table.item(r_idx, 0)
            if chk is not None and chk.checkState() == Qt.CheckState.Checked:
                indices.add(r_idx)
        # 若未勾选任何行，退回使用选中行
        if not indices:
            for idx in self.table.selectionModel().selectedRows():
                indices.add(idx.row())
        return sorted(indices)

    def onPermanentDelete(self):
        """彻底删除：永久删除选中邮件；删除前弹窗二次确认（不可恢复）"""
        indices = self._checkedRowIndices()
        if not indices:
            QMessageBox.information(self, '提示', '请先勾选或选中需要彻底删除的邮件。')
            return
        # 将行号映射为记录 id + 主题（用于确认提示）
        ids = [self.mail_ids[i] for i in indices if i < len(self.mail_ids)]
        if not ids:
            return
        first_title = ''
        first = indices[0]
        if first < len(self.records):
            first_title = self.records[first].get('title', '')
        # 删除前弹窗确认：永久删除不可恢复
        tip = '将永久删除 %d 封邮件' % len(ids) if len(ids) > 1 else '将永久删除该邮件'
        if first_title:
            tip += '\n「%s」' % first_title
        tip += '\n\n永久删除后不可恢复，确定继续吗？'
        result = QMessageBox.question(
            self, '彻底删除确认', tip,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if result != QMessageBox.StandardButton.Yes:
            return
        # 确认后回调 MainWindow 物理删除并刷新
        self.on_click_delete(ids, permanent=True)

    def onToolbarDelete(self):
        """工具条删除：收集选中行对应的记录 id，回调外部 on_click_delete"""
        indices = self._checkedRowIndices()
        if not indices:
            QMessageBox.information(self, '提示', '请先勾选或选中需要删除的行。')
            return
        # 将行号映射为记录 id 列表
        ids = [self.mail_ids[i] for i in indices if i < len(self.mail_ids)]
        self.on_click_delete(ids)

    def onToolbarEdit(self):
        """工具条再次编辑：对第一条选中的记录发起再次编辑"""
        indices = self._checkedRowIndices()
        if not indices:
            sel = self.table.currentRow()
            indices = [sel] if sel >= 0 else []
        if not indices:
            QMessageBox.information(self, '提示', '请先选中一行邮件。')
            return
        first = indices[0]
        if first >= len(self.mail_ids):
            return
        # 回传该记录的 id
        self.on_click_edit(self.mail_ids[first])

    def onTableContextMenu(self, pos):
        """列表右键菜单：删除 / 再次编辑（操作真实邮件记录）"""
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        mail_id = self.mail_ids[row] if row < len(self.mail_ids) else None
        if mail_id is None:
            return
        menu = QMenu(self)
        act_edit = QAction('再次编辑', self)
        act_delete = QAction('删除', self)
        menu.addAction(act_edit)
        menu.addAction(act_delete)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_edit:
            self.on_click_edit(mail_id)
        elif chosen == act_delete:
            self.on_click_delete([mail_id])

    def onTableDoubleClickEdit(self, model_index):
        """列表双击：作为「查看」快捷入口（只读，不进入编辑）"""
        row = model_index.row()
        mail_id = self.mail_ids[row] if row < len(self.mail_ids) else None
        if mail_id is not None:
            self.on_click_view(mail_id)

    @staticmethod
    def _placeholderForward():
        """转发按钮（占位）：不实现功能逻辑，仅弹窗"""
        QMessageBox.information(None, '提示', '转发功能开发中。')

    @staticmethod
    def _placeholderMore():
        """更多按钮（占位）：不实现功能逻辑，仅弹窗"""
        QMessageBox.information(None, '提示', '更多功能开发中。')


class RecipientPickerDialog(QDialog):
    """收件人选择器（群发功能）：选择收件人 Excel/TXT 文件并让用户勾选收件人

    UI 能力：
      - 「选择文件」按钮弹出文件对话框（*.xlsx / *.xls / *.txt）
      - 收件人以可勾选的列表展示，支持 全选 / 取消全选
      - 按首字母排序（A-Z，忽略大小写）
      - 关键字搜索：输入字符即时筛选出包含该字符的邮箱
      - 底部显示「已勾选 N / 共 M」
      - 确定后返回勾选的收件人邮箱列表

    说明：文件识别、排序、过滤等业务逻辑均收敛在 activity.recipient_bulk，
          本类仅负责界面交互与调用。
    """

    def __init__(self, parent=None):
        """初始化收件人选择器对话框"""
        super().__init__(parent)
        self.setWindowTitle('收件人选择（群发）')
        self.resize(420, 520)
        # 当前已识别出的全部收件人列表（字符串邮箱，保持解析顺序）
        self.all_recipients = []
        # 已勾选的邮箱集合（跨排序/筛选切换时保持勾选状态）
        self.selected_emails = set()
        # 当前排序开关：True=按首字母；False=原始顺序
        self.sort_by_letter = False

        v = QVBoxLayout(self)
        v.setSpacing(8)

        # 顶部说明 + 「选择文件」按钮
        top = QHBoxLayout()
        tip = QLabel('选择收件人 Excel 或 TXT 文件（文件内只含收件人邮箱）')
        tip.setStyleSheet('color:#666;')
        top.addWidget(tip)
        top.addStretch()
        pick_btn = QPushButton('选择文件')
        pick_btn.setStyleSheet('QPushButton{background:#1b7bf2;color:#fff;border:0;'
                               'padding:5px 14px;border-radius:4px;}')
        pick_btn.clicked.connect(self.onPickFile)
        top.addWidget(pick_btn)
        v.addLayout(top)

        # 排序 + 搜索工具栏
        tool_row = QHBoxLayout()
        sort_label = QLabel('排序:')
        tool_row.addWidget(sort_label)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem('原始顺序', False)
        self.sort_combo.addItem('按首字母 A-Z', True)
        self.sort_combo.currentIndexChanged.connect(self._onSortChanged)
        tool_row.addWidget(self.sort_combo)
        tool_row.addSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('输入字符筛选邮箱…')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._onSearchChanged)
        tool_row.addWidget(self.search_edit, 1)
        v.addLayout(tool_row)

        # 收件人可勾选列表
        self.recipient_list = QListWidget()
        self.recipient_list.itemChanged.connect(self._onItemToggled)
        v.addWidget(self.recipient_list)

        # 全选 / 取消全选
        op_row = QHBoxLayout()
        self.select_all_btn = QPushButton('全选')
        self.select_all_btn.clicked.connect(lambda: self._setAllChecked(True))
        self.clear_all_btn = QPushButton('取消全选')
        self.clear_all_btn.clicked.connect(lambda: self._setAllChecked(False))
        op_row.addWidget(self.select_all_btn)
        op_row.addWidget(self.clear_all_btn)
        op_row.addStretch()
        self.count_label = QLabel('已勾选 0 / 共 0')
        op_row.addWidget(self.count_label)
        v.addLayout(op_row)

        # 确定 / 取消
        bottom = QHBoxLayout()
        bottom.addStretch()
        confirm_btn = QPushButton('确定')
        confirm_btn.setStyleSheet('QPushButton{background:#1b7bf2;color:#fff;border:0;'
                                  'padding:6px 20px;border-radius:4px;}')
        confirm_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(confirm_btn)
        bottom.addWidget(cancel_btn)
        v.addLayout(bottom)

        # 启用列表为空时的按钮态保护
        self._updateButtons()
        self._updateCount()

    # ---------------- 文件选择（解析逻辑为占位） ----------------

    def onPickFile(self):
        """弹出文件对话框选择收件人文件（Excel/TXT），随后解析并展示收件人

        解析由 activity.recipient_bulk 提供，识别出的收件人填充为可勾选列表。
        """
        path, _ = QFileDialog.getOpenFileName(
            self, '选择收件人文件', '',
            '收件人文件 (*.xlsx *.xls *.txt);;所有文件 (*)')
        if not path:
            return
        # 解析收件人（业务逻辑在 activity 层）；文件类型不支持、解析依赖缺失等均在
        # 此处兜底捕获并提示，避免在 modal 对话框事件循环里抛裸异常导致程序崩溃
        try:
            recipients = self._loadRecipientsFromFile(path)
        except (ValueError, ImportError) as exc:
            QMessageBox.warning(self, '解析失败', str(exc))
            return
        self.setRecipients(recipients)

    def _loadRecipientsFromFile(self, path):
        """从文件读取并识别收件人（业务逻辑委托给 activity.recipient_bulk 实现）

        参数：
            path<str>：选中的收件人文件路径（xlsx/xls/txt）

        返回：
            list<str>：识别出的收件人邮箱列表（去重、保持顺序）
        """
        # 委托 activity 层解析；文件类型不支持等异常由调用方（onPickFile）统一处理
        return parseRecipientFile(path)

    def setRecipients(self, recipients):
        """用识别出的收件人填充列表（默认全部勾选），并重置排序/搜索为原始

        参数：
            recipients<list<str>>：收件人邮箱列表
        """
        self.all_recipients = list(recipients or [])
        # 初次载入：默认全选（清空旧的勾选记录并全部勾选）
        self.selected_emails = set(self.all_recipients)
        # 重置排序与搜索状态
        self.sort_by_letter = False
        self._setComboSilent(0)
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._renderList()

    def _setComboSilent(self, index):
        """不触发回调地切换排序下拉的选中项

        参数：
            index<int>：目标下拉索引
        """
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(index)
        self.sort_combo.blockSignals(False)

    # ---------------- 排序 / 搜索 ----------------

    def _onSortChanged(self, index):
        """排序下拉变化：记录排序开关后按当前状态重渲染列表"""
        self.sort_by_letter = bool(self.sort_combo.itemData(index))
        self._renderList()

    def _onSearchChanged(self, text):
        """搜索框文本变化：按关键字即时筛选并重渲染列表"""
        self._renderList()

    def _renderList(self):
        """按 排序 + 搜索 当前状态重渲染可勾选列表（保持已勾选状态）

        数据流：all_recipients →(activity.filterRecipients 按关键字)→(activity.sortRecipients 按字母)→ 展示
        """
        # 屏蔽 itemChanged 避免重填过程触发计数刷新（计数在填完后统一更新）
        self.recipient_list.itemChanged.disconnect(self._onItemToggled)
        self.recipient_list.clear()

        # 先按关键字过滤（业务逻辑在 activity），再按需排序（业务逻辑在 activity）
        filtered = filterRecipients(self.all_recipients, self.search_edit.text())
        ordered = sortRecipients(filtered, self.sort_by_letter)
        for email in ordered:
            item = QListWidgetItem(email)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if email in self.selected_emails
                else Qt.CheckState.Unchecked)
            self._addRecipientItem(item)

        self.recipient_list.itemChanged.connect(self._onItemToggled)
        self._updateCount()
        self._updateButtons()

    def _addRecipientItem(self, item):
        """把单个收件人条目加入列表（供不同重填路径复用）"""
        self.recipient_list.addItem(item)

    # ---------------- 勾选状态管理 ----------------

    def _onItemToggled(self, item):
        """列表项勾选状态变化：同步到勾选集合并刷新计数"""
        email = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            self.selected_emails.add(email)
        else:
            self.selected_emails.discard(email)
        self._updateCount()

    def _setAllChecked(self, checked):
        """全选或取消全选（更新勾选集合并对当前列表逐项设置勾选态）
        注意：仅作用于当前可见（筛选后）的列表项。

        参数：
            checked<bool>：True 全选，False 取消全选
        """
        for i in range(self.recipient_list.count()):
            item = self.recipient_list.item(i)
            if checked:
                self.selected_emails.add(item.text())
                item.setCheckState(Qt.CheckState.Checked)
            else:
                self.selected_emails.discard(item.text())
                item.setCheckState(Qt.CheckState.Unchecked)
        self._updateCount()

    def _checkedRecipients(self):
        """返回当前全部已勾选收件人（所有已勾选集合，含被筛选隐藏的）"""
        return sorted(self.selected_emails, key=lambda e: e.lower())

    def getSelectedRecipients(self):
        """供外部读取最终勾选的收件人（确定后调用）

        返回：
            list<str>：勾选的收件人邮箱列表
        """
        return self._checkedRecipients()

    def _updateCount(self):
        """刷新「已勾选 / 共」计数文案

        显示值：已勾选数 / 当前(筛选后可见)列表条数，便于用户感知筛选效果。
        """
        total = self.recipient_list.count()
        checked = len(self.selected_emails)
        self.count_label.setText('已勾选 %d / 共 %d' % (checked, total))

    def _updateButtons(self):
        """按列表是否为空启用/禁用 全选 与 取消全选 按钮"""
        has_items = self.recipient_list.count() > 0
        self.select_all_btn.setEnabled(has_items)
        self.clear_all_btn.setEnabled(has_items)


class RecipientManageDialog(QDialog):
    """查看/管理所有收件人对话框：应对收件人过多时输入框显示不全的问题

    与输入框维护「同一个」收件人集合：
      - 打开时从输入框文本即时拆分（activity.splitRecipients），保证列表与输入框一致；
      - 支持排序、搜索、全选/取消、逐项勾选取消；
      - 非法片段（用户手误删除字符导致）在列表中标红展示；
      - 确定后把仍勾选的结果回写输入框（activity 层拼接），从而：
          输入框里删掉的内容不会残留到列表；列表里取消勾选的内容也不会残留到输入框。

    业务逻辑（拆分/校验/排序/过滤/拼接）均收敛在 activity.recipient_bulk。
    """

    def __init__(self, parent=None):
        """初始化查看/管理收件人对话框"""
        super().__init__(parent)
        self.setWindowTitle('查看所有收件人')
        self.resize(440, 520)
        # 输入框拆分出的全部片段（含非法项，保持顺序）
        self.all_tokens = []
        # 非法片段集合（标红用）：手误导致的不完整邮箱
        self.invalid_set = set()
        # 仍勾选的片段集合（跨排序/筛选保持）
        self.selected_items = set()

        v = QVBoxLayout(self)
        v.setSpacing(8)

        # 顶部提示
        tip = QLabel('以下为收件人输入框中的所有收件人，可勾选/取消，确定后回写输入框。')
        tip.setStyleSheet('color:#666;')
        tip.setWordWrap(True)
        v.addWidget(tip)

        # 排序 + 搜索工具栏
        tool_row = QHBoxLayout()
        self.sort_combo = QComboBox()
        self.sort_combo.addItem('原始顺序', False)
        self.sort_combo.addItem('按首字母 A-Z', True)
        self.sort_combo.currentIndexChanged.connect(self._renderList)
        tool_row.addWidget(QLabel('排序:'))
        tool_row.addWidget(self.sort_combo)
        tool_row.addSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('输入字符筛选邮箱…')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._renderList)
        tool_row.addWidget(self.search_edit, 1)
        v.addLayout(tool_row)

        # 可勾选列表
        self.recipient_list = QListWidget()
        self.recipient_list.itemChanged.connect(self._onItemToggled)
        v.addWidget(self.recipient_list)

        # 全选 / 取消全选
        op_row = QHBoxLayout()
        self.select_all_btn = QPushButton('全选')
        self.select_all_btn.clicked.connect(lambda: self._setAllChecked(True))
        self.clear_all_btn = QPushButton('取消全选')
        self.clear_all_btn.clicked.connect(lambda: self._setAllChecked(False))
        op_row.addWidget(self.select_all_btn)
        op_row.addWidget(self.clear_all_btn)
        op_row.addStretch()
        self.count_label = QLabel('已勾选 0 / 共 0')
        op_row.addWidget(self.count_label)
        v.addLayout(op_row)

        # 确定 / 取消
        bottom = QHBoxLayout()
        bottom.addStretch()
        confirm_btn = QPushButton('确定')
        confirm_btn.setStyleSheet('QPushButton{background:#1b7bf2;color:#fff;border:0;'
                                  'padding:6px 20px;border-radius:4px;}')
        confirm_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(confirm_btn)
        bottom.addWidget(cancel_btn)
        v.addLayout(bottom)

        self._updateButtons()

    # ---------------- 数据填充 —— 与输入框保持同一集合 ----------------

    def loadFromText(self, text):
        """从输入框文本载入收件人（即时拆分）并默认全选，标记非法项

        参数：
            text<str>：输入框当前文本
        """
        self.all_tokens = splitRecipients(text)
        valid, invalid = validateRecipients(self.all_tokens)
        self.invalid_set = set(invalid)
        # 默认全选（包含非法项也默认勾选，便于用户自行取消）
        self.selected_items = set(self.all_tokens)
        # 重置排序/搜索
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.blockSignals(False)
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._renderList()

    # ---------------- 展示 ----------------

    def _renderList(self):
        """按 排序 + 搜索 重渲染列表（非法项标红，保持勾选状态）"""
        self.recipient_list.itemChanged.disconnect(self._onItemToggled)
        self.recipient_list.clear()

        keyword = self.search_edit.text()
        kw = keyword.strip().lower()
        # 过滤 + 排序（业务逻辑在 activity）
        pool = [t for t in self.all_tokens if t.lower().find(kw) >= 0] if kw else list(self.all_tokens)
        if self.sort_combo.currentData():
            pool = sortRecipients(pool, by_letter=True)
        for tok in pool:
            item = QListWidgetItem(tok)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if tok in self.selected_items
                               else Qt.CheckState.Unchecked)
            # 非法片段标红提示
            if tok in self.invalid_set:
                item.setForeground(QColor('#d93025'))  # 红色
            self.recipient_list.addItem(item)

        self.recipient_list.itemChanged.connect(self._onItemToggled)
        self._updateCount()
        self._updateButtons()

    # ---------------- 勾选状态管理 ----------------

    def _onItemToggled(self, item):
        """勾选变化：同步勾选集合，刷新计数"""
        tok = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            self.selected_items.add(tok)
        else:
            self.selected_items.discard(tok)
        self._updateCount()

    def _setAllChecked(self, checked):
        """全选/取消全选（作用于当前筛选后可见项）"""
        for i in range(self.recipient_list.count()):
            item = self.recipient_list.item(i)
            if checked:
                self.selected_items.add(item.text())
                item.setCheckState(Qt.CheckState.Checked)
            else:
                self.selected_items.discard(item.text())
                item.setCheckState(Qt.CheckState.Unchecked)
        self._updateCount()

    def getCheckedText(self):
        """返回确定时回写输入框用的拼接文本（按当前勾选、去重、分号分隔）

        返回：
            str：回写文本；无勾选项时为空串
        """
        # 按原始顺序保留勾选项；用 activity.mergeRecipients 风格拼接（分号）
        return '; '.join(t for t in self.all_tokens if t in self.selected_items)

    def hasInvalid(self):
        """是否存在非法邮箱（供打开时弹窗提示）

        返回：
            list<str>：非法片段列表
        """
        return sorted(self.invalid_set, key=lambda s: s.lower())

    def _updateCount(self):
        """刷新计数文案（已勾选/当前可见）"""
        total = self.recipient_list.count()
        checked = len(self.selected_items)
        self.count_label.setText('已勾选 %d / 共 %d' % (checked, total))

    def _updateButtons(self):
        """列表为空时禁用全选/取消全选"""
        has_items = self.recipient_list.count() > 0
        self.select_all_btn.setEnabled(has_items)
        self.clear_all_btn.setEnabled(has_items)


class NormalPage(QWidget):
    """普通模式发信页：仿 QQ 邮箱网页版写邮件界面

    包含：
      顶部操作栏（返回、发送、预览、附件菜单、设置菜单）
      收件人（可点抄送/密送展开，分别发送）
      主题行
      两行富文本工具栏 + 正文大输入区
      左下发件人显示
    """

    def __init__(self, db, on_back):
        super().__init__()
        # 数据库引用（发送成功写「已发送」、保存草稿写「草稿箱」时使用）
        self.db = db
        # 返回首页的回调函数
        self.on_back = on_back
        # 当前正在编辑的邮件记录 id（再次编辑进入时非空；新建写信为 None）
        self.editing_id = None
        # 当前编辑来源分类（draft/sent/deleted）：写已发送时据此判断「更新原记录 vs 新增」
        self.edit_category = None
        # 恢复回调（查看已删除时点击「恢复」触发，由 MainWindow 注入）
        self.restore_callback = None
        # 查看模式时需记住的记录 id（供恢复回传）
        self.view_record_id = None
        # 附件完整路径列表（列表控件中只显示文件名）
        self.attachment_paths = []
        # html 内嵌图片映射 {content_id: 文件路径}（正文以 cid:content_id 引用，
        # 发送时交给 LEmail 按映射构建 related，确保引用与 Content-ID 一致）
        self.inline_image_paths = {}
        # 已占用的 content-id 名称集合（保证多个图片的 cid 唯一）
        self._used_image_names = set()
        self.buildUi()

    def buildUi(self):
        """按照 QQ 邮箱网页版布局构建发信页整体结构"""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(6)

        # 1. 顶部操作栏（仿照截图最上方一排：返回 | 发送 预览 附件▼ 设置▼）
        root.addLayout(self.buildTopBar())

        # 2. 收件人区（收件人 + 右侧抄送/密送/分别发送可点展开）
        root.addLayout(self.buildRecipientArea())

        # 3. 主题行
        root.addLayout(self.buildTitleRow())

        # 先创建正文编辑器（工具栏槽函数需要引用它）
        self.body_editor = QTextEdit()
        self.body_editor.setAcceptRichText(True)
        self.body_editor.setPlaceholderText('输入正文')

        # 4. 富文本工具栏（两行：第一行是插入型工具，第二行是格式型工具）
        root.addWidget(self.buildToolbarRow1())
        root.addWidget(self.buildToolbarRow2())

        # 5. 正文编辑器（拉伸填充剩余空间）
        root.addWidget(self.body_editor, 1)

        # 6. 附件区（默认折叠，点击「附件」添加后展开）
        self.attachment_area = self.buildAttachmentArea()
        self.attachment_area.setVisible(False)
        root.addWidget(self.attachment_area)

        # 7. 底部：左下发件人
        root.addLayout(self.buildSenderRow())

    # ---------------- 顶部操作栏 ----------------

    def buildTopBar(self):
        """构建顶部操作栏：返回 / 发送 / 预览 / 附件▼ / 发信设置▼

        返回：
            QHBoxLayout：顶部按钮行布局
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        # 返回按钮
        self.back_btn = QPushButton('返回')
        self.back_btn.clicked.connect(self.on_back)
        row.addWidget(self.back_btn)

        # 存草稿按钮：仅把当前填写内容写入「草稿箱」，不发信（编辑草稿/查看模式隐藏）
        draft_btn = QPushButton('存草稿')
        draft_btn.setMinimumHeight(34)
        draft_btn.clicked.connect(self.onSaveDraft)
        row.addWidget(draft_btn)
        # 供 setWriteMode/setEditMode/setEditDraftMode 等控制显隐：存草稿按钮
        self.draft_btn = draft_btn

        # 恢复按钮：仅「已删除」只读查看时显示，点击恢复回草稿箱
        self.restore_btn = QPushButton('恢复')
        self.restore_btn.setMinimumHeight(34)
        # 恢复按钮的槽函数由 MainWindow 通过 setRestoreCallback 注入（需携带记录 id）
        self.restore_btn.setVisible(False)
        row.addWidget(self.restore_btn)

        row.addSpacing(12)

        # 发送按钮（主操作）
        send_btn = QPushButton('发送')
        send_btn.setMinimumHeight(34)
        send_btn.setMinimumWidth(90)
        send_btn.clicked.connect(self.onSend)
        row.addWidget(send_btn)
        # 供各模式切换显隐：发送按钮
        self.send_btn = send_btn
        # 预览按钮
        preview_btn = QPushButton('预览')
        preview_btn.setMinimumHeight(34)
        preview_btn.clicked.connect(self.onPreview)
        row.addWidget(preview_btn)
        # 供各模式切换显隐：预览按钮
        self.preview_btn = preview_btn

        # 附件▼ 按钮（下拉菜单：添加附件 / 删除附件）
        attach_menu_btn = QToolButton()
        attach_menu_btn.setText('附件▼')
        attach_menu_btn.setMinimumHeight(34)
        attach_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # 供查看模式隐藏：附件下拉按钮
        self.attach_menu_btn = attach_menu_btn
        attach_menu = QMenu(self)
        # 菜单项：添加附件
        add_attach_action = QAction('添加附件…', self)
        add_attach_action.triggered.connect(self.onAddAttachment)
        attach_menu.addAction(add_attach_action)
        # 菜单项：删除选中附件
        remove_attach_action = QAction('删除选中附件', self)
        remove_attach_action.triggered.connect(self.onRemoveAttachment)
        attach_menu.addAction(remove_attach_action)
        # 菜单项：清空所有附件
        clear_attach_action = QAction('清空全部附件', self)
        clear_attach_action.triggered.connect(self.onClearAttachments)
        attach_menu.addAction(clear_attach_action)
        attach_menu_btn.setMenu(attach_menu)
        row.addWidget(attach_menu_btn)

        # 发信设置▼ 按钮（下拉菜单：回信地址 / 退信地址 / 分别发送等）
        setting_menu_btn = QToolButton()
        setting_menu_btn.setText('发信设置▼')
        setting_menu_btn.setMinimumHeight(34)
        setting_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # 供查看模式隐藏：设置下拉按钮
        self.setting_menu_btn = setting_menu_btn
        setting_menu = QMenu(self)
        # 回信地址（对话框输入）
        reply_to_action = QAction('设置回信地址…', self)
        reply_to_action.triggered.connect(self.onSetReplyTo)
        setting_menu.addAction(reply_to_action)
        # 退信地址（对话框输入）
        return_email_action = QAction('设置退信地址…', self)
        return_email_action.triggered.connect(self.onSetReturnEmail)
        setting_menu.addAction(return_email_action)
        setting_menu.addSeparator()
        # 「分别发送」复选（作为可勾选菜单项）
        self.separate_send_action = QAction('分别发送（每人独立一封）', self)
        self.separate_send_action.setCheckable(True)
        self.separate_send_action.setChecked(False)
        setting_menu.addAction(self.separate_send_action)
        setting_menu_btn.setMenu(setting_menu)
        row.addWidget(setting_menu_btn)

        row.addStretch()
        return row

    # ---------------- 收件人区 ----------------

    def buildRecipientArea(self):
        """构建收件人区：左「收件人 ⊕」输入框，右侧「抄送 密送 分别发送」可点切换显隐

        返回：
            QVBoxLayout：收件人区整体布局
        """
        wrap_layout = QVBoxLayout()
        wrap_layout.setSpacing(4)

        # 第一行：收件人标签 + 输入框 + 右侧（抄送/密送/分别发送 链接）
        row1 = QHBoxLayout()
        # 收件人标签（带加号，蓝色视觉）
        to_label = QLabel('收件人  ⊕')
        to_label.setStyleSheet('color:#1a73e8;')
        row1.addWidget(to_label)
        # 收件人输入框
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText('多个收件人用逗号或分号分隔')
        self.to_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row1.addWidget(self.to_edit, 1)
        # 群发收件人选择按钮：打开收件人选择器（批量勾选后可回填到收件人框）
        self.pick_recipient_btn = QPushButton('收件人选择')
        self.pick_recipient_btn.setToolTip('从 Excel/TXT 批量导入收件人并勾选')
        self.pick_recipient_btn.setStyleSheet('QPushButton{background:#f5f7fa;color:#1a73e8;'
                                              'border:1px solid #d0d7de;padding:4px 10px;'
                                              'border-radius:4px;}'
                                              'QPushButton:hover{background:#e6efff;}')
        self.pick_recipient_btn.clicked.connect(self.onPickRecipients)
        row1.addWidget(self.pick_recipient_btn)
        # 查看所有收件人按钮：收件人过多输入框显示不全时，打开管理对话框查看/勾选
        self.manage_recipient_btn = QPushButton('查看所有收件人')
        self.manage_recipient_btn.setToolTip('收件人过多时查看/勾选管理，确定后回写输入框')
        self.manage_recipient_btn.setStyleSheet('QPushButton{background:#f5f7fa;color:#1a73e8;'
                                                'border:1px solid #d0d7de;padding:4px 10px;'
                                                'border-radius:4px;}'
                                                'QPushButton:hover{background:#e6efff;}')
        self.manage_recipient_btn.clicked.connect(self.onManageRecipients)
        row1.addWidget(self.manage_recipient_btn)
        # 右侧可点击「抄送」「密送」「分别发送」标签
        self.cc_link = QLabel('<a href="#" style="text-decoration:none;color:#666;">抄送</a>')
        self.cc_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.cc_link.linkActivated.connect(self.toggleCcArea)
        row1.addWidget(self.cc_link)
        self.bcc_link = QLabel('<a href="#" style="text-decoration:none;color:#666;">密送</a>')
        self.bcc_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.bcc_link.linkActivated.connect(self.toggleBccArea)
        row1.addWidget(self.bcc_link)
        # 分别发送勾选框
        self.separate_checkbox = QCheckBox('分别发送')
        self.separate_checkbox.stateChanged.connect(lambda s: self.separate_send_action.setChecked(bool(s)))
        row1.addWidget(self.separate_checkbox)
        wrap_layout.addLayout(row1)

        # 抄送行（默认隐藏，点「抄送」展开）
        self.cc_row_widget = QWidget()
        cc_row = QHBoxLayout(self.cc_row_widget)
        cc_row.setContentsMargins(0, 0, 0, 0)
        cc_label = QLabel('抄  送')
        cc_label.setMinimumWidth(70)
        cc_row.addWidget(cc_label)
        self.cc_edit = QLineEdit()
        self.cc_edit.setPlaceholderText('可空，多个用逗号/分号分隔')
        cc_row.addWidget(self.cc_edit, 1)
        self.cc_row_widget.setVisible(False)
        wrap_layout.addWidget(self.cc_row_widget)

        # 密送行（默认隐藏，点「密送」展开）
        self.bcc_row_widget = QWidget()
        bcc_row = QHBoxLayout(self.bcc_row_widget)
        bcc_row.setContentsMargins(0, 0, 0, 0)
        bcc_label = QLabel('密  送')
        bcc_label.setMinimumWidth(70)
        bcc_row.addWidget(bcc_label)
        self.bcc_edit = QLineEdit()
        self.bcc_edit.setPlaceholderText('可空，多个用逗号/分号分隔')
        bcc_row.addWidget(self.bcc_edit, 1)
        self.bcc_row_widget.setVisible(False)
        wrap_layout.addWidget(self.bcc_row_widget)

        # 回信 / 退信地址行（默认隐藏，在设置菜单中设定后可见）
        self.reply_row_widget = QWidget()
        reply_row = QHBoxLayout(self.reply_row_widget)
        reply_row.setContentsMargins(0, 0, 0, 0)
        reply_label = QLabel('回  信')
        reply_label.setMinimumWidth(70)
        reply_row.addWidget(reply_label)
        self.reply_edit = QLineEdit()
        self.reply_edit.setPlaceholderText('收件人回复时发送到这里')
        reply_row.addWidget(self.reply_edit, 1)
        self.reply_row_widget.setVisible(False)
        wrap_layout.addWidget(self.reply_row_widget)

        self.return_row_widget = QWidget()
        return_row = QHBoxLayout(self.return_row_widget)
        return_row.setContentsMargins(0, 0, 0, 0)
        return_label = QLabel('退  信')
        return_label.setMinimumWidth(70)
        return_row.addWidget(return_label)
        self.return_edit = QLineEdit()
        self.return_edit.setPlaceholderText('投递失败时退信到这里')
        return_row.addWidget(self.return_edit, 1)
        self.return_row_widget.setVisible(False)
        wrap_layout.addWidget(self.return_row_widget)

        return wrap_layout

    def onPickRecipients(self):
        """打开收件人选择器，确定后把勾选的收件人回填到收件人输入框

        选择器支持从 Excel/TXT 批量导入（解析在 activity 层）；
        确定后把勾选结果委托 activity.mergeRecipients 合并回填（去重、滤空）。
        """
        dlg = RecipientPickerDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.getSelectedRecipients()
        if not selected:
            return
        # 合并业务委托 activity 层：保留已有 + 新增勾选（去重、滤空），分号分隔
        self.to_edit.setText(mergeRecipients(self.to_edit.text(), selected))

    def onManageRecipients(self):
        """打开「查看所有收件人」对话框管理当前收件人，确定后回写输入框

        与输入框维护同一收件人集合：
          - 打开时从输入框文本即时拆分（activity.splitRecipients），保证列表一致；
          - 存在非法邮箱时弹窗提示并标红；
          - 确定后仅把仍勾选的结果回写输入框，从而列表取消项不会残留、
            输入框删除项也不会残留到列表。
        """
        text = self.to_edit.text().strip()
        if not text:
            QMessageBox.information(self, '查看所有收件人', '收件人框当前为空，无需管理。')
            return
        dlg = RecipientManageDialog(self)
        dlg.loadFromText(text)
        # 检测到非法邮箱时弹窗提示用户（输入框可能因手误删出非法字符）
        invalid = dlg.hasInvalid()
        if invalid:
            QMessageBox.warning(
                self, '存在非法邮箱',
                '检测到 %d 个非法收件人（已标红）：\n%s\n\n确定后仍会保留它们，'
                '请在列表取消勾选或回到输入框修正。'
                % (len(invalid), '\n'.join('- ' + s for s in invalid)))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # 回写仍勾选的结果（单一数据源仍是输入框，避免双向不一致）
        result = dlg.getCheckedText()
        self.to_edit.setText(result)

    def toggleCcArea(self):
        """切换抄送输入行的显示/隐藏"""
        visible = self.cc_row_widget.isVisible()
        self.cc_row_widget.setVisible(not visible)
        # 展开后把焦点放到输入框，方便直接输入
        if not visible:
            self.cc_edit.setFocus()

    def toggleBccArea(self):
        """切换密送输入行的显示/隐藏"""
        visible = self.bcc_row_widget.isVisible()
        self.bcc_row_widget.setVisible(not visible)
        if not visible:
            self.bcc_edit.setFocus()

    def onSetReplyTo(self):
        """通过「发信设置」菜单打开回信地址输入对话框，填入后展开回信行"""
        text, ok = self.inputDialogSingleLine('设置回信地址', '收件人回复时发送到该邮箱：')
        if ok and text.strip():
            self.reply_edit.setText(text.strip())
            self.reply_row_widget.setVisible(True)

    def onSetReturnEmail(self):
        """通过「发信设置」菜单打开退信地址输入对话框，填入后展开退信行"""
        text, ok = self.inputDialogSingleLine('设置退信地址', '投递失败时退信到该邮箱：')
        if ok and text.strip():
            self.return_edit.setText(text.strip())
            self.return_row_widget.setVisible(True)

    def inputDialogSingleLine(self, title, prompt):
        """简易单行输入对话框（避免额外依赖 QInputDialog 时不可用的情况，这里使用 PyQt6 自带 QInputDialog）

        参数：
            title<str>：对话框标题
            prompt<str>：提示文字

        返回：
            tuple(str, bool)：(用户输入文本, 是否确认)
        """
        # 局部导入避免顶层依赖
        from PyQt6.QtWidgets import QInputDialog
        result, ok = QInputDialog.getText(self, title, prompt)
        return result, ok

    # ---------------- 主题行 ----------------

    def buildTitleRow(self):
        """构建主题行：「主 题」标签 + 输入框（整行宽度）

        返回：
            QHBoxLayout：主题行布局
        """
        row = QHBoxLayout()
        label = QLabel('主  题')
        label.setMinimumWidth(70)
        row.addWidget(label)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText('邮件主题')
        row.addWidget(self.title_edit, 1)
        return row

    # ---------------- 富文本工具栏 ----------------

    def buildToolbarRow1(self):
        """工具栏第一行：撤销/重做 / 图片 / 插入▼ / 签名▼ … （仿照截图第一排：AI润色/图片/插入/导入文档/日程/更多/签名）

        返回：
            QWidget：工具栏组件
        """
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 撤销
        undo_btn = QToolButton()
        undo_btn.setText('↺ 撤销')
        undo_btn.clicked.connect(self.body_editor.undo)
        layout.addWidget(undo_btn)
        # 重做
        redo_btn = QToolButton()
        redo_btn.setText('↻ 重做')
        redo_btn.clicked.connect(self.body_editor.redo)
        layout.addWidget(redo_btn)

        layout.addSpacing(8)

        # 图片按钮
        image_btn = QToolButton()
        image_btn.setText('图片')
        image_btn.clicked.connect(self.onInsertImage)
        layout.addWidget(image_btn)

        # 超链接按钮（便捷插入可下载的链接文字，用于大附件走网盘分享的场景）
        link_btn = QToolButton()
        link_btn.setText('超链接')
        link_btn.clicked.connect(self.onInsertLink)
        layout.addWidget(link_btn)

        # 插入▼（水平线 / HTML 片段）
        insert_menu_btn = QToolButton()
        insert_menu_btn.setText('插入▼')
        insert_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        insert_menu = QMenu(self)
        hr_action = QAction('水平线', self)
        hr_action.triggered.connect(self.onInsertHr)
        insert_menu.addAction(hr_action)
        link_action = QAction('超链接…', self)
        link_action.triggered.connect(self.onInsertLink)
        insert_menu.addAction(link_action)
        insert_menu_btn.setMenu(insert_menu)
        layout.addWidget(insert_menu_btn)

        # 签名▼
        sign_menu_btn = QToolButton()
        sign_menu_btn.setText('签名▼')
        sign_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sign_menu = QMenu(self)
        default_sign_action = QAction('默认签名', self)
        default_sign_action.triggered.connect(self.onInsertDefaultSignature)
        sign_menu.addAction(default_sign_action)
        clear_sign_action = QAction('清空默认签名', self)
        clear_sign_action.triggered.connect(self.onClearSignature)
        sign_menu.addAction(clear_sign_action)
        sign_menu_btn.setMenu(sign_menu)
        layout.addWidget(sign_menu_btn)

        layout.addStretch()
        return bar

    def buildToolbarRow2(self):
        """工具栏第二行：字体 / 字号 / 粗体 斜体 下划线 删除线 / 字色 / 背景色 / 对齐 / 列表 … （仿照截图第二排：格式刷/字体/字号/B/I/U/S/字色/背景色/对齐/列表…）

        返回：
            QWidget：工具栏组件
        """
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 字体下拉
        layout.addWidget(QLabel('字体'))
        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(False)
        self.font_combo.currentFontChanged.connect(self.onFontFamilyChanged)
        layout.addWidget(self.font_combo)

        # 字号下拉
        layout.addWidget(QLabel('字号'))
        self.size_combo = QComboBox()
        self.size_combo.addItems(FONT_SIZES)
        self.size_combo.setCurrentText('12')
        self.size_combo.currentTextChanged.connect(self.onFontSizeChanged)
        layout.addWidget(self.size_combo)

        # 粗体（可切换）
        self.bold_btn = QToolButton()
        self.bold_btn.setText('B')
        self.bold_btn.setCheckable(True)
        self.bold_btn.clicked.connect(self.onBold)
        bold_font = self.bold_btn.font()
        bold_font.setBold(True)
        self.bold_btn.setFont(bold_font)
        layout.addWidget(self.bold_btn)
        # 斜体
        self.italic_btn = QToolButton()
        self.italic_btn.setText('I')
        self.italic_btn.setCheckable(True)
        self.italic_btn.clicked.connect(self.onItalic)
        italic_font = self.italic_btn.font()
        italic_font.setItalic(True)
        self.italic_btn.setFont(italic_font)
        layout.addWidget(self.italic_btn)
        # 下划线
        self.underline_btn = QToolButton()
        self.underline_btn.setText('U')
        self.underline_btn.setCheckable(True)
        self.underline_btn.clicked.connect(self.onUnderline)
        underline_font = self.underline_btn.font()
        underline_font.setUnderline(True)
        self.underline_btn.setFont(underline_font)
        layout.addWidget(self.underline_btn)
        # 删除线
        self.strike_btn = QToolButton()
        self.strike_btn.setText('S')
        self.strike_btn.setCheckable(True)
        self.strike_btn.clicked.connect(self.onStrikeOut)
        strike_font = self.strike_btn.font()
        strike_font.setStrikeOut(True)
        self.strike_btn.setFont(strike_font)
        layout.addWidget(self.strike_btn)

        # 字色
        color_btn = QToolButton()
        color_btn.setText('A▼')
        color_btn.clicked.connect(self.onTextColor)
        layout.addWidget(color_btn)

        # 背景色
        bg_color_btn = QToolButton()
        bg_color_btn.setText('✎▼')
        bg_color_btn.clicked.connect(self.onTextBgColor)
        layout.addWidget(bg_color_btn)

        layout.addSpacing(6)

        # 对齐按钮组
        align_left_btn = QToolButton()
        align_left_btn.setText('左')
        align_left_btn.clicked.connect(self.onAlignLeft)
        layout.addWidget(align_left_btn)
        align_center_btn = QToolButton()
        align_center_btn.setText('中')
        align_center_btn.clicked.connect(self.onAlignCenter)
        layout.addWidget(align_center_btn)
        align_right_btn = QToolButton()
        align_right_btn.setText('右')
        align_right_btn.clicked.connect(self.onAlignRight)
        layout.addWidget(align_right_btn)

        layout.addSpacing(6)

        # 项目符号 / 编号列表
        bullet_btn = QToolButton()
        bullet_btn.setText('• 列表')
        bullet_btn.clicked.connect(self.onBulletList)
        layout.addWidget(bullet_btn)
        numbered_btn = QToolButton()
        numbered_btn.setText('1. 编号')
        numbered_btn.clicked.connect(self.onNumberedList)
        layout.addWidget(numbered_btn)

        layout.addStretch()
        return bar

    # ---------------- 附件区 ----------------

    def buildAttachmentArea(self):
        """构建附件区（列表 + 标签标题）

        返回：
            QWidget：附件区组件
        """
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addWidget(QLabel('附件：'))
        head.addStretch()
        count_label = QLabel()
        self.attachment_count_label = count_label
        head.addWidget(count_label)
        layout.addLayout(head)
        self.attachment_list = QListWidget()
        self.attachment_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.attachment_list.setMaximumHeight(100)
        layout.addWidget(self.attachment_list)
        return area

    def updateAttachmentHeader(self):
        """更新附件区标题的数量显示，并根据是否有附件切换显示/隐藏"""
        count = len(self.attachment_paths)
        self.attachment_count_label.setText('共 %d 个' % count)
        # 有附件时显示附件区；没有时隐藏
        self.attachment_area.setVisible(count > 0)

    # ---------------- 底部发件人行 ----------------

    def buildSenderRow(self):
        """构建底部发件人显示行

        返回：
            QHBoxLayout：发件人行布局
        """
        row = QHBoxLayout()
        label = QLabel('发件人：')
        label.setStyleSheet('color:#666;')
        row.addWidget(label)
        # 发件人昵称（可编辑，模仿 QQ 邮箱「昵称 <邮箱>」）
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText(DEFAULT_FROM_NAME)
        self.from_edit.setMaximumWidth(260)
        row.addWidget(self.from_edit)
        # 邮箱地址（只读，阿里云账号默认发件箱）
        self.from_email_label = QLabel('&lt;%s&gt;' % DEFAULT_FROM_EMAIL)
        self.from_email_label.setStyleSheet('color:#666;')
        row.addWidget(self.from_email_label)
        row.addStretch()
        return row

    # ---------------- 预览 ----------------

    def onPreview(self):
        """预览当前邮件：弹出一个只读对话框展示 HTML 正文"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle('邮件预览（HTML）')
        msg_box.setIcon(QMessageBox.Icon.Information)
        # 展示主题 + 收件人 + HTML 正文
        header = '<h3>主题：%s</h3>' % (self.title_edit.text() or '(无主题)')
        header += '<p><b>收件人：</b>%s</p>' % (self.to_edit.text() or '(空)')
        if self.cc_edit.isVisible() and self.cc_edit.text():
            header += '<p><b>抄送：</b>%s</p>' % self.cc_edit.text()
        html = self.body_editor.toHtml()
        msg_box.setText(header + '<hr>' + html)
        msg_box.exec()

    # ---------------- 富文本编辑槽函数 ----------------

    def onFontFamilyChanged(self, font):
        """字体下拉变更：应用到正文当前选择及后续输入"""
        self.body_editor.setFontFamily(font.family())

    def onFontSizeChanged(self, text):
        """字号下拉变更：应用到正文当前选择及后续输入"""
        if text:
            self.body_editor.setFontPointSize(float(text))

    def onBold(self):
        """切换加粗状态（根据当前字体权重判断）"""
        bold_value = QFont.Weight.Bold.value
        if self.body_editor.fontWeight() >= bold_value:
            self.body_editor.setFontWeight(QFont.Weight.Normal.value)
            self.bold_btn.setChecked(False)
        else:
            self.body_editor.setFontWeight(bold_value)
            self.bold_btn.setChecked(True)

    def onItalic(self):
        """切换斜体状态"""
        target = not self.body_editor.fontItalic()
        self.body_editor.setFontItalic(target)
        self.italic_btn.setChecked(target)

    def onUnderline(self):
        """切换下划线状态"""
        target = not self.body_editor.fontUnderline()
        self.body_editor.setFontUnderline(target)
        self.underline_btn.setChecked(target)

    def onStrikeOut(self):
        """切换删除线状态（通过合并 QTextCharFormat 实现）"""
        cursor = self.body_editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontStrikeOut(not fmt.fontStrikeOut())
        cursor.mergeCharFormat(fmt)
        self.body_editor.setTextCursor(cursor)
        self.strike_btn.setChecked(fmt.fontStrikeOut())

    def onTextColor(self):
        """弹出色盘设置文字颜色"""
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self.body_editor.setTextColor(color)

    def onTextBgColor(self):
        """弹出色盘设置文字背景色（高亮色）"""
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            cursor = self.body_editor.textCursor()
            fmt = cursor.charFormat()
            fmt.setBackground(color)
            cursor.mergeCharFormat(fmt)
            self.body_editor.setTextCursor(cursor)

    def onAlignLeft(self):
        """设置段落左对齐"""
        self.body_editor.setAlignment(Qt.AlignmentFlag.AlignLeft)

    def onAlignCenter(self):
        """设置段落居中对齐"""
        self.body_editor.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def onAlignRight(self):
        """设置段落右对齐"""
        self.body_editor.setAlignment(Qt.AlignmentFlag.AlignRight)

    def onBulletList(self):
        """在光标所在段落插入项目符号列表"""
        cursor = self.body_editor.textCursor()
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.Style.ListDisc)
        cursor.createList(fmt)

    def onNumberedList(self):
        """在光标所在段落插入编号列表"""
        cursor = self.body_editor.textCursor()
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.Style.ListDecimal)
        cursor.createList(fmt)

    def onInsertImage(self):
        """在正文光标处插入图片，以 cid:文件名 引用并注册为邮件内嵌图片

        说明：不能使用 QTextCursor.insertImage(QImage) 直接插入，因为 Qt
        会将其序列化为 base64 的 data: URI 写入 HTML，多数邮件客户端不解析；
        也会导致 LEmail 无法走 related 结构。故此处统一用「文件名即 cid」
        的方式（与 MainEmail.buildRelated 的 content-id 规则一致）：
        编辑器内通过 addResource 显示，发送时 toHtml() 输出 <img src="cid:文件名">。
        """
        path, _ = QFileDialog.getOpenFileName(
            self, '选择图片', '', '图片文件 (*.png *.jpg *.jpeg *.gif *.bmp)')
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, '提示', '无法读取图片：' + path)
            return
        # 用文件名作为 content-id；同名冲突时追加序号保证唯一
        content_id = self.uniqueImageName(path)
        # 注册图片显示资源，使编辑器内能看到图片（key 为 cid:文件名）
        document = self.body_editor.document()
        document.addResource(QTextDocument.ResourceType.ImageResource,
                             QUrl('cid:' + content_id), image)
        # 以 cid 方式插入图片（toHtml() 会输出 src="cid:文件名"）
        image_format = QTextImageFormat()
        image_format.setName('cid:' + content_id)
        cursor = self.body_editor.textCursor()
        cursor.insertImage(image_format)
        # 记录图片文件路径（以 content_id 为键），发送时交给 LEmail 完成 related 内嵌
        self.inline_image_paths[content_id] = path

    def uniqueImageName(self, path):
        """为图片文件生成唯一的 content-id 名称（重名时追加序号）

        参数：
            path<str>：图片文件路径

        返回：
            str：唯一的 content-id 名称（不含 cid: 前缀）
        """
        base_name = os.path.basename(path)
        name = base_name
        counter = 1
        # 若名称已被占用，改为 base_序号.后缀
        while name in self._used_image_names:
            root, ext = os.path.splitext(base_name)
            name = '%s_%d%s' % (root, counter, ext)
            counter += 1
        self._used_image_names.add(name)
        return name

    def onInsertHr(self):
        """插入水平线"""
        self.body_editor.textCursor().insertHtml('<hr>')

    def onInsertLink(self):
        """插入超链接（弹窗输入 url 与显示文字）

        说明：适合将大附件上传到网盘后，把可下载分享链接插入正文；
        收件人点击"显示文字"即可下载，不受 15MB 附件限额影响。
        """
        from PyQt6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(
            self, '插入超链接',
            '请输入可下载链接 URL\n（大附件可先上传到网盘获取分享链接）：')
        if not ok or not url.strip():
            return
        text, ok = QInputDialog.getText(self, '插入超链接', '请输入显示文字（留空则用链接）：')
        if not ok:
            return
        # 若没填显示文字，用 url 作为显示文字
        display = text.strip() or url.strip()
        self.body_editor.textCursor().insertHtml('<a href="%s">%s</a>' % (url.strip(), display))

    def onInsertDefaultSignature(self):
        """插入默认签名：署名 + 发件邮箱 + 一句话"""
        html = ('<br><hr><p>-- <br>'
                '发件人：<b>%s</b><br>'
                '邮箱：%s<br>'
                '（来自 Lhack 邮箱助手）</p>') % (
            self.from_edit.text().strip() or DEFAULT_FROM_NAME,
            DEFAULT_FROM_EMAIL)
        cursor = self.body_editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html)
        self.body_editor.setTextCursor(cursor)

    def onClearSignature(self):
        """清空签名只是提示：用户手动删除"""
        QMessageBox.information(self, '提示', '签名已插入，若要清空请手动选中删除。')

    # ---------------- 附件槽函数 ----------------

    def onAddAttachment(self):
        """弹出文件多选对话框添加附件（含总大小预检，超阿里云 15MB 上限提示并跳过）"""
        files, _ = QFileDialog.getOpenFileNames(self, '选择附件')
        # 先汇总当前已添加附件的原始字节数（供添加新文件时做上限预判）
        current_bytes = sum(os.path.getsize(p) for p in self.attachment_paths if os.path.exists(p))
        for file_path in files:
            # 去重后加入列表，并显示文件名
            if file_path not in self.attachment_paths:
                # 附件数量达到官方上限 100 时拒绝继续添加
                if len(self.attachment_paths) >= 100:
                    QMessageBox.warning(
                        self, '附件数量超限',
                        '附件数量已达 100 个（阿里云邮件推送单封上限），\n不能再添加附件。')
                    break
                # 把待添加文件计入后校验总大小（base64 膨胀），超 15MB 上限则拒绝添加
                add_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                if int((current_bytes + add_size) * 1.35) > 15 * 1024 * 1024:
                    QMessageBox.warning(
                        self, '附件过大',
                        '添加「%s」后附件总大小可能超过阿里云邮件推送的 15MB 上限，\n'
                        '该附件未添加。\n'
                        '提示：不支持发送超大附件，可将该文件上传到网盘/云盘，\n'
                        '获取分享链接后点正文「超链接」按钮插入，收件人点击即可下载。'
                        % os.path.basename(file_path))
                    continue
                self.attachment_paths.append(file_path)
                self.attachment_list.addItem(os.path.basename(file_path))
                # 累加已加入的成功附件字节数
                current_bytes += add_size
        self.updateAttachmentHeader()

    def onRemoveAttachment(self):
        """删除选中的附件"""
        row = self.attachment_list.currentRow()
        if row < 0:
            QMessageBox.information(self, '提示', '请先选中要删除的附件。')
            return
        self.attachment_list.takeItem(row)
        self.attachment_paths.pop(row)
        self.updateAttachmentHeader()

    def onClearAttachments(self):
        """清空所有附件"""
        if not self.attachment_paths:
            return
        self.attachment_paths.clear()
        self.attachment_list.clear()
        self.updateAttachmentHeader()

    # ---------------- 发送 ----------------

    def showLoading(self):
        """显示「正在发送中...」遮罩（懒加载创建，首次点击发送时生成）"""
        if not hasattr(self, 'loading_overlay') or self.loading_overlay is None:
            # 遮罩挂在顶层窗口上，可覆盖整个窗口（含状态栏区域）
            self.loading_overlay = LoadingOverlay(self.window())
        self.loading_overlay.showLoading()

    def hideLoading(self):
        """隐藏发送中遮罩"""
        if hasattr(self, 'loading_overlay') and self.loading_overlay is not None:
            self.loading_overlay.hideLoading()

    def onSendFinished(self, result):
        """发送工作线程完成回调：隐藏遮罩；成功后写入已发送并返回列表主页"""
        # 隐藏发送中遮罩
        self.hideLoading()
        if result:
            # 发送成功：先把本次邮件写入数据库「已发送」，再提示并返回
            self._storeRecord(CATEGORY_SENT)
            QMessageBox.information(self, '发送成功', '邮件已发送成功！')
            # 成功后不再留在发信页：回调切回主窗口的列表页（返回按钮同样调用 on_back）
            self.on_back()
        else:
            QMessageBox.warning(self, '发送失败', '邮件发送失败，请检查网络或 SMTP 配置。')

    def onSend(self):
        """收集页面参数，交给 NormalMode 实装发送（普通模式功能实装入口）"""
        # 收件人为必填项
        to_list = parseEmails(self.to_edit.text())
        if not to_list:
            QMessageBox.warning(self, '提示', '收件人不能为空。')
            return
        # 抄送/密送仅在展开且有内容时取用
        cc_list = parseEmails(self.cc_edit.text()) if self.cc_row_widget.isVisible() else []
        bcc_list = parseEmails(self.bcc_edit.text()) if self.bcc_row_widget.isVisible() else []
        # 回信/退信地址：只有设置了内容才使用
        reply_to = self.reply_edit.text().strip()
        return_email = self.return_edit.text().strip()
        # 汇总各参数，生成用于发送的配置
        kwargs = dict(
            n_name=self.from_edit.text().strip() or DEFAULT_FROM_NAME,
            to_list=to_list,
            cc_list=cc_list or None,
            bcc_list=bcc_list or None,
            reply_to=reply_to,
            return_email=return_email,
            email_title=self.title_edit.text().strip(),
            html_text=self.body_editor.toHtml(),
            attachment_paths=list(self.attachment_paths) if self.attachment_paths else None,
            inline_image_paths=dict(self.inline_image_paths) if self.inline_image_paths else None,
        )
        # 实例化普通模式并注入配置，随后交由 NormalMode 调用 LEmail 发送
        normal_mode = NormalMode()
        # 收件人非空时配置必成功，此处配置失败仅兜底提示
        if not normal_mode.setConfig(**kwargs):
            QMessageBox.warning(self, '提示', '邮件配置失败，请检查收件人。')
            return
        # 发送前先校验收件人数/附件数量：超过官方上限则提示并中止
        over_limits, limit_msg = normal_mode.checkLimits()
        if over_limits:
            QMessageBox.warning(self, '超出限制', limit_msg)
            return
        # 发送前预检总大小：超过阿里云 15MB 上限则提示用户改用网盘+超链接，不发信
        over_limit, est_size, max_size = normal_mode.checkSize()
        if over_limit:
            QMessageBox.warning(
                self, '附件过大',
                '邮件总大小约 %.1f MB，超过阿里云邮件推送的 %.1f MB 上限，%s\n\n'
                '不支持发送超大附件。请：\n'
                '1. 将大文件上传到网盘/云盘，获取可下载分享链接；\n'
                '2. 在正文点「超链接」按钮，把链接插入邮件；\n'
                '3. 收件人点击即可下载。' % (
                    est_size / 1024 / 1024, max_size / 1024 / 1024, '无法发送。'))
            return
        # 显示「正在发送中...」遮罩提示用户（转圈动画在后台线程发送期间持续旋转）
        self.showLoading()
        # 创建发送工作线程，将实际发送放入后台，避免阻塞遮罩动画
        self.send_worker = SendWorker(normal_mode)
        self.send_worker.finished_signal.connect(self.onSendFinished)
        self.send_worker.start()

    # ---------------- 数据库关联：存草稿 / 已发送 / 再次编辑回填 ----------------

    def rememberRecordId(self, mail_id):
        """记录当前编辑的邮件记录 id（再次编辑进入时由 MainWindow 调用）

        参数：
            mail_id<int>|None：当前记录 id；新建写信传 None
        备注：同时把 edit_category 保留旧值，仅改 id（避免覆盖来源分类）。
        """
        self.editing_id = mail_id

    def onSaveDraft(self):
        """存草稿：把当前填写内容写入数据库「草稿箱」，不发送

        说明：存草稿仅在书写新邮件或再次编辑「已发送」时提供；编辑草稿/查看模式不显示该按钮，
        故此处一律新建一条草稿，避免覆盖他人草稿或改动已发送记录。
        """
        payload = self.collectPayload()
        # 新建草稿（存草稿按钮不在草稿编辑/查看模式显示，故不存在「更新既有草稿」场景）
        self.db.insertMail(CATEGORY_DRAFT, **payload)
        QMessageBox.information(self, '保存成功', '邮件已存入草稿箱。')
        # 返回列表主页并切到草稿箱，让用户看到新保存的草稿
        self.on_back()

    def _storeRecord(self, category):
        """把当前页面内容写入数据库指定分类（发送成功写已发送）

        参数：
            category<str>：目标分类常量（CATEGORY_SENT / CATEGORY_DRAFT 等）
        备注：从草稿/已发送再次编辑后发送，更新原记录到已发送；新写信则新增一条已发送。
        """
        payload = self.collectPayload()
        if self.editing_id is not None and self.edit_category in (CATEGORY_DRAFT, CATEGORY_SENT):
            # 来自草稿/已发送的再次编辑：更新原记录并改分类为已发送
            self.db.updateMail(self.editing_id, category=category, **{k: v for k, v in payload.items()})
        else:
            # 新建写信：新增一条已发送记录
            self.db.insertMail(category, **payload)

    def collectPayload(self):
        """收集发信页当前填写的全部字段，生成一条邮件记录 dict（供写库：已发送/草稿）

        返回：
            dict：包含 title/recipient/from_name/to_list/cc_list/bcc_list/reply_to/
                  return_email/html_text/attachment_paths/inline_image_paths
        """
        to_list = parseEmails(self.to_edit.text())
        # 抄送/密送仅在展开且有内容时取用
        cc_list = parseEmails(self.cc_edit.text()) if self.cc_row_widget.isVisible() else []
        bcc_list = parseEmails(self.bcc_edit.text()) if self.bcc_row_widget.isVisible() else []
        # 收件人摘要：用于列表页「收件人/发件人」列展示
        recipient = '; '.join(to_list)
        return dict(
            from_name=self.from_edit.text().strip() or DEFAULT_FROM_NAME,
            to_list=to_list,
            cc_list=cc_list,
            bcc_list=bcc_list,
            reply_to=self.reply_edit.text().strip(),
            return_email=self.return_edit.text().strip(),
            title=self.title_edit.text().strip(),
            recipient=recipient,
            html_text=self.body_editor.toHtml(),
            attachment_paths=list(self.attachment_paths) if self.attachment_paths else [],
            inline_image_paths=dict(self.inline_image_paths) if self.inline_image_paths else {},
        )

    def fillFromRecord(self, record):
        """用数据库邮件记录回填发信页各输入（再次编辑进入时调用）

        参数：
            record<dict>：一条数据库邮件记录
        """
        # 先把表单清空（含隐藏展开行/清附件），避免上次内容残留
        self.clearForm()
        # 记录来源分类，供写已发送时「更新原记录 vs 新增」判断
        self.edit_category = record.get('category')
        # 发件人昵称 / 收件人 / 抄送 / 密送
        self.from_edit.setText(record.get('from_name', ''))
        self.to_edit.setText('; '.join(record.get('to_list') or []))
        cc_list = record.get('cc_list') or []
        if cc_list:
            self.cc_row_widget.setVisible(True)
            self.cc_edit.setText('; '.join(cc_list))
        bcc_list = record.get('bcc_list') or []
        if bcc_list:
            self.bcc_row_widget.setVisible(True)
            self.bcc_edit.setText('; '.join(bcc_list))
        # 回信 / 退信地址（有值则展开对应行）
        if record.get('reply_to'):
            self.reply_row_widget.setVisible(True)
        if record.get('return_email'):
            self.return_row_widget.setVisible(True)
        # 主题与正文（HTML）
        self.title_edit.setText(record.get('title', ''))
        self.body_editor.setHtml(record.get('html_text', '') or '')
        # 附件路径列表与内嵌图片映射
        self.attachment_paths = list(record.get('attachment_paths') or [])
        self.attachment_list.clear()
        for p in self.attachment_paths:
            self.attachment_list.addItem(os.path.basename(p))
        self.inline_image_paths = dict(record.get('inline_image_paths') or {})
        self._used_image_names = set(self.inline_image_paths.keys())
        # 有附件则展开附件区；无则自动隐藏（updateAttachmentHeader 内部处理）
        self.updateAttachmentHeader()

    def setRestoreCallback(self, callback):
        """注入「恢复」按钮回调（由 MainWindow 提供，携带当前查看的记录 id）

        参数：
            callback<callable(mail_id)>：恢复处理函数
        """
        self.restore_callback = callback
        self.restore_btn.clicked.connect(self._onRestoreClicked) if callback else None

    def _onRestoreClicked(self):
        """点「恢复」：调用注入的恢复回调，回传当前查看的记录 id"""
        if self.restore_callback is not None:
            self.restore_callback(self.view_record_id)

    # ---------------- 页面状态模式 ----------------

    def _setFormReadOnly(self, readonly):
        """统一设置表单输入控件的只读状态

        参数：
            readonly<bool>：True=全部只读禁用；False=可编辑
        """
        for edit in (self.to_edit, self.cc_edit, self.bcc_edit,
                     self.reply_edit, self.return_edit, self.title_edit):
            edit.setReadOnly(readonly)
        self.body_editor.setReadOnly(readonly)
        # 附件/内嵌图片相关按钮与菜单在只读时隐藏（无法编辑附件）
        self.attach_menu_btn.setVisible(not readonly)
        self.setting_menu_btn.setVisible(not readonly)

    def clearForm(self):
        """清空写信表单（含展开行/附件/图片），用于写信初始化或再次编辑回填前重置"""
        # 文本输入清空
        self.from_edit.setText('')
        self.to_edit.setText('')
        self.cc_edit.setText('')
        self.bcc_edit.setText('')
        self.reply_edit.setText('')
        self.return_edit.setText('')
        self.title_edit.setText('')
        self.body_editor.clear()
        # 隐藏展开行（抄送/密送/回信/退信）
        self.cc_row_widget.setVisible(False)
        self.bcc_row_widget.setVisible(False)
        self.reply_row_widget.setVisible(False)
        self.return_row_widget.setVisible(False)
        # 清空附件与内嵌图片
        self.attachment_paths = []
        self.attachment_list.clear()
        self.inline_image_paths = {}
        self._used_image_names = set()
        self.updateAttachmentHeader()
        # 重置编辑/查看状态
        self.editing_id = None
        self.edit_category = None
        self.view_record_id = None

    def setWriteMode(self):
        """写信模式：所有编辑可用，显示发送/存草稿/附件/设置，隐藏恢复"""
        self._setFormReadOnly(False)
        # 显示发送/存草稿/预览；隐藏恢复
        self.send_btn.setVisible(True)
        self.draft_btn.setVisible(True)
        self.preview_btn.setVisible(True)
        self.restore_btn.setVisible(False)

    def setEditMode(self):
        """再次编辑模式：可发送/预览；草稿箱不提供存草稿；隐藏恢复"""
        self._setFormReadOnly(False)
        self.send_btn.setVisible(True)
        self.preview_btn.setVisible(True)
        # 草稿箱编辑不提供「存草稿」（再次保存草稿无意义）
        self.draft_btn.setVisible(self.edit_category != CATEGORY_DRAFT)
        self.restore_btn.setVisible(False)

    def setViewMode(self, restorable=False):
        """只读查看模式：所有编辑禁用；仅显示返回/恢复（已删除），隐藏发送/存草稿/附件/设置

        参数：
            restorable<bool>：True=已删除可恢复，显示「恢复」按钮
        """
        self._setFormReadOnly(True)
        # 编辑类按钮全部隐藏；恢复仅已删除查看时显示
        self.send_btn.setVisible(False)
        self.draft_btn.setVisible(False)
        self.preview_btn.setVisible(False)
        self.restore_btn.setVisible(restorable)
        # 恢复需记录当前查看的记录 id（onRequestView 已在 fillFromRecord 前设置）