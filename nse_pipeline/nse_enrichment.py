"""NSE-first enrichment helpers using the same browser-session pattern as scraper.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from .config import BROWSER_ARGS, USER_AGENT

NSE_BASE = "https://www.nseindia.com"
NSE_LANDING = (
    "https://www.nseindia.com/companies-listing/"
    "corporate-filings-insider-trading#"
)


def _browser_fetch(page: Any, path: str, params: dict[str, str]) -> Any:
    url = f"{NSE_BASE}{path}?{urlencode(params)}"
    result = page.evaluate(
        """async (url) => {
            const r = await fetch(url, {
                credentials: 'include',
                headers: {
                    'Accept': 'application/json, text/plain, */*',
                    'Referer': window.location.href
                }
            });
            return {status: r.status, text: await r.text()};
        }""",
        url,
    )
    if result["status"] >= 400:
        raise RuntimeError(f"NSE endpoint returned HTTP {result['status']}: {path}")
    try:
        return json.loads(result["text"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"NSE endpoint returned non-JSON response: {path}") from exc


def fetch_nse_snapshot(symbol: str) -> dict[str, Any]:
    """Fetch raw NSE datasets through the same browser setup as production.

    The production scraper uses Chromium with BROWSER_ARGS and a visible
    browser session because NSE rejects headless navigation in GitHub runners.
    We intentionally mirror that setup here for validation.
    """
    symbol = symbol.upper()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=BROWSER_ARGS)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        page.goto(NSE_LANDING, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector('a[data-name="InsiderTrading"]', timeout=60_000)
        page.wait_for_timeout(2000)

        snapshot: dict[str, Any] = {
            "symbol": symbol,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": "NSE India",
            "session_cookies": len(context.cookies()),
        }

        # NSE's legacy financial-results endpoints stop at the pre-Integrated
        # Filing data. Since March 2025, financial results are published under
        # Integrated Filing - Financials. Keep the legacy calls for comparison,
        # but make the current first-party source explicit.
        calls = {
            "shareholding": (
                "/api/corporate-share-holdings-master",
                {"index": "equities", "symbol": symbol},
            ),
            "integrated_financials": (
                "/api/integrated-filing-results",
                {
                    "index": "equities",
                    "symbol": symbol,
                    "type": "Integrated Filing- Financials",
                    "page": "1",
                    "size": "50",
                },
            ),
            "financial_results_legacy": (
                "/api/corporates-financial-results",
                {"index": "equities", "period": "Quarterly", "symbol": symbol},
            ),
            "results_comparison_legacy": (
                "/api/results-comparision",
                {"symbol": symbol},
            ),
            "quote": (
                "/api/quote-equity",
                {"symbol": symbol},
            ),
        }

        for name, (path, params) in calls.items():
            try:
                snapshot[name] = {"status": "ok", "data": _browser_fetch(page, path, params)}
            except Exception as exc:
                snapshot[name] = {"status": "error", "error": str(exc)}

        browser.close()
        return snapshot
