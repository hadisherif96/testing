# fb_ad_full_media_downloader.py
# Captures ALL video/image/media responses (including segments)
# pip install playwright
# playwright install chromium

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright

SAVE_DIR = Path("downloads_full")
SAVE_DIR.mkdir(exist_ok=True)

MEDIA_TYPES = ("video/", "image/", "application/vnd.apple.mpegurl", "application/x-mpegURL")
MEDIA_EXT_RE = re.compile(r"\.(mp4|mov|m3u8|ts|jpg|jpeg|png|webp|gif)$", re.I)

def safe_name(url):
    p = urlparse(url).path
    name = os.path.basename(unquote(p)) or "file"
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name

def is_media(response):
    url = response.url
    ctype = (response.headers.get("content-type") or "").lower()
    if MEDIA_EXT_RE.search(url):
        return True
    if any(mt in ctype for mt in MEDIA_TYPES):
        return True
    return False

def save_response_immediate(response):
    try:
        url = response.url
        filename = safe_name(url)
        # Add extension guess if missing
        if not os.path.splitext(filename)[1]:
            ctype = (response.headers.get("content-type") or "").lower()
            if "mpegurl" in ctype:
                filename += ".m3u8"
            elif "video" in ctype:
                filename += ".mp4"
            elif "image" in ctype:
                filename += ".jpg"

        out_path = SAVE_DIR / filename

        # Read body as soon as possible
        body = response.body()
        with open(out_path, "wb") as f:
            f.write(body)
        print(f"[✓] Saved {url} -> {out_path}")
    except Exception as e:
        print(f"[!] Failed to save {response.url[:80]}... {e}")

def main(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0 Safari/537.36"
        )
        page = context.new_page()

        page.on("response", lambda r: is_media(r) and save_response_immediate(r))

        print(f"Navigating to: {url}")
        page.goto(url, wait_until="domcontentloaded")

        # Scroll slowly to load ads progressively
        for _ in range(10):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        # Keep the browser alive to let background chunks complete
        print("Waiting 15 seconds for final downloads...")
        page.wait_for_timeout(15000)

        browser.close()
        print("\n✅ Done. Check:", SAVE_DIR.resolve())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fb_ad_full_media_downloader.py <facebook_ad_library_url>")
        sys.exit(1)
    main(sys.argv[1])
