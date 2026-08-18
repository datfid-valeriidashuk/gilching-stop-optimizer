# Gilching Stop Optimizer

A local application for placing 1, 2, 3, or more service points in the Gemeinde Gilching, minimizing the average walking distance from a resident to the nearest point.

Core objective function:

\[
D(S)=\frac{\sum_i n_i\min_{s\in S} d_{walk}(i,s)}{\sum_i n_i}
\]

where `n_i` is the estimated population of a building or a Zensus fallback cell, and `d_walk` is the shortest-path distance along the OpenStreetMap pedestrian graph.

## What version 0.1 can do

- loads the Gemeinde Gilching boundary via OSM/Nominatim;
- downloads the OpenStreetMap pedestrian network;
- downloads the road network to generate candidate stop locations;
- automatically downloads the official Zensus 2022 population grid at 100 x 100 m resolution;
- downloads OSM building footprints;
- estimates a building's residential capacity from its footprint area, type, and `building:levels`;
- allocates each 100 m Zensus cell's population across the plausible residential buildings within that cell;
- if a populated cell has no plausible residential OSM building, it does not discard the population but creates a fallback demand point at the cell center;
- connects demand points and selected points to pedestrian edges, not only to intersections;
- computes mean, median, P90, P95, and the share of population within 300, 500, and 750 m;
- lets you place points manually on the interactive map;
- automatically optimizes 1, 2, 3, 4, or 5 points;
- shows which nearest point each building is assigned to.

## Data sources

### Zensus 2022

Official Destatis population grid:

`https://www.destatis.de/static/DE/zensus/gitterdaten/Zensus2022_Bevoelkerungszahl.zip`

The file used is:

`Zensus2022_Bevoelkerungszahl_100m-Gitter.csv`

Fields: `GITTER_ID_100m`, `x_mp_100m`, `y_mp_100m`, `Einwohner`. Zensus coordinates are in EPSG:3035.

### OpenStreetMap

OSMnx is used for:

- the Gilching boundary;
- building footprints;
- the pedestrian network;
- the road network for candidate locations.

Standard OpenStreetMap attribution is shown on the map.

## Public demo (GitHub + free webpage)

Source belongs on **GitHub** (or GitLab). The live webpage cannot go on **Vercel**: this is a long-running Python GIS API, not a static site. Use **Render** (free) for the public URL. Step-by-step: [DEPLOY.md](DEPLOY.md).

## Installation on Windows

Python 3.12 x64 is recommended.

1. Install Python 3.12 from python.org. During installation, keep the Python Launcher (`py`).
2. Extract this folder to a convenient location, e.g. `C:\Projects\gilching-stop-optimizer`.
3. Double-click `setup.bat` once. It creates `.venv` and installs the dependencies.
4. Double-click `prepare.bat` once. This step requires internet access and prepares the local data.
5. After successful preparation, run `run.bat`.
6. The browser will open `http://127.0.0.1:8000`.

After preparation, internet access is only needed for background OpenStreetMap tiles in the browser. Distance calculation and optimization run entirely on local data.

## First run

`prepare.bat` performs the heaviest work:

1. downloads Zensus data;
2. fetches OSM buildings;
3. fetches the walk network;
4. fetches the drive network;
5. allocates population across buildings;
6. generates candidate locations;
7. computes the `demand x candidates` walking distance matrix.

All results are saved in `data/processed/`.

OSMnx also uses a cache in `data/raw/osmnx_cache/`, so re-running preparation usually does not require re-downloading all Overpass responses.

## Using the map

1. Choose the number of points, e.g. `3`.
2. Either click the map three times, or click `Find optimal points`.
3. For manual points, click `Compute my points`. Once exactly the required number of points is placed, the calculation also runs automatically after moving a marker.
4. A marker can be dragged with the mouse.
5. Right-click a marker to remove it.
6. Clicking a building shows its estimated population and the distance to the nearest selected point.

## Interpreting the optimization

For a single point, the algorithm scans all candidate locations and finds the exact best option within that discrete set.

For two or more points, the following is used:

1. greedy sequential addition;
2. 1-swap local search;
3. repeating swap iterations until no improvement or a limit is reached.

This is significantly faster than a full brute-force search. A global optimum for `p > 1` is not guaranteed in version 0.1.

## Candidate locations

Defaults in `config.yaml`:

```yaml
candidate_mode: "drive"
candidate_spacing_m: 80
max_candidates: 2500
```

That is, candidates are generated roughly every 80 m along drivable OSM roads inside Gilching, and each point is then connected to the pedestrian graph.

This is a reasonable first filter for a bus-stop example, but it does not mean every such position is legally or physically allowed to host a bus stop. For a real transit project, the candidate set should be further filtered by road width, traffic direction, intersections, safety, existing stop infrastructure, and municipal requirements.

If you want to optimize arbitrary pedestrian-facing amenities rather than bus stops, you can change:

```yaml
candidate_mode: "walk"
```

## Population accuracy

The building population estimate is not registry-level information about the actual residents of a specific building.

The model uses the official Zensus 2022 grid at 100 x 100 m resolution and only distributes each cell's population among plausible residential OSM buildings. A building's weight is approximately equal to:

`footprint area x estimated floors x residential score`.

Therefore, the overall spatial demand pattern is substantially better than a random distribution, but the exact number of residents attributed to an individual building should be treated as a model estimate.

## Walking distance accuracy

The distance is not Euclidean distance. It is computed over the OSM walk graph.

The demand point and the user-selected point are each connected to the nearest pedestrian edge. The distance via both endpoints of that edge is considered separately, and the best network path is taken. This is more accurate than simply snapping to the nearest graph node.

Limitations still depend on OSM data quality. If a passage, crossing, gate, or footpath is missing, the route may be inaccurate.

## Structure

```text
gilching-stop-optimizer/
  config.yaml
  setup.bat
  prepare.bat
  run.bat
  requirements.txt
  gilching_optimizer/
    app.py
    common.py
    metrics.py
    optimizer.py
    prepare.py
    static/
      index.html
  data/
    raw/
    processed/
  tests/
```

## API

Once running, FastAPI exposes:

- `GET /api/status`
- `GET /api/boundary`
- `GET /api/buildings`
- `GET /api/fallback`
- `POST /api/analyze`
- `POST /api/optimize`

Example manual calculation:

```json
{
  "stops": [
    {"lat": 48.11, "lon": 11.29},
    {"lat": 48.10, "lon": 11.30},
    {"lat": 48.12, "lon": 11.31}
  ]
}
```

## Changing parameters

The main parameters are in `config.yaml`.

After changing parameters that affect the data or candidate locations, run `prepare.bat` again.
