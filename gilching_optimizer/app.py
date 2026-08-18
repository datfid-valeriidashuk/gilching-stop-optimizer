from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pyproj import Transformer
from scipy.sparse.csgraph import dijkstra

from .common import DATA_PROCESSED, ROOT, load_config, read_json
from .metrics import summarize_distances
from .optimizer import load_distance_matrix, optimize_p_median
from .prepare import _simple_adjacency, attach_to_walk_edges

STATIC_DIR = ROOT / "gilching_optimizer" / "static"


class StopPoint(BaseModel):
    lat: float
    lon: float


class AnalyzeRequest(BaseModel):
    stops: list[StopPoint] = Field(min_length=1, max_length=10)


class OptimizeRequest(BaseModel):
    p: int = Field(ge=1, le=10)


class State:
    def __init__(self) -> None:
        metadata_path = DATA_PROCESSED / "metadata.json"
        if not metadata_path.exists():
            raise RuntimeError("Prepared data not found. Run prepare.bat first.")
        self.metadata = read_json(metadata_path)
        self.config = load_config()
        self.demand = pd.read_parquet(DATA_PROCESSED / "demand.parquet")
        self.candidates = pd.read_parquet(DATA_PROCESSED / "candidates.parquet")
        self.G = ox.io.load_graphml(DATA_PROCESSED / "walk.graphml")
        self.A, self.node_to_idx, self.node_list = _simple_adjacency(self.G)
        self.du = self.demand["node_u"].map(self.node_to_idx).to_numpy(dtype=int)
        self.dv = self.demand["node_v"].map(self.node_to_idx).to_numpy(dtype=int)
        self.dou = self.demand["offset_u_m"].to_numpy(dtype=float)
        self.dov = self.demand["offset_v_m"].to_numpy(dtype=float)
        self.demand_edge_id = self.demand["edge_id"].astype(str).to_numpy()
        self.demand_edge_pos = self.demand["edge_pos_a_m"].to_numpy(dtype=float)
        self.demand_perp = self.demand["perpendicular_m"].to_numpy(dtype=float)
        self.weights = self.demand["population"].to_numpy(dtype=float)
        self.to_projected = Transformer.from_crs(4326, self.config["crs_projected"], always_xy=True)
        self.matrix = None
        if self.metadata.get("distance_matrix_ready"):
            shape = tuple(int(x) for x in self.metadata["distance_matrix_shape"])
            self.matrix = load_distance_matrix(DATA_PROCESSED / "distance_matrix.float32", shape)

    def distances_for_stops(self, stops: list[StopPoint]) -> tuple[np.ndarray, np.ndarray, list[dict]]:
        lon = np.array([s.lon for s in stops], dtype=float)
        lat = np.array([s.lat for s in stops], dtype=float)
        x, y = self.to_projected.transform(lon, lat)
        gs = gpd.GeoSeries(gpd.points_from_xy(x, y), crs=self.config["crs_projected"])
        conn = attach_to_walk_edges(self.G, gs)

        endpoint_nodes = np.unique(np.concatenate([
            conn["node_u"].to_numpy(dtype=np.int64),
            conn["node_v"].to_numpy(dtype=np.int64),
        ]))
        endpoint_indices = np.array([self.node_to_idx[int(n)] for n in endpoint_nodes], dtype=int)
        dist_nodes = dijkstra(self.A, directed=True, indices=endpoint_indices, return_predecessors=False)
        row_of = {int(n): i for i, n in enumerate(endpoint_nodes)}

        per_stop = []
        snapped = []
        for i, c in conn.iterrows():
            ru = dist_nodes[row_of[int(c["node_u"])]]
            rv = dist_nodes[row_of[int(c["node_v"])]]
            via_u = np.minimum(ru[self.du] + self.dou, ru[self.dv] + self.dov) + float(c["offset_u_m"])
            via_v = np.minimum(rv[self.du] + self.dou, rv[self.dv] + self.dov) + float(c["offset_v_m"])
            best = np.minimum(via_u, via_v)
            same_edge = self.demand_edge_id == str(c["edge_id"])
            if np.any(same_edge):
                direct = (
                    self.demand_perp[same_edge]
                    + float(c["perpendicular_m"])
                    + np.abs(self.demand_edge_pos[same_edge] - float(c["edge_pos_a_m"]))
                )
                best[same_edge] = np.minimum(best[same_edge], direct)
            per_stop.append(best)
            snapped.append({
                "input_lat": float(stops[i].lat),
                "input_lon": float(stops[i].lon),
                "connector_offset_m": float(c["perpendicular_m"]),
            })
        all_dist = np.vstack(per_stop)
        assignment = np.argmin(all_dist, axis=0)
        nearest = all_dist[assignment, np.arange(all_dist.shape[1])]
        return nearest, assignment, snapped


@lru_cache(maxsize=1)
def get_state() -> State:
    return State()


app = FastAPI(title="Gilching Stop Optimizer", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "data_ready": (DATA_PROCESSED / "metadata.json").exists()}


@app.get("/api/status")
def status():
    try:
        s = get_state()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return s.metadata


@app.get("/api/boundary")
def boundary():
    path = DATA_PROCESSED / "boundary.geojson"
    if not path.exists():
        raise HTTPException(404, "Boundary not prepared")
    return FileResponse(path, media_type="application/geo+json")


@app.get("/api/buildings")
def buildings():
    path = DATA_PROCESSED / "buildings.geojson"
    if not path.exists():
        raise HTTPException(404, "Buildings not prepared")
    return FileResponse(path, media_type="application/geo+json")


@app.get("/api/fallback")
def fallback():
    path = DATA_PROCESSED / "fallback_points.geojson"
    if not path.exists():
        raise HTTPException(404, "Fallback points not prepared")
    return FileResponse(path, media_type="application/geo+json")


def _assignment_payload(s: State, nearest: np.ndarray, assignment: np.ndarray) -> list[dict]:
    result = []
    for demand_id, a, d in zip(s.demand["demand_id"], assignment, nearest):
        result.append({
            "demand_id": str(demand_id),
            "stop": int(a),
            "distance_m": None if not np.isfinite(d) else float(d),
        })
    return result


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    s = get_state()
    nearest, assignment, snapped = s.distances_for_stops(req.stops)
    finite = np.isfinite(nearest)
    if not finite.any():
        raise HTTPException(422, "No demand point is reachable from the selected stops")
    if not finite.all():
        nearest = nearest.copy()
        nearest[~finite] = np.nan
    stats = summarize_distances(nearest, s.weights)
    return {
        "stats": stats,
        "stops": [p.model_dump() for p in req.stops],
        "snap_info": snapped,
        "assignments": _assignment_payload(s, nearest, assignment),
    }


@app.post("/api/optimize")
def optimize(req: OptimizeRequest):
    s = get_state()
    if s.matrix is None:
        raise HTTPException(503, "Distance matrix is not ready. Re-run prepare.bat without --skip-matrix.")
    if req.p > len(s.candidates):
        raise HTTPException(422, "p exceeds candidate count")
    result = optimize_p_median(s.matrix, s.weights, req.p)
    selected = s.candidates.iloc[result.selected].copy()
    dist_selected = np.asarray(s.matrix[:, result.selected], dtype=np.float64)
    assignment = np.argmin(dist_selected, axis=1)
    nearest = dist_selected[np.arange(len(s.demand)), assignment]
    stats = summarize_distances(nearest, s.weights)
    stops = [
        {
            "lat": float(row.lat),
            "lon": float(row.lon),
            "candidate_id": int(row.candidate_id),
        }
        for row in selected.itertuples()
    ]
    return {
        "stats": stats,
        "stops": stops,
        "method": "exact-for-p1; greedy-plus-1-swap-for-p>1",
        "assignments": _assignment_payload(s, nearest, assignment),
    }
