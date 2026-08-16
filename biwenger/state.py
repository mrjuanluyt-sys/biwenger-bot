from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .settings import settings

DEFAULT = {
    "auto_lineup": False,
    "last_lineup_round": None,
}


def _path() -> Path:
    return settings.data_dir / "state.json"


def load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return dict(DEFAULT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT)
    merged = dict(DEFAULT)
    merged.update(data)
    return merged


def save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_value(key: str, value: Any) -> None:
    data = load()
    data[key] = value
    save(data)
