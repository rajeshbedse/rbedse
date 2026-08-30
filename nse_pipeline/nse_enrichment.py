"""NSE-first enrichment helpers using the same browser-session pattern as scraper.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import sync_playwright

NSE_BASE = "https://www.nseindia.com"


def _browser_fetch(page: Any, path: str, params: dict[str, str]) -> Any:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{NSE_BASE}{path}?{query}"
    result = page.evaluate(
        """async (url) => {
            const r = await fetch(url, {
                credentials: 'include',
                headers: { 'Accept': 'application/json, text/plain, */*' }
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
    """Fetch raw NSE datasets through a real Playwright NSE session.

    The browser establishes the NSE session first. API requests are then made
    from inside that same browser context, avoiding a fresh unauthenticated
    requests.Session and matching the working scraper architecture.
    """
    symbol = symbol.upper()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(NSE_BASE + "/", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)

        snapshot: dict[str, Any] = {
            "symbol": symbol,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": "NSE India",
            "session_cookies": len(context.cookies()),
        }

        calls = {
            "shareholding": (
                "/api/corporate-share-holdings-master",
                {"index": "equities", "symbol": symbol},
            ),
            "financial_results": (
                "/api/corporates-financial-results",
                {"index": "equities", "period": "Quarterly", "symbol": symbol},
            ),
            "results_comparison": (
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
