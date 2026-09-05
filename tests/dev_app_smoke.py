#!/usr/bin/env python3
"""DEV-only RYB Finserv application/UI smoke, regression and performance checks."""
from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urljoin

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_BASE_URL = "https://ryb-finserv-dev.onrender.com"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def check_http(session: requests.Session, url: str, expected: int = 200, timeout: float = 20) -> requests.Response:
    start = time.perf_counter()
    response = session.get(url, timeout=timeout)
    elapsed = time.perf_counter() - start
    print(f"HTTP {response.status_code} {elapsed:.3f}s {url}")
    if response.status_code != expected:
        fail(f"Expected HTTP {expected}, got {response.status_code} for {url}")
    return response


def wait_for_deployment(session: requests.Session, base_url: str, expected_commit: str, timeout: int) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            health = session.get(urljoin(base_url, "/healthz"), timeout=15)
            if health.status_code == 200:
                build = session.get(urljoin(base_url, "/static/dev-build.json"), timeout=15)
                if build.status_code == 200:
                    last = build.json()
                    commit = str(last.get("commit", ""))
                    print(f"DEV deployment reports branch={last.get('branch')} commit={commit}")
                    if commit == expected_commit:
                        return last
        except (requests.RequestException, ValueError) as exc:
            print(f"Waiting for DEV deployment: {exc}")
        time.sleep(10)
    fail(f"DEV deployment did not expose expected commit {expected_commit}; last={last}")


def validate_summary_payload(payload: dict, scan_date: str, expected_view: str = "shortlist") -> list[dict]:
    """Validate the public summary contract used by scan.js."""
    if not isinstance(payload, dict):
        fail("Scan summary API did not return a JSON object")
    if payload.get("date") != scan_date:
        fail(f"Scan summary API returned unexpected date: {payload.get('date')}")
    if payload.get("view") != expected_view:
        fail(f"Scan summary API returned unexpected view: {payload.get('view')}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        fail("Scan summary API schema is invalid: rows is not a list")

    required = {
        "symbol", "company", "last_price", "avg_price", "price_diff_pct",
        "promo_holding", "value_cr", "num_buy_txn", "acq_to_dt",
        "score", "category", "category_css", "band", "is_shortlisted",
    }
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            fail(f"Scan summary row {index} is not an object")
        missing = sorted(required - row.keys())
        if missing:
            fail(f"Scan summary row {index} is missing fields: {', '.join(missing)}")
        if not str(row.get("symbol", "")).strip():
            fail(f"Scan summary row {index} has an empty symbol")
        if row.get("is_shortlisted") is not True:
            fail(f"Shortlist row {index} is not marked is_shortlisted=true")
        if row.get("score") is not None and not isinstance(row.get("score"), int):
            fail(f"Scan summary row {index} has a non-integer score")

    return rows


def validate_candidates_payload(payload: dict, scan_date: str) -> list[dict]:
    """Validate the second scan view used by the All Reviewed tab."""
    rows = validate_summary_payload(payload, scan_date, expected_view="candidates")
    for index, row in enumerate(rows):
        if not isinstance(row.get("is_shortlisted"), bool):
            fail(f"Candidate row {index} has invalid is_shortlisted flag")
    return rows


def browser_checks(base_url: str, home_budget: float) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}: {req.failure}"))

        start = time.perf_counter()
        response = page.goto(base_url + "/", wait_until="domcontentloaded", timeout=30_000)
        home_time = time.perf_counter() - start
        if response is None or response.status != 200:
            fail(f"Home page did not return 200: {response.status if response else 'no response'}")
        print(f"UI home load: {home_time:.3f}s")
        if home_time > home_budget:
            print(f"PERF WARNING: home page {home_time:.3f}s exceeds {home_budget:.3f}s budget")

        page.locator("h1").first.wait_for(state="visible", timeout=10_000)
        latest_link = page.get_by_role("link", name="View Latest Scan")
        if latest_link.count() == 0:
            fail("Latest scan CTA is missing")
        latest_link.click()
        page.wait_for_load_state("domcontentloaded")
        if "/scan/" not in page.url:
            fail(f"Latest scan navigation failed: {page.url}")
        print(f"Latest scan URL: {page.url}")

        scan_date = page.url.rstrip("/").split("/")[-1]

        # The scan page is server-rendered as a shell; scan.js loads the actual
        # rows asynchronously. Validate the loading lifecycle instead of looking
        # for static words such as "Research" or "Candidates" in body text.
        try:
            page.locator("#scan-loading").wait_for(state="hidden", timeout=15_000)
            page.locator("#result-count").wait_for(state="visible", timeout=5_000)
        except PlaywrightTimeoutError:
            fail("Scan results did not finish loading within 15 seconds")

        summary_response = page.request.get(
            urljoin(base_url, f"/api/scan/{scan_date}/summary?view=shortlist")
        )
        if summary_response.status != 200:
            fail(f"Scan summary API returned HTTP {summary_response.status}")
        summary_payload = summary_response.json()
        shortlist_rows = validate_summary_payload(summary_payload, scan_date)
        print(f"Scan shortlist rows: {len(shortlist_rows)}")

        # The rendered result count and data-backed result state must agree with
        # the API. This remains valid when the scan is legitimately empty.
        result_count_text = page.locator("#result-count").inner_text().strip()
        if not result_count_text or result_count_text == "Loading…" or result_count_text == "Unable to load":
            fail(f"Scan result count did not render correctly: {result_count_text!r}")

        if shortlist_rows:
            rendered = page.locator("#stock-cards [data-stock]")
            table_buttons = page.locator("#scan-tbody [data-stock]")
            if rendered.count() == 0 and table_buttons.count() == 0:
                fail("Scan API returned rows, but the UI rendered no stock results")

            first_symbol = str(shortlist_rows[0]["symbol"]).strip()
            if not first_symbol:
                fail("First shortlist row has no symbol")

            # Exercise the primary stock-detail interaction, including the
            # asynchronous detail load that is central to the research UI.
            stock_button = page.locator(f'[data-stock="{first_symbol}"]').first
            if stock_button.count() == 0:
                fail(f"First API stock {first_symbol} is not rendered in the UI")
            stock_button.click()
            try:
                page.locator("#detail-content").wait_for(state="visible", timeout=15_000)
            except PlaywrightTimeoutError:
                fail(f"Stock detail did not finish loading for {first_symbol}")
            if page.locator("#detail-title").inner_text().strip() != first_symbol:
                fail(f"Stock detail opened for unexpected symbol; expected {first_symbol}")
            if page.locator("#detail-loading").is_visible():
                fail(f"Stock detail remains stuck on loading for {first_symbol}")
            print(f"Stock detail UI OK: {first_symbol}")

            # Close the detail view and confirm the scan result list is usable.
            back = page.locator("#detail-back")
            if back.count() == 0:
                fail("Stock detail Back to results control is missing")
            back.click()
            page.locator("#stock-cards").wait_for(state="visible", timeout=5_000)

        # Validate the All Reviewed tab and its separate API contract.
        candidates_tab = page.get_by_role("tab", name=lambda name: "All Reviewed" in name)
        if candidates_tab.count() == 0:
            fail("All Reviewed tab is missing")
        candidates_tab.click()
        try:
            page.locator("#scan-loading").wait_for(state="hidden", timeout=15_000)
        except PlaywrightTimeoutError:
            fail("All Reviewed view did not finish loading within 15 seconds")

        candidates_response = page.request.get(
            urljoin(base_url, f"/api/scan/{scan_date}/summary?view=candidates")
        )
        if candidates_response.status != 200:
            fail(f"Candidates summary API returned HTTP {candidates_response.status}")
        candidates_payload = candidates_response.json()
        candidate_rows = validate_candidates_payload(candidates_payload, scan_date)
        print(f"All Reviewed rows: {len(candidate_rows)}")
        if len(candidate_rows) < len(shortlist_rows):
            fail("All Reviewed API returned fewer rows than the shortlist")
        if shortlist_rows and page.locator("#result-count").inner_text().strip() in ("Loading…", "Unable to load"):
            fail("All Reviewed result count did not render")

        # Exercise search without relying on a particular stock symbol. Use the
        # first candidate returned by the API and verify the UI narrows to it.
        if candidate_rows:
            search_symbol = str(candidate_rows[0]["symbol"]).strip()
            search = page.locator("#scan-search")
            search.fill(search_symbol)
            page.wait_for_timeout(200)
            if page.locator("#result-count").inner_text().strip().startswith("0 stock"):
                fail(f"Scan search failed to find {search_symbol}")
            search.fill("")

        # Clear any transient UI state before final browser diagnostics.
        if console_errors or page_errors:
            fail("Browser JavaScript errors: " + " | ".join(console_errors + page_errors)[:2000])
        if failed_requests:
            fail("Browser request failures: " + " | ".join(failed_requests)[:2000])

        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("RYB_DEV_URL", DEFAULT_BASE_URL))
    parser.add_argument("--expected-commit", default=os.environ.get("EXPECTED_COMMIT", ""))
    parser.add_argument("--deploy-timeout", type=int, default=600)
    parser.add_argument("--home-budget", type=float, default=5.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/") + "/"
    session = requests.Session()
    session.headers.update({"User-Agent": "RYB-Finserv-DEV-Test/1.0"})

    check_http(session, urljoin(base, "/healthz"))
    if args.expected_commit:
        wait_for_deployment(session, base, args.expected_commit, args.deploy_timeout)
    else:
        check_http(session, urljoin(base, "/static/dev-build.json"))

    build = session.get(urljoin(base, "/static/dev-build.json"), timeout=20).json()
    if build.get("branch") not in ("dev-latest", "unknown"):
        fail(f"DEV service reports unexpected branch: {build.get('branch')}")

    check_http(session, base)
    browser_checks(base, args.home_budget)
    print("DEV application checks PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
