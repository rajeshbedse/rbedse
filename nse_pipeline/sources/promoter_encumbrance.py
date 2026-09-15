"""Current promoter encumbrance parser from the NSE stock quote page.

Acquisition is intentionally browser/DOM based: open the rendered NSE company
page, expand the Promoter Encumbrance Details section, and read the values that
are rendered on screen. No NSE JSON/API endpoint is used here.
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..browser.stock_page import NSEStockPage

log = logging.getLogger(__name__)

# Keep the canonical Regulation 31 snapshot schema stable while changing only
# the acquisition mechanism. Fields not exposed by the stock-page summary are
# intentionally null rather than estimated from unrelated data.
COLUMNS = [
    "Symbol", "Company Name", "TotalIssuedShares", "PromoterHoldingShares",
    "PromoterHoldingPctTotal", "PromoterEncumberedShares",
    "PromoterEncumberedPctPromoter", "PromoterEncumberedPctTotal",
    "PromoterEncumberedValueCr", "PromoterDisclosure", "DepositoryPledgedShares",
    "TotalDematShares", "DepositoryPledgePctDemat", "DepositoryPledgedValueCr",
    "SourceURL", "RetrievedAt", "Status",
]

_PERCENT = r"(?:\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?)"


def _number_tokens(text: str) -> list[float]:
    values = []
    for token in re.findall(_PERCENT + r"\s*%?", text or ""):
        try:
            values.append(float(token.replace(",", "").replace("%", "")))
        except ValueError:
            continue
    return values


def _pct_after_label(text: str, *labels: str) -> float | None:
    compact = re.sub(r"\s+", " ", text or "").strip()
    for label in labels:
        pattern = re.compile(
            re.escape(label) + r"[^\d]{0,180}(" + _PERCENT + r")\s*%?",
            re.I,
        )
        match = pattern.search(compact)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def _parse_table(tables: list[list[list[str]]]) -> tuple[float | None, float | None, float | None]:
    """Parse the rendered three-column summary table.

    NSE currently renders the three labels in one header row and the three
    percentages in the following row (as visible in the stock-page UI). Do not
    assume labels and values occupy the same row.
    """
    for table in tables:
        if len(table) < 2:
            continue

        for header_index, header in enumerate(table[:-1]):
            if len(header) < 3:
                continue
            normalized = [re.sub(r"\s+", " ", cell).strip().lower() for cell in header]
            if not any("promoter" in cell for cell in normalized):
                continue
            if not any("pledged" in cell or "encumbered" in cell for cell in normalized):
                continue

            # Usually the immediate next row contains the values. If the table
            # contains a spacer/header row, inspect the next few rows instead.
            for data_row in table[header_index + 1 : header_index + 4]:
                if len(data_row) < 3:
                    continue
                values = [_number_tokens(cell) for cell in data_row[:3]]
                if all(len(cell_values) == 1 for cell_values in values):
                    return values[0][0], values[1][0], values[2][0]

    return None, None, None


def _parse_percentages(text: str, tables: list[list[list[str]]]) -> tuple[float | None, float | None, float | None]:
    """Parse the rendered section, with table structure taking priority."""
    table_values = _parse_table(tables)
    if all(value is not None for value in table_values):
        return table_values

    # Text fallback handles minor wording changes while still reading only the
    # rendered section captured from the company page.
    promoter_total = _pct_after_label(
        text,
        "% of shareholding of promoter and promoter group to total shareholding",
        "promoter shareholding to total shareholding",
        "promoter shareholding to total",
    )
    enc_total = _pct_after_label(
        text,
        "% of shares pledged or otherwise encumbered by promoter and promoter group to total shareholding",
        "shares pledged/otherwise encumbered by promoter/promoter group to total shareholding",
        "encumbered by promoter/promoter group to total shareholding",
    )
    enc_promoter = _pct_after_label(
        text,
        "% of shares pledged or otherwise encumbered by promoter and promoter group to total shareholding of promoter and promoter group",
        "shares pledged/otherwise encumbered to promoter/promoter group",
        "encumbered to promoter/promoter group",
    )
    return promoter_total, enc_total, enc_promoter


def fetch_symbol(stock_page: NSEStockPage, symbol: str) -> dict:
    symbol = symbol.strip().upper()
    retrieved = datetime.now(timezone.utc).isoformat()
    try:
        stock_page.symbol = symbol
        stock_page.open()
        clicked = stock_page.navigate("promoter_encumbrance")
        if not clicked:
            return {
                "Symbol": symbol, "Company Name": "", "SourceURL": stock_page.url,
                "RetrievedAt": retrieved, "Status": "NO_NSE_NAVIGATION",
            }

        if not stock_page.wait_for_heading("promoter_encumbrance"):
            return {
                "Symbol": symbol, "Company Name": "", "SourceURL": stock_page.url,
                "RetrievedAt": retrieved, "Status": "NO_NSE_SECTION",
            }

        text = stock_page.extract_text("promoter_encumbrance")
        tables = stock_page.extract_tables("promoter_encumbrance")
        promoter_total, enc_total, enc_promoter = _parse_percentages(text, tables)

        if promoter_total is None and enc_total is None and enc_promoter is None:
            return {
                "Symbol": symbol, "Company Name": "", "SourceURL": stock_page.url,
                "RetrievedAt": retrieved, "Status": "NO_NSE_DATA",
            }

        return {
            "Symbol": symbol,
            "Company Name": "",
            "TotalIssuedShares": None,
            "PromoterHoldingShares": None,
            "PromoterHoldingPctTotal": promoter_total,
            "PromoterEncumberedShares": None,
            "PromoterEncumberedPctPromoter": enc_promoter,
            "PromoterEncumberedPctTotal": enc_total,
            "PromoterEncumberedValueCr": None,
            "PromoterDisclosure": "",
            "DepositoryPledgedShares": None,
            "TotalDematShares": None,
            "DepositoryPledgePctDemat": None,
            "DepositoryPledgedValueCr": None,
            "SourceURL": stock_page.url,
            "RetrievedAt": retrieved,
            "Status": "OK",
        }
    except Exception as exc:
        log.warning("Promoter encumbrance fetch failed for %s: %s", symbol, exc)
        return {
            "Symbol": symbol, "Company Name": "", "SourceURL": stock_page.url,
            "RetrievedAt": retrieved, "Status": f"ERROR: {type(exc).__name__}",
        }


def run(browser, symbols: list[str], out_path: Path) -> int:
    """Scrape the rendered NSE stock page sequentially using one browser context.

    Playwright's synchronous objects are not thread-safe, so avoid sharing a
    browser instance across worker threads. Sequential page reuse is also the
    most reliable foundation for adding more rendered stock-page sections.
    """
    wanted = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    records: list[dict] = []
    context = browser.new_context()
    page = context.new_page()
    stock_page = NSEStockPage(page, "")
    try:
        for completed, symbol in enumerate(wanted, start=1):
            records.append(fetch_symbol(stock_page, symbol))
            if completed % 10 == 0 or completed == len(wanted):
                log.info("  NSE promoter encumbrance … %d/%d symbols", completed, len(wanted))
    finally:
        page.close()
        context.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    ok = sum(1 for row in records if row.get("Status") == "OK")
    log.info("NSE promoter encumbrance → %s (%d/%d symbols with section data)", out_path, ok, len(records))
    return len(records)
