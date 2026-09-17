"""Fallback historical price source for the RYB research dataset.

NSE's legacy daily equity-history endpoints/files are not consistently
available for historical dates. This module is intentionally isolated from
core scoring and is used only when the primary NSE research price dataset is
empty.
"""
from __future__ import annotations

import csv
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from .config import USER_AGENT

log = logging.getLogger(__name__)

_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS"


def _fetch_symbol(session: requests.Session, symbol: str, start: date, end: date) -> list[dict]:
    period1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    url = _YAHOO_CHART_URL.format(symbol=quote(symbol, safe=""))
    try:
        response = session.get(
            url,
            params={
                "period1": period1,
                "period2": period2,
                "interval": "1d",
                "events": "history",
                "includeAdjustedClose": "true",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("chart", {}).get("result") or []
        if not result:
            return []
        chart = result[0]
        timestamps = chart.get("timestamp") or []
        quote_rows = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote_rows.get("open") or []
        highs = quote_rows.get("high") or []
        lows = quote_rows.get("low") or []
        closes = quote_rows.get("close") or []
        volumes = quote_rows.get("volume") or []
        rows = []
        for idx, timestamp in enumerate(timestamps):
            close = closes[idx] if idx < len(closes) else None
            if close is None:
                continue
            day = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
            rows.append({
                "Date": day,
                "Symbol": symbol,
                "Open": opens[idx] if idx < len(opens) else None,
                "High": highs[idx] if idx < len(highs) else None,
                "Low": lows[idx] if idx < len(lows) else None,
                "Close": close,
                "Volume": volumes[idx] if idx < len(volumes) else None,
                "TurnoverCr": None,
            })
        return rows
    except Exception as exc:
        log.warning("Yahoo historical price fallback failed for %s: %s", symbol, exc)
        return []


def build_yahoo_price_history(
    symbols: list[str],
    as_of_date: date,
    out_path: Path,
    lookback_days: int = 380,
) -> int:
    """Write daily OHLCV history when the primary NSE dataset is unavailable."""
    wanted = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    start = as_of_date - timedelta(days=max(1, lookback_days) - 1)
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finance.yahoo.com/",
    })

    rows: list[dict] = []
    successful_symbols = 0
    for symbol in wanted:
        fetched = _fetch_symbol(session, symbol, start, as_of_date)
        if fetched:
            successful_symbols += 1
            rows.extend(fetched)
        time.sleep(0.08)

    columns = ["Date", "Symbol", "Open", "High", "Low", "Close", "Volume", "TurnoverCr"]
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        result = result.drop_duplicates(["Date", "Symbol"], keep="last").sort_values(["Symbol", "Date"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    log.info(
        "Yahoo price-history fallback → %s (%d rows, %d/%d symbols)",
        out_path,
        len(result),
        successful_symbols,
        len(wanted),
    )
    return len(result)
