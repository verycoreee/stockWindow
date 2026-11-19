"""数据源扩展层：对外暴露抽象接口、注册中心与内置腾讯实现。"""

from stock_window.providers.base import ProviderError, QuoteProvider, SearchProvider
from stock_window.providers.registry import ProviderRegistry, create_default_registry
from stock_window.providers.tencent import TencentQuoteProvider, TencentSearchProvider

__all__ = [
    "ProviderError",
    "ProviderRegistry",
    "QuoteProvider",
    "SearchProvider",
    "TencentQuoteProvider",
    "TencentSearchProvider",
    "create_default_registry",
]
