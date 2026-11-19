"""程序入口：配置日志、Windows 单实例保护、确定配置路径并启动主应用。"""

from __future__ import annotations

import argparse
import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from stock_window import __app_name__, __version__
from stock_window.app import StockWindowApp

_ERROR_ALREADY_EXISTS = 183


def _default_project_root() -> Path:
    """定位项目根目录（src/stock_window/main.py 上溯两级）。"""
    return Path(__file__).resolve().parents[2]


def _setup_logging(log_dir: Path, debug: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_dir / "stock_window.log", encoding="utf-8"),
    ]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def _acquire_single_instance_lock() -> int | None:
    """在 Windows 下创建命名互斥锁，防止重复启动多个重叠任务栏条。"""
    if sys.platform != "win32":
        return 1
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\StockWindow_SingleInstance_Mutex_v1")
    if not handle:
        return None
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stock-window", description=f"{__app_name__} v{__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="自定义配置文件路径（默认写入项目目录下 data/config.json）",
    )
    parser.add_argument("--debug", action="store_true", help="输出详细调试日志")
    args = parser.parse_args(argv)

    root = _default_project_root()
    config_path = args.config or (root / "data" / "config.json")
    _setup_logging(root / "logs", debug=args.debug)

    mutex_handle = _acquire_single_instance_lock()
    if mutex_handle is None:
        logging.getLogger(__name__).info("StockWindow 已在运行中，跳过重复启动。")
        return 0

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(__app_name__)
    qt_app.setApplicationVersion(__version__)

    controller = StockWindowApp(qt_app=qt_app, config_path=config_path)
    controller.start()
    try:
        return qt_app.exec()
    finally:
        if sys.platform == "win32" and mutex_handle:
            ctypes.windll.kernel32.CloseHandle(mutex_handle)


if __name__ == "__main__":
    raise SystemExit(main())
