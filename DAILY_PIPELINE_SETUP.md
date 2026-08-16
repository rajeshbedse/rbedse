# Daily NSE Pipeline — Phase 1 Automation

This patch moves daily data generation to GitHub Actions. Render remains the web host and consumes the generated `output/YYYY-MM-DD/` snapshot from Git.

## What was added

- `.github/workflows/daily-nse-scan.yml` — weekday schedule at 20:30 IST plus manual `workflow_dispatch`.
- `requirements-pipeline.txt` — dependencies required only by the data pipeline.
- `nse_pipeline/validate_output.py` — blocks publication when required outputs or core data are missing/invalid.
- `meta.json` now records `status`, `generated_at`, and `failed_urls`.

## First test

After committing these files, do **not** wait for the scheduled run. Open GitHub → Actions → **Daily NSE Scan** → **Run workflow**.

The workflow will:

1. install Python and pipeline dependencies;
2. install Chromium + OS dependencies for Playwright;
3. calculate the India-local run date;
4. run the existing NSE scraper/analyzer/reporter;
5. validate `output/YYYY-MM-DD/`;
6. commit only that daily output folder; and
7. push the generated snapshot to `main`.

A successful push will then trigger the existing Render deployment.

## Important operational note

The workflow intentionally runs the existing scraper unchanged. It uses Playwright with a visible browser under the GitHub runner's virtual display. NSE may reject or throttle GitHub-hosted runner IPs; the first manual run is therefore the required compatibility test before relying on the schedule.

## No Render changes required

The Render web service continues to use `requirements-web.txt` and the Flask portal. The workflow is the data-generation job; Render is only the serving layer.
