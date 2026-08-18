# Deploy the current app (free public webpage)

This is a **Python FastAPI** app. It loads GeoPandas, OSMnx, a walking graph, and a ~33 MB distance matrix in a long-running process. That is why the host has to be a real Python web service, not a static/serverless frontend platform.

## Vercel is not a fit

[Vercel](https://vercel.com) is built for static sites and short serverless functions (Node, or tiny Python lambdas). This project will not run there as-is:

- GeoPandas / SciPy / OSMnx plus prepared data exceed typical serverless size and memory limits.
- `/api/optimize` and `/api/analyze` take several seconds and keep graph state in RAM. Serverless functions are stateless and time out.
- There is no useful way to “export the map as static HTML” — the map needs the live API.

Do **not** connect this repo to Vercel expecting the optimizer to work. Use GitHub for the source, and Render (or Hugging Face Spaces) for the live page.

## 1. Put the source on GitHub

The repo should include `data/processed/` (already prepared). Visitors and the host can start the app without running `prepare.bat`.

If the remote is not set yet:

1. Create an empty public repository on GitHub, e.g. `gilching-stop-optimizer`.
2. From this folder:

```text
git init
git add .
git commit -m "Gilching stop optimizer: working local app"
git branch -M main
git remote add origin https://github.com/<your-user>/gilching-stop-optimizer.git
git push -u origin main
```

GitLab works the same way (`git remote add origin https://gitlab.com/<your-user>/gilching-stop-optimizer.git`).

## 2. Free live URL on Render (recommended)

[Render](https://render.com) free web services run Python continuously enough for a demo (the service sleeps after ~15 minutes idle, then a cold start of several seconds).

1. Sign in at [https://dashboard.render.com](https://dashboard.render.com) with GitHub.
2. **New** → **Web Service** → pick `gilching-stop-optimizer`.
3. Render should read `render.yaml`. If you create the service by hand:
   - Runtime: Python
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn gilching_optimizer.app:app --host 0.0.0.0 --port $PORT`
   - Health check: `/health`
   - Environment variable: `PYTHON_VERSION=3.12.8` (required; Render otherwise uses Python 3.14, which cannot install pyarrow)
4. Choose the **free** instance type.
5. Deploy. After a few minutes the app is at `https://<name>.onrender.com`.

First deploy installs GeoPandas and friends, so it can take 5–10 minutes. The first visit after idle sleep is slower; later clicks are normal.

## Alternative: Hugging Face Spaces (Docker)

If you already use Hugging Face:

1. Create a new **Docker** Space.
2. Push this repo (including the `Dockerfile`) to the Space.
3. Set the app port to `7860` in the Space README metadata, or change the Dockerfile `CMD` port to `7860`.

Free Spaces hibernate after idle time, similar to Render.

## What is published

Prepared GeoJSON, the walk graph, and the distance matrix are derived from Destatis Zensus 2022 and OpenStreetMap. Keep `ATTRIBUTION.md` with the project. The raw Destatis ZIP stays out of git (`data/raw/`).
