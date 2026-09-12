"""Validate one generated daily NSE pipeline snapshot before publication."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .config import (
    CSV_FILENAME,
    EXCEL_FILENAME,
    FULL_CSV_FILENAME,
    TRADES_CSV_FILENAME,
)


REQUIRED_FILES = [
    CSV_FILENAME,
    FULL_CSV_FILENAME,
    EXCEL_FILENAME,
    TRADES_CSV_FILENAME,
    "meta.json",
    "run_log.txt",
]

RAW_REQUIRED_COLUMNS = {
    "Symbol",
    "Transaction Type",
    "Mode of Acquisition/Disposal",
}

FULL_REQUIRED_COLUMNS = {
    "Symbol",
    "CompanyName",
    "LastPrice",
    "52WeekHigh",
    "52WeekLow",
    "AvgPrice",
    "PriceDiffPct",
    "PromoHolding",
    "ValueCr",
    "NumBuyTxn",
    "acqtoDt",
    "Score",
    "Category",
}

TIMING_REQUIRED_COLUMNS = {
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


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def validate(run_dir: Path) -> list[str]:
    """Validate one daily NSE pipeline output directory."""

    errors: list[str] = []
    warnings: list[str] = []

    if not run_dir.is_dir():
        return [f"Output directory does not exist: {run_dir}"]

    missing = [
        name
        for name in REQUIRED_FILES
        if not (run_dir / name).is_file()
    ]

    if missing:
        errors.append(
            "Missing required files: " + ", ".join(missing)
        )

    meta_path = run_dir / "meta.json"
    meta: dict = {}

    if meta_path.is_file():
        try:
            meta = json.loads(
                meta_path.read_text(encoding="utf-8-sig")
            )
        except Exception as exc:
            errors.append(f"Invalid meta.json: {exc}")

    status = meta.get("status")

    if status is None:
        warnings.append(
            "meta.json has no status field; treating as legacy snapshot"
        )
    elif status == "no_data":
        print("NO DATA: NSE returned no filings for this run date.")
        return []
    elif status != "success":
        errors.append(
            f"meta.json status is not success: {status!r}"
        )

    raw_path = run_dir / CSV_FILENAME
    full_path = run_dir / FULL_CSV_FILENAME
    trades_path = run_dir / TRADES_CSV_FILENAME
    excel_path = run_dir / EXCEL_FILENAME

    raw = None
    full = None
    trades = None

    if raw_path.is_file():
        try:
            raw = _read_csv(raw_path)

            missing_cols = RAW_REQUIRED_COLUMNS - set(raw.columns)

            if missing_cols:
                errors.append(
                    "Raw CSV missing columns: "
                    + ", ".join(sorted(missing_cols))
                )

            if raw.empty:
                errors.append(
                    "Raw insider-trading CSV contains zero rows"
                )

        except Exception as exc:
            errors.append(f"Cannot read raw CSV: {exc}")

    if full_path.is_file():
        try:
            full = _read_csv(full_path)

            missing_cols = FULL_REQUIRED_COLUMNS - set(full.columns)

            if missing_cols:
                errors.append(
                    "Enriched CSV missing columns: "
                    + ", ".join(sorted(missing_cols))
                )

            missing_timing = TIMING_REQUIRED_COLUMNS - set(full.columns)
            if missing_timing:
                errors.append(
                    "Enriched CSV missing promoter timing columns: "
                    + ", ".join(sorted(missing_timing))
                )
            elif not full.empty:
                freshness = full["Freshness"].fillna("No Signal").astype(str)
                if not freshness.ne("No Signal").any():
                    errors.append(
                        "Enriched CSV contains no populated promoter timing signals"
                    )

            if full.empty:
                errors.append(
                    "Enriched CSV contains zero candidates"
                )

            if "52WeekHigh" in full.columns and "52WeekLow" in full.columns and not full.empty:
                high = pd.to_numeric(full["52WeekHigh"], errors="coerce")
                low = pd.to_numeric(full["52WeekLow"], errors="coerce")
                high_count = int(high.notna().sum())
                low_count = int(low.notna().sum())
                both_count = int((high.notna() & low.notna()).sum())
                coverage = both_count / len(full) * 100
                print(
                    f"52W validation: {both_count}/{len(full)} rows have both High+Low "
                    f"({coverage:.1f}%) | High populated={high_count} | Low populated={low_count}"
                )
                # 52-week data is supplementary enrichment. NSE can temporarily
                # omit or move the report without invalidating the core scan.
                if both_count == 0:
                    warnings.append(
                        "NSE 52-week High/Low data is unavailable for this run; "
                        "continuing publication without it"
                    )
                elif coverage < 95:
                    warnings.append(
                        f"NSE 52-week High/Low coverage is only {coverage:.1f}% "
                        "of enriched rows"
                    )
                invalid_range = (high.notna() & low.notna() & ((high <= 0) | (low <= 0) | (high < low))).sum()
                if int(invalid_range) > 0:
                    errors.append(
                        f"NSE 52-week High/Low contains {int(invalid_range)} invalid ranges"
                    )

            if "Score" in full.columns:
                scores = pd.to_numeric(
                    full["Score"],
                    errors="coerce",
                ).dropna()

                if not scores.empty:
                    invalid_scores = (
                        (scores < 0) | (scores > 100)
                    )

                    if invalid_scores.any():
                        errors.append(
                            "Enriched CSV contains an RYB Score "
                            "outside 0-100"
                        )

        except Exception as exc:
            errors.append(f"Cannot read enriched CSV: {exc}")

    if trades_path.is_file():
        try:
            trades = _read_csv(trades_path)

            if trades.empty:
                warnings.append(
                    "promoter_trades.csv is empty"
                )

        except Exception as exc:
            errors.append(
                f"Cannot read promoter trades CSV: {exc}"
            )

    if (
        raw is not None
        and full is not None
        and len(raw) > 0
        and len(full) == 0
    ):
        errors.append(
            "Raw filings exist but enrichment produced "
            "zero candidates"
        )

    if meta:
        try:
            meta_raw = int(meta.get("raw_filings", -1))
            meta_candidates = int(
                meta.get("candidates", -1)
            )
            meta_shortlisted = int(
                meta.get("shortlisted", -1)
            )

            if raw is not None and meta_raw != len(raw):
                warnings.append(
                    f"meta raw_filings={meta_raw}, "
                    f"actual raw rows={len(raw)}"
                )

            if full is not None and meta_candidates != len(full):
                warnings.append(
                    f"meta candidates={meta_candidates}, "
                    f"actual enriched rows={len(full)}"
                )

            if meta_shortlisted < 0:
                errors.append(
                    "meta.json shortlisted count is invalid"
                )

            if meta_shortlisted == 0:
                errors.append(
                    "Shortlist contains zero stocks"
                )

        except (TypeError, ValueError):
            errors.append(
                "meta.json contains invalid numeric counts"
            )

    if excel_path.is_file():
        try:
            sheets = pd.ExcelFile(
                excel_path
            ).sheet_names

            expected = {
                "ScoredStocks",
                "FilteredStocks",
                "Summary",
            }

            missing_sheets = expected - set(sheets)

            if missing_sheets:
                errors.append(
                    "Excel missing sheets: "
                    + ", ".join(sorted(missing_sheets))
                )

        except Exception as exc:
            errors.append(
                f"Cannot open Excel output: {exc}"
            )

    if errors:
        print("VALIDATION FAILED")

        for message in errors:
            print(f"ERROR: {message}")

    else:
        print("VALIDATION PASSED")

    for message in warnings:
        print(f"WARNING: {message}")

    return errors


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description="Validate an NSE pipeline output snapshot"
    )

    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    run_dir = repo_root / "output" / args.date

    errors = validate(run_dir)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
