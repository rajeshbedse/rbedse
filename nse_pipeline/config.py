"""
Central configuration — edit these values to tune the pipeline.
"""
from pathlib import Path

# ── Analysis thresholds ───────────────────────────────────────────────────────
MIN_PURCHASE_VALUE   = 2_000_000   # ₹ — minimum total promoter buy value per symbol
MAX_SELL_BUY_RATIO_PCT = 25.0       # retained for v1 shadow reporting; v2 treats sells as risk
MIN_PROMO_HOLDING    = 60.0         # % — minimum latest-quarter promoter shareholding
PRICE_PROXIMITY_BANDS = [10, 20, 30]  # % bands for proximity report

# ── NSE scraper ───────────────────────────────────────────────────────────────
NSE_FILING_PERIOD    = "3M"        # "1M" | "3M" | "6M" | "1Y"
SCRAPER_DETAIL_DELAY = 0.3         # seconds between detail page loads
SCRAPER_DETAIL_TIMEOUT = 15        # seconds per detail-page request
SCRAPER_DETAIL_RETRIES = 2         # total attempts per detail page
SCRAPER_DETAIL_RETRY_DELAY = 1.5   # seconds between retry attempts
HOLDING_FETCH_DELAY  = 3.5         # seconds between Screener fetches — 429 protection
HOLDING_RETRY_COUNT  = 3           # max retries per symbol on 429 (backoff: 5s, 10s, 20s)

# ── Parallelism ───────────────────────────────────────────────────────────────
SCRAPER_WORKERS      = 4           # parallel workers for Phase 1 detail pages
HOLDING_WORKERS      = 2           # parallel workers for Phase 2 holding fetch (staggered start)

# ── File / folder layout ──────────────────────────────────────────────────────
OUTPUT_ROOT          = Path("output")   # relative to cwd when pipeline is run
CSV_FILENAME         = "nse_insider_trading_3m.csv"
EXCEL_FILENAME       = "enriched_analysis.xlsx"
FULL_CSV_FILENAME    = "enriched_full.csv"
TRADES_CSV_FILENAME  = "promoter_trades.csv"
LOG_FILENAME         = "run_log.txt"

# ── Legacy v1 scoring constants (shadow model) ────────────────────────────────
# Kept unchanged so ScoreV1 remains exactly comparable with historical runs.
SCORE_PROMO_BUY           = 5
SCORE_PROMO_MULTI_TXN     = 3
SCORE_PROMO_CONVICTION    = 5
SCORE_PROMO_HOLDING_INC   = 5
SCORE_PROMO_NO_SELL       = 2
SCORE_PROMO_NO_PLEDGE     = 5

SCORE_FUND_REV_GROWTH     = 5
SCORE_FUND_EBITDA_GROWTH  = 5
SCORE_FUND_PAT_GROWTH     = 7
SCORE_FUND_EPS_GROWTH     = 5
SCORE_FUND_ROCE           = 4
SCORE_FUND_DE_RATIO       = 3
SCORE_FUND_OCF_POS        = 6

SCORE_TECH_ABOVE_REF      = 5
SCORE_TECH_ABOVE_50DMA    = 5
SCORE_TECH_ABOVE_200DMA   = 5
SCORE_TECH_DMA_CROSS      = 5
SCORE_TECH_VOL_EXPANSION  = 5
SCORE_TECH_REL_STRENGTH   = 5

SCORE_RISK_PLEDGE         = -5
SCORE_RISK_MARGIN_FALL    = -2
SCORE_RISK_HIGH_PE        = -3

# ── Active v2 scoring model ──────────────────────────────────────────────────
# Gross model: Promoter 30 + Fundamentals 30 + Technical 25 = 85.
# Gross score is normalized to 100; risk can deduct up to 15 points.
V2_PROMOTER_MAX           = 30
V2_FUNDAMENTAL_MAX        = 30
V2_TECHNICAL_MAX          = 25
V2_RISK_MAX_DEDUCTION     = 15

# ── Category thresholds (score / 100) ────────────────────────────────────────
CATEGORY_STRONG_BUY    = 65
CATEGORY_BUY_BREAKOUT  = 50
CATEGORY_WATCHLIST     = 40
CATEGORY_WEAK_FUND     = 30
# < CATEGORY_WEAK_FUND → Avoid

# ── Filter sets ───────────────────────────────────────────────────────────────
PROMOTER_CATEGORIES  = {"promoter", "promoter group", "promoter and director"}
PLEDGE_MODES         = {"pledge creation", "invocation of pledge"}

# ── Browser ───────────────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Disable HTTP/2 so NSE doesn't drop connections in headless mode.
# AutomationControlled suppression reduces bot-detection signals.
BROWSER_ARGS = [
    "--disable-http2",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]
