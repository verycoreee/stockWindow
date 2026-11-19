"""任务栏股票条主控件：无边框、透明贴靠、不抢焦点、支持滚轮翻页与解锁拖拽。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QWidget

from stock_window.models.settings import AppearanceConfig, WindowAnchor, WindowConfig, WindowMode
from stock_window.platform.base import TaskbarMetrics, TaskbarPlatformAdapter
from stock_window.services.formatter import FormattedStockView


class TaskbarStockBar(QWidget):
    """显示在 Windows 任务栏左下角（或自定义位置）的轻量股票行情条。"""

    # 对外事件信号，统一交由 app.py（Composition Root）协调处理
    manage_stocks_requested = Signal()
    open_settings_requested = Signal()
    refresh_requested = Signal()
    toggle_lock_requested = Signal(bool)
    hide_requested = Signal()
    quit_requested = Signal()
    dock_offset_changed = Signal(int, int)
    free_position_changed = Signal(int, int)

    def __init__(self, platform_adapter: TaskbarPlatformAdapter) -> None:
        super().__init__(None)
        self._platform = platform_adapter
        self._views: list[FormattedStockView] = []
        self._appearance = AppearanceConfig()
        self._window_cfg = WindowConfig()
        self._page_start = 0

        # 解锁拖拽状态
        self._dragging = False
        self._drag_offset = QPoint()

        self._setup_window_flags()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 2, 8, 2)
        self._layout.setSpacing(self._appearance.item_spacing)
        self._labels: list[QLabel] = []

    def _setup_window_flags(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # 窗口句柄创建后立刻附加 Win32 WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self._platform.apply_overlay_style(int(self.winId()))

    def update_state(
        self,
        views: list[FormattedStockView],
        appearance: AppearanceConfig,
        window_cfg: WindowConfig,
        reposition: bool = True,
    ) -> None:
        """刷新展示条目与样式，并按需重新对齐任务栏坐标。"""
        self._views = list(views)
        self._appearance = appearance
        self._window_cfg = window_cfg

        if self._views:
            self._page_start %= len(self._views)
        else:
            self._page_start = 0

        self._rebuild_labels()
        self.update()
        if reposition and not self._dragging:
            self.reposition()

    def advance_page(self, step: int = 1) -> None:
        """向前或向后翻页（用于鼠标滚轮切换与自动轮播）。"""
        max_items = max(1, self._window_cfg.max_visible_items)
        if len(self._views) <= max_items:
            return
        self._page_start = (self._page_start + step) % len(self._views)
        self._rebuild_labels()
        self.reposition()

    def reposition(self) -> None:
        """按当前窗口模式计算逻辑坐标并移动窗口。"""
        if self._dragging:
            return

        if self._window_cfg.mode == WindowMode.FREE_FLOAT.value:
            self.move(self._window_cfg.free_x, self._window_cfg.free_y)
            return

        metrics = self._resolve_taskbar_metrics()
        if metrics is None:
            return

        # 高度控制在任务栏高度之内，避免上下溢出挡住应用窗口
        target_height = min(max(24, self.sizeHint().height()), max(24, metrics.height - 4))
        target_width = max(80, self.sizeHint().width())
        self.resize(target_width, target_height)

        if self._window_cfg.anchor == WindowAnchor.BOTTOM_RIGHT.value:
            # 贴靠任务栏右侧系统托盘左边
            x = metrics.right - metrics.notify_width - target_width - self._window_cfg.offset_x
        else:
            # 默认贴靠任务栏左下角
            x = metrics.left + self._window_cfg.offset_x

        y = metrics.top + (metrics.height - target_height) // 2 + self._window_cfg.offset_y
        self.move(x, y)

    def ensure_above_taskbar(self) -> None:
        """维持位于任务栏上方且不抢焦点。"""
        if self.isVisible():
            self._platform.raise_above_taskbar(int(self.winId()))

    def _resolve_taskbar_metrics(self) -> TaskbarMetrics | None:
        """优先读取 Win32 任务栏精确几何，失败时回退到 Qt 主屏工作区差值。"""
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        metrics = self._platform.get_taskbar_metrics(fallback_dpr=dpr)
        if metrics is not None and metrics.height > 0:
            return metrics

        if screen is None:
            return None
        geom = screen.geometry()
        avail = screen.availableGeometry()
        tb_height = max(40, geom.bottom() - avail.bottom())
        return TaskbarMetrics(
            left=geom.left(),
            top=geom.bottom() - tb_height + 1,
            width=geom.width(),
            height=tb_height,
            notify_width=180,
            visible=True,
        )

    def _visible_slice(self) -> list[FormattedStockView]:
        if not self._views:
            return []
        max_items = max(1, self._window_cfg.max_visible_items)
        if len(self._views) <= max_items:
            return self._views
        return [self._views[(self._page_start + idx) % len(self._views)] for idx in range(max_items)]

    def _rebuild_labels(self) -> None:
        """重建可见标签集合，保持字号、颜色与 Tooltip 与最新状态同步。"""
        while self._layout.count():
            child = self._layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._labels.clear()

        self._layout.setSpacing(self._appearance.item_spacing)
        font = QFont(self._appearance.font_family, self._appearance.font_size)
        font.setBold(self._appearance.font_bold)

        visible_views = self._visible_slice()
        if not visible_views:
            placeholder = QLabel("StockWindow (右键添加)", self)
            placeholder.setFont(font)
            placeholder.setStyleSheet(f"color: {self._appearance.monochrome_color}; background: transparent;")
            placeholder.setToolTip("右键打开「自选管理」搜索并添加股票")
            self._layout.addWidget(placeholder)
            self._labels.append(placeholder)
        else:
            for view in visible_views:
                label = QLabel(view.text, self)
                label.setFont(font)
                label.setStyleSheet(f"color: {view.color}; background: transparent;")
                label.setToolTip(view.tooltip)
                self._layout.addWidget(label)
                self._labels.append(label)

        self.adjustSize()

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制背景：即使背景全透明也绘制 1/255 极微弱底色，保证鼠标右键/滚轮命中不穿透。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg = QColor(self._appearance.background_color)
        if not bg.isValid():
            bg = QColor("#1F1F1F")
        # 关键细节：Windows 透明窗口在 alpha==0 区域会穿透鼠标事件，设为 >=1 人眼不可见但可接收点击
        alpha = max(1, min(255, int(self._appearance.background_alpha)))
        bg.setAlpha(alpha)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(self.rect(), 4, 4)

        # 未锁定拖拽时绘制极淡虚线框，提醒用户当前可拖动
        if not self._window_cfg.locked:
            border = QColor(self._appearance.monochrome_color)
            border.setAlpha(110)
            painter.setPen(border)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta < 0:
            self.advance_page(1)
        elif delta > 0:
            self.advance_page(-1)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._window_cfg.locked:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            target = event.globalPosition().toPoint() - self._drag_offset
            self.move(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.unsetCursor()
            self._commit_dragged_position()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _commit_dragged_position(self) -> None:
        """拖拽松手后，根据当前模式换算并持久化新坐标或任务栏偏移量。"""
        pos = self.pos()
        if self._window_cfg.mode == WindowMode.FREE_FLOAT.value:
            self.free_position_changed.emit(pos.x(), pos.y())
            return

        metrics = self._resolve_taskbar_metrics()
        if metrics is None:
            self.free_position_changed.emit(pos.x(), pos.y())
            return

        if self._window_cfg.anchor == WindowAnchor.BOTTOM_RIGHT.value:
            new_offset_x = metrics.right - metrics.notify_width - self.width() - pos.x()
        else:
            new_offset_x = pos.x() - metrics.left
        center_y = metrics.top + (metrics.height - self.height()) // 2
        new_offset_y = pos.y() - center_y
        self.dock_offset_changed.emit(int(new_offset_x), int(new_offset_y))

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        menu = QMenu(self)

        act_manage = QAction("管理自选股（名称/拼音搜索）...", menu)
        act_manage.triggered.connect(self.manage_stocks_requested.emit)
        menu.addAction(act_manage)

        act_settings = QAction("外观与行为设置...", menu)
        act_settings.triggered.connect(self.open_settings_requested.emit)
        menu.addAction(act_settings)

        act_refresh = QAction("立即刷新行情", menu)
        act_refresh.triggered.connect(self.refresh_requested.emit)
        menu.addAction(act_refresh)

        menu.addSeparator()

        act_lock = QAction("锁定位置（防误拖）", menu)
        act_lock.setCheckable(True)
        act_lock.setChecked(self._window_cfg.locked)
        act_lock.triggered.connect(self.toggle_lock_requested.emit)
        menu.addAction(act_lock)

        boss_hint = f"（{self._window_cfg.boss_key}）" if self._window_cfg.boss_key_enabled else ""
        act_hide = QAction(f"隐藏任务栏条{boss_hint}", menu)
        act_hide.triggered.connect(self.hide_requested.emit)
        menu.addAction(act_hide)

        menu.addSeparator()

        act_quit = QAction("退出 StockWindow", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        menu.exec(event.globalPos())
