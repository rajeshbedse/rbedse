"""
Central configuration — edit these values to tune the pipeline.
"""
from pathlib import Path

# ── Analysis thresholds ───────────────────────────────────────────────────────
MIN_PURCHASE_VALUE   = 2_000_000   # ₹ — minimum total promoter buy value per symbol
MAX_SELL_BUY_RATIO_PCT = 25.0       # hard exclusion if promoter market sells exceed 25% of market buys
MIN_PROMO_HOLDING    = 60.0        # % — minimum latest-quarter promoter shareholding
PRICE_PROXIMITY_BANDS = [10, 20, 30]  # % bands for proximity report

# ── NSE scraper ───────────────────────────────────────────────────────────────
NSE_FILING_PERIOD    = "3M"        # "1M" | "3M" | "6M" | "1Y"
SCRAPER_DETAIL_DELAY = 0.3         # seconds between detail page loads
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

# ── Scoring model weights (max points per sub-bucket) ────────────────────────
# Promoter Signal  — 25 pts
SCORE_PROMO_BUY           = 5   # promoter market buy present
SCORE_PROMO_MULTI_TXN     = 3   # ≥ 3 transactions
SCORE_PROMO_CONVICTION    = 5   # buy value ≥ 0.25 % of market cap
SCORE_PROMO_HOLDING_INC   = 5   # holding > 65 % (proxy for high-conviction ownership)
SCORE_PROMO_NO_SELL       = 2   # no market sell in the period
SCORE_PROMO_NO_PLEDGE     = 5   # no pledge creation / invocation

# Fundamental Signal — 35 pts
SCORE_FUND_REV_GROWTH     = 5   # revenue growth > 15 %
SCORE_FUND_EBITDA_GROWTH  = 5   # EBITDA growth > 15 %
SCORE_FUND_PAT_GROWTH     = 7   # PAT growth > 15 %
SCORE_FUND_EPS_GROWTH     = 5   # EPS growth > 15 %
SCORE_FUND_ROCE           = 4   # ROCE > 15 %
SCORE_FUND_DE_RATIO       = 3   # D/E < 0.5
SCORE_FUND_OCF_POS        = 6   # operating cash flow positive

# Technical Signal — 30 pts
SCORE_TECH_ABOVE_REF      = 5   # price > promoter avg buy price
SCORE_TECH_ABOVE_50DMA    = 5   # price > 50 DMA  (approximated from Screener)
SCORE_TECH_ABOVE_200DMA   = 5   # price > 200 DMA (approximated from Screener)
SCORE_TECH_DMA_CROSS      = 5   # 50 DMA > 200 DMA (golden cross proxy)
SCORE_TECH_VOL_EXPANSION  = 5   # volume expansion signal from Screener
SCORE_TECH_REL_STRENGTH   = 5   # relative strength vs Nifty (positive 6M return)

# Risk deductions — up to −10 pts (applied as negative)
SCORE_RISK_PLEDGE         = -5  # promoter pledge > 0 %
SCORE_RISK_MARGIN_FALL    = -2  # operating margin deteriorating
SCORE_RISK_HIGH_PE        = -3  # PE > 60

# Category thresholds (score / 100)
CATEGORY_STRONG_BUY    = 65    # 🟢  Strong Buy Setup
CATEGORY_BUY_BREAKOUT  = 50    # 🟢  Buy on Breakout
CATEGORY_WATCHLIST     = 40    # 🟡  Watchlist
CATEGORY_WEAK_FUND     = 30    # 🟠  Fundamental but technically weak
# < CATEGORY_WEAK_FUND   → 🔴  Avoid

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
