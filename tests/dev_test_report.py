#!/usr/bin/env python3
"""Generate a compact HTML/JSON evidence report from DEV smoke-test results."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path

OUT = Path(os.environ.get("DEV_REPORT_DIR", "test-results"))
OUT.mkdir(parents=True, exist_ok=True)

# The smoke test writes this file incrementally when available.
source = Path(os.environ.get("DEV_RESULTS_JSON", OUT / "results.json"))
if source.exists():
    data = json.loads(source.read_text(encoding="utf-8"))
else:
    data = {"status": "UNKNOWN", "tests": [], "metadata": {}}

status = str(data.get("status", "UNKNOWN"))
metadata = data.get("metadata", {})
tests = data.get("tests", [])
counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "INFO": 0}
for test in tests:
    counts[str(test.get("status", "INFO")).upper()] = counts.get(str(test.get("status", "INFO")).upper(), 0) + 1

data["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
data["summary"] = counts
source.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

rows = []
for test in tests:
    s = str(test.get("status", "INFO")).upper()
    rows.append(
        "<tr><td>" + escape(str(test.get("area", ""))) + "</td>"
        + "<td>" + escape(str(test.get("name", ""))) + "</td>"
        + "<td>" + escape(str(test.get("expected", ""))) + "</td>"
        + "<td>" + escape(str(test.get("actual", ""))) + "</td>"
        + f'<td class="{escape(s.lower())}">{escape(s)}</td>'
        + "<td>" + escape(str(test.get("evidence", ""))) + "</td></tr>"
    )

html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>RYB Finserv DEV Test Evidence</title>
<style>body{{font-family:Arial,sans-serif;margin:32px;color:#222}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:8px;text-align:left;vertical-align:top}}th{{background:#eee}}.pass{{font-weight:700}}.fail{{font-weight:700}}.warn{{font-weight:700}}.summary{{display:flex;gap:24px;margin:18px 0}}.card{{padding:12px 18px;border:1px solid #ccc;border-radius:6px}}code{{word-break:break-all}}</style></head>
<body><h1>RYB Finserv — DEV Test Evidence Report</h1>
<p><b>Overall status:</b> {escape(status)}<br><b>Generated:</b> {escape(data['generated_at_utc'])}</p>
<div class="summary">{''.join(f'<div class="card"><b>{k}</b><br>{v}</div>' for k,v in counts.items())}</div>
<h2>Execution metadata</h2><pre>{escape(json.dumps(metadata, indent=2, ensure_ascii=False))}</pre>
<h2>Test cases and evidence</h2><table><thead><tr><th>Area</th><th>Validation</th><th>Expected</th><th>Actual</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body></html>"""
(OUT / "dev-test-report.html").write_text(html, encoding="utf-8")
print(f"Report written to {OUT / 'dev-test-report.html'}")
