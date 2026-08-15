"""
Phase 2 — Filter, Enrich, Fetch Prices, Holdings, Fundamentals & Score

Applies:
  Filter B  No Pledge Creation / Invocation by Promoter/PG
  Filter C  No Market Sale by Promoter/PG
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
    MIN_PURCHASE_VALUE, MIN_PROMO_HOLDING,
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


# ── Parsing helpers ───────────────────────────────────────────────────────────
def _v(raw) -> float:
    """Parse a money string like '22,398,800.00' → float."""
    return float(re.sub(r"[^\d.]", "", str(raw)) or 0)

def _q(raw) -> float:
    """Parse a quantity string like '4,250' → float."""
    return float(re.sub(r"[^\d.]", "", str(raw)) or 0)


def _build_aggregates(csv_path: Path) -> tuple[pd.DataFrame, set, set]:
    """
    Load CSV, build per-symbol aggregates for promoter market buys,
    and derive the pledge / market-sell exclusion sets.

    Returns (agg_filtered, pledge_syms, sell_syms)
    """
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()

    df_promo = df[
        df["Category of Person"].str.strip().str.lower().isin(PROMOTER_CATEGORIES)
    ].copy()

    # Aggregation source: promoter Market Purchase buys only
    df_buys = df_promo[
        (df_promo["Transaction Type"].str.strip().str.lower() == "buy") &
        (df_promo["Mode of Acquisition/Disposal"].str.strip().str.lower() == "market purchase")
    ].copy()

    df_buys["_value"] = df_buys["Securities Acquired/Disposed (Value)"].apply(_v)
    df_buys["_qty"]   = df_buys["Securities Acquired/Disposed (No.)"].apply(_q)
    df_buys["_date"]  = pd.to_datetime(
        df_buys["Date To"].str.strip(), format="%d-%m-%Y", errors="coerce"
    )

    agg = df_buys.groupby("Symbol").agg(
        CompanyName   = ("Company Name", "first"),
        ValuePurchased= ("_value", "sum"),
        TotalQty      = ("_qty",   "sum"),
        NumBuyTxn     = ("_value", "count"),
        acqtoDt       = ("_date",  "max"),
    ).reset_index()

    agg["AvgPrice"] = (
        agg["ValuePurchased"] / agg["TotalQty"].replace(0, float("nan"))
    ).round(2)
    agg["acqtoDt"] = agg["acqtoDt"].dt.strftime("%d-%m-%Y")
    agg["ValueCr"] = (agg["ValuePurchased"] / 1e7).round(2)

    # ≥ ₹20L gate
    agg = agg[agg["ValuePurchased"] >= MIN_PURCHASE_VALUE] \
            .sort_values("ValuePurchased", ascending=False) \
            .reset_index(drop=True)

    log.info("Base symbols ≥₹%.0fL: %d", MIN_PURCHASE_VALUE / 1e5, len(agg))

    # Pledge exclusion set
    pledge_syms = set(
        df_promo[
            df_promo["Mode of Acquisition/Disposal"].str.strip().str.lower().isin(PLEDGE_MODES)
        ]["Symbol"].str.strip().str.upper()
    )

    # Market-sell exclusion set
    sell_syms = set(
        df_promo[
            (df_promo["Transaction Type"].str.strip().str.lower() == "sell") &
            (df_promo["Mode of Acquisition/Disposal"].str.strip().str.lower() == "market sale")
        ]["Symbol"].str.strip().str.upper()
    )

    return agg, pledge_syms, sell_syms


# ── Price fetch — Bhavcopy daily CSV (no browser, no auth) ───────────────────
_BHAVCOPY_BASE = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
)
_BHAVCOPY_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}


def _download_bhavcopy(max_lookback: int = 5) -> dict[str, float] | None:
    """
    Download the most recent Bhavcopy daily CSV and return a dict
    {SYMBOL -> LastPrice} for all EQ/BE/BZ-series equities.

    Tries today first, then up to *max_lookback* prior calendar days
    (skipping weekends) so the pipeline works even if run after market
    hours before the day's file is published, or on a Monday.

    Returns None if no file is found within the lookback window.
    """
    session = requests.Session()
    session.headers.update(_BHAVCOPY_HEADERS)

    today = date.today()
    attempted: list[str] = []

    for delta in range(max_lookback + 1):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5:          # skip Saturday (5) and Sunday (6)
            continue
        ds  = d.strftime("%Y%m%d")
        url = _BHAVCOPY_BASE.format(date=ds)
        attempted.append(ds)
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code != 200 or resp.content[:2] != b"PK":
                continue
            z    = zipfile.ZipFile(io.BytesIO(resp.content))
            raw  = z.read(z.namelist()[0]).decode("utf-8")
            rows = _csv.DictReader(raw.splitlines())
            prices: dict[str, float] = {}
            for row in rows:
                series = row.get("SctySrs", "").strip()
                if series not in _BHAVCOPY_SERIES:
                    continue
                sym = row.get("TckrSymb", "").strip()
                # Prefer EQ price over BE/BZ if symbol appears in multiple series
                if sym in prices and series != "EQ":
                    continue
                try:
                    prices[sym] = float(row["LastPric"])
                except (ValueError, KeyError):
                    pass
            log.info(
                "  Bhavcopy loaded for %s — %d symbols (EQ+BE+BZ)",
                d.strftime("%Y-%m-%d"), len(prices),
            )
            return prices
        except Exception as exc:
            log.warning("  Bhavcopy fetch failed for %s: %s", ds, exc)

    log.warning("  Bhavcopy: no file found for dates %s", attempted)
    return None


def _fetch_prices(symbols: list[str]) -> dict[str, float | None]:
    """
    Resolve last traded prices for *symbols* from the Bhavcopy daily CSV.
    Downloads the file once; all symbol lookups are done in-memory.
    No browser, no cookies, no per-symbol HTTP request.
    """
    bhavcopy = _download_bhavcopy()
    prices: dict[str, float | None] = {}

    for sym in symbols:
        price = bhavcopy.get(sym) if bhavcopy else None
        prices[sym] = price
        if price is None:
            log.warning("  price %-15s = N/A  (not found in Bhavcopy EQ/BE/BZ)", sym)
        else:
            log.info("  price %-15s = %s", sym, price)

    return prices


# ── DMA computation from NSE Bhavcopy history ────────────────────────────────

_DMA_WORKERS = 8      # parallel workers for Bhavcopy history download
# NSE Bhavcopy archive has ~269 trading days available.
# 200 trading days needs ~280 calendar days but NSE holidays eat into that.
# Use 380 calendar days so we always request enough URLs to collect ≥200 results.
_DMA_LOOKBACK = 380


def _fetch_one_bhavcopy(args: tuple) -> dict[str, float] | None:
    """Download one Bhavcopy file and return {symbol: close_price}.
    Designed for use with ThreadPoolExecutor.map — takes a single tuple arg
    (date_str, url) so it can be pickled by the executor."""
    date_str, url = args
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200 or resp.content[:2] != b"PK":
            return None
        z    = zipfile.ZipFile(io.BytesIO(resp.content))
        raw  = z.read(z.namelist()[0]).decode("utf-8")
        rows = _csv.DictReader(raw.splitlines())
        prices: dict[str, float] = {}
        for row in rows:
            series = row.get("SctySrs", "").strip()
            if series not in _BHAVCOPY_SERIES:
                continue
            sym = row.get("TckrSymb", "").strip()
            # EQ preferred over BE/BZ; close price for DMA calculation
            if sym in prices and series != "EQ":
                continue
            try:
                prices[sym] = float(row["ClsPric"])
            except (ValueError, KeyError):
                pass
        return prices
    except Exception:
        return None


def _fetch_dma(symbols: list[str], lookback_days: int = _DMA_LOOKBACK) -> dict[str, dict]:
    """
    Download the last ~200 trading days of Bhavcopy files in parallel and
    compute 50-day DMA, 200-day DMA, and 6-month return for each symbol.

    Returns a dict keyed by symbol:
        {
            "DMA50"         : float | None,
            "DMA200"        : float | None,
            "SixMonthReturn": float | None,   # % return over ~126 trading days
        }

    Strategy
    --------
    - Walk back *lookback_days* calendar days from today, skip weekends.
    - Build a list of (date_str, url) for each candidate trading day.
    - Fetch all files in parallel (_DMA_WORKERS threads).
    - For each file that returns data, record the close price per symbol.
    - After all files loaded, sort the per-symbol close series by date
      (newest first) and compute DMAs from the most recent N closes.
    - 6M return = (close_today / close_~126_days_ago - 1) × 100.

    Only ~200 files × ~190 KB each are downloaded; the entire batch takes
    roughly 2–3 seconds with 8 parallel workers.
    """
    sym_set = set(symbols)
    today   = date.today()

    # Build candidate (date_str, url) list — newest first
    candidates: list[tuple[str, str]] = []
    for delta in range(lookback_days):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5:          # skip Saturday / Sunday
            continue
        ds  = d.strftime("%Y%m%d")
        url = _BHAVCOPY_BASE.format(date=ds)
        candidates.append((ds, url))

    log.info(
        "  DMA: fetching %d candidate Bhavcopy files (%d workers) …",
        len(candidates), _DMA_WORKERS,
    )

    # Parallel download — result list is ordered by candidates order (newest first)
    results: list[dict[str, float] | None] = []
    with ThreadPoolExecutor(max_workers=_DMA_WORKERS) as pool:
        results = list(pool.map(_fetch_one_bhavcopy, candidates))

    # Collect per-symbol close series (index 0 = most recent trading day)
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

    # Compute DMA50 / DMA200 / SixMonthReturn for each symbol
    output: dict[str, dict] = {}
    for sym in sym_set:
        closes = sym_closes[sym]   # newest → oldest
        n = len(closes)
        dma50  = round(sum(closes[:50])  / 50,  2) if n >= 50  else None
        dma200 = round(sum(closes[:200]) / 200, 2) if n >= 200 else None
        # 6M ≈ 126 trading days; use what we have if slightly short (≥ 120)
        six_m  = None
        if n >= 1:
            lookback_6m = min(126, n - 1)
            if lookback_6m >= 60:   # require at least ~3 months of data
                p_now  = closes[0]
                p_then = closes[lookback_6m]
                if p_then and p_then > 0:
                    six_m = round((p_now / p_then - 1) * 100, 1)
        output[sym] = {"DMA50": dma50, "DMA200": dma200, "SixMonthReturn": six_m}
        log.info(
            "  DMA %-15s  50DMA=%-8s  200DMA=%-8s  6M=%s",
            sym,
            f"{dma50:.2f}" if dma50 else "N/A",
            f"{dma200:.2f}" if dma200 else "N/A",
            f"{six_m:.1f}%" if six_m is not None else "N/A",
        )

    return output


# ── Screener.in HTML parsers ───────────────────────────────────────────────────

def _parse_holding_html(html: str) -> float | None:
    """
    Extract latest promoter holding % from Screener.in company page HTML.

    Targets the Shareholding Pattern section specifically, then falls back
    to a broad table scan.  Returns the most-recent-quarter figure
    (first percentage in the Promoters row, which is the leftmost/latest column).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try scoped search inside the #shareholding section first
    section = soup.find(id="shareholding")
    search_root = section if section else soup

    for row in search_root.find_all("tr"):
        text = " ".join(row.get_text().split())
        if re.match(r"^Promoters\s*[+-]?", text, re.IGNORECASE):
            pcts = re.findall(r"([\d.]+)%", text)
            if pcts:
                return float(pcts[0])   # first = most recent quarter

    return None


def _parse_num(text: str) -> float | None:
    """Parse a compact number string like '1,234 Cr' or '12.5%' → float or None."""
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_fundamentals_html(html: str) -> dict:
    """
    Parse Screener.in company page HTML for fundamental data points:
      MarketCap (₹ Cr), PE, RevGrowth%, EBITDAGrowth%, PATGrowth%,
      EPSGrowth%, ROCE%, DE_Ratio, OCFPositive (bool), OPM% (operating margin)

    DMA50 / DMA200 / SixMonthReturn are NO LONGER sourced from Screener —
    they are computed directly from NSE Bhavcopy history in _fetch_dma().

    All values are best-effort from the static Screener HTML.
    Missing fields are returned as None.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {
        "MarketCapCr": None,
        "PE": None,
        "RevGrowthPct": None,
        "EBITDAGrowthPct": None,
        "PATGrowthPct": None,
        "EPSGrowthPct": None,
        "ROCEPct": None,
        "DE_Ratio": None,
        "OCFPositive": None,
        "OPMPct": None,
    }

    # ── #top-ratios: Market Cap, PE, ROCE ───────────────────────────────────
    # Screener field names (lowercased):
    #   "market cap"  → MarketCapCr
    #   "stock p/e"   → PE          (NOT "p/e" or "pe" — those never appear)
    #   "roce"        → ROCEPct
    top = soup.find(id="top-ratios")
    if top:
        for li in top.find_all("li"):
            name_el = li.find("span", class_="name")
            val_el  = li.find("span", class_="nowrap") or li.find("span", class_="value")
            if not name_el or not val_el:
                continue
            name = name_el.get_text(strip=True).lower()
            raw  = val_el.get_text(strip=True)
            val  = _parse_num(raw)
            if "market cap" in name:
                result["MarketCapCr"] = val
            elif "p/e" in name or name == "pe":
                # Screener renders "Stock P/E" — any name containing "p/e" matches
                result["PE"] = val
            elif "roce" in name:
                result["ROCEPct"] = val

    # ── #profit-loss table ───────────────────────────────────────────────────
    # Quarterly table rows (no section id): Sales+, Expenses+, Operating Profit,
    # OPM %, Net Profit, EPS
    # Annual table rows (inside #profit-loss): same structure
    # We scan ALL tables to catch both quarterly and annual variants.
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        header_text = header.get_text(" ", strip=True).lower()

        # ── Compounded Sales / Profit Growth (TTM row) ──────────────────────
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

        # ── P&L / quarterly data rows ────────────────────────────────────────
        # Only process tables that look like financial statement tables
        # (header contains year/quarter patterns or empty first cell)
        for tr in table.find_all("tr"):
            cols = tr.find_all("td")
            if len(cols) < 2:
                continue
            label = cols[0].get_text(strip=True).lower()
            vals  = [_parse_num(c.get_text(strip=True)) for c in cols[1:]]
            vals  = [v for v in vals if v is not None]
            if not vals:
                continue

            if ("sales" in label or "revenue" in label) and result["RevGrowthPct"] is None:
                result["RevGrowthPct"] = vals[-1]
            elif "operating profit" in label and "margin" not in label and result["EBITDAGrowthPct"] is None:
                result["EBITDAGrowthPct"] = vals[-1]
            elif "opm" in label or ("operating" in label and "margin" in label):
                # OPM % row — take the most recent quarter value (last column)
                if result["OPMPct"] is None:
                    result["OPMPct"] = vals[-1]
            elif ("net profit" in label or "profit after tax" in label) and result["PATGrowthPct"] is None:
                result["PATGrowthPct"] = vals[-1]
            elif "eps" in label and result["EPSGrowthPct"] is None:
                result["EPSGrowthPct"] = vals[-1]

    # ── Balance sheet: compute D/E from Borrowings ÷ (Equity + Reserves) ────
    # Screener balance sheet table has rows: Equity Capital, Reserves, Borrowings+
    # We grab the most recent year values (last column) for all three.
    bs_section = soup.find(id="balance-sheet")
    if bs_section:
        eq_cap = reserves = borrowings = None
        for tr in bs_section.find_all("tr"):
            cols = tr.find_all("td")
            if len(cols) < 2:
                continue
            label = cols[0].get_text(strip=True).lower()
            vals  = [_parse_num(c.get_text(strip=True)) for c in cols[1:]]
            vals  = [v for v in vals if v is not None]
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

    # ── Cash-flow: OCF positive flag ─────────────────────────────────────────
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

def _screener_worker(
    syms_slice: list[str],
    wid: int,
    counter: list,
    lock: threading.Lock,
    total: int,
    log_every: int,
) -> dict[str, dict]:
    """
    Fetch promoter holdings AND fundamentals for a slice of symbols from
    Screener.in.  Returns a dict keyed by symbol:
        { "holding": float|None, "fundamentals": dict }

    Uses a single requests.Session per worker (thread-safe).
    Workers are staggered by wid*2s at startup to avoid burst 429s.
    429 responses trigger exponential backoff (5 s, 10 s, 20 s).
    """
    session = requests.Session()
    session.headers.update(_SCREENER_HEADERS)

    results: dict[str, dict] = {}
    time.sleep(wid * 2.0)

    for sym in syms_slice:
        holding      = None
        fundamentals = {}
        for attempt in range(1, HOLDING_RETRY_COUNT + 1):
            try:
                resp = session.get(
                    f"https://www.screener.in/company/{sym}/",
                    timeout=15, allow_redirects=True,
                )
                if resp.status_code == 429:
                    backoff = 5 * (2 ** (attempt - 1))
                    log.warning(
                        "  [SW%d] %-15s 429 — retry %d/%d in %ds",
                        wid, sym, attempt, HOLDING_RETRY_COUNT, backoff,
                    )
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
                html = resp.text
                holding      = _parse_holding_html(html)
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
    """Fetch holding + fundamentals for every symbol from Screener.in — parallel workers."""
    workers   = min(HOLDING_WORKERS, len(symbols))
    slices    = [symbols[i::workers] for i in range(workers)]
    n         = len(symbols)
    counter   = [0]
    lock      = threading.Lock()
    log_every = max(1, n // 10)
    log.info("  Fetching %d symbols (holding + fundamentals) with %d workers …", n, workers)

    combined: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_screener_worker, sl, wid, counter, lock, n, log_every): wid
            for wid, sl in enumerate(slices)
        }
        for fut in futures:
            combined.update(fut.result())
    return combined


# ── Legacy thin wrappers kept for backward compatibility ──────────────────────

def _fetch_holdings(symbols: list[str]) -> dict[str, float | None]:
    """Return {sym: holding%|None} — delegates to _fetch_screener_data."""
    data = _fetch_screener_data(symbols)
    return {sym: data[sym]["holding"] for sym in symbols}


# ── Scoring engine ────────────────────────────────────────────────────────────

def _score_row(row: pd.Series, fund: dict) -> tuple[int, int, int, int, int, str]:
    """
    Compute the four scoring sub-components and the final score for one row.

    Parameters
    ----------
    row : pd.Series
        A row from the enriched DataFrame (must have AvgPrice, LastPrice,
        PromoHolding, ValueCr, NumBuyTxn, HasPledging, HasMarketSell).
    fund : dict
        Fundamentals dict from _parse_fundamentals_html (may be empty {}).

    Returns
    -------
    (promo_score, fund_score, tech_score, risk_score, total_score, category)
    """
    promo_score = 0
    fund_score  = 0
    tech_score  = 0
    risk_score  = 0   # only deductions

    # ── Promoter Signal (max 25) ─────────────────────────────────────────────
    promo_score += SCORE_PROMO_BUY                          # always present (buy universe)

    if int(row.get("NumBuyTxn", 0) or 0) >= 3:
        promo_score += SCORE_PROMO_MULTI_TXN

    market_cap_cr = fund.get("MarketCapCr")
    value_cr = float(row.get("ValueCr") or 0)
    if market_cap_cr and market_cap_cr > 0:
        conviction_pct = value_cr / market_cap_cr * 100
        if conviction_pct >= 0.25:
            promo_score += SCORE_PROMO_CONVICTION
    # If market cap is unknown: partial credit if absolute value is large (≥₹10 Cr)
    elif value_cr >= 10:
        promo_score += SCORE_PROMO_CONVICTION

    holding = float(row.get("PromoHolding") or 0)
    if holding > 65:
        promo_score += SCORE_PROMO_HOLDING_INC

    if not bool(row.get("HasMarketSell", False)):
        promo_score += SCORE_PROMO_NO_SELL

    if not bool(row.get("HasPledging", False)):
        promo_score += SCORE_PROMO_NO_PLEDGE

    # ── Fundamental Signal (max 35) ──────────────────────────────────────────
    rev_g  = fund.get("RevGrowthPct")
    ebi_g  = fund.get("EBITDAGrowthPct")
    pat_g  = fund.get("PATGrowthPct")
    eps_g  = fund.get("EPSGrowthPct")
    roce   = fund.get("ROCEPct")
    de     = fund.get("DE_Ratio")
    ocf    = fund.get("OCFPositive")

    if rev_g  is not None and rev_g  > 15: fund_score += SCORE_FUND_REV_GROWTH
    if ebi_g  is not None and ebi_g  > 15: fund_score += SCORE_FUND_EBITDA_GROWTH
    if pat_g  is not None and pat_g  > 15: fund_score += SCORE_FUND_PAT_GROWTH
    if eps_g  is not None and eps_g  > 15: fund_score += SCORE_FUND_EPS_GROWTH
    if roce   is not None and roce   > 15: fund_score += SCORE_FUND_ROCE
    if de     is not None and de     < 0.5: fund_score += SCORE_FUND_DE_RATIO
    if ocf    is True:                     fund_score += SCORE_FUND_OCF_POS

    # ── Technical Signal (max 30) ────────────────────────────────────────────
    last_price = float(row.get("LastPrice") or 0)
    avg_price  = float(row.get("AvgPrice")  or 0)

    if last_price > avg_price > 0:
        tech_score += SCORE_TECH_ABOVE_REF

    dma50  = fund.get("DMA50")
    dma200 = fund.get("DMA200")

    if dma50  and last_price > dma50:  tech_score += SCORE_TECH_ABOVE_50DMA
    if dma200 and last_price > dma200: tech_score += SCORE_TECH_ABOVE_200DMA
    if dma50  and dma200 and dma50 > dma200: tech_score += SCORE_TECH_DMA_CROSS

    # Volume expansion: proxy — if price > ref and multiple transactions, assume positive
    price_diff_pct = float(row.get("PriceDiffPct") or 0)
    num_txn = int(row.get("NumBuyTxn", 0) or 0)
    if price_diff_pct > 5 and num_txn >= 2:
        tech_score += SCORE_TECH_VOL_EXPANSION

    # Relative strength vs Nifty — use 6M return from Screener if available
    six_m = fund.get("SixMonthReturn")
    if six_m is not None and six_m > 0:
        tech_score += SCORE_TECH_REL_STRENGTH
    elif six_m is None and price_diff_pct > 10:
        # Fallback: if price is well above ref and no data, partial signal
        tech_score += SCORE_TECH_REL_STRENGTH

    # ── Risk deductions (up to −10) ──────────────────────────────────────────
    if bool(row.get("HasPledging", False)):
        risk_score += SCORE_RISK_PLEDGE

    opm = fund.get("OPMPct")
    if opm is not None and opm < 5:   # very thin/negative operating margin
        risk_score += SCORE_RISK_MARGIN_FALL

    pe = fund.get("PE")
    if pe is not None and pe > 60:
        risk_score += SCORE_RISK_HIGH_PE

    total = max(0, min(100, promo_score + fund_score + tech_score + risk_score))

    # ── Category ─────────────────────────────────────────────────────────────
    if total >= CATEGORY_STRONG_BUY:
        category = "Strong Buy Setup"
    elif total >= CATEGORY_BUY_BREAKOUT:
        category = "Buy on Breakout"
    elif total >= CATEGORY_WATCHLIST:
        category = "Watchlist"
    elif total >= CATEGORY_WEAK_FUND:
        category = "Fundamental Watch"
    else:
        category = "Avoid"

    return promo_score, fund_score, tech_score, risk_score, total, category


def _apply_scores(df: pd.DataFrame, screener_data: dict,
                  dma_data: dict | None = None) -> pd.DataFrame:
    """
    Add score and fundamental columns to *df*.

    DMA50 / DMA200 / SixMonthReturn are expected to already be present as
    columns on *df* (merged in run() from _fetch_dma()).  This function
    populates the Screener-sourced fundamentals and then scores each row,
    reading DMA values directly from the row (not from fund dict).

    New columns added:
      MarketCapCr, PE, RevGrowthPct, EBITDAGrowthPct, PATGrowthPct,
      EPSGrowthPct, ROCEPct, DE_Ratio, OCFPositive, OPMPct,
      PromoConvictionPct,
      ScorePromo, ScoreFund, ScoreTech, ScoreRisk, Score, Category
    """
    screener_fund_cols = [
        "MarketCapCr", "PE", "RevGrowthPct", "EBITDAGrowthPct",
        "PATGrowthPct", "EPSGrowthPct", "ROCEPct", "DE_Ratio",
        "OCFPositive", "OPMPct",
    ]
    # Ensure DMA columns exist (may not if called without dma_data, e.g. in tests)
    for col in ("DMA50", "DMA200", "SixMonthReturn"):
        if col not in df.columns:
            df[col] = None

    # Initialise Screener-sourced columns with None
    for col in screener_fund_cols:
        df[col] = None

    score_rows = []
    for idx, row in df.iterrows():
        sym   = str(row["Symbol"])
        sdata = screener_data.get(sym, {})
        fund  = sdata.get("fundamentals", {}) if sdata else {}

        # Populate Screener fundamentals
        for col in screener_fund_cols:
            df.at[idx, col] = fund.get(col)

        # Promoter conviction %
        mc   = fund.get("MarketCapCr")
        vc   = float(row.get("ValueCr") or 0)
        conv = round(vc / mc * 100, 3) if mc and mc > 0 else None
        df.at[idx, "PromoConvictionPct"] = conv

        # Build augmented fund dict that also carries the DMA values for _score_row
        fund_with_dma = dict(fund)
        fund_with_dma["DMA50"]          = row.get("DMA50")
        fund_with_dma["DMA200"]         = row.get("DMA200")
        fund_with_dma["SixMonthReturn"] = row.get("SixMonthReturn")

        p, f, t, r, total, cat = _score_row(row, fund_with_dma)
        score_rows.append((p, f, t, r, total, cat))

    (df["ScorePromo"], df["ScoreFund"], df["ScoreTech"],
     df["ScoreRisk"],  df["Score"],     df["Category"]) = zip(*score_rows)

    return df


# ── Promoter trades saver ─────────────────────────────────────────────────────

def _save_promoter_trades(csv_path: Path, candidate_syms: set, out_path: Path) -> None:
    """
    Extract and save the raw promoter market-buy rows for *candidate_syms*
    from the scrape CSV to *out_path*.

    Columns saved: Symbol, Company Name, Name of Person, Category of Person,
    Securities Acquired/Disposed (No.), Securities Acquired/Disposed (Value),
    Securities Held Post (%), Date From, Date To, Details URL.

    Used by the portal to show per-symbol drill-down trade details.
    """
    _TRADE_COLS = [
        "Symbol", "Company Name",
        "Name of Person", "Category of Person",
        "Securities Acquired/Disposed (No.)",
        "Securities Acquired/Disposed (Value)",
        "Securities Held Post (%)",
        "Date From", "Date To",
        "Details URL",
    ]
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        df.columns = df.columns.str.strip()
        mask = (
            df["Symbol"].isin(candidate_syms) &
            (df["Transaction Type"].str.strip().str.lower() == "buy") &
            (df["Mode of Acquisition/Disposal"].str.strip().str.lower() == "market purchase") &
            df["Category of Person"].str.strip().str.lower().isin(PROMOTER_CATEGORIES)
        )
        trades = df.loc[mask, [c for c in _TRADE_COLS if c in df.columns]].copy()
        trades.to_csv(out_path, index=False, encoding="utf-8-sig")
        log.info("Promoter trades → %s (%d rows)", out_path, len(trades))
    except Exception as exc:
        log.warning("Could not save promoter trades: %s", exc)


# ── Phase 2 entry point ───────────────────────────────────────────────────────

def run(csv_path: Path, full_csv_path: Path) -> pd.DataFrame:
    """
    Run Phase 2.  Returns the final filtered + enriched + scored DataFrame.
    Also writes:
      *full_csv_path*        — all candidates before the holding filter
      promoter_trades.csv    — raw market-buy rows for candidates (portal drill-down)
    Prices are resolved from the Bhavcopy daily CSV — one HTTP download,
    no browser required.
    Promoter holdings and fundamental data are fetched from Screener.in
    in a single page-visit per symbol (both parsed together).
    """
    log.info("━" * 60)
    log.info("PHASE 2 — Filtering & enriching")
    log.info("━" * 60)

    agg, pledge_syms, sell_syms = _build_aggregates(csv_path)

    log.info("Pledging symbols excluded (%d): %s", len(pledge_syms), sorted(pledge_syms))
    log.info("Market-sell symbols excluded (%d): %s", len(sell_syms), sorted(sell_syms))

    agg["HasPledging"]   = agg["Symbol"].isin(pledge_syms)
    agg["HasMarketSell"] = agg["Symbol"].isin(sell_syms)
    agg_clean = agg[~agg["HasPledging"] & ~agg["HasMarketSell"]].reset_index(drop=True)
    log.info("After pledge + sell filter: %d symbols", len(agg_clean))

    symbols = agg_clean["Symbol"].tolist()

    # Save raw promoter buy rows for all candidates (portal drill-down)
    _save_promoter_trades(
        csv_path, set(symbols),
        full_csv_path.parent / TRADES_CSV_FILENAME,
    )

    log.info("Fetching prices (%d symbols) from NSE Bhavcopy …", len(symbols))
    prices = _fetch_prices(symbols)

    log.info("Computing DMA50 / DMA200 / 6M return from NSE Bhavcopy history …")
    dma_data = _fetch_dma(symbols)

    log.info("Fetching holdings + fundamentals (%d symbols) from Screener.in …", len(symbols))
    screener_data = _fetch_screener_data(symbols)

    # Merge prices, holdings and DMA data
    agg_clean = agg_clean.copy()
    agg_clean["LastPrice"]    = agg_clean["Symbol"].map(prices)
    agg_clean["PromoHolding"] = agg_clean["Symbol"].map(
        {sym: screener_data[sym]["holding"] for sym in symbols}
    )
    agg_clean["DMA50"]          = agg_clean["Symbol"].map({s: dma_data[s]["DMA50"]          for s in symbols})
    agg_clean["DMA200"]         = agg_clean["Symbol"].map({s: dma_data[s]["DMA200"]         for s in symbols})
    agg_clean["SixMonthReturn"] = agg_clean["Symbol"].map({s: dma_data[s]["SixMonthReturn"] for s in symbols})
    agg_clean["PriceDiffPct"] = (
        (agg_clean["LastPrice"] - agg_clean["AvgPrice"]) / agg_clean["AvgPrice"] * 100
    ).round(1)
    agg_clean["AbsDiffPct"] = agg_clean["PriceDiffPct"].abs()

    # Apply scoring (adds fundamentals + score columns in-place)
    agg_clean = _apply_scores(agg_clean, screener_data, dma_data)

    # Save pre-holding-filter snapshot
    full_csv_path.parent.mkdir(parents=True, exist_ok=True)
    agg_clean.to_csv(full_csv_path, index=False, encoding="utf-8-sig")
    log.info("Full enriched data → %s", full_csv_path)

    # Filter A: promoter holding ≥ threshold
    valid = agg_clean.dropna(subset=["LastPrice", "PromoHolding"])
    final = (
        valid[valid["PromoHolding"] >= MIN_PROMO_HOLDING]
        .sort_values("Score", ascending=False)   # primary sort: score descending
        .reset_index(drop=True)
    )
    log.info("After promoter holding ≥%.0f%% filter: %d symbols", MIN_PROMO_HOLDING, len(final))
    return final
