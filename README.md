# RYB Finserv — NSE Promoter Buying Intelligence Portal

> **Research use only.** This platform is an independent research tool based on publicly available regulatory disclosures. It does not constitute financial advice. Always consult a SEBI-registered investment advisor before making investment decisions.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What the platform does](#2-what-the-platform-does)
3. [Pipeline architecture](#3-pipeline-architecture)
4. [Phase 1 — NSE Scraper](#4-phase-1--nse-scraper)
5. [Phase 2 — Analyzer & Enrichment](#5-phase-2--analyzer--enrichment)
6. [Scoring model](#6-scoring-model)
7. [Category classification](#7-category-classification)
8. [Portal — pages & features](#8-portal--pages--features)
9. [Promoter transaction analysis](#9-promoter-transaction-analysis)
10. [Output files](#10-output-files)
11. [Project structure](#11-project-structure)
12. [Quick start](#12-quick-start)
13. [Configuration reference](#13-configuration-reference)
14. [Design system](#14-design-system)
15. [Disclaimer](#15-disclaimer)

---

## 1. Overview

RYB Finserv tracks **NSE promoter market-buy filings** and combines promoter activity with price, technical and fundamental data to produce a scored and ranked stock shortlist.

The core thesis is:

> Promoter buying alone is not sufficient signal. The strongest setups combine promoter conviction + business earnings acceleration + price/technical confirmation.

The pipeline produces a reproducible **0–100 RYB Score** across promoter, fundamental, technical and risk signal groups.

Current pipeline release: **v1.2.1**.

---

## 2. What the platform does

```text
NSE regulatory filings (configurable filing window; default 3M)
          │
          ▼
  Phase 1 — Scraper
  ├─ Downloads insider-trading filings from NSE
  ├─ Identifies promoter / promoter-group activity
  └─ Produces raw transaction CSV
          │
          ▼
  Transaction normalisation
  ├─ Removes repeated/re-filed disclosures for the same economic transaction
  ├─ Preserves legitimate sequential transactions within the same filing
  └─ Restricts equity accumulation calculations to equity instruments
          │
          ▼
  Phase 2 — Analyzer
  ├─ Promoter market-buy aggregation
  ├─ Priced vs reported transaction validation
  ├─ Pledge detection
  ├─ Promoter market-sell analysis
  ├─ Sell / buy ratio exclusion (>25%)
  ├─ Promoter holding filter (≥60%)
  ├─ NSE price + DMA enrichment
  ├─ Screener.in fundamental enrichment
  └─ RYB scoring and category classification
          │
          ▼
  Reporter — Excel + CSV outputs
          │
          ▼
  Flask Portal — searchable, sortable, filterable research dashboard
```

---

## 3. Pipeline architecture

| Component | File | Purpose |
|---|---|---|
| Scraper | `nse_pipeline/scraper.py` | Playwright-based NSE insider-trading scraper |
| Analyzer | `nse_pipeline/analyzer.py` | Transaction normalisation, filtering, enrichment and scoring |
| Reporter | `nse_pipeline/reporter.py` | Excel + CSV output writer |
| Pipeline | `nse_pipeline/pipeline.py` | End-to-end orchestrator |
| Config | `nse_pipeline/config.py` | Thresholds, weights and runtime settings |
| Portal | `portal/app.py` | Flask web application and JSON APIs |

---

## 4. Phase 1 — NSE Scraper

**Source:** NSE corporate filings — insider trading / SAST disclosures.

- Uses **Playwright** with headless Chromium.
- Filing period is configurable: `1M | 3M | 6M | 1Y`; default is `3M`.
- Focuses the strategy on promoter, promoter-group and promoter/director categories.
- Market-purchase transactions are retained for the promoter accumulation analysis.
- Raw filings remain available for auditability.

### Initial value gate

A symbol enters the analysis universe when its **priced promoter market-buy value** reaches the configured minimum of **₹20 lakh**.

The analyzer distinguishes between:

- **Reported transactions** — all reported promoter market-buy rows.
- **Priced transactions** — rows with both positive transaction value and positive quantity.

Rows with missing/zero value or quantity remain part of the audit trail but do not contribute to weighted average price, priced purchase value, transaction counts used by the trading signal, or the ₹20 lakh value gate.

**Output:** `output/YYYY-MM-DD/nse_insider_trading_3m.csv`

---

## 5. Phase 2 — Analyzer & Enrichment

### 5.1 Transaction de-duplication

NSE may expose the same economic transaction through multiple filing URLs, including corrected or re-filed disclosures. The analyzer removes those repeated economic transactions **before aggregation and exclusion calculations** so promoter buy value, quantity and transaction counts are not inflated.

The transaction identity is based on core economic fields such as symbol, person, instrument, quantity, value, transaction type, transaction dates and acquisition/disposal mode. Holding-prior/post fields are deliberately not part of the identity because corrected filings can legitimately change those balances.

Legitimate sequential transactions contained within the **same filing** are preserved.

### 5.2 Promoter market-buy aggregation

Per-symbol aggregates include:

| Field | Meaning |
|---|---|
| `ReportedBuyTxn` | Count of reported promoter market-buy rows |
| `ReportedBuyQty` | Total quantity across reported buy rows |
| `PricedValuePurchased` | Value of buy rows with valid positive value and quantity |
| `NumBuyTxn` | Count of valid/priced buy transactions |
| `TotalQty` | Quantity from valid/priced buy transactions |
| `AvgPrice` | `PricedValuePurchased ÷ TotalQty` |
| `ValueCr` | `PricedValuePurchased ÷ 10,000,000` |
| `acqtoDt` | Latest promoter purchase date |
| `MissingValueQty` | Reported quantity minus valid/priced quantity |
| `MissingValueTxn` | Reported transaction count minus valid/priced transaction count |

`MissingValueQty` and `MissingValueTxn` are retained for audit and calculation diagnostics; they are not intended as primary investor-facing metrics.

### 5.3 Exclusion filters

The current strategy applies three important filters:

- **Pledge filter:** exclude symbols where promoter/promoter-group pledge creation or invocation is detected.
- **Market-sell filter:** promoter selling is **not automatically disqualifying**. The symbol remains eligible when promoter market selling is **≤25% of promoter market buying** by reported consideration.
- **Holding filter:** latest promoter shareholding must be at least **60%**.

A promoter market-sell ratio above the configured `MAX_SELL_BUY_RATIO_PCT` threshold is excluded because the selling materially contradicts the accumulation signal.

### 5.4 Promoter sell/buy analysis

For eligible symbols the analyzer calculates:

| Field | Calculation |
|---|---|
| `MarketBuyValue` | Priced promoter market-buy value |
| `MarketSellValue` | Priced promoter market-sale value |
| `NetBuyValue` | `MarketBuyValue − MarketSellValue` |
| `SellBuyRatioPct` | `MarketSellValue ÷ MarketBuyValue × 100` |
| `HasMarketSell` | `True` when market-sale value is positive |
| `SellBuyExclusion` | `True` when sell/buy ratio exceeds the configured limit |

This makes a distinction between **no selling**, **limited selling**, and **material selling** instead of treating every promoter sale as an automatic exclusion.

### 5.5 Price enrichment — NSE Bhavcopy

Current price is resolved from NSE Bhavcopy daily data.

- Downloaded once per run; symbol lookups are performed in memory.
- Supports `EQ`, `BE` and `BZ` series.
- Falls back to prior trading days when the latest file is unavailable.
- `PriceDiffPct = (LastPrice − AvgPrice) ÷ AvgPrice × 100`.

### 5.6 DMA & 6M return — NSE Bhavcopy history

- Lookback: 380 calendar days.
- Bhavcopy history downloads use 8 parallel workers.
- Closing prices are used for DMA calculations.
- `DMA50` = average of the latest 50 closes.
- `DMA200` = average of the latest 200 closes.
- `SixMonthReturn` uses approximately 126 trading days, with a minimum history requirement.

### 5.7 Fundamental enrichment — Screener.in

Fundamental data is parsed from Screener.in using `requests` + `BeautifulSoup`, including:

- Market Cap
- P/E
- Promoter Holding
- Revenue Growth
- EBITDA / Operating Profit Growth
- PAT Growth
- EPS Growth
- ROCE
- Debt / Equity
- Operating Cash Flow status
- Operating Profit Margin

Rate-limit protection uses two parallel workers, staggered requests, a 3.5-second fetch delay and exponential retry backoff for HTTP 429 responses.

---

## 6. Scoring model

The RYB Score combines four signal buckets:

```text
Promoter Signal       max 25
Fundamental Signal    max 35
Technical Signal      max 30
Risk deductions       max -10
────────────────────────────
RYB Score             0–100
```

### Promoter Signal — max 25

| Signal | Points | Condition |
|---|---:|---|
| Market Buy present | +5 | Promoter market purchase exists |
| Multi-transaction | +3 | `NumBuyTxn ≥ 3` |
| High conviction | +5 | Buy value ≥ 0.25% of market cap |
| Holding >65% | +5 | Latest promoter holding >65% |
| No insider sell | +2 | No promoter market sale |
| No pledge | +5 | No pledge creation/invocation |

### Fundamental Signal — max 35

| Signal | Points | Condition |
|---|---:|---|
| Revenue Growth | +5 | >15% |
| EBITDA Growth | +5 | >15% |
| PAT Growth | +7 | >15% |
| EPS Growth | +5 | >15% |
| ROCE | +4 | >15% |
| D/E | +3 | <0.5 |
| Positive OCF | +6 | Latest operating cash flow positive |

### Technical Signal — max 30

| Signal | Points | Condition |
|---|---:|---|
| Price > Promoter Avg | +5 | Current price above weighted promoter purchase price |
| Price > 50 DMA | +5 | Current price above 50-day DMA |
| Price > 200 DMA | +5 | Current price above 200-day DMA |
| Golden Cross | +5 | 50 DMA > 200 DMA |
| Volume expansion | +5 | Expansion proxy satisfied |
| Relative strength | +5 | Positive 6-month return |

### Risk deductions — max -10

| Risk | Points | Condition |
|---|---:|---|
| Pledge | -5 | Promoter pledge detected |
| Thin margin | -2 | OPM <5% |
| High PE | -3 | P/E >60× |

---

## 7. Category classification

| Category | Score | Meaning |
|---|---:|---|
| **Strong Buy Setup** | ≥65 | Strong promoter + fundamental + technical alignment |
| **Buy on Breakout** | ≥50 | Strong combined setup needing technical confirmation |
| **Watchlist** | ≥40 | Mixed signals requiring monitoring |
| **Fundamental Watch** | ≥30 | Fundamental strength but weaker technical confirmation |
| **Avoid** | <30 | Insufficient overall conviction |

---

## 8. Portal — pages & features

### Homepage (`/`)

- Latest scan statistics and category distribution.
- Above/below promoter reference price view.
- Top stocks by RYB Score.
- Research history across scan dates.

### Scan Detail (`/scan/YYYY-MM-DD`)

The scan page provides:

- Quality shortlist and all-reviewed candidate views.
- Search by symbol/company.
- Category and price-proximity filters.
- Sortable columns.
- RYB score and score breakdown.
- Fundamental snapshot.
- Promoter transaction history.
- Keyboard-accessible navigation and accessible drawer controls.

### Stock detail API

`GET /api/scan/<date_str>/stock/<symbol>` returns the detailed stock record.

The endpoint first checks the shortlisted dataset and falls back to `enriched_full.csv` when the requested symbol is not shortlisted. This allows detailed inspection of non-shortlisted candidates without changing the scoring or filtering logic.

`GET /api/scan/<date_str>/summary` provides shortlist/candidate summary data.

`GET /healthz` provides a lightweight application health check and returns HTTP 200 when the Flask application is running.

---

## 9. Promoter transaction analysis

The portal data layer now exposes a dedicated transaction-analysis dataset for each stock.

### Transaction summary fields

| Field | Description |
|---|---|
| `reported_buy_txn` | Number of reported promoter buy transactions |
| `priced_value_purchased` | Valid/priced purchase value |
| `market_buy_value` | Promoter market-buy value |
| `market_sell_value` | Promoter market-sale value |
| `net_buy_value` | Market buys less market sells |
| `sell_buy_ratio_pct` | Market sell value as % of market buy value |
| `has_market_sell` | Whether any priced promoter market sale exists |
| `sell_buy_exclusion` | Whether the sell/buy threshold is breached |

The detailed transaction list is loaded from `promoter_trades.csv` and is ordered with the **most recent transaction first**, using `Date To` and falling back to `Date From`.

The transaction-analysis fields are sourced from `enriched_full.csv` and merged into the stock-detail response without changing the existing score, fundamental or technical fields.

`MissingValueQty` and `MissingValueTxn` remain available in the data layer for audit/calculation purposes but are not primary investor-facing metrics.

---

## 10. Output files

Each pipeline run creates `output/YYYY-MM-DD/`.

| File | Contents |
|---|---|
| `nse_insider_trading_3m.csv` | Raw NSE insider-trading filing data |
| `enriched_analysis.xlsx` | Scored workbook |
| `enriched_full.csv` | Full candidate dataset with enrichment and transaction-analysis fields |
| `promoter_trades.csv` | Individual promoter transaction rows used by portal drill-down |
| `meta.json` | Run metadata, counts, duration and pipeline information |
| `run_log.txt` | Pipeline execution log |
| `failed_urls.txt` | Filing URLs that failed during scraping |

### Important enriched columns

`Symbol`, `CompanyName`, `AvgPrice`, `LastPrice`, `PriceDiffPct`, `ValueCr`, `NumBuyTxn`, `ReportedBuyTxn`, `ReportedBuyQty`, `PricedValuePurchased`, `MissingValueQty`, `MissingValueTxn`, `MarketBuyValue`, `MarketSellValue`, `NetBuyValue`, `SellBuyRatioPct`, `HasMarketSell`, `SellBuyExclusion`, `PromoHolding`, `HasPledging`, `MarketCapCr`, `PromoConvictionPct`, `PE`, `RevGrowthPct`, `EBITDAGrowthPct`, `PATGrowthPct`, `EPSGrowthPct`, `ROCEPct`, `DE_Ratio`, `OCFPositive`, `OPMPct`, `DMA50`, `DMA200`, `SixMonthReturn`, `ScorePromo`, `ScoreFund`, `ScoreTech`, `ScoreRisk`, `Score`, `Category`.

---

## 11. Project structure

```text
nse-insider-pipeline/
│
├── nse_pipeline/
│   ├── __init__.py
│   ├── config.py          ← thresholds, weights and runtime settings
│   ├── scraper.py         ← Phase 1: Playwright NSE scraper
│   ├── analyzer.py        ← transaction normalisation, enrichment, scoring
│   ├── reporter.py        ← Excel + CSV writer
│   └── pipeline.py        ← orchestrator
│
├── portal/
│   ├── app.py             ← Flask app, routes and JSON APIs
│   ├── README.md          ← portal-specific notes
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── scan.html
│   │   └── 404.html
│   └── static/
│       ├── css/main.css
│       └── js/
│           ├── main.js
│           └── scan.js
│
├── output/
│   └── YYYY-MM-DD/        ← dated pipeline results
├── snapshots/             ← portal backups before major changes
├── run_portal.bat         ← Windows portal launcher
├── run_portal.sh          ← Linux/macOS portal launcher
├── run_pipeline.bat       ← Windows full-pipeline launcher
└── requirements.txt
```

---

## 12. Quick start

### Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### Run the portal

**Windows:**

```bat
run_portal.bat
```

**Linux / macOS:**

```bash
bash run_portal.sh
```

Then open `http://localhost:5000`.

For direct Flask execution from the project root:

```bash
python portal/app.py
```

### Run the full pipeline

**Windows:**

```bat
run_pipeline.bat
```

**Linux / macOS:**

```bash
python -m nse_pipeline.pipeline
```

The pipeline duration depends primarily on the number of candidate symbols and Screener.in rate limiting.

---

## 13. Configuration reference

Key settings are in `nse_pipeline/config.py`.

| Parameter | Default | Description |
|---|---:|---|
| `MIN_PURCHASE_VALUE` | ₹20,00,000 | Minimum priced promoter buy value per symbol |
| `MAX_SELL_BUY_RATIO_PCT` | 25% | Exclude when promoter market sells exceed 25% of market buys |
| `MIN_PROMO_HOLDING` | 60% | Minimum latest-quarter promoter holding |
| `NSE_FILING_PERIOD` | `3M` | Filing window: `1M`, `3M`, `6M`, `1Y` |
| `SCRAPER_WORKERS` | 4 | Parallel NSE detail-page workers |
| `HOLDING_WORKERS` | 2 | Parallel Screener holding workers |
| `HOLDING_FETCH_DELAY` | 3.5s | Delay between Screener requests |
| `HOLDING_RETRY_COUNT` | 3 | Retries for HTTP 429 responses |

Scoring weights and category thresholds are also centrally maintained in `config.py`.

---

## 14. Design system

The portal uses a restrained research-dashboard visual language with:

- Neutral surfaces and a blue primary brand colour.
- RYB red/yellow/blue reserved for signal identity.
- Compact typography and metric grids for information density.
- WCAG-oriented contrast targets.
- Keyboard-accessible tabs and drawers.
- `aria-sort`, `aria-expanded` and `aria-controls` semantics.
- `prefers-reduced-motion` and `prefers-contrast: more` support.

---

## 15. Disclaimer

This portal is for **educational and research purposes only**.

All data is derived from publicly available regulatory disclosures and third-party financial data. It does not constitute financial advice, investment recommendation, or a solicitation to buy or sell any security. Past promoter activity does not guarantee future stock performance.

Always consult a SEBI-registered investment advisor before making any investment decision.
