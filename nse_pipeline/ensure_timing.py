"""Ensure promoter timing fields are present in the published DEV snapshot.

This is a defensive output-contract step. The analyzer is expected to enrich
``enriched_full.csv`` with timing fields already; this module re-applies the
same enrichment before publication so a stale/partial output can never reach
the DEV portal without the timing columns.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import reporter
from .analyzer import _apply_timing_metrics
from .config import EXCEL_FILENAME, FULL_CSV_FILENAME, MIN_PROMO_HOLDING, CSV_FILENAME

TIMING_COLUMNS = {
    "PromoterAvgPrice",
    "CMPvsPromoterAvgPct",
    "Freshness",
    "AccumulationStage",
    "SignalStage",
    "FirstBuyDate",
    "LastBuyDate",
    "AccumulationDays",
    "DaysSinceLastBuy",
    "BuyTxn30D",
}


def repair(run_dir: Path, run_date: str) -> None:
    raw_path = run_dir / CSV_FILENAME
    full_path = run_dir / FULL_CSV_FILENAME
    excel_path = run_dir / EXCEL_FILENAME

    raw = pd.read_csv(raw_path, encoding="utf-8-sig")
    full = pd.read_csv(full_path, encoding="utf-8-sig")

    repaired = _apply_timing_metrics(
        full,
        raw_path,
        datetime.strptime(run_date, "%Y-%m-%d").date(),
    )
    missing = sorted(TIMING_COLUMNS - set(repaired.columns))
    if missing:
        raise RuntimeError(
            "Timing enrichment failed; missing columns: " + ", ".join(missing)
        )

    repaired.to_csv(full_path, index=False, encoding="utf-8-sig")

    # Rebuild the Excel report from the repaired enriched dataset so both
    # portal data sources carry the same timing fields.
    valid = repaired.dropna(subset=["LastPrice", "PromoHolding"])
    final = (
        valid[valid["PromoHolding"] >= MIN_PROMO_HOLDING]
        .sort_values("Score", ascending=False)
        .reset_index(drop=True)
    )
    reporter.run(final, excel_path)

    # Require at least one populated timing signal when the raw snapshot has
    # qualifying promoter buys. This prevents a silent all-No-Signal output.
    populated = repaired["Freshness"].fillna("No Signal").ne("No Signal").sum()
    if populated == 0:
        raise RuntimeError(
            "Timing output contains no populated Freshness values despite a non-empty raw snapshot"
        )

    print(
        f"Timing output verified: {populated} enriched rows; "
        f"{len(final)} shortlist rows; {len(raw)} raw filings."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure timing fields are present in a generated snapshot")
    parser.add_argument("--date", required=True, metavar="YYYY-MM-DD")
    args = parser.parse_args()
    repair(Path("output") / args.date, args.date)


if __name__ == "__main__":
    main()
