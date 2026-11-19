"""应用配置数据模型：外观配色、任务栏窗口行为、轮询数据源与总配置。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from stock_window.models.stock import StockItem


class ColorMode(str, Enum):
    """任务栏文字配色策略。"""

    # 低调纯色模式：忽略涨跌方向，全部使用统一的柔和颜色（默认，适合办公场景）
    MONOCHROME = "monochrome"
    # 自定义涨跌色模式：分别使用 up / down / flat 三种用户自定义颜色
    CUSTOM_TREND = "custom_trend"


class WindowMode(str, Enum):
    """窗口定位模式。"""

    # 贴靠 Windows 任务栏（自动跟随任务栏坐标与高度）
    DOCK_TASKBAR = "dock_taskbar"
    # 自由悬浮在桌面任意位置
    FREE_FLOAT = "free_float"


class WindowAnchor(str, Enum):
    """贴靠任务栏时的基准停靠边。"""

    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


@dataclass(slots=True)
class AppearanceConfig:
    """外观与文本展示配置（全部支持在设置弹窗中实时调整）。"""

    color_mode: str = ColorMode.MONOCHROME.value
    # 默认柔和浅灰白：在 Win11 深色任务栏下清晰但不刺眼
    monochrome_color: str = "#D8DCE2"
    # 自定义涨跌模式下也默认采用低饱和色，用户可通过取色器自由调整
    up_color: str = "#D98A8A"
    down_color: str = "#7DB89B"
    flat_color: str = "#B8BFC8"

    # 背景色与透明度（0 = 完全透明融入任务栏，255 = 不透明）
    background_color: str = "#1F1F1F"
    background_alpha: int = 0

    font_family: str = "Microsoft YaHei UI"
    font_size: int = 10
    font_bold: bool = False
    item_spacing: int = 14

    # 展示字段开关：允许极简模式（例如只显示别名 + 涨跌幅）
    show_name: bool = True
    show_price: bool = True
    show_change_percent: bool = True
    show_change_amount: bool = False
    show_sign_prefix: bool = True
    auto_precision: bool = True
    decimal_places: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "color_mode": self.color_mode,
            "monochrome_color": self.monochrome_color,
            "up_color": self.up_color,
            "down_color": self.down_color,
            "flat_color": self.flat_color,
            "background_color": self.background_color,
            "background_alpha": self.background_alpha,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "font_bold": self.font_bold,
            "item_spacing": self.item_spacing,
            "show_name": self.show_name,
            "show_price": self.show_price,
            "show_change_percent": self.show_change_percent,
            "show_change_amount": self.show_change_amount,
            "show_sign_prefix": self.show_sign_prefix,
            "auto_precision": self.auto_precision,
            "decimal_places": self.decimal_places,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AppearanceConfig:
        defaults = cls()
        if not isinstance(raw, dict):
            return defaults

        color_mode = str(raw.get("color_mode", defaults.color_mode))
        if color_mode not in {m.value for m in ColorMode}:
            color_mode = defaults.color_mode

        return cls(
            color_mode=color_mode,
            monochrome_color=str(raw.get("monochrome_color", defaults.monochrome_color)),
            up_color=str(raw.get("up_color", defaults.up_color)),
            down_color=str(raw.get("down_color", defaults.down_color)),
            flat_color=str(raw.get("flat_color", defaults.flat_color)),
            background_color=str(raw.get("background_color", defaults.background_color)),
            background_alpha=_clamp_int(raw.get("background_alpha", defaults.background_alpha), 0, 255),
            font_family=str(raw.get("font_family", defaults.font_family)),
            font_size=_clamp_int(raw.get("font_size", defaults.font_size), 7, 24),
            font_bold=bool(raw.get("font_bold", defaults.font_bold)),
            item_spacing=_clamp_int(raw.get("item_spacing", defaults.item_spacing), 4, 48),
            show_name=bool(raw.get("show_name", defaults.show_name)),
            show_price=bool(raw.get("show_price", defaults.show_price)),
            show_change_percent=bool(raw.get("show_change_percent", defaults.show_change_percent)),
            show_change_amount=bool(raw.get("show_change_amount", defaults.show_change_amount)),
            show_sign_prefix=bool(raw.get("show_sign_prefix", defaults.show_sign_prefix)),
            auto_precision=bool(raw.get("auto_precision", defaults.auto_precision)),
            decimal_places=_clamp_int(raw.get("decimal_places", defaults.decimal_places), 0, 4),
        )


@dataclass(slots=True)
class WindowConfig:
    """任务栏贴靠、翻页轮播与隐私隐藏相关配置。"""

    mode: str = WindowMode.DOCK_TASKBAR.value
    anchor: str = WindowAnchor.BOTTOM_LEFT.value
    # 距离任务栏左边缘/右托盘边缘的水平逻辑像素偏移（默认 12px 贴近左下角）
    offset_x: int = 12
    # 相对任务栏垂直中线的纵向微调
    offset_y: int = 0
    free_x: int = 120
    free_y: int = 120
    locked: bool = True
    max_visible_items: int = 3
    # 自动轮播间隔（秒），0 表示关闭自动轮播，改用鼠标滚轮手动翻页
    rotate_interval_sec: int = 0
    hide_on_fullscreen: bool = True
    boss_key_enabled: bool = True
    boss_key: str = "Ctrl+Alt+H"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "anchor": self.anchor,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "free_x": self.free_x,
            "free_y": self.free_y,
            "locked": self.locked,
            "max_visible_items": self.max_visible_items,
            "rotate_interval_sec": self.rotate_interval_sec,
            "hide_on_fullscreen": self.hide_on_fullscreen,
            "boss_key_enabled": self.boss_key_enabled,
            "boss_key": self.boss_key,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> WindowConfig:
        defaults = cls()
        if not isinstance(raw, dict):
            return defaults

        mode = str(raw.get("mode", defaults.mode))
        if mode not in {m.value for m in WindowMode}:
            mode = defaults.mode

        anchor = str(raw.get("anchor", defaults.anchor))
        if anchor not in {a.value for a in WindowAnchor}:
            anchor = defaults.anchor

        return cls(
            mode=mode,
            anchor=anchor,
            offset_x=_clamp_int(raw.get("offset_x", defaults.offset_x), -2000, 4000),
            offset_y=_clamp_int(raw.get("offset_y", defaults.offset_y), -200, 200),
            free_x=_clamp_int(raw.get("free_x", defaults.free_x), -4000, 8000),
            free_y=_clamp_int(raw.get("free_y", defaults.free_y), -4000, 8000),
            locked=bool(raw.get("locked", defaults.locked)),
            max_visible_items=_clamp_int(raw.get("max_visible_items", defaults.max_visible_items), 1, 10),
            rotate_interval_sec=_clamp_int(raw.get("rotate_interval_sec", defaults.rotate_interval_sec), 0, 300),
            hide_on_fullscreen=bool(raw.get("hide_on_fullscreen", defaults.hide_on_fullscreen)),
            boss_key_enabled=bool(raw.get("boss_key_enabled", defaults.boss_key_enabled)),
            boss_key=str(raw.get("boss_key", defaults.boss_key)).strip() or defaults.boss_key,
        )


@dataclass(slots=True)
class PollingConfig:
    """数据源与轮询策略配置（预留 provider 切换字段以便后续扩展）。"""

    provider: str = "tencent"
    search_provider: str = "tencent"
    interval_sec: int = 5
    timeout_sec: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "search_provider": self.search_provider,
            "interval_sec": self.interval_sec,
            "timeout_sec": self.timeout_sec,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PollingConfig:
        defaults = cls()
        if not isinstance(raw, dict):
            return defaults

        try:
            timeout = float(raw.get("timeout_sec", defaults.timeout_sec))
        except (TypeError, ValueError):
            timeout = defaults.timeout_sec
        timeout = max(1.0, min(30.0, timeout))

        return cls(
            provider=str(raw.get("provider", defaults.provider)).strip() or defaults.provider,
            search_provider=str(raw.get("search_provider", defaults.search_provider)).strip()
            or defaults.search_provider,
            interval_sec=_clamp_int(raw.get("interval_sec", defaults.interval_sec), 2, 300),
            timeout_sec=timeout,
        )


@dataclass(slots=True)
class AppConfig:
    """应用总配置根对象。"""

    schema_version: int = 1
    stocks: list[StockItem] = field(default_factory=list)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)

    @classmethod
    def default(cls) -> AppConfig:
        """构造首次启动默认配置：仅放 1 条公开指数作为示例，不含个人自选。"""
        return cls(
            schema_version=1,
            stocks=[
                StockItem(
                    symbol="sh000001",
                    name="上证指数",
                    alias="上证",
                    market="SH",
                    visible=True,
                ),
            ],
            appearance=AppearanceConfig(),
            window=WindowConfig(),
            polling=PollingConfig(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stocks": [item.to_dict() for item in self.stocks],
            "appearance": self.appearance.to_dict(),
            "window": self.window.to_dict(),
            "polling": self.polling.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AppConfig:
        if not isinstance(raw, dict):
            return cls.default()

        raw_stocks = raw.get("stocks")
        stocks: list[StockItem] = []
        if isinstance(raw_stocks, list):
            seen: set[str] = set()
            for entry in raw_stocks:
                if not isinstance(entry, dict):
                    continue
                item = StockItem.from_dict(entry)
                if item.symbol and item.symbol not in seen:
                    stocks.append(item)
                    seen.add(item.symbol)

        return cls(
            schema_version=_clamp_int(raw.get("schema_version", 1), 1, 100),
            stocks=stocks,
            appearance=AppearanceConfig.from_dict(raw.get("appearance")),
            window=WindowConfig.from_dict(raw.get("window")),
            polling=PollingConfig.from_dict(raw.get("polling")),
        )


def _clamp_int(value: Any, low: int, high: int) -> int:
    """防御性整数转换并限制在 [low, high] 范围内，防止手动改坏配置文件导致异常。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, parsed))
