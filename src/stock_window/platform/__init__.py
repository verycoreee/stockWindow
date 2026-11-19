"""操作系统适配层：对外暴露任务栏定位、全屏检测与全局热键抽象接口。"""

from stock_window.platform.base import (
    HotKeySpec,
    TaskbarMetrics,
    TaskbarPlatformAdapter,
    parse_hotkey_string,
)
from stock_window.platform.win32_taskbar import (
    NullPlatformAdapter,
    Win32TaskbarAdapter,
    create_platform_adapter,
)

__all__ = [
    "HotKeySpec",
    "NullPlatformAdapter",
    "TaskbarMetrics",
    "TaskbarPlatformAdapter",
    "Win32TaskbarAdapter",
    "create_platform_adapter",
    "parse_hotkey_string",
]
