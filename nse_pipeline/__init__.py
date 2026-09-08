"""NSE Insider Trading Weekly Pipeline."""
__version__ = "1.2.2"


# Backward-compatibility guard for Bhavcopy price maps.
# Older pipeline revisions returned ``{symbol: float}``, while the current
# analyzer expects ``{symbol: {"LastPrice": float}}``.  Normalise either
# shape at the module boundary so a stale/alternate price provider cannot
# crash Phase 2 with ``'float' object has no attribute 'get'``.
from . import analyzer as _analyzer

_original_download_bhavcopy = _analyzer._download_bhavcopy


def _normalised_download_bhavcopy(*args, **kwargs):
    data = _original_download_bhavcopy(*args, **kwargs)
    if not data:
        return data
    return {
        symbol: value if isinstance(value, dict) else {"LastPrice": value}
        for symbol, value in data.items()
    }


_analyzer._download_bhavcopy = _normalised_download_bhavcopy


# 52-week NSE report guard/diagnostics.
# Keep this on the same market-data path as Bhavcopy: one requests.Session,
# direct nsearchives URL, bounded trading-day lookback, CSV parsing in memory,
# then the existing analyzer maps the result to the requested symbols.
#
# We deliberately do NOT use NSE's daily-reports discovery API here. The
# daily archive is the source we expect the pipeline to consume, just like
# Bhavcopy, and these diagnostics make failures visible in the pipeline log.
import csv as _csv
import logging as _logging
import requests as _requests
from datetime import date as _date, timedelta as _timedelta

_log = _logging.getLogger(__name__)
_WEEK52_ARCHIVE_BASE = "https://nsearchives.nseindia.com/content/equities/CM_52_wk_High_low_{date}.csv"
_WEEK52_ARCHIVE_HEADERS = {
    "User-Agent": _analyzer.USER_AGENT,
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
_WEEK52_REQUIRED_HIGH = ("Adjusted_52_Week_High", "Adjusted 52_Week_High")
_WEEK52_REQUIRED_LOW = ("Adjusted_52_Week_Low", "Adjusted 52_Week_Low")


def _parse_52_week_archive(text: str):
    """Parse one NSE 52-week archive CSV using the same in-memory pattern as Bhavcopy."""
    lines = text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if any(k in line for k in _WEEK52_REQUIRED_HIGH)),
        None,
    )
    if header_idx is None:
        return {}, None
    rows = _csv.DictReader(lines[header_idx:])
    result = {}
    total_rows = 0
    valid_high = 0
    valid_low = 0
    for row in rows:
        total_rows += 1
        sym = (row.get("SYMBOL") or row.get("Symbol") or row.get("TckrSymb") or "").strip()
        if not sym:
            continue

        def _num(*keys):
            for key in keys:
                raw = row.get(key)
                if raw not in (None, "", "-", "NA"):
                    try:
                        return float(str(raw).replace(",", "").strip())
                    except (ValueError, TypeError):
                        pass
            return None

        high = _num(*_WEEK52_REQUIRED_HIGH)
        low = _num(*_WEEK52_REQUIRED_LOW)
        if high is not None:
            valid_high += 1
        if low is not None:
            valid_low += 1
        result[sym] = {"52WeekHigh": high, "52WeekLow": low}
    return result, {
        "header_line": header_idx + 1,
        "rows": total_rows,
        "symbols": len(result),
        "valid_high": valid_high,
        "valid_low": valid_low,
    }


def _download_52_week_archive(max_lookback=5, as_of_date=None):
    session = _requests.Session()
    session.headers.update(_WEEK52_ARCHIVE_HEADERS)
    today = as_of_date or _date.today()
    attempted = []

    for delta in range(max_lookback + 1):
        d = today - _timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%d%m%Y")
        url = _WEEK52_ARCHIVE_BASE.format(date=ds)
        attempted.append(ds)
        try:
            resp = session.get(url, timeout=20)
            _log.info("  52W archive probe %s — HTTP %d, %d bytes", ds, resp.status_code, len(resp.content))
            if resp.status_code != 200:
                continue
            result, stats = _parse_52_week_archive(resp.text)
            if not result:
                _log.warning("  52W archive %s returned no parseable rows (header line=%s)", ds, stats.get("header_line") if stats else "not found")
                continue

            _log.info(
                "  52W archive loaded for %s — %d symbols / %d rows | valid High=%d Low=%d | header line=%d",
                d.strftime("%Y-%m-%d"), stats["symbols"], stats["rows"],
                stats["valid_high"], stats["valid_low"], stats["header_line"],
            )
            if stats["valid_high"] < stats["symbols"] or stats["valid_low"] < stats["symbols"]:
                _log.warning("  52W archive %s has missing High/Low values for some symbols", ds)
            return result
        except Exception as exc:
            _log.warning("  52W archive fetch failed for %s: %s", ds, exc)

    _log.warning("  52W archive: no usable file found for dates %s", attempted)
    return None


_original_download_52_week_report = _analyzer._download_52_week_report
_original_fetch_52_week_prices = _analyzer._fetch_52_week_prices


def _download_52_week_report_from_archive(*args, **kwargs):
    # Ignore the previous API-based implementation and use the archive path,
    # matching the Bhavcopy fetch architecture exactly.
    return _download_52_week_archive(*args, **kwargs)


def _fetch_52_week_prices_with_diagnostics(symbols, *args, **kwargs):
    data = _original_fetch_52_week_prices(symbols, *args, **kwargs)
    matched = sum(1 for sym in symbols if data.get(sym, {}).get("52WeekHigh") is not None and data.get(sym, {}).get("52WeekLow") is not None)
    _log.info("  52W symbol coverage — requested=%d matched High+Low=%d missing=%d", len(symbols), matched, len(symbols) - matched)
    for sym in symbols[:5]:
        item = data.get(sym, {})
        _log.info("  52W sample %-15s High=%s Low=%s", sym, item.get("52WeekHigh"), item.get("52WeekLow"))
    missing = [sym for sym in symbols if data.get(sym, {}).get("52WeekHigh") is None or data.get(sym, {}).get("52WeekLow") is None]
    if missing:
        _log.warning("  52W missing sample (%d total): %s", len(missing), ", ".join(missing[:10]))
    return data


_analyzer._download_52_week_report = _download_52_week_report_from_archive
_analyzer._fetch_52_week_prices = _fetch_52_week_prices_with_diagnostics
