"""NSE Insider Trading Weekly Pipeline."""
__version__ = "1.2.1"


# Backward-compatibility guard for Bhavcopy price maps.
# Older pipeline revisions returned ``{symbol: float}``, while the current
# analyzer expects ``{symbol: {"LastPrice": float}}``.  Normalise either
# shape at the module boundary so a stale/alternate price provider cannot
# crash Phase 2 with ``'float' object has no attribute 'get'``.
from . import analyzer as _analyzer

_original_download_bhavcopy = _analyzer._download_bhavcopy


def _normalised_download_bhavcopy(*args, **kwargs):
    data = _original_download_bhavcopy(*args, **kwargs)
    if not data:
        return data
    return {
        symbol: value if isinstance(value, dict) else {"LastPrice": value}
        for symbol, value in data.items()
    }


_analyzer._download_bhavcopy = _normalised_download_bhavcopy
