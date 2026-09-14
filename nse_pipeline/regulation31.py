"""Compatibility entry point for current NSE promoter encumbrance data.

The actual acquisition now uses the reusable NSE stock-quote-page browser layer
and lives in ``nse_pipeline.sources.promoter_encumbrance``. Keep this module so
existing pipeline imports and callers remain stable while future NSE stock-page
sections can share the same browser/navigation implementation.
"""
from .sources.promoter_encumbrance import COLUMNS, fetch_symbol, run

__all__ = ["COLUMNS", "fetch_symbol", "run"]
