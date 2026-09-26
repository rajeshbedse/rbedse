"""Shared NSE transaction de-duplication helpers.

Keeps the transaction population used by scoring, timing metrics and research
datasets consistent when NSE republishes the same transaction in later filings.
"""
from __future__ import annotations

import pandas as pd

TRANSACTION_CORE_COLUMNS = [
    "Symbol", "Name of Person", "CIN/DIN", "Type of Instrument",
    "Securities Acquired/Disposed (No.)",
    "Securities Acquired/Disposed (Value)", "Transaction Type", "Date From",
    "Date To", "Mode of Acquisition/Disposal",
]


def _normalise_key_value(value) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().upper().split())


def deduplicate_transactions(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove repeated NSE filings while retaining the latest disclosure."""
    if df.empty:
        return df.copy(), 0

    work = df.copy()
    work.columns = work.columns.str.strip()

    exact_cols = [
        c for c in [
            "Details URL", *TRANSACTION_CORE_COLUMNS,
            "Securities Held Prior (No.)", "Securities Held Prior (%)",
            "Securities Held Post (No.)", "Securities Held Post (%)",
            "Date From", "Date To", "Date of Intimation",
        ] if c in work.columns
    ]
    before = len(work)
    if exact_cols:
        work = work.drop_duplicates(subset=exact_cols, keep="last").copy()

    key_cols = [c for c in TRANSACTION_CORE_COLUMNS if c in work.columns]
    for col in key_cols:
        work[f"__txn_{col}"] = work[col].map(_normalise_key_value)
    work["__txn_core_key"] = work[[f"__txn_{c}" for c in key_cols]].agg("|".join, axis=1)
    work["__broadcast_dt"] = pd.to_datetime(
        work.get("Broadcast Date/Time", ""), errors="coerce", dayfirst=True
    )

    if "Details URL" in work.columns:
        filing_meta = (
            work[["__txn_core_key", "Details URL", "__broadcast_dt"]]
            .drop_duplicates()
            .sort_values(
                ["__txn_core_key", "__broadcast_dt", "Details URL"],
                na_position="first",
            )
        )
        latest_filing = (
            filing_meta.groupby("__txn_core_key", dropna=False, as_index=False)
            .tail(1)[["__txn_core_key", "Details URL"]]
        )
        work = work.merge(
            latest_filing.assign(__keep=True),
            on=["__txn_core_key", "Details URL"],
            how="inner",
        ).drop(columns=["__keep"])
    else:
        latest = work.groupby("__txn_core_key", dropna=False)["__broadcast_dt"].transform("max")
        work = work[
            work["__broadcast_dt"].eq(latest) | work["__broadcast_dt"].isna()
        ].copy()

    helper_cols = [
        c for c in work.columns
        if c.startswith("__txn_") or c == "__broadcast_dt"
    ]
    work = work.drop(columns=helper_cols, errors="ignore")
    return work.reset_index(drop=True), before - len(work)
