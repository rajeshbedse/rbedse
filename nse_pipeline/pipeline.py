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

# Resolve output root relative to the repo root (parent of this package),
# regardless of which directory the user runs the exe from.
_REPO_ROOT   = Path(__file__).parent.parent
_OUTPUT_ROOT = _REPO_ROOT / OUTPUT_ROOT


def _download_close_bhavcopy(max_lookback: int = 5, as_of_date=None):
    """
    Download the most recent NSE Bhavcopy and return official closing prices.

    CMP in the report must be based on the NSE closing price (ClsPric), not
    the last traded price (LastPric). DMA calculations already use ClsPric.
    This function mirrors analyzer._download_bhavcopy but deliberately reads
    ClsPric so CMP and the technical indicators use the same price basis.

    The return shape intentionally matches analyzer._download_bhavcopy:
    {symbol: {"LastPrice": float}}.  analyzer._fetch_prices() consumes that
    shape, so the pipeline override must not return the legacy {symbol: float}
    form.
    """
    base = (
        "https://nsearchives.nseindia.com/content/cm/"
        "BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
    }
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
        url = base.format(date=ds)
        try:
            resp = session.get(url, timeout=20)
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
                    pass
            logging.getLogger(__name__).info(
                "  CMP prices loaded from NSE closing price for %s — %d symbols",
                d.strftime("%Y-%m-%d"), len(prices),
            )
            return prices
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "  NSE closing-price fetch failed for %s: %s", ds, exc
            )

    logging.getLogger(__name__).warning(
        "  NSE closing-price Bhavcopy: no file found for dates %s", attempted
    )
    return None


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


def run(skip_phase1: bool = False, run_date: str | None = None, dry_run: bool = False) -> Path:
    """
    Execute the full pipeline.

    Parameters
    ----------
    skip_phase1 : bool
        If True and the CSV for *run_date* already exists, skip Phase 1.
    run_date : str | None
        Date string YYYY-MM-DD to use for the output folder.
        Defaults to today.
    dry_run : bool
        If True, only run Phase 1 (scrape) and stop. No price/holding
        fetches, no Excel export. Useful for verifying connectivity.

    Returns
    -------
    Path
        The run output directory.
    """
    date_str = run_date or datetime.now().strftime("%Y-%m-%d")
    run_dir  = _OUTPUT_ROOT / date_str

    # Always create the date-specific output directory before
    # any scraper, logger, or metadata operation writes into it.
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_path    = run_dir / CSV_FILENAME
    excel_path  = run_dir / EXCEL_FILENAME
    full_csv    = run_dir / FULL_CSV_FILENAME
    log_path    = run_dir / LOG_FILENAME
    meta_path   = run_dir / "meta.json"
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

    # Phase 1 — scrape
    # headless=False is required: NSE blocks headless Chromium with
    # ERR_HTTP2_PROTOCOL_ERROR / timeouts during navigation.
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
                raw_count = 0
        else:
            raw_count = scraper.run(ctx, csv_path)

        browser.close()

    if dry_run:
        log.info("\nDry run complete. CSV written to: %s", csv_path.resolve())
        log.info("Re-run without --dry-run to proceed with enrichment and export.")
        return run_dir

    # No NSE filings means the market/data source had no usable data
    # for this run date (weekend, NSE holiday, or temporary no-data response).
    # Do not attempt enrichment/report generation and do not publish.
    if raw_count == 0:
        duration = round(time.monotonic() - pipeline_start)

        meta = {
            "run_date": date_str,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "no_data",
            "filing_period": NSE_FILING_PERIOD,
            "raw_filings": 0,
            "failed_urls": 0,
            "candidates": 0,
            "shortlisted": 0,
            "duration_s": duration,
            "pipeline_version": __version__,
        }

        meta_path.write_text(
            json.dumps(meta, indent=2),
            encoding="utf-8",
        )

        log.info("No NSE filings found for %s. Skipping enrichment.", date_str)
        log.info("meta.json → %s", meta_path)

        return run_dir

    # Phase 2 — analyse
    # CMP must use official NSE closing price (ClsPric), while DMA already
    # uses ClsPric. Override the analyzer's price download for this pipeline
    # run so CMP and technical calculations share the same price basis.
    analyzer._download_bhavcopy = _download_close_bhavcopy
    as_of = datetime.strptime(date_str, "%Y-%m-%d").date()
    final = analyzer.run(csv_path, full_csv, as_of_date=as_of)

    # Phase 3 — report + export
    reporter.run(final, excel_path)

    duration = round(time.monotonic() - pipeline_start)

    # ── meta.json — structured summary used by the portal dashboard ──────────
    candidates = 0
    try:
        candidates = len(pd.read_csv(full_csv, encoding="utf-8-sig"))
    except Exception:
        pass

    failed_path = run_dir / "failed_urls.txt"
    failed_urls = 0
    if failed_path.exists():
        try:
            failed_urls = max(0, len(failed_path.read_text(encoding="utf-8").splitlines()) - 1)
        except Exception:
            failed_urls = 0

    meta = {
        "run_date"      : date_str,
        "generated_at"  : datetime.now(timezone.utc).isoformat(),
        "status"        : "success",
        "filing_period" : NSE_FILING_PERIOD,
        "raw_filings"   : raw_count,
        "failed_urls"   : failed_urls,
        "candidates"    : candidates,
        "shortlisted"   : len(final),
        "duration_s"    : duration,
        "pipeline_version": __version__,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("meta.json → %s", meta_path)

    log.info("\nPipeline complete.  Duration: %ds", duration)
    log.info("Outputs in: %s", run_dir.resolve())
    return run_dir


def main() -> None:
    """CLI entry point: nse-pipeline"""
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="nse-pipeline",
        description="NSE Insider Trading Weekly Pipeline",
    )
    parser.add_argument(
        "--skip-phase1", action="store_true",
        help="Skip Phase 1 (scraping) and reuse an existing CSV for today's date",
    )
    parser.add_argument(
        "--date", metavar="YYYY-MM-DD", default=None,
        help="Override the run date (default: today)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run Phase 1 (scrape) only — no enrichment, no Excel export",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args()
    run(skip_phase1=args.skip_phase1, run_date=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
