"""数据源抽象基类（扩展点 1）。

后续如需新增东方财富、新浪、通达信、加密资产等数据源，只需继承本模块中的接口并注册到
ProviderRegistry，无需改动 UI 或轮询调度代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from stock_window.models.stock import SearchResult, StockQuote


class ProviderError(RuntimeError):
    """数据源请求或解析失败时抛出的统一异常。"""


class QuoteProvider(ABC):
    """实时行情数据源抽象接口。"""

    # 数据源唯一标识（与 config.polling.provider 对应）
    name: str = ""

    @abstractmethod
    def fetch_quotes(self, symbols: Sequence[str], timeout: float = 5.0) -> dict[str, StockQuote]:
        """批量拉取实时行情，返回 {symbol: StockQuote} 映射。

        Args:
            symbols: 标准化行情代码列表，例如 ["sh000001", "hk00700", "usAAPL"]。
            timeout: 单次网络请求超时时间（秒）。

        Returns:
            成功解析出的标的快照字典；未命中或停牌异常的单个代码不应阻断其余代码返回。
        """

    def close(self) -> None:
        """可选资源清理钩子（如关闭 HTTP Session）。"""


class SearchProvider(ABC):
    """股票名称 / 拼音 / 代码模糊搜索抽象接口。"""

    name: str = ""

    @abstractmethod
    def search(self, keyword: str, limit: int = 12, timeout: float = 5.0) -> list[SearchResult]:
        """根据中文名、拼音首字母或代码搜索候选标的。"""

    def close(self) -> None:
        """可选资源清理钩子。"""
