# RYB Finserv — Web Portal

A lightweight Flask portal that serves all **NSE promoter insider-scan results** from the `output/` folder as a clean, searchable, sortable web interface.

---

## Quick Start

### Windows

```
Double-click  run_portal.bat
```

Then open **http://localhost:5000** in your browser.

### Linux / macOS

```bash
bash run_portal.sh
```

---

## What it shows

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | All scan dates with shortlist counts and quick stats |
| Scan Detail | `/scan/YYYY-MM-DD` | Full shortlist table + all-candidates table for that run |

### Scan Detail features

- **Shortlist tab** — stocks that passed all four quality gates (promoter holding ≥ 60%, no pledging, no market sell, buy value ≥ ₹20 L)
- **All Candidates tab** — every symbol that passed pledge & sell filters (before the 60% holding cut)
- **Column sorting** — click any column header to sort ascending / descending
- **Search** — filter by symbol or company name (debounced)
- **Band filter chips** — filter by price proximity to promoter avg buy (±10%, ±20%, ±30%, >30%, or "Below buy price")
- **NSE links** — every symbol links directly to its NSE quote page

---

## Portal structure

```
portal/
├── app.py                  Flask application + routes
├── templates/
│   ├── base.html           Sticky header, nav, footer, skip-link
│   ├── index.html          Dashboard / scan history
│   ├── scan.html           Scan detail (tabs, tables, filters)
│   └── 404.html            Not-found page
└── static/
    ├── css/main.css        Design-token-driven stylesheet (no external deps)
    └── js/
        ├── main.js         Nav toggle
        └── scan.js         Sort / search / filter logic
```

---

## Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Port | `PORT` env var or `portal/app.py` | `5000` |
| Output root | `OUTPUT_DIR` in `portal/app.py` | `output/` (repo root) |

---

## Disclaimer

This portal is for **educational and research purposes only**.  
It does not constitute financial advice.  
Always consult a SEBI-registered financial advisor before investing.
