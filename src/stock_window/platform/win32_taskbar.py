"""Windows 11 / Windows 10 任务栏适配实现（纯 ctypes，无需额外第三方原生扩展）。

核心设计考量：
1. Windows 11 任务栏采用 XAML Island 渲染，强行 SetParent 容易被系统重绘盖住或破坏透明度，
   因此采用 `WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE` + 置顶 Z-Order 维护 + 任务栏几何贴靠方案。
2. 通过 `GetDpiForWindow(Shell_TrayWnd)` 换算逻辑像素，避免 125% / 150% / 200% 缩放下错位。
3. 全屏检测显式排除桌面壳窗口与 DWM Cloaked（被系统隐藏的 UWP 幽灵窗口），减少误判隐藏。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from stock_window.platform.base import (
    TaskbarMetrics,
    TaskbarPlatformAdapter,
    parse_hotkey_string,
)

logger = logging.getLogger(__name__)

# Win32 窗口样式与定位常量
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

MONITOR_DEFAULTTONEAREST = 0x00000002
DWMWA_CLOAKED = 14
WM_HOTKEY = 0x0312

# 不应被识别为“全屏应用”的系统外壳窗口类名
_IGNORED_FULLSCREEN_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Progman",
    "WorkerW",
    "Windows.UI.Core.CoreWindow",
    "NotifyIconOverflowWindow",
}


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class NullPlatformAdapter(TaskbarPlatformAdapter):
    """非 Windows 平台或单测环境使用的空实现。"""

    def apply_overlay_style(self, window_handle: int) -> None:
        return

    def raise_above_taskbar(self, window_handle: int) -> None:
        return

    def get_taskbar_metrics(self, fallback_dpr: float = 1.0) -> TaskbarMetrics | None:
        return None

    def is_foreground_fullscreen(self, ignore_handles: set[int] | None = None) -> bool:
        return False

    def register_hotkey(self, hotkey_id: int, hotkey: str) -> bool:
        return False

    def unregister_hotkey(self, hotkey_id: int) -> None:
        return


class Win32TaskbarAdapter(TaskbarPlatformAdapter):
    """Windows 10/11 任务栏贴靠与系统交互实现。"""

    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32
        self._dwmapi = getattr(ctypes.windll, "dwmapi", None)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        """显式声明 64 位安全的 Win32 参数与返回值类型，避免指针截断。"""
        u = self._user32
        is_64bit = ctypes.sizeof(ctypes.c_void_p) == 8

        self._get_window_long_ptr = u.GetWindowLongPtrW if is_64bit else u.GetWindowLongW
        self._set_window_long_ptr = u.SetWindowLongPtrW if is_64bit else u.SetWindowLongW
        self._get_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int]
        self._get_window_long_ptr.restype = ctypes.c_ssize_t
        self._set_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._set_window_long_ptr.restype = ctypes.c_ssize_t

        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowW.restype = wintypes.HWND

        u.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowExW.restype = wintypes.HWND

        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.restype = wintypes.BOOL

        u.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        u.SetWindowPos.restype = wintypes.BOOL

        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL

        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsIconic.restype = wintypes.BOOL

        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND

        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.restype = ctypes.c_int

        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromWindow.restype = wintypes.HANDLE

        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
        u.GetMonitorInfoW.restype = wintypes.BOOL

        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.RegisterHotKey.restype = wintypes.BOOL

        u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u.UnregisterHotKey.restype = wintypes.BOOL

        if hasattr(u, "GetDpiForWindow"):
            u.GetDpiForWindow.argtypes = [wintypes.HWND]
            u.GetDpiForWindow.restype = wintypes.UINT

    def apply_overlay_style(self, window_handle: int) -> None:
        if not window_handle:
            return
        try:
            ex_style = self._get_window_long_ptr(window_handle, GWL_EXSTYLE)
            new_style = (ex_style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
            if new_style != ex_style:
                self._set_window_long_ptr(window_handle, GWL_EXSTYLE, new_style)
            self._user32.SetWindowPos(
                window_handle,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("设置悬浮窗口样式失败: %s", exc)

    def raise_above_taskbar(self, window_handle: int) -> None:
        if not window_handle:
            return
        try:
            self._user32.SetWindowPos(
                window_handle,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("维护任务栏置顶顺序失败: %s", exc)

    def get_taskbar_metrics(self, fallback_dpr: float = 1.0) -> TaskbarMetrics | None:
        hwnd = self._user32.FindWindowW("Shell_TrayWnd", None)
        if not hwnd:
            return None

        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        scale = self._get_window_scale(hwnd, fallback_dpr)
        visible = bool(self._user32.IsWindowVisible(hwnd))

        # 额外查询系统托盘区域宽度，便于“贴靠任务栏右下角”模式避开时间与系统图标
        notify_width = 0
        notify_hwnd = self._user32.FindWindowExW(hwnd, None, "TrayNotifyWnd", None)
        if notify_hwnd:
            notify_rect = wintypes.RECT()
            if self._user32.GetWindowRect(notify_hwnd, ctypes.byref(notify_rect)):
                notify_width = max(0, round((notify_rect.right - notify_rect.left) / scale))

        return TaskbarMetrics(
            left=round(rect.left / scale),
            top=round(rect.top / scale),
            width=max(0, round((rect.right - rect.left) / scale)),
            height=max(0, round((rect.bottom - rect.top) / scale)),
            notify_width=notify_width,
            visible=visible,
        )

    def is_foreground_fullscreen(self, ignore_handles: set[int] | None = None) -> bool:
        fg = self._user32.GetForegroundWindow()
        if not fg:
            return False
        if ignore_handles and int(fg) in ignore_handles:
            return False
        if not self._user32.IsWindowVisible(fg) or self._user32.IsIconic(fg):
            return False
        if self._is_cloaked(fg):
            return False

        class_name = self._get_class_name(fg)
        if class_name in _IGNORED_FULLSCREEN_CLASSES:
            return False

        # 只关注与主任务栏位于同一显示器的全屏窗口，避免副屏全屏误隐藏主屏任务栏条
        taskbar_hwnd = self._user32.FindWindowW("Shell_TrayWnd", None)
        fg_monitor = self._user32.MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST)
        if taskbar_hwnd:
            tb_monitor = self._user32.MonitorFromWindow(taskbar_hwnd, MONITOR_DEFAULTTONEAREST)
            if tb_monitor and fg_monitor and tb_monitor != fg_monitor:
                return False

        mon_info = _MONITORINFO()
        mon_info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not self._user32.GetMonitorInfoW(fg_monitor, ctypes.byref(mon_info)):
            return False

        fg_rect = wintypes.RECT()
        if not self._user32.GetWindowRect(fg, ctypes.byref(fg_rect)):
            return False

        mon = mon_info.rcMonitor
        return (
            fg_rect.left <= mon.left + 1
            and fg_rect.top <= mon.top + 1
            and fg_rect.right >= mon.right - 1
            and fg_rect.bottom >= mon.bottom - 1
        )

    def register_hotkey(self, hotkey_id: int, hotkey: str) -> bool:
        spec = parse_hotkey_string(hotkey)
        if spec is None:
            logger.warning("无法解析全局老板键 '%s'", hotkey)
            return False
        ok = bool(self._user32.RegisterHotKey(None, hotkey_id, spec.modifiers, spec.vk_code))
        if not ok:
            logger.warning("注册全局老板键 '%s' 失败（可能与其他软件热键冲突）", hotkey)
        return ok

    def unregister_hotkey(self, hotkey_id: int) -> None:
        try:
            self._user32.UnregisterHotKey(None, hotkey_id)
        except Exception:  # noqa: BLE001
            pass

    def _get_window_scale(self, hwnd: int, fallback_dpr: float) -> float:
        if hasattr(self._user32, "GetDpiForWindow"):
            dpi = int(self._user32.GetDpiForWindow(hwnd))
            if dpi > 0:
                return dpi / 96.0
        return fallback_dpr if fallback_dpr > 0 else 1.0

    def _get_class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        length = self._user32.GetClassNameW(hwnd, buf, 256)
        return buf.value[:length] if length > 0 else ""

    def _is_cloaked(self, hwnd: int) -> bool:
        """检查窗口是否被 Win10/11 DWM 隐身（Cloaked），防止后台 UWP 容器误触发全屏隐藏。"""
        if self._dwmapi is None:
            return False
        cloaked = wintypes.DWORD(0)
        try:
            hr = self._dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_CLOAKED),
                ctypes.byref(cloaked),
                ctypes.sizeof(cloaked),
            )
            return hr == 0 and cloaked.value != 0
        except Exception:  # noqa: BLE001
            return False


def create_platform_adapter() -> TaskbarPlatformAdapter:
    """根据运行平台返回合适的适配器实例。"""
    if sys.platform == "win32":
        return Win32TaskbarAdapter()
    return NullPlatformAdapter()
