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
import json
from datetime import datetime
from typing import Iterable, List, Optional

from playwright.sync_api import sync_playwright, Page, Locator


LIBRARY_ID_RE = re.compile(r"\bLibrary ID:\s*(\d+)\b", re.I)
# Matches lines like: "Started running on Oct 8, 2025 · Total active time 14 hrs"
STARTED_RE = re.compile(
    r"Started\s+running\s+on\s+([^\n·\-]+?)\s*[·\-]\s*Total\s+active\s+time\s*([^\n]+)",
    re.I,
)
# Fallback when only the start date is present
STARTED_SIMPLE_RE = re.compile(r"Started\s+running\s+on\s+([^\n]+)", re.I)
# Match date range for inactive ads: "Sep 30, 2025 - Oct 1, 2025" or "Sep 30, 2025 – Oct 1, 2025"
DATE_RANGE_RE = re.compile(r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\s*[-–—]\s*([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", re.I)
# Alternative date range like "30 Sep 2025 - 1 Oct 2025"
DATE_RANGE_ALT_RE = re.compile(r"(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})\s*[-–—]\s*(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})", re.I)
STATUS_RE = re.compile(r"\b(Active|Inactive)\b", re.I)


@dataclass
class AdCard:
    status: Optional[str]
    library_id: Optional[str]
    started_running: Optional[str]
    total_active_time: Optional[str]

    def to_row(self) -> str:
        return f"{self.library_id or '-':<18}  {self.status or '-':<8}  {self.started_running or '-':<20}  {self.total_active_time or '-'}"


def _calculate_time_difference(start_date_str: str, end_date_str: str, *, inclusive: bool = False) -> str:
    """Calculate time difference between two dates and return formatted string.
    If inclusive=True, counts both the start and end dates (e.g., Sep 30 - Oct 1 → 2 days).
    """
    try:
        # Parse dates like "Sep 30, 2025" or "Oct 1, 2025"
        start_date = datetime.strptime(start_date_str.strip(), "%b %d, %Y")
        end_date = datetime.strptime(end_date_str.strip(), "%b %d, %Y")
        
        # Calculate difference
        diff = end_date - start_date
        days = diff.days + (1 if inclusive else 0)
        if days < 0:
            days = 0
        
        if days == 0:
            return "less than 1 day"
        elif days == 1:
            return "1 day"
        elif days < 7:
            return f"{days} days"
        elif days < 30:
            weeks = days // 7
            return f"{weeks} week" if weeks == 1 else f"{weeks} weeks"
        elif days < 365:
            months = days // 30
            return f"{months} month" if months == 1 else f"{months} months"
        else:
            years = days // 365
            return f"{years} year" if years == 1 else f"{years} years"
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    """Best-effort parse for rendered dates like 'Oct 6, 2025' or '6 Oct 2025'."""
    if not date_str:
        return None
    cleaned = (
        date_str.replace("\u00b7", " ")  # remove middle dot if present
        .replace("\u2009", " ")          # thin space
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .strip()
    )
    candidates = [cleaned, cleaned.split(" - ")[0].strip()]
    fmts = [
        "%b %d, %Y",  # Oct 6, 2025
        "%B %d, %Y",  # October 6, 2025
        "%d %b %Y",   # 6 Oct 2025
        "%d %B %Y",   # 6 October 2025
    ]
    for cand in candidates:
        for fmt in fmts:
            try:
                return datetime.strptime(cand, fmt)
            except Exception:
                continue
    return None


def _extract_from_text(text: str) -> AdCard:
    library_id = None
    started_running = None
    total_active_time = None
    status = None

    m = LIBRARY_ID_RE.search(text)
    if m:
        library_id = m.group(1)

    m = STATUS_RE.search(text)
    if m:
        status = m.group(1).capitalize()

    # If explicitly Inactive, prefer parsing the date range string and compute inclusive duration
    if status == "Inactive":
        # First try American month-name format
        m3 = DATE_RANGE_RE.search(text)
        if not m3:
            # Then try day-first format
            m3 = DATE_RANGE_ALT_RE.search(text)
            if m3:
                # Normalize to %b %d, %Y for our calculator
                try:
                    s = datetime.strptime(m3.group(1).strip(), "%d %b %Y").strftime("%b %d, %Y")
                    e = datetime.strptime(m3.group(2).strip(), "%d %b %Y").strftime("%b %d, %Y")
                    start_date, end_date = s, e
                except Exception:
                    start_date = end_date = None
        else:
            start_date = m3.group(1).strip()
            end_date = m3.group(2).strip()

        if start_date and end_date:
            started_running = started_running or start_date
            calculated_time = _calculate_time_difference(start_date, end_date, inclusive=True)
            if calculated_time:
                total_active_time = calculated_time
    else:
        # Active or unknown: check for "Started running on" formats
        m_active = STARTED_RE.search(text)
        if m_active:
            raw_date = m_active.group(1).strip()
            # Normalize to '8 Oct 2025' for output
            parsed_dt = _parse_date(raw_date)
            started_running = parsed_dt.strftime("%d %b %Y") if parsed_dt else raw_date
            # Keep only the duration fragment (e.g., '14 hrs')
            total_active_time = m_active.group(2).strip()
            total_active_time = re.sub(r"^total\s+active\s+time\s*[:\-]*\s*", "", total_active_time, flags=re.I)
        else:
            m2 = STARTED_SIMPLE_RE.search(text)
            if m2:
                started_running = m2.group(1).strip()

    # For active ads without a provided total active time, approximate to nearest hour since start date
    if status == "Active" and started_running and not total_active_time:
        start_dt = _parse_date(started_running)
        if start_dt:
            now_dt = datetime.now()
            hours = int(round((now_dt - start_dt).total_seconds() / 3600.0))
            if hours < 1:
                hours = 1
            total_active_time = f"{hours} hrs"

    return AdCard(status=status, library_id=library_id, started_running=started_running, total_active_time=total_active_time)


def _visible_card_locators(page: Page) -> List[Locator]:
    """Find unique ad card containers, avoiding duplicates from nested elements."""
    cards: List[Locator] = []
    
    # Try multiple selectors to find ad cards
    # Facebook's structure can vary, so we try different approaches
    
    # Approach 1: Look for divs with role='article' (Facebook feed items)
    div_articles = page.locator("div[role='article']")
    article_count = div_articles.count()
    
    if article_count > 0:
        # Get all role=article divs
        cards.extend([div_articles.nth(i) for i in range(article_count)])
    else:
        # Approach 2: Standard article tags
        article_cards = page.locator("article").filter(has_text="Library ID")
        if article_cards.count() > 0:
            cards.extend([article_cards.nth(i) for i in range(article_cards.count())])
        else:
            # Approach 3: Fallback to divs containing Library ID
            # Deduplicate by Library ID to avoid nested elements
            div_cards = page.locator("div:has-text('Library ID')")
            total_div_count = div_cards.count()
            count = min(total_div_count, 500)  # Increased limit to catch more cards
            seen_library_ids = set()
            for i in range(count):
                try:
                    loc = div_cards.nth(i)
                    text = loc.inner_text(timeout=500)
                    # Extract the Library ID from this element
                    m = LIBRARY_ID_RE.search(text)
                    if not m:
                        continue
                    lib_id = m.group(1)
                    if lib_id in seen_library_ids:
                        continue

                    # Promote to nearest card container so we capture header/date text as well
                    container = loc.locator("xpath=ancestor::div[@role='article'][1]")
                    if container.count() == 0:
                        container = loc.locator("xpath=ancestor::article[1]")
                    # Fallback to the original element if no container found
                    chosen = container if container.count() > 0 else loc

                    seen_library_ids.add(lib_id)
                    cards.append(chosen)
                except:
                    continue
                    
    return cards


def _scroll_to_load(page: Page, iterations: int) -> None:
    """Scroll slowly to load ads progressively."""
    for _ in range(max(0, iterations)):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(2000)


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
        # Note: Facebook uses virtual scrolling, so we always process all visible cards
        # and rely on seen_ids to skip duplicates.
        for step in range(max(1, scrolls)):
            try:
                cards_locators = _visible_card_locators(page)
                total_cards = len(cards_locators)
                cards_added_this_scroll = 0
                
                # Quick preview: what IDs are currently visible?
                visible_ids = set()
                for idx in range(min(total_cards, 100)):
                    try:
                        text = cards_locators[idx].inner_text(timeout=500)
                        m = LIBRARY_ID_RE.search(text)
                        if m:
                            visible_ids.add(m.group(1))
                    except:
                        continue
                
                new_ids = visible_ids - seen_ids
                if new_ids or step == 0:
                    print(f"[Scroll {step+1}/{scrolls}] {len(new_ids)} new IDs detected (total collected: {len(results)})")
                
                # Process all visible cards, relying on seen_ids for deduplication
                for idx in range(total_cards):
                    if max_cards and len(results) >= max_cards:
                        print(f"  ℹ Reached max_cards limit ({max_cards})")
                        break
                    card = cards_locators[idx]
                    try:
                        # Just wait for the card to be stable, don't scroll to it
                        page.wait_for_timeout(50)
                        text = card.inner_text()
                        parsed = _extract_from_text(text)
                        if parsed.library_id and parsed.library_id in seen_ids:
                            # Silently skip duplicates (too verbose otherwise)
                            continue
                        if parsed.library_id:
                            seen_ids.add(parsed.library_id)
                            cards_added_this_scroll += 1
                        if parsed.library_id or parsed.started_running or parsed.status:
                            results.append(parsed)
                    except Exception as e:
                        # Silently continue on extraction errors
                        continue
                
                if cards_added_this_scroll > 0:
                    print(f"  ✓ Added {cards_added_this_scroll} new cards (total: {len(results)})")
                
                if max_cards and len(results) >= max_cards:
                    break
                
                # Scroll more slowly in smaller increments to catch cards as they load
                # Do 2 half-screen scrolls instead of 1 full screen
                page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
                page.wait_for_timeout(1500)
                page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
                page.wait_for_timeout(1500)
            except Exception:
                # Even if a step fails, keep going to the next
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(2000)

        browser.close()
        print(f"\n📊 Extraction complete: Found {len(results)} unique cards (requested {max_cards})")
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
    # Footer with time of scrapping
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\nTime of Scrapping: {now_str}")
    except Exception:
        pass


def save_json(rows: List[AdCard], out_path: str) -> None:
    """Save extracted rows to a JSON file with a time_of_scrapping footer."""
    payload = {
        "time_of_scrapping": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "results": [asdict(r) for r in rows],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract Facebook Ad Library card metadata to console.")
    parser.add_argument("url", help="Facebook Ad Library URL")
    parser.add_argument("--max-cards", type=int, default=30, help="Maximum number of cards to parse")
    parser.add_argument("--scrolls", type=int, default=30, help="Number of scroll iterations to load more ads")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--json-out", type=str, default=None, help="Optional path to write results as JSON")

    args = parser.parse_args(argv)

    rows = extract_cards(url=args.url, max_cards=args.max_cards, scrolls=args.scrolls, headless=args.headless)
    print_table(rows)
    if args.json_out:
        try:
            save_json(rows, args.json_out)
            print(f"Saved JSON to {args.json_out}")
        except Exception as e:
            print(f"Failed to save JSON: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


