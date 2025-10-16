"""
shopify_scraper_json.py

Shopify-specific product scraper using JSON API endpoints.

Instead of scraping HTML, this leverages Shopify's built-in .js endpoint:
- Every Shopify product has a JSON API at /products/{handle}.js
- Returns structured data with variants, pricing, subscriptions
- Much more reliable than HTML scraping
- Works for all Shopify stores

Key Features:
- URL normalization (no hash fragment duplicates)
- Crawls Shopify stores using JSON API
- Extracts complete variant and subscription data
- Automatic deduplication
- Clean, production-ready output

Usage:
  python shopify/shopify_scraper_json.py "https://shopify-store.com" \
    --out-dir shopify_data \
    --max-pages 20 \
    --headless
"""

from __future__ import annotations

import argparse
import json
import os
import re
import html
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Set
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.sync_api import sync_playwright, Page, BrowserContext


def normalize_url(url: str) -> str:
    """
    Normalize URL by removing fragments (hash) and trailing slashes.
    This prevents treating the same page with different hash fragments as different pages.
    """
    parsed = urlparse(url)
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip('/') if parsed.path != '/' else parsed.path,
        parsed.params,
        parsed.query,
        ''  # Remove fragment
    ))
    return normalized


@dataclass
class VariantData:
    """Represents a product variant."""
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
    """Represents a Shopify product."""
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
    """Represents a crawled page."""
    url: str
    is_product_page: bool
    page_title: Optional[str]
    crawled_at: str
    products: List[ProductData]
    links_found: List[str]


def _is_shopify_product_url(url: str) -> bool:
    """
    Check if URL is a Shopify product URL.
    Must contain /products/ with a product handle after it.
    """
    url_lower = url.lower()
    
    # Must contain /products/ pattern
    if '/products/' not in url_lower:
        return False
    
    # Exclusion patterns (not product pages)
    exclusion_patterns = [
        '/cart',
        '/checkout',
        '/account',
        '/login',
        '/register',
        '/search',
        '/collections',
    ]
    
    for pattern in exclusion_patterns:
        if pattern in url_lower:
            return False
    
    # Extract what comes after /products/
    match = re.search(r'/products/([^/?#]+)', url_lower)
    if match and match.group(1):
        return True
    
    return False


def _extract_product_handle(url: str) -> Optional[str]:
    """Extract product handle from Shopify product URL."""
    match = re.search(r'/products/([^/?#]+)', url)
    if match:
        return match.group(1)
    return None


def _build_plan_lookup(product_json: Dict) -> Dict[int, Dict[str, Optional[str]]]:
    """
    Build a lookup of selling_plan_id -> {plan_name, group_name, discount_percent}.
    This allows us to enrich per-variant allocations with human-readable plan info.
    """
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
        # Be resilient: if structure varies we still proceed without names/discounts
        pass
    return lookup


def _fetch_shopify_product_json(
    context: BrowserContext,
    product_url: str,
    verbose: bool = False
) -> Optional[Dict]:
    """
    Fetch product data from Shopify's JSON API endpoint.
    
    Every Shopify product page has a .js endpoint that returns JSON:
    https://store.com/products/product-name -> https://store.com/products/product-name.js
    """
    try:
        # Extract product handle
        handle = _extract_product_handle(product_url)
        if not handle:
            if verbose:
                print(f"[JSON API] Could not extract product handle from: {product_url}")
            return None
        
        # Build JSON API URL
        base_url = re.match(r"^(https?://[^/]+)", product_url).group(1)
        json_url = f"{base_url}/products/{handle}.js"
        
        if verbose:
            print(f"[JSON API] Fetching: {json_url}")
        
        # Fetch JSON data
        response = context.request.get(json_url, headers={
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        })
        
        if not response.ok:
            if verbose:
                print(f"[JSON API] Failed to fetch (status {response.status}): {json_url}")
            return None
        
        product_json = response.json()
        
        if verbose:
            print(f"[JSON API] Successfully fetched product data")
        
        return product_json
        
    except Exception as e:
        if verbose:
            print(f"[JSON API Error] {e}")
        return None


def _extract_product_from_json(
    product_json: Dict,
    product_url: str,
    base_url: str,
    verbose: bool = False
) -> ProductData:
    """
    Extract product data from Shopify JSON response.
    """
    # Clean description (remove HTML tags, decode entities)
    raw_description = product_json.get("description", "")
    clean_description = html.unescape(
        re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', raw_description))
    ).strip()
    
    # Build plan lookup for human-friendly names/discounts
    plan_lookup = _build_plan_lookup(product_json)

    # Extract variants
    variants = []
    for v in product_json.get("variants", []):
        # Extract weight safely
        weight = v.get("weight") or v.get("grams") or 0

        # Extract prices (Shopify stores as cents/pence)
        buy_once_price = (v.get("price") or 0) / 100
        compare_at_raw = v.get("compare_at_price")
        compare_at_price = f"{(compare_at_raw or 0) / 100:.2f}" if compare_at_raw else None

        # Collect all subscription options for this variant
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

        # Lowest subscription price for convenience
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
    
    # Build product data
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
        for i, v in enumerate(variants[:3], 1):  # Show first 3
            sub_info = f" (Subscribe: {v.subscription_price})" if v.subscription_price else ""
            print(f"  {i}. {v.title}: {v.buy_once_price}{sub_info}")
    
    return product


def _extract_links(page: Page, base_url: str) -> List[str]:
    """Extract all links from the current page (normalized)."""
    links = []
    try:
        anchors = page.locator('a[href]')
        for i in range(min(100, anchors.count())):
            try:
                href = anchors.nth(i).get_attribute('href')
                if href:
                    full_url = urljoin(base_url, href)
                    normalized_url = normalize_url(full_url)
                    
                    # Only keep links from the same domain
                    if urlparse(normalized_url).netloc == urlparse(base_url).netloc:
                        # Skip regional URLs and country selectors
                        skip_patterns = [
                            '?__geom=',
                            '/en-us', '/en-au', '/en-ca', '/en-ie',
                            '/en-eu', '/en-nz', '/de-de', '/fr-fr',
                            '/es-es', '/it-it',
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


def _safe_name(name: str) -> str:
    """Sanitize filename by replacing unsafe characters."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name or "file")


def crawl_shopify_store(
    start_url: str,
    out_dir: str,
    max_pages: int = 20,
    headless: bool = True,
    verbose: bool = True,
) -> List[PageData]:
    """
    Crawl Shopify store using JSON API for product data.
    
    Args:
        start_url: Starting URL to crawl
        out_dir: Output directory for data
        max_pages: Maximum number of pages to crawl
        headless: Run browser in headless mode
        verbose: Show detailed output
    
    Returns:
        List of PageData objects with crawled information
    """
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
            
            # Skip if already visited
            if normalized_url in visited_urls:
                continue
            
            # Skip non-http(s) URLs
            if not normalized_url.startswith(('http://', 'https://')):
                continue
            
            # Skip if different domain
            if urlparse(normalized_url).netloc != base_domain:
                continue
            
            print(f"\n[Crawling {len(visited_urls)+1}/{max_pages}] {normalized_url}")
            visited_urls.add(normalized_url)
            
            try:
                page.goto(normalized_url, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                
                page_title = page.title()
                
                # Check if it's a Shopify product URL
                is_product = _is_shopify_product_url(normalized_url)
                print(f"[Detection] Product page: {is_product}")
                
                products = []
                
                if is_product:
                    # Fetch product data from JSON API
                    base_url = f"{urlparse(normalized_url).scheme}://{urlparse(normalized_url).netloc}"
                    product_json = _fetch_shopify_product_json(
                        context,
                        normalized_url,
                        verbose=verbose
                    )
                    
                    if product_json:
                        # Extract product data from JSON
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
                
                # Extract links for further crawling
                links = _extract_links(page, normalized_url)
                
                # Add new links to the queue
                for link in links:
                    normalized_link = normalize_url(link)
                    if normalized_link not in visited_urls and normalized_link not in to_visit:
                        to_visit.append(normalized_link)
                
                # Create page data
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
        print(f"[Summary] Crawl Complete")
        print(f"{'='*60}")
        print(f"  Pages crawled: {len(visited_urls)}")
        print(f"  Total products scraped: {total_products}")
        print(f"{'='*60}\n")
        
        return results


def save_results(results: List[PageData], out_dir: str) -> None:
    """Save crawl results to JSON file."""
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
        
        # Save products summary (deduplicated)
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
        description="Shopify Product Scraper - Uses JSON API for reliable data extraction"
    )
    parser.add_argument(
        "url",
        nargs='?',  # Make URL optional
        help="Starting URL to crawl (Shopify store). If not provided, will prompt for input."
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
    
    args = parser.parse_args()
    
    # Get URL from command line or prompt user
    url = args.url
    if not url:
        print("🚀 Shopify Product Scraper - JSON API Edition")
        print("=" * 60)
        url = input("Enter Shopify store URL to crawl: ").strip()
        
        if not url:
            print("❌ Error: No URL provided")
            return 1
        
        # Add https:// if not present
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
            print(f"📝 Using URL: {url}")
    
    # Validate it looks like a URL
    if not url.startswith(('http://', 'https://')):
        print("❌ Error: Invalid URL format. Must start with http:// or https://")
        return 1
    
    print(f"\n{'='*60}")
    print(f"Shopify Product Scraper - JSON API Edition")
    print(f"{'='*60}")
    print(f"Target URL: {url}")
    print(f"Max pages: {args.max_pages}")
    print(f"Output dir: {args.out_dir}")
    print(f"{'='*60}")
    print(f"Features:")
    print(f"  - Uses Shopify's built-in JSON API (.js endpoint)")
    print(f"  - Extracts complete variant and pricing data")
    print(f"  - Includes subscription pricing")
    print(f"  - URL normalization (no hash fragment duplicates)")
    print(f"  - Automatic deduplication by product ID")
    print(f"  - Clean, structured JSON output")
    print(f"  - More reliable than HTML scraping")
    print(f"{'='*60}\n")
    
    results = crawl_shopify_store(
        start_url=url,
        out_dir=args.out_dir,
        max_pages=args.max_pages,
        headless=args.headless,
        verbose=not args.quiet,
    )
    
    save_results(results, args.out_dir)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

