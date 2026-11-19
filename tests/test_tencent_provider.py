"""腾讯行情与搜索协议解析单元测试（纯离线，不发真实网络请求）。"""

from stock_window.providers.tencent import (
    decode_unicode_escapes,
    normalize_tencent_symbol,
    parse_tencent_quote_payload,
    parse_tencent_search_payload,
)


def _build_quote_line(
    key: str,
    name: str,
    code: str,
    price: str,
    prev_close: str,
    change: str,
    pct: str,
    quote_time: str = "20261119150000",
) -> str:
    fields = ["0"] * 40
    fields[1] = name
    fields[2] = code
    fields[3] = price
    fields[4] = prev_close
    fields[30] = quote_time
    fields[31] = change
    fields[32] = pct
    return f'v_{key}="{"~".join(fields)}";'


def test_parse_quotes_multi_market_and_ignore_invalid() -> None:
    payload = "\n".join(
        [
            _build_quote_line("sh000001", "上证指数", "000001", "3577.62", "3587.83", "-10.21", "-0.28"),
            _build_quote_line("hk00700", "腾讯控股", "00700", "348.400", "372.800", "-24.400", "-6.55"),
            _build_quote_line("usAAPL", "苹果", "AAPL.OQ", "352.45", "351.91", "0.54", "0.15"),
            'v_pv_none_match="1";',
        ]
    )

    quotes = parse_tencent_quote_payload(payload)
    assert set(quotes.keys()) == {"sh000001", "hk00700", "usAAPL"}

    assert quotes["sh000001"].name == "上证指数"
    assert quotes["sh000001"].price == 3577.62
    assert quotes["sh000001"].trend == "down"

    assert quotes["usAAPL"].price == 352.45
    assert quotes["usAAPL"].change_percent == 0.15
    assert quotes["usAAPL"].trend == "up"


def test_parse_quote_zero_price_falls_back_to_prev_close() -> None:
    payload = _build_quote_line("sh600519", "贵州茅台", "600519", "0.00", "1450.00", "-1450.00", "-100.00")
    quotes = parse_tencent_quote_payload(payload)
    q = quotes["sh600519"]
    assert q.price == 1450.00
    assert q.change == 0.0
    assert q.change_percent == 0.0
    assert q.raw_status == "suspended_or_pre"


def test_normalize_us_symbol_strips_exchange_suffix() -> None:
    assert normalize_tencent_symbol("us", "aapl.oq") == "usAAPL"
    assert normalize_tencent_symbol("us", "tme.n") == "usTME"
    assert normalize_tencent_symbol("sh", "600519") == "sh600519"
    assert normalize_tencent_symbol("hk", "00700") == "hk00700"


def test_parse_search_decodes_unicode_and_deprioritizes_warrants() -> None:
    raw = (
        'v_hint="hk~13005~\\u817e\\u8baf\\u6743\\u8bc1~txqz~QZ^'
        'hk~00700~\\u817e\\u8baf\\u63a7\\u80a1~txkg~GP^'
        'us~aapl.oq~\\u82f9\\u679c~pg~GP^'
        'jj~000001~\\u57fa\\u91d1\\u6d4b\\u8bd5~jjcs~JJ"'
    )
    results = parse_tencent_search_payload(raw, limit=10)
    # 场外基金 jj 不在支持列表内被过滤；权证 QZ 排在正股之后
    assert [r.symbol for r in results] == ["hk00700", "usAAPL", "hk13005"]
    assert results[0].name == "腾讯控股"
    assert results[0].security_type == "港股"
    assert results[1].name == "苹果"
    assert results[1].code == "AAPL"
    assert results[1].security_type == "美股"


def test_decode_unicode_escapes_keeps_plain_utf8() -> None:
    assert decode_unicode_escapes("贵州\\u8305\\u53f0") == "贵州茅台"
