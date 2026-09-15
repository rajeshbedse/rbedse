"""Reusable NSE stock-quote-page browser/navigation primitives."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

log = logging.getLogger(__name__)

# Public NSE stock-page entry point. NSE may redirect this to its rendered
# symbol-specific quote route; browser navigation follows that redirect.
NSE_STOCK_URL = "https://www.nseindia.com/get-quotes/equity?symbol={symbol}"

NSE_STOCK_SECTIONS = {
    "promoter_encumbrance": {
        "navigation": "Promoter Encumbrance Details",
        "heading": "Promoter Encumbrance Details",
        "type": "table",
        "navigation_timeout_ms": 8_000,
    },
}


@dataclass
class NSEStockPage:
    page: object
    symbol: str
    wait_ms: int = 1_000

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()

    @property
    def url(self) -> str:
        return NSE_STOCK_URL.format(symbol=quote(self.symbol))

    def open(self) -> None:
        # Render the real stock page. Do not replace this with an NSE API call.
        self.page.goto(self.url, wait_until="domcontentloaded", timeout=15_000)
        self.page.wait_for_timeout(self.wait_ms)

    def _navigation_candidates(self, label: str):
        """Return robust rendered-DOM locators for a stock-page option."""
        return (
            self.page.get_by_role("button", name=label, exact=True),
            self.page.get_by_role("link", name=label, exact=True),
            self.page.get_by_text(label, exact=True),
            self.page.get_by_role("button", name=label, exact=False),
            self.page.get_by_role("link", name=label, exact=False),
            self.page.get_by_text(label, exact=False),
            self.page.locator(f"xpath=//*[normalize-space(.)={label!r}]"),
        )

    def navigate(self, section: str) -> bool:
        """Click and select a named stock-page section using rendered UI text."""
        config = NSE_STOCK_SECTIONS.get(section)
        if config is None:
            raise KeyError(f"Unknown NSE stock section: {section}")

        label = config["navigation"]
        deadline = time.monotonic() + int(config.get("navigation_timeout_ms", 8_000)) / 1000

        while time.monotonic() < deadline:
            for locator in self._navigation_candidates(label):
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
                        self.page.wait_for_timeout(300)
                        log.info("NSE stock section selected: %s / %s", self.symbol, label)
                        return True
                    except Exception as exc:
                        log.debug("NSE section click failed for %s/%s: %s", self.symbol, label, exc)
            self.page.wait_for_timeout(150)

        log.warning("NSE stock section navigation unavailable for %s: %s (url=%s)", self.symbol, label, self.page.url)
        return False

    def wait_for_heading(self, section: str, timeout: int = 8_000) -> bool:
        """Wait for the rendered section heading."""
        heading = NSE_STOCK_SECTIONS[section]["heading"]
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            for locator in (
                self.page.get_by_text(heading, exact=True),
                self.page.get_by_text(heading, exact=False),
            ):
                try:
                    for index in range(locator.count()):
                        if locator.nth(index).is_visible():
                            return True
                except Exception:
                    pass
            self.page.wait_for_timeout(100)
        return False

    def extract_tables(self, section: str) -> list[list[list[str]]]:
        """Return rendered HTML tables associated with an opened section."""
        heading = NSE_STOCK_SECTIONS[section]["heading"]
        return self.page.evaluate(
            """
            heading => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const wanted = norm(heading);
              const elements = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading],button,a,div,span'));
              const matches = elements.filter(el => norm(el.innerText) === wanted);
              const roots = [];
              for (const match of matches) {
                let root = match.closest('section') || match.parentElement;
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
        heading = NSE_STOCK_SECTIONS[section]["heading"]
        return self.page.evaluate(
            """
            heading => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const wanted = norm(heading);
              const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading],div,span'));
              const node = nodes.find(el => norm(el.innerText) === wanted);
              if (!node) return document.body.innerText || '';
              let root = node.closest('section') || node.parentElement;
              for (let i = 0; i < 8 && root && !root.querySelector('table'); i++) root = root.parentElement;
              return root ? (root.innerText || '') : (node.parentElement?.innerText || '');
            }
            """,
            heading,
        )
