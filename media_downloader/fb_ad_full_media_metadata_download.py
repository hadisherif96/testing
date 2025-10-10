"""
fb_ad_full_media_metadata_download.py

Combines card extraction (status, Library ID, dates/durations) with media discovery and
downloading for each ad card on Facebook Ad Library pages.

Outputs:
- All media files named after the Library ID (and suffixed _2, _3 for multiples)
- A single JSON summary file named ads_summary.json

Usage:
  python scrapper/fb_ad_full_media_metadata_download.py "<ad_library_url>" \
    --out-dir ad_media \
    --max-cards 30 \
    --scrolls 30 \
    --headless
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

from playwright.sync_api import sync_playwright, Page, Locator


LIBRARY_ID_RE = re.compile(r"\bLibrary ID:\s*(\d+)\b", re.I)
# Media detection patterns from network interception
MEDIA_TYPES = ("video/", "image/", "application/vnd.apple.mpegurl", "application/x-mpegURL")
MEDIA_EXT_RE = re.compile(r"\.(mp4|mov|m3u8|ts|jpg|jpeg|png|webp|gif)$", re.I)
# e.g., Started running on Oct 8, 2025 · Total active time 14 hrs
STARTED_RE = re.compile(
    r"Started\s+running\s+on\s+([^\n·\-]+?)\s*[·\-]\s*Total\s+active\s+time\s*([^\n]+)",
    re.I,
)
STARTED_SIMPLE_RE = re.compile(r"Started\s+running\s+on\s+([^\n]+)", re.I)
DATE_RANGE_RE = re.compile(r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\s*[-–—]\s*([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", re.I)
DATE_RANGE_ALT_RE = re.compile(r"(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})\s*[-–—]\s*(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})", re.I)
STATUS_RE = re.compile(r"\b(Active|Inactive)\b", re.I)


@dataclass
class AdCard:
    status: Optional[str]
    library_id: Optional[str]
    started_running: Optional[str]
    total_active_time: Optional[str]
    media_urls: List[str]
    media_files: List[str]

    def to_print_row(self) -> str:
        return f"{self.library_id or '-':<18}  {self.status or '-':<8}  {self.started_running or '-':<20}  {self.total_active_time or '-'}"


def _parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    cleaned = (
        date_str.replace("\u00b7", " ")
        .replace("\u2009", " ")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .strip()
    )
    candidates = [cleaned, cleaned.split(" - ")[0].strip()]
    fmts = ["%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"]
    for cand in candidates:
        for fmt in fmts:
            try:
                return datetime.strptime(cand, fmt)
            except Exception:
                continue
    return None


def _calculate_time_difference(start_date_str: str, end_date_str: str, *, inclusive: bool = False) -> Optional[str]:
    try:
        s = datetime.strptime(start_date_str.strip(), "%b %d, %Y")
        e = datetime.strptime(end_date_str.strip(), "%b %d, %Y")
        diff = e - s
        days = diff.days + (1 if inclusive else 0)
        if days < 0:
            days = 0
        if days == 0:
            return "less than 1 day"
        if days == 1:
            return "1 day"
        if days < 7:
            return f"{days} days"
        if days < 30:
            weeks = days // 7
            return f"{weeks} week" if weeks == 1 else f"{weeks} weeks"
        if days < 365:
            months = days // 30
            return f"{months} month" if months == 1 else f"{months} months"
        years = days // 365
        return f"{years} year" if years == 1 else f"{years} years"
    except Exception:
        return None


def _extract_card_text_fields(text: str) -> AdCard:
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

    if status == "Inactive":
        m3 = DATE_RANGE_RE.search(text)
        start_date = end_date = None
        if not m3:
            m3 = DATE_RANGE_ALT_RE.search(text)
            if m3:
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
            started_running = start_date
            calc = _calculate_time_difference(start_date, end_date, inclusive=True)
            if calc:
                total_active_time = calc
    else:
        m_active = STARTED_RE.search(text)
        if m_active:
            raw_date = m_active.group(1).strip()
            parsed_dt = _parse_date(raw_date)
            started_running = parsed_dt.strftime("%d %b %Y") if parsed_dt else raw_date
            dur = m_active.group(2).strip()
            dur = re.sub(r"^total\s+active\s+time\s*[:\-]*\s*", "", dur, flags=re.I)
            total_active_time = dur
        else:
            m2 = STARTED_SIMPLE_RE.search(text)
            if m2:
                started_running = m2.group(1).strip()

    if status == "Active" and started_running and not total_active_time:
        sdt = _parse_date(started_running)
        if sdt:
            hours = int(round((datetime.now() - sdt).total_seconds() / 3600.0))
            if hours < 1:
                hours = 1
            total_active_time = f"{hours} hrs"

    return AdCard(
        status=status,
        library_id=library_id,
        started_running=started_running,
        total_active_time=total_active_time,
        media_urls=[],
        media_files=[],
    )


def _visible_card_locators(page: Page) -> List[Locator]:
    cards: List[Locator] = []
    div_articles = page.locator("div[role='article']")
    if div_articles.count() > 0:
        cards.extend([div_articles.nth(i) for i in range(div_articles.count())])
    else:
        article_cards = page.locator("article").filter(has_text="Library ID")
        if article_cards.count() > 0:
            cards.extend([article_cards.nth(i) for i in range(article_cards.count())])
        else:
            div_cards = page.locator("div:has-text('Library ID')")
            total_div_count = div_cards.count()
            count = min(total_div_count, 500)
            seen_library_ids = set()
            for i in range(count):
                try:
                    loc = div_cards.nth(i)
                    text = loc.inner_text(timeout=500)
                    m = LIBRARY_ID_RE.search(text)
                    if not m:
                        continue
                    lib_id = m.group(1)
                    if lib_id in seen_library_ids:
                        continue
                    container = loc.locator("xpath=ancestor::div[@role='article'][1]")
                    if container.count() == 0:
                        container = loc.locator("xpath=ancestor::article[1]")
                    chosen = container if container.count() > 0 else loc
                    seen_library_ids.add(lib_id)
                    cards.append(chosen)
                except Exception:
                    continue
    return cards


def _normalize_cdn_url(u: str) -> str:
    try:
        # Strip query to collapse size variants of the same asset
        return u.split("?")[0]
    except Exception:
        return u


def _score_sd(w: int, h: int) -> int:
    """Lower is better. Prefer ~640x360 and avoid huge or tiny assets."""
    if w <= 0 or h <= 0:
        return 10**9
    target_w, target_h = 640, 360
    return abs(w - target_w) + abs(h - target_h)


def _extract_media_urls(card: Locator, page: Page) -> List[str]:
    """Return exactly one primary creative URL per card in SD quality.
    Heuristic: If a sufficiently large video exists, pick the single video whose
    dimensions are closest to ~640x360. Otherwise, pick the single largest image
    (ignoring tiny icons < 300x300). Query params are ignored for comparison.
    """
    candidates: List[tuple[str, str, int, int]] = []  # (url, base, w, h)

    # Limit assets to elements whose center lies within the card box
    try:
        card_bb = card.bounding_box() or {}
    except Exception:
        card_bb = {}
    cx0 = float(card_bb.get("x") or 0)
    cy0 = float(card_bb.get("y") or 0)
    cw = float(card_bb.get("width") or 0)
    ch = float(card_bb.get("height") or 0)

    def _is_inside(elem: Locator) -> bool:
        try:
            bb = elem.bounding_box() or {}
            ex = float(bb.get("x") or 0) + float(bb.get("width") or 0) / 2.0
            ey = float(bb.get("y") or 0) + float(bb.get("height") or 0) / 2.0
            return (cx0 <= ex <= cx0 + cw) and (cy0 <= ey <= cy0 + ch)
        except Exception:
            return True

    # Simple video detection - just look for basic video elements
    try:
        vids = card.locator("video")
        for i in range(min(3, vids.count())):
            v = vids.nth(i)
            if not _is_inside(v):
                continue
            
            # Get video source
            src = v.get_attribute("src")
            if src:
                candidates.append((src, _normalize_cdn_url(src), 640, 360))
            
            # Check video sources
            try:
                sources = v.locator("source")
                for j in range(min(3, sources.count())):
                    s_src = sources.nth(j).get_attribute("src")
                    if s_src:
                        candidates.append((s_src, _normalize_cdn_url(s_src), 640, 360))
            except Exception:
                pass
    except Exception:
        pass

    # Images
    try:
        imgs = card.locator("img[src]")
        for i in range(min(30, imgs.count())):
            im = imgs.nth(i)
            if not _is_inside(im):
                continue
            src = im.get_attribute("src")
            if not src or src.startswith("data:"):
                continue
            try:
                dims = im.evaluate("el => ({w: el.naturalWidth || el.clientWidth || 0, h: el.naturalHeight || el.clientHeight || 0})")
            except Exception:
                dims = {"w": 0, "h": 0}
            base = _normalize_cdn_url(src)
            candidates.append((src, base, int(dims.get("w", 0) or 0), int(dims.get("h", 0) or 0)))
    except Exception:
        pass

    # Choose a single best candidate overall, preferring videos if present
    best_url = None
    best_kind = None  # 'video' or 'image'
    best_score = 10**9
    for u, b, w, h in candidates:
        kind = 'video' if u.lower().endswith(('.mp4', '.webm', '.mov', '.m3u8')) else 'image'
        
        # Apply size filter differently for videos vs images
        if kind == 'video':
            # For videos, be more lenient - only reject if obviously tiny
            if w > 0 and h > 0 and w * h < 100 * 100:
                continue
        else:
            # For images, keep the original strict filter
            if w * h < 300 * 300:
                continue
        
        score = _score_sd(w, h)
        # Prefer video over image when scores are similar
        prio = 0 if kind == 'video' else 1
        key = (prio, score)
        if best_url is None or key < ((0 if best_kind == 'video' else 1), best_score):
            best_url = u
            best_kind = kind
            best_score = score

    return [best_url] if best_url else []


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name or "file")


def _guess_ext(url: str, ctype: str) -> str:
    m = re.search(r"\.([a-z0-9]{2,4})(?:[\?#]|$)", url, re.I)
    if m:
        return "." + m.group(1).lower()
    if "mp4" in ctype: return ".mp4"
    if "webm" in ctype: return ".webm"
    if "jpeg" in ctype or "jpg" in ctype: return ".jpg"
    if "png" in ctype: return ".png"
    if "gif" in ctype: return ".gif"
    return ""


def _download_media(context, url: str, base_name: str, idx: int, out_dir: str) -> Optional[str]:
    try:
        # Download via Playwright request
        resp = context.request.get(url)
        if not resp.ok:
            return None
        body = resp.body()
        ctype = (resp.headers.get("content-type") or "").lower()
        
        ext = _guess_ext(url, ctype) or ".bin"
        fname = f"{base_name}{'' if idx == 1 else f'_{idx}'}{ext}"
        out_path = os.path.join(out_dir, _safe_name(fname))
        with open(out_path, "wb") as f:
            f.write(body)
        return out_path
    except Exception:
        return None


def _save_summary(rows: List[AdCard], out_dir: str) -> None:
    try:
        out_path = os.path.join(out_dir, "ads_summary.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _save_ad_cards_json(rows: List[AdCard], out_dir: str) -> None:
    """Save all ad data to ad_cards.json format matching outputs/ad_cards.json."""
    try:
        ad_cards_data = {
            "time_of_scrapping": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "results": []
        }
        
        for card in rows:
            if card.library_id:
                ad_cards_data["results"].append({
                    "status": card.status or "Unknown",
                    "library_id": card.library_id,
                    "started_running": card.started_running or "Unknown",
                    "total_active_time": card.total_active_time or "Unknown"
                })
        
        ad_cards_path = os.path.join(out_dir, "ad_cards.json")
        with open(ad_cards_path, "w", encoding="utf-8") as f:
            json.dump(ad_cards_data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _is_media_response(response) -> bool:
    """Check if a network response is media (video/image) based on URL or content-type."""
    url = response.url
    ctype = (response.headers.get("content-type") or "").lower()
    if MEDIA_EXT_RE.search(url):
        return True
    if any(mt in ctype for mt in MEDIA_TYPES):
        return True
    return False


def _setup_network_interception(page: Page, out_dir: str, video_queue: list) -> None:
    """Save all video responses and queue them for Library ID association.
    video_queue: list of (video_path, timestamp) tuples
    """
    def save_video_response(response):
        try:
            url = response.url
            ctype = (response.headers.get("content-type") or "").lower()
            
            # Only process video responses
            if not ("video" in ctype or any(ext in url.lower() for ext in ['.mp4', '.webm', '.mov', '.m3u8'])):
                return
            
            # Generate temporary filename
            timestamp = datetime.now().strftime("%H%M%S_%f")
            filename = f"temp_video_{timestamp}.mp4"
            out_path = os.path.join(out_dir, filename)
            
            try:
                body = response.body()
                with open(out_path, "wb") as f:
                    f.write(body)
                
                # Add to queue for later Library ID assignment
                video_queue.append((out_path, datetime.now()))
                return out_path
            except Exception as e:
                return None
        except Exception:
            return None
    page.on("response", save_video_response)


def _detect_video_thumbnails_in_card(page: Page, card) -> bool:
    """Detect if a card has a video thumbnail by looking for play button overlays."""
    try:
        # Look for play button icons within the card
        play_buttons = card.locator('[data-testid*="play"], .play-button, [class*="play"], svg[viewBox*="0 0 24 24"]')
        if play_buttons.count() > 0:
            return True
        
        # Look for video elements within the card
        videos = card.locator('video')
        if videos.count() > 0:
            return True
            
        # Look for elements with play button styling
        play_elements = card.locator('[style*="play"], [class*="Play"], [class*="playButton"]')
        if play_elements.count() > 0:
            return True
            
        # Check if the card contains any video-related attributes
        card_html = card.inner_html()
        if any(indicator in card_html.lower() for indicator in ['play', 'video', 'mp4', 'webm']):
            return True
            
        return False
    except Exception:
        return False


def _assign_videos_to_library_ids_precise(out_dir: str, results: List[AdCard], video_queue: list, video_card_mapping: dict) -> None:
    """Assign videos to Library IDs using precise visual detection mapping."""
    if not video_queue:
        return
    
    # Sort video queue by timestamp (earliest first)
    video_queue.sort(key=lambda x: x[1])
    
    # Create a list of Library IDs that have video thumbnails, in processing order
    video_library_ids = []
    for lib_id, (has_video, card_index) in video_card_mapping.items():
        if has_video:
            video_library_ids.append((lib_id, card_index))
    
    # Sort by card index to maintain processing order
    video_library_ids.sort(key=lambda x: x[1])
    video_library_ids = [lib_id for lib_id, _ in video_library_ids]
    
    # Assign videos to cards that have video thumbnails
    video_index = 0
    for lib_id in video_library_ids:
        if video_index < len(video_queue):
            video_path, timestamp = video_queue[video_index]
            
            # Check if the temp video file still exists
            if not os.path.exists(video_path):
                video_index += 1
                continue
            
            # Determine file extension by reading file header
            try:
                with open(video_path, 'rb') as f:
                    header = f.read(12)
                    if header.startswith(b'\x00\x00\x00\x20ftypmp42') or header.startswith(b'\x00\x00\x00\x18ftypmp41'):
                        ext = '.mp4'
                    elif header.startswith(b'RIFF') and b'WEBM' in header:
                        ext = '.webm'
                    elif header.startswith(b'\x00\x00\x00\x14ftypqt'):
                        ext = '.mov'
                    else:
                        ext = '.mp4'  # Default
            except Exception:
                ext = '.mp4'  # Default if can't read header
            
            # Rename video with Library ID
            new_name = f"{lib_id}{ext}"
            new_path = os.path.join(out_dir, new_name)
            
            # Remove existing file if it exists
            if os.path.exists(new_path):
                try:
                    os.remove(new_path)
                except Exception:
                    pass
            
            try:
                os.rename(video_path, new_path)
                
                # Update the card's media_files list
                for card in results:
                    if card.library_id == lib_id:
                        if not card.media_files:
                            card.media_files = []
                        card.media_files.append(new_path)
                        break
                
                video_index += 1
                
            except Exception as e:
                video_index += 1
    
    # Remove any remaining temp videos that weren't assigned
    import glob
    temp_videos = glob.glob(os.path.join(out_dir, "temp_video_*"))
    for temp_video in temp_videos:
        try:
            if os.path.exists(temp_video):
                os.remove(temp_video)
        except Exception:
            pass


def _assign_videos_to_library_ids(out_dir: str, results: List[AdCard], video_queue: list) -> None:
    """Assign videos to Library IDs based on visual detection of video thumbnails."""
    if not video_queue:
        print("[DEBUG] No videos in queue to assign")
        return
    
    print(f"[DEBUG] Assigning {len(video_queue)} videos to Library IDs")
    
    # Sort video queue by timestamp (earliest first)
    video_queue.sort(key=lambda x: x[1])
    
    # Create a list of cards that have video thumbnails (detected during processing)
    cards_with_videos = []
    for card in results:
        if card.library_id and not any('.mp4' in f or '.webm' in f or '.mov' in f for f in card.media_files):
            cards_with_videos.append(card)
    
    print(f"[DEBUG] {len(cards_with_videos)} cards need videos")
    
    # Assign videos to cards in order
    for i, (video_path, timestamp) in enumerate(video_queue):
        if i < len(cards_with_videos):
            card = cards_with_videos[i]
            
            # Determine file extension by reading file header
            with open(video_path, 'rb') as f:
                header = f.read(12)
                if header.startswith(b'\x00\x00\x00\x20ftypmp42') or header.startswith(b'\x00\x00\x00\x18ftypmp41'):
                    ext = '.mp4'
                elif header.startswith(b'RIFF') and b'WEBM' in header:
                    ext = '.webm'
                elif header.startswith(b'\x00\x00\x00\x14ftypqt'):
                    ext = '.mov'
                else:
                    ext = '.mp4'  # Default
            
            # Rename video with Library ID
            new_name = f"{card.library_id}{ext}"
            new_path = os.path.join(out_dir, new_name)
            
            try:
                os.rename(video_path, new_path)
                print(f"[Assign] Video assigned to {card.library_id}: {os.path.basename(video_path)} -> {new_name}")
                
                # Update the card's media_files list
                if not card.media_files:
                    card.media_files = []
                card.media_files.append(new_path)
                
            except Exception as e:
                print(f"[Assign] Failed to rename video for {card.library_id}: {e}")
    
    # Remove any remaining temp videos
    import glob
    temp_videos = glob.glob(os.path.join(out_dir, "temp_video_*"))
    for temp_video in temp_videos:
        try:
            os.remove(temp_video)
            print(f"[Cleanup] Removed unused temp video: {os.path.basename(temp_video)}")
        except Exception:
            pass


def extract_and_download(url: str, out_dir: str, max_cards: int, scrolls: int, headless: bool) -> List[AdCard]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(120000)

        os.makedirs(out_dir, exist_ok=True)

        # Set up network interception to save all videos and queue them
        video_queue = []  # List of (video_path, timestamp) tuples
        video_card_mapping = {}  # Library ID -> (has_video_thumbnail, card_index)
        _setup_network_interception(page, out_dir, video_queue)

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        # Zoom out to 67% so multiple cards are fully visible and in predictable layout
        try:
            page.evaluate("document.documentElement.style.zoom='0.67'")
        except Exception:
            pass

        results: List[AdCard] = []  # Only cards with a saved media file
        seen_ids = set()

        for step in range(max(1, scrolls)):
            try:
                cards_locators = _visible_card_locators(page)
                total_cards = len(cards_locators)

                for idx in range(total_cards):
                    if max_cards and len(results) >= max_cards:
                        break
                    card = cards_locators[idx]
                    try:
                        # Ensure card and its lazy media are in view before reading
                        try:
                            card.scroll_into_view_if_needed()
                            # Center the card in viewport to stabilize lazy loads
                            bb = card.bounding_box()
                            if bb and isinstance(bb, dict) and bb.get("y") is not None:
                                page.evaluate("window.scrollTo(0, Math.max(0, arguments[0] - window.innerHeight * 0.15))", bb.get("y"))
                            page.wait_for_timeout(200)
                        except Exception:
                            page.wait_for_timeout(50)
                        # Small extra wait to allow images/video sources to resolve
                        page.wait_for_timeout(150)
                        text = card.inner_text()
                        parsed = _extract_card_text_fields(text)
                        if parsed.library_id and parsed.library_id in seen_ids:
                            continue
                        # Detect if this card has a video thumbnail
                        has_video_thumbnail = _detect_video_thumbnails_in_card(page, card)
                        if parsed.library_id:
                            video_card_mapping[parsed.library_id] = (has_video_thumbnail, len(results))
                        
                        # Collect media and download
                        media_urls = _extract_media_urls(card, page)
                        parsed.media_urls = media_urls or []
                        parsed.media_files = []
                        
                        # Download images with Library ID names
                        if parsed.library_id and media_urls:
                            saved = []
                            for n, murl in enumerate(media_urls, start=1):
                                sp = _download_media(context, murl, parsed.library_id, n, out_dir)
                                if sp:
                                    saved.append(sp)
                            parsed.media_files = saved

                        # Only count/record cards that actually saved at least one media file
                        if parsed.library_id and parsed.media_files:
                            seen_ids.add(parsed.library_id)
                        results.append(parsed)
                    except Exception:
                        continue

                if max_cards and len(results) >= max_cards:
                    break

                page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
                page.wait_for_timeout(1500)
                page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
                page.wait_for_timeout(1500)
            except Exception:
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(2000)

        # Wait a moment to let any in-flight network responses finish saving
        page.wait_for_timeout(5000)
        
        # Assign saved videos to Library IDs using precise mapping
        _assign_videos_to_library_ids_precise(out_dir, results, video_queue, video_card_mapping)

        browser.close()
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Download ad media and metadata from Facebook Ad Library")
    parser.add_argument("url", help="Facebook Ad Library URL")
    parser.add_argument("--out-dir", default="ad_media", help="Output directory for media and per-ad JSON files")
    parser.add_argument("--max-cards", type=int, default=30, help="Maximum number of cards to process")
    parser.add_argument("--scrolls", type=int, default=30, help="Number of scroll iterations to load more ads")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    args = parser.parse_args()
    rows = extract_and_download(url=args.url, out_dir=args.out_dir, max_cards=args.max_cards, scrolls=args.scrolls, headless=args.headless)

    # Save summary JSON
    _save_summary(rows, args.out_dir)
    
    # Save ad_cards.json format
    _save_ad_cards_json(rows, args.out_dir)

    # Print a quick table and time of scrapping
    header = f"{'Library ID':<18}  {'Status':<8}  {'Started':<20}  Total active time"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(r.to_print_row())
    print(f"\nSaved {len(rows)} ads to: {os.path.abspath(args.out_dir)}")
    print(f"Time of Scrapping: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


