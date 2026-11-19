"""操作系统适配抽象层（扩展点 3）。

所有 Win32 API 细节都隐藏在本层实现之后，保证 UI 控件可以跨版本、可测试地演进。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Windows RegisterHotKey 修饰键常量
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000


@dataclass(slots=True)
class TaskbarMetrics:
    """任务栏在逻辑坐标系下的几何信息（单位：逻辑像素，与 Qt 坐标系一致）。"""

    left: int
    top: int
    width: int
    height: int
    notify_width: int = 0
    visible: bool = True

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(slots=True)
class HotKeySpec:
    """解析后的全局快捷键定义。"""

    modifiers: int
    vk_code: int
    raw: str


def parse_hotkey_string(hotkey: str) -> HotKeySpec | None:
    """将类似 'Ctrl+Alt+H' 的快捷键字符串解析为 Windows 修饰键与虚拟键码。"""
    if not hotkey or not hotkey.strip():
        return None

    modifiers = 0
    vk_code: int | None = None
    tokens = [part.strip().upper() for part in hotkey.split("+") if part.strip()]
    if not tokens:
        return None

    for token in tokens:
        if token in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif token == "ALT":
            modifiers |= MOD_ALT
        elif token == "SHIFT":
            modifiers |= MOD_SHIFT
        elif token in {"WIN", "SUPER", "META"}:
            modifiers |= MOD_WIN
        elif len(token) == 1 and ("A" <= token <= "Z" or "0" <= token <= "9"):
            vk_code = ord(token)
        elif token.startswith("F") and token[1:].isdigit():
            fn = int(token[1:])
            if 1 <= fn <= 12:
                vk_code = 0x70 + (fn - 1)  # VK_F1 = 0x70
        else:
            return None

    if vk_code is None or modifiers == 0:
        return None

    return HotKeySpec(modifiers=modifiers | MOD_NOREPEAT, vk_code=vk_code, raw=hotkey.strip())


class TaskbarPlatformAdapter(ABC):
    """任务栏窗口贴靠、防抢焦点与热键能力的平台抽象接口。"""

    @abstractmethod
    def apply_overlay_style(self, window_handle: int) -> None:
        """为指定窗口附加无焦点、不进 Alt+Tab 的悬浮工具窗样式。"""

    @abstractmethod
    def raise_above_taskbar(self, window_handle: int) -> None:
        """在不抢焦点的前提下，维持窗口 Z-Order 位于任务栏之上。"""

    @abstractmethod
    def get_taskbar_metrics(self, fallback_dpr: float = 1.0) -> TaskbarMetrics | None:
        """查询当前主任务栏的逻辑位置、尺寸及右侧托盘区宽度。"""

    @abstractmethod
    def is_foreground_fullscreen(self, ignore_handles: set[int] | None = None) -> bool:
        """检测当前是否有全屏应用覆盖了任务栏所在屏幕（用于自动隐藏）。"""

    @abstractmethod
    def register_hotkey(self, hotkey_id: int, hotkey: str) -> bool:
        """注册线程级全局快捷键（老板键）。"""

    @abstractmethod
    def unregister_hotkey(self, hotkey_id: int) -> None:
        """注销全局快捷键。"""
