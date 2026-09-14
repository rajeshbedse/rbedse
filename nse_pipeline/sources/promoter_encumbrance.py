"""Current promoter encumbrance parser from the NSE stock quote page."""
from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..browser.stock_page import NSEStockPage

log = logging.getLogger(__name__)

COLUMNS = [
    "Symbol", "Company Name", "PromoterHoldingPctTotal",
    "PromoterEncumberedPctTotal", "PromoterEncumberedPctPromoter",
    "PromoterEncumberedValueCr", "SourceURL", "RetrievedAt", "Status",
]


_PERCENT = r"(?:\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?)"


def _pct_after_label(text: str, *labels: str) -> float | None:
    compact = re.sub(r"\s+", " ", text or "").strip()
    for label in labels:
        pattern = re.compile(re.escape(label) + r"[^\d]{0,160}(" + _PERCENT + r")\s*%?", re.I)
        match = pattern.search(compact)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def _parse_percentages(text: str) -> tuple[float | None, float | None, float | None]:
    promoter_total = _pct_after_label(
        text,
        "promoter shareholding to total shareholding",
        "promoter shareholding to total",
    )
    enc_total = _pct_after_label(
        text,
        "shares pledged/otherwise encumbered by promoter/promoter group to total shareholding",
        "shares pledged / otherwise encumbered by promoter / promoter group to total shareholding",
        "encumbered by promoter/promoter group to total shareholding",
    )
    enc_promoter = _pct_after_label(
        text,
        "shares pledged/otherwise encumbered to promoter/promoter group",
        "shares pledged / otherwise encumbered to promoter / promoter group",
        "encumbered to promoter/promoter group",
    )
    return promoter_total, enc_total, enc_promoter


def _parse_table_fallback(tables: list[list[list[str]]]) -> tuple[float | None, float | None, float | None]:
    """Fallback for minor label/markup changes: use the first section row with 3+ percentages."""
    for table in tables:
        for row in table:
            joined = " | ".join(row)
            low = joined.lower()
            if "promoter" not in low or "encumber" not in low and "pledged" not in low:
                continue
            values = []
            for token in re.findall(_PERCENT + r"\s*%?", joined):
                try:
                    values.append(float(token.replace(",", "").replace("%", "")))
                except ValueError:
                    continue
            if len(values) >= 3:
                return values[0], values[1], values[2]
    return None, None, None


def fetch_symbol(stock_page: NSEStockPage, symbol: str) -> dict:
    symbol = symbol.strip().upper()
    retrieved = datetime.now(timezone.utc).isoformat()
    try:
        stock_page.open()
        stock_page.navigate("promoter_encumbrance")
        stock_page.wait_for_heading("promoter_encumbrance")
        text = stock_page.extract_text("promoter_encumbrance")
        tables = stock_page.extract_tables("promoter_encumbrance")
        promoter_total, enc_total, enc_promoter = _parse_percentages(text)
        if promoter_total is None or enc_total is None or enc_promoter is None:
            fallback = _parse_table_fallback(tables)
            promoter_total = promoter_total if promoter_total is not None else fallback[0]
            enc_total = enc_total if enc_total is not None else fallback[1]
            enc_promoter = enc_promoter if enc_promoter is not None else fallback[2]

        if promoter_total is None and enc_total is None and enc_promoter is None:
            return {
                "Symbol": symbol,
                "Company Name": "",
                "SourceURL": stock_page.url,
                "RetrievedAt": retrieved,
                "Status": "NO_NSE_SECTION",
            }

        # The stock quote section does not expose a separate current value field
        # in the visible encumbrance summary. Keep it null rather than deriving a
        # value from a potentially different closing-price timestamp.
        return {
            "Symbol": symbol,
            "Company Name": "",
            "PromoterHoldingPctTotal": promoter_total,
            "PromoterEncumberedPctTotal": enc_total,
            "PromoterEncumberedPctPromoter": enc_promoter,
            "PromoterEncumberedValueCr": None,
            "SourceURL": stock_page.url,
            "RetrievedAt": retrieved,
            "Status": "OK",
        }
    except Exception as exc:
        log.warning("Promoter encumbrance fetch failed for %s: %s", symbol, exc)
        return {
            "Symbol": symbol,
            "Company Name": "",
            "SourceURL": stock_page.url,
            "RetrievedAt": retrieved,
            "Status": f"ERROR: {type(exc).__name__}",
        }


def run(browser_context, symbols: list[str], out_path: Path) -> int:
    wanted = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    page = browser_context.new_page()
    stock_page = NSEStockPage(page, "")
    records = []
    try:
        for index, symbol in enumerate(wanted, start=1):
            stock_page.symbol = symbol
            records.append(fetch_symbol(stock_page, symbol))
            if index % 10 == 0 or index == len(wanted):
                log.info("  NSE promoter encumbrance … %d/%d symbols", index, len(wanted))
    finally:
        page.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    ok = sum(1 for row in records if row.get("Status") == "OK")
    log.info("NSE promoter encumbrance → %s (%d/%d symbols with section data)", out_path, ok, len(records))
    return len(records)
