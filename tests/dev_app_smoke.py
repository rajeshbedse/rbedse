#!/usr/bin/env python3
"""DEV-only RYB Finserv application/UI smoke, regression and performance checks."""
from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urljoin

import requests
from playwright.sync_api import sync_playwright

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

        page.wait_for_timeout(500)
        body_text = page.locator("body").inner_text()
        if "Research" not in body_text and "Candidates" not in body_text:
            fail("Scan page does not contain expected research/candidate content")

        scan_date = page.url.rstrip("/").split("/")[-1]
        api = page.request.get(urljoin(base_url, f"/api/scan/{scan_date}/summary"))
        if api.status != 200:
            fail(f"Scan summary API returned HTTP {api.status}")
        payload = api.json()
        rows = payload.get("rows")
        if payload.get("date") != scan_date or not isinstance(rows, list):
            fail("Scan summary API schema is invalid")
        print(f"Scan summary rows: {len(rows)}")

        if rows:
            symbol = str(rows[0].get("symbol", "")).strip()
            if symbol:
                detail = page.request.get(urljoin(base_url, f"/api/scan/{scan_date}/stock/{symbol}"))
                if detail.status != 200:
                    fail(f"Stock detail API returned HTTP {detail.status} for {symbol}")
                detail_payload = detail.json()
                if detail_payload.get("symbol") != symbol:
                    fail(f"Stock detail API returned unexpected symbol for {symbol}")
                print(f"Stock detail API OK: {symbol}")

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
