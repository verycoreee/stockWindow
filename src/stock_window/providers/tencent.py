"""腾讯财经数据源实现：实时行情接口（qt.gtimg.cn）与拼音/名称模糊搜索（smartbox.gtimg.cn）。

接口协议说明（已实测验证）：
1. 行情接口：https://qt.gtimg.cn/q=sh000001,hk00700,usAAPL
   - 响应编码为 GBK，每行格式为 `v_<symbol>="字段0~字段1~...";`
   - 关键字段下标（A股/ETF/指数/港股/美股通用）：
     [1]=名称, [2]=纯代码, [3]=现价, [4]=昨收, [30]=时间, [31]=涨跌额, [32]=涨跌幅(%)
   - 注意：美股在行情接口中必须是 `usAAPL`（不含 `.oq` / `.n` 交易所后缀，且代码大写）。
2. 搜索接口：https://smartbox.gtimg.cn/s3/?v=2&q=<keyword>&t=all
   - 响应格式为 `v_hint="market~code~name~pinyin~type^..."`，中文可能以 `\\uXXXX` 转义。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import quote as url_quote

import requests

from stock_window.models.stock import SearchResult, StockQuote
from stock_window.providers.base import ProviderError, QuoteProvider, SearchProvider

logger = logging.getLogger(__name__)

_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_QUOTE_LINE_RE = re.compile(r'^v_(?P<key>[^=]+)="(?P<payload>.*)";?$')

# 支持直接通过 qt.gtimg.cn 查询的市场集合
_SUPPORTED_MARKETS = {"sh", "sz", "bj", "hk", "us"}

# 证券类型友好中文映射
_TYPE_LABEL_MAP = {
    "GP-A": "A股",
    "GP-A-KCB": "科创板",
    "GP-A-CYB": "创业板",
    "GP-B": "B股",
    "ZS": "指数",
    "ETF": "ETF",
    "LOF": "LOF",
    "QZ": "权证",
    "ZQ": "债券",
}


def decode_unicode_escapes(text: str) -> str:
    """安全解码形如 \\u8d35 的 Unicode 转义序列，同时保留已有正常 UTF-8 字符。"""
    return _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def normalize_tencent_symbol(market: str, raw_code: str) -> str:
    """将搜索接口返回的 (market, code) 转为 qt.gtimg.cn 可直接查询的标准代码。

    关键兼容点：
    - 美股在 smartbox 中返回 `us` + `aapl.oq` / `tme.n`，
      实测 qt.gtimg.cn 不接受 `.oq`/`.n` 后缀，必须去掉后缀并大写为 `usAAPL` / `usTME`。
    - A股 / 北交所 / 港股直接拼接为 `sh600519`、`sz000001`、`bj430047`、`hk00700`。
    """
    m = market.strip().lower()
    code = raw_code.strip()
    if m == "us":
        base_ticker = code.split(".", 1)[0].upper()
        return f"us{base_ticker}"
    return f"{m}{code}"


def _format_security_type(market: str, raw_type: str) -> str:
    """把腾讯原始类型代号转为面向用户的简短标签。"""
    market_upper = market.upper()
    code_upper = raw_type.upper()
    if code_upper in _TYPE_LABEL_MAP:
        return _TYPE_LABEL_MAP[code_upper]
    if code_upper == "GP":
        if market_upper == "HK":
            return "港股"
        if market_upper == "US":
            return "美股"
        return "股票"
    return f"{market_upper}/{code_upper}" if code_upper else market_upper


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_tencent_quote_payload(raw_text: str) -> dict[str, StockQuote]:
    """解析 qt.gtimg.cn 返回的多行文本（纯函数，便于直接单元测试）。"""
    results: dict[str, StockQuote] = {}
    now = datetime.now()

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _QUOTE_LINE_RE.match(line)
        if not match:
            continue

        key = match.group("key").strip()
        payload = match.group("payload")
        # 腾讯对无效代码会返回 v_pv_none_match="1";
        if not payload or key == "pv_none_match":
            continue

        parts = payload.split("~")
        if len(parts) <= 32:
            continue

        name = parts[1].strip() or key
        price = _safe_float(parts[3])
        prev_close = _safe_float(parts[4])
        quote_time = parts[30].strip() if len(parts) > 30 else ""
        change = _safe_float(parts[31])
        change_percent = _safe_float(parts[32])
        currency = parts[82].strip() if len(parts) > 82 else ""
        status = "ok"

        # 盘前集合竞价或停牌时部分接口会返回 price=0，回退昨收防止显示 -100%
        if price <= 0.0 and prev_close > 0.0:
            price = prev_close
            change = 0.0
            change_percent = 0.0
            status = "suspended_or_pre"

        results[key] = StockQuote(
            symbol=key,
            name=name,
            price=price,
            prev_close=prev_close,
            change=change,
            change_percent=change_percent,
            currency=currency,
            quote_time=quote_time,
            updated_at=now,
            raw_status=status,
        )

    return results


def parse_tencent_search_payload(raw_text: str, limit: int = 12) -> list[SearchResult]:
    """解析 smartbox.gtimg.cn 返回的候选列表（纯函数，便于直接单元测试）。"""
    text = decode_unicode_escapes(raw_text.strip())
    match = re.search(r'v_hint="(.*)"', text, flags=re.DOTALL)
    if not match:
        return []

    body = match.group(1).strip()
    if not body or body == "N":
        return []

    normal_items: list[SearchResult] = []
    secondary_items: list[SearchResult] = []
    seen_symbols: set[str] = set()

    for entry in body.split("^"):
        fields = entry.split("~")
        if len(fields) < 5:
            continue

        market = fields[0].strip().lower()
        raw_code = fields[1].strip()
        name = fields[2].strip()
        pinyin = fields[3].strip()
        raw_type = fields[4].strip()

        if market not in _SUPPORTED_MARKETS or not raw_code or not name:
            continue

        symbol = normalize_tencent_symbol(market, raw_code)
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)

        display_code = raw_code.split(".", 1)[0].upper() if market == "us" else raw_code
        item = SearchResult(
            symbol=symbol,
            code=display_code,
            name=name,
            market=market.upper(),
            pinyin=pinyin,
            security_type=_format_security_type(market, raw_type),
        )

        # 港股窝轮/权证（QZ）在搜索中文名时噪音较多，排在正股/ETF/指数之后
        if raw_type.upper() == "QZ":
            secondary_items.append(item)
        else:
            normal_items.append(item)

    merged = normal_items + secondary_items
    return merged[: max(1, limit)]


class TencentQuoteProvider(QuoteProvider):
    """基于腾讯 qt.gtimg.cn 的批量实时行情数据源。"""

    name = "tencent"
    ENDPOINT = "https://qt.gtimg.cn/q={symbols}"
    BATCH_SIZE = 30

    def __init__(self, session: requests.Session | None = None) -> None:
        self._owns_session = session is None
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockWindow/0.1",
        )

    def fetch_quotes(self, symbols: Sequence[str], timeout: float = 5.0) -> dict[str, StockQuote]:
        cleaned = [s.strip() for s in symbols if s and s.strip()]
        if not cleaned:
            return {}

        all_quotes: dict[str, StockQuote] = {}
        # 分批拉取，防止自选股过多导致单条 URL 过长
        for start in range(0, len(cleaned), self.BATCH_SIZE):
            batch = cleaned[start : start + self.BATCH_SIZE]
            url = self.ENDPOINT.format(symbols=",".join(batch))
            try:
                resp = self._session.get(url, timeout=timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise ProviderError(f"腾讯行情接口请求失败: {exc}") from exc

            # qt.gtimg.cn 实际编码为 GBK / GB18030
            text = resp.content.decode("gb18030", errors="replace")
            all_quotes.update(parse_tencent_quote_payload(text))

        return all_quotes

    def close(self) -> None:
        if self._owns_session:
            self._session.close()


class TencentSearchProvider(SearchProvider):
    """基于腾讯 smartbox.gtimg.cn 的中文名称 / 拼音 / 代码模糊搜索数据源。"""

    name = "tencent"
    ENDPOINT = "https://smartbox.gtimg.cn/s3/?v=2&q={query}&t=all"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._owns_session = session is None
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockWindow/0.1",
        )

    def search(self, keyword: str, limit: int = 12, timeout: float = 5.0) -> list[SearchResult]:
        query = keyword.strip()
        if not query:
            return []

        url = self.ENDPOINT.format(query=url_quote(query, safe=""))
        try:
            resp = self._session.get(url, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"腾讯搜索接口请求失败: {exc}") from exc

        text = resp.content.decode("utf-8", errors="replace")
        return parse_tencent_search_payload(text, limit=limit)

    def close(self) -> None:
        if self._owns_session:
            self._session.close()
