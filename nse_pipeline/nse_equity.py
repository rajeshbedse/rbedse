"""NSE official equity-history client.

Uses the public NSE report-detail/eq_security application and its backing
historical-security API. This replaces direct nsearchives Bhavcopy access for
price/volume history used by the scan.
"""
from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.nseindia.com"
REPORT_URL = f"{BASE_URL}/report-detail/eq_security"
HISTORY_URL = f"{BASE_URL}/api/historicalOR/generateSecurityWiseHistoricalData"
ARCHIVE_API_URL = f"{BASE_URL}/api/historical/securityArchives"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0 Safari/537.36",
    "Accept": "text/csv,application/csv,application/json,text/plain,*/*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Referer": REPORT_URL,
    "X-Requested-With": "XMLHttpRequest",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(REPORT_URL, timeout=20)
    r.raise_for_status()
    return s


def _parse_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "NA", "null", "None"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalise_frame(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return df
    df.columns = [str(c).strip() for c in df.columns]
    aliases = {
        "DATE": ["DATE", "Date", "CH_TIMESTAMP", "mTIMESTAMP"],
        "CLOSE": ["CLOSE", "Close", "CH_CLOSING_PRICE", "ClsPric"],
        "PREV_CLOSE": ["PREV. CLOSE", "PREV_CLOSE", "CH_PREVIOUS_CLS_PRICE", "Prev Close"],
        "OPEN": ["OPEN", "Open", "CH_OPENING_PRICE"],
        "HIGH": ["HIGH", "High", "CH_TRADE_HIGH_PRICE"],
        "LOW": ["LOW", "Low", "CH_TRADE_LOW_PRICE"],
        "LTP": ["LTP", "Last", "CH_LAST_TRADED_PRICE"],
        "VWAP": ["VWAP", "Avg Price", "Average Price"],
        "VOLUME": ["VOLUME", "Volume", "CH_TOT_TRADED_QTY", "TTL_TRD_QNTY"],
        "VALUE": ["VALUE", "Turnover", "CH_TOT_TRADED_VAL", "TURNOVER_LACS"],
        "NO_OF_TRADES": ["NO OF TRADES", "NO_OF_TRADES", "CH_TOTAL_TRADES"],
        "52W_H": ["52W H", "52W_H", "52 Week High", "52WeekHigh", "52W High"],
        "52W_L": ["52W L", "52W_L", "52 Week Low", "52WeekLow", "52W Low"],
    }
    out = pd.DataFrame(index=df.index)
    for target, names in aliases.items():
        source = next((name for name in names if name in df.columns), None)
        out[target] = df[source] if source else None
    out["DATE"] = pd.to_datetime(out["DATE"], errors="coerce", dayfirst=True)
    for col in out.columns:
        if col != "DATE":
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["SYMBOL"] = symbol.upper()
    out = out.dropna(subset=["DATE"]).sort_values("DATE").drop_duplicates("DATE")
    return out.reset_index(drop=True)


def _request_csv(session: requests.Session, symbol: str, start: date, end: date) -> pd.DataFrame:
    params = {
        "from": start.strftime("%d-%m-%Y"),
        "to": end.strftime("%d-%m-%Y"),
        "symbol": symbol,
        "type": "priceVolumeDeliverable",
        "series": "EQ",
        "csv": "true",
    }
    response = session.get(HISTORY_URL, params=params, timeout=30)
    if response.status_code == 200 and response.text.strip():
        return pd.read_csv(io.StringIO(response.text))
    params.pop("type", None)
    params["dataType"] = "priceVolumeDeliverable"
    response = session.get(ARCHIVE_API_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return pd.DataFrame(payload.get("data", []))


def fetch_history(symbol: str, start: date, end: date, session: requests.Session | None = None) -> pd.DataFrame:
    own_session = session is None
    s = session or _session()
    try:
        return _normalise_frame(_request_csv(s, symbol.upper(), start, end), symbol)
    finally:
        if own_session:
            s.close()


def fetch_current_prices(symbols: list[str], as_of_date: date | None = None) -> dict[str, dict[str, float | None]]:
    target = as_of_date or date.today()
    start = target - timedelta(days=7)
    result: dict[str, dict[str, float | None]] = {s: {"LastPrice": None} for s in symbols}

    def worker(sym: str):
        try:
            with _session() as s:
                df = fetch_history(sym, start, target, s)
                if df.empty:
                    return sym, None
                row = df.sort_values("DATE").iloc[-1]
                return sym, _parse_number(row.get("CLOSE"))
        except Exception as exc:
            log.warning("  NSE current price failed for %-15s: %s", sym, exc)
            return sym, None

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(symbols)))) as pool:
        futures = [pool.submit(worker, sym) for sym in symbols]
        for future in as_completed(futures):
            sym, close = future.result()
            result[sym] = {"LastPrice": close}
            if close is not None:
                log.info("  price %-15s = %s (NSE eq_security)", sym, close)
    return result


def fetch_52_week_prices(symbols: list[str], as_of_date: date | None = None) -> dict[str, dict[str, float | None]]:
    target = as_of_date or date.today()
    start = target - timedelta(days=370)
    result: dict[str, dict[str, float | None]] = {s: {} for s in symbols}

    def worker(sym: str):
        try:
            with _session() as s:
                df = fetch_history(sym, start, target, s)
                if df.empty:
                    return sym, {}
                row = df.sort_values("DATE").iloc[-1]
                high = _parse_number(row.get("52W_H"))
                low = _parse_number(row.get("52W_L"))
                if high is None:
                    high = float(df["HIGH"].dropna().tail(252).max()) if df["HIGH"].notna().any() else None
                if low is None:
                    low = float(df["LOW"].dropna().tail(252).min()) if df["LOW"].notna().any() else None
                return sym, {"52WeekHigh": high, "52WeekLow": low}
        except Exception as exc:
            log.warning("  NSE 52-week history failed for %-15s: %s", sym, exc)
            return sym, {}

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(symbols)))) as pool:
        futures = [pool.submit(worker, sym) for sym in symbols]
        for future in as_completed(futures):
            sym, values = future.result()
            result[sym] = values
    return result


def fetch_dma(symbols: list[str], lookback_days: int = 380, as_of_date: date | None = None) -> dict[str, dict[str, float | None]]:
    target = as_of_date or date.today()
    start = target - timedelta(days=lookback_days)
    output: dict[str, dict[str, float | None]] = {}

    def worker(sym: str):
        try:
            with _session() as s:
                df = fetch_history(sym, start, target, s)
                closes = df["CLOSE"].dropna().tolist() if not df.empty else []
                recent = list(reversed(closes))
                dma50 = round(sum(recent[:50]) / 50, 2) if len(recent) >= 50 else None
                dma200 = round(sum(recent[:200]) / 200, 2) if len(recent) >= 200 else None
                six_m = None
                if len(recent) > 60:
                    p_now = recent[0]
                    p_then = recent[min(126, len(recent) - 1)]
                    if p_then:
                        six_m = round((p_now / p_then - 1) * 100, 1)
                return sym, {"DMA50": dma50, "DMA200": dma200, "SixMonthReturn": six_m}
        except Exception as exc:
            log.warning("  NSE DMA history failed for %-15s: %s", sym, exc)
            return sym, {"DMA50": None, "DMA200": None, "SixMonthReturn": None}

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(symbols)))) as pool:
        futures = [pool.submit(worker, sym) for sym in symbols]
        for future in as_completed(futures):
            sym, values = future.result()
            output[sym] = values
    return output
