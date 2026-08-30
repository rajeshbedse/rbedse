"""NSE-first enrichment helpers used for source validation."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

import requests

NSE_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


class NSEEnrichmentClient:
    def __init__(self, session: requests.Session | None = None, timeout: int = 30):
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)
        self.timeout = timeout
        self._bootstrap()

    def _bootstrap(self) -> None:
        response = self.session.get(
            NSE_BASE + "/",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": NSE_BASE + "/",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(
                    NSE_BASE + path,
                    params=params,
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Referer": NSE_BASE + "/",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=self.timeout,
                )
                if response.status_code == 403 and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    self._bootstrap()
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def shareholding(self, symbol: str, index: str = "equities") -> Any:
        return self._get_json("/api/corporate-share-holdings-master", {"index": index, "symbol": symbol.upper()})

    def financial_results(self, symbol: str, index: str = "equities", period: str = "Quarterly") -> Any:
        return self._get_json("/api/corporates-financial-results", {"index": index, "period": period, "symbol": symbol.upper()})

    def results_comparison(self, symbol: str) -> Any:
        return self._get_json("/api/results-comparision", {"symbol": symbol.upper()})

    def quote(self, symbol: str) -> Any:
        return self._get_json("/api/quote-equity", {"symbol": symbol.upper()})


def _capture(fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"status": "ok", "data": fn()}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def fetch_nse_snapshot(symbol: str) -> dict[str, Any]:
    """Fetch raw NSE datasets without calculations or scoring."""
    client = NSEEnrichmentClient()
    symbol = symbol.upper()
    return {
        "symbol": symbol,
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "source": "NSE India",
        "shareholding": _capture(lambda: client.shareholding(symbol)),
        "financial_results": _capture(lambda: client.financial_results(symbol)),
        "results_comparison": _capture(lambda: client.results_comparison(symbol)),
        "quote": _capture(lambda: client.quote(symbol)),
    }
