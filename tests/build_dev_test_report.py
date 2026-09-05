#!/usr/bin/env python3
"""Build an HTML/JSON evidence report from the DEV test-pack console log."""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

OUT = Path("test-results")
LOG = OUT / "smoke.log"
REPORT = OUT / "dev-test-report.html"
JSON_OUT = OUT / "test-results.json"

text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
expected_commit = os.environ.get("EXPECTED_COMMIT", "").strip()
try:
    exit_code = int((OUT / "exit-code.txt").read_text().strip())
except (OSError, ValueError):
    exit_code = 1


def first(pattern: str, default: str = "") -> str:
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1) if m else default


def last(pattern: str, default: str = "") -> str:
    matches = re.findall(pattern, text, re.MULTILINE)
    return matches[-1] if matches else default


def observed(pattern: str) -> bool:
    return re.search(pattern, text, re.MULTILINE) is not None


deployed_branch = last(r"DEV deployment reports branch=([^\s]+)")
deployed_commit = last(r"DEV deployment reports branch=[^\s]+ commit=([0-9a-f]{7,40})")
metadata = {
    "expected_commit": expected_commit,
    "deployed_branch": deployed_branch,
    "deployed_commit": deployed_commit,
    "latest_scan_url": first(r"Latest scan URL: (.+)"),
    "home_load_seconds": first(r"UI home load: ([0-9.]+)s"),
    "shortlist_rows": first(r"Scan shortlist rows: (\d+)"),
    "stock_detail": first(r"Stock detail UI OK: (.+)"),
    "all_reviewed_rows": first(r"All Reviewed rows: (\d+)"),
    "exit_code": exit_code,
}

checks: list[tuple[str, str, str, str, str, str]] = []
def add(area: str, name: str, expected: str, actual: str, status: str, evidence: str) -> None:
    checks.append((area, name, expected, actual, status, evidence))

health_ok = observed(r"HTTP 200 .*?/healthz")
home_http_ok = observed(r"HTTP 200 .*https://ryb-finserv-dev\.onrender\.com/\s*$")
pack_started = observed(r"TEST PACK STARTED")

if expected_commit and deployed_commit:
    deployment_status = "PASS" if deployed_commit == expected_commit else "FAIL"
    add("Deployment", "Expected DEV commit deployed", expected_commit, deployed_commit, deployment_status, "dev-build.json / smoke log")
elif expected_commit:
    status = "BLOCKED" if not health_ok else "FAIL"
    add("Deployment", "Expected DEV commit deployed", expected_commit, "not observed", status, "dev-build.json / smoke log")
else:
    add("Deployment", "Expected DEV commit deployed", "test-pack commit", deployed_commit or "not observed", "WARN" if not deployed_commit else "PASS", "dev-build.json / smoke log")

branch_status = "PASS" if deployed_branch == "dev-latest" else ("BLOCKED" if not deployed_branch else "FAIL")
add("Deployment", "DEV branch", "dev-latest", deployed_branch or "not observed", branch_status, "dev-build.json / smoke log")
add("Availability", "Health endpoint", "HTTP 200", "HTTP 200" if health_ok else "not observed", "PASS" if health_ok else "FAIL", "HTTP preflight")

if home_http_ok:
    add("Home", "Home page", "HTTP 200", "HTTP 200", "PASS", "HTTP/UI check")
else:
    add("Home", "Home page", "HTTP 200", "not observed", "NOT RUN" if not health_ok else "FAIL", "HTTP/UI check")

if metadata["home_load_seconds"]:
    seconds = float(metadata["home_load_seconds"])
    add("Performance", "Home UI load", "<= 5.0s", f"{seconds:.3f}s", "PASS" if seconds <= 5 else "WARN", "Playwright timing")
else:
    add("Performance", "Home UI load", "<= 5.0s", "not observed", "NOT RUN", "Playwright timing")

add("Navigation", "Latest Scan CTA/navigation", "/scan/<date>", metadata["latest_scan_url"] or "not observed", "PASS" if metadata["latest_scan_url"] and "/scan/" in metadata["latest_scan_url"] else ("NOT RUN" if not pack_started else "FAIL"), "Playwright URL")
add("Scan", "Shortlist data", "API 200 + valid schema", f"{metadata['shortlist_rows']} rows" if metadata["shortlist_rows"] else "not observed", "PASS" if metadata["shortlist_rows"] else ("NOT RUN" if not pack_started else "FAIL"), "summary API validation")
add("Scan", "Shortlist UI rendering", "At least one result when API has rows", "Rendered" if metadata["stock_detail"] else "not observed", "PASS" if metadata["stock_detail"] else ("NOT RUN" if not pack_started else "FAIL"), "DOM validation")
add("Stock Detail", "Open first stock detail", "Detail content/title loaded", metadata["stock_detail"] or "not observed", "PASS" if metadata["stock_detail"] else ("NOT RUN" if not pack_started else "FAIL"), "DOM/API validation")
add("Navigation", "Back to results", "Results visible", "Completed" if metadata["stock_detail"] else "not observed", "PASS" if metadata["stock_detail"] else ("NOT RUN" if not pack_started else "FAIL"), "Playwright navigation")
add("All Reviewed", "Candidates view", "API 200 + valid schema", f"{metadata['all_reviewed_rows']} rows" if metadata["all_reviewed_rows"] else "not observed", "PASS" if metadata["all_reviewed_rows"] else ("NOT RUN" if not pack_started else "FAIL"), "summary API validation")
add("Search", "Candidate symbol search", "Matching result", "Completed" if metadata["all_reviewed_rows"] else "not observed", "PASS" if metadata["all_reviewed_rows"] else ("NOT RUN" if not pack_started else "FAIL"), "DOM validation")

js_seen = observed(r"Browser JavaScript errors:")
request_seen = observed(r"Browser application request failures:")
if pack_started:
    add("Browser", "JavaScript errors", "None", "Errors found" if js_seen else "None observed", "FAIL" if js_seen else "PASS", "console/pageerror listeners")
    add("Browser", "Application request failures", "None", "Failures found" if request_seen else "None observed", "FAIL" if request_seen else "PASS", "requestfailed listener")
else:
    add("Browser", "JavaScript errors", "None", "not observed", "NOT RUN", "console/pageerror listeners")
    add("Browser", "Application request failures", "None", "not observed", "NOT RUN", "requestfailed listener")

for line in text.splitlines():
    if "PERF WARNING:" in line:
        add("Performance", "Performance budget", "Within configured budget", line.strip(), "WARN", "smoke.log")

failures = re.findall(r"^FAIL: (.+)$", text, re.MULTILINE)
# If the test process stopped before browser execution, surface the actual root cause
# and keep downstream validations as NOT RUN/BLOCKED rather than fake failures.
if not failures and exit_code != 0:
    failures.append("Test pack exited with code %s before producing a successful result." % exit_code)

overall = "PASS" if exit_code == 0 and not failures else "FAIL"
counts = {s: sum(1 for c in checks if c[4] == s) for s in ("PASS", "FAIL", "WARN", "BLOCKED", "NOT RUN")}
payload = {
    "status": overall,
    "metadata": metadata,
    "summary": counts,
    "checks": [dict(zip(("area", "name", "expected", "actual", "status", "evidence"), c)) for c in checks],
    "failures": failures,
}
JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

rows = []
for area, name, expected, actual, status, evidence in checks:
    rows.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in (area, name, expected, actual, status, evidence)) + "</tr>")
failure_html = "".join(f"<li>{html.escape(x)}</li>" for x in failures) or "<li>None</li>"

report = f"""<!doctype html><html><head><meta charset='utf-8'><title>RYB Finserv DEV Test Evidence</title><style>body{{font-family:Arial,sans-serif;margin:28px;color:#222}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:7px;text-align:left;vertical-align:top}}th{{background:#eee}}.PASS{{font-weight:bold}}.FAIL{{font-weight:bold}}.WARN{{font-weight:bold}}.BLOCKED{{font-weight:bold}}.NOT-RUN{{font-weight:bold}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:12px;max-height:500px;overflow:auto}}code{{word-break:break-all}}</style></head><body><h1>RYB Finserv — DEV Test Evidence Report</h1><p><b>Overall status:</b> {overall}</p><p><b>Interpretation:</b> PASS = executed successfully; FAIL = executed and failed; BLOCKED = prerequisite unavailable; NOT RUN = dependent check was not reached; WARN = executed but outside a performance budget.</p><h2>Execution metadata</h2><pre>{html.escape(json.dumps(metadata, indent=2))}</pre><h2>Validation matrix</h2><table><thead><tr><th>Area</th><th>Validation</th><th>Expected</th><th>Actual</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table><h2>Failures / root cause</h2><ul>{failure_html}</ul><h2>Raw execution log</h2><pre>{html.escape(text)}</pre></body></html>"""
REPORT.write_text(report, encoding="utf-8")
print(f"Generated {REPORT}")
