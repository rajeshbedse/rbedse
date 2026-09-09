"""BUY-candidate verification layer.

This is intentionally separate from the RYB score. The opportunity universe
remains BUY-led; this layer answers the second question: *what else did the
promoter do for the same stock?*

Outputs are suitable for joining to scored BUY candidates as an audit/risk
view and for exposing independent SELL/PLEDGE signals later in the portal.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .promoter_signals import build_promoter_signals


def verify_buy_candidates(
    csv_path: Path,
    buy_candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Join independent SELL/PLEDGE intelligence to BUY candidates.

    No-buy stocks are not introduced into the returned frame. This preserves
    the existing BUY-led opportunity engine while ensuring every BUY candidate
    is checked against market selling and pledge activity.
    """
    if buy_candidates.empty:
        return buy_candidates.copy()

    signals = build_promoter_signals(csv_path)
    if signals.empty:
        result = buy_candidates.copy()
        for col in (
            "MarketSellValue", "NetBuyValue", "SellBuyRatioPct", "SellTxn",
            "PledgeTxn", "PledgeValue", "HasMarketSell", "HasPledge",
            "PromoterSignal", "PromoterVerification",
        ):
            result[col] = 0 if col.endswith(("Value", "Txn")) else False if col.startswith("Has") else pd.NA
        return result

    cols = [
        "Symbol", "SellValue", "NetBuyValue", "SellBuyRatioPct", "SellTxn",
        "PledgeTxn", "PledgeValue", "HasMarketSell", "HasPledge", "PromoterSignal",
    ]
    verification = signals[[c for c in cols if c in signals.columns]].copy()
    verification = verification.rename(columns={"SellValue": "MarketSellValue"})

    result = buy_candidates.merge(verification, on="Symbol", how="left", suffixes=("", "_verify"))
    result["MarketSellValue"] = pd.to_numeric(result["MarketSellValue"], errors="coerce").fillna(0.0)
    result["NetBuyValue"] = pd.to_numeric(result["NetBuyValue"], errors="coerce").fillna(
        pd.to_numeric(result.get("ValuePurchased"), errors="coerce").fillna(0.0)
    )
    result["SellBuyRatioPct"] = pd.to_numeric(result["SellBuyRatioPct"], errors="coerce")
    result["SellTxn"] = pd.to_numeric(result["SellTxn"], errors="coerce").fillna(0).astype(int)
    result["PledgeTxn"] = pd.to_numeric(result["PledgeTxn"], errors="coerce").fillna(0).astype(int)
    result["PledgeValue"] = pd.to_numeric(result["PledgeValue"], errors="coerce").fillna(0.0)
    result["HasMarketSell"] = result["HasMarketSell"].fillna(False).astype(bool)
    result["HasPledge"] = result["HasPledge"].fillna(False).astype(bool)
    result["PromoterSignal"] = result["PromoterSignal"].fillna("BUY CONFIRMED")

    def _verification(row: pd.Series) -> str:
        sell = bool(row["HasMarketSell"])
        pledge = bool(row["HasPledge"])
        ratio = row["SellBuyRatioPct"]
        if pledge and sell:
            return "REVIEW — BUY + MARKET SELL + PLEDGE"
        if pledge:
            return "REVIEW — BUY + PLEDGE"
        if sell and pd.notna(ratio) and float(ratio) > 25:
            return "REVIEW — SELL >25% OF BUY"
        if sell:
            return "REVIEW — BUY + MARKET SELL"
        return "PASS — BUY ONLY"

    result["PromoterVerification"] = result.apply(_verification, axis=1)
    return result
