import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from nse_pipeline.analyzer import _apply_timing_metrics, _signal_stage


class TimingIntegrationTests(unittest.TestCase):
    def test_signal_stage_boundaries(self):
        self.assertEqual(_signal_stage("Fresh", "Early Accumulation", -5), "Early Accumulation")
        self.assertEqual(_signal_stage("Fresh", "Confirmed Accumulation", 5), "Confirmed Accumulation")
        self.assertEqual(_signal_stage("Active", "Confirmed Accumulation", 15), "Mature — Wait for Pullback")
        self.assertEqual(_signal_stage("Stale", "Stale Accumulation", 5), "Late — Poor Entry")
        self.assertEqual(_signal_stage("No Signal", "No Signal", None), "No Signal")

    def test_timing_metrics_join_and_cmp_delta(self):
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
        ]
        raw = pd.DataFrame(rows, columns=columns)
        enriched = pd.DataFrame([{"Symbol": "TEST", "AvgPrice": 120.0, "LastPrice": 132.0}])
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "nse.csv"
            raw.to_csv(csv_path, index=False, encoding="utf-8-sig")
            result = _apply_timing_metrics(enriched, csv_path, date(2026, 8, 28))

        row = result.iloc[0]
        self.assertAlmostEqual(row["PromoterAvgPrice"], 120.0, places=6)
        self.assertAlmostEqual(row["CMPvsPromoterAvgPct"], 10.0, places=6)
        self.assertEqual(row["Freshness"], "Fresh")
        self.assertEqual(row["AccumulationStage"], "Confirmed Accumulation")
        self.assertEqual(row["SignalStage"], "Confirmed Accumulation")
        self.assertEqual(row["Score"] if "Score" in row else 0, 0)


if __name__ == "__main__":
    unittest.main()
