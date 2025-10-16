"""
shopify_detection_plus_scraper.py

Intelligent product scraper with automatic Shopify detection and fallback.

Features:
- Automatically detects if a website is Shopify-based
- Uses Shopify JSON API scraper for Shopify stores (fast & reliable)
- Falls back to general HTML scraper for non-Shopify stores (universal)
- Multi-strategy product detection and extraction
- Scrolling support for lazy-loaded content
- Enhanced buying options extraction

This v2 variant fetches product JSON using a CLEAN Playwright request context
(no cookies), to avoid sites that set invalid Cookie headers which break the
`.js` request when using the browser context's request object.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import html
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Set
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.sync_api import sync_playwright, Page, BrowserContext

# Add parent directory to path to import fallback scraper
sys.path.insert(0, str(Path(__file__).parent.parent))
from scrapper.product_scaper_final_v2 import (
    crawl_website as fallback_crawl_website,
    save_results as fallback_save_results
)


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip('/') if parsed.path != '/' else parsed.path,
        parsed.params,
        parsed.query,
        ''
    ))
    return normalized


@dataclass
class VariantData:
    id: int
    title: str
    weight: float
    available: bool
    buy_once_price: str
    compare_at_price: Optional[str]
    subscription_price: Optional[str]
    subscription_options: List[Dict]


@dataclass
class ProductData:
    page_url: str
    product_id: int
    product_name: str
    handle: str
    description: str
    available: bool
    featured_image: str
    variants: List[VariantData]


@dataclass
class PageData:
    url: str
    is_product_page: bool
    page_title: Optional[str]
    crawled_at: str
    products: List[ProductData]
    links_found: List[str]


def _detect_shopify_store(url: str, verbose: bool = False) -> bool:
    """
    Detect if a website is a Shopify store by checking for Shopify indicators.
    
    Returns:
        True if the site is Shopify-based, False otherwise
    """
    try:
        if verbose:
            print(f"[Shopify Detection] Checking {url}...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(10000)
            
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                
                # Check 1: Look for Shopify JavaScript variables
                has_shopify_js = page.evaluate("""
                    () => {
                        return typeof window.Shopify !== 'undefined' || 
                               typeof window.ShopifyAnalytics !== 'undefined' ||
                               document.querySelector('script[src*="shopify"]') !== null ||
                               document.querySelector('link[href*="shopify"]') !== null;
                    }
                """)
                
                if has_shopify_js:
                    if verbose:
                        print("[Shopify Detection] Found Shopify JS variables or assets")
                    browser.close()
                    return True
                
                # Check 2: Try to access a common Shopify endpoint
                base_url = re.match(r"^(https?://[^/]+)", url).group(1)
                test_endpoints = [
                    f"{base_url}/products.json",
                    f"{base_url}/collections.json",
                ]
                
                for endpoint in test_endpoints:
                    try:
                        with sync_playwright() as p_req:
                            req_ctx = p_req.request.new_context()
                            response = req_ctx.get(endpoint)
                            req_ctx.dispose()
                        
                        if response.ok:
                            try:
                                data = response.json()
                                if 'products' in data or 'collections' in data:
                                    if verbose:
                                        print(f"[Shopify Detection] Found Shopify API endpoint: {endpoint}")
                                    browser.close()
                                    return True
                            except:
                                pass
                    except:
                        continue
                
                # Check 3: Look for Shopify meta tags or attributes
                has_shopify_meta = page.evaluate("""
                    () => {
                        const metas = document.querySelectorAll('meta[content*="Shopify"]');
                        const shopifyAttr = document.querySelector('[data-shopify]');
                        return metas.length > 0 || shopifyAttr !== null;
                    }
                """)
                
                if has_shopify_meta:
                    if verbose:
                        print("[Shopify Detection] Found Shopify meta tags or attributes")
                    browser.close()
                    return True
                
                if verbose:
                    print("[Shopify Detection] No Shopify indicators found")
                browser.close()
                return False
                
            except Exception as e:
                if verbose:
                    print(f"[Shopify Detection Error] {e}")
                browser.close()
                return False
                
    except Exception as e:
        if verbose:
            print(f"[Shopify Detection Error] {e}")
        return False


def _is_shopify_product_url(url: str) -> bool:
    url_lower = url.lower()
    if '/products/' not in url_lower:
        return False
    exclusion_patterns = [
        '/cart', '/checkout', '/account', '/login', '/register', '/search', '/collections',
    ]
    for pattern in exclusion_patterns:
        if pattern in url_lower:
            return False
    match = re.search(r'/products/([^/?#]+)', url_lower)
    return bool(match and match.group(1))


def _extract_product_handle(url: str) -> Optional[str]:
    match = re.search(r'/products/([^/?#]+)', url)
    if match:
        return match.group(1)
    return None


def _build_plan_lookup(product_json: Dict) -> Dict[int, Dict[str, Optional[str]]]:
    lookup: Dict[int, Dict[str, Optional[str]]] = {}
    try:
        for group in (product_json.get("selling_plan_groups") or []):
            group_name = group.get("name")
            for plan in (group.get("selling_plans") or []):
                discount = None
                for adj in (plan.get("price_adjustments") or []):
                    if adj.get("value_type") == "percentage":
                        discount = adj.get("value")
                plan_id = plan.get("id")
                if plan_id is not None:
                    lookup[plan_id] = {
                        "plan_name": plan.get("name"),
                        "group_name": group_name,
                        "discount_percent": discount,
                    }
    except Exception:
        pass
    return lookup


def _scroll_page_to_load_content(page: Page, verbose: bool = False) -> None:
    """Scroll the page to trigger lazy-loaded content and infinite lists."""
    try:
        # Initial height
        initial_height = page.evaluate("document.body.scrollHeight")
        current_scroll = 0
        step = 1000
        no_change = 0
        for _ in range(30):  # max steps
            current_scroll += step
            page.evaluate(f"window.scrollTo(0, {current_scroll})")
            page.wait_for_timeout(300)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height > initial_height:
                initial_height = new_height
                no_change = 0
            else:
                no_change += 1
            if no_change >= 5:
                break
        # small pause to allow any final loads
        page.wait_for_timeout(500)
    except Exception:
        pass


def _fetch_shopify_product_json(
    context: BrowserContext,
    product_url: str,
    verbose: bool = False,
    page: Optional[Page] = None,
) -> Optional[Dict]:
    """
    Multi-strategy fetch of Shopify product JSON, in this order:
    1) In-page fetch of /products/{handle}.js using window.fetch with credentials (uses site cookies)
    2) Clean request context GET to /products/{handle}.js (no cookies)
    3) Clean request context GET to /products/{handle}.json (parse ['product'])
    4) Parse JSON-LD Product from the HTML
    Returns a standard product dict matching the .js structure when possible.
    """
    try:
        handle = _extract_product_handle(product_url)
        if not handle:
            if verbose:
                print(f"[Resolver] Could not extract product handle from: {product_url}")
            return None

        base_url = re.match(r"^(https?://[^/]+)", product_url).group(1)
        js_url = f"{base_url}/products/{handle}.js"
        json_url = f"{base_url}/products/{handle}.json"

        # 1) Try in-page fetch (best chance to pass anti-bot/cookie checks)
        if page is not None:
            try:
                if verbose:
                    print(f"[Resolver] In-page fetch: {js_url}")
                js_text = page.evaluate(
                    "url => fetch(url, {credentials: 'include'}).then(r => r.text())",
                    js_url,
                )
                if js_text and js_text.strip().startswith("{"):
                    product_json = json.loads(js_text)
                    return product_json
            except Exception as e:
                if verbose:
                    print(f"[Resolver] In-page fetch failed: {e}")

        # Build a fresh request context with safe headers and NO cookies
        req_headers = {
            "Accept": "application/json, text/javascript;q=0.9, */*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        }
        with sync_playwright() as p_req:
            req_ctx = p_req.request.new_context(extra_http_headers=req_headers)
            try:
                # 2) Clean GET to .js
                if verbose:
                    print(f"[Resolver] Clean fetch: {js_url}")
                resp = req_ctx.get(js_url)
                ctype = (resp.headers.get("content-type") or "").lower()
                body = resp.text()
                if resp.ok and ("json" in ctype or "javascript" in ctype or (body and body.strip().startswith("{"))):
                    return json.loads(body)

                # 3) Clean GET to .json
                if verbose:
                    print(f"[Resolver] Fallback fetch: {json_url}")
                resp2 = req_ctx.get(json_url)
                if resp2.ok:
                    try:
                        data2 = resp2.json()
                        # Many stores return {"product": {...}}
                        if isinstance(data2, dict) and isinstance(data2.get("product"), dict):
                            return data2["product"]
                    except Exception:
                        pass
            finally:
                req_ctx.dispose()

        # 4) JSON-LD parse from the HTML
        if page is not None:
            try:
                if verbose:
                    print(f"[Resolver] Try JSON-LD parse from page")
                scripts = page.locator('script[type="application/ld+json"]').all_text_contents()
                for s in scripts:
                    try:
                        data = json.loads(s)
                    except Exception:
                        continue
                    items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
                    for item in items:
                        if isinstance(item, dict) and item.get("@type") in ("Product", "ProductModel"):
                            # Convert minimal JSON-LD to .js-like structure (best effort)
                            product_like = {
                                "id": 0,
                                "title": item.get("name"),
                                "handle": handle,
                                "description": item.get("description", ""),
                                "available": True,
                                "featured_image": "",
                                "variants": [],
                            }
                            # Offers may include price
                            offers = item.get("offers")
                            price = None
                            if isinstance(offers, dict):
                                price = offers.get("price")
                            variant = {
                                "id": 0,
                                "title": "default",
                                "price": float(price) * 100 if price else 0,
                                "weight": 0,
                                "selling_plan_allocations": [],
                                "available": True,
                            }
                            product_like["variants"].append(variant)
                            return product_like
            except Exception as e:
                if verbose:
                    print(f"[Resolver] JSON-LD parse failed: {e}")

        return None

    except Exception as e:
        if verbose:
            print(f"[Resolver Error] {e}")
        return None


def _extract_product_from_json(
    product_json: Dict,
    product_url: str,
    base_url: str,
    verbose: bool = False
) -> ProductData:
    raw_description = product_json.get("description", "")
    clean_description = html.unescape(
        re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', raw_description))
    ).strip()

    plan_lookup = _build_plan_lookup(product_json)

    variants = []
    for v in product_json.get("variants", []):
        weight = v.get("weight") or v.get("grams") or 0
        buy_once_price = (v.get("price") or 0) / 100
        compare_at_raw = v.get("compare_at_price")
        compare_at_price = f"{(compare_at_raw or 0) / 100:.2f}" if compare_at_raw else None

        subscription_options: List[Dict] = []
        allocations = v.get("selling_plan_allocations") or []
        for alloc in allocations:
            sp_id = alloc.get("selling_plan_id")
            meta = plan_lookup.get(sp_id, {}) if sp_id is not None else {}
            subscription_options.append({
                "plan_id": sp_id,
                "plan_name": meta.get("plan_name"),
                "group_name": meta.get("group_name"),
                "discount_percent": meta.get("discount_percent"),
                "price": f"{((alloc.get('price') or 0) / 100):.2f}",
                "compare_at_price": f"{(((alloc.get('compare_at_price') or v.get('price') or 0)) / 100):.2f}",
                "per_delivery_price": f"{((alloc.get('per_delivery_price') or alloc.get('price') or 0) / 100):.2f}",
            })

        subscription_price = None
        if subscription_options:
            subscription_price = f"{min(float(o['price']) for o in subscription_options):.2f}"

        variants.append(VariantData(
            id=v.get("id"),
            title=v.get("title"),
            weight=weight,
            available=bool(v.get("available", False)),
            buy_once_price=f"{buy_once_price:.2f}",
            compare_at_price=compare_at_price,
            subscription_price=subscription_price,
            subscription_options=subscription_options,
        ))

    product = ProductData(
        page_url=product_url,
        product_id=product_json.get("id"),
        product_name=product_json.get("title"),
        handle=product_json.get("handle"),
        description=clean_description,
        available=product_json.get("available", False),
        featured_image=urljoin(base_url, product_json.get("featured_image", "")),
        variants=variants
    )

    if verbose:
        print(f"[Product] {product.product_name}")
        print(f"[Variants] {len(variants)} variant(s)")
    return product


def _extract_links(page: Page, base_url: str) -> List[str]:
    links = []
    try:
        anchors = page.locator('a[href]')
        for i in range(min(100, anchors.count())):
            try:
                href = anchors.nth(i).get_attribute('href')
                if href:
                    full_url = urljoin(base_url, href)
                    normalized_url = normalize_url(full_url)
                    if urlparse(normalized_url).netloc == urlparse(base_url).netloc:
                        skip_patterns = [
                            '?__geom=',
                            '/en-us', '/en-au', '/en-ca', '/en-ie', '/en-eu', '/en-nz', '/de-de', '/fr-fr', '/es-es', '/it-it',
                        ]
                        if any(pattern in normalized_url.lower() for pattern in skip_patterns):
                            continue
                        if normalized_url not in links:
                            links.append(normalized_url)
            except:
                continue
    except Exception:
        pass
    return links


def crawl_shopify_store(
    start_url: str,
    out_dir: str,
    max_pages: int = 20,
    headless: bool = True,
    verbose: bool = True,
) -> List[PageData]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(30000)

        os.makedirs(out_dir, exist_ok=True)

        visited_urls: Set[str] = set()
        to_visit: List[str] = [normalize_url(start_url)]
        results: List[PageData] = []

        base_domain = urlparse(start_url).netloc

        while to_visit and len(visited_urls) < max_pages:
            current_url = to_visit.pop(0)
            normalized_url = normalize_url(current_url)

            if normalized_url in visited_urls:
                continue
            if not normalized_url.startswith(('http://', 'https://')):
                continue
            if urlparse(normalized_url).netloc != base_domain:
                continue

            print(f"\n[Crawling {len(visited_urls)+1}/{max_pages}] {normalized_url}")
            visited_urls.add(normalized_url)

            try:
                page.goto(normalized_url, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                # Extra stabilization for SPAs/redirects
                try:
                    page.wait_for_load_state("networkidle", timeout=2000)
                except Exception:
                    pass

                # Scroll to load lazy content and reveal more links/products
                _scroll_page_to_load_content(page, verbose=verbose)

                try:
                    page_title = page.title()
                except Exception:
                    page_title = ""

                is_product = _is_shopify_product_url(normalized_url)
                # Do not mark non-product yet; try resolution flow first
                print(f"[Detection] Product page: {is_product}")

                products = []
                if is_product:
                    base_url = f"{urlparse(normalized_url).scheme}://{urlparse(normalized_url).netloc}"
                    product_json = _fetch_shopify_product_json(
                        context,
                        normalized_url,
                        verbose=verbose,
                        page=page
                    )
                    if product_json:
                        product = _extract_product_from_json(
                            product_json,
                            normalized_url,
                            base_url,
                            verbose=verbose
                        )
                        products.append(product)
                    else:
                        if verbose:
                            print(f"[Warning] Failed to fetch JSON data for product page")

                links = _extract_links(page, normalized_url)
                for link in links:
                    normalized_link = normalize_url(link)
                    if normalized_link not in visited_urls and normalized_link not in to_visit:
                        to_visit.append(normalized_link)

                page_data = PageData(
                    url=normalized_url,
                    is_product_page=is_product,
                    page_title=page_title,
                    crawled_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    products=products,
                    links_found=links[:20],
                )
                results.append(page_data)

            except Exception as e:
                print(f"[Error] Failed to crawl {normalized_url}: {e}")
                continue

        browser.close()

        total_products = sum(len(r.products) for r in results)
        print(f"\n{'='*60}")
        print(f"[Summary] Crawl Complete (Shopify JSON API)")
        print(f"{'='*60}")
        print(f"  Pages crawled: {len(visited_urls)}")
        print(f"  Total products scraped: {total_products}")
        print(f"{'='*60}\n")

        return results


def save_results(results: List[PageData], out_dir: str) -> None:
    try:
        output_file = os.path.join(out_dir, "crawl_results.json")
        total_products_count = sum(len(r.products) for r in results)
        data = {
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pages": len(results),
            "product_pages": sum(1 for r in results if r.is_product_page),
            "total_products": total_products_count,
            "pages": [asdict(r) for r in results]
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n[Saved] Results saved to {output_file}")

        products_only = []
        seen_product_ids = set()
        for page in results:
            if page.products:
                for product in page.products:
                    if product.product_id in seen_product_ids:
                        continue
                    seen_product_ids.add(product.product_id)
                    products_only.append(asdict(product))

        if products_only:
            products_file = os.path.join(out_dir, "products.json")
            with open(products_file, "w", encoding="utf-8") as f:
                json.dump({
                    "total_products": len(products_only),
                    "products": products_only
                }, f, ensure_ascii=False, indent=2)
            print(f"[Saved] Products saved to {products_file}")
            print(f"[Info] Total unique products: {len(products_only)}")

    except Exception as e:
        print(f"[Error] Failed to save results: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Intelligent Product Scraper - Auto-detects Shopify and uses appropriate scraper"
    )
    parser.add_argument(
        "url",
        nargs='?',
        help="Starting URL to crawl. If not provided, will prompt for input."
    )
    parser.add_argument(
        "--out-dir",
        default="shopify_data",
        help="Output directory for data files"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum number of pages to crawl"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output"
    )
    parser.add_argument(
        "--force-shopify",
        action="store_true",
        help="Skip Shopify detection and force use of Shopify scraper"
    )

    args = parser.parse_args()

    url = args.url
    if not url:
        print("Intelligent Product Scraper - Auto-detects Platform")
        print("=" * 60)
        url = input("Enter store URL to crawl: ").strip()
        if not url:
            print("Error: No URL provided")
            return 1
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
            print(f"Using URL: {url}")

    if not url.startswith(('http://', 'https://')):
        print("Error: Invalid URL format. Must start with http:// or https://")
        return 1

    print(f"\n{'='*60}")
    print(f"Intelligent Product Scraper with Platform Detection")
    print(f"{'='*60}")
    print(f"Target URL: {url}")
    print(f"Max pages: {args.max_pages}")
    print(f"Output dir: {args.out_dir}")
    
    # Detect if site is Shopify
    is_shopify = False
    if args.force_shopify:
        is_shopify = True
        print(f"Platform: Shopify (forced)")
    else:
        print(f"Detecting platform...")
        is_shopify = _detect_shopify_store(url, verbose=not args.quiet)
        if is_shopify:
            print(f"Platform: Shopify (detected)")
        else:
            print(f"Platform: Non-Shopify (detected)")
            print(f"{'='*60}")
            print(f"[Fallback] Using general-purpose HTML scraper")
    
    print(f"{'='*60}")

    # Use appropriate scraper based on platform
    if is_shopify:
        # Use Shopify-specific JSON API scraper
        print(f"\n[Shopify Mode] Using fast JSON API scraper...\n")
        results = crawl_shopify_store(
            start_url=url,
            out_dir=args.out_dir,
            max_pages=args.max_pages,
            headless=args.headless,
            verbose=not args.quiet,
        )
        save_results(results, args.out_dir)
    else:
        # Use fallback general-purpose scraper
        print(f"\n[HTML Mode] Using universal HTML scraper...")
        print(f"This scraper works with any e-commerce platform.\n")
        
        results = fallback_crawl_website(
            start_url=url,
            out_dir=args.out_dir,
            max_pages=args.max_pages,
            download_media=True,
            headless=args.headless,
            verbose=not args.quiet,
            scroll_enabled=True,
            buy_button_scraping=True,
            take_screenshots=True,
            accept_cookies=True,
            extract_buying_options=False  # Can enable if needed
        )
        fallback_save_results(results, args.out_dir)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

