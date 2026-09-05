"""Promoter transaction history and accumulation metrics.

This module is intentionally independent of the existing stock score.  It
turns the raw NSE Regulation 7 transaction snapshot into an auditable,
transaction-level history and derives freshness/accumulation metrics needed
for the future timing model.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

import pandas as pd

from .config import OUTPUT_ROOT, CSV_FILENAME

PROMOTER_CATEGORIES = {"promoter", "promoter group", "promoter and director"}


def _num(value) -> float:
    """Parse NSE numeric strings containing commas/currency symbols."""
    if pd.isna(value):
        return 0.0
    text = str(value).strip().replace(",", "")
    try:
        return float(re.sub(r"[^0-9.\-]", "", text) or 0)
    except ValueError:
        return 0.0


def _date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def build_promoter_event_history(csv_path: Path) -> pd.DataFrame:
    """Return clean promoter buy/sell transaction events from an NSE snapshot."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()
    required = {
        "Symbol", "Name of Person", "Category of Person", "Type of Instrument",
        "Securities Acquired/Disposed (No.)", "Securities Acquired/Disposed (Value)",
        "Transaction Type", "Date From", "Date To", "Mode of Acquisition/Disposal",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"NSE filing snapshot missing columns: {missing}")

    category = df["Category of Person"].fillna("").str.strip().str.lower()
    instrument = df["Type of Instrument"].fillna("").str.strip().str.lower()
    tx_type = df["Transaction Type"].fillna("").str.strip().str.lower()
    mode = df["Mode of Acquisition/Disposal"].fillna("").str.strip().str.lower()
    promoter = df.loc[category.isin(PROMOTER_CATEGORIES) & instrument.eq("equity")].copy()

    promoter["TransactionDate"] = _date_series(promoter["Date To"])
    promoter["DisclosureDate"] = _date_series(promoter.get("Broadcast Date/Time", promoter["Date To"]))
    promoter["Quantity"] = promoter["Securities Acquired/Disposed (No.)"].map(_num)
    promoter["Value"] = promoter["Securities Acquired/Disposed (Value)"].map(_num)
    promoter["Price"] = promoter["Value"] / promoter["Quantity"].replace(0, pd.NA)
    promoter["BuySell"] = tx_type.map(lambda x: "BUY" if x == "buy" else ("SELL" if x == "sell" else "OTHER"))
    promoter["MarketTransaction"] = mode.map(lambda x: "MARKET_BUY" if x == "market purchase" else ("MARKET_SELL" if x == "market sale" else "OTHER"))

    keep = [
        "Symbol", "Company Name", "Name of Person", "Category of Person", "TransactionDate",
        "DisclosureDate", "Broadcast Date/Time", "Type of Instrument", "Transaction Type",
        "BuySell", "MarketTransaction", "Quantity", "Value", "Price",
        "Securities Held Prior (No.)", "Securities Held Prior (%)", "Securities Held Post (No.)",
        "Securities Held Post (%)", "Date From", "Date To", "Mode of Acquisition/Disposal", "Details URL",
    ]
    return promoter[[c for c in keep if c in promoter.columns]].sort_values(
        ["Symbol", "TransactionDate", "DisclosureDate"], na_position="last"
    ).reset_index(drop=True)


def _window_metrics(events: pd.DataFrame, as_of_date: pd.Timestamp) -> dict:
    buys = events[events["BuySell"].eq("BUY") & events["MarketTransaction"].eq("MARKET_BUY")].copy()
    sells = events[events["BuySell"].eq("SELL") & events["MarketTransaction"].eq("MARKET_SELL")].copy()
    result = {}
    for days in (7, 15, 30, 60, 90):
        start = as_of_date - pd.Timedelta(days=days - 1)
        b = buys[buys["TransactionDate"].between(start, as_of_date)]
        s = sells[sells["TransactionDate"].between(start, as_of_date)]
        result[f"BuyTxn{days}D"] = int(len(b))
        result[f"BuyValue{days}D"] = float(b["Value"].sum())
        result[f"SellTxn{days}D"] = int(len(s))
        result[f"SellValue{days}D"] = float(s["Value"].sum())
        result[f"NetBuyValue{days}D"] = result[f"BuyValue{days}D"] - result[f"SellValue{days}D"]

    if not buys.empty:
        first, last = buys.iloc[0], buys.iloc[-1]
        result.update({
            "FirstBuyDate": first["TransactionDate"], "FirstBuyDisclosureDate": first["DisclosureDate"],
            "FirstBuyPrice": first["Price"], "FirstBuyValue": float(first["Value"]),
            "LastBuyDate": last["TransactionDate"], "LastBuyDisclosureDate": last["DisclosureDate"],
            "LastBuyPrice": last["Price"], "LastBuyValue": float(last["Value"]),
            "AccumulationDays": int((last["TransactionDate"] - first["TransactionDate"]).days),
            "DaysSinceFirstBuy": int((as_of_date - first["TransactionDate"]).days),
            "DaysSinceLastBuy": int((as_of_date - last["TransactionDate"]).days),
            "UniquePromotersBuying": int(buys["Name of Person"].nunique()),
            "UniquePromotersSelling": int(sells["Name of Person"].nunique()),
        })
        priced = buys[(buys["Quantity"] > 0) & (buys["Value"] > 0)]
        result["WeightedAvgBuyPrice"] = float(priced["Value"].sum() / priced["Quantity"].sum()) if not priced.empty else pd.NA
    else:
        result.update({
            "FirstBuyDate": pd.NaT, "FirstBuyDisclosureDate": pd.NaT, "FirstBuyPrice": pd.NA,
            "FirstBuyValue": 0.0, "LastBuyDate": pd.NaT, "LastBuyDisclosureDate": pd.NaT,
            "LastBuyPrice": pd.NA, "LastBuyValue": 0.0, "AccumulationDays": 0,
            "DaysSinceFirstBuy": pd.NA, "DaysSinceLastBuy": pd.NA, "UniquePromotersBuying": 0,
            "UniquePromotersSelling": int(sells["Name of Person"].nunique()), "WeightedAvgBuyPrice": pd.NA,
        })
    result["BuyAcceleration"] = round(result["BuyValue7D"] / max(result["BuyValue30D"], 1e-9), 4)
    return result


def build_accumulation_snapshot(csv_path: Path, as_of_date: str | pd.Timestamp) -> pd.DataFrame:
    """Build one symbol-level accumulation snapshot without changing stock score."""
    as_of = pd.Timestamp(as_of_date).normalize()
    events = build_promoter_event_history(csv_path)
    rows = []
    for symbol, group in events.groupby("Symbol", dropna=False):
        row = {"Symbol": str(symbol).strip().upper()}
        row.update(_window_metrics(group, as_of))
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    for col in ["FirstBuyDate", "FirstBuyDisclosureDate", "LastBuyDate", "LastBuyDisclosureDate"]:
        result[col] = pd.to_datetime(result[col], errors="coerce").dt.strftime("%d-%m-%Y")
    return result


def write_promoter_history(csv_path: Path, out_path: Path, as_of_date: str | pd.Timestamp) -> tuple[int, int]:
    """Write transaction-level history and symbol-level accumulation snapshot."""
    events = build_promoter_event_history(csv_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(out_path, index=False, encoding="utf-8-sig")
    snapshot = build_accumulation_snapshot(csv_path, as_of_date)
    snapshot_path = out_path.with_name("promoter_accumulation.csv")
    snapshot.to_csv(snapshot_path, index=False, encoding="utf-8-sig")
    return len(events), len(snapshot)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build promoter transaction history from an NSE snapshot")
    parser.add_argument("--date", required=True, help="Run date in YYYY-MM-DD format")
    args = parser.parse_args()
    run_dir = Path(OUTPUT_ROOT) / args.date
    csv_path = run_dir / CSV_FILENAME
    out_path = run_dir / "promoter_events.csv"
    if not csv_path.exists():
        raise SystemExit(f"NSE filing snapshot not found: {csv_path}")
    events, symbols = write_promoter_history(csv_path, out_path, args.date)
    print(f"Promoter history: {events} events / {symbols} symbols")


if __name__ == "__main__":
    main()
