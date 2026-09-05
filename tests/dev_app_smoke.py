#!/usr/bin/env python3
"""DEV-only RYB Finserv application/UI regression and performance test pack."""
from __future__ import annotations

import argparse
import os
import time
from urllib.parse import urljoin

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_BASE_URL = "https://ryb-finserv-dev.onrender.com"
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def request_with_retries(session: requests.Session, method: str, url: str, *, attempts: int = 3, timeout: float = 20, **kwargs):
    """Make an HTTP request resilient to transient runner/Render failures."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            if response.status_code not in RETRYABLE_STATUS or attempt == attempts:
                return response
            print(f"HTTP retry {attempt}/{attempts - 1}: {response.status_code} {url}")
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == attempts:
                raise
            print(f"HTTP retry {attempt}/{attempts - 1}: {type(exc).__name__}: {exc}")
        time.sleep(min(3 * attempt, 6))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"HTTP request failed without a response: {url}")


def check_http(session: requests.Session, url: str, expected: int = 200, timeout: float = 20) -> requests.Response:
    start = time.perf_counter()
    try:
        response = request_with_retries(session, "GET", url, timeout=timeout)
    except requests.RequestException as exc:
        fail(f"HTTP request failed after retries: GET {url}: {type(exc).__name__}: {exc}")
    elapsed = time.perf_counter() - start
    print(f"HTTP {response.status_code} {elapsed:.3f}s {url}")
    if response.status_code != expected:
        fail(f"Expected HTTP {expected}, got {response.status_code} for {url}")
    return response


def get_build(session: requests.Session, base_url: str) -> dict:
    response = check_http(session, urljoin(base_url, "/static/dev-build.json"))
    try:
        payload = response.json()
    except ValueError as exc:
        fail(f"dev-build.json is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        fail("dev-build.json did not return a JSON object")
    return payload


def wait_for_deployment(session: requests.Session, base_url: str, expected_commit: str, timeout: int) -> dict:
    """Wait for Render to expose the exact DEV commit, tolerating transient timeouts."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            health = request_with_retries(session, "GET", urljoin(base_url, "/healthz"), attempts=3, timeout=15)
            if health.status_code == 200:
                build = request_with_retries(session, "GET", urljoin(base_url, "/static/dev-build.json"), attempts=3, timeout=15)
                if build.status_code == 200:
                    try:
                        last = build.json()
                    except ValueError:
                        last = None
                    if isinstance(last, dict):
                        commit = str(last.get("commit", ""))
                        print(f"DEV deployment reports branch={last.get('branch')} commit={commit}")
                        if commit == expected_commit:
                            return last
        except (requests.RequestException, ValueError) as exc:
            print(f"Waiting for DEV deployment: {type(exc).__name__}: {exc}")
        time.sleep(10)
    fail(f"DEV deployment did not expose expected commit {expected_commit}; last={last}")


def validate_summary_payload(payload: dict, scan_date: str, expected_view: str = "shortlist") -> list[dict]:
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
    if not isinstance(payload, dict):
        fail("Candidates summary API did not return a JSON object")
    if payload.get("date") != scan_date or payload.get("view") != "candidates":
        fail("Candidates summary API returned an invalid date or view")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        fail("Candidates summary API schema is invalid: rows is not a list")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            fail(f"Candidate row {index} is not an object")
        if not str(row.get("symbol", "")).strip():
            fail(f"Candidate row {index} has an empty symbol")
        if not isinstance(row.get("is_shortlisted"), bool):
            fail(f"Candidate row {index} has invalid is_shortlisted flag")
    return rows


def browser_checks(base_url: str, home_budget: float) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    app_origin = base_url.rstrip("/")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        def record_failed_request(req) -> None:
            if req.url.startswith(app_origin + "/") or req.url == app_origin:
                failed_requests.append(f"{req.method} {req.url}: {req.failure}")

        page.on("requestfailed", record_failed_request)

        start = time.perf_counter()
        try:
            response = page.goto(base_url + "/", wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            fail(f"Browser could not load home page: {type(exc).__name__}: {exc}")
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

        try:
            page.locator("#scan-loading").wait_for(state="hidden", timeout=15_000)
            page.locator("#result-count").wait_for(state="visible", timeout=5_000)
        except PlaywrightTimeoutError:
            fail("Scan results did not finish loading within 15 seconds")

        api_start = time.perf_counter()
        summary_response = page.request.get(urljoin(base_url, f"/api/scan/{scan_date}/summary?view=shortlist"))
        api_time = time.perf_counter() - api_start
        print(f"API shortlist summary: HTTP {summary_response.status} {api_time:.3f}s")
        if api_time > 5:
            print(f"PERF WARNING: shortlist summary API {api_time:.3f}s exceeds 5.000s budget")
        if summary_response.status != 200:
            fail(f"Scan summary API returned HTTP {summary_response.status}")
        shortlist_rows = validate_summary_payload(summary_response.json(), scan_date)
        print(f"Scan shortlist rows: {len(shortlist_rows)}")

        result_count_text = page.locator("#result-count").inner_text().strip()
        if not result_count_text or result_count_text in ("Loading…", "Unable to load"):
            fail(f"Scan result count did not render correctly: {result_count_text!r}")

        if shortlist_rows:
            rendered = page.locator("#stock-cards [data-stock]")
            table_buttons = page.locator("#scan-tbody [data-stock]")
            if rendered.count() == 0 and table_buttons.count() == 0:
                fail("Scan API returned rows, but the UI rendered no stock results")
            first_symbol = str(shortlist_rows[0]["symbol"]).strip()
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
            back = page.locator("#detail-back")
            if back.count() == 0:
                fail("Stock detail Back to results control is missing")
            back.click()
            page.locator("#stock-cards").wait_for(state="visible", timeout=5_000)

        candidates_tab = page.locator('.scan-tab[data-view="candidates"]')
        if candidates_tab.count() == 0:
            fail("All Reviewed tab is missing")
        candidates_tab.click()
        try:
            page.locator("#scan-loading").wait_for(state="hidden", timeout=15_000)
        except PlaywrightTimeoutError:
            fail("All Reviewed view did not finish loading within 15 seconds")

        api_start = time.perf_counter()
        candidates_response = page.request.get(urljoin(base_url, f"/api/scan/{scan_date}/summary?view=candidates"))
        api_time = time.perf_counter() - api_start
        print(f"API candidates summary: HTTP {candidates_response.status} {api_time:.3f}s")
        if api_time > 5:
            print(f"PERF WARNING: candidates summary API {api_time:.3f}s exceeds 5.000s budget")
        if candidates_response.status != 200:
            fail(f"Candidates summary API returned HTTP {candidates_response.status}")
        candidate_rows = validate_candidates_payload(candidates_response.json(), scan_date)
        print(f"All Reviewed rows: {len(candidate_rows)}")
        if len(candidate_rows) < len(shortlist_rows):
            fail("All Reviewed API returned fewer rows than the shortlist")

        if candidate_rows:
            search_symbol = str(candidate_rows[0]["symbol"]).strip()
            search = page.locator("#scan-search")
            search.fill(search_symbol)
            page.wait_for_timeout(200)
            if page.locator("#result-count").inner_text().strip().startswith("0 stock"):
                fail(f"Scan search failed to find {search_symbol}")
            print(f"Scan search OK: {search_symbol}")
            search.fill("")

        if console_errors or page_errors:
            fail("Browser JavaScript errors: " + " | ".join(console_errors + page_errors)[:2000])
        if failed_requests:
            fail("Browser application request failures: " + " | ".join(failed_requests)[:2000])
        print("Browser console/page/request checks: PASS")
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("RYB_DEV_URL", DEFAULT_BASE_URL))
    parser.add_argument("--expected-commit", default=os.environ.get("EXPECTED_COMMIT", ""))
    parser.add_argument("--deploy-timeout", type=int, default=600)
    parser.add_argument("--home-budget", type=float, default=5.0)
    parser.add_argument("--http-attempts", type=int, default=3)
    args = parser.parse_args()

    base = args.base_url.rstrip("/") + "/"
    session = requests.Session()
    session.headers.update({"User-Agent": "RYB-Finserv-DEV-Test/2.0"})

    # Deployment preflight is the only gate. It now tolerates transient
    # GitHub-runner -> Render connection timeouts before declaring the DEV
    # service unavailable.
    if args.expected_commit:
        build = wait_for_deployment(session, base, args.expected_commit, args.deploy_timeout)
    else:
        check_http(session, urljoin(base, "/healthz"), timeout=20)
        build = get_build(session, base)

    branch = build.get("branch")
    if branch not in ("dev-latest", "unknown"):
        fail(f"DEV service reports unexpected branch: {branch}")
    print(f"DEV preflight PASS: branch={branch} commit={build.get('commit')}")

    check_http(session, base, timeout=20)
    print("TEST PACK STARTED")
    browser_checks(base, args.home_budget)
    print("DEV application test pack PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
