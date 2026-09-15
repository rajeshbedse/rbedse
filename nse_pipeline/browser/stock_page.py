"""Reusable NSE stock-quote-page browser/navigation primitives.

The NSE stock quote page is a symbol-centric rendered application. This layer
keeps browser mechanics separate from source-specific parsing so additional
stock-level sections can reuse the same navigation and DOM acquisition flow.

Important: this module intentionally uses only the rendered company page. It
does not call NSE JSON/API endpoints. Section data is acquired from the same
visible DOM a user sees in the browser.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

log = logging.getLogger(__name__)

NSE_STOCK_URL = "https://www.nseindia.com/get-quote/equity/{symbol}"

NSE_STOCK_SECTIONS = {
    "promoter_encumbrance": {
        "navigation": "Promoter Encumbrance Details",
        "heading": "Promoter Encumbrance Details",
        "type": "table",
    },
}


@dataclass
class NSEStockPage:
    page: object
    symbol: str
    wait_ms: int = 500

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()

    @property
    def url(self) -> str:
        return NSE_STOCK_URL.format(symbol=quote(self.symbol))

    def open(self) -> None:
        # Browser navigation only. Do not replace this with an NSE API call:
        # the rendered quote page is the reusable source for stock-specific
        # sections that may be added later.
        self.page.goto(self.url, wait_until="domcontentloaded", timeout=15_000)
        self.page.wait_for_timeout(self.wait_ms)

    def navigate(self, section: str) -> bool:
        """Open a named stock-page section using visible navigation text."""
        config = NSE_STOCK_SECTIONS.get(section)
        if config is None:
            raise KeyError(f"Unknown NSE stock section: {section}")

        label = config["navigation"]
        locator = self.page.get_by_text(label, exact=True)
        try:
            count = locator.count()
        except Exception:
            count = 0

        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible():
                    continue
                candidate.scroll_into_view_if_needed(timeout=2_000)
                candidate.click(timeout=3_000)
                self.page.wait_for_timeout(200)
                return True
            except Exception as exc:
                log.debug(
                    "NSE stock section click failed for %s/%s: %s",
                    self.symbol,
                    section,
                    exc,
                )

        return False

    def wait_for_heading(self, section: str, timeout: int = 5_000) -> bool:
        """Wait for a rendered section heading without executing page JS.

        The previous implementation used ``page.wait_for_function``. Apart
        from being unnecessary for this rendered-page workflow, that created
        compatibility problems in the production Playwright invocation. A
        locator poll is both simpler and closer to what a user sees on screen.
        """
        config = NSE_STOCK_SECTIONS[section]
        heading = config["heading"]
        found = self.page.get_by_text(heading, exact=True)
        deadline = time.monotonic() + (timeout / 1000.0)

        while time.monotonic() < deadline:
            try:
                count = found.count()
                for index in range(count):
                    if found.nth(index).is_visible():
                        return True
            except Exception:
                pass
            self.page.wait_for_timeout(100)

        return False

    def extract_tables(self, section: str) -> list[list[list[str]]]:
        """Return rendered HTML tables associated with a section.

        This reads the table cells from the browser DOM after the section is
        opened. It is deliberately not an NSE endpoint/API request.
        """
        config = NSE_STOCK_SECTIONS[section]
        heading = config["heading"]
        return self.page.evaluate(
            """
            heading => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const wanted = norm(heading);
              const elements = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"],button,a,div,span'));
              const matches = elements.filter(el => norm(el.innerText) === wanted);
              const roots = [];
              for (const match of matches) {
                let root = match.closest('section');
                if (!root) root = match.parentElement;
                for (let i = 0; i < 8 && root && !root.querySelector('table'); i++) root = root.parentElement;
                if (root && !roots.includes(root)) roots.push(root);
              }
              const tables = [];
              const add = table => {
                if (!table || tables.includes(table)) return;
                const rows = Array.from(table.querySelectorAll('tr')).map(tr =>
                  Array.from(tr.querySelectorAll('th,td')).map(td => (td.innerText || '').replace(/\\s+/g, ' ').trim())
                ).filter(row => row.length);
                if (rows.length) tables.push(table);
              };
              roots.forEach(root => root.querySelectorAll('table').forEach(add));
              if (!tables.length) document.querySelectorAll('table').forEach(add);
              return tables.map(table => Array.from(table.querySelectorAll('tr')).map(tr =>
                Array.from(tr.querySelectorAll('th,td')).map(td => (td.innerText || '').replace(/\\s+/g, ' ').trim())
              ).filter(row => row.length));
            }
            """,
            heading,
        )

    def extract_text(self, section: str) -> str:
        config = NSE_STOCK_SECTIONS[section]
        heading = config["heading"]
        return self.page.evaluate(
            """
            heading => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const wanted = norm(heading);
              const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"],div,span'));
              const node = nodes.find(el => norm(el.innerText) === wanted);
              if (!node) return document.body.innerText || '';
              let root = node.closest('section') || node.parentElement;
              for (let i = 0; i < 8 && root && !root.querySelector('table'); i++) root = root.parentElement;
              return root ? (root.innerText || '') : (node.parentElement?.innerText || '');
            }
            """,
            heading,
        )
