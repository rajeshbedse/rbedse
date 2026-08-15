# RYB Finserv — NSE Promoter Buying Intelligence Portal

> **Research use only.** This platform is an independent research tool based on publicly available regulatory disclosures. It does not constitute financial advice. Always consult a SEBI-registered investment advisor before making investment decisions.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What the platform does](#2-what-the-platform-does)
3. [Pipeline architecture](#3-pipeline-architecture)
4. [Phase 1 — NSE Scraper](#4-phase-1--nse-scraper)
5. [Phase 2 — Analyzer & Enrichment](#5-phase-2--analyzer--enrichment)
6. [Scoring model (0–100)](#6-scoring-model-0100)
7. [Category classification](#7-category-classification)
8. [Fundamental snapshot — metrics explained](#8-fundamental-snapshot--metrics-explained)
9. [Technical signals — DMA computation](#9-technical-signals--dma-computation)
10. [Portal — pages & features](#10-portal--pages--features)
11. [Output files](#11-output-files)
12. [Project structure](#12-project-structure)
13. [Quick start](#13-quick-start)
14. [Configuration reference](#14-configuration-reference)
15. [Design system](#15-design-system)

---

## 1. Overview

RYB Finserv tracks **NSE promoter market-buy filings** (SAST / insider-trading disclosures) and combines them with live fundamentals and price data to produce a scored, ranked shortlist of stocks where promoters are buying their own company shares with their own money.

The core thesis:

> Promoter buying alone is not sufficient signal. The strongest setups combine:
> promoter conviction **+** business earnings acceleration **+** price/volume momentum.

The platform operationalises this thesis through a reproducible **0–100 score** across four signal buckets.

---

## 2. What the platform does

```
NSE regulatory filings (3-month window)
          │
          ▼
  Phase 1 — Scraper
  ├─ Downloads all insider-trading filings via NSE website
  ├─ Filters: promoter/promoter-group only, market-purchase only
  └─ Outputs raw CSV of all eligible transactions
          │
          ▼
  Phase 2 — Analyzer
  ├─ Filter A: promoter holding ≥ 60% (Screener.in)
  ├─ Filter B: no pledge creation/invocation
  ├─ Filter C: no market sale by promoter
  ├─ Enrichment: current price (NSE Bhavcopy)
  ├─ Enrichment: DMA50 / DMA200 / 6M return (Bhavcopy history)
  ├─ Enrichment: fundamentals (Screener.in HTML parse)
  └─ Scoring: 0–100 across 4 signal groups
          │
          ▼
  Reporter — Excel (3 sheets) + CSV outputs
          │
          ▼
  Flask Portal — searchable, sortable, filterable research dashboard
```

---

## 3. Pipeline architecture

| Component | File | Purpose |
|---|---|---|
| Scraper | `nse_pipeline/scraper.py` | Playwright-based NSE scraper |
| Analyzer | `nse_pipeline/analyzer.py` | Filtering, enrichment, scoring |
| Reporter | `nse_pipeline/reporter.py` | Excel + CSV output writer |
| Pipeline | `nse_pipeline/pipeline.py` | Orchestrator — runs all phases |
| Config | `nse_pipeline/config.py` | All thresholds and weights |
| Portal | `portal/app.py` | Flask web application |

---

## 4. Phase 1 — NSE Scraper

**Source:** `https://www.nseindia.com/companies-listing/corporate-filings-insider-trading`

- Uses **Playwright** (headless Chromium) to navigate the NSE insider-trading filings page
- Downloads the 3-month SAST disclosure CSV
- Filing period is configurable: `1M | 3M | 6M | 1Y` (default: `3M`)
- HTTP/2 disabled and `AutomationControlled` suppressed to reduce bot-detection signals

**Pre-filter applied at scrape time:**
- Category of Person must be in: `promoter`, `promoter group`, `promoter and director`
- Transaction type must be: `buy`
- Mode of Acquisition must be: `market purchase` (excludes ESOPs, off-market, preferential allotment)
- Total buy value per symbol must be **≥ ₹20 Lakh** (₹20,00,000)

**Output:** `output/YYYY-MM-DD/nse_insider_trading_3m.csv`

---

## 5. Phase 2 — Analyzer & Enrichment

### 5.1 Aggregation

Per-symbol aggregates computed from raw filings:

| Column | Calculation |
|---|---|
| `ValuePurchased` | Sum of all market-buy values in the period |
| `TotalQty` | Sum of all shares acquired |
| `NumBuyTxn` | Count of individual buy transactions |
| `AvgPrice` | `ValuePurchased ÷ TotalQty` (weighted average cost) |
| `ValueCr` | `ValuePurchased ÷ 10,000,000` (in Crores) |
| `acqtoDt` | Latest transaction date |

### 5.2 Exclusion filters

Applied before any enrichment:

- **Pledge filter:** Symbol excluded if promoter/PG created or invoked a pledge in the same period (`pledge creation`, `invocation of pledge`)
- **Market-sell filter:** Symbol excluded if promoter/PG made a market sale in the same period
- **Holding filter:** Symbol excluded if latest promoter shareholding (from Screener.in) is < 60%

### 5.3 Price enrichment — NSE Bhavcopy

Current price is resolved from the **NSE Bhavcopy daily CSV** (public, no auth required):

```
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip
```

- Downloaded **once** per run; all symbols resolved from the in-memory dict
- Covers `EQ`, `BE` (trade-to-trade), and `BZ` (SME trade-to-trade) series
- Falls back up to 5 prior trading days if today's file is not yet published
- `PriceDiffPct` = `(LastPrice − AvgPrice) ÷ AvgPrice × 100`

### 5.4 DMA & 6M Return — Bhavcopy history

50-day and 200-day moving averages and 6-month return are computed **directly from NSE Bhavcopy historical files** (not Screener.in):

- Lookback: **380 calendar days** (~270 weekday URL candidates → ~200 usable trading days)
- Downloads all files **in parallel** (8 worker threads) — entire batch takes ~2–3 seconds
- Uses **closing price** (`ClsPric`) from each daily file
- Close series collected newest-first per symbol; DMAs computed from the most recent N closes

| Metric | Calculation |
|---|---|
| `DMA50` | Simple average of most recent 50 closing prices |
| `DMA200` | Simple average of most recent 200 closing prices (requires ≥ 200 days) |
| `SixMonthReturn` | `(close[0] ÷ close[126] − 1) × 100` — requires ≥ 60 days minimum |

### 5.5 Fundamental enrichment — Screener.in

Each symbol is fetched from `https://www.screener.in/company/{SYMBOL}/` using `requests` + `BeautifulSoup` (static HTML, no browser):

| Metric | Source on Screener.in | Parser logic |
|---|---|---|
| Market Cap | `#top-ratios` → "Market Cap" li | Parsed from `<span class="nowrap">` |
| P/E Ratio | `#top-ratios` → "Stock P/E" li | Any `li` with name containing `p/e` |
| ROCE % | `#top-ratios` → "ROCE" li | Any `li` with name containing `roce` |
| Revenue Growth % | Compounded Sales Growth table → TTM row | `"compounded sales"` header → TTM cell |
| PAT Growth % | Compounded Profit Growth table → TTM row | `"compounded profit"` header → TTM cell |
| EBITDA Growth % | P&L table → "Operating Profit" row | Most recent column value |
| EPS Growth % | P&L table → "EPS" row | Most recent column value |
| OPM % | P&L table → "OPM %" row | Most recent column value |
| D/E Ratio | Balance sheet → Borrowings, Equity Capital, Reserves | `Borrowings ÷ (Equity Capital + Reserves)` |
| OCF Positive | Cash-flow section → "Operating" row | `True` if most recent value > 0 |
| Promoter Holding % | Shareholding Pattern → Promoters row | First % in the row = most recent quarter |

**Rate-limit protection:**
- 2 parallel workers, staggered by 2s at startup
- 3.5s delay between each symbol fetch
- 429 responses trigger exponential backoff: 5s → 10s → 20s (3 retries)

---

## 6. Scoring model (0–100)

The RYB Score quantifies the combined strength of promoter conviction, business fundamentals, technical price action, and risk flags into a single 0–100 number.

```
RYB Score = Promoter Signal (max 25)
           + Fundamental Signal (max 35)
           + Technical Signal (max 30)
           + Risk Deductions (max −10)
           ─────────────────────────────
           Clamped to [0, 100]
```

The three signal groups map directly to the **RYB logo circles**:
- 🔴 **Red** = Promoter Signal
- 🟡 **Yellow** = Fundamental Signal
- 🔵 **Blue** = Technical Signal

---

### 6.1 Promoter Signal — max 25 pts

| Sub-signal | Points | Condition |
|---|---|---|
| Market Buy present | +5 | Always true (universe filter guarantees this) |
| Multi-transaction | +3 | `NumBuyTxn ≥ 3` — promoter bought in multiple tranches |
| High conviction | +5 | `BuyValue ÷ MarketCap ≥ 0.25%` — significant relative to company size |
| Holding > 65% | +5 | Latest promoter shareholding > 65% (high-ownership alignment) |
| No insider sell | +2 | No market sale by promoter/PG in the same period |
| No pledge | +5 | No pledge creation or invocation in the same period |

**Conviction fallback:** If market cap is unavailable, partial credit (+5) is awarded if absolute buy value ≥ ₹10 Crore.

---

### 6.2 Fundamental Signal — max 35 pts

| Sub-signal | Points | Condition | Why it matters |
|---|---|---|---|
| Revenue Growth | +5 | YoY revenue growth > 15% | Business is expanding |
| EBITDA Growth | +5 | YoY EBITDA/operating profit growth > 15% | Margins are improving |
| PAT Growth | +7 | YoY profit after tax growth > 15% | **Highest weight** — bottom-line confirmation |
| EPS Growth | +5 | YoY earnings per share growth > 15% | Per-share value increasing (accounts for dilution) |
| ROCE > 15% | +4 | Return on Capital Employed > 15% | Capital being deployed efficiently |
| D/E < 0.5 | +3 | Debt-to-Equity ratio < 0.5 | Low financial leverage = safety margin |
| Positive OCF | +6 | Operating Cash Flow > 0 (most recent year) | Real cash generation — harder to manipulate than PAT |

**PAT Growth carries the highest weight (7 pts)** because a company can show revenue growth while profits decline — that combination is a red flag. PAT confirmation validates that growth is real.

**OCF carries 6 pts** because cash flow is significantly harder to manipulate than accounting profit. Positive OCF means the business funds itself.

---

### 6.3 Technical Signal — max 30 pts

| Sub-signal | Points | Condition |
|---|---|---|
| Price > Promoter Avg | +5 | Current price > weighted average promoter buy price |
| Price > 50 DMA | +5 | Current price > 50-day moving average |
| Price > 200 DMA | +5 | Current price > 200-day moving average |
| Golden Cross | +5 | 50 DMA > 200 DMA (shorter MA above longer = uptrend) |
| Volume expansion | +5 | Price > ref price by > 5% AND ≥ 2 buy transactions |
| Relative strength | +5 | 6-month price return > 0% (stock rising over medium term) |

**Price > Promoter Avg** is a critical check: it means the market has already validated the promoter's purchase price. Combined with other technical signals it confirms the trade is working.

**Relative strength fallback:** If 6M return data is unavailable, the signal triggers if price is more than 10% above the promoter reference price.

---

### 6.4 Risk Deductions — max −10 pts

| Sub-signal | Points | Condition | Why it's a risk |
|---|---|---|---|
| Pledge detected | −5 | Promoter pledge > 0 in period | Pledged shares can be force-sold; promoter buying while pledging is contradictory |
| Thin margin | −2 | OPM % < 5% | Operating margin below 5% leaves no buffer for cost shocks |
| High PE | −3 | P/E ratio > 60× | Expensive valuation increases downside risk if growth disappoints |

---

## 7. Category classification

| Category | Score range | Meaning |
|---|---|---|
| 🟢 **Strong Buy Setup** | ≥ 65 | Promoter conviction + fundamental acceleration + technical confirmation all aligned |
| 🔵 **Buy on Breakout** | ≥ 50 | Strong combined signal — technically ready or fundamentals improving |
| 🟡 **Watchlist** | ≥ 40 | Mixed signals — monitor for confirmation |
| 🟠 **Fundamental Watch** | ≥ 30 | Fundamentally improving but technically unconfirmed |
| 🔴 **Avoid** | < 30 | Insufficient conviction across signal groups |

---

## 8. Fundamental snapshot — metrics explained

The portal displays 11 metrics organised into **3 groups × 2×2 grid** per stock.

### Valuation (4 metrics)

| Metric | Formula | Scoring relevance |
|---|---|---|
| **Market Cap** | Share Price × Total Shares | Used to compute conviction % |
| **P/E Ratio** | Market Price ÷ EPS | > 60× deducts −3 pts (risk) |
| **Buy / Mkt Cap** | Total ₹ bought ÷ Market Cap × 100 | ≥ 0.25% earns +5 pts (conviction) |
| **6M Return** | (Price now ÷ Price 6M ago − 1) × 100 | > 0% earns +5 pts (relative strength) |

**Buy / Mkt Cap is the most important missing metric** that most screens ignore. A ₹10 Cr buy in a ₹100 Cr company (1%) is fundamentally different from a ₹10 Cr buy in a ₹20,000 Cr company (0.05%). The signal strength is proportional.

### Growth — YoY (4 metrics)

| Metric | Formula | Scoring relevance |
|---|---|---|
| **Revenue** | YoY sales growth % (TTM) | > 15% earns +5 pts |
| **EBITDA** | YoY operating profit growth % | > 15% earns +5 pts |
| **PAT** | YoY profit after tax growth % | > 15% earns +7 pts (highest weight) |
| **EPS** | YoY earnings per share growth % | > 15% earns +5 pts |

### Efficiency & Risk (4 metrics)

| Metric | Formula | Scoring relevance |
|---|---|---|
| **ROCE** | EBIT ÷ (Debt + Equity) × 100 | > 15% earns +4 pts |
| **D/E Ratio** | Total Borrowings ÷ (Equity Capital + Reserves) | < 0.5 earns +3 pts |
| **OPM %** | Operating Profit ÷ Revenue × 100 | < 5% deducts −2 pts (risk) |
| **Cash Flow** | Operating Cash Flow (most recent year) | Positive earns +6 pts |

---

## 9. Technical signals — DMA computation

### How DMA is computed

1. Walk back 380 calendar days from today, skip weekends
2. Build a list of ~270 candidate trading-day URLs
3. Download all Bhavcopy ZIP files in parallel (8 threads)
4. For each file, extract closing prices for all `EQ/BE/BZ` series symbols
5. Sort per-symbol closes newest-first
6. `DMA50 = mean(closes[0:50])` — requires ≥ 50 trading days
7. `DMA200 = mean(closes[0:200])` — requires ≥ 200 trading days
8. `6M Return = (closes[0] / closes[126] - 1) × 100` — requires ≥ 60 trading days minimum

### Why NSE Bhavcopy (not Screener.in)

- Public, unauthenticated, reliable
- Covers all ~2,000 equity symbols in one file
- No per-symbol HTTP request — one download resolves prices for every symbol
- Data is official exchange-sourced close prices

### NSE archive availability

The Bhavcopy archive goes back approximately **269 trading days** (~14 months). The 380 calendar day lookback generates enough candidates to collect ≥ 200 usable trading days, making the 200 DMA computation reliable for most symbols.

---

## 10. Portal — pages & features

### Homepage (`/`)

- **Hero panel:** Live stats from the latest scan — category breakdown segmented bar, above/below promoter reference price split, top 3 stocks by score
- **Philosophy pillars:** Mind · Discipline · Compounding
- **Methodology strip:** How the screen works (5 criteria pills)
- **Research History:** All scan dates with shortlist ratio bar, stock counts, and direct links

### Scan Detail (`/scan/YYYY-MM-DD`)

**Quality Shortlist tab:**

| Feature | Details |
|---|---|
| Score column | 0–100 RYB Score with colour-coded bar (green ≥65, blue ≥50, yellow ≥40, red <40) |
| Category dot | Colour-coded dot: 🟢 Strong Buy / 🔵 Breakout / 🟡 Watchlist / 🟠 Fund Watch / 🔴 Avoid |
| CMP | Current market price from latest Bhavcopy |
| Ref price | Promoter weighted average buy price |
| Δ% | `(CMP − Ref) ÷ Ref × 100` — how far price has moved since promoter bought |
| Hold% | Latest promoter shareholding % from Screener.in |
| ₹Cr | Total promoter buy value in Crores |
| Date | Latest transaction date |
| Search | Debounced search by symbol or company name |
| Band filter | ±0–10%, ±11–20%, ±21–30%, >30%, Below ref price |
| Category filter | All / Strong Buy / Breakout / Watchlist / Fund Watch / Avoid |
| Column sort | Click any header — ascending/descending, keyboard accessible |

**Expandable drawer (per stock):**

Clicking the expand button on any row reveals:

1. **RYB Score breakdown** — 4 horizontal bands (Promoter/Fundamental/Technical/Risk), each showing the progress bar, pts/max, and individual signal chips with pass/fail state and tooltip notes

2. **Fundamental Snapshot** — 3-group 2×2 grid:
   - Valuation: Market Cap, P/E, Buy/Mkt Cap, 6M Return
   - Growth: Revenue, EBITDA, PAT, EPS
   - Efficiency & Risk: ROCE, D/E, OPM%, Cash Flow
   - Each metric has a `?` tooltip explaining the formula, scoring rule, and signal thresholds

3. **Promoter Buying Transactions** — full table of individual trades:
   - Buyer name, category, qty acquired, value (₹), post-trade holding %, date, NSE filing link
   - Stock symbol is a hyperlink to Screener.in company page

**All Reviewed tab:**

Every symbol that passed the pledge + sell filters (before the 60% holding threshold cut), with the same scoring columns.

### Accessibility features

- WCAG AA contrast on all text (light surfaces: 4.5:1 minimum)
- Skip-to-content link
- Keyboard-navigable tabs (← → Home End)
- `aria-sort` on sortable column headers
- `aria-expanded` / `aria-controls` on drawer expand buttons
- Tooltips visible on both hover and `focus-within`
- `prefers-reduced-motion` support
- `prefers-contrast: more` support (stronger borders + text)
- Roving `tabindex` on tab bar

---

## 11. Output files

Each pipeline run creates a dated folder: `output/YYYY-MM-DD/`

| File | Contents |
|---|---|
| `nse_insider_trading_3m.csv` | Raw NSE insider filing data (all filers, 3-month window) |
| `enriched_analysis.xlsx` | 3-sheet Excel workbook (see below) |
| `enriched_full.csv` | All candidates after pledge/sell filter, before holding filter — with full scoring |
| `promoter_trades.csv` | Individual market-buy transaction rows for shortlisted symbols (portal drill-down) |
| `meta.json` | Run metadata: date, counts, duration, pipeline version |
| `run_log.txt` | Full pipeline execution log |
| `failed_urls.txt` | NSE filing URLs that returned errors during scrape |

### Excel workbook sheets

| Sheet | Contents |
|---|---|
| `ScoredStocks` | Final shortlisted stocks sorted by score descending — all enriched columns |
| `AllCandidates` | All symbols after pledge/sell filter (pre-holding filter) |
| `Summary` | Aggregate stats: category distribution, score averages, run metadata |

### Key columns in enriched output

| Column | Description |
|---|---|
| `Symbol` | NSE ticker |
| `CompanyName` | Company name |
| `AvgPrice` | Promoter weighted average buy price (₹) |
| `LastPrice` | Current market price from Bhavcopy |
| `PriceDiffPct` | % change from promoter avg to current price |
| `ValueCr` | Total promoter buy value (₹ Crore) |
| `NumBuyTxn` | Number of individual buy transactions |
| `PromoHolding` | Latest promoter shareholding % |
| `HasPledging` | True if pledge created/invoked in period |
| `HasMarketSell` | True if market sale in period |
| `MarketCapCr` | Market capitalisation (₹ Crore) |
| `PromoConvictionPct` | Buy value as % of market cap |
| `PE` | Price-to-Earnings ratio |
| `RevGrowthPct` | Revenue YoY growth % |
| `EBITDAGrowthPct` | EBITDA YoY growth % |
| `PATGrowthPct` | PAT YoY growth % |
| `EPSGrowthPct` | EPS YoY growth % |
| `ROCEPct` | Return on Capital Employed % |
| `DE_Ratio` | Debt-to-Equity ratio |
| `OCFPositive` | Operating Cash Flow positive (bool) |
| `OPMPct` | Operating Profit Margin % |
| `DMA50` | 50-day moving average (from Bhavcopy history) |
| `DMA200` | 200-day moving average (from Bhavcopy history) |
| `SixMonthReturn` | 6-month price return % (from Bhavcopy history) |
| `ScorePromo` | Promoter signal sub-score (0–25) |
| `ScoreFund` | Fundamental signal sub-score (0–35) |
| `ScoreTech` | Technical signal sub-score (0–30) |
| `ScoreRisk` | Risk deduction (0 to −10) |
| `Score` | Total RYB Score (0–100) |
| `Category` | Strong Buy Setup / Buy on Breakout / Watchlist / Fundamental Watch / Avoid |

---

## 12. Project structure

```
nse-insider-pipeline/
│
├── nse_pipeline/
│   ├── __init__.py
│   ├── config.py          ← All thresholds, weights, category cutoffs
│   ├── scraper.py         ← Phase 1: Playwright NSE scraper
│   ├── analyzer.py        ← Phase 2: filter, enrich, score
│   ├── reporter.py        ← Excel + CSV writer
│   └── pipeline.py        ← Orchestrator
│
├── portal/
│   ├── app.py             ← Flask app, routes, scoring display logic
│   ├── README.md          ← Portal-specific notes
│   ├── templates/
│   │   ├── base.html      ← Header, nav, footer, watermark
│   │   ├── index.html     ← Homepage: hero, pillars, methodology, history
│   │   ├── scan.html      ← Scan detail: tabs, table, drawer, score breakdown
│   │   └── 404.html
│   └── static/
│       ├── css/main.css   ← Full design-token stylesheet (v6)
│       └── js/
│           ├── main.js    ← Nav toggle
│           └── scan.js    ← Sort, filter, search, drawer, keyboard tabs
│
├── output/
│   └── YYYY-MM-DD/        ← One folder per run
│
├── snapshots/             ← Portal file backups before major changes
├── run_portal.bat         ← Windows: start Flask portal
├── run_portal.sh          ← Linux/macOS: start Flask portal
├── run_pipeline.bat       ← Windows: run full pipeline
└── requirements.txt
```

---

## 13. Quick start

### Run the portal (view existing scan results)

**Windows:**
```bat
run_portal.bat
```

**Linux / macOS:**
```bash
bash run_portal.sh
```

Then open **http://localhost:5000**

### Run the full pipeline (new scan)

**Windows:**
```bat
run_pipeline.bat
```

**Linux / macOS:**
```bash
python -m nse_pipeline.pipeline
```

The pipeline takes approximately 5–10 minutes depending on the number of candidate symbols (most time is Screener.in rate-limiting).

### Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 14. Configuration reference

All tuneable parameters are in [`nse_pipeline/config.py`](nse_pipeline/config.py).

### Entry filters

| Parameter | Default | Description |
|---|---|---|
| `MIN_PURCHASE_VALUE` | ₹20,00,000 | Minimum total buy value per symbol to enter the screen |
| `MIN_PROMO_HOLDING` | 60% | Minimum promoter shareholding to pass Filter A |
| `NSE_FILING_PERIOD` | `3M` | Filing lookback period: `1M`, `3M`, `6M`, `1Y` |

### Scoring weights

| Parameter | Points | Signal |
|---|---|---|
| `SCORE_PROMO_BUY` | 5 | Market buy present |
| `SCORE_PROMO_MULTI_TXN` | 3 | ≥ 3 transactions |
| `SCORE_PROMO_CONVICTION` | 5 | ≥ 0.25% of market cap |
| `SCORE_PROMO_HOLDING_INC` | 5 | Holding > 65% |
| `SCORE_PROMO_NO_SELL` | 2 | No market sell |
| `SCORE_PROMO_NO_PLEDGE` | 5 | No pledge |
| `SCORE_FUND_REV_GROWTH` | 5 | Revenue > 15% |
| `SCORE_FUND_EBITDA_GROWTH` | 5 | EBITDA > 15% |
| `SCORE_FUND_PAT_GROWTH` | 7 | PAT > 15% |
| `SCORE_FUND_EPS_GROWTH` | 5 | EPS > 15% |
| `SCORE_FUND_ROCE` | 4 | ROCE > 15% |
| `SCORE_FUND_DE_RATIO` | 3 | D/E < 0.5 |
| `SCORE_FUND_OCF_POS` | 6 | Positive OCF |
| `SCORE_TECH_ABOVE_REF` | 5 | Price > promoter avg |
| `SCORE_TECH_ABOVE_50DMA` | 5 | Price > 50 DMA |
| `SCORE_TECH_ABOVE_200DMA` | 5 | Price > 200 DMA |
| `SCORE_TECH_DMA_CROSS` | 5 | Golden cross (50 > 200 DMA) |
| `SCORE_TECH_VOL_EXPANSION` | 5 | Volume expansion proxy |
| `SCORE_TECH_REL_STRENGTH` | 5 | Positive 6M return |
| `SCORE_RISK_PLEDGE` | −5 | Pledge detected |
| `SCORE_RISK_MARGIN_FALL` | −2 | OPM < 5% |
| `SCORE_RISK_HIGH_PE` | −3 | PE > 60× |

### Category thresholds

| Parameter | Default | Category |
|---|---|---|
| `CATEGORY_STRONG_BUY` | 65 | Strong Buy Setup |
| `CATEGORY_BUY_BREAKOUT` | 50 | Buy on Breakout |
| `CATEGORY_WATCHLIST` | 40 | Watchlist |
| `CATEGORY_WEAK_FUND` | 30 | Fundamental Watch |

### Performance

| Parameter | Default | Description |
|---|---|---|
| `SCRAPER_WORKERS` | 4 | Parallel workers for NSE detail pages |
| `HOLDING_WORKERS` | 2 | Parallel workers for Screener.in |
| `HOLDING_FETCH_DELAY` | 3.5s | Delay between Screener fetches (429 protection) |
| `HOLDING_RETRY_COUNT` | 3 | Retries on 429 (backoff: 5s, 10s, 20s) |

---

## 15. Design system

### Colour philosophy

The UI follows a **70-15-5-10** colour allocation:

- **70%** neutral surfaces (`#F7F8FA` background, `#FFFFFF` cards, `#F2F4F7` secondary)
- **15%** brand blue (`#1F4B8F`) — navigation, links, active states, primary button
- **5–10%** status colours — green/amber/red for signal states only
- **RYB logo colours** (Red `#e32636`, Yellow `#f5c800`, Blue `#1a56db`) reserved for brand identity elements only

### Typography scale

8 defined sizes only — no ad-hoc values:

| Token | Size | Usage |
|---|---|---|
| `--text-xxs` | 11px | Labels, badges, table headers |
| `--text-xs` | 12px | Captions, secondary labels |
| `--text-sm` | 13px | Body secondary, chips |
| `--text-base` | 15px | Body text |
| `--text-md` | 17px | Metric values in snapshots |
| `--text-lg` | 20px | Section titles |
| `--text-xl` | 28px | Page titles |
| `--text-2xl` | 40px | Hero headlines |

### Status colours (WCAG AA compliant)

| Token | Value | Contrast on white | Usage |
|---|---|---|---|
| `--color-success` | `#2E7D6B` | 5.8:1 ✓ | Positive signals, good values |
| `--color-warning` | `#9A6B00` | 4.6:1 ✓ | Watchlist, caution states |
| `--color-error` | `#B5474D` | 4.7:1 ✓ | Negative signals, risk flags |
| `--color-muted` | `#475467` | 7.5:1 ✓ | Secondary text |
| `--color-muted-light` | `#667085` | 5.7:1 ✓ | Tertiary text |

---

## Disclaimer

This portal is for **educational and research purposes only**.
All data is derived from publicly available regulatory disclosures (NSE SAST filings) and third-party financial data (Screener.in).
It does not constitute financial advice, investment recommendation, or a solicitation to buy or sell any security.
Past promoter activity does not guarantee future stock performance.
Always consult a SEBI-registered investment advisor before making any investment decision.
