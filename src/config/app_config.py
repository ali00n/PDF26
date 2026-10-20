"""Preferências do usuário do PDF26, persistidas em JSON (%APPDATA%/PDF26/config.json no Windows)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, List

from ..utils.logger import get_logger

logger = get_logger(__name__)

_RECENT_LIMIT = 8


def config_dir() -> Path:
    override = os.environ.get("PDF26_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "PDF26"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "pdf26"


@dataclass
class AppConfig:
    appearance: str = "system"  # system | light | dark
    favorites: List[str] = field(default_factory=lambda: ["merge", "compress", "split", "reader"])
    recent: List[str] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    output_mode: str = "same"  # same = pasta do arquivo de entrada | folder = output_dir
    output_dir: str = ""
    open_folder_after: bool = False
    default_dir: str = str(Path.home() / "Documents" / "PDF26")
    ghostscript_path: str = ""
    soffice_path: str = ""
    tessdata_path: str = ""

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_dir() / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as error:
            logger.warning(f"Configuração ignorada ({path}): {error}")
            return cls()
        known = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    def save(self) -> None:
        path = config_dir() / "config.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            logger.warning(f"Não foi possível salvar a configuração: {error}")

    def is_favorite(self, tool_id: str) -> bool:
        return tool_id in self.favorites

    def toggle_favorite(self, tool_id: str) -> bool:
        if tool_id in self.favorites:
            self.favorites.remove(tool_id)
        else:
            self.favorites.append(tool_id)
        self.save()
        return tool_id in self.favorites

    def register_use(self, tool_id: str) -> None:
        self.recent = [tool_id] + [item for item in self.recent if item != tool_id][: _RECENT_LIMIT - 1]
        self.usage[tool_id] = self.usage.get(tool_id, 0) + 1
        self.save()
