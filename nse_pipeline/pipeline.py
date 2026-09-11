"""
Main pipeline orchestrator — ties Phases 1, 2, 3 together.
Called by the CLI entry point (run_pipeline) and by the scheduler.
"""
import argparse
import csv as _csv
import io
import json
import logging
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from playwright.sync_api import sync_playwright

from . import __version__
from .config import (
    OUTPUT_ROOT, CSV_FILENAME, EXCEL_FILENAME, FULL_CSV_FILENAME,
    TRADES_CSV_FILENAME, LOG_FILENAME, USER_AGENT, BROWSER_ARGS, NSE_FILING_PERIOD,
)
from . import scraper, analyzer, reporter
from .research_enrichment import build_research_datasets

_REPO_ROOT = Path(__file__).parent.parent
_OUTPUT_ROOT = _REPO_ROOT / OUTPUT_ROOT


def _download_close_bhavcopy(max_lookback: int = 5, as_of_date=None):
    """Download NSE ClsPric using the same Bhavcopy lookup as the analyzer."""
    base = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
    session = requests.Session()
    session.headers.update(headers)
    today = as_of_date or datetime.now().date()
    attempted = []
    for delta in range(max_lookback + 1):
        d = today - pd.Timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        attempted.append(ds)
        try:
            resp = session.get(base.format(date=ds), timeout=20)
            if resp.status_code != 200 or resp.content[:2] != b"PK":
                continue
            z = zipfile.ZipFile(io.BytesIO(resp.content))
            raw = z.read(z.namelist()[0]).decode("utf-8")
            rows = _csv.DictReader(raw.splitlines())
            prices = {}
            for row in rows:
                series = row.get("SctySrs", "").strip()
                if series not in {"EQ", "BE", "BZ"}:
                    continue
                sym = row.get("TckrSymb", "").strip()
                if sym in prices and series != "EQ":
                    continue
                try:
                    prices[sym] = {"LastPrice": float(row["ClsPric"])}
                except (ValueError, KeyError):
                    prices[sym] = {"LastPrice": None}
            logging.getLogger(__name__).info("  CMP prices loaded from NSE closing price for %s — %d symbols", d.strftime("%Y-%m-%d"), len(prices))
            return prices
        except Exception as exc:
            logging.getLogger(__name__).warning("  NSE closing-price fetch failed for %s: %s", ds, exc)
    logging.getLogger(__name__).warning("  NSE closing-price Bhavcopy: no file found for dates %s", attempted)
    return None


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")])


def run(skip_phase1: bool = False, run_date: str | None = None, dry_run: bool = False) -> Path:
    date_str = run_date or datetime.now().strftime("%Y-%m-%d")
    run_dir = _OUTPUT_ROOT / date_str
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / CSV_FILENAME
    excel_path = run_dir / EXCEL_FILENAME
    full_csv = run_dir / FULL_CSV_FILENAME
    log_path = run_dir / LOG_FILENAME
    meta_path = run_dir / "meta.json"
    pipeline_start = time.monotonic()
    _setup_logging(log_path)
    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("NSE WEEKLY INSIDER TRADING PIPELINE  v%s", __version__)
    log.info("Run date : %s", date_str)
    log.info("Output   : %s", run_dir.resolve())
    if dry_run:
        log.info("MODE     : DRY RUN (Phase 1 only — no enrichment, no export)")
    log.info("=" * 60)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=BROWSER_ARGS)
        ctx = browser.new_context(user_agent=USER_AGENT)
        raw_count = 0
        if skip_phase1 and csv_path.exists():
            log.info("--skip-phase1: reusing %s", csv_path)
            try:
                raw_count = len(pd.read_csv(csv_path, encoding="utf-8-sig"))
                log.info("Reused existing NSE snapshot: %d rows", raw_count)
            except Exception as exc:
                log.error("Could not read existing NSE snapshot: %s", exc)
        else:
            raw_count = scraper.run(ctx, csv_path)
        browser.close()
    if dry_run:
        log.info("\nDry run complete. CSV written to: %s", csv_path.resolve())
        return run_dir
    if raw_count == 0:
        duration = round(time.monotonic() - pipeline_start)
        meta = {"run_date": date_str, "generated_at": datetime.now(timezone.utc).isoformat(), "status": "no_data", "filing_period": NSE_FILING_PERIOD, "raw_filings": 0, "failed_urls": 0, "candidates": 0, "shortlisted": 0, "duration_s": duration, "pipeline_version": __version__}
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        log.info("No NSE filings found for %s. Skipping enrichment.", date_str)
        return run_dir
    analyzer._download_bhavcopy = _download_close_bhavcopy
    as_of = datetime.strptime(date_str, "%Y-%m-%d").date()
    final = analyzer.run(csv_path, full_csv, as_of_date=as_of)

    # Additive research layer for the new RYB repository. Existing outputs,
    # scoring and reporter behaviour remain unchanged; failures here should be
    # visible but must not destroy the core Daily NSE Scan result.
    try:
        build_research_datasets(csv_path, full_csv, run_dir, as_of_date=as_of)
    except Exception as exc:
        log.exception("Research dataset enrichment failed; core pipeline output is retained: %s", exc)
        (run_dir / "research_enrichment_error.txt").write_text(str(exc), encoding="utf-8")

    reporter.run(final, excel_path)
    duration = round(time.monotonic() - pipeline_start)
    try:
        candidates = len(pd.read_csv(full_csv, encoding="utf-8-sig"))
    except Exception:
        candidates = 0
    failed_path = run_dir / "failed_urls.txt"
    failed_urls = 0
    if failed_path.exists():
        try: failed_urls = max(0, len(failed_path.read_text(encoding="utf-8").splitlines()) - 1)
        except Exception: failed_urls = 0
    meta = {"run_date": date_str, "generated_at": datetime.now(timezone.utc).isoformat(), "status": "success", "filing_period": NSE_FILING_PERIOD, "raw_filings": raw_count, "failed_urls": failed_urls, "candidates": candidates, "shortlisted": len(final), "duration_s": duration, "pipeline_version": __version__}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("meta.json → %s", meta_path)
    log.info("\nPipeline complete.  Duration: %ds", duration)
    log.info("Outputs in: %s", run_dir.resolve())
    return run_dir


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="nse-pipeline", description="NSE Insider Trading Weekly Pipeline")
    parser.add_argument("--skip-phase1", action="store_true", help="Skip Phase 1 (scraping) and reuse an existing CSV for today's date")
    parser.add_argument("--date", metavar="YYYY-MM-DD", default=None, help="Override the run date (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Run Phase 1 (scrape) only — no enrichment, no Excel export")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()
    run(skip_phase1=args.skip_phase1, run_date=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
