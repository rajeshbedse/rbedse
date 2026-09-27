""" 
Phase 2 — Filter, Enrich, Fetch Prices, Holdings, Fundamentals & Score

Applies:
  Filter B  No Pledge Creation / Invocation by Promoter/PG
  Filter C  Promoter market selling <= 25% of promoter market buying
  Filter A  Promoter holding >= MIN_PROMO_HOLDING (from Screener.in)

Prices are fetched from the NSE Bhavcopy daily CSV
(nsearchives.nseindia.com) — a single public HTTP download, no browser,
no cookies, no auth required.  The file covers all equities traded that
day and is downloaded once, then the whole symbol batch is resolved from
the in-memory dict.  EQ, BE, and BZ series are all included so SME-listed
and trade-to-trade symbols are not missed.

Promoter holdings + fundamental data are fetched from Screener.in using
requests + BeautifulSoup — static HTML, no browser required, fully
thread-safe.  Each symbol retries up to HOLDING_RETRY_COUNT times on 429
with exponential backoff (5 s → 10 s → 20 s) before recording None.

Both fetches are parallelised across ThreadPoolExecutor workers.
No Playwright objects are used or passed across thread boundaries.

Scoring model (0–100):
  Promoter Signal   — 25 pts
  Fundamental Signal— 35 pts
  Technical Signal  — 30 pts
  Risk deductions   — up to −10 pts

Category labels:
  🟢 Strong Buy Setup   (≥ 65)
  🟢 Buy on Breakout    (≥ 50)
  🟡 Watchlist           (≥ 40)
  🟠 Fundamental Watch  (≥ 30)
  🔴 Avoid              (< 30)
"""
import csv as _csv
import io
import re
import logging
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .config import (
    MIN_PURCHASE_VALUE, MIN_PROMO_HOLDING, MAX_SELL_BUY_RATIO_PCT,
    PROMOTER_CATEGORIES, PLEDGE_MODES,
    HOLDING_FETCH_DELAY, HOLDING_RETRY_COUNT,
    HOLDING_WORKERS, USER_AGENT,
    TRADES_CSV_FILENAME,
    SCORE_PROMO_BUY, SCORE_PROMO_MULTI_TXN, SCORE_PROMO_CONVICTION,
    SCORE_PROMO_HOLDING_INC, SCORE_PROMO_NO_SELL, SCORE_PROMO_NO_PLEDGE,
    SCORE_FUND_REV_GROWTH, SCORE_FUND_EBITDA_GROWTH, SCORE_FUND_PAT_GROWTH,
    SCORE_FUND_EPS_GROWTH, SCORE_FUND_ROCE, SCORE_FUND_DE_RATIO, SCORE_FUND_OCF_POS,
    SCORE_TECH_ABOVE_REF, SCORE_TECH_ABOVE_50DMA, SCORE_TECH_ABOVE_200DMA,
    SCORE_TECH_DMA_CROSS, SCORE_TECH_VOL_EXPANSION, SCORE_TECH_REL_STRENGTH,
    SCORE_RISK_PLEDGE, SCORE_RISK_MARGIN_FALL, SCORE_RISK_HIGH_PE,
    CATEGORY_STRONG_BUY, CATEGORY_BUY_BREAKOUT, CATEGORY_WATCHLIST, CATEGORY_WEAK_FUND,
)
from .promoter_history import build_accumulation_snapshot

log = logging.getLogger(__name__)

_NSE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_SCREENER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_BHAVCOPY_SERIES = {"EQ", "BE", "BZ"}

from .transaction_utils import deduplicate_transactions


def _v(raw) -> float:
    return float(re.sub(r"[^\d.]", "", str(raw)) or 0)


def _q(raw) -> float:
    return float(re.sub(r"[^\d.]", "", str(raw)) or 0)


def _is_equity_instrument(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().eq("equity")


def _build_aggregates(csv_path: Path) -> tuple[pd.DataFrame, set, set]:
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()
    df, duplicate_rows_removed = deduplicate_transactions(df)
    log.info("Transaction de-duplication: removed %d repeated filing row(s)", duplicate_rows_removed)
    df_promo = df[df["Category of Person"].str.strip().str.lower().isin(PROMOTER_CATEGORIES)].copy()
    df_buys = df_promo[
        _is_equity_instrument(df_promo["Type of Instrument"]) &
        (df_promo["Transaction Type"].str.strip().str.lower() == "buy") &
        (df_promo["Mode of Acquisition/Disposal"].str.strip().str.lower() == "market purchase")
    ].copy()
    df_buys["_value"] = df_buys["Securities Acquired/Disposed (Value)"].apply(_v)
    df_buys["_qty"] = df_buys["Securities Acquired/Disposed (No.)"].apply(_q)
    df_buys["_date"] = pd.to_datetime(df_buys["Date To"].str.strip(), format="%d-%m-%Y", errors="coerce")
    df_buys["_priced"] = (df_buys["_value"] > 0) & (df_buys["_qty"] > 0)
    agg = df_buys.groupby("Symbol").agg(
        CompanyName=("Company Name", "first"), ValuePurchased=("_value", "sum"), ReportedBuyQty=("_qty", "sum"), ReportedBuyTxn=("_value", "count"), acqtoDt=("_date", "max"),
    ).reset_index()
    priced = df_buys[df_buys["_priced"]].groupby("Symbol").agg(TotalQty=("_qty", "sum"), NumBuyTxn=("_value", "count")).reset_index()
    priced_value = df_buys[df_buys["_priced"]].groupby("Symbol")["_value"].sum()
    agg["TotalQty"] = agg["Symbol"].map(priced.set_index("Symbol")["TotalQty"])
    agg["NumBuyTxn"] = agg["Symbol"].map(priced.set_index("Symbol")["NumBuyTxn"]).fillna(0).astype(int)
    agg["PricedValuePurchased"] = agg["Symbol"].map(priced_value).fillna(0.0)
    agg["ValuePurchased"] = agg["PricedValuePurchased"]
    agg["AvgPrice"] = (agg["PricedValuePurchased"] / agg["TotalQty"].replace(0, float("nan"))).round(2)
    agg["MissingValueQty"] = (agg["ReportedBuyQty"] - agg["TotalQty"].fillna(0)).round(4)
    agg["MissingValueTxn"] = (agg["ReportedBuyTxn"] - agg["NumBuyTxn"]).astype(int)
    agg["acqtoDt"] = agg["acqtoDt"].dt.strftime("%d-%m-%Y")
    agg["ValueCr"] = (agg["PricedValuePurchased"] / 1e7).round(2)
    agg = agg[agg["PricedValuePurchased"] >= MIN_PURCHASE_VALUE].sort_values("PricedValuePurchased", ascending=False).reset_index(drop=True)
    log.info("Base symbols with priced buys ≥₹%.0fL: %d", MIN_PURCHASE_VALUE / 1e5, len(agg))
    pledge_syms = set(df_promo[df_promo["Mode of Acquisition/Disposal"].str.strip().str.lower().isin(PLEDGE_MODES)]["Symbol"].str.strip().str.upper())
    df_sells = df_promo[
        _is_equity_instrument(df_promo["Type of Instrument"]) &
        (df_promo["Transaction Type"].str.strip().str.lower() == "sell") &
        (df_promo["Mode of Acquisition/Disposal"].str.strip().str.lower() == "market sale")
    ].copy()
    df_sells["_value"] = df_sells["Securities Acquired/Disposed (Value)"].apply(_v)
    df_sells["_qty"] = df_sells["Securities Acquired/Disposed (No.)"].apply(_q)
    df_sells["_priced"] = (df_sells["_value"] > 0) & (df_sells["_qty"] > 0)
    sell_priced = df_sells[df_sells["_priced"]]
    sell_values = sell_priced.groupby("Symbol")["_value"].sum()
    sell_qty = sell_priced.groupby("Symbol")["_qty"].sum()
    buy_values = agg.set_index("Symbol")["PricedValuePurchased"]
    buy_qty = agg.set_index("Symbol")["TotalQty"].fillna(0.0)
    agg["MarketBuyValue"] = agg["Symbol"].map(buy_values).fillna(0.0)
    agg["MarketSellValue"] = agg["Symbol"].map(sell_values).fillna(0.0)
    agg["GrossSellQty"] = agg["Symbol"].map(sell_qty).fillna(0.0)
    agg["NetBuyQty"] = agg["Symbol"].map(buy_qty).fillna(0.0) - agg["GrossSellQty"]
    agg["NetBuyValue"] = agg["MarketBuyValue"] - agg["MarketSellValue"]
    agg["SellBuyRatioPct"] = (agg["MarketSellValue"] / agg["MarketBuyValue"].replace(0, float("nan")) * 100).round(2)
    agg["HasMarketSell"] = agg["MarketSellValue"] > 0

    # A buy and a sell reported in the same NSE filing can represent a
    # promoter-group transfer rather than fresh group-level accumulation.
    # We expose this as a transfer-like pattern; we do not assert that
    # every same-filing buy/sell is an internal transfer.
    buy_filing_keys = {
        (str(sym).strip().upper(), str(url).strip())
        for sym, url in zip(
            df_buys["Symbol"],
            df_buys["Details URL"].fillna("") if "Details URL" in df_buys.columns else pd.Series("", index=df_buys.index),
        )
        if str(url).strip()
    }
    sell_filing_keys = {
        (str(sym).strip().upper(), str(url).strip())
        for sym, url in zip(
            df_sells["Symbol"],
            df_sells["Details URL"].fillna("") if "Details URL" in df_sells.columns else pd.Series("", index=df_sells.index),
        )
        if str(url).strip()
    }
    transfer_like_symbols = {sym for sym, _url in buy_filing_keys & sell_filing_keys}
    agg["TransferLikeFiling"] = agg["Symbol"].astype(str).str.strip().str.upper().isin(transfer_like_symbols)

    def _flow_status(row):
        buy = float(row.get("MarketBuyValue") or 0)
        sell = float(row.get("MarketSellValue") or 0)
        net = buy - sell
        ratio = float(row.get("SellBuyRatioPct") or 0)
        if buy <= 0 and sell > 0:
            return "Net Selling"
        if net < 0:
            return "Net Selling"
        if sell > 0 and bool(row.get("TransferLikeFiling", False)) and ratio >= 75:
            return "Transfer-like"
        if sell > 0 and ratio >= 50:
            return "Heavy Selling Pressure"
        if sell > 0:
            return "Net Buying with Selling"
        return "Net Buying"

    agg["PromoterFlowStatus"] = agg.apply(_flow_status, axis=1)
    agg["NetBuyValueCr"] = (agg["NetBuyValue"] / 1e7).round(2)
    agg["GrossBuyValueCr"] = (agg["MarketBuyValue"] / 1e7).round(2)
    agg["GrossSellValueCr"] = (agg["MarketSellValue"] / 1e7).round(2)
    agg["SellBuyExclusion"] = agg["SellBuyRatioPct"] > MAX_SELL_BUY_RATIO_PCT
    sell_syms = set(agg.loc[agg["SellBuyExclusion"], "Symbol"].astype(str).str.strip().str.upper())
    return agg, pledge_syms, sell_syms


_BHAVCOPY_BASE = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
_BHAVCOPY_HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}


def _download_bhavcopy(max_lookback: int = 5, as_of_date: date | None = None) -> dict[str, dict[str, float | None]] | None:
    """Download NSE Bhavcopy and resolve closing prices."""
    session = requests.Session()
    session.headers.update(_BHAVCOPY_HEADERS)
    today = as_of_date or date.today()
    attempted: list[str] = []
    for delta in range(max_lookback + 1):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        url = _BHAVCOPY_BASE.format(date=ds)
        attempted.append(ds)
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
                if series not in _BHAVCOPY_SERIES:
                    continue
                sym = row.get("TckrSymb", "").strip()
                if sym in prices and series != "EQ":
                    continue
                try:
                    prices[sym] = {"LastPrice": float(row["ClsPric"])}
                except (ValueError, KeyError):
                    prices[sym] = {"LastPrice": None}
            log.info("CMP prices loaded from NSE closing price for %s — %d symbols", d.strftime("%Y-%m-%d"), len(prices))
            return prices
        except Exception as exc:
            log.warning("Bhavcopy fetch failed for %s: %s", ds, exc)
    log.warning("NSE Bhavcopy: no file found for dates %s", attempted)
    return None


# NOTE: The remainder of this file is unchanged from the current main branch.
# Use GitHub's current main as the source of truth for all helper functions.
