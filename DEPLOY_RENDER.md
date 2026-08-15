# Deploy RYB Finserv to Render (Free)

This deployment package serves the existing Flask portal and the committed scan results from `output/2026-08-15/`.
The NSE scraping pipeline is intentionally **not** run on Render in this first deployment.

## 1. Test locally

From the repository root:

```bash
python -m pip install -r requirements-web.txt
python -m gunicorn --chdir portal --bind 127.0.0.1:5000 app:app
```

Open `http://127.0.0.1:5000`.

Health check: `http://127.0.0.1:5000/healthz`

## 2. Create GitHub repository

Create a new repository, for example:

`ryb-finserv`

Keep it private initially if you do not want the source code public.

## 3. Push this project

```bash
git init
git add .
git commit -m "Prepare RYB Finserv for Render"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/ryb-finserv.git
git push -u origin main
```

## 4. Create Render service

In Render:

- New -> Web Service
- Connect the GitHub repository
- Branch: `main`
- Runtime: Python
- Build command: `pip install -r requirements-web.txt`
- Start command: `gunicorn --chdir portal --bind 0.0.0.0:$PORT app:app`
- Instance type: Free
- Health check path: `/healthz`

The included `render.yaml` can also be used as a Blueprint.

## 5. Environment variables

Set:

- `PYTHON_VERSION=3.13.9`
- `SECRET_KEY=<long random value>`

`render.yaml` is configured to generate the secret automatically.

## Important limitation

Render Free web services have an ephemeral filesystem. Do not depend on newly generated scan files remaining on the server. The current deployment therefore treats the committed `output/2026-08-15/` files as demo/reference data.

For automated daily/weekly NSE scans, move scan storage to persistent external storage or a database in a later phase.
