"""Canonical promoter activity windows for RYB."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import pandas as pd

WINDOWS = (7, 15, 30, 60, 90)


def _num(value) -> float:
    if pd.isna(value):
        return 0.0
    text = str(value).replace(",", "").strip()
    try:
        return float("".join(ch for ch in text if ch.isdigit() or ch in ".-"))
    except (TypeError, ValueError):
        return 0.0


def _prepare_events(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()
    categories = df.get("Category of Person", pd.Series(index=df.index, dtype=str)).fillna("").astype(str).str.strip().str.lower()
    df = df[categories.isin({"promoter", "promoter group", "promoter and director"})].copy()
    df["TransactionDate"] = pd.to_datetime(df["Date To"], errors="coerce", dayfirst=True)
    df["Value"] = df["Securities Acquired/Disposed (Value)"].map(_num)
    transaction_type = df["Transaction Type"].fillna("").astype(str).str.strip().str.lower()
    mode = df["Mode of Acquisition/Disposal"].fillna("").astype(str).str.strip().str.lower()
    instrument = df["Type of Instrument"].fillna("").astype(str).str.strip().str.lower()
    df["Transaction"] = "OTHER"
    df.loc[transaction_type.eq("buy") & mode.eq("market purchase") & instrument.eq("equity"), "Transaction"] = "BUY"
    df.loc[transaction_type.eq("sell") & mode.eq("market sale") & instrument.eq("equity"), "Transaction"] = "SELL"
    df["Person"] = df["Name of Person"].fillna("").astype(str).str.strip()
    return df


def rebuild_promoter_activity_windows(csv_path: Path, symbols: list[str], as_of_date: date, out_path: Path) -> int:
    """Write promoter/entity activity for 7D, 15D, 30D, 60D and 90D."""
    wanted = {str(s).strip().upper() for s in symbols if str(s).strip()}
    events = _prepare_events(csv_path)
    events = events[events["Symbol"].astype(str).str.upper().isin(wanted)].copy()
    rows: list[dict] = []
    as_of = pd.Timestamp(as_of_date)
    for symbol, group in events.groupby(events["Symbol"].astype(str).str.upper()):
        for person, entity in group.groupby("Person", dropna=False):
            buys = entity[entity["Transaction"].eq("BUY")]
            sells = entity[entity["Transaction"].eq("SELL")]
            for days in WINDOWS:
                start = as_of - pd.Timedelta(days=days - 1)
                b = buys[buys["TransactionDate"].between(start, as_of)]
                s = sells[sells["TransactionDate"].between(start, as_of)]
                buy_value = float(b["Value"].sum())
                sell_value = float(s["Value"].sum())
                rows.append({
                    "Symbol": symbol, "PromoterEntity": person, "WindowDays": days,
                    "BuyTransactions": int(len(b)), "BuyValue": buy_value,
                    "SellTransactions": int(len(s)), "SellValue": sell_value,
                    "NetBuyValue": buy_value - sell_value,
                    "FirstTransactionDate": entity["TransactionDate"].min().strftime("%d-%m-%Y") if entity["TransactionDate"].notna().any() else "",
                    "LastTransactionDate": entity["TransactionDate"].max().strftime("%d-%m-%Y") if entity["TransactionDate"].notna().any() else "",
                })
    columns = ["Symbol", "PromoterEntity", "WindowDays", "BuyTransactions", "BuyValue", "SellTransactions", "SellValue", "NetBuyValue", "FirstTransactionDate", "LastTransactionDate"]
    pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(rows)
