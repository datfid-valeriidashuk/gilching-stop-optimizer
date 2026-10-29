from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

from .common import ROOT, read_json
from .prepare import attach_to_walk_edges

INSTITUTIONS_PATH = ROOT / "data" / "institutions.json"


def load_institutions(path=INSTITUTIONS_PATH) -> list[dict]:
    path = Path(path) if path is not None else INSTITUTIONS_PATH
    if not path.exists():
        return []
    payload = read_json(path)
    records = payload.get("institutions") or []
    cleaned = []
    for raw in records:
        weight = float(raw["weight"])
        if weight <= 0:
            continue
        cleaned.append({
            "id": str(raw["id"]),
            "name": str(raw["name"]),
            "kind": str(raw.get("kind") or "institution"),
            "lat": float(raw["lat"]),
            "lon": float(raw["lon"]),
            "weight": weight,
            "weight_source": str(raw.get("weight_source") or "unknown"),
            "note": str(raw.get("note") or ""),
        })
    return cleaned


def institutions_public_payload(records: list[dict] | None = None) -> dict:
    records = load_institutions() if records is None else records
    return {
        "institutions": records,
        "count": len(records),
        "weight_total": float(sum(r["weight"] for r in records)),
    }


def snap_institutions(G, records: list[dict], config: dict) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    to_projected = Transformer.from_crs(4326, config["crs_projected"], always_xy=True)
    lons = np.array([r["lon"] for r in records], dtype=float)
    lats = np.array([r["lat"] for r in records], dtype=float)
    x, y = to_projected.transform(lons, lats)
    gs = gpd.GeoSeries(gpd.points_from_xy(x, y), crs=config["crs_projected"])
    conn = attach_to_walk_edges(G, gs)
    meta = pd.DataFrame({
        "demand_id": [f"institution:{r['id']}" for r in records],
        "population": [r["weight"] for r in records],
        "name": [r["name"] for r in records],
        "kind": [r["kind"] for r in records],
        "lat": lats,
        "lon": lons,
        "weight_source": [r["weight_source"] for r in records],
        "note": [r["note"] for r in records],
        "x": x,
        "y": y,
    })
    return pd.concat([meta.reset_index(drop=True), conn.reset_index(drop=True)], axis=1)


def stack_institution_demand(
    matrix: np.ndarray,
    weights: np.ndarray,
    institution_matrix: np.ndarray,
    institution_weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Append institution rows onto a residential demand-by-candidate matrix."""
    matrix = np.asarray(matrix)
    institution_matrix = np.asarray(institution_matrix)
    weights = np.asarray(weights, dtype=np.float64)
    institution_weights = np.asarray(institution_weights, dtype=np.float64)
    if institution_matrix.ndim != 2 or institution_matrix.shape[1] != matrix.shape[1]:
        raise ValueError("institution matrix must have the same candidate columns as the residential matrix")
    if institution_matrix.shape[0] != institution_weights.shape[0]:
        raise ValueError("institution weights must match institution matrix rows")
    return (
        np.vstack([matrix, institution_matrix]),
        np.concatenate([weights, institution_weights]),
    )
