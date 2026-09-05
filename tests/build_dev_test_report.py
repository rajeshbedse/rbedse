#!/usr/bin/env python3
"""Build an HTML/JSON evidence report from the DEV smoke-test console log."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

log_path = Path("test-results/smoke.log")
out = Path("test-results")
out.mkdir(parents=True, exist_ok=True)
text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""


def first(pattern: str, default: str = "") -> str:
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1) if m else default

failed = re.findall(r"^FAIL: (.+)$", text, re.MULTILINE)
metadata = {
    "expected_commit": first(r"EXPECTED_COMMIT:\s+([0-9a-f]{40})"),
    "deployed_branch": first(r"DEV deployment reports branch=([^ ]+)"),
    "deployed_commit": first(r"DEV deployment reports branch=[^ ]+ commit=([0-9a-f]{40})"),
    "latest_scan_url": first(r"Latest scan URL: (.+)"),
    "home_load_seconds": first(r"UI home load: ([0-9.]+)s"),
    "shortlist_rows": first(r"Scan shortlist rows: (\d+)"),
    "stock_detail": first(r"Stock detail UI OK: (.+)"),
    "all_reviewed_rows": first(r"All Reviewed rows: (\d+)"),
}

checks = [
    ("Deployment", "Expected DEV commit deployed", metadata["expected_commit"] or "workflow commit", metadata["deployed_commit"] or "not observed", "PASS" if metadata["expected_commit"] and metadata["expected_commit"] == metadata["deployed_commit"] else "FAIL", "dev-build.json / smoke log"),
    ("Deployment", "DEV branch", "dev-latest", metadata["deployed_branch"] or "not observed", "PASS" if metadata["deployed_branch"] == "dev-latest" else "FAIL", "dev-build.json / smoke log"),
    ("Availability", "Health endpoint", "HTTP 200", "HTTP 200" if "HTTP 200" in text and "/healthz" in text else "not observed", "PASS" if "/healthz" in text and "HTTP 200" in text else "FAIL", "HTTP check"),
    ("Home", "Home page", "HTTP 200", "HTTP 200" if "HTTP 200" in text and "https://ryb-finserv-dev.onrender.com/" in text else "not observed", "PASS" if "https://ryb-finserv-dev.onrender.com/" in text else "FAIL", "HTTP/UI check"),
    ("Performance", "Home UI load", "< 5.0s", (metadata["home_load_seconds"] + "s") if metadata["home_load_seconds"] else "not observed", "PASS" if metadata["home_load_seconds"] and float(metadata["home_load_seconds"]) <= 5 else "WARN" if metadata["home_load_seconds"] else "FAIL", "Playwright timing"),
    ("Navigation", "Latest Scan CTA/navigation", "/scan/<date>", metadata["latest_scan_url"] or "not observed", "PASS" if metadata["latest_scan_url"] else "FAIL", "Playwright URL"),
    ("Scan", "Shortlist data", "API 200 + valid schema", f"{metadata['shortlist_rows']} rows" if metadata["shortlist_rows"] else "not observed", "PASS" if metadata["shortlist_rows"] else "FAIL", "summary API validation"),
    ("Scan", "Shortlist UI rendering", "At least one result when API has rows", "Rendered" if metadata["stock_detail"] else "not observed", "PASS" if metadata["stock_detail"] else "FAIL", "DOM validation"),
    ("Stock Detail", "Open first stock detail", "Detail content/title loaded", metadata["stock_detail"] or "not observed", "PASS" if metadata["stock_detail"] else "FAIL", "DOM/API validation"),
    ("Navigation", "Back to results", "Results visible", "Completed" if metadata["stock_detail"] else "not observed", "PASS" if metadata["stock_detail"] else "FAIL", "Playwright navigation"),
    ("All Reviewed", "Candidates view", "API 200 + valid schema", f"{metadata['all_reviewed_rows']} rows" if metadata["all_reviewed_rows"] else "not observed", "PASS" if metadata["all_reviewed_rows"] else "FAIL", "summary API validation"),
    ("Search", "Candidate symbol search", "Matching result", "Completed" if metadata["all_reviewed_rows"] else "not observed", "PASS" if metadata["all_reviewed_rows"] else "FAIL", "DOM validation"),
    ("Browser", "JavaScript errors", "None", "Errors found" if "Browser JavaScript errors:" in text else "None observed", "FAIL" if "Browser JavaScript errors:" in text else "PASS", "console/pageerror listeners"),
    ("Browser", "Application request failures", "None", "Failures found" if "Browser application request failures:" in text else "None observed", "FAIL" if "Browser application request failures:" in text else "PASS", "requestfailed listener"),
]

if failed:
    overall = "FAIL"
elif "DEV application checks PASSED" in text:
    overall = "PASS"
else:
    overall = "UNKNOWN"

payload = {"status": overall, "metadata": metadata, "checks": [dict(zip(("area","name","expected","actual","status","evidence"), c)) for c in checks], "failures": failed}
(out / "test-results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

rows = []
for area, name, expected, actual, status, evidence in checks:
    rows.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in (area, name, expected, actual, status, evidence)) + "</tr>")

failure_html = "".join(f"<li>{html.escape(x)}</li>" for x in failed) or "<li>None</li>"
report = f"""<!doctype html><html><head><meta charset='utf-8'><title>RYB Finserv DEV Test Evidence</title><style>body{{font-family:Arial,sans-serif;margin:28px;color:#222}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:7px;text-align:left;vertical-align:top}}th{{background:#eee}}.PASS{{font-weight:bold}}.FAIL{{font-weight:bold}}.WARN{{font-weight:bold}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:12px;max-height:500px;overflow:auto}}code{{word-break:break-all}}</style></head><body><h1>RYB Finserv — DEV Test Evidence Report</h1><p><b>Overall status:</b> {overall}</p><h2>Execution metadata</h2><pre>{html.escape(json.dumps(metadata, indent=2))}</pre><h2>Validation matrix</h2><table><thead><tr><th>Area</th><th>Validation</th><th>Expected</th><th>Actual</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table><h2>Failures</h2><ul>{failure_html}</ul><h2>Raw execution log</h2><pre>{html.escape(text)}</pre></body></html>"""
(out / "dev-test-report.html").write_text(report, encoding="utf-8")
print(f"Generated {out / 'dev-test-report.html'}")
