"""Normalize NSE enrichment payloads into fields consumed by RYB.

This module is intentionally separate from the scoring engine. It converts
raw NSE shareholding and results-comparison payloads into a stable shape while
preserving the raw source semantics. It must not silently use stale financial
results: callers should inspect ``financial_data_current`` before migration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass
class NSENormalized:
    symbol: str
    promo_holding_pct: float | None = None
    latest_financial_period: str | None = None
    financial_filing_date: str | None = None
    financial_consolidated: bool | None = None
    financial_data_current: bool = False
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


def _date(value: Any) -> datetime:
    if not value:
        return datetime.min
    text = str(value).strip().upper()
    for fmt in (
        "%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M",
        "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return datetime.min


def _records(payload: Any) -> list[dict[str, Any]]:
    """Extract records from the actual NSE response shapes."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("data"), (dict, list)):
        return _records(payload["data"])
    if isinstance(payload.get("resCmpData"), list):
        return [x for x in payload["resCmpData"] if isinstance(x, dict)]
    for key in ("results", "records", "financial_results", "shareholding"):
        if isinstance(payload.get(key), (dict, list)):
            return _records(payload[key])
    return [payload]


def _is_consolidated(record: dict[str, Any]) -> bool:
    value = str(record.get("consolidated") or record.get("consolidation") or "").strip().lower()
    if value:
        return value == "consolidated"
    value = str(record.get("re_res_type") or "").lower()
    return "consolid" in value and "non" not in value


def select_latest_financial(records: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Select latest filing, preferring consolidated where available."""
    rows = list(records)
    if not rows:
        return None
    consolidated = [r for r in rows if _is_consolidated(r)]
    pool = consolidated or rows
    return max(
        pool,
        key=lambda r: max(
            _date(r.get("filingDate")),
            _date(r.get("broadCastDate")),
            _date(r.get("re_create_dt")),
            _date(r.get("re_to_dt")),
        ),
    )


def select_latest_shareholding(records: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    rows = list(records)
    return max(rows, key=lambda r: _date(r.get("date") or r.get("broadcastDate")), default=None)


def promoter_holding_pct(payload: Any) -> float | None:
    row = select_latest_shareholding(_records(payload))
    if not row:
        return None
    return _number(row.get("pr_and_prgrp") or row.get("promoter_holding") or row.get("promoter_pct"))


def _pick(record: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(record.get(key))
        if value is not None:
            return value
    return None


def _operating_profit(record: dict[str, Any]) -> float | None:
    value = _pick(record, "re_operating_profit", "operating_profit", "ebitda")
    if value is not None:
        return value
    sales = _pick(record, "re_net_sale")
    raw_expense = _pick(record, "re_oth_tot_exp")
    if sales is not None and raw_expense is not None:
        return sales - raw_expense
    return None


def _business_description(records: Iterable[dict[str, Any]]) -> str | None:
    for row in records:
        for key in (
            "business_description", "businessDescription", "nature_of_business",
            "natureOfBusiness", "re_desc_note_seg", "re_desc_note_fin",
        ):
            value = row.get(key)
            if value and str(value).strip() not in {"-", "None"}:
                return " ".join(str(value).split())
    return None


def normalize_financials(
    symbol: str,
    financial_results_payload: Any,
    results_comparison_payload: Any,
    as_of: datetime | None = None,
) -> NSENormalized:
    """Normalize NSE financial data without silently accepting stale results."""
    out = NSENormalized(symbol=symbol)
    filing_rows = _records(financial_results_payload)
    comparison_rows = _records(results_comparison_payload)
    latest_filing = select_latest_financial(filing_rows)
    latest_comparison = max(
        comparison_rows,
        key=lambda r: max(_date(r.get("re_create_dt")), _date(r.get("re_to_dt"))),
        default=None,
    )

    if latest_filing:
        out.latest_financial_period = str(
            latest_filing.get("financialYear") or latest_filing.get("toDate")
            or latest_filing.get("to_date") or ""
        ) or None
        out.financial_filing_date = str(
            latest_filing.get("filingDate") or latest_filing.get("broadCastDate") or ""
        ) or None
        out.financial_consolidated = _is_consolidated(latest_filing)

    if latest_comparison:
        out.revenue = _pick(latest_comparison, "re_net_sale", "re_total_inc", "net_sales", "revenue")
        out.pat = _pick(latest_comparison, "re_net_profit", "re_con_pro_loss", "profit_after_tax", "pat")
        out.eps = _pick(latest_comparison, "re_basic_eps_for_cont_dic_opr", "re_basic_eps", "basic_eps", "eps")
        out.operating_profit = _operating_profit(latest_comparison)
        out.debt_equity = _pick(latest_comparison, "re_debt_eqt_rat", "debt_equity", "de_ratio")
        out.business_description = _business_description([latest_comparison])

        comparison_date = max(
            _date(latest_comparison.get("re_create_dt")),
            _date(latest_comparison.get("re_to_dt")),
        )
        filing_date = _date(latest_filing.get("filingDate")) if latest_filing else datetime.min
        reference = as_of or datetime.now()
        cutoff = reference.replace(year=reference.year - 1)
        out.financial_data_current = (
            comparison_date != datetime.min
            and comparison_date >= cutoff
            and (filing_date == datetime.min or filing_date >= cutoff)
        )

        if len(comparison_rows) > 1:
            ordered = sorted(
                comparison_rows,
                key=lambda r: max(_date(r.get("re_create_dt")), _date(r.get("re_to_dt"))),
                reverse=True,
            )
            prior = ordered[1]
            out.previous_year_revenue = _pick(prior, "re_net_sale", "re_total_inc")
            out.previous_year_pat = _pick(prior, "re_net_profit", "re_con_pro_loss")
            out.previous_year_eps = _pick(prior, "re_basic_eps_for_cont_dic_opr", "re_basic_eps")

    return out


def normalize_snapshot(
    symbol: str,
    snapshot: dict[str, Any],
    as_of: datetime | None = None,
) -> NSENormalized:
    return normalize_financials(
        symbol,
        snapshot.get("financial_results") or {},
        snapshot.get("results_comparison") or {},
        as_of=as_of,
    )
