"""
NSE-first enrichment helpers.

This module is the first step of the Screener.in migration. It talks only to
NSE's first-party endpoints and deliberately does not change the existing
scoring pipeline yet.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

NSE_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": NSE_BASE + "/",
}


class NSEEnrichmentClient:
    """Session-based client for NSE first-party enrichment endpoints."""

    def __init__(self, session: requests.Session | None = None, timeout: int = 20):
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)
        self.timeout = timeout

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(NSE_BASE + path, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def shareholding(self, symbol: str, index: str = "equities") -> Any:
        return self._get_json("/api/corporate-share-holdings-master", {"index": index, "symbol": symbol.upper()})

    def financial_results(self, symbol: str, index: str = "equities", period: str = "Quarterly") -> Any:
        return self._get_json("/api/corporates-financial-results", {"index": index, "period": period, "symbol": symbol.upper()})

    def results_comparison(self, symbol: str) -> Any:
        return self._get_json("/api/results-comparision", {"symbol": symbol.upper()})

    def quote(self, symbol: str) -> Any:
        return self._get_json("/api/quote-equity", {"symbol": symbol.upper()})


def fetch_nse_snapshot(symbol: str) -> dict[str, Any]:
    """Fetch raw NSE datasets needed for source-vs-source validation.

    No calculations or scoring are performed here. This keeps the migration
    auditable before the existing Screener-derived fields are replaced.
    """
    client = NSEEnrichmentClient()
    return {
        "symbol": symbol.upper(),
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "shareholding": client.shareholding(symbol),
        "financial_results": client.financial_results(symbol),
        "results_comparison": client.results_comparison(symbol),
        "quote": client.quote(symbol),
    }
