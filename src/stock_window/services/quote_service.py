"""行情与搜索业务服务：协调 Provider、内存缓存与异常降级（纯 Python，不依赖 Qt）。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field

from stock_window.models.stock import SearchResult, StockItem, StockQuote
from stock_window.providers.base import ProviderError, QuoteProvider, SearchProvider

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QuoteSnapshotResult:
    """一次行情刷新任务的统一返回结果。"""

    quotes: dict[str, StockQuote] = field(default_factory=dict)
    error: str | None = None


class QuoteService:
    """封装实时行情拉取、最新快照缓存与股票模糊搜索。

    线程安全说明：
    网络请求通常在后台工作线程执行，UI 线程读取缓存快照，因此对内部缓存加锁保护。
    """

    def __init__(
        self,
        quote_provider: QuoteProvider,
        search_provider: SearchProvider,
        timeout: float = 5.0,
    ) -> None:
        self._quote_provider = quote_provider
        self._search_provider = search_provider
        self._timeout = timeout
        self._lock = threading.RLock()
        self._cache: dict[str, StockQuote] = {}

    def update_providers(
        self,
        quote_provider: QuoteProvider,
        search_provider: SearchProvider,
        timeout: float = 5.0,
    ) -> None:
        """热切换数据源（例如用户在配置中切换 provider 后调用）。"""
        with self._lock:
            old_q, old_s = self._quote_provider, self._search_provider
            self._quote_provider = quote_provider
            self._search_provider = search_provider
            self._timeout = timeout
        if old_q is not quote_provider:
            old_q.close()
        if old_s is not search_provider:
            old_s.close()

    def refresh_quotes(self, items: Sequence[StockItem]) -> QuoteSnapshotResult:
        """拉取可见标的的最新行情；网络异常时保留旧缓存并返回错误信息。"""
        symbols = [item.symbol for item in items if item.visible and item.symbol]
        if not symbols:
            return QuoteSnapshotResult(quotes=self.get_cached_quotes(), error=None)

        with self._lock:
            provider = self._quote_provider
            timeout = self._timeout

        try:
            fresh = provider.fetch_quotes(symbols, timeout=timeout)
        except ProviderError as exc:
            logger.warning("刷新行情失败，继续保留上次缓存: %s", exc)
            return QuoteSnapshotResult(quotes=self.get_cached_quotes(), error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("刷新行情出现未预期异常")
            return QuoteSnapshotResult(quotes=self.get_cached_quotes(), error=str(exc))

        with self._lock:
            self._cache.update(fresh)
            # 清理已不再需要的过旧键不会影响当前展示，保留字典副本返回给调用方
            snapshot = dict(self._cache)
        return QuoteSnapshotResult(quotes=snapshot, error=None)

    def get_cached_quotes(self) -> dict[str, StockQuote]:
        with self._lock:
            return dict(self._cache)

    def search_stocks(self, keyword: str, limit: int = 12) -> list[SearchResult]:
        """按中文名、拼音或代码搜索股票候选。"""
        with self._lock:
            provider = self._search_provider
            timeout = self._timeout
        return provider.search(keyword, limit=limit, timeout=timeout)

    def close(self) -> None:
        with self._lock:
            self._quote_provider.close()
            self._search_provider.close()
