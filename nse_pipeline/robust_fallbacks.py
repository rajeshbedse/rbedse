"""Resilience helpers for upstream NSE availability gaps.

Keeps the primary analyzer/scoring logic unchanged while allowing the daily
pipeline to reuse the most recent successful 52-week snapshot and the
classification already retrieved from Screener.in during fundamentals fetch.
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


def install(
    analyzer_module,
    research_enrichment_module,
    output_root: Path,
    current_date: date,
    scan_path: Path,
) -> None:
    """Install resilient 52W and Screener-classification fallbacks."""
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

    original_apply = analyzer_module._apply_scores

    def apply_scores(df, screener_data, dma_data=None):
        result = original_apply(df, screener_data, dma_data)
        for column in _CLASSIFICATION_COLUMNS:
            result[column] = result["Symbol"].map({
                symbol: (screener_data.get(symbol, {}).get("fundamentals", {}) or {}).get(column)
                for symbol in result["Symbol"].astype(str)
            })
        return result

    analyzer_module._apply_scores = apply_scores

    # Research enrichment should consume the classification just obtained from
    # Screener, avoiding a second classification source that is currently less
    # reliable in automated runs.
    original_classification = research_enrichment_module.build_company_classification

    def build_classification(symbols, out_path):
        try:
            scan = pd.read_csv(scan_path, encoding="utf-8-sig")
            if "Symbol" in scan.columns and all(c in scan.columns for c in _CLASSIFICATION_COLUMNS):
                cols = ["Symbol", *_CLASSIFICATION_COLUMNS]
                result = scan[cols].copy()
                result["Symbol"] = result["Symbol"].astype(str).str.strip().str.upper()
                populated = result[_CLASSIFICATION_COLUMNS].astype(str).apply(
                    lambda s: s.str.strip().ne("")
                ).any(axis=1).sum()
                if populated > 0:
                    result.to_csv(out_path, index=False, encoding="utf-8-sig")
                    log.info(
                        "Company classification → Screener hierarchy (%d/%d symbols populated)",
                        populated,
                        len(result),
                    )
                    return len(result)
        except Exception as exc:
            log.warning("Screener classification reuse failed: %s", exc)
        return original_classification(symbols, out_path)

    research_enrichment_module.build_company_classification = build_classification
