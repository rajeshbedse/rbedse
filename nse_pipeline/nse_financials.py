"""NSE Integrated Filing -> scoring-model financial normalization.

The NSE financial-results catalog moved to Integrated Filing.  The catalog is
an NSE browser/API response containing links to first-party iXBRL filings on
nsearchives.nseindia.com.  This module keeps the source-of-truth path entirely
within NSE and produces the same field names consumed by the existing scorer.

Important design rule: no third-party financial vendor is used and no stale
legacy result is silently substituted for a current Integrated Filing result.
"""

from __future__ import annotations

import re
import requests
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from .nse_enrichment import _browser_fetch, NSE_BASE

_XBRLI = "http://www.xbrl.org/2003/instance"


@dataclass(frozen=True)
class Filing:
    symbol: str
    company: str
    consolidated: bool
    audited: bool
    period_end: date | None
    filing_date: date | None
    xbrl_url: str


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return _records(data)
    return [payload]


def list_integrated_filings(page: Any, symbol: str, size: int = 50) -> list[Filing]:
    """Return NSE Integrated Filing - Financials rows for one symbol."""
    payload = _browser_fetch(
        page,
        "/api/integrated-filing-results",
        {
            "index": "equities",
            "symbol": symbol.upper(),
            "type": "Integrated Filing- Financials",
            "page": "1",
            "size": str(size),
        },
    )
    out: list[Filing] = []
    for row in _records(payload):
        filing_type = str(row.get("type") or "").strip().lower()
        if filing_type and filing_type != "integrated filing- financials":
            continue
        xbrl = str(row.get("xbrl") or row.get("xbrlFile") or "").strip()
        consolidated = str(row.get("consolidated") or "").strip().lower()
        period_end = _parse_date(row.get("qe_Date") or row.get("quarterEndDate") or row.get("toDate"))
        filing_date = _parse_date(row.get("broadcast_Date") or row.get("broadcastDate") or row.get("filingDate"))
        if not xbrl or period_end is None or consolidated not in {"consolidated", "standalone"}:
            continue
        out.append(
            Filing(
                symbol=str(row.get("symbol") or symbol).upper(),
                company=str(row.get("cmName") or row.get("companyName") or ""),
                consolidated=consolidated == "consolidated",
                audited=str(row.get("audited") or "").strip().lower() == "audited",
                period_end=period_end,
                filing_date=filing_date,
                xbrl_url=xbrl,
            )
        )
    return sorted(out, key=lambda x: (x.period_end or date.min, x.filing_date or date.min), reverse=True)


def _local_name(tag: Any) -> str | None:
    if not isinstance(tag, str):
        return None
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag.rsplit(":", 1)[-1]


def _is_financial_taxonomy(tag: Any) -> bool:
    if not isinstance(tag, str):
        return False
    if not tag.startswith("{"):
        return False
    uri = tag[1:].split("}", 1)[0].lower()
    return uri.endswith("in-capmkt") or uri.endswith("in-bse-fin") or "sebi.gov.in/xbrl" in uri


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    text = text.strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _plain_contexts(root: ET.Element) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]]]:
    contexts: dict[str, dict[str, Any]] = {}
    facts: dict[str, dict[str, float]] = {}
    for ctx in root.findall(f"{{{_XBRLI}}}context"):
        cid = ctx.get("id")
        if not cid:
            continue
        period = ctx.find(f"{{{_XBRLI}}}period")
        start = end = instant = None
        if period is not None:
            start = _parse_date(period.findtext(f"{{{_XBRLI}}}startDate"))
            end = _parse_date(period.findtext(f"{{{_XBRLI}}}endDate"))
            instant = _parse_date(period.findtext(f"{{{_XBRLI}}}instant"))
        has_dimension = ctx.find(".//{http://xbrl.org/2006/xbrldi}explicitMember") is not None
        contexts[cid] = {"start": start, "end": end, "instant": instant, "dimension": has_dimension}
    return contexts, facts


def parse_xbrl(raw: bytes) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, Any]]]:
    """Parse dimensionless NSE financial facts keyed by XBRL context."""
    root = ET.fromstring(raw)
    contexts, facts = _plain_contexts(root)
    for element in root.iter():
        if not _is_financial_taxonomy(element.tag):
            continue
        context_ref = element.get("contextRef")
        if not context_ref or context_ref not in contexts:
            continue
        meta = contexts[context_ref]
        if meta["dimension"]:
            continue
        value = _number(element.text)
        if value is None:
            continue
        local = _local_name(element.tag)
        if local:
            facts.setdefault(context_ref, {})[local] = value
    return facts, contexts


def _context(facts: dict[str, dict[str, float]], contexts: dict[str, dict[str, Any]], preferred: str, *, instant: bool = False, period_end: date | None = None) -> dict[str, float]:
    if preferred in facts:
        return facts[preferred]
    candidates: list[tuple[str, dict[str, float]]] = []
    for cid, meta in contexts.items():
        if cid not in facts:
            continue
        if instant and meta.get("instant"):
            if period_end is None or meta["instant"] == period_end:
                candidates.append((cid, facts[cid]))
        elif not instant and meta.get("end"):
            if period_end is None or meta["end"] == period_end:
                candidates.append((cid, facts[cid]))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[-1][1]
    return {}


def _pick(facts: dict[str, float], exact: Iterable[str], contains: Iterable[str] = ()) -> float | None:
    for key in exact:
        if key in facts:
            return facts[key]
    lowered = {k.lower(): v for k, v in facts.items()}
    for needle in contains:
        for key, value in lowered.items():
            if needle.lower() in key:
                return value
    return None


def _metric_row(facts: dict[str, float]) -> dict[str, float | None]:
    revenue = _pick(facts, ("RevenueFromOperations", "Revenue"), ("revenuefromoperations",))
    pat = _pick(facts, ("ProfitLossForPeriod", "ProfitLoss", "ProfitForPeriod"), ("profitlossforperiod", "profitloss"))
    pbt = _pick(facts, ("ProfitBeforeTax",), ("profitbeforetax",))
    finance = _pick(facts, ("FinanceCosts", "FinanceCost"), ("financecost", "financecosts"))
    depreciation = _pick(facts, ("DepreciationDepletionAndAmortisation", "DepreciationAndAmortisation"), ("depreciation", "amortisation"))
    operating_profit = _pick(facts, ("OperatingProfit", "ProfitFromOperations"), ("operatingprofit", "profitfromoperations"))
    if operating_profit is None and pbt is not None:
        operating_profit = pbt + (finance or 0) + (depreciation or 0)
    eps = _pick(facts, ("BasicEarningsLossPerShare", "BasicEarningsPerShare"), ("basicearnings", "basiceps"))
    return {
        "revenue": revenue,
        "pat": pat,
        "pbt": pbt,
        "finance": finance,
        "depreciation": depreciation,
        "operating_profit": operating_profit,
        "eps": eps,
    }


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    return round((current / prior - 1) * 100, 2)


def normalize_symbol(page: Any, symbol: str, quote: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return fields matching the existing scorer, using NSE Integrated Filing."""
    filings = list_integrated_filings(page, symbol)
    if not filings:
        return {"NSEFinancialSource": "Integrated Filing", "FinancialDataCurrent": False}

    # Keep the newest consolidated filing for each period; fall back to standalone
    # only when no consolidated filing exists for that period.
    by_period: dict[date, Filing] = {}
    for filing in filings:
        current = by_period.get(filing.period_end)
        if current is None or (filing.consolidated and not current.consolidated):
            by_period[filing.period_end] = filing
    selected = sorted(by_period.values(), key=lambda f: f.period_end or date.min, reverse=True)

    parsed: list[tuple[Filing, dict[str, dict[str, float]], dict[str, dict[str, Any]]]] = []
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    for filing in selected[:8]:
        try:
            response = session.get(filing.xbrl_url, timeout=20)
            response.raise_for_status()
            facts, contexts = parse_xbrl(response.content)
            parsed.append((filing, facts, contexts))
        except Exception:
            continue

    if not parsed:
        return {"NSEFinancialSource": "Integrated Filing", "FinancialDataCurrent": False}

    latest = parsed[0]
    latest_filing, latest_facts, latest_contexts = latest
    current_q = _context(latest_facts, latest_contexts, "OneD", period_end=latest_filing.period_end)
    current = _metric_row(current_q)

    # Find the same quarter in the prior year rather than assuming row order.
    prior_year = next((item for item in parsed if item[0].period_end and latest_filing.period_end and item[0].period_end.month == latest_filing.period_end.month and item[0].period_end.day == latest_filing.period_end.day and item[0].period_end.year < latest_filing.period_end.year), None)
    prior = _metric_row(_context(prior_year[1], prior_year[2], "OneD", period_end=prior_year[0].period_end)) if prior_year else {}

    annual = next((item for item in parsed if item[0].period_end and item[0].period_end.month == 3 and item[0].period_end.day == 31), None)
    annual_metrics = {}
    balance = {}
    if annual:
        annual_q = _context(annual[1], annual[2], "FourD", period_end=annual[0].period_end)
        annual_metrics = _metric_row(annual_q)
        balance = _context(annual[1], annual[2], "OneI", instant=True, period_end=annual[0].period_end)

    issued_size = None
    last_price = None
    if quote:
        security = quote.get("securityInfo") or {}
        price = quote.get("priceInfo") or {}
        issued_size = _number(str(security.get("issuedSize")))
        last_price = _number(str(price.get("lastPrice")))
    market_cap_cr = last_price * issued_size / 1e7 if last_price and issued_size else None

    ttm_pat = 0.0
    ttm_count = 0
    for filing, facts, contexts in parsed[:4]:
        metric = _metric_row(_context(facts, contexts, "OneD", period_end=filing.period_end))
        if metric.get("pat") is not None:
            ttm_pat += float(metric["pat"])
            ttm_count += 1
    # NSE XBRL financial statements are commonly reported in lakhs; PE only needs
    # the ratio, so scale cancels between market cap (crore) and PAT after conversion.
    pe = market_cap_cr / (ttm_pat / 1e5) if market_cap_cr and ttm_count == 4 and ttm_pat > 0 else None

    equity = _pick(balance, ("EquityShareCapital", "Equity"), ("equitysharecapital",))
    reserves = _pick(balance, ("OtherEquity", "ReservesAndSurplus", "Reserves"), ("otherequity", "reserves"))
    borrowings = _pick(balance, ("Borrowings", "BorrowingsNonCurrent", "BorrowingsCurrent"), ("borrowings",))
    cash = _pick(balance, ("CashAndCashEquivalents", "CashAndBankBalances"), ("cashandcashequivalents", "cashandbank"))
    debt_equity = borrowings / (equity + reserves) if borrowings is not None and equity is not None and reserves is not None and equity + reserves > 0 else None
    capital_employed = (equity + reserves + borrowings - (cash or 0)) if equity is not None and reserves is not None and borrowings is not None else None
    ebit = annual_metrics.get("pbt")
    if ebit is not None:
        ebit = ebit + (annual_metrics.get("finance") or 0)
    roce = ebit / capital_employed * 100 if ebit is not None and capital_employed and capital_employed > 0 else None

    ocf = _pick(annual_q if annual else {}, ("CashFlowsFromUsedInOperatingActivities", "CashFlowsFromOperatingActivities"), ("cashflowsfromusedinoperatingactivities", "cashflowsfromoperatingactivities")) if annual else None
    opm = current["operating_profit"] / current["revenue"] * 100 if current.get("operating_profit") is not None and current.get("revenue") not in (None, 0) else None

    return {
        "MarketCapCr": round(market_cap_cr, 2) if market_cap_cr is not None else None,
        "PE": round(pe, 2) if pe is not None else None,
        "RevGrowthPct": _growth(current.get("revenue"), prior.get("revenue")),
        "EBITDAGrowthPct": _growth(current.get("operating_profit"), prior.get("operating_profit")),
        "PATGrowthPct": _growth(current.get("pat"), prior.get("pat")),
        "EPSGrowthPct": _growth(current.get("eps"), prior.get("eps")),
        "ROCEPct": round(roce, 2) if roce is not None else None,
        "DE_Ratio": round(debt_equity, 2) if debt_equity is not None else None,
        "OCFPositive": bool(ocf > 0) if ocf is not None else None,
        "OPMPct": round(opm, 2) if opm is not None else None,
        "NSEFinancialSource": "Integrated Filing/XBRL",
        "NSEFinancialPeriod": latest_filing.period_end.isoformat() if latest_filing.period_end else None,
        "FinancialDataCurrent": bool(latest_filing.period_end and latest_filing.period_end >= date.today().replace(year=date.today().year - 1)),
    }
