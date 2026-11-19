"""数据源注册中心：按名称动态解析行情与搜索实现，实现开闭原则。"""

from __future__ import annotations

from collections.abc import Callable

from stock_window.providers.base import QuoteProvider, SearchProvider
from stock_window.providers.tencent import TencentQuoteProvider, TencentSearchProvider


class ProviderRegistry:
    """管理所有已注册的数据源工厂。

    以后扩展东方财富、新浪、通达信或加密货币行情时，只需调用
    register_quote_provider / register_search_provider 注册工厂函数即可。
    """

    def __init__(self) -> None:
        self._quote_factories: dict[str, Callable[[], QuoteProvider]] = {}
        self._search_factories: dict[str, Callable[[], SearchProvider]] = {}

    def register_quote_provider(self, name: str, factory: Callable[[], QuoteProvider]) -> None:
        self._quote_factories[name.strip().lower()] = factory

    def register_search_provider(self, name: str, factory: Callable[[], SearchProvider]) -> None:
        self._search_factories[name.strip().lower()] = factory

    def create_quote_provider(self, name: str) -> QuoteProvider:
        key = name.strip().lower()
        factory = self._quote_factories.get(key)
        if factory is None:
            available = ", ".join(sorted(self._quote_factories)) or "(无)"
            raise KeyError(f"未注册的行情数据源 '{name}'，当前可用: {available}")
        return factory()

    def create_search_provider(self, name: str) -> SearchProvider:
        key = name.strip().lower()
        factory = self._search_factories.get(key)
        if factory is None:
            available = ", ".join(sorted(self._search_factories)) or "(无)"
            raise KeyError(f"未注册的搜索数据源 '{name}'，当前可用: {available}")
        return factory()

    @property
    def quote_provider_names(self) -> list[str]:
        return sorted(self._quote_factories.keys())

    @property
    def search_provider_names(self) -> list[str]:
        return sorted(self._search_factories.keys())


def create_default_registry() -> ProviderRegistry:
    """创建包含内置数据源的默认注册表。"""
    registry = ProviderRegistry()
    registry.register_quote_provider("tencent", TencentQuoteProvider)
    registry.register_search_provider("tencent", TencentSearchProvider)
    return registry
