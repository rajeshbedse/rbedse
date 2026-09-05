"""
Phase 1 — NSE Insider Trading Scraper

Navigation (single Playwright browser) → collect session cookies + all filing
URLs → fan out to N parallel threads using requests (HTTP only, no browser)
for detail-page fetching → write CSV.
"""
import csv
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .config import (
    NSE_FILING_PERIOD, SCRAPER_DETAIL_DELAY, SCRAPER_WORKERS, USER_AGENT
)

log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "Symbol", "Company Name", "Regulation", "Type of Submission",
    "Broadcast Date/Time", "Details URL",
    "Scrip Code", "NSE Symbol", "MSEI Symbol",
    "Name of Signatory", "Designation of Signatory",
    "Sr. No.", "Type of Instrument", "Category of Person",
    "Name of Person", "CIN/DIN",
    "Securities Held Prior (No.)", "Securities Held Prior (%)",
    "Securities Acquired/Disposed (No.)", "Securities Acquired/Disposed (Value)",
    "Transaction Type",
    "Securities Held Post (No.)", "Securities Held Post (%)",
    "Date From", "Date To", "Mode of Acquisition/Disposal",
    "Date of Intimation", "Exchange", "Notes",
]

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _parse_detail_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    header = {}
    trades = []
    if not tables:
        return {"header": header, "trades": trades}
    for row in tables[0].find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 2:
            header[cells[0].get_text(strip=True)] = cells[1].get_text(strip=True)
    if len(tables) > 1:
        for row in list(tables[1].find_all("tr"))[3:]:
            cells = row.find_all("td")
            if len(cells) >= 10 and cells[0].get_text(strip=True):
                def t(i): return cells[i].get_text(strip=True) if i < len(cells) else ""
                trades.append({
                    "srNo": t(0), "typeInstrument": t(1), "categoryPerson": t(3),
                    "namePerson": t(4), "cinDin": t(5), "heldPriorNo": t(6),
                    "heldPriorPct": t(7), "acquiredNo": t(8), "acquiredValue": t(9),
                    "transactionType": t(10), "heldPostNo": t(11), "heldPostPct": t(12),
                    "dateFrom": t(13), "dateTo": t(14), "modeAcquisition": t(15),
                    "dateIntimation": t(16), "exchange": t(17), "notes": t(18),
                })
    return {"header": header, "trades": trades}


def _worker(rows_slice, cookies, worker_id, counter, counter_lock, total, log_every):
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.cookies.update(cookies)
    records, failed_urls = [], []
    for row in rows_slice:
        try:
            resp = session.get(row["detailsUrl"], timeout=20)
            resp.raise_for_status()
            details = _parse_detail_html(resp.text)
            header, trades = details["header"], details["trades"]
            base = {
                "Symbol": row["symbol"], "Company Name": row["company"],
                "Regulation": row["regulation"], "Type of Submission": row["typeSubmission"],
                "Broadcast Date/Time": row["broadcastDate"], "Details URL": row["detailsUrl"],
                "Scrip Code": header.get("Scrip Code", ""), "NSE Symbol": header.get("NSE Symbol", ""),
                "MSEI Symbol": header.get("MSEI Symbol", ""),
                "Name of Signatory": header.get("Name of the Signatory", ""),
                "Designation of Signatory": header.get("Designation of Signatory", ""),
            }
            if trades:
                for tr in trades:
                    records.append({**base, "Sr. No.": tr["srNo"], "Type of Instrument": tr["typeInstrument"],
                        "Category of Person": tr["categoryPerson"], "Name of Person": tr["namePerson"],
                        "CIN/DIN": tr["cinDin"], "Securities Held Prior (No.)": tr["heldPriorNo"],
                        "Securities Held Prior (%)": tr["heldPriorPct"],
                        "Securities Acquired/Disposed (No.)": tr["acquiredNo"],
                        "Securities Acquired/Disposed (Value)": tr["acquiredValue"],
                        "Transaction Type": tr["transactionType"], "Securities Held Post (No.)": tr["heldPostNo"],
                        "Securities Held Post (%)": tr["heldPostPct"], "Date From": tr["dateFrom"],
                        "Date To": tr["dateTo"], "Mode of Acquisition/Disposal": tr["modeAcquisition"],
                        "Date of Intimation": tr["dateIntimation"], "Exchange": tr["exchange"], "Notes": tr["notes"]})
            else:
                records.append(base)
        except Exception as exc:
            failed_urls.append(f"{row['symbol']}\t{row['detailsUrl']}\t{exc}")
            log.warning("[W%d] SKIP %s: %s", worker_id, row["symbol"], exc)
        with counter_lock:
            counter[0] += 1
            done = counter[0]
        if done % log_every == 0 or done == total:
            log.info("  Fetching … %d/%d filings (%d%%)", done, total, done * 100 // total)
        time.sleep(SCRAPER_DETAIL_DELAY)
    return records, failed_urls


def run(browser_context, csv_path: Path) -> int:
    log.info("━" * 60)
    log.info("PHASE 1 — Scraping NSE insider trading filings (%s)", NSE_FILING_PERIOD)
    log.info("━" * 60)
    page = browser_context.new_page()

    # TEMPORARY DIAGNOSTIC: capture the network activity triggered by the
    # Equity/3M filter. This is intentionally observational only.
    network_events = []
    def _on_response(response):
        try:
            url = response.url
            if "nseindia.com" in url:
                network_events.append({
                    "kind": "response",
                    "status": response.status,
                    "method": response.request.method,
                    "resource_type": response.request.resource_type,
                    "url": url,
                    "content_type": response.headers.get("content-type", ""),
                })
        except Exception as exc:
            log.debug("Network diagnostic response handler error: %s", exc)
    page.on("response", _on_response)

    log.info("Navigating to NSE Corporate Filings …")
    page.goto("https://www.nseindia.com/companies-listing/corporate-filings-insider-trading#", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_selector('a[data-name="InsiderTrading"]', timeout=60_000)
    page.wait_for_timeout(2000)
    log.info("Clicking Insider Trading …")
    page.click('a[data-name="InsiderTrading"]')
    page.wait_for_selector('a[href="#Insider_Trading_equity"]', timeout=30_000)
    page.wait_for_timeout(1000)
    log.info("Clicking Equity tab …")
    page.click('a[href="#Insider_Trading_equity"]')
    page.wait_for_selector(f'#Insider_Trading_equity ul.dayslisting a[data-val="{NSE_FILING_PERIOD}"]', timeout=30_000)
    page.wait_for_timeout(1000)

    # Clear navigation noise so the following output focuses on the filter.
    network_events.clear()
    log.info("Applying %s filter …", NSE_FILING_PERIOD)
    page.locator(f'#Insider_Trading_equity ul.dayslisting a[data-val="{NSE_FILING_PERIOD}"]').click(force=True)

    # The table is populated asynchronously. Waiting for tbody/tr alone is
    # insufficient because NSE first renders a spinner row. Wait specifically
    # for a real filing row containing a details link.
    page.wait_for_function(
        """
        () => Array.from(
            document.querySelectorAll('#Insider_Trading_equity tbody tr')
        ).some(row => row.querySelector('a[href]'))
        """,
        timeout=30_000,
    )

    log.info("NSE FILTER NETWORK DIAGNOSTIC: %s", network_events)

    raw_cookies = browser_context.cookies()
    cookies = {c["name"]: c["value"] for c in raw_cookies}
    log.info("Harvested %d session cookies", len(cookies))

    diagnostic = page.evaluate("""
        () => {
            const pane = document.querySelector('#Insider_Trading_equity');
            if (!pane) return {paneFound:false};
            const tables = Array.from(pane.querySelectorAll('table')).map((table, ti) => ({
                index: ti,
                id: table.id || '',
                classes: table.className || '',
                rows: table.querySelectorAll('tbody tr').length,
                allRows: table.querySelectorAll('tr').length,
                links: Array.from(table.querySelectorAll('a')).length,
                sample: Array.from(table.querySelectorAll('tbody tr')).slice(0,3).map(row => ({
                    text: row.innerText,
                    cells: Array.from(row.querySelectorAll('td')).map(td => ({text: td.innerText.trim(), html: td.innerHTML.slice(0,500)}))
                }))
            }));
            return {
                paneFound:true,
                paneText:pane.innerText.slice(0,5000),
                paneHtml:pane.innerHTML.slice(0,12000),
                tables
            };
        }
    """)
    log.info("NSE DOM DIAGNOSTIC: %s", diagnostic)

    rows_data = page.evaluate("""
        () => {
            const pane = document.querySelector('#Insider_Trading_equity');
            return Array.from(pane.querySelectorAll('tbody tr')).map(row => {
                const c = Array.from(row.querySelectorAll('td'));
                if (c.length < 4) return null;
                const a = c[3]?.querySelector('a');
                return {symbol:c[0]?.innerText.trim() ?? '', company:c[1]?.innerText.trim() ?? '', regulation:c[2]?.innerText.trim() ?? '', detailsUrl:a ? a.href : '', typeSubmission:c[4]?.innerText.trim() ?? '', broadcastDate:c[6]?.innerText.trim() ?? ''};
            }).filter(r => r && r.symbol && r.detailsUrl);
        }
    """)
    page.close()
    log.info("Found %d filing rows with detail links", len(rows_data))
    if not rows_data:
        log.info("No filing rows found. Skipping detail-page fetch.")
        return 0
    n, workers = len(rows_data), min(SCRAPER_WORKERS, len(rows_data))
    slices = [rows_data[i::workers] for i in range(workers)]
    log.info("Fetching %d detail pages with %d parallel workers …", n, workers)
    counter, lock, log_every = [0], threading.Lock(), max(1, n // 10)
    all_records, all_failed = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {wid: pool.submit(_worker, s, cookies, wid, counter, lock, n, log_every) for wid, s in enumerate(slices)}
        for wid in range(workers):
            records, failed = futures[wid].result()
            all_records.extend(records); all_failed.extend(failed)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader(); writer.writerows(all_records)
    if all_failed:
        failed_path = csv_path.parent / "failed_urls.txt"
        with open(failed_path, "w", encoding="utf-8") as f:
            f.write("Symbol\tURL\tError\n" + "\n".join(all_failed))
        log.warning("Phase 1: %d failed URLs → %s", len(all_failed), failed_path)
    else:
        log.info("Phase 1: no failed URLs")
    log.info("Phase 1 complete — %d records → %s", len(all_records), csv_path)
    return len(all_records)
