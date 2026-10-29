from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else ROOT / "config.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def place_id_of(config: dict[str, Any]) -> str:
    return str(config.get("place_id") or "gilching")


def processed_dir_for(config: dict[str, Any]) -> Path:
    """Gilching stays in data/processed so the existing dataset keeps working."""
    place_id = place_id_of(config)
    if place_id == "gilching":
        return DATA_PROCESSED
    return DATA_PROCESSED / place_id


def config_path_for(place_id: str) -> Path:
    if place_id == "gilching":
        return ROOT / "config.yaml"
    return ROOT / f"config.{place_id}.yaml"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
