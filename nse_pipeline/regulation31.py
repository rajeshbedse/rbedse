"""NSE Regulation 31 promoter-encumbrance dataset.

The NSE Pledged Data page exposes the current promoter encumbrance view. Its
column for promoter shares encumbered is sourced from the SEBI Regulation 31
filing, while the depository pledge columns are updated from NSDL/CDSL.

This module deliberately keeps current outstanding encumbrance separate from
transaction-level pledge creation/release/invocation activity in the insider
trading snapshot. A release is therefore not treated as a new pledge risk.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

log = logging.getLogger(__name__)
NSE_URL = "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data"

COLUMNS = [
    "Symbol", "Company Name", "TotalIssuedShares", "PromoterHoldingShares",
    "PromoterHoldingPctTotal", "PromoterEncumberedShares",
    "PromoterEncumberedPctPromoter", "PromoterEncumberedPctTotal",
    "PromoterEncumberedValueCr", "PromoterDisclosure", "DepositoryPledgedShares",
    "TotalDematShares", "DepositoryPledgePctDemat", "DepositoryPledgedValueCr",
    "SourceURL", "RetrievedAt", "Status",
]


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "—", "NA", "N/A"}:
        return None
    try:
        return float(text.replace("%", ""))
    except ValueError:
        return None


def _extract_rows(page) -> list[list[str]]:
    """Find the Pledged Data table without depending on generated NSE IDs."""
    return page.evaluate(
        """
        () => {
          const tables = Array.from(document.querySelectorAll('table'));
          const table = tables.find(t => {
            const text = (t.innerText || '').toLowerCase();
            return text.includes('promoter shares encumbered') &&
                   text.includes('shares pledged in the depository');
          });
          if (!table) return [];
          return Array.from(table.querySelectorAll('tbody tr')).map(tr =>
            Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim())
          ).filter(row => row.length >= 10);
        }
        """
    )


def _find_symbol_row(rows: list[list[str]], symbol: str) -> list[str] | None:
    target = symbol.strip().upper()
    for row in rows:
        if row and (target == row[0].strip().upper() or target in row[0].upper().split()):
            return row
    # The NSE symbol query normally filters the table to the requested company.
    # If the company cell contains the company name rather than the symbol,
    # accept the sole data row rather than discarding valid filtered data.
    if len(rows) == 1 and len(rows[0]) >= 10:
        return rows[0]
    return None


def _parse_row(row: list[str], symbol: str, source_url: str) -> dict:
    # Current NSE Pledged Data table has 14 data columns. Positions follow the
    # published table order and are intentionally independent of CSS classes.
    values = (row + [""] * 14)[:14]
    return {
        "Symbol": symbol.upper(), "Company Name": values[0],
        "TotalIssuedShares": _num(values[1]), "PromoterHoldingShares": _num(values[2]),
        "PromoterHoldingPctTotal": _num(values[3]), "PromoterEncumberedShares": _num(values[5]),
        "PromoterEncumberedPctPromoter": _num(values[6]), "PromoterEncumberedPctTotal": _num(values[7]),
        "PromoterEncumberedValueCr": _num(values[8]), "PromoterDisclosure": values[9],
        "DepositoryPledgedShares": _num(values[10]), "TotalDematShares": _num(values[11]),
        "DepositoryPledgePctDemat": _num(values[12]), "DepositoryPledgedValueCr": _num(values[13]),
        "SourceURL": source_url, "RetrievedAt": datetime.now(timezone.utc).isoformat(), "Status": "OK",
    }


def fetch_symbol(page, symbol: str) -> dict:
    symbol = symbol.strip().upper()
    url = f"{NSE_URL}?symbol={symbol}&tabIndex=equity"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        try:
            page.wait_for_function(
                """
                () => Array.from(document.querySelectorAll('table')).some(t => {
                  const text = (t.innerText || '').toLowerCase();
                  return text.includes('promoter shares encumbered') &&
                         text.includes('shares pledged in the depository');
                })
                """,
                timeout=20_000,
            )
        except PlaywrightTimeoutError:
            pass
        rows = _extract_rows(page)
        row = _find_symbol_row(rows, symbol)
        if row:
            return _parse_row(row, symbol, url)
        return {"Symbol": symbol, "Company Name": "", "SourceURL": url,
                "RetrievedAt": datetime.now(timezone.utc).isoformat(), "Status": "NO_NSE_ROW"}
    except Exception as exc:
        log.warning("Regulation 31 pledge fetch failed for %s: %s", symbol, exc)
        return {"Symbol": symbol, "Company Name": "", "SourceURL": url,
                "RetrievedAt": datetime.now(timezone.utc).isoformat(), "Status": f"ERROR: {type(exc).__name__}"}


def run(browser_context, symbols: list[str], out_path: Path) -> int:
    """Fetch current NSE promoter encumbrance for the supplied symbols."""
    wanted = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    page = browser_context.new_page()
    records = []
    try:
        for index, symbol in enumerate(wanted, start=1):
            records.append(fetch_symbol(page, symbol))
            if index % 10 == 0 or index == len(wanted):
                log.info("  Regulation 31 pledge data … %d/%d symbols", index, len(wanted))
    finally:
        page.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader(); writer.writerows(records)
    ok = sum(1 for r in records if r.get("Status") == "OK")
    log.info("Regulation 31 pledge data → %s (%d/%d symbols with NSE rows)", out_path, ok, len(records))
    return len(records)
