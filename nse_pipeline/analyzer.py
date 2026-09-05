"""
Phase 2 — Filter, Enrich, Fetch Prices, Holdings, Fundamentals & Score

Applies:
  Filter B  No Pledge Creation / Invocation by Promoter/PG
  Filter C  Promoter market selling <= 25% of promoter market buying
  Filter A  Promoter holding >= MIN_PROMO_HOLDING (from Screener.in)

Prices are fetched from the NSE Bhavcopy daily CSV
(nsearchives.nseindia.com) — a single public HTTP download, no browser,
no cookies, no auth required.  The file covers all equities traded that
day and is downloaded once, then the whole symbol batch is resolved from
the in-memory dict.  EQ, BE, and BZ series are all included so SME-listed
and trade-to-trade symbols are not missed.

Promoter holdings + fundamental data are fetched from Screener.in using
requests + BeautifulSoup — static HTML, no browser required, fully
thread-safe.  Each fetch retries up to HOLDING_RETRY_COUNT times on 429
with exponential backoff (5 s → 10 s → 20 s) before recording None.

Both fetches are parallelised across ThreadPoolExecutor workers.
No Playwright objects are used or passed across thread boundaries.

Scoring model (0–100):
  Promoter Signal   — 25 pts
  Fundamental Signal— 35 pts
  Technical Signal  — 30 pts
  Risk deductions   — up to −10 pts

Category labels:
  🟢 Strong Buy Setup   (≥ 65)
  🟢 Buy on Breakout    (≥ 50)
  🟡 Watchlist          (≥ 40)
  🟠 Fundamental Watch  (≥ 30)
  🔴 Avoid              (< 30)
"""
import csv as _csv
import io
import re
import logging
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .config import (
    MIN_PURCHASE_VALUE, MIN_PROMO_HOLDING, MAX_SELL_BUY_RATIO_PCT,
    PROMOTER_CATEGORIES, PLEDGE_MODES,
    HOLDING_FETCH_DELAY, HOLDING_RETRY_COUNT,
    HOLDING_WORKERS, USER_AGENT,
    TRADES_CSV_FILENAME,
    SCORE_PROMO_BUY, SCORE_PROMO_MULTI_TXN, SCORE_PROMO_CONVICTION,
    SCORE_PROMO_HOLDING_INC, SCORE_PROMO_NO_SELL, SCORE_PROMO_NO_PLEDGE,
    SCORE_FUND_REV_GROWTH, SCORE_FUND_EBITDA_GROWTH, SCORE_FUND_PAT_GROWTH,
    SCORE_FUND_EPS_GROWTH, SCORE_FUND_ROCE, SCORE_FUND_DE_RATIO, SCORE_FUND_OCF_POS,
    SCORE_TECH_ABOVE_REF, SCORE_TECH_ABOVE_50DMA, SCORE_TECH_ABOVE_200DMA,
    SCORE_TECH_DMA_CROSS, SCORE_TECH_VOL_EXPANSION, SCORE_TECH_REL_STRENGTH,
    SCORE_RISK_PLEDGE, SCORE_RISK_MARGIN_FALL, SCORE_RISK_HIGH_PE,
    CATEGORY_STRONG_BUY, CATEGORY_BUY_BREAKOUT, CATEGORY_WATCHLIST, CATEGORY_WEAK_FUND,
)
from .promoter_history import build_accumulation_snapshot

log = logging.getLogger(__name__)

_NSE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_SCREENER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

# The remainder of this module is unchanged from the verified DEV baseline.
# Timing helpers are inserted immediately before the Phase 2 entry point below.
