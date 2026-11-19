"""应用装配器（Composition Root）：统一接线配置、数据源、业务服务、平台适配与 UI 控件。"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QApplication

from stock_window.config.store import ConfigStore
from stock_window.models.settings import AppConfig
from stock_window.models.stock import StockItem
from stock_window.platform.win32_taskbar import WM_HOTKEY, create_platform_adapter
from stock_window.providers.registry import ProviderRegistry, create_default_registry
from stock_window.services.formatter import DisplayFormatter, FormattedStockView
from stock_window.services.quote_service import QuoteService, QuoteSnapshotResult
from stock_window.ui.settings_dialog import SettingsDialog
from stock_window.ui.stock_manager_dialog import StockManagerDialog
from stock_window.ui.taskbar_bar import TaskbarStockBar
from stock_window.ui.tray import StockTrayIcon

logger = logging.getLogger(__name__)

_BOSS_HOTKEY_ID = 0x5701


class _RefreshSignals(QObject):
    """后台行情刷新结果信号。"""

    completed = Signal(object)


class _QuoteRefreshWorker(QRunnable):
    """在后台线程池执行 HTTP 行情拉取，保证任务栏 UI 与菜单永不卡顿。"""

    def __init__(
        self,
        quote_service: QuoteService,
        items: list[StockItem],
        signals: _RefreshSignals,
    ) -> None:
        super().__init__()
        self._quote_service = quote_service
        self._items = items
        self._signals = signals

    def run(self) -> None:
        result = self._quote_service.refresh_quotes(self._items)
        self._signals.completed.emit(result)


class _WinHotkeyEventFilter(QAbstractNativeEventFilter):
    """拦截 Windows 原生 WM_HOTKEY 消息以响应全局老板键。"""

    def __init__(self, hotkey_id: int, on_triggered) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._on_triggered = on_triggered

    def nativeEventFilter(self, event_type, message):  # type: ignore[override]
        if sys.platform == "win32" and event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    self._on_triggered()
                    return True, 0
            except Exception as exc:  # noqa: BLE001
                logger.debug("解析 WM_HOTKEY 原生事件失败: %s", exc)
        return False, 0


class StockWindowApp(QObject):
    """主应用协调器：负责各层依赖注入、定时器调度、状态同步与优雅退出。"""

    def __init__(
        self,
        qt_app: QApplication,
        config_path: Path,
        registry: ProviderRegistry | None = None,
    ) -> None:
        super().__init__()
        self._qt_app = qt_app
        self._qt_app.setQuitOnLastWindowClosed(False)

        self._config_store = ConfigStore(config_path)
        self._config: AppConfig = self._config_store.load()
        self._registry = registry or create_default_registry()
        self._formatter = DisplayFormatter()
        self._platform = create_platform_adapter()

        self._quote_service = self._build_quote_service(self._config)
        self._thread_pool = QThreadPool.globalInstance()
        self._refresh_in_flight = False

        # 用户显式隐藏状态（按老板键或点菜单隐藏后为 True，全屏退出时不会擅自弹出）
        self._manually_hidden = False
        self._fullscreen_hidden = False

        self._bar = TaskbarStockBar(self._platform)
        self._tray = StockTrayIcon()
        self._manager_dialog: StockManagerDialog | None = None
        self._settings_dialog: SettingsDialog | None = None

        # 全局老板键原生消息过滤器
        self._hotkey_registered = False
        self._hotkey_filter = _WinHotkeyEventFilter(_BOSS_HOTKEY_ID, self._toggle_manual_visibility)
        self._qt_app.installNativeEventFilter(self._hotkey_filter)

        # 三类职责清晰的定时器：行情轮询 / 任务栏置顶与全屏守护 / 多只股票自动轮播
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.trigger_refresh)

        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(800)
        self._watchdog_timer.timeout.connect(self._on_watchdog_tick)

        self._rotate_timer = QTimer(self)
        self._rotate_timer.timeout.connect(lambda: self._bar.advance_page(1))

        self._bind_signals()

    def start(self) -> None:
        """启动任务栏条、托盘图标、全局热键与定时轮询。"""
        self._apply_runtime_policies()
        self._render_current_quotes()
        self._bar.show()
        self._bar.reposition()
        self._tray.show()
        self._sync_tray_state()

        self._watchdog_timer.start()
        self.trigger_refresh()

    def shutdown(self) -> None:
        """清理热键、定时器、网络连接并退出事件循环。"""
        self._poll_timer.stop()
        self._watchdog_timer.stop()
        self._rotate_timer.stop()
        if self._hotkey_registered:
            self._platform.unregister_hotkey(_BOSS_HOTKEY_ID)
            self._hotkey_registered = False
        self._qt_app.removeNativeEventFilter(self._hotkey_filter)
        self._tray.hide()
        self._bar.close()
        self._quote_service.close()
        self._qt_app.quit()

    def _build_quote_service(self, config: AppConfig) -> QuoteService:
        """根据配置从注册中心创建行情与搜索数据源（配置失效时回退 tencent）。"""
        try:
            quote_provider = self._registry.create_quote_provider(config.polling.provider)
        except KeyError:
            logger.warning("未找到行情源 %s，自动回退 tencent", config.polling.provider)
            quote_provider = self._registry.create_quote_provider("tencent")

        try:
            search_provider = self._registry.create_search_provider(config.polling.search_provider)
        except KeyError:
            logger.warning("未找到搜索源 %s，自动回退 tencent", config.polling.search_provider)
            search_provider = self._registry.create_search_provider("tencent")

        return QuoteService(
            quote_provider=quote_provider,
            search_provider=search_provider,
            timeout=config.polling.timeout_sec,
        )

    def _bind_signals(self) -> None:
        # 任务栏主控件信号
        self._bar.manage_stocks_requested.connect(self._open_stock_manager)
        self._bar.open_settings_requested.connect(self._open_settings)
        self._bar.refresh_requested.connect(self.trigger_refresh)
        self._bar.toggle_lock_requested.connect(self._set_locked)
        self._bar.hide_requested.connect(self._toggle_manual_visibility)
        self._bar.quit_requested.connect(self.shutdown)
        self._bar.dock_offset_changed.connect(self._on_dock_offset_changed)
        self._bar.free_position_changed.connect(self._on_free_position_changed)

        # 系统托盘信号
        self._tray.toggle_visible_requested.connect(self._toggle_manual_visibility)
        self._tray.manage_stocks_requested.connect(self._open_stock_manager)
        self._tray.open_settings_requested.connect(self._open_settings)
        self._tray.refresh_requested.connect(self.trigger_refresh)
        self._tray.toggle_lock_requested.connect(self._set_locked)
        self._tray.quit_requested.connect(self.shutdown)

        # 监听屏幕分辨率 / DPI 变化，及时重新贴靠任务栏
        primary = self._qt_app.primaryScreen()
        if primary is not None:
            primary.geometryChanged.connect(lambda _rect: self._bar.reposition())
            primary.availableGeometryChanged.connect(lambda _rect: self._bar.reposition())

    def trigger_refresh(self) -> None:
        """异步触发一次行情拉取（防并发堆积）。"""
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True

        signals = _RefreshSignals()
        signals.completed.connect(self._on_refresh_completed)
        items_snapshot = [StockItem.from_dict(s.to_dict()) for s in self._config.stocks]
        worker = _QuoteRefreshWorker(self._quote_service, items_snapshot, signals)
        worker._signals_ref = signals  # type: ignore[attr-defined]
        self._thread_pool.start(worker)

    def _on_refresh_completed(self, result: QuoteSnapshotResult) -> None:
        self._refresh_in_flight = False
        if result.error:
            logger.debug("本轮行情刷新异常（沿用缓存）: %s", result.error)
        self._render_current_quotes()

    def _render_current_quotes(self) -> None:
        """使用 DisplayFormatter 将当前可见标的与行情缓存转为视图模型并交给主控件渲染。"""
        quotes = self._quote_service.get_cached_quotes()
        views: list[FormattedStockView] = []
        for item in self._config.stocks:
            if not item.visible:
                continue
            views.append(self._formatter.format_item(item, quotes.get(item.symbol), self._config.appearance))
        self._bar.update_state(views, self._config.appearance, self._config.window, reposition=True)

    def _apply_runtime_policies(self) -> None:
        """按最新配置同步轮询频率、轮播定时器与全局老板键。"""
        self._poll_timer.setInterval(max(2, self._config.polling.interval_sec) * 1000)
        if not self._poll_timer.isActive():
            self._poll_timer.start()

        rotate_sec = self._config.window.rotate_interval_sec
        if rotate_sec > 0:
            self._rotate_timer.setInterval(rotate_sec * 1000)
            self._rotate_timer.start()
        else:
            self._rotate_timer.stop()

        # 重新注册全局老板键
        if self._hotkey_registered:
            self._platform.unregister_hotkey(_BOSS_HOTKEY_ID)
            self._hotkey_registered = False
        if self._config.window.boss_key_enabled:
            self._hotkey_registered = self._platform.register_hotkey(
                _BOSS_HOTKEY_ID,
                self._config.window.boss_key,
            )

    def _on_watchdog_tick(self) -> None:
        """周期维护窗口可见性与任务栏上方 Z-Order，处理全屏应用自动避让。"""
        if self._manually_hidden:
            if self._bar.isVisible():
                self._bar.hide()
            return

        if self._config.window.hide_on_fullscreen:
            ignore_handles = {int(self._bar.winId())}
            if self._manager_dialog is not None and self._manager_dialog.isVisible():
                ignore_handles.add(int(self._manager_dialog.winId()))
            if self._settings_dialog is not None and self._settings_dialog.isVisible():
                ignore_handles.add(int(self._settings_dialog.winId()))

            is_fs = self._platform.is_foreground_fullscreen(ignore_handles=ignore_handles)
            if is_fs:
                self._fullscreen_hidden = True
                if self._bar.isVisible():
                    self._bar.hide()
                return
            if self._fullscreen_hidden:
                self._fullscreen_hidden = False
                self._bar.show()
                self._bar.reposition()

        if not self._bar.isVisible():
            self._bar.show()
            self._bar.reposition()
        self._bar.ensure_above_taskbar()

    def _toggle_manual_visibility(self) -> None:
        self._manually_hidden = not self._manually_hidden
        if self._manually_hidden:
            self._bar.hide()
        else:
            self._fullscreen_hidden = False
            self._bar.show()
            self._bar.reposition()
            self._bar.ensure_above_taskbar()
        self._sync_tray_state()

    def _set_locked(self, locked: bool) -> None:
        self._config.window.locked = bool(locked)
        self._config_store.save(self._config)
        self._render_current_quotes()
        self._sync_tray_state()

    def _on_dock_offset_changed(self, offset_x: int, offset_y: int) -> None:
        self._config.window.offset_x = offset_x
        self._config.window.offset_y = offset_y
        self._config_store.save(self._config)
        self._render_current_quotes()

    def _on_free_position_changed(self, x: int, y: int) -> None:
        self._config.window.free_x = x
        self._config.window.free_y = y
        self._config_store.save(self._config)

    def _open_stock_manager(self) -> None:
        if self._manager_dialog is not None and self._manager_dialog.isVisible():
            self._manager_dialog.raise_()
            self._manager_dialog.activateWindow()
            return

        dialog = StockManagerDialog(
            stocks=self._config.stocks,
            search_fn=self._quote_service.search_stocks,
        )
        self._manager_dialog = dialog
        if dialog.exec():
            self._config.stocks = dialog.get_stocks()
            self._config_store.save(self._config)
            self._render_current_quotes()
            self.trigger_refresh()
        self._manager_dialog = None

    def _open_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return

        dialog = SettingsDialog(
            config=self._config,
            quote_providers=self._registry.quote_provider_names,
            search_providers=self._registry.search_provider_names,
            formatter=self._formatter,
        )
        dialog.config_applied.connect(self._apply_new_config)
        self._settings_dialog = dialog
        dialog.exec()
        self._settings_dialog = None

    def _apply_new_config(self, new_config: AppConfig) -> None:
        old_polling = self._config.polling
        # 保留当前最新自选列表，防止用户在开着设置框时通过别处改动了自选
        new_config.stocks = self._config.stocks
        self._config = new_config
        self._config_store.save(self._config)

        # 若数据源名称或超时变化，热更新 QuoteService 中的 Provider 实例
        if (
            old_polling.provider != new_config.polling.provider
            or old_polling.search_provider != new_config.polling.search_provider
            or old_polling.timeout_sec != new_config.polling.timeout_sec
        ):
            q_prov = self._registry.create_quote_provider(new_config.polling.provider)
            s_prov = self._registry.create_search_provider(new_config.polling.search_provider)
            self._quote_service.update_providers(q_prov, s_prov, timeout=new_config.polling.timeout_sec)

        self._apply_runtime_policies()
        self._render_current_quotes()
        self._sync_tray_state()
        self.trigger_refresh()

    def _sync_tray_state(self) -> None:
        hint = self._config.window.boss_key if self._config.window.boss_key_enabled else ""
        self._tray.sync_state(
            visible=not self._manually_hidden,
            locked=self._config.window.locked,
            boss_key_hint=hint,
        )
