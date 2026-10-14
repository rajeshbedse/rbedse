from __future__ import annotations

from datetime import date
from unittest.mock import patch

from nse_pipeline import analyzer


def test_parse_52_week_report_tolerates_bom_and_report_preamble():
    csv_text = """\ufeffNSE 52 Week High Low Report
SYMBOL,Adjusted 52_Week_High,Adjusted 52_Week_Low
ABC,125.50,75.25
XYZ,500,310
"""
    result = analyzer._parse_52_week_rows(csv_text)

    assert result["ABC"] == {"52WeekHigh": 125.5, "52WeekLow": 75.25}
    assert result["XYZ"] == {"52WeekHigh": 500.0, "52WeekLow": 310.0}


def test_download_52_week_report_uses_latest_report_discovered_by_nse():
    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = 0

        def get(self, url, timeout):
            self.calls += 1
            if url == analyzer._WEEK52_API:
                return FakeResponse(200, {
                    "CurrentDay": [],
                    "PreviousDay": [{
                        "fileKey": "CM-52 WEEK-HIGH_LOW",
                        "tradingDate": "13-Oct-2026",
                        "filePath": "https://example.test/",
                        "fileActlName": "week52.csv",
                    }],
                })
            return FakeResponse(
                200,
                text="SYMBOL,Adjusted 52_Week_High,Adjusted 52_Week_Low\nABC,125.5,75.25\n",
            )

    session = FakeSession()
    with patch.object(analyzer.requests, "Session", return_value=session):
        result = analyzer._download_52_week_report(as_of_date=date(2026, 10, 14))

    assert result["ABC"] == {"52WeekHigh": 125.5, "52WeekLow": 75.25}
    assert session.calls == 2
