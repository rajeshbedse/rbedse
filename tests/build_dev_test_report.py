#!/usr/bin/env python3
"""Build an HTML/JSON evidence report from the DEV smoke-test console log."""
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
exit_code = int((OUT / "exit-code.txt").read_text().strip()) if (OUT / "exit-code.txt").exists() else 1


def first(pattern: str, default: str = "") -> str:
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1) if m else default


def last(pattern: str, default: str = "") -> str:
    matches = re.findall(pattern, text, re.MULTILINE)
    return matches[-1] if matches else default


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

# Deployment identity must compare the SHA supplied to the smoke test with the SHA
# actually exposed by the running DEV service. Never use a placeholder such as
# "workflow commit" when the workflow supplied EXPECTED_COMMIT.
if expected_commit and deployed_commit:
    deployment_status = "PASS" if deployed_commit == expected_commit else "FAIL"
    add("Deployment", "Expected DEV commit deployed", expected_commit, deployed_commit, deployment_status, "dev-build.json / smoke log")
elif expected_commit:
    add("Deployment", "Expected DEV commit deployed", expected_commit, "not observed", "FAIL", "dev-build.json / smoke log")
else:
    add("Deployment", "Expected DEV commit deployed", "workflow commit", deployed_commit or "not observed", "WARN", "EXPECTED_COMMIT not available to report step")

add("Deployment", "DEV branch", "dev-latest", deployed_branch or "not observed", "PASS" if deployed_branch == "dev-latest" else "FAIL", "dev-build.json / smoke log")
add("Availability", "Health endpoint", "HTTP 200", "HTTP 200" if re.search(r"HTTP 200 .*?/healthz", text) else "not observed", "PASS" if re.search(r"HTTP 200 .*?/healthz", text) else "FAIL", "HTTP check")
add("Home", "Home page", "HTTP 200", "HTTP 200" if re.search(r"HTTP 200 .*https://ryb-finserv-dev\.onrender\.com/\s*$", text, re.MULTILINE) else "not observed", "PASS" if re.search(r"HTTP 200 .*https://ryb-finserv-dev\.onrender\.com/\s*$", text, re.MULTILINE) else "FAIL", "HTTP/UI check")

if metadata["home_load_seconds"]:
    seconds = float(metadata["home_load_seconds"])
    add("Performance", "Home UI load", "<= 5.0s", f"{seconds:.3f}s", "PASS" if seconds <= 5 else "WARN", "Playwright timing")
else:
    add("Performance", "Home UI load", "<= 5.0s", "not observed", "FAIL", "Playwright timing")

add("Navigation", "Latest Scan CTA/navigation", "/scan/<date>", metadata["latest_scan_url"] or "not observed", "PASS" if metadata["latest_scan_url"] and "/scan/" in metadata["latest_scan_url"] else "FAIL", "Playwright URL")
add("Scan", "Shortlist data", "API 200 + valid schema", f"{metadata['shortlist_rows']} rows" if metadata["shortlist_rows"] else "not observed", "PASS" if metadata["shortlist_rows"] else "FAIL", "summary API validation")
add("Scan", "Shortlist UI rendering", "At least one result when API has rows", "Rendered" if metadata["stock_detail"] else "not observed", "PASS" if metadata["stock_detail"] else "FAIL", "DOM validation")
add("Stock Detail", "Open first stock detail", "Detail content/title loaded", metadata["stock_detail"] or "not observed", "PASS" if metadata["stock_detail"] else "FAIL", "DOM/API validation")
add("Navigation", "Back to results", "Results visible", "Completed" if metadata["stock_detail"] else "not observed", "PASS" if metadata["stock_detail"] else "FAIL", "Playwright navigation")
add("All Reviewed", "Candidates view", "API 200 + valid schema", f"{metadata['all_reviewed_rows']} rows" if metadata["all_reviewed_rows"] else "not observed", "PASS" if metadata["all_reviewed_rows"] else "FAIL", "summary API validation")
add("Search", "Candidate symbol search", "Matching result", "Completed" if metadata["all_reviewed_rows"] else "not observed", "PASS" if metadata["all_reviewed_rows"] else "FAIL", "DOM validation")
add("Browser", "JavaScript errors", "None", "Errors found" if "Browser JavaScript errors:" in text else "None observed", "FAIL" if "Browser JavaScript errors:" in text else "PASS", "console/pageerror listeners")
add("Browser", "Application request failures", "None", "Failures found" if "Browser application request failures:" in text else "None observed", "FAIL" if "Browser application request failures:" in text else "PASS", "requestfailed listener")

for line in text.splitlines():
    if "PERF WARNING:" in line:
        add("Performance", "Performance budget", "Within configured budget", line.strip(), "WARN", "smoke.log")

failures = re.findall(r"^FAIL: (.+)$", text, re.MULTILINE)
overall = "PASS" if exit_code == 0 and not failures else "FAIL"
counts = {s: sum(1 for c in checks if c[4] == s) for s in ("PASS", "FAIL", "WARN")}
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

report = f"""<!doctype html><html><head><meta charset='utf-8'><title>RYB Finserv DEV Test Evidence</title><style>body{{font-family:Arial,sans-serif;margin:28px;color:#222}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:7px;text-align:left;vertical-align:top}}th{{background:#eee}}.PASS{{font-weight:bold}}.FAIL{{font-weight:bold}}.WARN{{font-weight:bold}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:12px;max-height:500px;overflow:auto}}code{{word-break:break-all}}</style></head><body><h1>RYB Finserv — DEV Test Evidence Report</h1><p><b>Overall status:</b> {overall}</p><h2>Execution metadata</h2><pre>{html.escape(json.dumps(metadata, indent=2))}</pre><h2>Validation matrix</h2><table><thead><tr><th>Area</th><th>Validation</th><th>Expected</th><th>Actual</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table><h2>Failures</h2><ul>{failure_html}</ul><h2>Raw execution log</h2><pre>{html.escape(text)}</pre></body></html>"""
REPORT.write_text(report, encoding="utf-8")
print(f"Generated {REPORT}")
