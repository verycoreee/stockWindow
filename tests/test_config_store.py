"""配置持久化与快捷键解析单元测试。"""

import json
from pathlib import Path

from stock_window.config.store import ConfigStore
from stock_window.models.settings import AppConfig, ColorMode
from stock_window.models.stock import StockItem
from stock_window.platform.base import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, parse_hotkey_string


def test_config_store_initializes_and_roundtrips(tmp_path: Path) -> None:
    cfg_file = tmp_path / "data" / "config.json"
    store = ConfigStore(cfg_file)

    default_cfg = store.load()
    assert cfg_file.exists()
    assert len(default_cfg.stocks) == 1
    assert default_cfg.appearance.color_mode == ColorMode.MONOCHROME.value

    default_cfg.stocks.append(StockItem(symbol="hk00700", name="腾讯控股", alias="TX", market="HK"))
    default_cfg.appearance.monochrome_color = "#9CA3AF"
    default_cfg.window.offset_x = 42
    store.save(default_cfg)

    reloaded = store.load()
    assert [s.symbol for s in reloaded.stocks] == ["sh000001", "hk00700"]
    assert reloaded.stocks[1].alias == "TX"
    assert reloaded.appearance.monochrome_color == "#9CA3AF"
    assert reloaded.window.offset_x == 42


def test_config_store_handles_partial_and_corrupted_json(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    # 模拟旧版本缺少字段的局部配置
    cfg_file.write_text(json.dumps({"stocks": [{"symbol": "usAAPL", "name": "苹果"}]}), encoding="utf-8")
    store = ConfigStore(cfg_file)
    loaded = store.load()
    assert loaded.stocks[0].symbol == "usAAPL"
    assert loaded.polling.provider == "tencent"
    assert loaded.window.boss_key == "Ctrl+Alt+H"

    # 模拟损坏的 JSON：应备份旧文件并回退默认配置
    cfg_file.write_text("{ broken json", encoding="utf-8")
    recovered = store.load()
    assert recovered.stocks[0].symbol == "sh000001"
    backups = list(tmp_path.glob("config.json.corrupted.*"))
    assert len(backups) == 1


def test_parse_hotkey_string() -> None:
    spec = parse_hotkey_string("Ctrl+Alt+H")
    assert spec is not None
    assert spec.modifiers == (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT)
    assert spec.vk_code == ord("H")

    assert parse_hotkey_string("H") is None  # 必须包含修饰键，防止劫持普通打字键
    assert parse_hotkey_string("Ctrl+InvalidKey") is None
