"""NSE Integrated Filing -> scoring-model financial normalization.

Uses NSE Integrated Filing/XBRL as the first-party financial source. The
normalizer deliberately keeps the existing RYB field contract while making
period selection and ratio calculations explicit.
"""
from __future__ import annotations

import re
import requests
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from .nse_enrichment import _browser_fetch

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
    if not value: return None
    text = str(value).strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y"):
        try: return datetime.strptime(text, fmt).date()
        except ValueError: pass
    return None

def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list): return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict): return []
    data = payload.get("data")
    if isinstance(data, list): return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict): return _records(data)
    return [payload]

def list_integrated_filings(page: Any, symbol: str, size: int = 50) -> list[Filing]:
    payload = _browser_fetch(page, "/api/integrated-filing-results", {
        "index":"equities", "symbol":symbol.upper(),
        "type":"Integrated Filing- Financials", "page":"1", "size":str(size)
    })
    out=[]
    for row in _records(payload):
        typ=str(row.get("type") or "").strip().lower()
        if typ and typ != "integrated filing- financials": continue
        xbrl=str(row.get("xbrl") or row.get("xbrlFile") or "").strip()
        consolidated=str(row.get("consolidated") or "").strip().lower()
        period_end=_parse_date(row.get("qe_Date") or row.get("quarterEndDate") or row.get("toDate"))
        filing_date=_parse_date(row.get("broadcast_Date") or row.get("broadcastDate") or row.get("filingDate"))
        if not xbrl or not period_end or consolidated not in {"consolidated","standalone"}: continue
        out.append(Filing(str(row.get("symbol") or symbol).upper(), str(row.get("cmName") or row.get("companyName") or ""), consolidated=="consolidated", str(row.get("audited") or "").lower()=="audited", period_end, filing_date, xbrl))
    return sorted(out,key=lambda x:(x.period_end or date.min,x.filing_date or date.min),reverse=True)

def _local_name(tag: Any) -> str | None:
    if not isinstance(tag,str): return None
    return tag.split("}",1)[1] if tag.startswith("{") else tag.rsplit(":",1)[-1]

def _is_financial_taxonomy(tag: Any) -> bool:
    if not isinstance(tag,str) or not tag.startswith("{"): return False
    uri=tag[1:].split("}",1)[0].lower()
    return "sebi.gov.in/xbrl" in uri or uri.endswith("in-capmkt") or uri.endswith("in-bse-fin")

def _number(text: str | None) -> float | None:
    if text is None: return None
    try: return float(text.strip().replace(",",""))
    except (ValueError,AttributeError): return None

def parse_xbrl(raw: bytes) -> tuple[dict[str,dict[str,float]],dict[str,dict[str,Any]]]:
    root=ET.fromstring(raw); contexts={}; facts={}
    for ctx in root.findall(f"{{{_XBRLI}}}context"):
        cid=ctx.get("id")
        if not cid: continue
        period=ctx.find(f"{{{_XBRLI}}}period"); start=end=instant=None
        if period is not None:
            start=_parse_date(period.findtext(f"{{{_XBRLI}}}startDate")); end=_parse_date(period.findtext(f"{{{_XBRLI}}}endDate")); instant=_parse_date(period.findtext(f"{{{_XBRLI}}}instant"))
        contexts[cid]={"start":start,"end":end,"instant":instant,"dimension":ctx.find(".//{http://xbrl.org/2006/xbrldi}explicitMember") is not None}
    for element in root.iter():
        if not _is_financial_taxonomy(element.tag): continue
        cid=element.get("contextRef")
        if not cid or cid not in contexts or contexts[cid]["dimension"]: continue
        value=_number(element.text); local=_local_name(element.tag)
        if value is not None and local: facts.setdefault(cid,{})[local]=value
    return facts,contexts

def _contexts_for(facts,contexts,period_end,instant=False):
    candidates=[]
    for cid,meta in contexts.items():
        if cid not in facts: continue
        target=meta.get("instant") if instant else meta.get("end")
        if target==period_end: candidates.append((cid,facts[cid],meta))
    return candidates

def _pick(facts:dict[str,float], exact:Iterable[str], contains:Iterable[str]=()):
    for key in exact:
        if key in facts: return facts[key]
    for needle in contains:
        needle=needle.lower()
        for key,val in facts.items():
            if needle in key.lower(): return val
    return None

def _metric(facts):
    revenue=_pick(facts,("RevenueFromOperations","Revenue"),("revenuefromoperations","revenue"))
    pat=_pick(facts,("ProfitLossForPeriod","ProfitLoss","ProfitForPeriod"),("profitlossforperiod","profitloss"))
    eps=_pick(facts,("BasicEarningsLossPerShare","BasicEarningsPerShare"),("basicearningsloss","basicearningspershare"))
    pbt=_pick(facts,("ProfitBeforeTax",),("profitbeforetax",))
    finance=_pick(facts,("FinanceCosts","FinanceCost"),("financecost",))
    depreciation=_pick(facts,("DepreciationDepletionAndAmortisation","DepreciationAndAmortisation"),("depreciation",))
    op=_pick(facts,("OperatingProfit","ProfitFromOperations"),("operatingprofit","profitfromoperations"))
    if op is None and pbt is not None: op=pbt+(finance or 0)+(depreciation or 0)
    return {"revenue":revenue,"pat":pat,"eps":eps,"pbt":pbt,"finance":finance,"depreciation":depreciation,"operating_profit":op}

def _growth(a,b):
    if a is None or b in (None,0): return None
    return round((a/b-1)*100,2)

def _facts_for_period(facts,contexts,period_end,instant=False,annual=False):
    candidates=_contexts_for(facts,contexts,period_end,instant=instant)
    if not candidates: return {}
    # Prefer the context whose duration best matches the requested period.
    if not instant and annual:
        candidates.sort(key=lambda x: ((x[2].get("start") or date.min), x[0]), reverse=True)
    else:
        candidates.sort(key=lambda x:x[0])
    return candidates[-1][1]

def normalize_symbol(page:Any,symbol:str,quote:dict[str,Any]|None=None)->dict[str,Any]:
    filings=list_integrated_filings(page,symbol)
    if not filings: return {"NSEFinancialSource":"Integrated Filing","FinancialDataCurrent":False}
    by_period={}
    for f in filings:
        if f.period_end not in by_period or (f.consolidated and not by_period[f.period_end].consolidated): by_period[f.period_end]=f
    selected=sorted(by_period.values(),key=lambda f:(f.period_end or date.min,f.filing_date or date.min),reverse=True)
    parsed=[]; session=requests.Session(); session.headers.update({"User-Agent":"Mozilla/5.0","Accept":"*/*"})
    for f in selected[:12]:
        try:
            r=session.get(f.xbrl_url,timeout=20); r.raise_for_status(); parsed.append((f,*parse_xbrl(r.content)))
        except Exception: continue
    if not parsed: return {"NSEFinancialSource":"Integrated Filing","FinancialDataCurrent":False}
    latest,lfacts,lcontexts=parsed[0]
    current=_metric(_facts_for_period(lfacts,lcontexts,latest.period_end,instant=False,annual=False))
    prior_item=next((x for x in parsed[1:] if x[0].period_end and latest.period_end and x[0].period_end.month==latest.period_end.month and x[0].period_end.day==latest.period_end.day and x[0].period_end.year==latest.period_end.year-1),None)
    prior=_metric(_facts_for_period(prior_item[1],prior_item[2],prior_item[0].period_end)) if prior_item else {}
    annual_item=next((x for x in parsed if x[0].period_end and x[0].period_end.month==3 and x[0].period_end.day==31),None)
    annual={}; balance={}
    if annual_item:
        annual=_metric(_facts_for_period(annual_item[1],annual_item[2],annual_item[0].period_end,annual=True))
        balance=_facts_for_period(annual_item[1],annual_item[2],annual_item[0].period_end,instant=True)
    price=None; shares=None
    if quote:
        price=_number(str((quote.get("priceInfo") or {}).get("lastPrice"))); shares=_number(str((quote.get("securityInfo") or {}).get("issuedSize")))
    market_cap_cr=price*shares/1e7 if price and shares else None
    eps_values=[]
    for f,facts,contexts in parsed[:6]:
        m=_metric(_facts_for_period(facts,contexts,f.period_end))
        if m.get("eps") is not None: eps_values.append(float(m["eps"]))
    ttm_eps=sum(eps_values[:4]) if len(eps_values)>=4 else None
    pe=market_cap_cr/((ttm_eps*shares)/1e7) if market_cap_cr and shares and ttm_eps not in (None,0) else None
    equity=_pick(balance,("EquityShareCapital","Equity"),("equitysharecapital",))
    reserves=_pick(balance,("OtherEquity","ReservesAndSurplus","Reserves"),("otherequity","reserves"))
    borrowings=_pick(balance,("Borrowings","BorrowingsNonCurrent","BorrowingsCurrent"),("borrowings",))
    debt_equity=borrowings/(equity+reserves) if borrowings is not None and equity is not None and reserves is not None and equity+reserves>0 else None
    cash=_pick(balance,("CashAndCashEquivalents","CashAndBankBalances"),("cashandcashequivalents","cashandbank"))
    capital_employed=(equity+reserves+borrowings-(cash or 0)) if equity is not None and reserves is not None and borrowings is not None else None
    ebit=(annual.get("pbt")+(annual.get("finance") or 0)) if annual.get("pbt") is not None else None
    roce=ebit/capital_employed*100 if ebit is not None and capital_employed and capital_employed>0 else None
    ocf=_pick(_facts_for_period(annual_item[1],annual_item[2],annual_item[0].period_end,instant=False,annual=True) if annual_item else {},("CashFlowsFromUsedInOperatingActivities","CashFlowsFromOperatingActivities"),("cashflowsfromusedinoperatingactivities","cashflowsfromoperatingactivities"))
    opm=current["operating_profit"]/current["revenue"]*100 if current.get("operating_profit") is not None and current.get("revenue") not in (None,0) else None
    return {
        "MarketCapCr":round(market_cap_cr,2) if market_cap_cr is not None else None,
        "PE":round(pe,2) if pe is not None else None,
        "RevGrowthPct":_growth(current.get("revenue"),prior.get("revenue")),
        "EBITDAGrowthPct":_growth(current.get("operating_profit"),prior.get("operating_profit")),
        "PATGrowthPct":_growth(current.get("pat"),prior.get("pat")),
        "EPSGrowthPct":_growth(current.get("eps"),prior.get("eps")),
        "ROCEPct":round(roce,2) if roce is not None else None,
        "DE_Ratio":round(debt_equity,2) if debt_equity is not None else None,
        "OCFPositive":bool(ocf>0) if ocf is not None else None,
        "OPMPct":round(opm,2) if opm is not None else None,
        "NSEFinancialSource":"Integrated Filing/XBRL",
        "NSEFinancialPeriod":latest.period_end.isoformat() if latest.period_end else None,
        "FinancialDataCurrent":bool(latest.period_end and latest.period_end>=date.today().replace(year=date.today().year-1)),
    }
