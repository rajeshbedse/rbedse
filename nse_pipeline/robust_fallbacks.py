"""Resilience helpers for upstream NSE availability gaps.

Keeps the primary analyzer/scoring logic unchanged while allowing the daily
pipeline to reuse the most recent successful 52-week snapshot and the
classification already retrieved from Screener.in during fundamentals fetch.

Promoter pledges and market sells are deliberately retained as risk signals,
not hard exclusions. Their values are measured as a percentage of the same
stock's total promoter market-buy value.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_CLASSIFICATION_COLUMNS = (
    "MacroEconomicSector",
    "Sector",
    "Industry",
    "BasicIndustry",
)


def _previous_successful_52w(output_root: Path, current_date: date) -> dict[str, dict[str, float | None]]:
    """Return 52-week values from the newest prior successful pipeline run."""
    if not output_root.exists():
        return {}
    candidates = []
    for run_dir in output_root.iterdir():
        if not run_dir.is_dir() or run_dir.name == current_date.isoformat():
            continue
        try:
            run_date = date.fromisoformat(run_dir.name)
        except ValueError:
            continue
        meta_path = run_dir / "meta.json"
        enriched_path = run_dir / "enriched_full.csv"
        if not meta_path.exists() or not enriched_path.exists():
            continue
        try:
            meta = pd.read_json(meta_path, typ="series")
            if str(meta.get("status", "")).lower() != "success":
                continue
        except Exception:
            continue
        candidates.append((run_date, enriched_path))
    candidates.sort(reverse=True)
    for run_date, path in candidates:
        try:
            df = pd.read_csv(
                path,
                encoding="utf-8-sig",
                usecols=lambda c: c in {"Symbol", "52WeekHigh", "52WeekLow"},
            )
            if "Symbol" not in df.columns:
                continue
            result = {}
            for _, row in df.iterrows():
                symbol = str(row.get("Symbol", "")).strip().upper()
                if not symbol:
                    continue
                high = pd.to_numeric(row.get("52WeekHigh"), errors="coerce")
                low = pd.to_numeric(row.get("52WeekLow"), errors="coerce")
                if pd.notna(high) and float(high) > 0 and pd.notna(low) and float(low) > 0:
                    result[symbol] = {"52WeekHigh": float(high), "52WeekLow": float(low)}
            if result:
                log.info(
                    "52-week fallback: reusing %d symbols from successful run %s",
                    len(result), run_date.isoformat(),
                )
                return result
        except Exception as exc:
            log.warning("52-week fallback read failed for %s: %s", path, exc)
    return {}


def _parse_screener_classification(html: str) -> dict[str, str | None]:
    """Extract the four-level classification shown in Screener peer comparison."""
    soup = BeautifulSoup(html, "html.parser")
    heading = None
    for tag in soup.find_all(["h2", "h3"]):
        if " ".join(tag.get_text(" ", strip=True).split()).lower() == "peer comparison":
            heading = tag
            break
    if heading is None:
        return {key: None for key in _CLASSIFICATION_COLUMNS}

    values: list[str] = []
    for link in heading.find_all_next("a"):
        text = " ".join(link.get_text(" ", strip=True).split())
        if not text:
            continue
        if text.lower() in {"edit columns", "show all"} or text.lower().startswith(("bse ", "nifty ")):
            break
        values.append(text)
        if len(values) == 4:
            break
    values = values[:4]
    while len(values) < 4:
        values.append(None)
    return dict(zip(_CLASSIFICATION_COLUMNS, values))


def _risk_deduction(pct: float) -> int:
    """Apply graduated risk: negligible activity should not hide an opportunity."""
    if pct <= 0:
        return 0
    if pct <= 5:
        return -1
    if pct <= 15:
        return -3
    return -5


def _risk_label(pledge_pct: float, sell_pct: float) -> str:
    maximum = max(pledge_pct, sell_pct)
    combined = pledge_pct + sell_pct
    if maximum <= 0:
        return "Low"
    if maximum <= 5 and combined <= 10:
        return "Low"
    if maximum <= 15 and combined <= 25:
        return "Moderate"
    return "High"


def _install_risk_aware_inclusion(analyzer_module) -> None:
    """Keep qualifying promoter-buy stocks and convert pledge/sell into risk."""
    original_build = analyzer_module._build_aggregates

    def build_aggregates(csv_path):
        agg, _pledge_syms, _sell_syms = original_build(csv_path)

        raw = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        raw.columns = raw.columns.str.strip()
        raw, _ = analyzer_module._deduplicate_transactions(raw)
        promoter = raw[
            raw["Category of Person"].fillna("").str.strip().str.lower().isin(
                analyzer_module.PROMOTER_CATEGORIES
            )
        ].copy()
        instrument = promoter["Type of Instrument"].fillna("").str.strip().str.lower().eq("equity")
        mode = promoter["Mode of Acquisition/Disposal"].fillna("").str.strip().str.lower()

        pledge = promoter[instrument & mode.isin(analyzer_module.PLEDGE_MODES)].copy()
        pledge["_value"] = pledge["Securities Acquired/Disposed (Value)"].apply(analyzer_module._v)
        pledge_values = pledge.groupby("Symbol")["_value"].sum()

        agg["PledgeValue"] = agg["Symbol"].map(pledge_values).fillna(0.0)
        agg["PledgeBuyRatioPct"] = (
            agg["PledgeValue"] / agg["MarketBuyValue"].replace(0, float("nan")) * 100
        ).round(2).fillna(0.0)
        agg["MarketSellBuyRatioPct"] = pd.to_numeric(
            agg.get("SellBuyRatioPct", 0), errors="coerce"
        ).fillna(0.0).round(2)
        agg["RiskActivityValueCr"] = (
            agg["PledgeValue"] + agg["MarketSellValue"]
        ) / 1e7
        agg["RiskActivityPct"] = (
            agg["PledgeBuyRatioPct"] + agg["MarketSellBuyRatioPct"]
        ).round(2)

        # The legacy analyzer hard-excludes pledges and >25% market sells.
        # RYB now retains every stock with a qualifying promoter market buy.
        agg["SellBuyExclusion"] = False
        log.info(
            "RYB risk-aware inclusion: %d buy candidates retained; pledge/sell are risk signals, not hard exclusions",
            len(agg),
        )
        return agg, set(), set()

    analyzer_module._build_aggregates = build_aggregates

    original_score = analyzer_module._score_row

    def score_row(row, fund):
        promo, fund_score, tech, risk, _total, _category = original_score(row, fund)
        pledge_pct = float(pd.to_numeric(row.get("PledgeBuyRatioPct", 0), errors="coerce") or 0)
        sell_pct = float(pd.to_numeric(row.get("MarketSellBuyRatioPct", 0), errors="coerce") or 0)
        risk_delta = max(-10, _risk_deduction(pledge_pct) + _risk_deduction(sell_pct))
        risk += risk_delta
        total = max(0, min(100, promo + fund_score + tech + risk))
        if total >= analyzer_module.CATEGORY_STRONG_BUY:
            category = "Strong Buy Setup"
        elif total >= analyzer_module.CATEGORY_BUY_BREAKOUT:
            category = "Buy on Breakout"
        elif total >= analyzer_module.CATEGORY_WATCHLIST:
            category = "Watchlist"
        elif total >= analyzer_module.CATEGORY_WEAK_FUND:
            category = "Fundamental Watch"
        else:
            category = "Avoid"
        return promo, fund_score, tech, risk, total, category

    analyzer_module._score_row = score_row

    original_apply = analyzer_module._apply_scores

    def apply_scores(df, screener_data, dma_data=None):
        result = original_apply(df, screener_data, dma_data)
        pledge = pd.to_numeric(result.get("PledgeBuyRatioPct", 0), errors="coerce").fillna(0)
        sells = pd.to_numeric(result.get("MarketSellBuyRatioPct", 0), errors="coerce").fillna(0)
        result["RiskActivityPct"] = (pledge + sells).round(2)
        result["RiskLevel"] = [_risk_label(float(p), float(s)) for p, s in zip(pledge, sells)]
        result["RiskSummary"] = [
            (
                (f"Pledge {float(p):.2f}% of buy value" if float(p) > 0 else "")
                + ("; " if float(p) > 0 and float(s) > 0 else "")
                + (f"Market sell {float(s):.2f}% of buy value" if float(s) > 0 else "")
            ) or "No pledge / market sell"
            for p, s in zip(pledge, sells)
        ]
        return result

    analyzer_module._apply_scores = apply_scores


def install(
    analyzer_module,
    research_enrichment_module,
    output_root: Path,
    current_date: date,
    scan_path: Path,
) -> None:
    """Install resilient 52W, classification and risk-aware fallbacks."""
    _install_risk_aware_inclusion(analyzer_module)

    original_52w = analyzer_module._fetch_52_week_prices
    fallback_cache = {"loaded": False, "data": {}}

    def fetch_52w(symbols, as_of_date=None):
        current = original_52w(symbols, as_of_date=as_of_date)
        if not fallback_cache["loaded"]:
            fallback_cache["data"] = _previous_successful_52w(output_root, current_date)
            fallback_cache["loaded"] = True
        fallback = fallback_cache["data"]
        reused = 0
        for symbol in symbols:
            existing = current.get(symbol, {}) or {}
            if existing.get("52WeekHigh") and existing.get("52WeekLow"):
                continue
            prior = fallback.get(str(symbol).strip().upper())
            if prior:
                current[symbol] = prior.copy()
                reused += 1
        if reused:
            log.warning(
                "52-week report unavailable/partial: reused prior successful values for %d symbols",
                reused,
            )
        return current

    analyzer_module._fetch_52_week_prices = fetch_52w

    # Screener already supplies the classification hierarchy on the same HTML
    # page used for fundamentals. Capture it once instead of calling NSE again.
    original_parse = analyzer_module._parse_fundamentals_html

    def parse_fundamentals(html):
        data = original_parse(html)
        data.update(_parse_screener_classification(html))
        return data

    analyzer_module._parse_fundamentals_html = parse_fundamentals

    # The risk-aware _apply_scores wrapper above already wraps the original
    # scorer. Add classification fields without introducing another score pass.
    original_scored_apply = analyzer_module._apply_scores

    def apply_classification(df, screener_data, dma_data=None):
        result = original_scored_apply(df, screener_data, dma_data)
        for column in _CLASSIFICATION_COLUMNS:
            result[column] = result["Symbol"].map({
                symbol: (screener_data.get(symbol, {}).get("fundamentals", {}) or {}).get(column)
                for symbol in result["Symbol"].astype(str)
            })
        return result

    analyzer_module._apply_scores = apply_classification

    # The scan is the canonical classification hand-off. Do not call a second
    # NSE classification endpoint here: Screener was already queried for the
    # same symbols during fundamentals enrichment.
    def build_classification(symbols, out_path):
        try:
            scan = pd.read_csv(scan_path, encoding="utf-8-sig")
            if "Symbol" not in scan.columns:
                raise ValueError("RYB scan is missing Symbol column")
            result = scan[["Symbol", *[c for c in _CLASSIFICATION_COLUMNS if c in scan.columns]]].copy()
            for column in _CLASSIFICATION_COLUMNS:
                if column not in result.columns:
                    result[column] = None
            result = result[["Symbol", *_CLASSIFICATION_COLUMNS]]
            result["Symbol"] = result["Symbol"].astype(str).str.strip().str.upper()
            populated = result[_CLASSIFICATION_COLUMNS].astype("string").apply(
                lambda s: s.str.strip().ne("") & s.notna()
            ).any(axis=1).sum()
            result.to_csv(out_path, index=False, encoding="utf-8-sig")
            log.info(
                "Company classification → Screener hierarchy (%d/%d symbols populated)",
                populated,
                len(result),
            )
            return len(result)
        except Exception as exc:
            log.warning("Screener classification reuse failed: %s", exc)
            result = pd.DataFrame({"Symbol": [str(s).strip().upper() for s in symbols]})
            for column in _CLASSIFICATION_COLUMNS:
                result[column] = None
            out_path.parent.mkdir(parents=True, exist_ok=True)
            result.to_csv(out_path, index=False, encoding="utf-8-sig")
            return len(result)

    research_enrichment_module.build_company_classification = build_classification
