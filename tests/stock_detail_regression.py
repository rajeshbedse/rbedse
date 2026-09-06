#!/usr/bin/env python3
"""DEV-only regression test for one complete stock-analysis journey.

The test deliberately chooses the first stock returned by the shortlist API so
it exercises a real, current production-shaped row rather than a hard-coded
symbol. It validates the UI against the stock-detail API and verifies that the
full analysis is reachable by scrolling, including promoter transactions.
"""
from __future__ import annotations

import argparse
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_BASE_URL = "https://ryb-finserv-dev.onrender.com"
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def http(session: requests.Session, method: str, url: str, *, expected: int = 200, attempts: int = 3, timeout: float = 20, **kwargs):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            if response.status_code not in RETRYABLE_STATUS or attempt == attempts:
                if response.status_code != expected:
                    fail(f"HTTP {method} {url} expected {expected}, got {response.status_code}")
                return response
        except requests.RequestException as exc:
            last = exc
            if attempt == attempts:
                fail(f"HTTP {method} {url} failed: {type(exc).__name__}: {exc}")
        time.sleep(min(3 * attempt, 6))
    fail(f"HTTP {method} {url} failed: {last}")


def number_from_text(text: str) -> float | None:
    value = re.sub(r"[^0-9.+-]", "", text or "")
    if value in ("", "+", "-"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def assert_num(actual_text: str, expected, label: str, tolerance: float = 0.05) -> None:
    if expected is None:
        if actual_text.strip() not in ("—", "N/A", "No Signal"):
            fail(f"{label}: expected unavailable value, got {actual_text!r}")
        return
    actual = number_from_text(actual_text)
    if actual is None or abs(actual - float(expected)) > tolerance:
        fail(f"{label}: expected {expected}, got {actual_text!r}")


def assert_text(actual: str, expected: str, label: str) -> None:
    if str(actual).strip() != str(expected).strip():
        fail(f"{label}: expected {expected!r}, got {actual!r}")


def display_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(str(value), "%d-%m-%Y").strftime("%d %b %Y")
    except ValueError:
        return str(value)


def signal(row: dict, group: str, label: str) -> dict | None:
    return next((item for item in row.get(group, []) if item.get("label") == label), None)


def dma_from_signal(row: dict, label: str) -> float | None:
    item = signal(row, "tech_signals", label)
    if not item:
        return None
    match = re.search(r"vs\s*₹\s*([\d.]+)", str(item.get("note", "")), re.I)
    return float(match.group(1)) if match else None


def expected_overview(row: dict) -> dict:
    high_debt = row.get("de_ratio") is not None and float(row["de_ratio"]) > 1
    low_hold = row.get("promo_holding") is not None and float(row["promo_holding"]) < 50
    risk_count = int(high_debt) + int(low_hold) + int(bool(row.get("has_pledging")))
    risk = "Low" if risk_count == 0 else "Moderate" if risk_count == 1 else "High"
    dma50 = dma_from_signal(row, "Price > 50 DMA")
    dma200 = dma_from_signal(row, "Price > 200 DMA")
    above_ref = signal(row, "tech_signals", "Price > Promoter Avg")
    if dma50 is not None and dma200 is not None:
        trend = "Positive" if float(row["last_price"]) > dma50 and float(row["last_price"]) > dma200 else "Mixed" if float(row["last_price"]) > dma50 or float(row["last_price"]) > dma200 else "Weak"
    else:
        trend = "Positive" if above_ref and above_ref.get("triggered") else "Neutral"
    triggered = sum(1 for item in row.get("tech_signals", []) if item.get("triggered"))
    overall = "Bullish" if triggered >= 4 else "Positive" if triggered >= 2 else "Neutral"
    return {
        "Fundamentals": {
            "Market Cap": row.get("market_cap_cr"), "P/E": row.get("pe"),
            "Revenue growth": row.get("rev_growth_pct"), "PAT growth": row.get("pat_growth_pct"),
            "ROCE": row.get("roce_pct"), "Debt / Equity": row.get("de_ratio"),
        },
        "Technical": {
            "Trend": trend, "50 DMA": dma50, "200 DMA": dma200,
            "6M return": row.get("six_month_return"), "Vs promoter avg": row.get("cmp_vs_promoter_avg_pct"),
            "Overall": overall,
        },
        "Risk": {
            "Promoter pledge": "Yes" if row.get("has_pledging") else "No",
            "High debt": "Yes" if high_debt else "No",
            "Low promoter holding": "Yes" if low_hold else "No",
            "Governance concern": "No",
            "Price volatility": "High" if abs(float(row.get("price_diff_pct") or 0)) > 10 else "Moderate",
            "Overall risk": risk,
        },
    }


def labelled_map(container, item_selector: str, label_selector: str, value_selector: str) -> dict[str, str]:
    result = {}
    for item in container.locator(item_selector).all():
        label = item.locator(label_selector).inner_text().strip()
        value = item.locator(value_selector).first.inner_text().strip()
        result[label] = value
    return result


def run(base_url: str, expected_commit: str, deploy_timeout: int) -> None:
    base = base_url.rstrip("/")
    session = requests.Session()
    session.headers.update({"User-Agent": "RYB-Finserv-Stock-Detail-Regression/1.0"})

    deadline = time.time() + deploy_timeout
    build = None
    while time.time() < deadline:
        try:
            response = session.get(urljoin(base, "/static/dev-build.json"), timeout=15)
            if response.status_code == 200 and isinstance(response.json(), dict):
                build = response.json()
                if not expected_commit or str(build.get("commit")) == expected_commit:
                    break
        except (requests.RequestException, ValueError):
            pass
        time.sleep(10)
    if not isinstance(build, dict) or (expected_commit and str(build.get("commit")) != expected_commit):
        fail(f"DEV deployment did not expose expected commit {expected_commit}; last={build}")
    print(f"Regression preflight PASS: branch={build.get('branch')} commit={build.get('commit')}")

    home = http(session, "GET", base + "/")
    match = re.search(r'href=[\"\'](/scan/[0-9]{4}-[0-9]{2}-[0-9]{2})[\"\']', home.text)
    if not match:
        fail("Could not find View Latest Scan URL on the home page")
    scan_path = match.group(1)
    scan_date = scan_path.rsplit("/", 1)[-1]
    summary = http(session, "GET", urljoin(base, f"/api/scan/{scan_date}/summary?view=shortlist")).json()
    rows = summary.get("rows") if isinstance(summary, dict) else None
    if not isinstance(rows, list) or not rows:
        fail("Shortlist returned no stock from which to run the regression")
    stock = rows[0]
    symbol = str(stock.get("symbol", "")).strip()
    if not symbol:
        fail("First shortlist row has no symbol")
    detail = http(session, "GET", urljoin(base, f"/api/scan/{scan_date}/stock/{symbol}")).json()
    print(f"Regression stock selected: {symbol}")

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}: {req.failure}") if req.url.startswith(base + "/") else None)
        page.goto(urljoin(base, scan_path), wait_until="domcontentloaded", timeout=30_000)
        page.locator("#scan-loading").wait_for(state="hidden", timeout=15_000)
        button = page.locator(f'[data-stock="{symbol}"]').first
        if button.count() != 1:
            fail(f"Selected stock {symbol} is not rendered exactly once in the scan UI")
        button.click()
        page.locator("#detail-content").wait_for(state="visible", timeout=15_000)
        page.locator("#detail-loading").wait_for(state="hidden", timeout=5_000)
        detail_root = page.locator(".stock-detail")

        # Hero / decision identity.
        assert_text(page.locator("#detail-title").inner_text(), detail["symbol"], "Symbol")
        assert_text(page.locator("#detail-company").inner_text(), detail["company"], "Company")
        assert_num(page.locator("#detail-score").inner_text(), detail["score"], "RYB score")
        assert_text(page.locator("#detail-category").inner_text(), detail["category"], "Setup category")
        if page.locator(".detail-score-block #detail-category").count() != 1:
            fail("Setup category is not in the score block")
        if page.locator(".detail-watermark").count() != 1:
            fail("Watermark is missing")

        # Metadata must be usable, not placeholder text. BSE is cross-checked against
        # the transaction data when a scrip code is present.
        meta = [x.strip() for x in page.locator(".detail-meta span").all_inner_texts()]
        if len(meta) != 4:
            fail(f"Expected four stock metadata chips, got {len(meta)}: {meta}")
        if meta[0] in ("Sector unavailable", ""):
            fail("Sector metadata is missing/unavailable on stock detail")
        if meta[2] in ("BSE: —", "BSE:"):
            fail("BSE metadata is missing on stock detail")
        assert_text(meta[3], f"NSE: {symbol}", "NSE metadata")
        trade_codes = [str(t.get("Scrip Code") or t.get("scripCode") or t.get("ScripCode") or "").strip() for t in detail.get("trades", [])]
        trade_codes = [x for x in trade_codes if x]
        if trade_codes and meta[2] != f"BSE: {trade_codes[0]}":
            fail(f"BSE metadata: expected BSE: {trade_codes[0]!r}, got {meta[2]!r}")

        # Price & market snapshot.
        market = page.locator(".detail-decision-flow .dd-card").nth(0)
        if not market.is_visible():
            fail("Price & Market Snapshot is not visible")
        cells = {c.locator("label").inner_text().strip(): c for c in market.locator(".market-cell").all()}
        for label in ("Current Price (CMP)", "52-week range", "Market Cap"):
            if label not in cells or not cells[label].is_visible():
                fail(f"Market detail is missing: {label}")
        assert_num(cells["Current Price (CMP)"].locator(".market-big").inner_text(), detail["last_price"], "CMP")
        assert_num(cells["Current Price (CMP)"].locator(".market-sub").inner_text(), detail["price_diff_pct"], "CMP vs promoter reference")
        assert_num(cells["Market Cap"].locator(".market-big").inner_text(), detail["market_cap_cr"], "Market cap")
        range_text = cells["52-week range"].inner_text().strip()
        if "52-week data unavailable" in range_text:
            fail("52-week range is unavailable on stock detail")
        if "Low" not in range_text or "High" not in range_text:
            fail(f"52-week range is incomplete: {range_text!r}")
        range_values = cells["52-week range"].locator(".range-values")
        if range_values.count() != 1:
            fail("52-week range values are not rendered")
        range_numbers = [number_from_text(x) for x in range_values.locator("span, b").all_inner_texts()]
        if len(range_numbers) != 3 or any(x is None for x in range_numbers):
            fail(f"52-week range contains invalid numbers: {range_values.inner_text()!r}")
        low, cmp_value, high = range_numbers
        if not (low <= cmp_value <= high):
            fail(f"52-week range is internally inconsistent: low={low}, cmp={cmp_value}, high={high}")
        assert_num(str(cmp_value), detail["last_price"], "52-week range CMP")

        # Promoter activity & entry timing.
        promoter = page.locator(".detail-decision-flow .dd-card").nth(1)
        if not promoter.is_visible():
            fail("Promoter Activity & Timing card is not visible")
        activity = labelled_map(promoter, ".activity", "label", "b")
        assert_num(activity["Promoter holding"], detail["promo_holding"], "Promoter holding")
        assert_num(activity["Total buying value"], detail["value_cr"], "Total buying value")
        assert_num(activity["Transactions"], detail["num_buy_txn"], "Promoter transactions")
        timing = labelled_map(promoter, ".timing", "label", "b")
        assert_text(timing["Signal stage"], detail.get("signal_stage") or detail.get("accumulation_stage") or "No Signal", "Signal stage")
        assert_text(timing["Freshness"], detail.get("freshness") or "—", "Freshness")
        assert_num(timing["Avg buy price"], detail["promoter_avg_price"], "Promoter average buy price")
        assert_num(timing["CMP vs promoter avg"], detail["cmp_vs_promoter_avg_pct"], "CMP vs promoter average")
        assert_text(timing["First buy"], display_date(detail.get("first_buy_date")), "First buy date")
        assert_text(timing["Latest buy"], display_date(detail.get("last_buy_date")), "Latest buy date")
        expected_accum = "—" if detail.get("accumulation_days") is None else f"{detail['accumulation_days']} days"
        assert_text(timing["Accumulation period"], expected_accum, "Accumulation period")
        assert_num(timing["Buys · 30D"], detail.get("buy_txn_30d"), "30-day buy transactions")

        # Overview cards are the visible replacement for the old detail tabs.
        overview = page.locator("#detail-panel .overview-grid")
        if not overview.is_visible():
            fail("Overview summary is not visible")
        cards = overview.locator(".overview-card")
        if cards.count() != 3:
            fail(f"Expected 3 overview cards (Fundamentals/Technical/Risk), got {cards.count()}")
        expected = expected_overview(detail)
        for card_name, expected_rows in expected.items():
            card = overview.locator(".overview-card").filter(has_text=card_name).first
            if card.count() != 1 or not card.is_visible():
                fail(f"Overview card is missing: {card_name}")
            rows_map = labelled_map(card, ".ov-row", "span", "b")
            for label, expected_value in expected_rows.items():
                if label not in rows_map:
                    fail(f"{card_name} card is missing row: {label}")
                if isinstance(expected_value, str):
                    assert_text(rows_map[label], expected_value, f"{card_name} / {label}")
                else:
                    assert_num(rows_map[label], expected_value, f"{card_name} / {label}")

        # Actual scrolling, not just CSS presence: scroll to the bottom and verify
        # the lower part of the dashboard becomes reachable.
        scroll_state = detail_root.evaluate("el => ({scrollHeight:el.scrollHeight, clientHeight:el.clientHeight, overflowY:getComputedStyle(el).overflowY, scrollTop:el.scrollTop})")
        if scroll_state["overflowY"] not in ("auto", "scroll"):
            fail(f"Stock detail is not vertically scrollable: {scroll_state}")
        if scroll_state["scrollHeight"] <= scroll_state["clientHeight"]:
            fail(f"Stock detail has no scrollable overflow: {scroll_state}")
        detail_root.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.wait_for_timeout(100)
        if detail_root.evaluate("el => el.scrollTop") <= 0:
            fail("Stock detail did not actually scroll")
        print(f"Vertical scroll PASS: scrollTop={detail_root.evaluate('el => el.scrollTop'):.0f}")

        # Promoter transactions: every rendered transaction card must correspond to
        # the API row, and the count must match exactly.
        transaction_link = page.locator(".transaction-link")
        if transaction_link.count() != 1 or not transaction_link.is_visible():
            fail("Promoter transaction link is missing")
        transaction_link.click()
        page.locator(".transaction-back-link").wait_for(state="visible", timeout=5_000)
        cards = page.locator(".transaction-card")
        trades = detail.get("trades") or []
        if cards.count() != len(trades):
            fail(f"Transaction count mismatch: API={len(trades)}, UI={cards.count()}")
        for index, trade in enumerate(trades):
            card = cards.nth(index)
            expected_name = str(trade.get("Name of Person") or "Promoter").strip()
            expected_category = str(trade.get("Category of Person") or "").strip()
            expected_date = str(trade.get("Date To") or trade.get("Date From") or "—").strip()
            card_text = card.inner_text()
            if expected_name not in card_text:
                fail(f"Transaction {index + 1}: promoter name missing: {expected_name!r}")
            if expected_category and expected_category not in card_text:
                fail(f"Transaction {index + 1}: category missing: {expected_category!r}")
            if expected_date not in card_text:
                fail(f"Transaction {index + 1}: date missing: {expected_date!r}")
            shares = trade.get("Securities Acquired/Disposed (No.)")
            if shares and str(shares).replace(",", "") not in card_text.replace(",", ""):
                fail(f"Transaction {index + 1}: shares value missing: {shares!r}")
            post = str(trade.get("Securities Held Post (%)") or "—").strip()
            if post != "—" and post not in card_text:
                fail(f"Transaction {index + 1}: post-holding value missing: {post!r}")
            if trade.get("Details URL") and card.locator("a[href]").count() != 1:
                fail(f"Transaction {index + 1}: NSE filing link is missing")
        page.locator(".transaction-back-link").click()
        if not page.locator("#detail-panel .overview-grid").is_visible():
            fail("Back to stock overview did not restore the overview")

        if console_errors or page_errors:
            fail("Browser JavaScript errors: " + " | ".join(console_errors + page_errors)[:3000])
        if failed_requests:
            fail("Browser application request failures: " + " | ".join(failed_requests)[:3000])
        print(f"STOCK DETAIL REGRESSION PASSED: {symbol}")
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("RYB_DEV_URL", DEFAULT_BASE_URL))
    parser.add_argument("--expected-commit", default=os.environ.get("EXPECTED_COMMIT", ""))
    parser.add_argument("--deploy-timeout", type=int, default=600)
    args = parser.parse_args()
    run(args.base_url, args.expected_commit, args.deploy_timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
