from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import requests
from pyproj import Transformer
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString, Point, box

from .common import DATA_PROCESSED, DATA_RAW, load_config, read_json, write_json

NON_RESIDENTIAL = {
    "garage", "garages", "shed", "roof", "carport", "industrial", "commercial",
    "retail", "warehouse", "office", "school", "church", "chapel", "hospital",
    "kindergarten", "public", "service", "construction", "greenhouse", "barn",
    "farm_auxiliary", "stable", "hangar", "transformer_tower", "train_station",
}
RESIDENTIAL = {
    "apartments", "residential", "house", "detached", "semidetached_house",
    "terrace", "bungalow", "dormitory", "ger", "houseboat",
}
NON_RES_TAG_COLUMNS = ["amenity", "shop", "office", "tourism", "industrial"]


def log(message: str) -> None:
    print(f"[prepare] {message}", flush=True)


FALLBACK_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


def configure_overpass_endpoint(config: dict) -> None:
    """Pick a reachable Overpass endpoint.

    The default overpass-api.de is sometimes unreachable from certain
    networks/ISPs while community mirrors stay up. An explicit
    `overpass_url` in config.yaml always wins; otherwise we probe a short
    list of known mirrors and use the first one that responds.
    """
    explicit = config.get("overpass_url")
    candidates = [explicit] if explicit else FALLBACK_OVERPASS_ENDPOINTS
    for base_url in candidates:
        status_url = base_url.rstrip("/") + "/status"
        try:
            resp = requests.get(status_url, timeout=8)
            if resp.status_code < 500:
                ox.settings.overpass_url = base_url
                log(f"Using Overpass endpoint: {base_url}")
                return
        except requests.RequestException as exc:
            log(f"Overpass endpoint unreachable ({base_url}): {exc}")
    if explicit:
        raise RuntimeError(f"Configured overpass_url is unreachable: {explicit}")
    raise RuntimeError(
        "No Overpass endpoint from the built-in mirror list is reachable. "
        "Set 'overpass_url' explicitly in config.yaml to a working mirror."
    )


def download_zensus(config: dict) -> Path:
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_RAW / "Zensus2022_Bevoelkerungszahl.zip"
    csv_path = DATA_RAW / config["zensus_csv_name"]
    if csv_path.exists():
        log(f"Zensus CSV already present: {csv_path.name}")
        return csv_path
    if not zip_path.exists():
        log("Downloading official Destatis Zensus 2022 population grid...")
        with requests.get(config["zensus_url"], stream=True, timeout=120) as response:
            response.raise_for_status()
            with zip_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
    log("Extracting 100 m population CSV...")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        target = config["zensus_csv_name"]
        if target not in names:
            candidates = [n for n in names if "100m" in n and n.lower().endswith(".csv")]
            if not candidates:
                raise RuntimeError(f"No 100m CSV found in {zip_path}")
            target = candidates[0]
        with archive.open(target) as src, csv_path.open("wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
    return csv_path


def get_boundary(config: dict) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    log("Geocoding municipality boundary with OSM/Nominatim...")
    boundary_wgs = ox.geocoder.geocode_to_gdf(config["place_query"])
    if boundary_wgs.empty:
        raise RuntimeError("Could not geocode Gilching municipality boundary.")
    boundary_wgs = boundary_wgs.iloc[[0]][["geometry"]].set_crs(4326)
    boundary_proj = boundary_wgs.to_crs(config["crs_projected"])
    boundary_wgs.to_file(DATA_PROCESSED / "boundary.geojson", driver="GeoJSON")
    return boundary_wgs, boundary_proj


def load_local_census(csv_path: Path, boundary_proj: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    log("Reading Zensus 100 m grid and clipping it to Gilching...")
    boundary_3035 = boundary_proj.to_crs(3035).geometry.iloc[0]
    minx, miny, maxx, maxy = boundary_3035.bounds

    parts: list[pd.DataFrame] = []
    usecols = ["GITTER_ID_100m", "x_mp_100m", "y_mp_100m", "Einwohner"]
    for chunk in pd.read_csv(csv_path, sep=";", usecols=usecols, chunksize=400_000):
        mask = (
            chunk["x_mp_100m"].between(minx - 100, maxx + 100)
            & chunk["y_mp_100m"].between(miny - 100, maxy + 100)
        )
        if mask.any():
            parts.append(chunk.loc[mask].copy())
    if not parts:
        raise RuntimeError("No Zensus cells found near the municipality boundary.")
    df = pd.concat(parts, ignore_index=True)
    df["Einwohner"] = pd.to_numeric(df["Einwohner"], errors="coerce").fillna(0).clip(lower=0)
    cells = gpd.GeoDataFrame(
        df.rename(columns={"GITTER_ID_100m": "grid_id", "Einwohner": "population"}),
        geometry=gpd.points_from_xy(df["x_mp_100m"], df["y_mp_100m"]),
        crs=3035,
    )
    cells = cells[cells.geometry.within(boundary_3035)].copy()
    cells["geometry"] = [box(x - 50, y - 50, x + 50, y + 50) for x, y in zip(cells["x_mp_100m"], cells["y_mp_100m"])]
    cells = cells.to_crs(boundary_proj.crs)
    log(f"Selected {len(cells)} inhabited/empty 100 m cells inside Gilching boundary.")
    return cells[["grid_id", "population", "geometry"]]


def _first_scalar(value):
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return next(iter(value), None)
    return value


def _parse_levels(value, default: float) -> float:
    value = _first_scalar(value)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    try:
        text = str(value).replace(",", ".").split(";")[0]
        result = float(text)
        return result if 0.5 <= result <= 30 else default
    except (ValueError, TypeError):
        return default


def prepare_buildings(config: dict, boundary_wgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    log("Downloading building footprints from OpenStreetMap...")
    poly = boundary_wgs.geometry.iloc[0]
    b = ox.features.features_from_polygon(poly, {"building": True}).copy()
    b = b[b.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if b.empty:
        raise RuntimeError("No OSM buildings found in Gilching.")
    b = b.to_crs(config["crs_projected"])
    b["building_id"] = [f"{idx[0]}:{idx[1]}" if isinstance(idx, tuple) else str(idx) for idx in b.index]
    btype = b.get("building", pd.Series("yes", index=b.index)).map(_first_scalar).fillna("yes").astype(str).str.lower()
    b["building_type"] = btype

    nonres_tag = pd.Series(False, index=b.index)
    for col in NON_RES_TAG_COLUMNS:
        if col in b.columns:
            nonres_tag |= b[col].notna()

    score = np.where(btype.isin(RESIDENTIAL), 1.0, np.where(btype.isin(NON_RESIDENTIAL) | nonres_tag, 0.0, 0.60))
    b["residential_score"] = score
    b["area_m2"] = b.geometry.area
    b = b[(b["residential_score"] > 0) & (b["area_m2"] >= 20)].copy()

    floors_default = config["assumed_floors"]
    level_values = b.get("building:levels", pd.Series(np.nan, index=b.index))
    floors = []
    confidence = []
    for idx, row in b.iterrows():
        default = float(floors_default.get(row["building_type"], floors_default["default"]))
        raw = level_values.loc[idx] if idx in level_values.index else np.nan
        parsed = _parse_levels(raw, default)
        floors.append(parsed)
        explicit_res = row["building_type"] in RESIDENTIAL
        explicit_levels = not (raw is None or (isinstance(raw, float) and math.isnan(raw)))
        confidence.append("high" if explicit_res and explicit_levels else "medium" if explicit_res else "low")
    b["floors_est"] = floors
    b["confidence"] = confidence
    b["capacity_weight"] = b["area_m2"] * b["floors_est"] * b["residential_score"]
    log(f"Kept {len(b)} plausible residential buildings.")
    return b


def allocate_population(
    buildings: gpd.GeoDataFrame,
    cells: gpd.GeoDataFrame,
    config: dict,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    log("Allocating each Zensus cell population across plausible residential buildings...")
    reps = buildings[["building_id", "capacity_weight", "geometry"]].copy()
    reps["geometry"] = reps.geometry.representative_point()
    joined = gpd.sjoin(reps, cells[["grid_id", "population", "geometry"]], how="left", predicate="within")
    joined = joined.drop(columns=[c for c in ["index_right"] if c in joined.columns])

    b = buildings.copy()
    b["grid_id"] = joined.set_index("building_id").reindex(b["building_id"])["grid_id"].to_numpy()
    b["estimated_population"] = 0.0

    cell_pop = cells.set_index("grid_id")["population"].to_dict()
    for grid_id, group in b.dropna(subset=["grid_id"]).groupby("grid_id"):
        pop = float(cell_pop.get(grid_id, 0.0))
        if pop <= 0:
            continue
        weights = group["capacity_weight"].to_numpy(dtype=float)
        if not np.isfinite(weights).all() or weights.sum() <= 0:
            weights = np.ones(len(group), dtype=float)
        shares = pop * weights / weights.sum()
        b.loc[group.index, "estimated_population"] = shares

    represented = set(b.loc[b["grid_id"].notna(), "grid_id"].astype(str))
    fallback = cells[(cells["population"] > 0) & (~cells["grid_id"].astype(str).isin(represented))].copy()
    fallback["demand_id"] = [f"grid:{g}" for g in fallback["grid_id"]]
    fallback["source"] = "grid_fallback"
    fallback["building_id"] = None
    fallback["estimated_population"] = fallback["population"].astype(float)
    fallback["geometry"] = fallback.geometry.centroid

    target = config.get("population_scale_target")
    total = float(b["estimated_population"].sum() + fallback["estimated_population"].sum())
    if target:
        factor = float(target) / total
        b["estimated_population"] *= factor
        fallback["estimated_population"] *= factor
        total = float(target)
    log(f"Demand population total: {total:.0f}; fallback cells without a plausible building: {len(fallback)}")
    return b, fallback


def prepare_walk_graph(config: dict, boundary_proj: gpd.GeoDataFrame) -> nx.MultiDiGraph:
    graph_path = DATA_PROCESSED / "walk.graphml"
    boundary_buffer = boundary_proj.geometry.iloc[0].buffer(float(config["walk_buffer_m"]))
    poly_wgs = gpd.GeoSeries([boundary_buffer], crs=boundary_proj.crs).to_crs(4326).iloc[0]
    log("Downloading pedestrian network from OpenStreetMap...")
    G = ox.graph.graph_from_polygon(poly_wgs, network_type="walk", simplify=True, retain_all=False)
    G = ox.projection.project_graph(G, to_crs=config["crs_projected"])
    ox.io.save_graphml(G, graph_path)
    log(f"Walk graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} directed edges.")
    return G


def _edge_geometry(G: nx.MultiDiGraph, u: int, v: int, k: int) -> LineString:
    data = G.get_edge_data(u, v, k)
    geom = data.get("geometry") if data else None
    if geom is None:
        geom = LineString([(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])])
    return geom


def attach_to_walk_edges(G: nx.MultiDiGraph, points: gpd.GeoSeries) -> pd.DataFrame:
    if len(points) == 0:
        return pd.DataFrame(columns=["node_u", "node_v", "offset_u_m", "offset_v_m"])
    xs = points.x.to_numpy()
    ys = points.y.to_numpy()
    nearest = ox.distance.nearest_edges(G, X=xs, Y=ys)
    # osmnx 2.1.1 returns a 1-D object array of (u, v, k) tuples (not an
    # (N, 3) array), for both single and multiple query points.
    nearest = np.array([tuple(edge) for edge in np.atleast_1d(nearest)], dtype=np.int64)
    rows = []
    for point, edge in zip(points, nearest):
        u, v, k = int(edge[0]), int(edge[1]), int(edge[2])
        geom = _edge_geometry(G, u, v, k)
        projection = float(geom.project(point))
        geom_len = float(geom.length)
        if geom_len <= 0:
            frac_from_geom_start = 0.0
        else:
            frac_from_geom_start = projection / geom_len
        u_point = Point(G.nodes[u]["x"], G.nodes[u]["y"])
        if Point(geom.coords[0]).distance(u_point) <= Point(geom.coords[-1]).distance(u_point):
            frac_from_u = frac_from_geom_start
        else:
            frac_from_u = 1.0 - frac_from_geom_start
        edge_len = float(G.get_edge_data(u, v, k).get("length", geom_len))
        perpendicular = float(point.distance(geom))
        along_u = frac_from_u * edge_len
        edge_a, edge_b = sorted((u, v))
        pos_from_a = along_u if u == edge_a else edge_len - along_u
        rows.append({
            "node_u": u,
            "node_v": v,
            "edge_key": k,
            "edge_a": edge_a,
            "edge_b": edge_b,
            "edge_id": f"{edge_a}:{edge_b}:{k}",
            "edge_pos_a_m": pos_from_a,
            "perpendicular_m": perpendicular,
            "offset_u_m": perpendicular + along_u,
            "offset_v_m": perpendicular + (edge_len - along_u),
        })
    return pd.DataFrame(rows)


def make_demand(
    buildings: gpd.GeoDataFrame,
    fallback: gpd.GeoDataFrame,
    G: nx.MultiDiGraph,
    config: dict,
) -> pd.DataFrame:
    log("Connecting demand points to the pedestrian graph edges...")
    bpos = buildings[buildings["estimated_population"] > 0].copy()
    bpos["demand_id"] = [f"building:{x}" for x in bpos["building_id"]]
    bpos["source"] = "building"
    bpoints = bpos.geometry.representative_point()

    demand = pd.DataFrame({
        "demand_id": bpos["demand_id"].to_numpy(),
        "source": bpos["source"].to_numpy(),
        "building_id": bpos["building_id"].to_numpy(),
        "population": bpos["estimated_population"].to_numpy(dtype=float),
        "x": bpoints.x.to_numpy(),
        "y": bpoints.y.to_numpy(),
    })
    if len(fallback):
        fp = fallback.geometry
        fdf = pd.DataFrame({
            "demand_id": fallback["demand_id"].to_numpy(),
            "source": fallback["source"].to_numpy(),
            "building_id": fallback["building_id"].to_numpy(),
            "population": fallback["estimated_population"].to_numpy(dtype=float),
            "x": fp.x.to_numpy(),
            "y": fp.y.to_numpy(),
        })
        demand = pd.concat([demand, fdf], ignore_index=True)

    gs = gpd.GeoSeries(gpd.points_from_xy(demand["x"], demand["y"]), crs=config["crs_projected"])
    conn = attach_to_walk_edges(G, gs)
    demand = pd.concat([demand.reset_index(drop=True), conn.reset_index(drop=True)], axis=1)
    to_wgs = Transformer.from_crs(config["crs_projected"], 4326, always_xy=True)
    lon, lat = to_wgs.transform(demand["x"].to_numpy(), demand["y"].to_numpy())
    demand["lon"] = lon
    demand["lat"] = lat
    demand.to_parquet(DATA_PROCESSED / "demand.parquet", index=False)

    building_pop_map = demand[demand["source"] == "building"].set_index("building_id")["population"]
    buildings["demand_id"] = buildings["building_id"].map(lambda x: f"building:{x}" if x in building_pop_map.index else None)
    display_cols = ["building_id", "demand_id", "building_type", "floors_est", "area_m2", "confidence", "estimated_population", "geometry"]
    buildings[display_cols].to_crs(4326).to_file(DATA_PROCESSED / "buildings.geojson", driver="GeoJSON")

    if len(fallback):
        fb = fallback[["demand_id", "estimated_population", "geometry"]].to_crs(4326)
        fb.to_file(DATA_PROCESSED / "fallback_points.geojson", driver="GeoJSON")
    else:
        write_json(DATA_PROCESSED / "fallback_points.geojson", {"type": "FeatureCollection", "features": []})
    return demand


def _sample_edge_points(edges: gpd.GeoDataFrame, spacing: float, boundary) -> list[Point]:
    points: list[Point] = []
    seen_edge = set()
    for idx, row in edges.iterrows():
        u, v = int(idx[0]), int(idx[1])
        pair = tuple(sorted((u, v)))
        osmid = str(row.get("osmid", ""))
        key = (pair, osmid)
        if key in seen_edge:
            continue
        seen_edge.add(key)
        geom = row.geometry
        if geom is None or geom.length <= 0:
            continue
        n = max(1, int(math.ceil(geom.length / spacing)))
        for t in np.linspace(0, geom.length, n + 1):
            p = geom.interpolate(float(t))
            if boundary.covers(p):
                points.append(p)
    return points


def prepare_candidates(
    config: dict,
    boundary_proj: gpd.GeoDataFrame,
    G_walk: nx.MultiDiGraph,
) -> pd.DataFrame:
    mode = str(config.get("candidate_mode", "drive")).lower()
    spacing = float(config.get("candidate_spacing_m", 80))
    boundary = boundary_proj.geometry.iloc[0]
    if mode == "drive":
        log("Downloading drivable road network for candidate stop locations...")
        poly_wgs = boundary_proj.to_crs(4326).geometry.iloc[0]
        G_source = ox.graph.graph_from_polygon(poly_wgs, network_type="drive", simplify=True, retain_all=False)
        G_source = ox.projection.project_graph(G_source, to_crs=config["crs_projected"])
    else:
        G_source = G_walk
    edges = ox.convert.graph_to_gdfs(G_source, nodes=False, edges=True, fill_edge_geometry=True)
    points = _sample_edge_points(edges, spacing, boundary)
    if not points:
        raise RuntimeError("No candidate stop points were generated.")

    coords = np.array([(round(p.x, 1), round(p.y, 1)) for p in points])
    _, unique_idx = np.unique(coords, axis=0, return_index=True)
    points = [points[i] for i in np.sort(unique_idx)]
    max_candidates = int(config.get("max_candidates", 2500))
    if len(points) > max_candidates:
        choose = np.linspace(0, len(points) - 1, max_candidates).astype(int)
        points = [points[i] for i in choose]

    gs = gpd.GeoSeries(points, crs=config["crs_projected"])
    conn = attach_to_walk_edges(G_walk, gs)
    candidates = pd.DataFrame({
        "candidate_id": np.arange(len(points), dtype=int),
        "x": gs.x.to_numpy(),
        "y": gs.y.to_numpy(),
    })
    candidates = pd.concat([candidates, conn], axis=1)
    to_wgs = Transformer.from_crs(config["crs_projected"], 4326, always_xy=True)
    lon, lat = to_wgs.transform(candidates["x"].to_numpy(), candidates["y"].to_numpy())
    candidates["lon"] = lon
    candidates["lat"] = lat
    candidates.to_parquet(DATA_PROCESSED / "candidates.parquet", index=False)
    log(f"Generated {len(candidates)} candidate locations ({mode}, spacing about {spacing:.0f} m).")
    return candidates


def _simple_adjacency(G: nx.MultiDiGraph):
    D = nx.DiGraph()
    D.add_nodes_from(G.nodes())
    for u, v, data in G.edges(data=True):
        w = float(data.get("length", 1.0))
        if D.has_edge(u, v):
            if w < D[u][v]["length"]:
                D[u][v]["length"] = w
        else:
            D.add_edge(u, v, length=w)
    nodes = list(D.nodes())
    node_to_idx = {int(n): i for i, n in enumerate(nodes)}
    A = nx.to_scipy_sparse_array(D, nodelist=nodes, weight="length", dtype=np.float64, format="csr")
    return A, node_to_idx, nodes


def compute_distance_matrix(
    G: nx.MultiDiGraph,
    demand: pd.DataFrame,
    candidates: pd.DataFrame,
    matrix_path: Path | None = None,
    label: str = "walk",
) -> tuple[int, int]:
    log(f"Computing {label} candidate-to-demand walking distance matrix...")
    A, node_to_idx, _ = _simple_adjacency(G)
    du = demand["node_u"].map(node_to_idx).to_numpy(dtype=int)
    dv = demand["node_v"].map(node_to_idx).to_numpy(dtype=int)
    dou = demand["offset_u_m"].to_numpy(dtype=float)
    dov = demand["offset_v_m"].to_numpy(dtype=float)
    demand_edge_id = demand["edge_id"].astype(str).to_numpy()
    demand_edge_pos = demand["edge_pos_a_m"].to_numpy(dtype=float)
    demand_perp = demand["perpendicular_m"].to_numpy(dtype=float)
    n_demand = len(demand)
    n_candidates = len(candidates)
    matrix_path = Path(matrix_path) if matrix_path else DATA_PROCESSED / "distance_matrix.float32"
    mm = np.memmap(matrix_path, dtype="float32", mode="w+", shape=(n_demand, n_candidates))

    batch_size = 64
    for start in range(0, n_candidates, batch_size):
        end = min(n_candidates, start + batch_size)
        block = candidates.iloc[start:end]
        endpoint_nodes = np.unique(np.concatenate([block["node_u"].to_numpy(dtype=np.int64), block["node_v"].to_numpy(dtype=np.int64)]))
        endpoint_indices = np.array([node_to_idx[int(n)] for n in endpoint_nodes], dtype=int)
        dist_to_nodes = dijkstra(A, directed=True, indices=endpoint_indices, return_predecessors=False)
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
            mm[:, start + local_j] = best.astype("float32")
        mm.flush()
        log(f"  {label} distance matrix: {end}/{n_candidates} candidates")

    finite = np.isfinite(mm)
    if not finite.all():
        unreachable = int((~finite).sum())
        log(f"Warning: {unreachable} demand-candidate pairs are unreachable in the {label} graph.")
    return n_demand, n_candidates


# OSMnx walk already includes steps. Wheelchair mode drops stairs and ways
# tagged wheelchair=no. This is a local approximation of OpenRouteService's
# wheelchair profile; kerb height / incline are only used when OSM has them.
WHEELCHAIR_CUSTOM_FILTER = (
    '["highway"]["area"!~"yes"]'
    '["highway"!~"abandoned|bus_guideway|construction|cycleway|elevator|escalator|'
    'motor|planned|platform|proposed|raceway|steps"]'
    '["foot"!~"no"]["access"!~"private"]'
    '["wheelchair"!~"no"]'
)
CONNECTOR_COLS = [
    "node_u", "node_v", "edge_key", "edge_a", "edge_b", "edge_id",
    "edge_pos_a_m", "perpendicular_m", "offset_u_m", "offset_v_m",
]


def _ensure_wheelchair_tags() -> None:
    extra = {"wheelchair", "kerb", "kerb:height", "incline", "smoothness", "width", "surface"}
    ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way) | extra)


def _drop_blocked_wheelchair_edges(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    remove = []
    for u, v, k, data in G.edges(keys=True, data=True):
        highway = str(data.get("highway") or "").lower()
        wheelchair = str(data.get("wheelchair") or "").lower()
        if highway == "steps" or wheelchair in {"no", "false"}:
            remove.append((u, v, k))
    if remove:
        G.remove_edges_from(remove)
    isolated = [n for n, deg in G.degree() if deg == 0]
    if isolated:
        G.remove_nodes_from(isolated)
    return G


def prepare_wheelchair_graph(config: dict, boundary_proj: gpd.GeoDataFrame) -> nx.MultiDiGraph:
    graph_path = DATA_PROCESSED / "wheelchair.graphml"
    boundary_buffer = boundary_proj.geometry.iloc[0].buffer(float(config["walk_buffer_m"]))
    poly_wgs = gpd.GeoSeries([boundary_buffer], crs=boundary_proj.crs).to_crs(4326).iloc[0]
    log("Downloading wheelchair-oriented pedestrian network from OpenStreetMap (no steps, wheelchair!=no)...")
    _ensure_wheelchair_tags()
    G = ox.graph.graph_from_polygon(
        poly_wgs,
        custom_filter=WHEELCHAIR_CUSTOM_FILTER,
        simplify=True,
        retain_all=False,
    )
    G = _drop_blocked_wheelchair_edges(G)
    G = ox.projection.project_graph(G, to_crs=config["crs_projected"])
    ox.io.save_graphml(G, graph_path)
    log(f"Wheelchair graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} directed edges.")
    return G


def snap_xy_frame(G: nx.MultiDiGraph, df: pd.DataFrame, config: dict) -> pd.DataFrame:
    gs = gpd.GeoSeries(gpd.points_from_xy(df["x"], df["y"]), crs=config["crs_projected"])
    conn = attach_to_walk_edges(G, gs)
    keep = df.drop(columns=[c for c in CONNECTOR_COLS if c in df.columns], errors="ignore").reset_index(drop=True)
    return pd.concat([keep, conn.reset_index(drop=True)], axis=1)


def prepare_wheelchair_mode(config: dict, boundary_proj: gpd.GeoDataFrame | None = None, skip_matrix: bool = False) -> dict:
    """Build wheelchair graph, re-snap existing demand/candidates, compute matrix."""
    demand_src = DATA_PROCESSED / "demand.parquet"
    cand_src = DATA_PROCESSED / "candidates.parquet"
    if not demand_src.exists() or not cand_src.exists():
        raise RuntimeError("Walk-mode demand/candidates are missing. Run a full prepare.bat first.")
    if boundary_proj is None:
        boundary_path = DATA_PROCESSED / "boundary.geojson"
        if not boundary_path.exists():
            raise RuntimeError("boundary.geojson is missing. Run a full prepare.bat first.")
        boundary_proj = gpd.read_file(boundary_path).to_crs(config["crs_projected"])

    demand = pd.read_parquet(demand_src)
    candidates = pd.read_parquet(cand_src)
    G = prepare_wheelchair_graph(config, boundary_proj)
    demand_w = snap_xy_frame(G, demand, config)
    candidates_w = snap_xy_frame(G, candidates, config)
    demand_w.to_parquet(DATA_PROCESSED / "demand_wheelchair.parquet", index=False)
    candidates_w.to_parquet(DATA_PROCESSED / "candidates_wheelchair.parquet", index=False)
    if skip_matrix:
        shape = [len(demand_w), len(candidates_w)]
        ready = False
    else:
        shape = list(compute_distance_matrix(
            G, demand_w, candidates_w,
            matrix_path=DATA_PROCESSED / "wheelchair_distance_matrix.float32",
            label="wheelchair",
        ))
        ready = True
    return {
        "wheelchair_demand_count": len(demand_w),
        "wheelchair_candidate_count": len(candidates_w),
        "wheelchair_distance_matrix_shape": shape,
        "wheelchair_distance_matrix_ready": ready,
        "wheelchair_method": (
            "OSM pedestrian ways excluding highway=steps and wheelchair=no. "
            "Approximation of OpenRouteService wheelchair routing; not Google Maps or Wheelmap."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Gilching stop optimizer data")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--skip-matrix", action="store_true", help="Prepare GIS data but do not compute the candidate distance matrix")
    parser.add_argument(
        "--wheelchair-only",
        action="store_true",
        help="Reuse existing demand/candidates and only build the wheelchair graph and matrix",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(DATA_RAW / "osmnx_cache")
    ox.settings.log_console = False
    ox.settings.requests_timeout = 300
    configure_overpass_endpoint(config)

    if args.wheelchair_only:
        wheelchair_meta = prepare_wheelchair_mode(config, skip_matrix=args.skip_matrix)
        metadata_path = DATA_PROCESSED / "metadata.json"
        metadata = read_json(metadata_path) if metadata_path.exists() else {}
        metadata.update(wheelchair_meta)
        write_json(metadata_path, metadata)
        log("Wheelchair preparation finished successfully.")
        log(json.dumps(wheelchair_meta, ensure_ascii=False, indent=2))
        return

    census_csv = download_zensus(config)
    boundary_wgs, boundary_proj = get_boundary(config)
    cells = load_local_census(census_csv, boundary_proj)
    buildings = prepare_buildings(config, boundary_wgs)
    buildings, fallback = allocate_population(buildings, cells, config)
    G_walk = prepare_walk_graph(config, boundary_proj)
    demand = make_demand(buildings, fallback, G_walk, config)
    candidates = prepare_candidates(config, boundary_proj, G_walk)
    if args.skip_matrix:
        shape = [len(demand), len(candidates)]
        matrix_ready = False
    else:
        shape = list(compute_distance_matrix(G_walk, demand, candidates))
        matrix_ready = True

    centroid = boundary_wgs.geometry.iloc[0].centroid
    metadata = {
        "place_query": config["place_query"],
        "crs_projected": config["crs_projected"],
        "demand_count": len(demand),
        "candidate_count": len(candidates),
        "population_total": float(demand["population"].sum()),
        "distance_matrix_shape": shape,
        "distance_matrix_ready": matrix_ready,
        "candidate_mode": config.get("candidate_mode", "drive"),
        "candidate_spacing_m": config.get("candidate_spacing_m", 80),
        "center": {"lat": float(centroid.y), "lon": float(centroid.x)},
        "notes": [
            "Population is Zensus 2022 100m-cell population allocated to plausible OSM residential buildings.",
            "Cells with population but no plausible residential OSM building are retained as fallback demand at the cell center.",
            "Walking distances use the OSM pedestrian graph (OSMnx network_type=walk) and edge connectors, not straight-line or Google Maps.",
            "For p>1 the optimizer uses greedy construction plus 1-swap local search over candidate locations.",
        ],
    }
    try:
        wheelchair_meta = prepare_wheelchair_mode(config, boundary_proj, skip_matrix=args.skip_matrix)
        metadata.update(wheelchair_meta)
    except Exception as exc:
        log(f"Wheelchair network could not be prepared ({exc}). Walk mode is still available.")
        metadata["wheelchair_distance_matrix_ready"] = False
    write_json(DATA_PROCESSED / "metadata.json", metadata)
    log("Preparation finished successfully.")
    log(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
