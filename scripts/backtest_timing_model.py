"""Backtest the proposed 30D-current / prior-60D promoter timing model.

This is a SHADOW analysis only. It does not modify the production score.

For every historical scan snapshot it derives:
  * current promoter behaviour: last 30 calendar days
  * prior promoter behaviour: days -90 through -31
  * current-vs-prior buying change
  * price change since the first promoter buy visible in the snapshot
  * forward returns using later scan snapshots for the same symbol

The repository currently contains a relatively short history, so the output
is deliberately framed as diagnostic evidence rather than a weight-fitting
engine. As daily snapshots accumulate, the same workflow can be rerun.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


OUTPUT_ROOT = Path("output")
DEFAULT_HORIZONS = (5, 10, 20)


NUMERIC_COLUMNS = [
    "LastPrice",
    "FirstBuyPrice",
    "WeightedAvgBuyPrice",
    "MarketCapCr",
    "BuyTxn30D",
    "BuyTxn90D",
    "BuyValue30D",
    "BuyValue90D",
    "SellValue30D",
    "SellValue90D",
    "NetBuyValue30D",
    "NetBuyValue90D",
    "UniquePromotersBuying",
    "UniquePromotersSelling",
    "DaysSinceLastBuy",
    "CMPvsPromoterAvgPct",
    "ScorePromo",
    "ScoreFund",
    "ScoreTech",
    "ScoreRisk",
    "Score",
]


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def load_scan_history(output_root: Path) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for run_dir in sorted(output_root.glob("20??-??-??")):
        path = run_dir / "enriched_full.csv"
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig")
        except Exception as exc:
            print(f"Skipping {path}: {exc}")
            continue
        if "Symbol" not in frame.columns or "LastPrice" not in frame.columns:
            continue
        frame["ScanDate"] = pd.Timestamp(run_dir.name)
        frame["Symbol"] = frame["Symbol"].astype(str).str.strip().str.upper()
        for col in NUMERIC_COLUMNS:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        rows.append(frame)

    if not rows:
        raise SystemExit("No output/YYYY-MM-DD/enriched_full.csv files found")

    history = pd.concat(rows, ignore_index=True, sort=False)
    history = history.drop_duplicates(["ScanDate", "Symbol"], keep="last")
    return history.sort_values(["Symbol", "ScanDate"]).reset_index(drop=True)


def derive_features(history: pd.DataFrame) -> pd.DataFrame:
    df = history.copy()

    buy30 = _num(df, "BuyValue30D")
    buy90 = _num(df, "BuyValue90D")
    sell30 = _num(df, "SellValue30D")
    sell90 = _num(df, "SellValue90D")
    net30 = _num(df, "NetBuyValue30D")
    net90 = _num(df, "NetBuyValue90D")

    # 30D = current decision window; 90D - 30D = the preceding 60D context.
    df["Current30BuyCr"] = buy30 / 1e7
    df["Current30SellCr"] = sell30 / 1e7
    df["Current30NetBuyCr"] = net30 / 1e7
    df["Prior60BuyCr"] = (buy90 - buy30) / 1e7
    df["Prior60SellCr"] = (sell90 - sell30) / 1e7
    df["Prior60NetBuyCr"] = (net90 - net30) / 1e7
    df["Current30BuyTxn"] = _num(df, "BuyTxn30D")
    df["Prior60BuyTxn"] = (_num(df, "BuyTxn90D") - _num(df, "BuyTxn30D")).clip(lower=0)

    # Keep these calculations as ordinary float Series. Using pd.NA here
    # creates pandas' nullable object dtype, for which Series.round() can
    # raise TypeError under current pandas versions.
    market_cap = _num(df, "MarketCapCr")
    safe_market_cap = market_cap.where(market_cap != 0)
    df["Current30BuyPctMcap"] = (df["Current30BuyCr"] / safe_market_cap * 100).round(4)
    df["Prior60BuyPctMcap"] = (df["Prior60BuyCr"] / safe_market_cap * 100).round(4)

    # A positive value means promoter buying is stronger in the current 30D
    # window than in the preceding 60D. This is deliberately not a score.
    prior = df["Prior60NetBuyCr"]
    safe_prior = prior.where(prior > 0)
    df["CurrentVsPriorNetBuyRatio"] = (
        df["Current30NetBuyCr"] / safe_prior
    ).replace([float("inf"), -float("inf")], float("nan")).round(3)
    df["CurrentVsPriorNetBuyDeltaCr"] = (
        df["Current30NetBuyCr"] - df["Prior60NetBuyCr"]
    ).round(3)

    first_price = _num(df, "FirstBuyPrice")
    last_price = _num(df, "LastPrice")
    safe_first_price = first_price.where(first_price != 0)
    df["PriceSinceFirstBuyPct"] = (
        (last_price / safe_first_price - 1) * 100
    ).round(2)

    first_buy_date = pd.to_datetime(df.get("FirstBuyDate"), errors="coerce", dayfirst=True)
    df["FirstBuyDateParsed"] = first_buy_date
    df["BuyAgeDays"] = (df["ScanDate"] - first_buy_date).dt.days

    return df


def add_forward_returns(df: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    work = df.sort_values(["Symbol", "ScanDate"]).copy()
    grouped = work.groupby("Symbol", group_keys=False)
    for horizon in horizons:
        work[f"ForwardReturn_{horizon}ScanPct"] = (
            grouped["LastPrice"].shift(-horizon) / work["LastPrice"].replace(0, pd.NA) - 1
        ) * 100
        work[f"ForwardDays_{horizon}Scan"] = (
            grouped["ScanDate"].shift(-horizon) - work["ScanDate"]
        ).dt.days
    return work


def _bucket_current30(value: float) -> str:
    if pd.isna(value):
        return "No data"
    if value <= 0:
        return "<= 0 Cr"
    if value <= 5:
        return "0–5 Cr"
    if value <= 25:
        return "5–25 Cr"
    return ">25 Cr"


def _bucket_prior60(value: float) -> str:
    if pd.isna(value):
        return "No data"
    if value <= 0:
        return "<= 0 Cr"
    if value <= 10:
        return "0–10 Cr"
    if value <= 50:
        return "10–50 Cr"
    return ">50 Cr"


def _bucket_price_since_first(value: float) -> str:
    if pd.isna(value):
        return "No data"
    if value < 0:
        return "<0%"
    if value <= 10:
        return "0–10%"
    if value <= 25:
        return "10–25%"
    return ">25%"


def _summary_for(frame: pd.DataFrame, label: str, horizon: int) -> list[dict]:
    col = f"ForwardReturn_{horizon}ScanPct"
    if col not in frame:
        return []
    rows = []
    for bucket, group in frame.dropna(subset=[col]).groupby(label, dropna=False):
        values = group[col]
        rows.append(
            {
                "Horizon": f"{horizon} scans",
                "Dimension": label,
                "Bucket": str(bucket),
                "N": int(values.count()),
                "MeanForwardReturnPct": round(float(values.mean()), 2),
                "MedianForwardReturnPct": round(float(values.median()), 2),
                "WinRatePct": round(float((values > 0).mean() * 100), 1),
                "P25Pct": round(float(values.quantile(0.25)), 2),
                "P75Pct": round(float(values.quantile(0.75)), 2),
            }
        )
    return rows


def build_summary(df: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    work = df.copy()
    work["Current30BuyBucket"] = work["Current30BuyCr"].map(_bucket_current30)
    work["Prior60BuyBucket"] = work["Prior60BuyCr"].map(_bucket_prior60)
    work["PriceSinceFirstBuyBucket"] = work["PriceSinceFirstBuyPct"].map(_bucket_price_since_first)

    rows: list[dict] = []
    dimensions = [
        "Current30BuyBucket",
        "Prior60BuyBucket",
        "PriceSinceFirstBuyBucket",
        "Freshness",
        "AccumulationStage",
    ]
    for horizon in horizons:
        col = f"ForwardReturn_{horizon}ScanPct"
        valid = work.dropna(subset=[col])
        if not valid.empty:
            values = valid[col]
            rows.append(
                {
                    "Horizon": f"{horizon} scans",
                    "Dimension": "ALL",
                    "Bucket": "ALL",
                    "N": int(values.count()),
                    "MeanForwardReturnPct": round(float(values.mean()), 2),
                    "MedianForwardReturnPct": round(float(values.median()), 2),
                    "WinRatePct": round(float((values > 0).mean() * 100), 1),
                    "P25Pct": round(float(values.quantile(0.25)), 2),
                    "P75Pct": round(float(values.quantile(0.75)), 2),
                }
            )
        for dimension in dimensions:
            rows.extend(_summary_for(work, dimension, horizon))
    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, summary: pd.DataFrame, out_dir: Path, horizons: tuple[int, ...]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    observations_path = out_dir / "timing_backtest_observations.csv"
    summary_path = out_dir / "timing_backtest_summary.csv"
    report_path = out_dir / "timing_backtest.md"
    df.to_csv(observations_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    dates = df["ScanDate"].dropna()
    valid_forward = [c for c in df.columns if c.startswith("ForwardReturn_")]
    lines = [
        "# RYB promoter timing shadow backtest",
        "",
        f"Scan history: **{dates.min().date() if not dates.empty else 'N/A'} → {dates.max().date() if not dates.empty else 'N/A'}**",
        f"Observations: **{len(df):,} symbol-scan rows** across **{df['ScanDate'].nunique()} scan dates**.",
        "",
        "## Model windows",
        "",
        "- **Current 30D:** the last 30 calendar days available at each scan date; used as the decision window.",
        "- **Prior 60D:** 90D cumulative minus 30D cumulative; represents days -90 through -31 and is context only.",
        "- **Price since first buy:** current scan price versus the first promoter buy price visible in the NSE snapshot.",
        "- **Forward returns:** measured only from later scan snapshots for the same symbol; no future data is used in the feature columns.",
        "",
        "## Important limitation",
        "",
        "The repository currently contains a short historical scan window. Therefore this report is a diagnostic backtest, not sufficient evidence for locking production weights. In particular, 60/120-calendar-day forward outcomes require more historical snapshots.",
        "",
        "## Forward-return coverage",
        "",
    ]
    for col in valid_forward:
        n = int(df[col].notna().sum())
        lines.append(f"- `{col}`: {n:,} observations")
    lines += [
        "",
        "## Weighting rule",
        "",
        "Do **not** change production weights from this report alone. The intended next step is to accumulate a materially longer history and then calibrate weights against forward median return, win rate, and downside/drawdown, with a time-based out-of-sample validation period.",
        "",
        "## Raw outputs",
        "",
        f"- `{observations_path.name}` — every symbol/date feature and forward-return observation.",
        f"- `{summary_path.name}` — bucketed performance summary.",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--out-dir", type=Path, default=Path("output/backtest/timing"))
    parser.add_argument("--horizons", default=",".join(map(str, DEFAULT_HORIZONS)))
    args = parser.parse_args()
    horizons = tuple(int(x.strip()) for x in args.horizons.split(",") if x.strip())
    if not horizons:
        raise SystemExit("At least one horizon is required")

    history = load_scan_history(args.output_root)
    features = derive_features(history)
    backtest = add_forward_returns(features, horizons)
    summary = build_summary(backtest, horizons)
    write_report(backtest, summary, args.out_dir, horizons)

    print(f"Loaded {len(backtest):,} symbol-scan observations across {backtest['ScanDate'].nunique()} dates")
    for horizon in horizons:
        col = f"ForwardReturn_{horizon}ScanPct"
        print(f"{col}: {int(backtest[col].notna().sum()):,} observations")
    print(f"Report written to {args.out_dir}")


if __name__ == "__main__":
    main()
