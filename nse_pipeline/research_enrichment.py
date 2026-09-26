"""Build additive research datasets for the RYB research interface.

This module deliberately does not modify the existing scoring model or remove
any existing pipeline output. It creates additional, independently consumable
files beside enriched_full.csv:

- market_price_history.csv      daily OHLCV history for shortlisted symbols
- promoter_activity.csv         promoter/entity level activity summary
- promoter_holding_history.csv transaction-level holding history
- company_classification.csv    NSE macro/sector/industry/basic-industry
- research_manifest.json        data-contract metadata for downstream clients

The datasets are intended to be consumed by the new RYB repository while the
existing rbedse portal continues to consume its current files unchanged.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from .config import USER_AGENT
from .transaction_utils import deduplicate_transactions

log = logging.getLogger(__name__)

_BHAVCOPY_BASE = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
_BHAVCOPY_SERIES = {"EQ", "BE", "BZ"}

_NSE_BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


# ---------------------------------------------------------------------------
# Common parsing helpers
# ---------------------------------------------------------------------------
def _num(value) -> float:
    if pd.isna(value):
        return 0.0
    text = str(value).replace(",", "").strip()
    try:
        return float(re.sub(r"[^0-9.\-]", "", text) or 0)
    except (ValueError, TypeError):
        return 0.0


def _normalise(value) -> str:
    return " ".join(str(value or "").strip().split())


def _promoter_mask(df: pd.DataFrame) -> pd.Series:
    categories = df.get("Category of Person", pd.Series(index=df.index, dtype=str)).fillna("").str.strip().str.lower()
    return categories.isin({"promoter", "promoter group", "promoter and director"})


def _market_buy_mask(df: pd.DataFrame) -> pd.Series:
    return (
        df["Transaction Type"].fillna("").str.strip().str.lower().eq("buy")
        & df["Mode of Acquisition/Disposal"].fillna("").str.strip().str.lower().eq("market purchase")
        & df["Type of Instrument"].fillna("").str.strip().str.lower().eq("equity")
    )


def _market_sell_mask(df: pd.DataFrame) -> pd.Series:
    return (
        df["Transaction Type"].fillna("").str.strip().str.lower().eq("sell")
        & df["Mode of Acquisition/Disposal"].fillna("").str.strip().str.lower().eq("market sale")
        & df["Type of Instrument"].fillna("").str.strip().str.lower().eq("equity")
    )


# ---------------------------------------------------------------------------
# Historical market prices
# ---------------------------------------------------------------------------
def _download_daily_prices(session: requests.Session, trading_date: date) -> list[dict]:
    url = _BHAVCOPY_BASE.format(date=trading_date.strftime("%Y%m%d"))
    try:
        response = session.get(url, timeout=20)
        if response.status_code != 200 or response.content[:2] != b"PK":
            return []
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            raw = archive.read(archive.namelist()[0]).decode("utf-8")
        rows = csv.DictReader(raw.splitlines())
        result = []
        for row in rows:
            if row.get("SctySrs", "").strip() not in _BHAVCOPY_SERIES:
                continue
            symbol = row.get("TckrSymb", "").strip().upper()
            if not symbol:
                continue
            try:
                close = float(row.get("ClsPric", ""))
            except (ValueError, TypeError):
                continue
            def f(key):
                try:
                    return float(row.get(key, ""))
                except (ValueError, TypeError):
                    return None
            result.append({
                "Date": trading_date.isoformat(),
                "Symbol": symbol,
                "Open": f("OpnPric"),
                "High": f("HghPric"),
                "Low": f("LwPric"),
                "Close": close,
                "Volume": f("TtlTradgVol"),
                "TurnoverCr": (f("TtlTrdVal") / 1e7) if f("TtlTrdVal") is not None else None,
            })
        return result
    except Exception as exc:
        log.debug("Historical Bhavcopy failed for %s: %s", trading_date, exc)
        return []


def build_market_price_history(
    symbols: list[str],
    as_of_date: date,
    out_path: Path,
    lookback_days: int = 380,
) -> int:
    """Persist daily price history for symbols over the requested lookback."""
    wanted = {str(s).strip().upper() for s in symbols if str(s).strip()}
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
    })
    rows: list[dict] = []
    attempted = 0
    loaded = 0
    # Reuse the same archive source already used by the existing analyzer.
    for delta in range(max(1, lookback_days)):
        d = as_of_date - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        attempted += 1
        daily = _download_daily_prices(session, d)
        if not daily:
            continue
        loaded += 1
        rows.extend(r for r in daily if r["Symbol"] in wanted)
        # A short pause avoids hammering NSE when a long history is requested.
        time.sleep(0.03)
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.drop_duplicates(["Date", "Symbol"], keep="last").sort_values(["Symbol", "Date"])
    else:
        result = pd.DataFrame(columns=["Date", "Symbol", "Open", "High", "Low", "Close", "Volume", "TurnoverCr"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    log.info("Research price history → %s (%d rows, %d/%d trading files)", out_path, len(result), loaded, attempted)
    return len(result)


# ---------------------------------------------------------------------------
# Promoter holding history and entity-level activity
# ---------------------------------------------------------------------------
def _prepare_events(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()
    df, _ = deduplicate_transactions(df)
    df = df[_promoter_mask(df)].copy()
    df["TransactionDate"] = pd.to_datetime(df["Date To"], errors="coerce", dayfirst=True)
    df["Quantity"] = df["Securities Acquired/Disposed (No.)"].map(_num)
    df["Value"] = df["Securities Acquired/Disposed (Value)"].map(_num)
    df["Price"] = df["Value"] / df["Quantity"].replace(0, pd.NA)
    df["Transaction"] = "OTHER"
    df.loc[_market_buy_mask(df), "Transaction"] = "BUY"
    df.loc[_market_sell_mask(df), "Transaction"] = "SELL"
    df["Person"] = df["Name of Person"].map(_normalise)
    return df


def build_promoter_activity(events: pd.DataFrame, symbols: list[str], as_of_date: date, out_path: Path) -> int:
    wanted = {str(s).strip().upper() for s in symbols}
    events = events[events["Symbol"].astype(str).str.upper().isin(wanted)].copy()
    rows: list[dict] = []
    for symbol, group in events.groupby(events["Symbol"].astype(str).str.upper()):
        for person, entity in group.groupby("Person", dropna=False):
            buys = entity[entity["Transaction"].eq("BUY")]
            sells = entity[entity["Transaction"].eq("SELL")]
            for days in (7, 30, 90):
                start = pd.Timestamp(as_of_date) - pd.Timedelta(days=days - 1)
                b = buys[buys["TransactionDate"].between(start, pd.Timestamp(as_of_date))]
                s = sells[sells["TransactionDate"].between(start, pd.Timestamp(as_of_date))]
                rows.append({
                    "Symbol": symbol,
                    "PromoterEntity": person,
                    "WindowDays": days,
                    "BuyTransactions": int(len(b)),
                    "BuyValue": float(b["Value"].sum()),
                    "SellTransactions": int(len(s)),
                    "SellValue": float(s["Value"].sum()),
                    "NetBuyValue": float(b["Value"].sum() - s["Value"].sum()),
                    "FirstTransactionDate": entity["TransactionDate"].min().strftime("%d-%m-%Y") if entity["TransactionDate"].notna().any() else "",
                    "LastTransactionDate": entity["TransactionDate"].max().strftime("%d-%m-%Y") if entity["TransactionDate"].notna().any() else "",
                })
    result = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(result)


def build_promoter_holding_history(events: pd.DataFrame, symbols: list[str], out_path: Path) -> int:
    wanted = {str(s).strip().upper() for s in symbols}
    events = events[events["Symbol"].astype(str).str.upper().isin(wanted)].copy()
    columns = [
        "Symbol", "Company Name", "Name of Person", "Category of Person",
        "TransactionDate", "Transaction", "Quantity", "Value", "Price",
        "Securities Held Prior (No.)", "Securities Held Prior (%)",
        "Securities Held Post (No.)", "Securities Held Post (%)", "Date From", "Date To",
        "Mode of Acquisition/Disposal", "Broadcast Date/Time", "Details URL",
    ]
    result = events[[c for c in columns if c in events.columns]].copy()
    result = result.sort_values(["Symbol", "TransactionDate", "Name of Person"], na_position="last")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(result)


def build_promoter_cost_series(events: pd.DataFrame, price_path: Path, out_path: Path) -> int:
    """Create a daily promoter weighted-average cost basis series.

    The raw NSE snapshot contains only the available disclosure window. The
    series therefore represents the weighted cost of disclosed market buys up
    to each day in that window; it is not presented as a full historical
    ownership cost basis beyond the available filings.
    """
    prices = pd.read_csv(price_path, encoding="utf-8-sig") if price_path.exists() else pd.DataFrame()
    if prices.empty:
        pd.DataFrame(columns=["Date", "Symbol", "PromoterWeightedAvgBuyPrice"]).to_csv(out_path, index=False, encoding="utf-8-sig")
        return 0
    buys = events[events["Transaction"].eq("BUY")].copy()
    buys["Date"] = buys["TransactionDate"].dt.normalize()
    buys["CostValue"] = buys["Value"]
    buys["CostQty"] = buys["Quantity"]
    rows = []
    for symbol, p in prices.groupby("Symbol"):
        b = buys[buys["Symbol"].astype(str).str.upper().eq(str(symbol).upper())].sort_values("Date")
        cumulative_value = 0.0
        cumulative_qty = 0.0
        by_date = defaultdict(list)
        for _, r in b.iterrows():
            if pd.notna(r["Date"]):
                by_date[pd.Timestamp(r["Date"]).date()].append(r)
        for _, pr in p.sort_values("Date").iterrows():
            d = pd.Timestamp(pr["Date"]).date()
            for r in by_date.get(d, []):
                cumulative_value += float(r["CostValue"] or 0)
                cumulative_qty += float(r["CostQty"] or 0)
            rows.append({
                "Date": d.isoformat(),
                "Symbol": str(symbol).upper(),
                "PromoterWeightedAvgBuyPrice": round(cumulative_value / cumulative_qty, 4) if cumulative_qty > 0 else None,
            })
    result = pd.DataFrame(rows)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(result)


# ---------------------------------------------------------------------------
# NSE classification
# ---------------------------------------------------------------------------
def _nse_quote_classification(session: requests.Session, symbol: str) -> dict:
    """Fetch NSE's four-level industry classification for one symbol."""
    encoded = requests.utils.quote(symbol, safe="")
    # Opening the public equity quote page first establishes NSE cookies before
    # the JSON endpoint. This is the same session pattern used by NSE clients.
    try:
        session.get(f"https://www.nseindia.com/get-quotes/equity?symbol={encoded}", timeout=15)
        response = session.get(
            f"https://www.nseindia.com/api/quote-equity?symbol={encoded}",
            timeout=15,
        )
        if response.status_code != 200:
            return {}
        payload = response.json()
        info = payload.get("industryInfo") or {}
        return {
            "MacroEconomicSector": info.get("macro"),
            "Sector": info.get("sector"),
            "Industry": info.get("industry"),
            "BasicIndustry": info.get("basicIndustry"),
        }
    except Exception as exc:
        log.warning("NSE classification failed for %s: %s", symbol, exc)
        return {}


def build_company_classification(symbols: list[str], out_path: Path) -> int:
    session = requests.Session()
    session.headers.update(_NSE_BASE_HEADERS)
    rows = []
    for symbol in symbols:
        data = _nse_quote_classification(session, str(symbol).strip().upper())
        rows.append({"Symbol": str(symbol).strip().upper(), **data})
        time.sleep(0.15)
    result = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(result)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_research_datasets(
    csv_path: Path,
    full_csv_path: Path,
    out_dir: Path,
    as_of_date: date,
    price_lookback_days: int = 380,
) -> dict:
    """Build all additive datasets and return a compact manifest."""
    enriched = pd.read_csv(full_csv_path, encoding="utf-8-sig")
    symbols = enriched.get("Symbol", pd.Series(dtype=str)).dropna().astype(str).str.upper().drop_duplicates().tolist()
    events = _prepare_events(csv_path)

    price_path = out_dir / "market_price_history.csv"
    cost_path = out_dir / "promoter_cost_history.csv"
    activity_path = out_dir / "promoter_activity.csv"
    holding_path = out_dir / "promoter_holding_history.csv"
    classification_path = out_dir / "company_classification.csv"

    counts = {
        "symbols": len(symbols),
        "price_history_rows": build_market_price_history(symbols, as_of_date, price_path, price_lookback_days),
        "promoter_activity_rows": build_promoter_activity(events, symbols, as_of_date, activity_path),
        "promoter_holding_history_rows": build_promoter_holding_history(events, symbols, holding_path),
        "company_classification_rows": build_company_classification(symbols, classification_path),
    }
    counts["promoter_cost_history_rows"] = build_promoter_cost_series(events, price_path, cost_path)

    manifest = {
        "schema_version": "1.0",
        "run_date": as_of_date.isoformat(),
        "source": "RYB Daily NSE Scan",
        "disclosure_history_note": "Promoter event-derived datasets cover the filing snapshot available to the daily scan; cost/holding history must not be interpreted as complete ownership history outside that window.",
        "files": {
            "enriched_full": full_csv_path.name,
            "market_price_history": price_path.name,
            "promoter_cost_history": cost_path.name,
            "promoter_activity": activity_path.name,
            "promoter_holding_history": holding_path.name,
            "company_classification": classification_path.name,
        },
        "counts": counts,
    }
    (out_dir / "research_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Research datasets complete: %s", json.dumps(counts, sort_keys=True))
    return manifest
