"""Independent promoter-event intelligence for BUY-candidate verification.

The existing RYB opportunity engine remains BUY-led: a stock must still have a
qualifying promoter market BUY to enter the scored opportunity universe.

This module deliberately keeps SELL and PLEDGE as independent event streams so
that BUY candidates can be re-verified against distribution/pledge risk, while
also preserving standalone SELL/PLEDGE signals for audit and future portal use.
Standalone signals are informational only and are never added to the RYB score.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .config import MIN_PURCHASE_VALUE, PLEDGE_MODES, PROMOTER_CATEGORIES


def _num(value) -> float:
    if pd.isna(value):
        return 0.0
    text = str(value).strip().replace(",", "")
    try:
        return float(re.sub(r"[^0-9.\-]", "", text) or 0)
    except ValueError:
        return 0.0


def build_promoter_signals(csv_path: Path) -> pd.DataFrame:
    """Build symbol-level BUY/SELL/PLEDGE intelligence from the raw NSE snapshot."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()

    category = df["Category of Person"].fillna("").str.strip().str.lower()
    instrument = df["Type of Instrument"].fillna("").str.strip().str.lower()
    tx_type = df["Transaction Type"].fillna("").str.strip().str.lower()
    mode = df["Mode of Acquisition/Disposal"].fillna("").str.strip().str.lower()

    promo = df.loc[category.isin(PROMOTER_CATEGORIES) & instrument.eq("equity")].copy()
    promo["_value"] = promo["Securities Acquired/Disposed (Value)"].map(_num)
    promo["_qty"] = promo["Securities Acquired/Disposed (No.)"].map(_num)

    is_buy = tx_type.loc[promo.index].eq("buy") & mode.loc[promo.index].eq("market purchase")
    is_sell = tx_type.loc[promo.index].eq("sell") & mode.loc[promo.index].eq("market sale")
    is_pledge = mode.loc[promo.index].isin(PLEDGE_MODES)

    promo["_buy"] = is_buy
    promo["_sell"] = is_sell
    promo["_pledge"] = is_pledge

    rows = []
    for symbol, g in promo.groupby("Symbol", dropna=False):
        symbol = str(symbol).strip().upper()
        buys = g[g["_buy"]]
        sells = g[g["_sell"]]
        pledges = g[g["_pledge"]]
        buy_value = float(buys["_value"].sum())
        sell_value = float(sells["_value"].sum())
        qualified_buy = buy_value >= MIN_PURCHASE_VALUE
        has_sell = sell_value > 0
        has_pledge = not pledges.empty
        ratio = (sell_value / buy_value * 100) if buy_value > 0 else pd.NA

        if qualified_buy:
            if has_pledge and has_sell:
                signal = "BUY + SELL + PLEDGE"
            elif has_pledge:
                signal = "BUY + PLEDGE RISK"
            elif has_sell:
                signal = "BUY + SELL"
            else:
                signal = "BUY CONFIRMED"
        elif has_sell and has_pledge:
            signal = "STANDALONE SELL + PLEDGE"
        elif has_sell:
            signal = "STANDALONE SELL"
        elif has_pledge:
            signal = "STANDALONE PLEDGE"
        else:
            continue

        rows.append({
            "Symbol": symbol,
            "CompanyName": g["Company Name"].dropna().iloc[0] if "Company Name" in g.columns and not g["Company Name"].dropna().empty else "",
            "BuyValue": round(buy_value, 2),
            "SellValue": round(sell_value, 2),
            "NetBuyValue": round(buy_value - sell_value, 2),
            "SellBuyRatioPct": round(float(ratio), 2) if pd.notna(ratio) else pd.NA,
            "BuyTxn": int(len(buys)),
            "SellTxn": int(len(sells)),
            "PledgeTxn": int(len(pledges)),
            "PledgeValue": round(float(pledges["_value"].sum()), 2),
            "QualifiedBuy": bool(qualified_buy),
            "HasMarketSell": bool(has_sell),
            "HasPledge": bool(has_pledge),
            "PromoterSignal": signal,
        })

    return pd.DataFrame(rows).sort_values(
        ["QualifiedBuy", "BuyValue", "SellValue"],
        ascending=[False, False, False],
    ).reset_index(drop=True) if rows else pd.DataFrame()


def write_promoter_signals(csv_path: Path, out_path: Path) -> int:
    """Write the independent promoter signal stream for the current scan."""
    signals = build_promoter_signals(csv_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    signals.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(signals)
