"""Small JSON settings store for VectorForge preferences."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


DEFAULTS: Dict[str, Any] = {
    "screenscraper": {
        "dev_id": "",
        "dev_password": "",
        "soft_name": "VectorForge",
        "user": "",
        "password": "",
    },
    "thegamesdb_api_key": "",
    "providers": ["screenscraper"],
}


class SettingsStore:
    def __init__(self, config_root: Path) -> None:
        self.path = config_root / "settings.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(DEFAULTS))
        with self.path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError("VectorForge settings must be a JSON object")
        result = json.loads(json.dumps(DEFAULTS))
        result.update(value)
        return result

    def save(self, value: Dict[str, Any]) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="ascii",
        )
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, self.path)
