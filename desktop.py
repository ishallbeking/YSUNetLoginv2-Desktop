"""YSUNet desktop client, built with Qt Widgets."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import desktop_backend as backend

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal, QLockFile
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox, QScrollArea, QLayout,
    QStackedWidget, QSystemTrayIcon, QMenu, QTextEdit, QVBoxLayout, QWidget,
)


def icon():
    pixmap = QPixmap(80, 80)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(0, 0, 80, 80, 22, 22)
    painter.setPen(QPen(QColor("white"), 5, Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(16, 19, 48, 44, 40 * 16, 100 * 16)
    painter.drawArc(25, 30, 30, 28, 40 * 16, 100 * 16)
    painter.setBrush(QColor("white"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(36, 48, 8, 8)
    painter.end()
    return QIcon(pixmap)


class ResultSignals(QObject):
    done = Signal(str, object, str)


class Task(QRunnable):
    def __init__(self, action, function):
        super().__init__()
        self.action, self.function = action, function
        self.signals = ResultSignals()

    def run(self):
        try:
            self.signals.done.emit(self.action, self.function(), "")
        except Exception as error:
            self.signals.done.emit(self.action, None, backend.error_message(error))


def text(value, name=None):
    label = QLabel(value)
    if name:
        label.setObjectName(name)
    return label


def button(value, primary=False):
    result = QPushButton(value)
    result.setCursor(Qt.PointingHandCursor)
    if primary:
        result.setObjectName("primary")
    return result


def card():
    result = QFrame()
    result.setObjectName("card")
    return result


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #24344f; }
QMainWindow, #main { background: #f4f7fc; }
#sidebar { background: #ffffff; border-right: 1px solid #e7edf6; }
#brand { font-size: 23px; font-weight: 700; color: #162d57; }
#muted, #eyebrow { color: #7d8ba3; }
#eyebrow { font-size: 11px; font-weight: 600; }
#pageTitle { font-size: 27px; font-weight: 700; color: #182d50; }
#card { background: #ffffff; border: 1px solid #e4eaf4; border-radius: 16px; }
#hero { background: #eef5ff; border: 1px solid #dce9ff; border-radius: 18px; }
#heroTitle { font-size: 29px; font-weight: 700; color: #1b3a6a; }
#sectionTitle { font-size: 15px; font-weight: 700; color: #213756; }
#value { font-size: 18px; font-weight: 600; color: #1b3559; }
#badge { padding: 6px 11px; border-radius: 11px; color: #147d65; background: #e5f6ed; font-size: 12px; }
#notice { background: #eaf1ff; color: #335991; padding: 12px 16px; border-radius: 9px; }
QPushButton { min-height: 22px; background: white; border: 1px solid #dce4ef; border-radius: 9px; padding: 10px 18px; font-weight: 600; }
QPushButton:hover { background: #edf3ff; border-color: #acc6f5; }
QPushButton:pressed { background: #dceaff; }
QPushButton:disabled { color: #a8b2c3; background: #f2f4f8; border-color: #e8edf4; }
QPushButton#primary { background: #2563eb; color: white; border-color: #2563eb; }
QPushButton#primary:hover { background: #1c55d3; }
QPushButton#primary:disabled { background: #a1b9e9; border-color: #a1b9e9; }
QPushButton#nav { text-align: left; border: none; padding: 13px 20px; background: transparent; color: #718097; font-weight: 500; }
QPushButton#nav:checked { background: #ecf3ff; color: #2563eb; font-weight: 700; }
QPushButton#nav:hover { background: #f2f6fd; }
QLineEdit, QComboBox, QSpinBox { background: #fafcff; border: 1px solid #dce4f0; border-radius: 8px; padding: 10px; min-height: 22px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #6092ee; }
QComboBox::drop-down { border: none; width: 25px; }
QTextEdit { background: #fafcff; border: 1px solid #e3eaf4; border-radius: 10px; padding: 10px; font-family: 'Microsoft YaHei UI'; font-size: 12px; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 19px; height: 19px; border: 1px solid #bdcce0; border-radius: 5px; background: white; }
QCheckBox::indicator:checked { background: #2563eb; border-color: #2563eb; image: none; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #d6dfed; border-radius: 3px; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QToolTip { background: #213756; color: white; border: none; padding: 5px; }
"""


class Window(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.settings = backend.load_settings() if not demo else {"auto_reconnect": False, "interval": 30, "close_to_tray": False}
        self.policy = backend.RetryPolicy(backup_available=backend.backup_available())
        self.next_scheduled = time.monotonic() + self.settings.get("schedule_minutes", 60) * 60
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self.cycle_path = None
        self.cycle_started = 0
        self.pending_close = False
        self.last_state = None
        self.internet_state = "未检测"
        self.events = backend.load_events() if not demo else []
        self.setWindowTitle("YSUNet · 燕山大学校园网")
        self.setWindowIcon(icon())
        self.resize(1100, 920)
        self.setMinimumSize(940, 700)
        self.setStyleSheet(STYLE)
        main = QWidget()
        main.setObjectName("main")
        self.setCentralWidget(main)
        shell = QHBoxLayout(main)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 30, 18, 22)
        side.setSpacing(8)
        brand_row = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon().pixmap(35, 35))
        brand_row.addWidget(mark)
        brand_row.addWidget(text("YSUNet", "brand"))
        brand_row.addStretch()
        side.addLayout(brand_row)
        side.addWidget(text("  燕山大学 · 校园网助手", "muted"))
        side.addSpacing(36)
        self.nav = []
        for index, name in enumerate(("连接概览", "账号与设置", "运行日志")):
            item = button(name)
            item.setObjectName("nav")
            item.setCheckable(True)
            item.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            self.nav.append(item)
            side.addWidget(item)
        side.addStretch()
        side.addWidget(text("CAMPUS NETWORK", "eyebrow"))
        side.addWidget(text("让连接更简单。", "muted"))
        side.addSpacing(12)
        side.addWidget(text("桌面客户端  /  v2.1", "muted"))
        shell.addWidget(sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 27, 32, 20)
        layout.setSpacing(16)
        header = QHBoxLayout()
        self.page_title = text("连接概览", "pageTitle")
        header.addWidget(self.page_title)
        header.addStretch()
        self.badge = text("正在检测", "badge")
        header.addWidget(self.badge)
        layout.addLayout(header)
        self.page_description = text("查看校园网连接，管理你的每一次在线。", "muted")
        layout.addWidget(self.page_description)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.build_overview()
        self.build_settings()
        self.build_logs()
        self.notice = text("正在读取连接状态…", "notice")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        footer = QHBoxLayout()
        self.updated = text("尚未更新", "muted")
        footer.addWidget(self.updated)
        footer.addStretch()
        footer.addWidget(text("本机运行 · 凭据保存在项目目录", "muted"))
        layout.addLayout(footer)
        shell.addWidget(content, 1)
        self.create_tray()
        self.navigate(0)
        self.refresh_logs()
        self.load_account()
        self.update_auto_detail()
        self.schedule_changed(self.settings.get("schedule_minutes", 60), persist=False)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.settings["interval"] * 1000)
        self.cycle_timer = QTimer(self)
        self.cycle_timer.setInterval(1000)
        self.cycle_timer.timeout.connect(self.poll_cycle)
        self.schedule_timer = QTimer(self)
        self.schedule_timer.setInterval(1000)
        self.schedule_timer.timeout.connect(self.schedule_tick)
        if not self.demo:
            self.schedule_timer.start()
        if demo:
            self.apply_state({"online": True, "service": "中国电信", "account": "demo****user", "account_matches": True,
                              "service_matches": True, "ip": "10.0.0.123", "login_time": "2026-11-14 15:22:25", "checked_at": backend.now()})
            self.internet_state = "HTTP / HTTPS 均正常"
            self.internet_value.setText("外网连通    " + self.internet_state)
            self.notice.setText("连接正常。开启自动重连后，助手会在校园网掉线时尝试恢复。")
            self.add_log("校园网连接正常，账号与运营商匹配。")
            self.add_log("HTTP 与 HTTPS 连通性检测通过。")
        else:
            QTimer.singleShot(0, lambda: self.start("diagnose"))

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for number, nav in enumerate(self.nav):
            nav.setChecked(number == index)
        self.page_title.setText(("连接概览", "账号与设置", "运行日志")[index])
        self.page_description.setText(("查看校园网连接，管理你的每一次在线。",
                                       "管理当前账号，按你的习惯设置连接策略。",
                                       "查看连接记录、诊断结果与自动重连进度。")[index])

    def add_page(self, page):
        page.layout().setSizeConstraint(QLayout.SetMinimumSize)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)

    def build_overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(17)
        hero = QFrame()
        hero.setObjectName("hero")
        box = QVBoxLayout(hero)
        box.setContentsMargins(26, 24, 26, 22)
        box.setSpacing(12)
        hero.setMinimumHeight(208)
        box.addWidget(text("YOUR CAMPUS, CONNECTED", "eyebrow"))
        self.hero_title = text("正在检查连接", "heroTitle")
        self.hero_title.setMinimumHeight(48)
        box.addWidget(self.hero_title)
        self.hero_description = text("正在与校园网认证服务器通信…", "muted")
        self.hero_description.setWordWrap(True)
        box.addWidget(self.hero_description)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.login_button = button("连接校园网", True)
        self.login_button.clicked.connect(lambda: self.start("login"))
        self.logout_button = button("断开连接")
        self.logout_button.clicked.connect(self.logout)
        self.check_button = button("网络诊断")
        self.check_button.clicked.connect(lambda: self.start("diagnose"))
        controls.addWidget(self.login_button)
        controls.addWidget(self.logout_button)
        controls.addWidget(self.check_button)
        controls.addStretch()
        box.addSpacing(6)
        box.addLayout(controls)
        layout.addWidget(hero)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metric_labels = {}
        for name, value in (("当前账号", "—"), ("网络服务", "—"), ("本机 IP", "—")):
            panel = card()
            column = QVBoxLayout(panel)
            column.setContentsMargins(18, 17, 18, 18)
            column.setSpacing(9)
            column.addWidget(text(name, "muted"))
            label = text(value, "value")
            self.metric_labels[name] = label
            column.addWidget(label)
            metrics.addWidget(panel)
        layout.addLayout(metrics)
        automation = card()
        auto = QVBoxLayout(automation)
        auto.setContentsMargins(22, 18, 22, 18)
        row = QHBoxLayout()
        column = QVBoxLayout()
        column.addWidget(text("断线自动重连", "sectionTitle"))
        column.addWidget(text("定期检查认证状态，离线时自动恢复连接。", "muted"))
        row.addLayout(column, 1)
        self.auto_check = QCheckBox("开启")
        self.auto_check.setChecked(self.settings["auto_reconnect"])
        self.auto_check.toggled.connect(self.toggle_auto)
        row.addWidget(self.auto_check)
        auto.addLayout(row)
        self.auto_detail = text("关闭 · 仅手动连接", "muted")
        auto.addWidget(self.auto_detail)
        self.schedule_check = QCheckBox("定时主动重连（每 60 分钟）")
        self.schedule_check.setChecked(self.settings.get("scheduled_reconnect", False))
        self.schedule_check.toggled.connect(self.toggle_schedule)
        auto.addWidget(self.schedule_check)
        self.schedule_detail = text("关闭 · 按需开启，重连时网络会短暂中断", "muted")
        auto.addWidget(self.schedule_detail)
        automation.setMinimumHeight(170)
        layout.addWidget(automation)
        lower = card()
        detail = QVBoxLayout(lower)
        detail.setContentsMargins(22, 18, 22, 18)
        detail.setSpacing(11)
        lower.setMinimumHeight(200)
        row = QHBoxLayout()
        row.addWidget(text("连接详情", "sectionTitle"))
        row.addStretch()
        self.refresh_button = button("刷新状态")
        self.refresh_button.clicked.connect(lambda: self.start("status"))
        row.addWidget(self.refresh_button)
        detail.addLayout(row)
        self.login_time = text("认证时间    —", "muted")
        detail.addWidget(self.login_time)
        self.internet_value = text("外网连通    未检测", "muted")
        detail.addWidget(self.internet_value)
        row = QHBoxLayout()
        self.cycle_button = button("断网重连测试")
        self.cycle_button.clicked.connect(self.confirm_cycle)
        row.addWidget(self.cycle_button)
        row.addWidget(text("独立后台执行，带恢复守护进程", "muted"))
        row.addStretch()
        detail.addLayout(row)
        layout.addWidget(lower)
        layout.addStretch()
        self.add_page(page)

    def build_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(16)
        account_card = card()
        account = QVBoxLayout(account_card)
        account.setContentsMargins(24, 22, 24, 22)
        account.setSpacing(11)
        account.addWidget(text("主账号", "sectionTitle"))
        account.addWidget(text("读取本目录 zc.txt；点击保存后更新原文件。", "muted"))
        self.username = QLineEdit()
        self.username.setPlaceholderText("校园网账号")
        self.password = QLineEdit()
        self.password.setPlaceholderText("校园网密码")
        self.password.setEchoMode(QLineEdit.Password)
        self.service = QComboBox()
        self.service.addItems(backend.SERVICES)
        account.addWidget(text("账号", "muted"))
        account.addWidget(self.username)
        account.addWidget(text("密码", "muted"))
        account.addWidget(self.password)
        account.addWidget(text("运营商 / 网络服务", "muted"))
        account.addWidget(self.service)
        row = QHBoxLayout()
        self.save_account_button = button("保存账号", True)
        self.save_account_button.clicked.connect(self.save_account)
        row.addWidget(self.save_account_button)
        row.addStretch()
        account.addLayout(row)
        layout.addWidget(account_card)
        backup_card = card()
        backup = QVBoxLayout(backup_card)
        backup.setContentsMargins(24, 22, 24, 22)
        backup.setSpacing(11)
        backup.addWidget(text("备用账号", "sectionTitle"))
        backup.addWidget(text("主账号失败 3 次后，再用备用账号尝试 3 次。", "muted"))
        self.backup_check = QCheckBox("启用备用账号")
        self.backup_check.setChecked(self.settings.get("backup_enabled", False))
        self.backup_check.toggled.connect(self.toggle_backup)
        backup.addWidget(self.backup_check)
        self.backup_username = QLineEdit()
        self.backup_username.setPlaceholderText("备用校园网账号")
        self.backup_password = QLineEdit()
        self.backup_password.setEchoMode(QLineEdit.Password)
        self.backup_password.setPlaceholderText("备用校园网密码")
        self.backup_service = QComboBox()
        self.backup_service.addItems(backend.SERVICES)
        backup.addWidget(text("备用账号", "muted"))
        backup.addWidget(self.backup_username)
        backup.addWidget(text("备用密码", "muted"))
        backup.addWidget(self.backup_password)
        backup.addWidget(text("备用运营商 / 网络服务", "muted"))
        backup.addWidget(self.backup_service)
        row = QHBoxLayout()
        self.save_backup_button = button("保存并启用备用账号", True)
        self.save_backup_button.clicked.connect(self.save_backup)
        self.delete_backup_button = button("删除备用账号")
        self.delete_backup_button.clicked.connect(self.delete_backup)
        row.addWidget(self.save_backup_button)
        row.addWidget(self.delete_backup_button)
        row.addStretch()
        backup.addLayout(row)
        layout.addWidget(backup_card)
        policy = card()
        options = QVBoxLayout(policy)
        options.setContentsMargins(24, 20, 24, 20)
        options.setSpacing(12)
        options.addWidget(text("连接偏好", "sectionTitle"))
        row = QHBoxLayout()
        row.addWidget(text("状态检查间隔"))
        row.addStretch()
        self.interval = QSpinBox()
        self.interval.setRange(15, 300)
        self.interval.setSuffix(" 秒")
        self.interval.setValue(self.settings["interval"])
        self.interval.valueChanged.connect(self.interval_changed)
        row.addWidget(self.interval)
        options.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(text("定时主动重连间隔"))
        row.addStretch()
        self.schedule_minutes = QSpinBox()
        self.schedule_minutes.setRange(5, 1440)
        self.schedule_minutes.setSuffix(" 分钟")
        self.schedule_minutes.setValue(self.settings.get("schedule_minutes", 60))
        self.schedule_minutes.valueChanged.connect(self.schedule_changed)
        row.addWidget(self.schedule_minutes)
        options.addLayout(row)
        options.addWidget(text("启用后，到时会先登出再登录；可在连接概览中开启。", "muted"))
        self.tray_check = QCheckBox("关闭窗口时最小化到托盘，继续保持连接")
        self.tray_check.setChecked(self.settings["close_to_tray"])
        self.tray_check.toggled.connect(self.tray_changed)
        options.addWidget(self.tray_check)
        options.addWidget(text("主账号最多 3 次，备用账号最多 3 次；全部失败后暂停。", "muted"))
        layout.addWidget(policy)
        layout.addStretch()
        self.add_page(page)

    def build_logs(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        row = QHBoxLayout()
        row.addWidget(text("最近的操作记录", "sectionTitle"))
        row.addStretch()
        export = button("导出日志")
        export.clicked.connect(self.export_logs)
        row.addWidget(export)
        open_button = button("打开记录目录")
        open_button.clicked.connect(lambda: os.startfile(str(backend.STATE)))
        row.addWidget(open_button)
        layout.addLayout(row)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        layout.addWidget(self.logs)
        layout.addWidget(text("仅保存操作结果与错误提示，账号密码不会写入日志。", "muted"))
        self.add_page(page)

    def create_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("YSUNet · 校园网助手")
        menu = QMenu()
        menu.addAction("打开主界面", self.bring_forward)
        menu.addAction("连接校园网", lambda: self.start("login"))
        menu.addSeparator()
        menu.addAction("退出助手", self.quit_requested)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.bring_forward() if reason == QSystemTrayIcon.Trigger else None)
        if not self.demo and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def bring_forward(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def load_account(self):
        if not self.demo:
            try:
                backup = backend.backup_credentials(enabled_only=False)
                if backup:
                    self.backup_username.setText(backup[0])
                    self.backup_password.setText(backup[1])
                    self.backup_service.setCurrentText(backup[2])
            except (OSError, ValueError):
                self.notice.setText("备用账号文件无法读取，请重新保存备用账号。")
        if self.demo:
            self.username.setText("demo-campus-user")
            self.password.setText("demo-only")
            self.service.setCurrentText("中国电信")
            return
        try:
            username, password, service = backend.credentials()
            self.username.setText(username)
            self.password.setText(password)
            self.service.setCurrentText(service)
        except (OSError, ValueError):
            self.notice.setText("请先在「账号与设置」中配置校园网账号。")

    def save_account(self):
        if self.busy or self.cycle_path:
            return
        try:
            backend.save_credentials(self.username.text(), self.password.text(), self.service.currentText())
        except (ValueError, OSError):
            self.notice.setText("保存失败，请填写完整账号、密码并检查文件权限。")
            return
        self.policy.reset()
        self.add_log("账号配置已更新。")
        self.notice.setText("账号已保存；下次连接时使用新配置。")
        self.refresh()

    def toggle_auto(self, enabled):
        self.settings["auto_reconnect"] = enabled
        self.policy.reset()
        if not self.demo:
            backend.save_settings(self.settings)
        self.update_auto_detail()
        self.add_log("已开启断线自动重连。" if enabled else "已关闭断线自动重连。")
        if enabled:
            self.refresh()

    def update_auto_detail(self):
        if self.policy.exhausted:
            value = ("已暂停 · 主账号和备用账号各失败 3 次" if self.policy.backup_available
                     else "已暂停 · 主账号失败 3 次，未启用备用账号")
        elif self.settings["auto_reconnect"]:
            profile = "备用账号" if self.policy.profile == "backup" else "主账号"
            value = "已开启 · 每 {} 秒检查 · {}已失败 {}/3 次".format(
                self.settings["interval"], profile, self.policy.counts[self.policy.profile])
        else:
            value = "关闭 · 仅手动连接"
        self.auto_detail.setText(value)

    def save_backup(self):
        if self.busy or self.cycle_path or self.demo:
            return
        try:
            backend.save_credentials(self.backup_username.text(), self.backup_password.text(),
                                     self.backup_service.currentText(), backend.BACKUP_PATH)
            self.settings["backup_enabled"] = True
            backend.save_settings(self.settings)
        except (ValueError, OSError):
            self.notice.setText("备用账号保存失败，请填写完整账号、密码和运营商。")
            return
        self.backup_check.blockSignals(True)
        self.backup_check.setChecked(True)
        self.backup_check.blockSignals(False)
        self.policy.configure_backup(backend.backup_available())
        self.policy.reset()
        self.update_auto_detail()
        self.add_log("备用账号已保存并启用；主账号失败 3 次后自动切换。")
        self.notice.setText("备用账号已启用，主账号和备用账号各最多尝试 3 次。")
        self.refresh()

    def toggle_backup(self, enabled):
        if self.demo:
            return
        if enabled:
            try:
                configured = backend.backup_credentials(enabled_only=False)
            except (ValueError, OSError):
                configured = None
            if not configured:
                self.backup_check.blockSignals(True)
                self.backup_check.setChecked(False)
                self.backup_check.blockSignals(False)
                self.notice.setText("请先填写备用账号，再点击「保存并启用备用账号」。")
                return
        self.settings["backup_enabled"] = enabled
        backend.save_settings(self.settings)
        self.policy.configure_backup(backend.backup_available())
        self.update_auto_detail()
        self.add_log("已启用备用账号。" if enabled else "已停用备用账号，保留已保存的配置。")
        self.refresh()

    def delete_backup(self):
        if self.busy or self.cycle_path or self.demo:
            return
        try:
            backend.BACKUP_PATH.unlink(missing_ok=True)
        except OSError:
            self.notice.setText("无法删除备用账号文件，请检查文件权限。")
            return
        self.backup_check.setChecked(False)
        self.settings["backup_enabled"] = False
        backend.save_settings(self.settings)
        self.backup_username.clear()
        self.backup_password.clear()
        self.policy.configure_backup(False)
        self.update_auto_detail()
        self.add_log("备用账号已删除。")
        self.notice.setText("已删除备用账号；主账号保持不变。")


    def toggle_schedule(self, enabled):
        self.settings["scheduled_reconnect"] = enabled
        self.next_scheduled = time.monotonic() + self.settings.get("schedule_minutes", 60) * 60
        if not self.demo:
            backend.save_settings(self.settings)
        self.add_log("已开启定时主动重连。" if enabled else "已关闭定时主动重连。")
        self.schedule_tick()

    def schedule_changed(self, value, persist=True):
        self.settings["schedule_minutes"] = value
        self.next_scheduled = time.monotonic() + value * 60
        self.schedule_check.setText("定时主动重连（每 {} 分钟）".format(value))
        if persist and not self.demo:
            backend.save_settings(self.settings)

    def schedule_tick(self):
        if not self.settings.get("scheduled_reconnect"):
            self.schedule_detail.setText("关闭 · 按需开启，重连时网络会短暂中断")
            return
        remaining = max(0, int(self.next_scheduled - time.monotonic()))
        self.schedule_detail.setText("下次主动重连  {:02d}:{:02d}  · 到时自动执行".format(remaining // 60, remaining % 60))
        if remaining or self.busy or self.cycle_path or self.demo:
            return
        if self.last_state and self.last_state["online"]:
            if self.last_state["account_matches"] and self.last_state["service_matches"]:
                self.add_log("已到设定时间，开始独立后台重连。")
                self.next_scheduled = time.monotonic() + self.settings["schedule_minutes"] * 60
                self.launch_cycle()
            else:
                self.schedule_check.setChecked(False)
                self.add_log("在线账号与配置不同，定时主动重连已暂停。", "warning")
        else:
            self.next_scheduled = time.monotonic() + self.settings["schedule_minutes"] * 60
            if self.policy.allowed(True, False, self.busy):
                self.start("login", automatic=True)

    def interval_changed(self, value):
        self.settings["interval"] = value
        self.timer.setInterval(value * 1000)
        if not self.demo:
            backend.save_settings(self.settings)
        self.update_auto_detail()

    def tray_changed(self, enabled):
        self.settings["close_to_tray"] = enabled
        if not self.demo:
            backend.save_settings(self.settings)

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.login_button, self.logout_button, self.check_button, self.refresh_button,
                       self.cycle_button, self.save_account_button, self.username, self.password,
                       self.service, self.auto_check, self.schedule_check,
                       self.backup_check, self.backup_username, self.backup_password,
                       self.backup_service, self.save_backup_button, self.delete_backup_button):
            widget.setEnabled(not busy and not self.cycle_path)
        if not busy and self.last_state and not self.cycle_path:
            online = self.last_state["online"]
            self.logout_button.setEnabled(online)
            self.login_button.setEnabled(not online)
            self.cycle_button.setEnabled(online and self.last_state["account_matches"] and self.last_state["service_matches"])

    def start(self, action, automatic=False):
        if self.demo or self.busy or self.cycle_path:
            return
        if action == "login" and not automatic:
            self.policy.reset()
        profile = self.policy.profile if automatic else "primary"
        self.attempt_profile = profile
        if automatic and self.policy.exhausted:
            return
        if action in ("login", "logout"):
            # Coordinate with the standalone reconnect worker and guardian.
            def operation():
                import reconnect
                with reconnect.operation_lock():
                    return backend.network_operation(action, profile=profile)
        else:
            operation = lambda: backend.network_operation(action)
        self.set_busy(True)
        if action != "status":
            self.notice.setText({"login": "正在连接校园网…", "logout": "正在断开连接…", "diagnose": "正在检测校园网与外网连通性…"}[action])
        task = Task("auto_login" if automatic else action, operation)
        task.signals.done.connect(self.task_done)
        self.pool.start(task)

    def task_done(self, action, result, error):
        self.set_busy(False)
        if error:
            self.notice.setText(error)
            if action == "status":
                self.hero_title.setText("暂时无法获取状态")
                self.badge.setText("状态未知")
                self.hero_description.setText(error)
            if action == "auto_login":
                previous_profile = self.policy.profile
                self.policy.failed(self.settings["interval"])
                if previous_profile == "primary" and self.policy.profile == "backup":
                    self.add_log("主账号连续失败 3 次，将切换备用账号尝试（最多 3 次）。", "warning")
                    self.notice.setText("主账号连续失败 3 次，下一次重连将使用备用账号。")
                elif self.policy.exhausted:
                    message = ("主账号和备用账号各失败 3 次，自动重连已暂停。"
                               if self.policy.backup_available else "主账号失败 3 次，未启用备用账号，已暂停。")
                    self.add_log(message, "warning")
                    self.notice.setText(message)
            self.add_log(error, "error")
        else:
            state = result["state"]
            self.apply_state(state)
            if "internet" in result:
                passed = all(item["passed"] for item in result["internet"])
                self.internet_state = "HTTP / HTTPS 均正常" if passed else "外网检测未全部通过"
                self.internet_value.setText("外网连通    " + self.internet_state)
                self.add_log(self.internet_state + "。", "info" if passed else "warning")
            if action in ("login", "auto_login"):
                self.policy.reset()
                self.notice.setText("已连接校园网，账号与运营商验证通过。")
                self.add_log(("备用账号" if state.get("account_profile") == "backup" else "主账号")
                             + "登录成功，账号与运营商匹配。")
            elif action == "logout":
                self.notice.setText("已断开校园网，自动重连已关闭。")
                self.add_log("校园网已登出。")
            elif action == "diagnose":
                self.notice.setText("诊断完成：" + ("校园网在线；" if state["online"] else "校园网离线；") + self.internet_state + "。")
            if self.policy.allowed(self.settings["auto_reconnect"], state["online"], self.busy):
                self.add_log("检测到校园网离线，正在自动重连。")
                QTimer.singleShot(0, lambda: self.start("login", automatic=True))
        self.update_auto_detail()
        self.set_busy(self.busy)
        if self.pending_close and not self.busy:
            self.close()

    def apply_state(self, state):
        previous = self.last_state
        self.last_state = state
        online = state["online"]
        matched = state["account_matches"] and state["service_matches"]
        self.hero_title.setText("校园网已连接" if online else "校园网未连接")
        self.hero_description.setText(
            (("正在使用备用账号，网络连接正常。" if state.get("account_profile") == "backup"
              else "连接稳定，开始你的学习与探索。") if matched else "当前在线账号或运营商与配置不同，请先核对。")
            if online else "确认已接入校园网后，点击下方按钮登录。"
        )
        self.badge.setText("●  已在线" if online else "○  未连接")
        self.badge.setStyleSheet("color: #147d65; background: #e5f6ed;" if online else "color: #8b6519; background: #fff3d6;")
        self.metric_labels["当前账号"].setText(state["account"])
        self.metric_labels["网络服务"].setText(state["service"])
        self.metric_labels["本机 IP"].setText(state["ip"])
        self.login_time.setText("认证时间    " + str(state["login_time"]))
        self.updated.setText("最近更新  " + state["checked_at"][11:19])
        if not online or (previous and previous["online"] != online):
            self.internet_state = "未检测"
            self.internet_value.setText("外网连通    未检测")
        if previous and previous["online"] != online:
            self.add_log("状态变化：校园网已上线。" if online else "状态变化：校园网已离线。")
        if online and matched:
            self.policy.reset()
        self.update_auto_detail()

    def refresh(self):
        self.start("status")

    def logout(self):
        if self.busy or self.cycle_path:
            return
        if self.auto_check.isChecked():
            self.auto_check.setChecked(False)
        self.schedule_check.setChecked(False)
        self.start("logout")

    def confirm_cycle(self):
        if self.busy or self.cycle_path:
            return
        answer = QMessageBox.question(self, "断网重连测试", "将暂时断开校园网，再由独立后台脚本恢复。\n是否开始？",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.launch_cycle()

    def launch_cycle(self):
        if self.demo or self.busy or self.cycle_path:
            return
        self.set_busy(True)
        self.notice.setText("正在启动独立的断网重连测试…")
        def launch():
            python = Path(sys.executable).with_name("python.exe")
            command = [str(python), str(ROOT / "reconnect.py")]
            result = subprocess.run(command, cwd=str(ROOT), capture_output=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError("Cannot start reconnect worker")
            return json.loads(result.stdout.decode("utf-8"))
        task = Task("cycle_launch", launch)
        task.signals.done.connect(self.cycle_launched)
        self.pool.start(task)

    def cycle_launched(self, action, result, error):
        if error:
            self.set_busy(False)
            self.notice.setText(error)
            self.next_scheduled = time.monotonic() + self.settings.get("schedule_minutes", 60) * 60
            self.add_log("断网重连测试未能启动。", "error")
            return
        self.cycle_path = Path(result["result"])
        self.cycle_started = time.monotonic()
        self.set_busy(False)
        self.add_log("独立断网重连测试已启动，恢复守护进程将自动运行。")
        self.cycle_timer.start()

    def poll_cycle(self):
        try:
            report = json.loads(self.cycle_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = {}
        phase = report.get("phase")
        if phase == "completed":
            self.finish_cycle("断网重连测试成功，网络已恢复。" if report.get("success") else "网络已恢复，但未完整验证断网重连。")
        elif phase == "failed":
            guard = self.cycle_path.parent / "guard-result.json"
            if guard.exists():
                self.finish_cycle("自动恢复未成功，请检查账号或手动登录。", "error")
            else:
                self.notice.setText("主进程恢复失败，独立守护进程正在接管…")
        elif time.monotonic() - self.cycle_started > 600:
            self.finish_cycle("等待测试超时，请在运行日志目录查看后台结果。", "warning")
        else:
            self.notice.setText({"disconnecting": "正在断开校园网…", "reconnecting": "正在自动恢复网络…",
                                 "guard_recovery": "守护进程正在恢复网络…", "prepared": "后台测试已就绪…"}.get(phase, "独立后台测试运行中…"))

    def finish_cycle(self, message, level="info"):
        self.cycle_timer.stop()
        self.cycle_path = None
        self.next_scheduled = time.monotonic() + self.settings.get("schedule_minutes", 60) * 60
        if level == "error":
            self.schedule_check.setChecked(False)
            self.policy.exhaust()
            self.update_auto_detail()
        self.set_busy(False)
        self.notice.setText(message)
        self.add_log(message, level)
        self.refresh()

    def add_log(self, message, level="info"):
        item = {"time": backend.now(), "level": level, "message": message}
        if not self.demo:
            try:
                item = backend.log_event(message, level)
            except OSError:
                pass
        self.events.append(item)
        self.events = self.events[-200:]
        self.refresh_logs()

    def refresh_logs(self):
        self.logs.setPlainText("\n".join("{}  [{}]  {}".format(item["time"][11:19],
                              {"info": "信息", "error": "错误", "warning": "提示"}.get(item["level"], item["level"]),
                              item["message"]) for item in self.events))
        scrollbar = self.logs.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出运行日志", "YSUNet-运行日志.txt", "文本文件 (*.txt)")
        if path:
            try:
                Path(path).write_text(self.logs.toPlainText(), encoding="utf-8")
                self.notice.setText("日志已导出。")
            except OSError:
                self.notice.setText("日志导出失败，请选择可写目录。")

    def quit_requested(self):
        self.pending_close = True
        self.close()

    def closeEvent(self, event):
        if self.settings["close_to_tray"] and not self.pending_close and self.tray.isVisible():
            self.hide()
            event.ignore()
        elif self.busy:
            self.pending_close = True
            self.notice.setText("当前操作完成后将退出助手。")
            event.ignore()
        else:
            self.timer.stop()
            self.schedule_timer.stop()
            self.tray.hide()
            event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, help="Render an offline demo screenshot and exit.")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setApplicationName("YSUNet")
    lock = None
    if not args.preview:
        backend.STATE.mkdir(exist_ok=True)
        lock = QLockFile(str(backend.STATE / "desktop.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            QMessageBox.information(None, "YSUNet", "校园网助手已经运行，请从任务栏或托盘打开。")
            return 0
    window = Window(demo=bool(args.preview))
    window.show()
    if args.preview:
        def capture():
            window.grab().save(str(args.preview))
            app.quit()
        QTimer.singleShot(200, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
