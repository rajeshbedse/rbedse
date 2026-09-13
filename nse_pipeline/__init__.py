"""NSE Insider Trading pipeline package."""
__version__ = "1.3.0"

# Install resilience/scoring extensions as soon as the package loads.
# This keeps the scheduled pipeline behavior centralized while allowing the
# analyzer's legacy v1 scorer to remain available as a shadow score.
from . import research_enrichment as _research_enrichment
from .research_resilience import install_price_history_circuit_breaker
from . import analyzer as _analyzer
from .scoring_v2 import install as install_scoring_v2

install_price_history_circuit_breaker(_research_enrichment)
install_scoring_v2(_analyzer)
