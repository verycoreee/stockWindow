"""系统托盘图标与菜单：即使任务栏股票条被隐藏，也可随时通过托盘恢复与配置。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from stock_window import __app_name__, __version__


def create_minimal_tray_icon() -> QIcon:
    """用代码动态绘制极简低饱和折线图标，避免仓库中维护二进制图标资产。"""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 深灰圆角底板 + 柔和灰白折线，风格低调
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2D3138"))
    painter.drawRoundedRect(2, 2, 28, 28, 6, 6)

    pen = QPen(QColor("#D8DCE2"))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    points = QPolygonF(
        [
            QPointF(7, 21),
            QPointF(13, 15),
            QPointF(18, 18),
            QPointF(25, 10),
        ]
    )
    painter.drawPolyline(points)
    painter.end()
    return QIcon(pixmap)


class StockTrayIcon(QSystemTrayIcon):
    """右下角系统托盘入口。"""

    toggle_visible_requested = Signal()
    manage_stocks_requested = Signal()
    open_settings_requested = Signal()
    refresh_requested = Signal()
    toggle_lock_requested = Signal(bool)
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__(create_minimal_tray_icon())
        self.setToolTip(f"{__app_name__} v{__version__}")

        self._menu = QMenu()
        self._act_toggle_visible = QAction("隐藏 / 显示任务栏条", self._menu)
        self._act_toggle_visible.triggered.connect(self.toggle_visible_requested.emit)
        self._menu.addAction(self._act_toggle_visible)

        self._act_manage = QAction("管理自选股（名称/拼音搜索）...", self._menu)
        self._act_manage.triggered.connect(self.manage_stocks_requested.emit)
        self._menu.addAction(self._act_manage)

        self._act_settings = QAction("外观与行为设置...", self._menu)
        self._act_settings.triggered.connect(self.open_settings_requested.emit)
        self._menu.addAction(self._act_settings)

        self._act_refresh = QAction("立即刷新行情", self._menu)
        self._act_refresh.triggered.connect(self.refresh_requested.emit)
        self._menu.addAction(self._act_refresh)

        self._menu.addSeparator()

        self._act_lock = QAction("锁定位置（防误拖）", self._menu)
        self._act_lock.setCheckable(True)
        self._act_lock.setChecked(True)
        self._act_lock.triggered.connect(self.toggle_lock_requested.emit)
        self._menu.addAction(self._act_lock)

        self._menu.addSeparator()

        self._act_quit = QAction("退出", self._menu)
        self._act_quit.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(self._act_quit)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def sync_state(self, visible: bool, locked: bool, boss_key_hint: str = "") -> None:
        suffix = f"（{boss_key_hint}）" if boss_key_hint else ""
        self._act_toggle_visible.setText(f"{'隐藏' if visible else '显示'}任务栏条{suffix}")
        self._act_lock.setChecked(locked)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_visible_requested.emit()
