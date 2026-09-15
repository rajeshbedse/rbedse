"""Reusable NSE stock-quote-page browser/navigation primitives.

The NSE stock quote page is a symbol-centric rendered application. This layer
keeps browser mechanics separate from source-specific parsing so additional
stock-level sections can reuse the same navigation and DOM acquisition flow.
"""
from __future__ import annotations

import logging
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
    wait_ms: int = 2500

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()

    @property
    def url(self) -> str:
        return NSE_STOCK_URL.format(symbol=quote(self.symbol))

    def open(self) -> None:
        self.page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)
        self.page.wait_for_timeout(self.wait_ms)

    def navigate(self, section: str) -> None:
        """Open a named stock-page section using visible navigation text."""
        config = NSE_STOCK_SECTIONS.get(section)
        if config is None:
            raise KeyError(f"Unknown NSE stock section: {section}")

        label = config["navigation"]
        # NSE occasionally renders duplicate responsive navigation elements.
        # Prefer an exact visible match and fall back to the first text match.
        locator = self.page.get_by_text(label, exact=True)
        visible = None
        for index in range(locator.count()):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    visible = candidate
                    break
            except Exception:
                continue
        if visible is None:
            visible = locator.first

        try:
            visible.scroll_into_view_if_needed()
            visible.click(timeout=15_000)
        except Exception as exc:
            log.debug("NSE stock section click failed for %s/%s: %s", self.symbol, section, exc)
            # Some NSE releases expose the section as an anchor/hash rather than
            # a clickable tab. The content may already be present in the DOM.

        self.page.wait_for_timeout(800)

    def wait_for_heading(self, section: str, timeout: int = 20_000) -> bool:
        config = NSE_STOCK_SECTIONS[section]
        heading = config["heading"]
        try:
            # Playwright's sync API expects the page-function argument via the
            # keyword `arg`. Passing it positionally is incompatible with the
            # current Playwright signature and caused every stock to consume the
            # full timeout before falling through with a TypeError.
            self.page.wait_for_function(
                """
                heading => (document.body.innerText || '').toLowerCase().includes(heading.toLowerCase())
                """,
                arg=heading,
                timeout=timeout,
            )
            return True
        except PlaywrightTimeoutError:
            return False

    def extract_tables(self, section: str) -> list[list[list[str]]]:
        """Return tables associated with a section, preserving DOM cell text."""
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
                for (let i = 0; i < 5 && root && !root.querySelector('table'); i++) root = root.parentElement;
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
              for (let i = 0; i < 5 && root && !root.querySelector('table'); i++) root = root.parentElement;
              return root ? (root.innerText || '') : (node.parentElement?.innerText || '');
            }
            """,
            heading,
        )
