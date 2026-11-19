"""展示格式化与低调配色策略单元测试。"""

from stock_window.models.settings import AppearanceConfig, ColorMode
from stock_window.models.stock import StockItem, StockQuote
from stock_window.services.formatter import DisplayFormatter


def test_monochrome_mode_ignores_up_and_down_colors() -> None:
    formatter = DisplayFormatter()
    appearance = AppearanceConfig(
        color_mode=ColorMode.MONOCHROME.value,
        monochrome_color="#CCCCCC",
        up_color="#FF0000",
        down_color="#00FF00",
    )
    item = StockItem(symbol="sh600519", name="贵州茅台", alias="MT", market="SH")
    q_up = StockQuote("sh600519", "贵州茅台", 1500.0, 1480.0, 20.0, 1.35)
    q_down = StockQuote("sh600519", "贵州茅台", 1460.0, 1480.0, -20.0, -1.35)

    v_up = formatter.format_item(item, q_up, appearance)
    v_down = formatter.format_item(item, q_down, appearance)

    assert v_up.color == "#CCCCCC"
    assert v_down.color == "#CCCCCC"
    assert v_up.text == "MT 1500.00 +1.35%"
    assert v_down.text == "MT 1460.00 -1.35%"


def test_custom_trend_mode_uses_configured_colors() -> None:
    formatter = DisplayFormatter()
    appearance = AppearanceConfig(
        color_mode=ColorMode.CUSTOM_TREND.value,
        up_color="#D98A8A",
        down_color="#7DB89B",
        flat_color="#B8BFC8",
    )
    item = StockItem(symbol="sh000001", name="上证指数")
    assert formatter.resolve_color(StockQuote("sh000001", "上证指数", 101, 100, 1, 1.0), appearance) == "#D98A8A"
    assert formatter.resolve_color(StockQuote("sh000001", "上证指数", 99, 100, -1, -1.0), appearance) == "#7DB89B"
    assert formatter.resolve_color(StockQuote("sh000001", "上证指数", 100, 100, 0, 0.0), appearance) == "#B8BFC8"
    assert formatter.resolve_color(None, appearance) == "#B8BFC8"


def test_etf_auto_precision_and_minimal_display() -> None:
    formatter = DisplayFormatter()
    item = StockItem(symbol="sh510300", name="沪深300ETF", alias="300E")
    quote = StockQuote("sh510300", "沪深300ETF", 4.06, 4.058, 0.002, 0.05)

    v_full = formatter.format_item(item, quote, AppearanceConfig(auto_precision=True))
    assert v_full.text == "300E 4.060 +0.05%"

    v_minimal = formatter.format_item(
        item,
        quote,
        AppearanceConfig(show_name=True, show_price=False, show_change_percent=True, show_sign_prefix=False),
    )
    assert v_minimal.text == "300E 0.05%"
