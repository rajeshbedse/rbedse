"""Runtime resilience for optional research enrichment.

The core NSE scan must not spend the entire GitHub Actions budget retrying an
NSE archive endpoint that is temporarily unavailable.  This module adds a
small circuit breaker around the optional daily Bhavcopy downloader.
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)


def install_price_history_circuit_breaker(research_enrichment, failure_threshold: int = 5) -> None:
    """Stop an unavailable optional archive from consuming the whole run.

    A successful archive response resets the counter.  After ``failure_threshold``
    consecutive failed archive dates, subsequent dates are skipped for this
    run.  This preserves the core scan and all other research datasets while
    avoiding hundreds of 20-second HTTP timeouts when NSE archives are down.
    """
    original: Callable = research_enrichment._download_daily_prices
    state = {"consecutive_failures": 0, "tripped": False}

    def guarded(session, trading_date):
        if state["tripped"]:
            return []
        rows = original(session, trading_date)
        if rows:
            state["consecutive_failures"] = 0
            return rows
        state["consecutive_failures"] += 1
        if state["consecutive_failures"] >= failure_threshold:
            state["tripped"] = True
            log.warning(
                "Research price-history circuit breaker tripped after %d consecutive "
                "NSE archive failures; remaining dates will be skipped.",
                state["consecutive_failures"],
            )
        return []

    research_enrichment._download_daily_prices = guarded
    log.info("Research price-history circuit breaker installed (threshold=%d)", failure_threshold)
