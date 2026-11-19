"""ProviderRegistry 扩展点与 QuoteService 缓存降级行为单元测试。"""

from collections.abc import Sequence

import pytest

from stock_window.models.stock import SearchResult, StockItem, StockQuote
from stock_window.providers.base import ProviderError, QuoteProvider, SearchProvider
from stock_window.providers.registry import ProviderRegistry, create_default_registry
from stock_window.services.quote_service import QuoteService


class _FakeQuoteProvider(QuoteProvider):
    name = "fake"

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.closed = False

    def fetch_quotes(self, symbols: Sequence[str], timeout: float = 5.0) -> dict[str, StockQuote]:
        if self.should_fail:
            raise ProviderError("模拟网络超时")
        return {
            sym: StockQuote(
                symbol=sym,
                name=f"测试-{sym}",
                price=100.0,
                prev_close=98.0,
                change=2.0,
                change_percent=2.04,
            )
            for sym in symbols
        }

    def close(self) -> None:
        self.closed = True


class _FakeSearchProvider(SearchProvider):
    name = "fake"

    def search(self, keyword: str, limit: int = 12, timeout: float = 5.0) -> list[SearchResult]:
        return [
            SearchResult(symbol="sh600519", code="600519", name="贵州茅台", market="SH", security_type="A股")
        ]


def test_registry_allows_custom_provider_registration() -> None:
    registry = create_default_registry()
    assert "tencent" in registry.quote_provider_names
    assert "tencent" in registry.search_provider_names

    registry.register_quote_provider("custom_demo", _FakeQuoteProvider)
    provider = registry.create_quote_provider("custom_demo")
    assert isinstance(provider, _FakeQuoteProvider)

    with pytest.raises(KeyError):
        registry.create_quote_provider("nonexistent")


def test_quote_service_keeps_cache_on_network_error() -> None:
    fake_quote = _FakeQuoteProvider(should_fail=False)
    service = QuoteService(fake_quote, _FakeSearchProvider())
    items = [
        StockItem(symbol="sh000001", name="上证指数", visible=True),
        StockItem(symbol="sz000001", name="平安银行", visible=False),
    ]

    # 仅拉取 visible=True 的标的
    first = service.refresh_quotes(items)
    assert first.error is None
    assert set(first.quotes.keys()) == {"sh000001"}

    # 下一轮网络失败时，应保留上一轮缓存而非清空任务栏显示
    fake_quote.should_fail = True
    second = service.refresh_quotes(items)
    assert second.error is not None
    assert "模拟网络超时" in second.error
    assert "sh000001" in second.quotes
    assert second.quotes["sh000001"].price == 100.0

    service.close()
    assert fake_quote.closed is True
