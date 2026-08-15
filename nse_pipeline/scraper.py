"""
Phase 1 — NSE Insider Trading Scraper

Navigation (single Playwright browser) → collect session cookies + all filing
URLs → fan out to N parallel threads using requests (HTTP only, no browser)
for detail-page fetching → write CSV.

Parallelism model
-----------------
Playwright's sync API uses greenlets that are permanently bound to the OS thread
that created the sync_playwright() instance.  Passing any Playwright object into
a ThreadPoolExecutor worker causes:
  greenlet.error: Cannot switch to a different thread

Solution: use Playwright only on the main thread for navigation + cookie harvest.
Then pass the harvested cookies as a plain dict to each worker thread, which uses
the stdlib requests library (fully thread-safe) for detail-page fetching.
The XBRL detail pages (nsearchives.nseindia.com) are static server-rendered HTML
that require no JavaScript execution, so requests is sufficient.

Error handling
--------------
404 / connection errors on individual detail pages are recorded in a sidecar
file (failed_urls.txt) inside the run directory.  Error rows are NOT written
into the main CSV — keeping the CSV clean and the failures auditable.
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
    """Parse XBRL detail page HTML → {header: {}, trades: []}."""
    soup   = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    header = {}
    trades = []

    if not tables:
        return {"header": header, "trades": trades}

    # Table 0 — header key/value pairs
    for row in tables[0].find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 2:
            header[cells[0].get_text(strip=True)] = cells[1].get_text(strip=True)

    # Table 1 — trade rows (first 3 rows are header rows)
    if len(tables) > 1:
        for row in list(tables[1].find_all("tr"))[3:]:
            cells = row.find_all("td")
            if len(cells) >= 10 and cells[0].get_text(strip=True):
                def t(i): return cells[i].get_text(strip=True) if i < len(cells) else ""
                trades.append({
                    "srNo":            t(0),
                    "typeInstrument":  t(1),
                    "categoryPerson":  t(3),
                    "namePerson":      t(4),
                    "cinDin":          t(5),
                    "heldPriorNo":     t(6),
                    "heldPriorPct":    t(7),
                    "acquiredNo":      t(8),
                    "acquiredValue":   t(9),
                    "transactionType": t(10),
                    "heldPostNo":      t(11),
                    "heldPostPct":     t(12),
                    "dateFrom":        t(13),
                    "dateTo":          t(14),
                    "modeAcquisition": t(15),
                    "dateIntimation":  t(16),
                    "exchange":        t(17),
                    "notes":           t(18),
                })

    return {"header": header, "trades": trades}


def _worker(
    rows_slice: list[dict],
    cookies: dict,
    worker_id: int,
    counter: list,
    counter_lock: threading.Lock,
    total: int,
    log_every: int,
) -> tuple[list[dict], list[str]]:
    """
    Run inside a thread.  Uses requests (thread-safe) with the NSE session
    cookies harvested by the main-thread Playwright navigation.
    No Playwright objects are used or referenced here.

    Returns (records, failed_urls):
      records    — clean parsed rows to write into the main CSV
      failed_urls — list of "SYMBOL\\tURL\\tERROR" strings for the sidecar file
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.cookies.update(cookies)

    records: list[dict] = []
    failed_urls: list[str] = []

    for row in rows_slice:
        try:
            resp = session.get(row["detailsUrl"], timeout=20)
            resp.raise_for_status()
            details = _parse_detail_html(resp.text)
            header  = details["header"]
            trades  = details["trades"]

            base = {
                "Symbol":                   row["symbol"],
                "Company Name":             row["company"],
                "Regulation":               row["regulation"],
                "Type of Submission":       row["typeSubmission"],
                "Broadcast Date/Time":      row["broadcastDate"],
                "Details URL":              row["detailsUrl"],
                "Scrip Code":               header.get("Scrip Code", ""),
                "NSE Symbol":               header.get("NSE Symbol", ""),
                "MSEI Symbol":              header.get("MSEI Symbol", ""),
                "Name of Signatory":        header.get("Name of the Signatory", ""),
                "Designation of Signatory": header.get("Designation of Signatory", ""),
            }

            if trades:
                for tr in trades:
                    records.append({**base,
                        "Sr. No.":                              tr["srNo"],
                        "Type of Instrument":                   tr["typeInstrument"],
                        "Category of Person":                   tr["categoryPerson"],
                        "Name of Person":                       tr["namePerson"],
                        "CIN/DIN":                              tr["cinDin"],
                        "Securities Held Prior (No.)":          tr["heldPriorNo"],
                        "Securities Held Prior (%)":            tr["heldPriorPct"],
                        "Securities Acquired/Disposed (No.)":   tr["acquiredNo"],
                        "Securities Acquired/Disposed (Value)": tr["acquiredValue"],
                        "Transaction Type":                     tr["transactionType"],
                        "Securities Held Post (No.)":           tr["heldPostNo"],
                        "Securities Held Post (%)":             tr["heldPostPct"],
                        "Date From":                            tr["dateFrom"],
                        "Date To":                              tr["dateTo"],
                        "Mode of Acquisition/Disposal":         tr["modeAcquisition"],
                        "Date of Intimation":                   tr["dateIntimation"],
                        "Exchange":                             tr["exchange"],
                        "Notes":                                tr["notes"],
                    })
            else:
                records.append(base)

        except Exception as exc:
            # Record failure in sidecar list — do NOT pollute the main CSV
            err_str = f"{row['symbol']}\t{row['detailsUrl']}\t{exc}"
            failed_urls.append(err_str)
            log.warning("[W%d] SKIP %s: %s", worker_id, row["symbol"], exc)

        # ── progress tick ──────────────────────────────────────────────────
        with counter_lock:
            counter[0] += 1
            done = counter[0]
        if done % log_every == 0 or done == total:
            pct = done * 100 // total
            log.info("  Fetching … %d/%d filings (%d%%)", done, total, pct)

        time.sleep(SCRAPER_DETAIL_DELAY)

    return records, failed_urls


def run(browser_context, csv_path: Path) -> int:
    """
    Scrape NSE insider trading filings and write to *csv_path*.
    Phase 1 navigation uses the provided *browser_context* (main thread).
    Cookies are harvested from that session and passed to parallel
    requests-based worker threads for detail-page fetching.

    Any filing URLs that return errors are written to *failed_urls.txt*
    in the same directory as *csv_path* — they are not included in the CSV.

    Returns the number of records written.
    """
    log.info("━" * 60)
    log.info("PHASE 1 — Scraping NSE insider trading filings (%s)", NSE_FILING_PERIOD)
    log.info("━" * 60)

    # ── Step A: navigate main listing, harvest cookies ────────────────────────
    # NSE's page fires continuous background XHR polls so "networkidle" never
    # settles.  Use "domcontentloaded" for the initial goto, then gate each
    # subsequent action on the concrete selector that proves the data is ready.
    page = browser_context.new_page()

    log.info("Navigating to NSE Corporate Filings …")
    page.goto(
        "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading#",
        wait_until="domcontentloaded", timeout=60_000,
    )
    # Wait until the tab bar itself is painted before interacting
    page.wait_for_selector('a[data-name="InsiderTrading"]', timeout=60_000)
    page.wait_for_timeout(2000)

    log.info("Clicking Insider Trading …")
    page.click('a[data-name="InsiderTrading"]')
    # Gate on the equity sub-tab appearing, not on networkidle
    page.wait_for_selector('a[href="#Insider_Trading_equity"]', timeout=30_000)
    page.wait_for_timeout(1000)

    log.info("Clicking Equity tab …")
    page.click('a[href="#Insider_Trading_equity"]')
    # Gate on the days-filter strip appearing inside the equity pane
    page.wait_for_selector(
        f'#Insider_Trading_equity ul.dayslisting a[data-val="{NSE_FILING_PERIOD}"]',
        timeout=30_000,
    )
    page.wait_for_timeout(1000)

    log.info("Applying %s filter …", NSE_FILING_PERIOD)
    page.locator(
        f'#Insider_Trading_equity ul.dayslisting a[data-val="{NSE_FILING_PERIOD}"]'
    ).click(force=True)
    # Gate on at least one data row appearing in the equity table
    page.wait_for_selector(
        "#Insider_Trading_equity tbody tr", timeout=30_000,
    )
    page.wait_for_timeout(2000)

    # Harvest cookies from the live Playwright session — these are valid NSE
    # session tokens that will be accepted by nsearchives.nseindia.com too
    raw_cookies = browser_context.cookies()
    cookies = {c["name"]: c["value"] for c in raw_cookies}
    log.info("Harvested %d session cookies", len(cookies))

    rows_data = page.evaluate("""
        () => {
            const pane = document.querySelector('#Insider_Trading_equity');
            return Array.from(pane.querySelectorAll('tbody tr'))
                .map(row => {
                    const c = Array.from(row.querySelectorAll('td'));
                    if (c.length < 4) return null;
                    const a = c[3]?.querySelector('a');
                    return {
                        symbol:         c[0]?.innerText.trim() ?? '',
                        company:        c[1]?.innerText.trim() ?? '',
                        regulation:     c[2]?.innerText.trim() ?? '',
                        detailsUrl:     a ? a.href : '',
                        typeSubmission: c[4]?.innerText.trim() ?? '',
                        broadcastDate:  c[6]?.innerText.trim() ?? '',
                    };
                })
                .filter(r => r && r.symbol && r.detailsUrl);
        }
    """)
    page.close()
    log.info("Found %d filing rows with detail links", len(rows_data))

    # ── Step B: fan out to SCRAPER_WORKERS threads using requests ─────────────
    n       = len(rows_data)
    workers = min(SCRAPER_WORKERS, n)
    slices  = [rows_data[i::workers] for i in range(workers)]

    log.info("Fetching %d detail pages with %d parallel workers …", n, workers)

    # Shared progress counter — workers increment this atomically via the lock.
    # log_every: aim for ~10 progress lines regardless of total count.
    counter   = [0]
    lock      = threading.Lock()
    log_every = max(1, n // 10)

    all_records: list[dict] = []
    all_failed:  list[str]  = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Only plain Python dicts/lists cross the thread boundary — no Playwright objects
        futures = {
            wid: pool.submit(_worker, rows_slice, cookies, wid, counter, lock, n, log_every)
            for wid, rows_slice in enumerate(slices)
        }
        for wid in range(workers):
            records, failed = futures[wid].result()
            all_records.extend(records)
            all_failed.extend(failed)

    # ── Step C: write CSV ─────────────────────────────────────────────────────
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_records)

    # ── Step D: write failed_urls sidecar (if any) ───────────────────────────
    if all_failed:
        failed_path = csv_path.parent / "failed_urls.txt"
        with open(failed_path, "w", encoding="utf-8") as f:
            f.write("Symbol\tURL\tError\n")
            f.write("\n".join(all_failed))
        log.warning("Phase 1: %d failed URLs → %s", len(all_failed), failed_path)
    else:
        log.info("Phase 1: no failed URLs")

    log.info("Phase 1 complete — %d records → %s", len(all_records), csv_path)
    return len(all_records)
