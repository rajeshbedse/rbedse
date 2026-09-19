"""
Phase 3 — Proximity Report & Excel Export

Prints tiered proximity sections to the log and exports a
three-sheet Excel workbook:
  Sheet 1 — ScoredStocks  (final shortlist, sorted by Score descending)
  Sheet 2 — FilteredStocks (same data, backward-compatible column set)
  Sheet 3 — Summary        (band + category counts)
"""
import logging
from pathlib import Path

import pandas as pd

from .config import MIN_PROMO_HOLDING, MIN_PURCHASE_VALUE, PRICE_PROXIMITY_BANDS

log = logging.getLogger(__name__)

REPORT_COLS = [
    "Symbol", "CompanyName", "LastPrice", "AvgPrice", "PriceDiffPct",
    "PromoHolding", "ValueCr", "NumBuyTxn", "acqtoDt",
]

SCORE_COLS = [
    "Symbol", "CompanyName", "Score", "Category",
    "ScorePromo", "ScoreFund", "ScoreTech", "ScoreRisk",
    "LastPrice", "AvgPrice", "PriceDiffPct",
    "PromoHolding", "ValueCr", "MarketBuyValue", "MarketSellValue", "NetBuyValue",
    "SellBuyRatioPct", "PromoterFlowStatus", "TransferLikeFiling", "NumBuyTxn", "acqtoDt",
    "PromoConvictionPct",
    "MarketCapCr", "PE",
    "RevGrowthPct", "EBITDAGrowthPct", "PATGrowthPct", "EPSGrowthPct",
    "ROCEPct", "DE_Ratio", "OCFPositive", "OPMPct",
    "DMA50", "DMA200", "SixMonthReturn",
    # Promoter timing is descriptive only; it never changes Score/Category.
    "PromoterAvgPrice", "CMPvsPromoterAvgPct", "Freshness", "AccumulationStage",
    "SignalStage", "FirstBuyDate", "LastBuyDate", "AccumulationDays",
    "DaysSinceFirstBuy", "DaysSinceLastBuy", "BuyTxn7D", "BuyTxn15D",
    "BuyTxn30D", "BuyTxn60D", "BuyTxn90D", "BuyValue7D", "BuyValue15D",
    "BuyValue30D", "BuyValue60D", "BuyValue90D", "SellTxn7D", "SellTxn15D", "SellTxn30D",
    "SellTxn60D", "SellTxn90D", "SellValue7D", "SellValue15D", "SellValue30D",
    "SellValue60D", "SellValue90D", "NetBuyValue7D", "NetBuyValue30D",
    "UniquePromotersBuying", "UniquePromotersSelling",
    "BuyAcceleration",
]


def _compute_bands(final: pd.DataFrame) -> list[dict]:
    """
    Compute proximity band memberships for *final*.

    Returns a list of dicts:
        [{"label": str, "log_label": str, "mask": pd.Series, "count": int}, ...]
    One entry per band defined in PRICE_PROXIMITY_BANDS, ordered lowest→highest.
    """
    bands = sorted(PRICE_PROXIMITY_BANDS)
    result = []
    prev = 0
    for band in bands:
        if prev == 0:
            mask      = final["AbsDiffPct"] <= band
            label     = f"±0–{band}%"
            log_label = f"✅  WITHIN ±{band}%  — Price very close to promoter buy price"
        else:
            mask      = (final["AbsDiffPct"] > prev) & (final["AbsDiffPct"] <= band)
            label     = f"±{prev+1}–{band}%"
            log_label = f"🟡  WITHIN ±{prev+1}–{band}%  — Near promoter buy price"
        result.append({
            "label"    : label,
            "log_label": log_label,
            "mask"     : mask,
            "count"    : int(mask.sum()),
        })
        prev = band
    last_band = bands[-1]
    beyond_mask = final["AbsDiffPct"] > last_band
    result.append({
        "label"    : f">{last_band}%",
        "log_label": f"  BEYOND ±{last_band}%",
        "mask"     : beyond_mask,
        "count"    : int(beyond_mask.sum()),
    })
    return result


def _section(df_sub: pd.DataFrame, title: str) -> None:
    log.info("\n%s\n%s\n%s", "=" * 90, title, "=" * 90)
    if df_sub.empty:
        log.info("  — none —")
    else:
        log.info("\n%s", df_sub[REPORT_COLS].to_string(index=False))


def _category_order(cat: str) -> int:
    """Sort key so categories print in a natural priority order."""
    order = {
        "Strong Buy Setup"  : 0,
        "Buy on Breakout"   : 1,
        "Watchlist"         : 2,
        "Fundamental Watch" : 3,
        "Avoid"             : 4,
    }
    return order.get(cat, 9)


def run(final: pd.DataFrame, excel_path: Path) -> None:
    """Phase 3: print proximity sections + export Excel."""
    log.info("━" * 60)
    log.info("PHASE 3 — Proximity report")
    log.info("━" * 60)

    bands = _compute_bands(final)

    for b in bands[:-1]:
        _section(final[b["mask"]], b["log_label"])

    _section(
        final[final["PriceDiffPct"] < 0],
        "⭐  PRICE BELOW PROMOTER AVG BUY — Trading cheaper than what promoter paid",
    )

    log.info("\n%s", "=" * 90)
    log.info(
        "SCORED TABLE — %d symbols | sorted by Score descending\n"
        "Filters: ≥₹%.0fL buys · Market Purchase · No pledging · No promo sell · "
        "Promo holding ≥%.0f%%",
        len(final), MIN_PURCHASE_VALUE / 1e5, MIN_PROMO_HOLDING,
    )
    log.info("%s", "=" * 90)
    score_display_cols = [c for c in SCORE_COLS if c in final.columns]
    log.info("\n%s", final[score_display_cols].to_string(index=False))

    excel_path.parent.mkdir(parents=True, exist_ok=True)

    summary_rows = [{"Band": b["label"], "Count": b["count"]} for b in bands]
    summary_rows.append({
        "Band":  "Below avg buy price",
        "Count": int((final["PriceDiffPct"] < 0).sum()),
    })
    if "Category" in final.columns:
        for cat, grp in final.groupby("Category"):
            summary_rows.append({"Band": f"[Category] {cat}", "Count": len(grp)})

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        scored_cols = [c for c in SCORE_COLS if c in final.columns]
        final[scored_cols].to_excel(writer, index=False, sheet_name="ScoredStocks")
        ws1 = writer.sheets["ScoredStocks"]
        for col in ws1.columns:
            ws1.column_dimensions[col[0].column_letter].width = min(
                max(len(str(c.value or "")) for c in col) + 4, 45
            )

        final[REPORT_COLS].to_excel(writer, index=False, sheet_name="FilteredStocks")
        ws2 = writer.sheets["FilteredStocks"]
        for col in ws2.columns:
            ws2.column_dimensions[col[0].column_letter].width = min(
                max(len(str(c.value or "")) for c in col) + 4, 45
            )

        pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name="Summary")

    log.info("Excel exported → %s", excel_path)
