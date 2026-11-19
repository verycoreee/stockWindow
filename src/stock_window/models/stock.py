"""股票相关核心数据模型（自选配置、实时行情、模糊搜索候选）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class StockItem:
    """用户自选列表中的单条标的配置。

    Attributes:
        symbol: 统一内部行情代码（如 sh000001 / sz000001 / hk00700 / usAAPL）。
        name: 标的官方名称（如 贵州茅台）。
        alias: 用户自定义的低调简称或代号（如 MT），为空时回退使用 name。
        market: 市场标识（SH / SZ / BJ / HK / US 等），仅用于分组与展示。
        visible: 是否在任务栏股票条中展示（允许保留在列表但暂时隐藏）。
    """

    symbol: str
    name: str
    alias: str = ""
    market: str = ""
    visible: bool = True

    @property
    def display_name(self) -> str:
        """优先返回用户设置的低调别名，未设置时返回官方名称或代码。"""
        alias = self.alias.strip()
        if alias:
            return alias
        return self.name.strip() or self.symbol

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "alias": self.alias,
            "market": self.market,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> StockItem:
        symbol = str(raw.get("symbol", "")).strip()
        name = str(raw.get("name", symbol)).strip()
        return cls(
            symbol=symbol,
            name=name,
            alias=str(raw.get("alias", "")).strip(),
            market=str(raw.get("market", "")).strip().upper(),
            visible=bool(raw.get("visible", True)),
        )


@dataclass(slots=True)
class StockQuote:
    """单只标的的标准化实时行情快照（屏蔽不同数据源的原始报文差异）。"""

    symbol: str
    name: str
    price: float
    prev_close: float
    change: float
    change_percent: float
    currency: str = ""
    quote_time: str = ""
    updated_at: datetime = field(default_factory=datetime.now)
    raw_status: str = "ok"

    @property
    def trend(self) -> str:
        """返回涨跌方向枚举字符串：up / down / flat。"""
        if self.change > 0 or self.change_percent > 0:
            return "up"
        if self.change < 0 or self.change_percent < 0:
            return "down"
        return "flat"


@dataclass(slots=True)
class SearchResult:
    """搜索接口返回的候选标的条目，可直接转换为 StockItem 加入自选。"""

    symbol: str
    code: str
    name: str
    market: str
    pinyin: str = ""
    security_type: str = ""

    def to_stock_item(self) -> StockItem:
        """将搜索候选转为默认可见的自选配置项。"""
        return StockItem(
            symbol=self.symbol,
            name=self.name,
            alias="",
            market=self.market,
            visible=True,
        )
