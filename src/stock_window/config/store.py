"""JSON 配置文件读写器：支持自动初始化、缺省值兼容与原子写入。"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from stock_window.models.settings import AppConfig

logger = logging.getLogger(__name__)


class ConfigStore:
    """负责 AppConfig 与本地 JSON 文件之间的安全读写。

    设计原则：
    1. 写文件采用“先写临时文件 + os.replace 原子替换”，避免程序被强制关闭时写出半截坏 JSON。
    2. 配置文件损坏时自动备份原文件并回退默认配置，保证软件永远可启动。
    3. 配置文件默认存放在被 .gitignore 忽略的 data/ 目录，避免个人自选列表被误推送到仓库。
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppConfig:
        """读取配置；文件不存在则创建默认配置并落盘。"""
        if not self._path.exists():
            config = AppConfig.default()
            self.save(config)
            return config

        try:
            text = self._path.read_text(encoding="utf-8")
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise ValueError("配置文件根节点必须是 JSON 对象")
            return AppConfig.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 - 任何读取或解析错误都需要降级恢复
            logger.warning("读取配置文件失败，将备份旧文件并回退默认配置: %s", exc)
            self._backup_corrupted_file()
            config = AppConfig.default()
            self.save(config)
            return config

    def save(self, config: AppConfig) -> None:
        """将配置以 UTF-8 美化格式原子写入磁盘。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        # Windows 上 os.replace 同样具备原子覆盖目标文件的语义
        os.replace(tmp_path, self._path)

    def _backup_corrupted_file(self) -> None:
        """备份损坏的配置文件，便于排查手工修改错误。"""
        if not self._path.exists():
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self._path.with_name(f"{self._path.name}.corrupted.{timestamp}")
        try:
            shutil.copy2(self._path, backup)
        except OSError as exc:
            logger.error("备份损坏配置文件失败: %s", exc)
