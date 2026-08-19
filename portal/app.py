"""
RYB Finserv – NSE Insider Scan Portal
Flask application — serves backdated scan results from output/
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Flask, abort, jsonify, render_template, request
from markupsafe import Markup

log = logging.getLogger(__name__)

# ── path setup ────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent          # repo root
OUTPUT_DIR = BASE_DIR / "output"
_CSS_PATH  = Path(__file__).parent / "static" / "css" / "main.css"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)


# ── Static asset content-hashes for cache-busting (computed once at startup) ──
_STATIC_DIR = Path(__file__).parent / "static"

def _file_hash(p: Path) -> str:
    try:
        return hashlib.md5(p.read_bytes()).hexdigest()[:8]
    except Exception:
        return "1"

_CSS_VERSION     = _file_hash(_CSS_PATH)
_MAIN_JS_VERSION = _file_hash(_STATIC_DIR / "js" / "main.js")
_SCAN_JS_VERSION = _file_hash(_STATIC_DIR / "js" / "scan.js")


# ── RYB logo SVG ─────────────────────────────────────────────────────────────
def _ryb_watermark_svg() -> Markup:
    """
    Full-viewport RYB watermark — three filled overlapping circles with
    correct RYB mixed colours in every intersection zone, mirroring the
    logo exactly.  Rendered at very low opacity so it never obscures UI.

    Paint order (back → front) to get correct overlap colours:
      1. Red, Yellow, Blue base circles (pure zones)
      2. Red∩Yellow = Orange  (clip Red, paint Yellow circle)
      3. Red∩Blue   = Violet  (clip Red, paint Blue circle)
      4. Yellow∩Blue= Green   (clip Yellow, paint Blue circle)
      5. All three  = Brown   (clip Red∩Yellow, paint Blue circle)
    """
    size  = 1000
    pad   = size * 0.047
    ratio = 1.1
    avail = size - 2 * pad

    r = min(avail / (ratio + 2),
            avail / (ratio * math.sqrt(3) / 2 + 2))
    s   = r * ratio
    h   = s * math.sqrt(3) / 2
    ctv = h * 2 / 3

    cx = size / 2
    cy = ((pad + ctv + r) + (size - pad - ctv / 2 - r)) / 2

    bx, by = cx,         cy - ctv       # Blue   — top
    rx, ry = cx - s / 2, cy + ctv / 2  # Red    — bottom-left
    yx, yy = cx + s / 2, cy + ctv / 2  # Yellow — bottom-right

    def c(x, y):
        return f'cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"'

    i = "wm"  # unique id suffix so clip-path IDs don't clash with the logo

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {size} {size}" '
        f'aria-hidden="true" focusable="false" '
        f'style="position:fixed;top:0;left:0;width:100vw;height:100vh;'
        f'pointer-events:none;z-index:0;opacity:0.03;overflow:visible;">'

        f'<defs>'
        f'<clipPath id="cRwm"><circle {c(rx,ry)}/></clipPath>'
        f'<clipPath id="cYwm"><circle {c(yx,yy)}/></clipPath>'
        f'<clipPath id="cBwm"><circle {c(bx,by)}/></clipPath>'
        f'</defs>'

        # 1 — pure base circles
        f'<circle {c(rx,ry)} fill="#e32636"/>'   # Red
        f'<circle {c(yx,yy)} fill="#f5c800"/>'   # Yellow
        f'<circle {c(bx,by)} fill="#1a56db"/>'   # Blue

        # 2 — Red ∩ Yellow = Orange
        f'<g clip-path="url(#cRwm)"><circle {c(yx,yy)} fill="#ff8c00"/></g>'

        # 3 — Red ∩ Blue = Violet
        f'<g clip-path="url(#cRwm)"><circle {c(bx,by)} fill="#7b2d8b"/></g>'

        # 4 — Yellow ∩ Blue = Green
        f'<g clip-path="url(#cYwm)"><circle {c(bx,by)} fill="#2e8b57"/></g>'

        # 5 — Red ∩ Yellow ∩ Blue = Brown
        f'<g clip-path="url(#cRwm)"><g clip-path="url(#cYwm)">'
        f'<circle {c(bx,by)} fill="#6b3a2a"/>'
        f'</g></g>'

        f'</svg>'
    )
    return Markup(svg)


def _ryb_logo_svg(size: int = 32, id_suffix: str = "a") -> Markup:
    """
    Three overlapping circles — Red (left), Yellow (right), Blue (top) —
    arranged so their centres form an equilateral triangle.
    All circles are fully visible within the canvas with padding on every side.
    Intersection zones filled with the correct RYB mixed colour:
      Red  + Yellow  = Orange   #ff8c00
      Red  + Blue    = Violet   #7b2d8b
      Yellow + Blue  = Green    #2e8b57
      All three      = Brown    #6b3a2a
    Pure zones: Red #e32636, Yellow #f5c800, Blue #1a56db
    """
    pad = size * 0.047          # ~1.5 px on 32 px canvas
    ratio = 1.1                  # triangle side = r * ratio (controls overlap)
    avail = size - 2 * pad

    # max r so bounding box fits: width = (ratio+2)*r, height = (ratio*√3/2+2)*r
    r = min(avail / (ratio + 2),
            avail / (ratio * math.sqrt(3) / 2 + 2))
    s = r * ratio                           # equilateral triangle side
    h = s * math.sqrt(3) / 2               # triangle height
    ctv = h * 2 / 3                        # centroid → vertex distance

    # Vertically centre the bounding box within the canvas
    cx = size / 2
    cy = ((pad + ctv + r) + (size - pad - ctv / 2 - r)) / 2

    # Blue  : top vertex
    bx, by = cx, cy - ctv
    # Red   : bottom-left vertex
    rx, ry = cx - s / 2, cy + ctv / 2
    # Yellow: bottom-right vertex
    yx, yy = cx + s / 2, cy + ctv / 2

    def c(x, y):
        return f"cx='{x:.3f}' cy='{y:.3f}' r='{r:.3f}'"

    i = id_suffix   # short alias for unique clip-path IDs

    svg = f"""<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="RYB logo">
  <defs>
    <!-- clip paths for each circle -->
    <clipPath id="cR{i}"><circle {c(rx,ry)}/></clipPath>
    <clipPath id="cY{i}"><circle {c(yx,yy)}/></clipPath>
    <clipPath id="cB{i}"><circle {c(bx,by)}/></clipPath>
    <!-- two-circle intersections -->
    <clipPath id="cRY{i}"><circle {c(rx,ry)}/></clipPath>
    <clipPath id="cRB{i}"><circle {c(rx,ry)}/></clipPath>
    <clipPath id="cYB{i}"><circle {c(yx,yy)}/></clipPath>
    <!-- three-circle intersection -->
    <clipPath id="cRYB{i}"><circle {c(rx,ry)}/></clipPath>
  </defs>

  <!-- ── 1. Pure circle zones (draw first, intersections painted over) ── -->
  <circle {c(rx,ry)} fill="#e32636"/>
  <circle {c(yx,yy)} fill="#f5c800"/>
  <circle {c(bx,by)} fill="#1a56db"/>

  <!-- ── 2. Red ∩ Yellow = Orange (clip to Red, paint Yellow circle) ── -->
  <g clip-path="url(#cRY{i})">
    <circle {c(yx,yy)} fill="#ff8c00"/>
  </g>

  <!-- ── 3. Red ∩ Blue = Violet (clip to Red, paint Blue circle) ── -->
  <g clip-path="url(#cRB{i})">
    <circle {c(bx,by)} fill="#7b2d8b"/>
  </g>

  <!-- ── 4. Yellow ∩ Blue = Green (clip to Yellow, paint Blue circle) ── -->
  <g clip-path="url(#cYB{i})">
    <circle {c(bx,by)} fill="#2e8b57"/>
  </g>

  <!-- ── 5. Red ∩ Yellow ∩ Blue = Brown (clip to Red, then Y∩B inside) ── -->
  <g clip-path="url(#cRYB{i})">
    <g clip-path="url(#cY{i})">
      <circle {c(bx,by)} fill="#6b3a2a"/>
    </g>
  </g>
</svg>"""
    return Markup(svg)


@app.context_processor
def inject_globals():
    return {
        "now_year"         : datetime.now(timezone.utc).year,
        "ryb_logo_svg"     : _ryb_logo_svg,
        "ryb_watermark_svg": _ryb_watermark_svg(),
        "css_version"      : _CSS_VERSION,
        "main_js_version"  : _MAIN_JS_VERSION,
        "scan_js_version"  : _SCAN_JS_VERSION,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _file_mtime(p: Path) -> float:
    """Return mtime of *p*, or 0.0 if it doesn't exist."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


@lru_cache(maxsize=64)
def _cached_excel(path_str: str, _mtime: float) -> pd.DataFrame | None:
    """Load ScoredStocks sheet (preferred) or FilteredStocks (legacy fallback).
    Keyed by path + mtime so stale data is never served."""
    try:
        xl = pd.ExcelFile(path_str)
        sheet = "ScoredStocks" if "ScoredStocks" in xl.sheet_names else "FilteredStocks"
        return xl.parse(sheet)
    except Exception as e:
        log.warning("Could not read excel %s: %s", path_str, e)
        return None


@lru_cache(maxsize=64)
def _cached_csv(path_str: str, _mtime: float) -> pd.DataFrame | None:
    """Load enriched_full CSV; keyed by path + mtime."""
    try:
        return pd.read_csv(path_str, encoding="utf-8-sig")
    except Exception as e:
        log.warning("Could not read csv %s: %s", path_str, e)
        return None


@lru_cache(maxsize=64)
def _cached_meta(path_str: str, _mtime: float) -> dict | None:
    """Load meta.json; keyed by path + mtime."""
    try:
        return json.loads(Path(path_str).read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Could not read meta %s: %s", path_str, e)
        return None


def _load_filtered(date_str: str) -> pd.DataFrame | None:
    p = OUTPUT_DIR / date_str / "enriched_analysis.xlsx"
    if not p.exists():
        return None
    return _cached_excel(str(p), _file_mtime(p))


def _load_full(date_str: str) -> pd.DataFrame | None:
    p = OUTPUT_DIR / date_str / "enriched_full.csv"
    if not p.exists():
        return None
    return _cached_csv(str(p), _file_mtime(p))


def _load_meta(date_str: str) -> dict | None:
    p = OUTPUT_DIR / date_str / "meta.json"
    if not p.exists():
        return None
    return _cached_meta(str(p), _file_mtime(p))


@lru_cache(maxsize=64)
def _cached_trades(path_str: str, _mtime: float) -> dict | None:
    """Load promoter_trades.csv → dict {SYMBOL: [row, …]}; keyed by path + mtime."""
    try:
        df = pd.read_csv(path_str, encoding="utf-8-sig", dtype=str).fillna("")
        df.columns = df.columns.str.strip()

        # Always expose the most recent promoter transaction first.
        # Prefer Date To; fall back to Date From when Date To is unavailable.
        date_col = "__transaction_date"
        date_to = (
            pd.to_datetime(df.get("Date To", ""), format="%d-%m-%Y", errors="coerce")
            if "Date To" in df.columns
            else pd.Series(pd.NaT, index=df.index)
        )
        date_from = (
            pd.to_datetime(df.get("Date From", ""), format="%d-%m-%Y", errors="coerce")
            if "Date From" in df.columns
            else pd.Series(pd.NaT, index=df.index)
        )

        df[date_col] = date_to.fillna(date_from)

        # Stable descending sort: transactions with the latest date appear first,
        # while transactions on the same date retain their original CSV order.
        df = df.sort_values(
            by=date_col,
            ascending=False,
            na_position="last",
            kind="stable",
        )

        trades: dict[str, list] = {}
        for r in df.to_dict(orient="records"):
            sym = r.get("Symbol", "").strip()
            if sym:
                r.pop(date_col, None)
                trades.setdefault(sym, []).append(r)

        return trades
    except Exception as e:
        log.warning("Could not read trades %s: %s", path_str, e)
        return None


def _load_trades(date_str: str) -> dict | None:
    p = OUTPUT_DIR / date_str / "promoter_trades.csv"
    if not p.exists():
        return None
    return _cached_trades(str(p), _file_mtime(p))


def _scan_dates() -> list[dict]:
    """Return sorted list of scan-date metadata dicts (newest first)."""
    dates = []
    if not OUTPUT_DIR.exists():
        return dates
    for d in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        try:
            dt = datetime.strptime(d.name, "%Y-%m-%d")
        except ValueError:
            continue

        has_excel = (d / "enriched_analysis.xlsx").exists()
        has_full  = (d / "enriched_full.csv").exists()

        # Skip scrape-only runs (no enriched results at all)
        if not has_excel and not has_full:
            continue

        # Prefer meta.json counts; fall back to reading files directly
        meta = _load_meta(d.name)
        if meta:
            shortlist  = meta.get("shortlisted", 0)
            candidates = meta.get("candidates", 0)
        else:
            shortlist  = 0
            candidates = 0
            if has_excel:
                df = _load_filtered(d.name)
                if df is not None:
                    shortlist = len(df)
            if has_full:
                df_full = _load_full(d.name)
                if df_full is not None:
                    candidates = len(df_full)

        dates.append({
            "date_str"  : d.name,
            "display"   : dt.strftime("%d %b %Y"),
            "weekday"   : dt.strftime("%A"),
            "has_excel" : has_excel,
            "has_full"  : has_full,
            "shortlist" : shortlist,
            "candidates": candidates,
        })
    return dates


def _band_label(pct: float) -> str:
    a = abs(pct)
    if a <= 10:
        return "within10"
    if a <= 20:
        return "within20"
    if a <= 30:
        return "within30"
    return "beyond30"


# Category → CSS class suffix
_CATEGORY_CSS = {
    "Strong Buy Setup"  : "strong-buy",
    "Buy on Breakout"   : "buy-breakout",
    "Watchlist"         : "watchlist",
    "Fundamental Watch" : "fund-watch",
    "Avoid"             : "avoid",
}


def _clean(v):
    """Convert NaN/Inf float values to None so json.dumps emits null, not NaN.
    NaN is not valid JSON and causes JSON.parse to throw in the browser,
    which silently breaks all JS filtering and sorting."""
    import math
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _all_signals(r: dict) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """
    Derive all four signal groups from a row dict so the score breakdown panel
    can display each section's bar and its contributing sub-signals side-by-side.

    Each item: { label, pts, triggered, note }

    Promoter (max 25):  buy present +5, multi-txn +3, conviction +5,
                        holding>65% +5, no sell +2, no pledge +5
    Fundamental (max 35): rev>15% +5, ebitda>15% +5, pat>15% +7,
                           eps>15% +5, roce>15% +4, de<0.5 +3, ocf+ +6
    Technical (max 30): price>avg +5, >50DMA +5, >200DMA +5,
                        golden cross +5, vol expansion +5, rel strength +5
    Risk deductions (max −10): pledge −5, thin margin −2, high PE −3
    """
    # raw values
    last_price  = _clean(r.get("LastPrice"))  or 0.0
    avg_price   = _clean(r.get("AvgPrice"))   or 0.0
    pct         = float(r.get("PriceDiffPct") or 0)
    num_txn     = int(r.get("NumBuyTxn") or 0)
    value_cr    = _clean(r.get("ValueCr"))    or 0.0
    holding     = _clean(r.get("PromoHolding")) or 0.0
    market_cap  = _clean(r.get("MarketCapCr"))
    has_pledge  = bool(r.get("HasPledging", False))
    has_sell    = bool(r.get("HasMarketSell", False))
    dma50       = _clean(r.get("DMA50"))
    dma200      = _clean(r.get("DMA200"))
    six_m       = _clean(r.get("SixMonthReturn"))
    opm         = _clean(r.get("OPMPct"))
    pe          = _clean(r.get("PE"))
    rev_g       = _clean(r.get("RevGrowthPct"))
    ebi_g       = _clean(r.get("EBITDAGrowthPct"))
    pat_g       = _clean(r.get("PATGrowthPct"))
    eps_g       = _clean(r.get("EPSGrowthPct"))
    roce        = _clean(r.get("ROCEPct"))
    de          = _clean(r.get("DE_Ratio"))
    ocf         = r.get("OCFPositive")
    conv_pct    = _clean(r.get("PromoConvictionPct"))

    # conviction check
    if market_cap and market_cap > 0:
        conviction_ok = (value_cr / market_cap * 100) >= 0.25
    else:
        conviction_ok = value_cr >= 10

    # ── Promoter signals ──────────────────────────────────────────────────────
    promo_signals = [
        {
            "label"    : "Market Buy",
            "pts"      : 5,
            "triggered": True,          # always true — universe filter guarantees this
            "note"     : f"₹{value_cr:.2f} Cr bought",
        },
        {
            "label"    : "Multi-transaction",
            "pts"      : 3,
            "triggered": num_txn >= 3,
            "note"     : f"{num_txn} buy txn" + (" ≥3 ✓" if num_txn >= 3 else " (need ≥3)"),
        },
        {
            "label"    : "High conviction",
            "pts"      : 5,
            "triggered": conviction_ok,
            "note"     : (f"{conv_pct:.3f}% of mkt cap" if conv_pct is not None
                          else (f"₹{value_cr:.1f} Cr abs." if value_cr >= 10 else "< 0.25% of mkt cap")),
        },
        {
            "label"    : "Holding > 65%",
            "pts"      : 5,
            "triggered": holding > 65,
            "note"     : f"{holding:.1f}%",
        },
        {
            "label"    : "No insider sell",
            "pts"      : 2,
            "triggered": not has_sell,
            "note"     : "No market sell" if not has_sell else "Market sell detected",
        },
        {
            "label"    : "No pledge",
            "pts"      : 5,
            "triggered": not has_pledge,
            "note"     : "No pledge" if not has_pledge else "Pledge detected",
        },
    ]

    # ── Fundamental signals ───────────────────────────────────────────────────
    def _fmt_g(v, threshold=15):
        if v is None: return "N/A"
        return f"{v:+.1f}%" + (" ✓" if v > threshold else f" (need >{threshold}%)")

    fund_signals = [
        {
            "label"    : "Revenue growth",
            "pts"      : 5,
            "triggered": rev_g is not None and rev_g > 15,
            "note"     : _fmt_g(rev_g),
        },
        {
            "label"    : "EBITDA growth",
            "pts"      : 5,
            "triggered": ebi_g is not None and ebi_g > 15,
            "note"     : _fmt_g(ebi_g),
        },
        {
            "label"    : "PAT growth",
            "pts"      : 7,
            "triggered": pat_g is not None and pat_g > 15,
            "note"     : _fmt_g(pat_g),
        },
        {
            "label"    : "EPS growth",
            "pts"      : 5,
            "triggered": eps_g is not None and eps_g > 15,
            "note"     : _fmt_g(eps_g),
        },
        {
            "label"    : "ROCE > 15%",
            "pts"      : 4,
            "triggered": roce is not None and roce > 15,
            "note"     : (f"{roce:.1f}%" if roce is not None else "N/A"),
        },
        {
            "label"    : "D/E < 0.5",
            "pts"      : 3,
            "triggered": de is not None and de < 0.5,
            "note"     : (f"D/E {de:.2f}" if de is not None else "N/A"),
        },
        {
            "label"    : "Positive OCF",
            "pts"      : 6,
            "triggered": ocf is True,
            "note"     : ("Positive" if ocf is True else ("Negative" if ocf is False else "N/A")),
        },
    ]

    # ── Technical signals ─────────────────────────────────────────────────────
    sig_above_ref    = bool(last_price > avg_price > 0)
    sig_above_50dma  = bool(dma50  and last_price > dma50)
    sig_above_200dma = bool(dma200 and last_price > dma200)
    sig_golden       = bool(dma50  and dma200 and dma50 > dma200)
    sig_vol          = bool(pct > 5 and num_txn >= 2)
    if six_m is not None:
        sig_rel  = bool(six_m > 0)
        rel_note = f"6M return {six_m:+.1f}%"
    else:
        sig_rel  = bool(pct > 10)
        rel_note = f"price {pct:+.1f}% vs ref (proxy)"

    tech_signals = [
        {
            "label"    : "Price > Promoter Avg",
            "pts"      : 5,
            "triggered": sig_above_ref,
            "note"     : (f"₹{last_price:.2f} vs ₹{avg_price:.2f}"
                          if avg_price > 0 else "avg price unavailable"),
        },
        {
            "label"    : "Price > 50 DMA",
            "pts"      : 5,
            "triggered": sig_above_50dma,
            "note"     : (f"₹{last_price:.2f} vs ₹{dma50:.2f}"
                          if dma50 else "N/A"),
        },
        {
            "label"    : "Price > 200 DMA",
            "pts"      : 5,
            "triggered": sig_above_200dma,
            "note"     : (f"₹{last_price:.2f} vs ₹{dma200:.2f}"
                          if dma200 else "N/A"),
        },
        {
            "label"    : "Golden Cross",
            "pts"      : 5,
            "triggered": sig_golden,
            "note"     : (f"50DMA {dma50:.0f} > 200DMA {dma200:.0f}"
                          if (dma50 and dma200) else "N/A"),
        },
        {
            "label"    : "Vol. expansion",
            "pts"      : 5,
            "triggered": sig_vol,
            "note"     : f"{pct:+.1f}% · {num_txn} txn",
        },
        {
            "label"    : "Rel. strength",
            "pts"      : 5,
            "triggered": sig_rel,
            "note"     : rel_note,
        },
    ]

    # ── Risk deductions ───────────────────────────────────────────────────────
    risk_signals = [
        {
            "label"    : "No pledge",
            "pts"      : -5,
            "triggered": has_pledge,
            "note"     : "Pledge detected" if has_pledge else "Clear",
        },
        {
            "label"    : "OPM ≥ 5%",
            "pts"      : -2,
            "triggered": bool(opm is not None and opm < 5),
            "note"     : (f"OPM {opm:.1f}% — thin" if (opm is not None and opm < 5)
                          else (f"OPM {opm:.1f}%" if opm is not None else "N/A")),
        },
        {
            "label"    : "PE ≤ 60",
            "pts"      : -3,
            "triggered": bool(pe is not None and pe > 60),
            "note"     : (f"PE {pe:.1f} — high" if (pe is not None and pe > 60)
                          else (f"PE {pe:.1f}" if pe is not None else "N/A")),
        },
    ]

    return promo_signals, fund_signals, tech_signals, risk_signals


def _df_to_rows(df: pd.DataFrame, include_flags: bool = False) -> list[dict]:
    """Convert a DataFrame to the row-dict format used by templates.
    Uses to_dict('records') for speed instead of iterrows().
    Each row includes _row_index (0-based position) so scan.js can do
    position-based DOM matching rather than symbol-based (handles duplicates).
    All float NaN/Inf values are sanitised to None → JSON null.
    """
    rows = []
    for idx, r in enumerate(df.to_dict(orient="records")):
        pct      = float(r.get("PriceDiffPct") or 0)
        score    = r.get("Score")
        category = r.get("Category") or ""

        promo_sigs, fund_sigs, tech_sigs, risk_sigs = _all_signals(r)

        entry = {
            "_row_index"         : idx,
            "symbol"             : r.get("Symbol", ""),
            "company"            : r.get("CompanyName", ""),
            "last_price"         : _clean(r.get("LastPrice")),
            "avg_price"          : _clean(r.get("AvgPrice")),
            "price_diff_pct"     : pct,
            "promo_holding"      : _clean(r.get("PromoHolding")),
            "value_cr"           : _clean(r.get("ValueCr")),
            "num_buy_txn"        : r.get("NumBuyTxn"),
            "reported_buy_txn"       : r.get("ReportedBuyTxn"),
            "priced_value_purchased" : _clean(r.get("PricedValuePurchased")),
            "missing_value_qty"      : _clean(r.get("MissingValueQty")),
            "missing_value_txn"      : r.get("MissingValueTxn"),
            "market_buy_value"       : _clean(r.get("MarketBuyValue")),
            "market_sell_value"      : _clean(r.get("MarketSellValue")),
            "net_buy_value"          : _clean(r.get("NetBuyValue")),
            "sell_buy_ratio_pct"     : _clean(r.get("SellBuyRatioPct")),
            "has_market_sell"        : bool(r.get("HasMarketSell", False)),
            "sell_buy_exclusion"     : bool(r.get("SellBuyExclusion", False)),
            "acq_to_dt"          : r.get("acqtoDt", ""),
            "band"               : _band_label(pct),
            # scoring
            "score"              : int(score) if score is not None and str(score) not in ("", "nan") else None,
            "category"           : category,
            "category_css"       : _CATEGORY_CSS.get(category, ""),
            "score_promo"        : r.get("ScorePromo"),
            "score_fund"         : r.get("ScoreFund"),
            "score_tech"         : r.get("ScoreTech"),
            "score_risk"         : r.get("ScoreRisk"),
            # all four signal groups for the score breakdown panel
            "promo_signals"      : promo_sigs,
            "fund_signals"       : fund_sigs,
            "tech_signals"       : tech_sigs,
            "risk_signals"       : risk_sigs,
            # fundamentals — all may be NaN from pandas
            "market_cap_cr"      : _clean(r.get("MarketCapCr")),
            "pe"                 : _clean(r.get("PE")),
            "promo_conviction_pct": _clean(r.get("PromoConvictionPct")),
            "rev_growth_pct"     : _clean(r.get("RevGrowthPct")),
            "ebitda_growth_pct"  : _clean(r.get("EBITDAGrowthPct")),
            "pat_growth_pct"     : _clean(r.get("PATGrowthPct")),
            "eps_growth_pct"     : _clean(r.get("EPSGrowthPct")),
            "roce_pct"           : _clean(r.get("ROCEPct")),
            "de_ratio"           : _clean(r.get("DE_Ratio")),
            "ocf_positive"       : r.get("OCFPositive"),
            "opm_pct"            : _clean(r.get("OPMPct")),
            "six_month_return"   : _clean(r.get("SixMonthReturn")),
        }
        if include_flags:
            entry["has_pledging"] = bool(r.get("HasPledging", False))
            entry["has_sell"]     = bool(r.get("HasMarketSell", False))
        rows.append(entry)
    return rows


# ── routes ────────────────────────────────────────────────────────────────────

# Category display ordering + colours for the hero stats panel
_CAT_ORDER = [
    ("Strong Buy Setup",  "strong-buy",  "#16a34a"),
    ("Buy on Breakout",   "buy-breakout","#1a56db"),
    ("Watchlist",         "watchlist",   "#f5c800"),
    ("Fundamental Watch", "fund-watch",  "#ff8c00"),
    ("Avoid",             "avoid",       "#e32636"),
]


def _latest_stats(date_str: str) -> dict:
    """Compute hero-panel stats from the latest scan's ScoredStocks sheet.
    Returns a dict with keys:
      cat_breakdown  – list of {label, css, color, count, pct}  (only non-zero cats)
      above_ref      – int  (stocks where current > promoter avg)
      below_ref      – int
      total          – int
      score_avg      – float | None
      top3           – list of {symbol, score, category_css, diff_pct}
    Falls back to all-zero values when data is unavailable.
    """
    empty = dict(cat_breakdown=[], above_ref=0, below_ref=0,
                 total=0, score_avg=None, top3=[], featured=None)
    df = _load_filtered(date_str)
    if df is None or df.empty:
        return empty

    total = len(df)

    # ── category breakdown ────────────────────────────────────────────────────
    cat_counts: dict[str, int] = {}
    if "Category" in df.columns:
        cat_counts = df["Category"].value_counts().to_dict()

    cat_breakdown = []
    for label, css, color in _CAT_ORDER:
        cnt = cat_counts.get(label, 0)
        if cnt:
            cat_breakdown.append({
                "label": label,
                "css"  : css,
                "color": color,
                "count": cnt,
                "pct"  : round(cnt / total * 100),
            })

    # ── above / below promoter reference price ────────────────────────────────
    above_ref = below_ref = 0
    if "PriceDiffPct" in df.columns:
        pct_series = pd.to_numeric(df["PriceDiffPct"], errors="coerce").fillna(0)
        above_ref  = int((pct_series > 0).sum())
        below_ref  = int((pct_series <= 0).sum())

    # ── score average ─────────────────────────────────────────────────────────
    score_avg = None
    if "Score" in df.columns:
        s = pd.to_numeric(df["Score"], errors="coerce").dropna()
        if len(s):
            score_avg = round(float(s.mean()), 1)

    # ── top 3 by score ────────────────────────────────────────────────────────
    top3 = []
    if "Score" in df.columns:
        df2 = df.copy()
        df2["_score"] = pd.to_numeric(df2["Score"], errors="coerce")
        top_df = df2.nlargest(3, "_score")
        for _, row in top_df.iterrows():
            pct = float(row.get("PriceDiffPct") or 0)
            sc  = row.get("_score")
            cat = row.get("Category", "")
            top3.append({
                "symbol"      : row.get("Symbol", ""),
                "score"       : int(sc) if sc is not None and not math.isnan(sc) else None,
                "category_css": _CATEGORY_CSS.get(cat, ""),
                "diff_pct"    : round(pct, 1),
            })

    # ── featured signal ──────────────────────────────────────────────────────
    featured = None
    if top3:
        top_symbol = top3[0]["symbol"]
        top_match = df[df["Symbol"].astype(str) == str(top_symbol)]
        if not top_match.empty:
            row = top_match.iloc[0]
            featured = {
                "symbol": row.get("Symbol", ""),
                "company": row.get("CompanyName", ""),
                "score": top3[0]["score"],
                "category": row.get("Category", ""),
                "diff_pct": top3[0]["diff_pct"],
                "promo_holding": _clean(row.get("PromoHolding")),
                "value_cr": _clean(row.get("ValueCr")),
                "num_buy_txn": int(row.get("NumBuyTxn") or 0),
            }

    return dict(
        cat_breakdown=cat_breakdown,
        above_ref=above_ref,
        below_ref=below_ref,
        total=total,
        score_avg=score_avg,
        top3=top3,
        featured=featured,
    )


@app.route("/")
def index():
    dates = _scan_dates()
    total_scans     = len(dates)
    total_shortlist = sum(d["shortlist"] for d in dates)
    latest          = dates[0] if dates else None
    latest_stats    = _latest_stats(latest["date_str"]) if latest else {}
    return render_template(
        "index.html",
        dates=dates,
        total_scans=total_scans,
        total_shortlist=total_shortlist,
        latest=latest,
        latest_stats=latest_stats,
    )


def _validate_scan_date(date_str: str) -> datetime:
    """Validate a scan date and ensure its output directory exists."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        abort(404)
    if not (OUTPUT_DIR / date_str).is_dir():
        abort(404)
    return dt


def _row_summary(r: dict, idx: int, include_flags: bool = False) -> dict:
    """Small payload used by the scan list; detailed signals load on demand."""
    score = r.get("Score")
    entry = {
        "_row_index": idx,
        "symbol": r.get("Symbol", ""),
        "company": r.get("CompanyName", ""),
        "last_price": _clean(r.get("LastPrice")),
        "avg_price": _clean(r.get("AvgPrice")),
        "price_diff_pct": float(r.get("PriceDiffPct") or 0),
        "promo_holding": _clean(r.get("PromoHolding")),
        "value_cr": _clean(r.get("ValueCr")),
        "num_buy_txn": int(r.get("NumBuyTxn") or 0),
        "acq_to_dt": r.get("acqtoDt", ""),
        "score": int(score) if score is not None and str(score) not in ("", "nan") else None,
        "category": r.get("Category") or "",
        "category_css": _CATEGORY_CSS.get(r.get("Category") or "", ""),
        "band": _band_label(float(r.get("PriceDiffPct") or 0)),
    }
    if include_flags:
        entry["has_pledging"] = bool(r.get("HasPledging", False))
        entry["has_sell"] = bool(r.get("HasMarketSell", False))
    return entry


def _summary_rows(df: pd.DataFrame | None, include_flags: bool = False) -> list[dict]:
    if df is None or df.empty:
        return []
    return [_row_summary(r, idx, include_flags) for idx, r in enumerate(df.to_dict(orient="records"))]


@app.route("/scan/<date_str>")
def scan_detail(date_str: str):
    dt = _validate_scan_date(date_str)
    df_filtered = _load_filtered(date_str)
    df_full = _load_full(date_str)
    return render_template(
        "scan.html",
        date_str=date_str,
        display_date=dt.strftime("%d %b %Y"),
        weekday=dt.strftime("%A"),
        shortlist_count=len(df_filtered) if df_filtered is not None else 0,
        reviewed_count=len(df_full) if df_full is not None else 0,
    )


@app.get("/api/scan/<date_str>/summary")
def scan_summary(date_str: str):
    _validate_scan_date(date_str)
    view = request.args.get("view", "shortlist")
    if view == "candidates":
        rows = _summary_rows(_load_full(date_str), include_flags=True)
    else:
        rows = _summary_rows(_load_filtered(date_str), include_flags=False)
    return jsonify({"date": date_str, "view": view, "rows": rows})


@app.get("/api/scan/<date_str>/stock/<symbol>")
def scan_stock_detail(date_str: str, symbol: str):
    _validate_scan_date(date_str)
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 30 or not all(ch.isalnum() or ch in "&-_" for ch in symbol):
        abort(404)

    df = _load_filtered(date_str)

    if df is not None and not df.empty and "Symbol" in df.columns:
        matches = df[df["Symbol"].astype(str).str.upper() == symbol]
    else:
        matches = pd.DataFrame()

    # Non-shortlisted candidates must fall back to enriched_full.csv
    if matches.empty:
        df = _load_full(date_str)
        if df is None or df.empty or "Symbol" not in df.columns:
            abort(404)
        matches = df[df["Symbol"].astype(str).str.upper() == symbol]

    if matches.empty:
        abort(404)

    raw = matches.iloc[0].to_dict()

    # Transaction-analysis fields are stored in enriched_full.csv.
    # Merge them into the shortlisted row without changing existing
    # scoring, fundamental, or technical fields.
    full_df = _load_full(date_str)

    if full_df is not None and not full_df.empty and "Symbol" in full_df.columns:
        full_matches = full_df[
            full_df["Symbol"].astype(str).str.upper() == symbol
        ]

        if not full_matches.empty:
            full_raw = full_matches.iloc[0].to_dict()

            transaction_fields = [
                "ReportedBuyTxn",
                "PricedValuePurchased",
                "MissingValueQty",
                "MissingValueTxn",
                "MarketBuyValue",
                "MarketSellValue",
                "NetBuyValue",
                "SellBuyRatioPct",
                "HasMarketSell",
                "SellBuyExclusion",
            ]

            for field in transaction_fields:
                if field in full_raw:
                    raw[field] = full_raw[field]

    row = _df_to_rows(pd.DataFrame([raw]), include_flags=True)[0]
    row["trades"] = (_load_trades(date_str) or {}).get(symbol, [])
    return jsonify(row)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host  = os.environ.get("HOST", "0.0.0.0")
    app.run(debug=debug, host=host, port=port)
