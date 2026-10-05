from __future__ import annotations

from functools import lru_cache
from typing import Literal

import geopandas as gpd
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
from .institutions import (
    institutions_public_payload,
    load_institutions,
    snap_institutions,
    stack_institution_demand,
)
from .metrics import summarize_distances
from .optimizer import load_distance_matrix, optimize_p_median
from .prepare import _simple_adjacency, attach_to_walk_edges

STATIC_DIR = ROOT / "gilching_optimizer" / "static"
ModeName = Literal["walk", "wheelchair"]


class StopPoint(BaseModel):
    lat: float
    lon: float
    kind: Literal["fixed", "new"] | None = None


class AnalyzeRequest(BaseModel):
    stops: list[StopPoint] = Field(min_length=1, max_length=20)
    mode: ModeName = "walk"
    include_institutions: bool = True


class OptimizeRequest(BaseModel):
    p: int = Field(ge=1, le=5)
    mode: ModeName = "walk"
    fixed_stops: list[StopPoint] = Field(default_factory=list, max_length=15)
    include_institutions: bool = True


class NetworkState:
    def __init__(
        self,
        demand: pd.DataFrame,
        candidates: pd.DataFrame,
        graph_path,
        matrix_path,
        matrix_shape: tuple[int, int] | None,
        config: dict,
    ) -> None:
        self.config = config
        self.demand = demand
        self.candidates = candidates
        self.G = ox.io.load_graphml(graph_path)
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
        if matrix_path is not None and matrix_shape is not None and matrix_path.exists():
            self.matrix = load_distance_matrix(matrix_path, matrix_shape)
        self.institutions = pd.DataFrame()
        self._institution_matrix = None
        self._set_institution_arrays(pd.DataFrame())

    def set_institutions(self, institutions: pd.DataFrame) -> None:
        self.institutions = institutions if institutions is not None else pd.DataFrame()
        self._institution_matrix = None
        self._set_institution_arrays(self.institutions)

    def _set_institution_arrays(self, institutions: pd.DataFrame) -> None:
        if institutions is None or institutions.empty:
            self.inst_du = np.array([], dtype=int)
            self.inst_dv = np.array([], dtype=int)
            self.inst_dou = np.array([], dtype=float)
            self.inst_dov = np.array([], dtype=float)
            self.inst_edge_id = np.array([], dtype=object)
            self.inst_edge_pos = np.array([], dtype=float)
            self.inst_perp = np.array([], dtype=float)
            return
        self.inst_du = institutions["node_u"].map(self.node_to_idx).to_numpy(dtype=int)
        self.inst_dv = institutions["node_v"].map(self.node_to_idx).to_numpy(dtype=int)
        self.inst_dou = institutions["offset_u_m"].to_numpy(dtype=float)
        self.inst_dov = institutions["offset_v_m"].to_numpy(dtype=float)
        self.inst_edge_id = institutions["edge_id"].astype(str).to_numpy()
        self.inst_edge_pos = institutions["edge_pos_a_m"].to_numpy(dtype=float)
        self.inst_perp = institutions["perpendicular_m"].to_numpy(dtype=float)

    def demand_for(self, include_institutions: bool) -> pd.DataFrame:
        if include_institutions and len(self.institutions):
            return pd.concat([self.demand, self.institutions], ignore_index=True)
        return self.demand

    def _demand_arrays(self, include_institutions: bool):
        if include_institutions and len(self.institutions):
            return (
                np.concatenate([self.du, self.inst_du]),
                np.concatenate([self.dv, self.inst_dv]),
                np.concatenate([self.dou, self.inst_dou]),
                np.concatenate([self.dov, self.inst_dov]),
                np.concatenate([self.demand_edge_id, self.inst_edge_id]),
                np.concatenate([self.demand_edge_pos, self.inst_edge_pos]),
                np.concatenate([self.demand_perp, self.inst_perp]),
                np.concatenate([self.weights, self.institutions["population"].to_numpy(dtype=float)]),
            )
        return (
            self.du, self.dv, self.dou, self.dov,
            self.demand_edge_id, self.demand_edge_pos, self.demand_perp, self.weights,
        )

    def institution_candidate_matrix(self) -> np.ndarray:
        if self._institution_matrix is not None:
            return self._institution_matrix
        if self.institutions is None or self.institutions.empty:
            self._institution_matrix = np.empty((0, len(self.candidates)), dtype=np.float32)
            return self._institution_matrix
        du, dv, dou, dov = self.inst_du, self.inst_dv, self.inst_dou, self.inst_dov
        demand_edge_id = self.inst_edge_id
        demand_edge_pos = self.inst_edge_pos
        demand_perp = self.inst_perp
        n_demand = len(self.institutions)
        n_candidates = len(self.candidates)
        out = np.empty((n_demand, n_candidates), dtype=np.float32)
        batch_size = 64
        for start in range(0, n_candidates, batch_size):
            end = min(n_candidates, start + batch_size)
            block = self.candidates.iloc[start:end]
            endpoint_nodes = np.unique(np.concatenate([
                block["node_u"].to_numpy(dtype=np.int64),
                block["node_v"].to_numpy(dtype=np.int64),
            ]))
            endpoint_indices = np.array([self.node_to_idx[int(n)] for n in endpoint_nodes], dtype=int)
            dist_to_nodes = dijkstra(self.A, directed=True, indices=endpoint_indices, return_predecessors=False)
            row_of = {int(n): i for i, n in enumerate(endpoint_nodes)}
            for local_j, (_, c) in enumerate(block.iterrows()):
                ru = dist_to_nodes[row_of[int(c["node_u"])]]
                rv = dist_to_nodes[row_of[int(c["node_v"])]]
                via_u = np.minimum(ru[du] + dou, ru[dv] + dov) + float(c["offset_u_m"])
                via_v = np.minimum(rv[du] + dou, rv[dv] + dov) + float(c["offset_v_m"])
                best = np.minimum(via_u, via_v)
                same_edge = demand_edge_id == str(c["edge_id"])
                if np.any(same_edge):
                    direct = (
                        demand_perp[same_edge]
                        + float(c["perpendicular_m"])
                        + np.abs(demand_edge_pos[same_edge] - float(c["edge_pos_a_m"]))
                    )
                    best[same_edge] = np.minimum(best[same_edge], direct)
                out[:, start + local_j] = best.astype("float32")
        self._institution_matrix = out
        return out

    def distances_for_stops(
        self,
        stops: list[StopPoint],
        include_institutions: bool = False,
    ) -> tuple[np.ndarray, np.ndarray, list[dict], np.ndarray]:
        du, dv, dou, dov, demand_edge_id, demand_edge_pos, demand_perp, _weights = self._demand_arrays(
            include_institutions
        )
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
            via_u = np.minimum(ru[du] + dou, ru[dv] + dov) + float(c["offset_u_m"])
            via_v = np.minimum(rv[du] + dou, rv[dv] + dov) + float(c["offset_v_m"])
            best = np.minimum(via_u, via_v)
            same_edge = demand_edge_id == str(c["edge_id"])
            if np.any(same_edge):
                direct = (
                    demand_perp[same_edge]
                    + float(c["perpendicular_m"])
                    + np.abs(demand_edge_pos[same_edge] - float(c["edge_pos_a_m"]))
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
        return nearest, assignment, snapped, all_dist


class AppData:
    def __init__(self) -> None:
        metadata_path = DATA_PROCESSED / "metadata.json"
        if not metadata_path.exists():
            raise RuntimeError("Prepared data not found. Run prepare.bat first.")
        self.metadata = read_json(metadata_path)
        self.config = load_config()
        self.institutions_raw = load_institutions()
        walk_demand = pd.read_parquet(DATA_PROCESSED / "demand.parquet")
        walk_candidates = pd.read_parquet(DATA_PROCESSED / "candidates.parquet")
        walk_shape = None
        if self.metadata.get("distance_matrix_ready"):
            walk_shape = tuple(int(x) for x in self.metadata["distance_matrix_shape"])
        self.modes: dict[str, NetworkState] = {
            "walk": NetworkState(
                walk_demand,
                walk_candidates,
                DATA_PROCESSED / "walk.graphml",
                DATA_PROCESSED / "distance_matrix.float32",
                walk_shape,
                self.config,
            )
        }
        wheel_ready = bool(self.metadata.get("wheelchair_distance_matrix_ready"))
        wheel_demand_path = DATA_PROCESSED / "demand_wheelchair.parquet"
        wheel_graph = DATA_PROCESSED / "wheelchair.graphml"
        if wheel_ready and wheel_demand_path.exists() and wheel_graph.exists():
            wheel_shape = tuple(int(x) for x in self.metadata["wheelchair_distance_matrix_shape"])
            self.modes["wheelchair"] = NetworkState(
                pd.read_parquet(wheel_demand_path),
                pd.read_parquet(DATA_PROCESSED / "candidates_wheelchair.parquet"),
                wheel_graph,
                DATA_PROCESSED / "wheelchair_distance_matrix.float32",
                wheel_shape,
                self.config,
            )
        for state in self.modes.values():
            state.set_institutions(snap_institutions(state.G, self.institutions_raw, self.config))
        self.metadata["available_modes"] = sorted(self.modes.keys())
        self.metadata["institutions"] = institutions_public_payload(self.institutions_raw)
        self.metadata["map_sources"] = {
            "basemap": "OpenStreetMap raster tiles (tile.openstreetmap.org)",
            "walk_network": "OSMnx network_type=walk from OpenStreetMap",
            "wheelchair_network": (
                "OSM pedestrian ways excluding steps and wheelchair=no "
                "(local approximation of OpenRouteService wheelchair routing)"
            ),
            "not_used": ["Google Maps", "Wheelmap routing", "StandortTOOL", "daviplan"],
        }

    def require_mode(self, mode: str) -> NetworkState:
        if mode not in self.modes:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Wheelchair network is not prepared. "
                    "Run: .venv\\Scripts\\python.exe -m gilching_optimizer.prepare --wheelchair-only"
                ),
            )
        return self.modes[mode]


@lru_cache(maxsize=1)
def get_app_data() -> AppData:
    return AppData()


app = FastAPI(title="Gilching Stop Optimizer", version="0.3.0")
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
        s = get_app_data()
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


def _assignment_payload(demand: pd.DataFrame, nearest: np.ndarray, assignment: np.ndarray) -> list[dict]:
    result = []
    for demand_id, a, d in zip(demand["demand_id"], assignment, nearest):
        result.append({
            "demand_id": str(demand_id),
            "stop": int(a),
            "distance_m": None if not np.isfinite(d) else float(d),
        })
    return result


def _institution_meta(s: NetworkState, include_institutions: bool) -> dict:
    inst_w = float(s.institutions["population"].sum()) if include_institutions and len(s.institutions) else 0.0
    return {
        "include_institutions": bool(include_institutions and len(s.institutions)),
        "residential_population": float(s.weights.sum()),
        "institution_weight": inst_w,
    }


@app.get("/api/institutions")
def institutions():
    try:
        data = get_app_data()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return institutions_public_payload(data.institutions_raw)


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    data = get_app_data()
    s = data.require_mode(req.mode)
    include = bool(req.include_institutions and len(s.institutions))
    demand = s.demand_for(include)
    weights = demand["population"].to_numpy(dtype=float)
    nearest, assignment, snapped, _ = s.distances_for_stops(req.stops, include_institutions=include)
    finite = np.isfinite(nearest)
    if not finite.any():
        raise HTTPException(422, "No demand point is reachable from the selected stops")
    if not finite.all():
        nearest = nearest.copy()
        nearest[~finite] = np.nan
    stats = summarize_distances(nearest, weights)
    return {
        "stats": stats,
        "stops": [p.model_dump() for p in req.stops],
        "snap_info": snapped,
        "assignments": _assignment_payload(demand, nearest, assignment),
        "mode": req.mode,
        **_institution_meta(s, include),
    }


@app.post("/api/optimize")
def optimize(req: OptimizeRequest):
    data = get_app_data()
    s = data.require_mode(req.mode)
    if s.matrix is None:
        raise HTTPException(503, "Distance matrix is not ready. Re-run prepare.bat without --skip-matrix.")
    if req.p > len(s.candidates):
        raise HTTPException(422, "p exceeds candidate count")
    include = bool(req.include_institutions and len(s.institutions))
    demand = s.demand_for(include)
    matrix = s.matrix
    weights = s.weights
    if include:
        matrix, weights = stack_institution_demand(
            s.matrix,
            s.weights,
            s.institution_candidate_matrix(),
            s.institutions["population"].to_numpy(dtype=float),
        )
    baseline = None
    if req.fixed_stops:
        baseline, _, _, _ = s.distances_for_stops(req.fixed_stops, include_institutions=include)
    result = optimize_p_median(matrix, weights, req.p, baseline=baseline)
    selected = s.candidates.iloc[result.selected].copy()
    dist_new = np.asarray(matrix[:, result.selected], dtype=np.float64)
    if req.fixed_stops:
        _, _, _, dist_fixed = s.distances_for_stops(req.fixed_stops, include_institutions=include)
        all_dist = np.vstack([dist_fixed, dist_new.T])
        assignment = np.argmin(all_dist, axis=0)
        nearest = all_dist[assignment, np.arange(all_dist.shape[1])]
    else:
        assignment = np.argmin(dist_new, axis=1)
        nearest = dist_new[np.arange(len(demand)), assignment]
    stats = summarize_distances(nearest, weights)
    new_stops = [
        {
            "lat": float(row.lat),
            "lon": float(row.lon),
            "candidate_id": int(row.candidate_id),
            "kind": "new",
        }
        for row in selected.itertuples()
    ]
    return {
        "stats": stats,
        "stops": new_stops,
        "fixed_stops": [p.model_dump() | {"kind": "fixed"} for p in req.fixed_stops],
        "method": "exact-for-p1; greedy-plus-1-swap-for-p>1; fixed stops held as baseline; schools optional extra demand",
        "assignments": _assignment_payload(demand, nearest, assignment),
        "mode": req.mode,
        **_institution_meta(s, include),
    }
