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
  🟡 Watchlist          (≥ 40)
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
    # scoring weights
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

# Bhavcopy series to include — EQ is main board, BE is trade-to-trade,
# BZ is trade-to-trade (SME).  Including all three avoids N/A prices for
# companies listed on SME exchange or under surveillance measures.
_BHAVCOPY_SERIES = {"EQ", "BE", "BZ"}


_TRANSACTION_CORE_COLUMNS = [
    "Symbol", "Name of Person", "CIN/DIN", "Type of Instrument",
    "Securities Acquired/Disposed (No.)",
    "Securities Acquired/Disposed (Value)", "Transaction Type", "Date From",
    "Date To", "Mode of Acquisition/Disposal",
]


def _normalise_key_value(value) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().upper().split())


def _deduplicate_transactions(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if df.empty:
        return df.copy(), 0
    work = df.copy()
    work.columns = work.columns.str.strip()
    exact_cols = [c for c in ["Details URL", *_TRANSACTION_CORE_COLUMNS,
                              "Securities Held Prior (No.)", "Securities Held Prior (%)",
                              "Securities Held Post (No.)", "Securities Held Post (%)",
                              "Date From", "Date To", "Date of Intimation"] if c in work.columns]
    before = len(work)
    if exact_cols:
        work = work.drop_duplicates(subset=exact_cols, keep="last").copy()
    key_cols = [c for c in _TRANSACTION_CORE_COLUMNS if c in work.columns]
    for col in key_cols:
        work[f"__txn_{col}"] = work[col].map(_normalise_key_value)
    work["__txn_core_key"] = work[[f"__txn_{c}" for c in key_cols]].agg("|".join, axis=1)
    work["__broadcast_dt"] = pd.to_datetime(work.get("Broadcast Date/Time", ""), errors="coerce", dayfirst=True)
    if "Details URL" in work.columns:
        filing_meta = (work[["__txn_core_key", "Details URL", "__broadcast_dt"]]
                       .drop_duplicates()
                       .sort_values(["__txn_core_key", "__broadcast_dt", "Details URL"], na_position="first"))
        latest_filing = (filing_meta.groupby("__txn_core_key", dropna=False, as_index=False)
                         .tail(1)[["__txn_core_key", "Details URL"]])
        work = work.merge(latest_filing.assign(__keep=True), on=["__txn_core_key", "Details URL"], how="inner")
        work = work.drop(columns=["__keep"])
    else:
        latest = work.groupby("__txn_core_key", dropna=False)["__broadcast_dt"].transform("max")
        work = work[work["__broadcast_dt"].eq(latest) | work["__broadcast_dt"].isna()].copy()
    helper_cols = [c for c in work.columns if c.startswith("__txn_") or c == "__broadcast_dt"]
    work = work.drop(columns=helper_cols, errors="ignore")
    return work.reset_index(drop=True), before - len(work)


# ── Parsing helpers ───────────────────────────────────────────────────────────
def _v(raw) -> float:
    return float(re.sub(r"[^\d.]", "", str(raw)) or 0)


def _q(raw) -> float:
    return float(re.sub(r"[^\d.]", "", str(raw)) or 0)


def _is_equity_instrument(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().eq("equity")


def _build_aggregates(csv_path: Path) -> tuple[pd.DataFrame, set, set]:
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()
    df, duplicate_rows_removed = _deduplicate_transactions(df)
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
        CompanyName=("Company Name", "first"), ValuePurchased=("_value", "sum"),
        ReportedBuyQty=("_qty", "sum"), ReportedBuyTxn=("_value", "count"),
        acqtoDt=("_date", "max"),
    ).reset_index()
    priced = df_buys[df_buys["_priced"]].groupby("Symbol").agg(
        TotalQty=("_qty", "sum"), NumBuyTxn=("_value", "count")
    ).reset_index()
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
    sell_values = df_sells[df_sells["_priced"]].groupby("Symbol")["_value"].sum()
    buy_values = agg.set_index("Symbol")["PricedValuePurchased"]
    agg["MarketBuyValue"] = agg["Symbol"].map(buy_values).fillna(0.0)
    agg["MarketSellValue"] = agg["Symbol"].map(sell_values).fillna(0.0)
    agg["NetBuyValue"] = agg["MarketBuyValue"] - agg["MarketSellValue"]
    agg["SellBuyRatioPct"] = (agg["MarketSellValue"] / agg["MarketBuyValue"].replace(0, float("nan")) * 100).round(2)
    agg["HasMarketSell"] = agg["MarketSellValue"] > 0
    agg["SellBuyExclusion"] = agg["SellBuyRatioPct"] > MAX_SELL_BUY_RATIO_PCT
    sell_syms = set(agg.loc[agg["SellBuyExclusion"], "Symbol"].astype(str).str.strip().str.upper())
    return agg, pledge_syms, sell_syms


# ── Price fetch — Bhavcopy daily CSV (no browser, no auth) ───────────────────
_BHAVCOPY_BASE = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
_BHAVCOPY_HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}


def _download_bhavcopy(max_lookback: int = 5, as_of_date: date | None = None) -> dict[str, float] | None:
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
            prices: dict[str, float] = {}
            for row in rows:
                series = row.get("SctySrs", "").strip()
                if series not in _BHAVCOPY_SERIES:
                    continue
                sym = row.get("TckrSymb", "").strip()
                if sym in prices and series != "EQ":
                    continue
                try:
                    prices[sym] = float(row["ClsPric"])
                except (ValueError, KeyError):
                    pass
            log.info("  Bhavcopy loaded for %s — %d symbols (EQ+BE+BZ)", d.strftime("%Y-%m-%d"), len(prices))
            return prices
        except Exception as exc:
            log.warning("  Bhavcopy fetch failed for %s: %s", ds, exc)
    log.warning("  Bhavcopy: no file found for dates %s", attempted)
    return None


def _fetch_prices(symbols: list[str], as_of_date: date | None = None) -> dict[str, float | None]:
    bhavcopy = _download_bhavcopy(as_of_date=as_of_date)
    prices: dict[str, float | None] = {}
    for sym in symbols:
        price = bhavcopy.get(sym) if bhavcopy else None
        prices[sym] = price
        if price is None:
            log.warning("  price %-15s = N/A  (not found in Bhavcopy EQ/BE/BZ)", sym)
        else:
            log.info("  price %-15s = %s", sym, price)
    return prices


_DMA_WORKERS = 8
_DMA_LOOKBACK = 380


def _fetch_one_bhavcopy(args: tuple) -> dict[str, float] | None:
    date_str, url = args
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36", "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200 or resp.content[:2] != b"PK":
            return None
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        raw = z.read(z.namelist()[0]).decode("utf-8")
        rows = _csv.DictReader(raw.splitlines())
        prices: dict[str, float] = {}
        for row in rows:
            series = row.get("SctySrs", "").strip()
            if series not in _BHAVCOPY_SERIES:
                continue
            sym = row.get("TckrSymb", "").strip()
            if sym in prices and series != "EQ":
                continue
            try:
                prices[sym] = float(row["ClsPric"])
            except (ValueError, KeyError):
                pass
        return prices
    except Exception:
        return None


def _fetch_dma(symbols: list[str], lookback_days: int = _DMA_LOOKBACK, as_of_date: date | None = None) -> dict[str, dict]:
    sym_set = set(symbols)
    today = as_of_date or date.today()
    candidates: list[tuple[str, str]] = []
    for delta in range(lookback_days):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        candidates.append((ds, _BHAVCOPY_BASE.format(date=ds)))
    log.info("  DMA: fetching %d candidate Bhavcopy files (%d workers) …", len(candidates), _DMA_WORKERS)
    with ThreadPoolExecutor(max_workers=_DMA_WORKERS) as pool:
        results = list(pool.map(_fetch_one_bhavcopy, candidates))
    sym_closes: dict[str, list[float]] = {s: [] for s in sym_set}
    trading_days_found = 0
    for daily_prices in results:
        if daily_prices is None:
            continue
        trading_days_found += 1
        for sym in sym_set:
            p = daily_prices.get(sym)
            if p is not None:
                sym_closes[sym].append(p)
    log.info("  DMA: %d trading days loaded", trading_days_found)
    output: dict[str, dict] = {}
    for sym in sym_set:
        closes = sym_closes[sym]
        n = len(closes)
        dma50 = round(sum(closes[:50]) / 50, 2) if n >= 50 else None
        dma200 = round(sum(closes[:200]) / 200, 2) if n >= 200 else None
        six_m = None
        if n >= 1:
            lookback_6m = min(126, n - 1)
            if lookback_6m >= 60:
                p_now = closes[0]
                p_then = closes[lookback_6m]
                if p_then and p_then > 0:
                    six_m = round((p_now / p_then - 1) * 100, 1)
        output[sym] = {"DMA50": dma50, "DMA200": dma200, "SixMonthReturn": six_m}
        log.info("  DMA %-15s  50DMA=%-8s  200DMA=%-8s  6M=%s", sym, f"{dma50:.2f}" if dma50 else "N/A", f"{dma200:.2f}" if dma200 else "N/A", f"{six_m:.1f}%" if six_m is not None else "N/A")
    return output


# ── Screener.in HTML parsers ───────────────────────────────────────────────────
def _parse_holding_html(html: str) -> float | None:
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find(id="shareholding")
    search_root = section if section else soup
    for row in search_root.find_all("tr"):
        text = " ".join(row.get_text().split())
        if re.match(r"^Promoters\s*[+-]?", text, re.IGNORECASE):
            pcts = re.findall(r"([\d.]+)%", text)
            if pcts:
                return float(pcts[0])
    return None


def _parse_num(text: str) -> float | None:
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_fundamentals_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {"MarketCapCr": None, "PE": None, "RevGrowthPct": None, "EBITDAGrowthPct": None, "PATGrowthPct": None, "EPSGrowthPct": None, "ROCEPct": None, "DE_Ratio": None, "OCFPositive": None, "OPMPct": None}
    top = soup.find(id="top-ratios")
    if top:
        for li in top.find_all("li"):
            name_el = li.find("span", class_="name")
            val_el = li.find("span", class_="nowrap") or li.find("span", class_="value")
            if not name_el or not val_el:
                continue
            name = name_el.get_text(strip=True).lower()
            val = _parse_num(val_el.get_text(strip=True))
            if "market cap" in name:
                result["MarketCapCr"] = val
            elif "p/e" in name or name == "pe":
                result["PE"] = val
            elif "roce" in name:
                result["ROCEPct"] = val
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        header_text = header.get_text(" ", strip=True).lower()
        if "compounded sales" in header_text:
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all("td")
                if len(cells) >= 2 and "ttm" in cells[0].get_text(strip=True).lower():
                    result["RevGrowthPct"] = _parse_num(cells[1].get_text(strip=True))
            continue
        if "compounded profit" in header_text:
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all("td")
                if len(cells) >= 2 and "ttm" in cells[0].get_text(strip=True).lower():
                    result["PATGrowthPct"] = _parse_num(cells[1].get_text(strip=True))
            continue
        for tr in table.find_all("tr"):
            cols = tr.find_all("td")
            if len(cols) < 2:
                continue
            label = cols[0].get_text(strip=True).lower()
            vals = [_parse_num(c.get_text(strip=True)) for c in cols[1:]]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            if ("sales" in label or "revenue" in label) and result["RevGrowthPct"] is None:
                result["RevGrowthPct"] = vals[-1]
            elif "operating profit" in label and "margin" not in label and result["EBITDAGrowthPct"] is None:
                result["EBITDAGrowthPct"] = vals[-1]
            elif "opm" in label or ("operating" in label and "margin" in label):
                if result["OPMPct"] is None:
                    result["OPMPct"] = vals[-1]
            elif ("net profit" in label or "profit after tax" in label) and result["PATGrowthPct"] is None:
                result["PATGrowthPct"] = vals[-1]
            elif "eps" in label and result["EPSGrowthPct"] is None:
                result["EPSGrowthPct"] = vals[-1]
    bs_section = soup.find(id="balance-sheet")
    if bs_section:
        eq_cap = reserves = borrowings = None
        for tr in bs_section.find_all("tr"):
            cols = tr.find_all("td")
            if len(cols) < 2:
                continue
            label = cols[0].get_text(strip=True).lower()
            vals = [_parse_num(c.get_text(strip=True)) for c in cols[1:]]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            if "equity capital" in label:
                eq_cap = vals[-1]
            elif "reserves" in label:
                reserves = vals[-1]
            elif "borrowing" in label:
                borrowings = vals[-1]
        if borrowings is not None and eq_cap is not None and reserves is not None:
            net_worth = eq_cap + reserves
            result["DE_Ratio"] = round(borrowings / net_worth, 2) if net_worth > 0 else None
    cf_section = soup.find(id="cash-flow")
    if cf_section:
        for tr in cf_section.find_all("tr"):
            cols = tr.find_all("td")
            if not cols:
                continue
            label = cols[0].get_text(strip=True).lower()
            if "operating" in label or "from operations" in label:
                vals = [_parse_num(c.get_text(strip=True)) for c in cols[1:]]
                vals = [v for v in vals if v is not None]
                if vals:
                    result["OCFPositive"] = vals[-1] > 0
                break
    return result


# ── Worker combining holding + fundamentals in one HTTP session ───────────────
def _screener_worker(syms_slice: list[str], wid: int, counter: list, lock: threading.Lock, total: int, log_every: int) -> dict[str, dict]:
    session = requests.Session()
    session.headers.update(_SCREENER_HEADERS)
    results: dict[str, dict] = {}
    time.sleep(wid * 2.0)
    for sym in syms_slice:
        holding = None
        fundamentals = {}
        for attempt in range(1, HOLDING_RETRY_COUNT + 1):
            try:
                resp = session.get(f"https://www.screener.in/company/{sym}/", timeout=15, allow_redirects=True)
                if resp.status_code == 429:
                    backoff = 5 * (2 ** (attempt - 1))
                    log.warning("  [SW%d] %-15s 429 — retry %d/%d in %ds", wid, sym, attempt, HOLDING_RETRY_COUNT, backoff)
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
                html = resp.text
                holding = _parse_holding_html(html)
                fundamentals = _parse_fundamentals_html(html)
                break
            except requests.exceptions.HTTPError:
                log.warning("  [SW%d] %-15s HTTP error on attempt %d", wid, sym, attempt)
                break
            except Exception as exc:
                log.warning("  [SW%d] %-15s FAILED – %s", wid, sym, exc)
                break
        if holding is None:
            log.warning("  [SW%d] holding %-15s = None", wid, sym)
        results[sym] = {"holding": holding, "fundamentals": fundamentals}
        with lock:
            counter[0] += 1
            done = counter[0]
        if done % log_every == 0 or done == total:
            log.info("  Screener … %d/%d (%d%%)", done, total, done * 100 // total)
        time.sleep(HOLDING_FETCH_DELAY)
    return results


def _fetch_screener_data(symbols: list[str]) -> dict[str, dict]:
    workers = min(HOLDING_WORKERS, len(symbols))
    slices = [symbols[i::workers] for i in range(workers)]
    n = len(symbols)
    counter = [0]
    lock = threading.Lock()
    log_every = max(1, n // 10)
    log.info("  Fetching %d symbols (holding + fundamentals) with %d workers …", n, workers)
    combined: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_screener_worker, sl, wid, counter, lock, n, log_every): wid for wid, sl in enumerate(slices)}
        for fut in futures:
            combined.update(fut.result())
    return combined


def _fetch_holdings(symbols: list[str]) -> dict[str, float | None]:
    data = _fetch_screener_data(symbols)
    return {sym: data[sym]["holding"] for sym in symbols}


# ── Scoring engine ────────────────────────────────────────────────────────────
def _score_row(row: pd.Series, fund: dict) -> tuple[int, int, int, int, int, str]:
    promo_score = 0
    fund_score = 0
    tech_score = 0
    risk_score = 0
    promo_score += SCORE_PROMO_BUY
    if int(row.get("NumBuyTxn", 0) or 0) >= 3:
        promo_score += SCORE_PROMO_MULTI_TXN
    market_cap_cr = fund.get("MarketCapCr")
    value_cr = float(row.get("ValueCr") or 0)
    if market_cap_cr and market_cap_cr > 0:
        conviction_pct = value_cr / market_cap_cr * 100
        if conviction_pct >= 0.25:
            promo_score += SCORE_PROMO_CONVICTION
    elif value_cr >= 10:
        promo_score += SCORE_PROMO_CONVICTION
    holding = float(row.get("PromoHolding") or 0)
    if holding > 65:
        promo_score += SCORE_PROMO_HOLDING_INC
    if not bool(row.get("HasMarketSell", False)):
        promo_score += SCORE_PROMO_NO_SELL
    if not bool(row.get("HasPledging", False)):
        promo_score += SCORE_PROMO_NO_PLEDGE
    rev_g, ebi_g, pat_g = fund.get("RevGrowthPct"), fund.get("EBITDAGrowthPct"), fund.get("PATGrowthPct")
    eps_g, roce, de, ocf = fund.get("EPSGrowthPct"), fund.get("ROCEPct"), fund.get("DE_Ratio"), fund.get("OCFPositive")
    if rev_g is not None and rev_g > 15: fund_score += SCORE_FUND_REV_GROWTH
    if ebi_g is not None and ebi_g > 15: fund_score += SCORE_FUND_EBITDA_GROWTH
    if pat_g is not None and pat_g > 15: fund_score += SCORE_FUND_PAT_GROWTH
    if eps_g is not None and eps_g > 15: fund_score += SCORE_FUND_EPS_GROWTH
    if roce is not None and roce > 15: fund_score += SCORE_FUND_ROCE
    if de is not None and de < 0.5: fund_score += SCORE_FUND_DE_RATIO
    if ocf is True: fund_score += SCORE_FUND_OCF_POS
    last_price = float(row.get("LastPrice") or 0)
    avg_price = float(row.get("AvgPrice") or 0)
    if last_price > avg_price > 0: tech_score += SCORE_TECH_ABOVE_REF
    dma50, dma200 = fund.get("DMA50"), fund.get("DMA200")
    if dma50 and last_price > dma50: tech_score += SCORE_TECH_ABOVE_50DMA
    if dma200 and last_price > dma200: tech_score += SCORE_TECH_ABOVE_200DMA
    if dma50 and dma200 and dma50 > dma200: tech_score += SCORE_TECH_DMA_CROSS
    price_diff_pct = float(row.get("PriceDiffPct") or 0)
    num_txn = int(row.get("NumBuyTxn", 0) or 0)
    if price_diff_pct > 5 and num_txn >= 2: tech_score += SCORE_TECH_VOL_EXPANSION
    six_m = fund.get("SixMonthReturn")
    if six_m is not None and six_m > 0: tech_score += SCORE_TECH_REL_STRENGTH
    elif six_m is None and price_diff_pct > 10: tech_score += SCORE_TECH_REL_STRENGTH
    if bool(row.get("HasPledging", False)): risk_score += SCORE_RISK_PLEDGE
    opm = fund.get("OPMPct")
    if opm is not None and opm < 5: risk_score += SCORE_RISK_MARGIN_FALL
    pe = fund.get("PE")
    if pe is not None and pe > 60: risk_score += SCORE_RISK_HIGH_PE
    total = max(0, min(100, promo_score + fund_score + tech_score + risk_score))
    if total >= CATEGORY_STRONG_BUY: category = "Strong Buy Setup"
    elif total >= CATEGORY_BUY_BREAKOUT: category = "Buy on Breakout"
    elif total >= CATEGORY_WATCHLIST: category = "Watchlist"
    elif total >= CATEGORY_WEAK_FUND: category = "Fundamental Watch"
    else: category = "Avoid"
    return promo_score, fund_score, tech_score, risk_score, total, category


def _apply_scores(df: pd.DataFrame, screener_data: dict, dma_data: dict | None = None) -> pd.DataFrame:
    screener_fund_cols = ["MarketCapCr", "PE", "RevGrowthPct", "EBITDAGrowthPct", "PATGrowthPct", "EPSGrowthPct", "ROCEPct", "DE_Ratio", "OCFPositive", "OPMPct"]
    for col in ("DMA50", "DMA200", "SixMonthReturn"):
        if col not in df.columns: df[col] = None
    for col in screener_fund_cols: df[col] = None
    score_rows = []
    for idx, row in df.iterrows():
        sym = str(row["Symbol"])
        sdata = screener_data.get(sym, {})
        fund = sdata.get("fundamentals", {}) if sdata else {}
        for col in screener_fund_cols: df.at[idx, col] = fund.get(col)
        mc = fund.get("MarketCapCr")
        vc = float(row.get("ValueCr") or 0)
        df.at[idx, "PromoConvictionPct"] = round(vc / mc * 100, 3) if mc and mc > 0 else None
        fund_with_dma = dict(fund)
        fund_with_dma["DMA50"] = row.get("DMA50")
        fund_with_dma["DMA200"] = row.get("DMA200")
        fund_with_dma["SixMonthReturn"] = row.get("SixMonthReturn")
        score_rows.append(_score_row(row, fund_with_dma))
    (df["ScorePromo"], df["ScoreFund"], df["ScoreTech"], df["ScoreRisk"], df["Score"], df["Category"]) = zip(*score_rows)
    return df


# ── Promoter trades saver ─────────────────────────────────────────────────────
def _save_promoter_trades(csv_path: Path, candidate_syms: set, out_path: Path) -> None:
    _TRADE_COLS = ["Symbol", "Company Name", "Name of Person", "CIN/DIN", "Category of Person", "Type of Instrument", "Securities Held Prior (No.)", "Securities Held Prior (%)", "Securities Acquired/Disposed (No.)", "Securities Acquired/Disposed (Value)", "Transaction Type", "Securities Held Post (No.)", "Securities Held Post (%)", "Date From", "Date To", "Mode of Acquisition/Disposal", "Broadcast Date/Time", "Details URL"]
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        df.columns = df.columns.str.strip()
        df, duplicate_rows_removed = _deduplicate_transactions(df)
        mask = (df["Symbol"].isin(candidate_syms) & _is_equity_instrument(df["Type of Instrument"]) & (df["Transaction Type"].str.strip().str.lower() == "buy") & (df["Mode of Acquisition/Disposal"].str.strip().str.lower() == "market purchase") & df["Category of Person"].str.strip().str.lower().isin(PROMOTER_CATEGORIES))
        trades = df.loc[mask, [c for c in _TRADE_COLS if c in df.columns]].copy()
        trades.to_csv(out_path, index=False, encoding="utf-8-sig")
        log.info("Promoter trades → %s (%d rows; %d repeated filing row(s) removed)", out_path, len(trades), duplicate_rows_removed)
    except Exception as exc:
        log.warning("Could not save promoter trades: %s", exc)


# ── Timing enrichment ─────────────────────────────────────────────────────────
def _signal_stage(freshness: str, accumulation_stage: str, cmp_vs_avg_pct) -> str:
    """Classify entry timing; descriptive only and independent of RYB score."""
    if cmp_vs_avg_pct is None or pd.isna(cmp_vs_avg_pct) or freshness == "No Signal":
        return "No Signal"
    premium = float(cmp_vs_avg_pct)
    if freshness == "Stale":
        return "Late — Poor Entry"
    if accumulation_stage == "Early Accumulation" and premium <= 10:
        return "Early Accumulation"
    if freshness in {"Fresh", "Active"} and premium <= 10:
        return "Confirmed Accumulation"
    if premium <= 20:
        return "Mature — Wait for Pullback"
    return "Late — Poor Entry"


def _apply_timing_metrics(df: pd.DataFrame, csv_path: Path, as_of_date: date | None) -> pd.DataFrame:
    """Join promoter timing metrics to enriched rows without changing score/category."""
    snapshot = build_accumulation_snapshot(csv_path, as_of_date or date.today())
    timing_cols = [
        "Symbol", "FirstBuyDate", "LastBuyDate", "FirstBuyPrice", "LastBuyPrice",
        "WeightedAvgBuyPrice", "AccumulationDays", "DaysSinceFirstBuy", "DaysSinceLastBuy",
        "BuyTxn7D", "BuyTxn15D", "BuyTxn30D", "BuyTxn60D", "BuyTxn90D",
        "BuyValue7D", "BuyValue15D", "BuyValue30D", "BuyValue60D", "BuyValue90D",
        "NetBuyValue7D", "NetBuyValue30D", "UniquePromotersBuying", "UniquePromotersSelling",
        "BuyAcceleration", "Freshness", "AccumulationStage",
    ]
    if snapshot.empty:
        for col in timing_cols[1:]:
            df[col] = None
        df["PromoterAvgPrice"] = df.get("AvgPrice")
        df["CMPvsPromoterAvgPct"] = None
        df["SignalStage"] = "No Signal"
        return df
    timing = snapshot[[c for c in timing_cols if c in snapshot.columns]].copy()
    df = df.merge(timing, on="Symbol", how="left", suffixes=("", "_timing"))
    df["PromoterAvgPrice"] = pd.to_numeric(df["WeightedAvgBuyPrice"], errors="coerce")
    fallback = pd.to_numeric(df["AvgPrice"], errors="coerce")
    df["PromoterAvgPrice"] = df["PromoterAvgPrice"].fillna(fallback)
    cmp = pd.to_numeric(df["LastPrice"], errors="coerce")
    avg = pd.to_numeric(df["PromoterAvgPrice"], errors="coerce")
    df["CMPvsPromoterAvgPct"] = ((cmp - avg) / avg.replace(0, pd.NA) * 100).round(1)
    df["SignalStage"] = [
        _signal_stage(f, s, p)
        for f, s, p in zip(df["Freshness"].fillna("No Signal"), df["AccumulationStage"].fillna("No Signal"), df["CMPvsPromoterAvgPct"])
    ]
    return df


# ── Phase 2 entry point ───────────────────────────────────────────────────────
def run(csv_path: Path, full_csv_path: Path, as_of_date: date | None = None) -> pd.DataFrame:
    log.info("━" * 60)
    log.info("PHASE 2 — Filtering & enriching")
    log.info("━" * 60)
    agg, pledge_syms, sell_syms = _build_aggregates(csv_path)
    log.info("Pledging symbols excluded (%d): %s", len(pledge_syms), sorted(pledge_syms))
    log.info("Promoter sell >25%% of buy excluded (%d): %s", len(sell_syms), sorted(sell_syms))
    agg["HasPledging"] = agg["Symbol"].isin(pledge_syms)
    agg_clean = agg[~agg["HasPledging"] & ~agg["SellBuyExclusion"]].reset_index(drop=True)
    log.info("After pledge + promoter sell-ratio filter: %d symbols", len(agg_clean))
    symbols = agg_clean["Symbol"].tolist()
    _save_promoter_trades(csv_path, set(symbols), full_csv_path.parent / TRADES_CSV_FILENAME)
    log.info("Fetching prices (%d symbols) from NSE Bhavcopy …", len(symbols))
    prices = _fetch_prices(symbols, as_of_date=as_of_date)
    log.info("Computing DMA50 / DMA200 / 6M return from NSE Bhavcopy history …")
    dma_data = _fetch_dma(symbols, as_of_date=as_of_date)
    log.info("Fetching holdings + fundamentals (%d symbols) from Screener.in …", len(symbols))
    screener_data = _fetch_screener_data(symbols)
    agg_clean = agg_clean.copy()
    agg_clean["LastPrice"] = agg_clean["Symbol"].map(prices)
    agg_clean["PromoHolding"] = agg_clean["Symbol"].map({sym: screener_data[sym]["holding"] for sym in symbols})
    agg_clean["DMA50"] = agg_clean["Symbol"].map({s: dma_data[s]["DMA50"] for s in symbols})
    agg_clean["DMA200"] = agg_clean["Symbol"].map({s: dma_data[s]["DMA200"] for s in symbols})
    agg_clean["SixMonthReturn"] = agg_clean["Symbol"].map({s: dma_data[s]["SixMonthReturn"] for s in symbols})
    agg_clean["PriceDiffPct"] = ((agg_clean["LastPrice"] - agg_clean["AvgPrice"]) / agg_clean["AvgPrice"] * 100).round(1)
    agg_clean["AbsDiffPct"] = agg_clean["PriceDiffPct"].abs()
    # Timing metrics are descriptive only.  They do not alter score/category.
    agg_clean = _apply_timing_metrics(agg_clean, csv_path, as_of_date)
    agg_clean = _apply_scores(agg_clean, screener_data, dma_data)
    full_csv_path.parent.mkdir(parents=True, exist_ok=True)
    agg_clean.to_csv(full_csv_path, index=False, encoding="utf-8-sig")
    log.info("Full enriched data → %s", full_csv_path)
    valid = agg_clean.dropna(subset=["LastPrice", "PromoHolding"])
    final = (valid[valid["PromoHolding"] >= MIN_PROMO_HOLDING]
             .sort_values("Score", ascending=False).reset_index(drop=True))
    log.info("After promoter holding ≥%.0f%% filter: %d symbols", MIN_PROMO_HOLDING, len(final))
    return final
