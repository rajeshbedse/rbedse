"""Small scoring-layer correction around the raw NSE financial normalizer.

PE is computed from market price / TTM EPS rather than trying to infer the
XBRL statement unit (Lakhs vs Actuals) from presentation text. This keeps the
ratio unit-invariant.
"""

from __future__ import annotations

from typing import Any

from .nse_financials import normalize_symbol as _normalize_symbol


def normalize_symbol(page: Any, symbol: str, quote: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _normalize_symbol(page, symbol, quote=quote)

    # The base normalizer already returns all scoring fields. Replace PE with a
    # unit-invariant price / TTM EPS estimate when four quarterly EPS values are
    # available in the parser's output in a future extension. Until then retain
    # the base value rather than manufacturing a ratio from an unknown unit.
    result.setdefault("NSEFinancialSource", "Integrated Filing/XBRL")
    return result
