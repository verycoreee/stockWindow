"""展示格式化与配色策略（扩展点 2）。

将“原始行情数值 -> 任务栏文本 / 字体颜色 / 悬停详情”完全收敛到本模块，
后续若要扩展“超过 ±3% 才变色”“自定义显示模板”或“本地提醒规则”，只需修改此处。
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_window.models.settings import AppearanceConfig, ColorMode
from stock_window.models.stock import StockItem, StockQuote


@dataclass(slots=True)
class FormattedStockView:
    """交付给 UI 控件直接绘制的只读视图模型。"""

    symbol: str
    text: str
    color: str
    tooltip: str


class DisplayFormatter:
    """根据用户外观配置生成任务栏单条股票的渲染数据。"""

    def format_item(
        self,
        item: StockItem,
        quote: StockQuote | None,
        appearance: AppearanceConfig,
    ) -> FormattedStockView:
        color = self.resolve_color(quote, appearance)
        text = self.format_bar_text(item, quote, appearance)
        tooltip = self.format_tooltip(item, quote)
        return FormattedStockView(
            symbol=item.symbol,
            text=text,
            color=color,
            tooltip=tooltip,
        )

    def resolve_color(self, quote: StockQuote | None, appearance: AppearanceConfig) -> str:
        """解析最终文本颜色：默认低调纯色模式不随涨跌变色。"""
        if appearance.color_mode == ColorMode.MONOCHROME.value:
            return appearance.monochrome_color

        if quote is None:
            return appearance.flat_color

        trend = quote.trend
        if trend == "up":
            return appearance.up_color
        if trend == "down":
            return appearance.down_color
        return appearance.flat_color

    def format_bar_text(
        self,
        item: StockItem,
        quote: StockQuote | None,
        appearance: AppearanceConfig,
    ) -> str:
        """拼装任务栏显示的精简文本。"""
        segments: list[str] = []

        if appearance.show_name:
            segments.append(item.display_name)

        if quote is None:
            segments.append("--")
            return " ".join(segments)

        decimals = self._pick_decimals(quote.price, appearance)

        if appearance.show_price:
            segments.append(f"{quote.price:.{decimals}f}")

        if appearance.show_change_amount:
            segments.append(self._format_signed(quote.change, decimals, appearance.show_sign_prefix))

        if appearance.show_change_percent:
            pct = self._format_signed(quote.change_percent, 2, appearance.show_sign_prefix)
            segments.append(f"{pct}%")

        # 兜底：如果用户把所有开关都关了，至少展示简称与涨跌幅，避免任务栏完全空白
        if not segments:
            pct = self._format_signed(quote.change_percent, 2, appearance.show_sign_prefix)
            return f"{item.display_name} {pct}%"

        return " ".join(segments)

    def format_tooltip(self, item: StockItem, quote: StockQuote | None) -> str:
        """生成鼠标悬停时的完整详情文本。"""
        header = f"{item.name} ({item.symbol})"
        if item.alias.strip() and item.alias.strip() != item.name:
            header += f"  [简称: {item.alias.strip()}]"

        if quote is None:
            return f"{header}\n状态: 等待拉取行情..."

        decimals = 3 if 0 < quote.price < 10 else 2
        sign_change = f"{quote.change:+.{decimals}f}"
        sign_pct = f"{quote.change_percent:+.2f}%"
        refresh_str = quote.updated_at.strftime("%H:%M:%S")

        lines = [
            header,
            f"现价: {quote.price:.{decimals}f}   昨收: {quote.prev_close:.{decimals}f}",
            f"涨跌: {sign_change} ({sign_pct})",
            f"刷新: {refresh_str}",
        ]
        if quote.raw_status != "ok":
            lines.append("提示: 当前可能处于停牌或盘前阶段")
        return "\n".join(lines)

    @staticmethod
    def _pick_decimals(price: float, appearance: AppearanceConfig) -> int:
        # 基金/ETF/低价股常以三位小数计价，自动精度开启时保留 3 位更准确
        if appearance.auto_precision and 0 < price < 10:
            return max(3, appearance.decimal_places)
        return appearance.decimal_places

    @staticmethod
    def _format_signed(value: float, decimals: int, show_sign_prefix: bool) -> str:
        if show_sign_prefix:
            return f"{value:+.{decimals}f}"
        if value < 0:
            return f"{value:.{decimals}f}"
        return f"{abs(value):.{decimals}f}"
