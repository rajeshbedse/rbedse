"""NSE Insider Trading pipeline package."""
__version__ = "1.2.0"

# Install the optional-research circuit breaker as soon as the package loads.
# This keeps transient NSE archive outages from consuming the entire scheduled
# scan while leaving the core scoring pipeline unchanged.
from . import research_enrichment as _research_enrichment
from .research_resilience import install_price_history_circuit_breaker

install_price_history_circuit_breaker(_research_enrichment)
