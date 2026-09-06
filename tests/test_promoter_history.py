import tempfile
import unittest
from pathlib import Path

import pandas as pd

from nse_pipeline.promoter_history import (
    _accumulation_stage,
    _freshness,
    build_accumulation_snapshot,
)


class PromoterTimingTests(unittest.TestCase):
    def test_freshness_bands(self):
        self.assertEqual(_freshness(0), "Fresh")
        self.assertEqual(_freshness(7), "Fresh")
        self.assertEqual(_freshness(8), "Active")
        self.assertEqual(_freshness(30), "Active")
        self.assertEqual(_freshness(31), "Aging")
        self.assertEqual(_freshness(60), "Aging")
        self.assertEqual(_freshness(61), "Stale")
        self.assertEqual(_freshness(pd.NA), "No Signal")

    def test_accumulation_stage(self):
        self.assertEqual(_accumulation_stage(3, 5, 1), "Early Accumulation")
        self.assertEqual(_accumulation_stage(20, 20, 2), "Confirmed Accumulation")
        self.assertEqual(_accumulation_stage(45, 40, 5), "Mature Accumulation")
        self.assertEqual(_accumulation_stage(90, 80, 10), "Stale Accumulation")

    def test_snapshot_uses_transaction_date_and_weighted_average(self):
        columns = [
            "Symbol", "Company Name", "Name of Person", "Category of Person",
            "Type of Instrument", "Securities Acquired/Disposed (No.)",
            "Securities Acquired/Disposed (Value)", "Transaction Type",
            "Date From", "Date To", "Mode of Acquisition/Disposal",
        ]
        rows = [
            ["TEST", "Test Co", "Promoter A", "Promoter", "Equity", "100", "10000", "Buy", "01-08-2026", "01-08-2026", "Market Purchase"],
            ["TEST", "Test Co", "Promoter A", "Promoter", "Equity", "100", "12000", "Buy", "10-08-2026", "10-08-2026", "Market Purchase"],
            ["TEST", "Test Co", "Promoter B", "Promoter Group", "Equity", "200", "26000", "Buy", "25-08-2026", "25-08-2026", "Market Purchase"],
            ["TEST", "Test Co", "Promoter A", "Promoter", "Equity", "50", "5000", "Sell", "20-08-2026", "20-08-2026", "Market Sale"],
            ["OTHER", "Other Co", "Person", "Public", "Equity", "100", "10000", "Buy", "25-08-2026", "25-08-2026", "Market Purchase"],
        ]
        frame = pd.DataFrame(rows, columns=columns)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nse.csv"
            frame.to_csv(path, index=False, encoding="utf-8-sig")
            result = build_accumulation_snapshot(path, "2026-08-28")

        row = result.loc[result["Symbol"].eq("TEST")].iloc[0]
        self.assertEqual(row["FirstBuyDate"], "01-08-2026")
        self.assertEqual(row["LastBuyDate"], "25-08-2026")
        self.assertEqual(row["DaysSinceLastBuy"], 3)
        self.assertEqual(row["AccumulationDays"], 24)
        self.assertEqual(row["BuyTxn30D"], 3)
        self.assertEqual(row["UniquePromotersBuying"], 2)
        self.assertEqual(row["Freshness"], "Fresh")
        self.assertEqual(row["AccumulationStage"], "Confirmed Accumulation")
        self.assertAlmostEqual(row["WeightedAvgBuyPrice"], 120.0, places=6)


if __name__ == "__main__":
    unittest.main()
