"""Normalize NSE enrichment payloads into the fields consumed by RYB.

This module is deliberately independent of the scoring engine. It converts
raw NSE financial-results/shareholding responses into a stable, auditable
shape so the existing analyzer can be migrated without changing scoring
rules in the same step.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Iterable


@dataclass
class NSENormalized:
    symbol: str
    promo_holding_pct: float | None = None
    latest_financial_period: str | None = None
    financial_consolidated: bool | None = None
    revenue: float | None = None
    previous_year_revenue: float | None = None
    pat: float | None = None
    previous_year_pat: float | None = None
    eps: float | None = None
    previous_year_eps: float | None = None
    operating_profit: float | None = None
    debt_equity: float | None = None
    business_description: str | None = None
    source: str = "NSE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "NA", "N/A", "null", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "records", "financial_results", "shareholding"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return [payload]
    return []


def _date_value(record: dict[str, Any]) -> datetime:
    for key in ("to_date", "toDate", "date", "filed_date", "filedDate", "end_date"):
        value = record.get(key)
        if not value:
            continue
        text = str(value).strip()
        for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
    return datetime.min


def _is_consolidated(record: dict[str, Any]) -> bool:
    text = " ".join(str(record.get(k, "")) for k in ("nature", "type", "result_type", "consolidated", "consolidation")).lower()
    return "consolidated" in text and "non" not in text


def select_latest_financial(records: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Select the latest usable consolidated result, falling back to any result."""
    rows = list(records)
    if not rows:
        return None
    consolidated = [r for r in rows if _is_consolidated(r)]
    pool = consolidated or rows
    return max(pool, key=_date_value)


def select_latest_shareholding(records: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    rows = list(records)
    if not rows:
        return None
    return max(rows, key=_date_value)


def promoter_holding_pct(payload: Any) -> float | None:
    row = select_latest_shareholding(_records(payload))
    if not row:
        return None
    for key in (
        "pr_and_prgrp", "prAndPrGrp", "promoter_and_promoter_group",
        "promoterHolding", "promoter_holding", "promoter_pct",
    ):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _pick(record: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(record.get(key))
        if value is not None:
            return value
    return None


def normalize_financials(symbol: str, payload: Any) -> NSENormalized:
    rows = _records(payload)
    row = select_latest_financial(rows)
    out = NSENormalized(symbol=symbol)
    if not row:
        return out

    out.latest_financial_period = str(
        row.get("to_date") or row.get("toDate") or row.get("date") or ""
    ) or None
    out.financial_consolidated = _is_consolidated(row)
    out.revenue = _pick(row, "re_net_sale", "net_sales", "revenue", "total_income")
    out.pat = _pick(row, "re_net_profit", "net_profit", "profit_after_tax", "pat")
    out.eps = _pick(row, "re_basic_eps_for_cont_dic_opr", "basic_eps", "eps")
    out.operating_profit = _pick(row, "re_operating_profit", "operating_profit", "ebitda")
    out.debt_equity = _pick(row, "re_debt_eqt_rat", "debt_equity", "de_ratio")

    for key in ("business_description", "businessDescription", "nature_of_business", "natureOfBusiness"):
        value = row.get(key)
        if value:
            out.business_description = str(value).strip()
            break

    return out


def normalize_snapshot(symbol: str, snapshot: dict[str, Any]) -> NSENormalized:
    """Normalize the complete validation snapshot without changing raw data."""
    financial = normalize_financials(symbol, snapshot.get("financial_results") or snapshot.get("results_comparison") or {})
    financial.promo_holding_pct = promoter_holding_pct(snapshot.get("shareholding") or snapshot.get("shareholding_pattern") or {})
    return financial
