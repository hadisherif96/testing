"""
Playwright-based extractor for Facebook Ad Library cards rendered by JavaScript.

It navigates to a given Ad Library URL, scrolls to load cards, and extracts
for each visible ad card:
  - status (Active / Inactive)
  - library_id
  - started_running (date string as rendered)
  - total_active_time (e.g., "14 hrs"), if available

The script prints a compact table to stdout. Designed to be resilient to DOM
changes by relying on visible text patterns and minimal selectors instead of
fragile class names.

Usage:
  python scrapper/fb_ad_card_extractor.py "<ad_library_url>" --max-cards 10 --scrolls 30 --headless
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional

from playwright.sync_api import sync_playwright, Page, Locator


LIBRARY_ID_RE = re.compile(r"\bLibrary ID:\s*(\d+)\b", re.I)
STARTED_RE = re.compile(r"Started running on\s+([^\n\-]+)\s*\-\s*Total active time\s*([^\n]+)", re.I)
STARTED_SIMPLE_RE = re.compile(r"Started running on\s+([^\n]+)", re.I)
STATUS_RE = re.compile(r"\b(Active|Inactive)\b", re.I)


@dataclass
class AdCard:
    status: Optional[str]
    library_id: Optional[str]
    started_running: Optional[str]
    total_active_time: Optional[str]

    def to_row(self) -> str:
        return f"{self.library_id or '-':<18}  {self.status or '-':<8}  {self.started_running or '-':<20}  {self.total_active_time or '-'}"


def _extract_from_text(text: str) -> AdCard:
    library_id = None
    started_running = None
    total_active_time = None
    status = None

    m = LIBRARY_ID_RE.search(text)
    if m:
        library_id = m.group(1)

    m = STARTED_RE.search(text)
    if m:
        started_running = m.group(1).strip()
        total_active_time = m.group(2).strip()
    else:
        m2 = STARTED_SIMPLE_RE.search(text)
        if m2:
            started_running = m2.group(1).strip()

    m = STATUS_RE.search(text)
    if m:
        status = m.group(1).capitalize()

    return AdCard(status=status, library_id=library_id, started_running=started_running, total_active_time=total_active_time)


def _visible_card_locators(page: Page) -> List[Locator]:
    # Prefer article containers that already include the Library ID text.
    cards: List[Locator] = []
    article_cards = page.locator("article:has-text('Library ID')")
    if article_cards.count() > 0:
        cards.extend([article_cards.nth(i) for i in range(article_cards.count())])
    else:
        div_cards = page.locator("div:has-text('Library ID')").filter(has_text="Library ID")
        count = min(div_cards.count(), 60)
        cards.extend([div_cards.nth(i) for i in range(count)])
    return cards


def _scroll_to_load(page: Page, iterations: int) -> None:
    for _ in range(max(0, iterations)):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1200)


def extract_cards(url: str, max_cards: int, scrolls: int, headless: bool) -> List[AdCard]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(120000)

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        results: List[AdCard] = []
        seen_ids = set()

        # Progressive scan: on each iteration, re-query visible cards, parse, then scroll.
        for step in range(max(1, scrolls)):
            try:
                cards_locators = _visible_card_locators(page)
                for idx in range(cards_locators.__len__() if hasattr(cards_locators, "__len__") else 0):
                    if max_cards and len(results) >= max_cards:
                        break
                    card = cards_locators[idx]
                    try:
                        card.scroll_into_view_if_needed()
                        page.wait_for_timeout(120)
                        text = card.inner_text()
                        parsed = _extract_from_text(text)
                        if parsed.library_id and parsed.library_id in seen_ids:
                            continue
                        if parsed.library_id:
                            seen_ids.add(parsed.library_id)
                        if parsed.library_id or parsed.started_running or parsed.status:
                            results.append(parsed)
                    except Exception:
                        continue
                if max_cards and len(results) >= max_cards:
                    break
                # Scroll one viewport to trigger virtualization to render adjacent cards
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(350)
            except Exception:
                # Even if a step fails, keep going to the next
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(350)

        browser.close()
        return results


def print_table(rows: List[AdCard]) -> None:
    if not rows:
        print("No ad cards parsed. Try increasing --scrolls or checking the URL/filters.")
        return
    header = f"{'Library ID':<18}  {'Status':<8}  {'Started':<20}  Total active time"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(row.to_row())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract Facebook Ad Library card metadata to console.")
    parser.add_argument("url", help="Facebook Ad Library URL")
    parser.add_argument("--max-cards", type=int, default=30, help="Maximum number of cards to parse")
    parser.add_argument("--scrolls", type=int, default=30, help="Number of scroll iterations to load more ads")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    args = parser.parse_args(argv)

    rows = extract_cards(url=args.url, max_cards=args.max_cards, scrolls=args.scrolls, headless=args.headless)
    print_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())


