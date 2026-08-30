"""NSE replacement for the legacy Screener enrichment contract.

The analyzer expects ``{symbol: {holding, fundamentals}}``.  This adapter
keeps that contract unchanged while sourcing both promoter holding and
fundamentals from NSE, allowing the scoring engine to be migrated without
rewriting its scoring rules in the same change.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from playwright.sync_api import sync_playwright

from .config import BROWSER_ARGS, HOLDING_WORKERS, USER_AGENT
from .nse_enrichment import _browser_fetch, NSE_LANDING
from .nse_financials import normalize_symbol
from .nse_normalization import promoter_holding_pct

log = logging.getLogger(__name__)


def _warm_page(page: Any) -> None:
    page.goto(NSE_LANDING, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_selector('a[data-name="InsiderTrading"]', timeout=60_000)
    page.wait_for_timeout(1500)


def _worker(symbols: list[str], worker_id: int, total: int, counter: list[int], lock: threading.Lock) -> dict[str, dict]:
    results: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=BROWSER_ARGS)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        try:
            _warm_page(page)
            for symbol in symbols:
                symbol = symbol.upper()
                holding = None
                fundamentals: dict[str, Any] = {}
                try:
                    shareholding = _browser_fetch(
                        page,
                        "/api/corporate-share-holdings-master",
                        {"index": "equities", "symbol": symbol},
                    )
                    holding = promoter_holding_pct(shareholding)
                except Exception as exc:
                    log.warning("[NSE-W%d] %s shareholding failed: %s", worker_id, symbol, exc)

                try:
                    quote = _browser_fetch(
                        page,
                        "/api/quote-equity",
                        {"symbol": symbol},
                    )
                except Exception as exc:
                    log.warning("[NSE-W%d] %s quote failed: %s", worker_id, symbol, exc)
                    quote = None

                try:
                    fundamentals = normalize_symbol(page, symbol, quote=quote)
                except Exception as exc:
                    log.warning("[NSE-W%d] %s financials failed: %s", worker_id, symbol, exc)
                    fundamentals = {
                        "NSEFinancialSource": "Integrated Filing/XBRL",
                        "FinancialDataCurrent": False,
                    }

                results[symbol] = {
                    "holding": holding,
                    "fundamentals": fundamentals,
                }

                with lock:
                    counter[0] += 1
                    done = counter[0]
                if done % max(1, total // 10) == 0 or done == total:
                    log.info("  NSE enrichment … %d/%d (%d%%)", done, total, done * 100 // total)
        finally:
            browser.close()
    return results


def fetch_nse_data(symbols: list[str]) -> dict[str, dict]:
    """Fetch NSE promoter holding + fundamentals using the analyzer's contract."""
    if not symbols:
        return {}
    workers = min(HOLDING_WORKERS, len(symbols))
    slices = [symbols[i::workers] for i in range(workers)]
    counter = [0]
    lock = threading.Lock()
    combined: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_worker, sl, wid, len(symbols), counter, lock)
            for wid, sl in enumerate(slices)
        ]
        for future in futures:
            combined.update(future.result())
    return combined
