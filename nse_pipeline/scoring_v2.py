"""RYB scoring v2.

V2 is the active score. The previous production scorer remains available as a
shadow score (ScoreV1 / ScorePromoV1 / ScoreFundV1 / ScoreTechV1 /
ScoreRiskV1 / CategoryV1) so daily runs can be compared without changing the
historical v1 calculation.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

# State is deliberately module-local: one pipeline run is single-process and
# scoring happens synchronously after timing metrics have been attached.
_ORIGINAL_SCORE_ROW = None
_ORIGINAL_APPLY_SCORES = None
_ORIGINAL_BUILD_AGGREGATES = None
_SHADOW: dict[str, tuple[int, int, int, int, int, str]] = {}
_RISK: dict[str, dict[str, float | bool]] = {}
_INSTALLED = False


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _band(value: float, bands: list[tuple[float, int]]) -> int:
    score = 0
    for threshold, points in bands:
        if value >= threshold:
            score = points
        else:
            break
    return score


def _promoter_v2(row: pd.Series, fund: dict) -> int:
    market_cap = _num(fund.get("MarketCapCr"))
    # Economic commitment is based on net promoter-group buying. Gross buys
    # remain available for disclosure/audit but must not inflate conviction
    # when promoter selling offsets them.
    net_buy_value_cr = max(0.0, _num(row.get("NetBuyValue")) / 1e7)
    last_price = _num(row.get("LastPrice"))
    holding = _num(row.get("PromoHolding"))

    # 1) Economic commitment: net buy value relative to company market value.
    buy_mcap_pct = (net_buy_value_cr / market_cap * 100.0) if market_cap > 0 else 0.0
    intensity = _band(buy_mcap_pct, [
        (0.10, 2), (0.25, 4), (0.50, 6), (1.00, 8), (2.00, 10),
    ])

    # 2) Incremental ownership / existing promoter exposure.
    # Market cap / CMP implies shares outstanding. This is explicitly an
    # estimate; the raw transaction quantity is authoritative, but shares
    # outstanding are not currently supplied by the Screener parser.
    qty = max(0.0, _num(row.get("NetBuyQty")))
    implied_shares = (market_cap * 1e7 / last_price) if market_cap > 0 and last_price > 0 else 0.0
    stake_add_pct = (qty / implied_shares * 100.0) if implied_shares > 0 else 0.0
    exposure_increase_pct = (stake_add_pct / holding * 100.0) if holding > 0 else 0.0
    exposure = _band(exposure_increase_pct, [
        (0.50, 2), (1.00, 4), (2.00, 6), (5.00, 8),
    ])

    # 3) Persistence across the five rolling windows. A window counts
    # only when there is net buying, not merely gross purchase activity.
    windows = [
        _num(row.get(f"NetBuyValue{days}D")) > 0
        for days in (7, 15, 30, 60, 90)
    ]
    active_windows = sum(windows)
    persistence = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}[active_windows]

    # 4) Recency + acceleration. Keep the two signals bounded so a single
    # anomalous transaction cannot dominate the score.
    days_since = _num(row.get("DaysSinceLastBuy"), 9999)
    recency = 2 if days_since <= 7 else (1 if days_since <= 21 else 0)
    acceleration_value = _num(row.get("BuyAcceleration"))
    acceleration = 2 if acceleration_value > 1 else (1 if acceleration_value > 0.25 else 0)

    # 5) Participation: independent promoters buying increases breadth.
    buyers = int(_num(row.get("UniquePromotersBuying")))
    participation = min(3, max(0, buyers))

    return min(30, intensity + exposure + persistence + recency + acceleration + participation)


def _fundamental_v2(row: pd.Series, fund: dict) -> int:
    score = 0
    if _num(fund.get("RevGrowthPct")) > 15: score += 4
    if _num(fund.get("EBITDAGrowthPct")) > 15: score += 4
    if _num(fund.get("PATGrowthPct")) > 15: score += 6
    if _num(fund.get("EPSGrowthPct")) > 15: score += 4
    if _num(fund.get("ROCEPct")) > 15: score += 4
    de = fund.get("DE_Ratio")
    if de is not None and not pd.isna(de) and _num(de) < 0.5: score += 3
    if fund.get("OCFPositive") is True: score += 5
    return min(30, score)


def _technical_v2(row: pd.Series, fund: dict) -> int:
    last = _num(row.get("LastPrice"))
    avg = _num(row.get("PromoterAvgPrice")) or _num(row.get("AvgPrice"))
    dma50 = _num(fund.get("DMA50"))
    dma200 = _num(fund.get("DMA200"))
    six_m = fund.get("SixMonthReturn")
    score = 0
    if last > avg > 0: score += 4
    if dma50 > 0 and last > dma50: score += 4
    if dma200 > 0 and last > dma200: score += 4
    if dma50 > 0 and dma200 > 0 and dma50 > dma200: score += 4
    if _num(row.get("PriceDiffPct")) > 5 and _num(row.get("NumBuyTxn")) >= 2: score += 4
    if six_m is not None and not pd.isna(six_m) and _num(six_m) > 0: score += 5
    return min(25, score)


def _risk_v2(symbol: str, row: pd.Series, fund: dict) -> int:
    risk = _RISK.get(symbol, {})
    pledge_ratio = _num(risk.get("PledgeBuyRatioPct"))
    sell_ratio = _num(row.get("SellBuyRatioPct"))
    net_buy_value = _num(row.get("NetBuyValue"))

    # Risk is magnitude-based, but net promoter selling is materially
    # different from a small offsetting sale. A gross-buy signal must not
    # remain strongly positive when promoter-group flow is net negative.
    if pledge_ratio <= 0: pledge = 0
    elif pledge_ratio <= 5: pledge = -2
    elif pledge_ratio <= 15: pledge = -4
    elif pledge_ratio <= 30: pledge = -6
    else: pledge = -8

    if net_buy_value < 0 and sell_ratio >= 100:
        sell = -10
    elif net_buy_value < 0:
        sell = -7
    elif sell_ratio <= 0: sell = 0
    elif sell_ratio <= 5: sell = -1
    elif sell_ratio <= 15: sell = -2
    elif sell_ratio <= 30: sell = -4
    else: sell = -5

    margin = -1 if fund.get("OPMPct") is not None and _num(fund.get("OPMPct")) < 5 else 0
    high_pe = -1 if fund.get("PE") is not None and _num(fund.get("PE")) > 60 else 0
    return max(-15, pledge + sell + margin + high_pe)


def _score_v2(symbol: str, row: pd.Series, fund: dict) -> tuple[int, int, int, int, int, str]:
    promo = _promoter_v2(row, fund)
    fundamentals = _fundamental_v2(row, fund)
    technical = _technical_v2(row, fund)
    risk = _risk_v2(symbol, row, fund)

    # Gross v2 model is 85 points (30+30+25). Normalize to the familiar
    # 100-point RYB scale, then apply the separate risk deduction.
    gross = round((promo + fundamentals + technical) / 85 * 100)
    total = max(0, min(100, gross + risk))
    if total >= 65: category = "Strong Buy Setup"
    elif total >= 50: category = "Buy on Breakout"
    elif total >= 40: category = "Watchlist"
    elif total >= 30: category = "Fundamental Watch"
    else: category = "Avoid"
    return promo, fundamentals, technical, risk, total, category


def _build_risk_map(csv_path: Path, buy_values: pd.Series) -> None:
    global _RISK
    raw = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    raw.columns = raw.columns.str.strip()
    if "Category of Person" not in raw.columns:
        return
    cat = raw["Category of Person"].fillna("").str.strip().str.lower()
    promo = raw[cat.isin({"promoter", "promoter group", "promoter and director"})].copy()
    if promo.empty:
        return
    mode = promo["Mode of Acquisition/Disposal"].fillna("").str.strip().str.lower()
    pledge = promo[mode.isin({"pledge creation", "invocation of pledge"})].copy()
    if pledge.empty:
        pledge_values = pd.Series(dtype=float)
    else:
        def parse(v):
            try:
                return float(re.sub(r"[^\d.]", "", str(v)) or 0)
            except (TypeError, ValueError):
                return 0.0
        pledge["_value"] = pledge["Securities Acquired/Disposed (Value)"].map(parse)
        pledge_values = pledge.groupby("Symbol")["_value"].sum()
    _RISK = {}
    for sym, buy_value in buy_values.items():
        pv = float(pledge_values.get(sym, 0.0))
        bv = float(buy_value or 0.0)
        _RISK[str(sym)] = {
            "HasPledging": pv > 0,
            "PledgeValue": pv,
            "PledgeBuyRatioPct": (pv / bv * 100.0) if bv > 0 else 0.0,
        }


def install(analyzer_module) -> None:
    """Install v2 as active scoring while retaining v1 as a shadow score."""
    global _ORIGINAL_SCORE_ROW, _ORIGINAL_APPLY_SCORES, _ORIGINAL_BUILD_AGGREGATES, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_SCORE_ROW = analyzer_module._score_row
    _ORIGINAL_APPLY_SCORES = analyzer_module._apply_scores
    _ORIGINAL_BUILD_AGGREGATES = analyzer_module._build_aggregates

    def shadow_score(row: pd.Series, fund: dict):
        symbol = str(row.get("Symbol", ""))
        old = _ORIGINAL_SCORE_ROW(row, fund)
        _SHADOW[symbol] = old
        return _score_v2(symbol, row, fund)

    def build_aggregates(csv_path: Path):
        agg, _pledge_syms, _sell_syms = _ORIGINAL_BUILD_AGGREGATES(csv_path)
        buy_values = agg.set_index("Symbol")["PricedValuePurchased"]
        _build_risk_map(csv_path, buy_values)
        # Pledge/sell are risk context, never eligibility filters in v2.
        return agg, set(), set()

    def apply_scores(df: pd.DataFrame, screener_data: dict, dma_data: dict | None = None):
        # Restore risk context before the scorer is called. The original scorer
        # is invoked by shadow_score, while v2 reads these values independently.
        for idx in df.index:
            sym = str(df.at[idx, "Symbol"])
            risk = _RISK.get(sym, {})
            df.at[idx, "HasPledging"] = bool(risk.get("HasPledging", False))
            df.at[idx, "PledgeValue"] = _num(risk.get("PledgeValue"))
            df.at[idx, "PledgeBuyRatioPct"] = _num(risk.get("PledgeBuyRatioPct"))
            df.at[idx, "SellBuyRatioPct"] = _num(df.at[idx, "SellBuyRatioPct"])
        result = _ORIGINAL_APPLY_SCORES(df, screener_data, dma_data)
        shadow_cols = {
            "ScorePromoV1": [], "ScoreFundV1": [], "ScoreTechV1": [],
            "ScoreRiskV1": [], "ScoreV1": [], "CategoryV1": [],
            "BuyMarketCapPct": [], "NetBuyMarketCapPct": [],
            "PromoterStakeAdditionPct": [], "PromoterOwnershipIncreasePct": [],
        }
        for _, row in result.iterrows():
            symbol = str(row["Symbol"])
            old = _SHADOW.get(symbol, (0, 0, 0, 0, 0, "Avoid"))
            shadow_cols["ScorePromoV1"].append(old[0])
            shadow_cols["ScoreFundV1"].append(old[1])
            shadow_cols["ScoreTechV1"].append(old[2])
            shadow_cols["ScoreRiskV1"].append(old[3])
            shadow_cols["ScoreV1"].append(old[4])
            shadow_cols["CategoryV1"].append(old[5])
            mc = _num(row.get("MarketCapCr"))
            buy_cr = _num(row.get("ValueCr"))
            net_buy_cr = max(0.0, _num(row.get("NetBuyValue")) / 1e7)
            cmp = _num(row.get("LastPrice"))
            qty = max(0.0, _num(row.get("NetBuyQty")))
            holding = _num(row.get("PromoHolding"))
            buy_pct = buy_cr / mc * 100 if mc > 0 else 0.0
            shares = mc * 1e7 / cmp if mc > 0 and cmp > 0 else 0.0
            stake_pct = qty / shares * 100 if shares > 0 else 0.0
            exposure_pct = stake_pct / holding * 100 if holding > 0 else 0.0
            shadow_cols["BuyMarketCapPct"].append(round(buy_pct, 3))
            shadow_cols["NetBuyMarketCapPct"].append(round(net_buy_cr / mc * 100, 3) if mc > 0 else 0.0)
            shadow_cols["PromoterStakeAdditionPct"].append(round(stake_pct, 3))
            shadow_cols["PromoterOwnershipIncreasePct"].append(round(exposure_pct, 3))
        for col, values in shadow_cols.items():
            result[col] = values
        return result

    analyzer_module._score_row = shadow_score
    analyzer_module._build_aggregates = build_aggregates
    analyzer_module._apply_scores = apply_scores
    _INSTALLED = True
