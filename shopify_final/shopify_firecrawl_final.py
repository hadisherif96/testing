"""
shopify_firecrawl_final.py

Optimized Shopify scraper using Firecrawl's native link extraction.
No BeautifulSoup - uses Firecrawl's links directly for maximum speed.

Usage:
  python shopify_firecrawl_final.py "https://example-shop.com/products/foo" --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import re
import html as html_module
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Set
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode

try:
    from firecrawl import Firecrawl
except ImportError:
    print("ERROR: firecrawl-py not installed. Run: pip install firecrawl-py")
    raise

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    raise


def normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and tracking parameters."""
    parsed = urlparse(url)

    if parsed.query:
        query_params = parse_qs(parsed.query)
        tracking_params = [
            'pr_prod_strat', 'pr_rec_id', 'pr_rec_pid', 'pr_ref_pid', 'pr_seq',
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'fbclid', 'gclid', 'msclkid', '_ga', '_gid', '_gac',
            'mc_cid', 'mc_eid', 'pb',
        ]
        clean_params = {k: v for k, v in query_params.items() if k not in tracking_params}
        clean_query = urlencode(clean_params, doseq=True) if clean_params else ''
    else:
        clean_query = ''

    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip('/') if parsed.path != '/' else parsed.path,
        parsed.params,
        clean_query,
        ''
    ))
    return normalized


@dataclass
class VariantData:
    """Variant data structure."""
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
    """Product data structure."""
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
    """Page data structure."""
    url: str
    is_product_page: bool
    page_title: Optional[str]
    crawled_at: str
    products: List[ProductData]
    links_found: List[str]


def _is_shopify_product_url(url: str) -> bool:
    """Check if URL looks like a product URL."""
    url_lower = url.lower()

    # Shopify standard pattern
    if '/products/' in url_lower:
        return True

    # Alternative patterns often used by stores
    product_patterns = [
        r'/supplements/[^/?#]+$',
        r'/shop/[^/?#]+$',
        r'/product/[^/?#]+$',
    ]

    for pattern in product_patterns:
        if re.search(pattern, url_lower):
            return True

    return False


def _extract_product_handle(url: str) -> Optional[str]:
    """Extract product handle from URL."""
    # Try standard Shopify pattern first
    match = re.search(r'/products/([^/?#]+)', url)
    if match:
        return match.group(1)

    # Try alternative patterns
    match = re.search(r'/supplements/([^/?#]+)', url)
    if match:
        return match.group(1)

    match = re.search(r'/shop/([^/?#]+)', url)
    if match:
        return match.group(1)

    return None


def _build_plan_lookup(product_json: Dict) -> Dict[int, Dict[str, Optional[str]]]:
    """Build lookup of selling plan data."""
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


def _fetch_shopify_product_json(
    product_url: str,
    verbose: bool = False
) -> Optional[Dict]:
    """Try to fetch Shopify JSON API data via .js endpoint."""
    try:
        handle = _extract_product_handle(product_url)
        if not handle:
            return None

        base_url = re.match(r"^(https?://[^/]+)", product_url).group(1)

        # Standard Shopify endpoint
        json_url = f"{base_url}/products/{handle}.js"

        if verbose:
            print(f"[JSON API] Trying: {json_url}")

        with httpx.Client(timeout=30.0) as client:
            response = client.get(json_url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0"
            })

        if response.status_code == 200:
            if verbose:
                print(f"[JSON API] ✓ Success")
            return response.json()

        if verbose:
            print(f"[JSON API] ✗ Failed (status {response.status_code})")
        return None

    except Exception as e:
        if verbose:
            print(f"[JSON API] ✗ Exception: {e}")
        return None


def _extract_product_from_json(
    product_json: Dict,
    product_url: str,
    base_url: str,
    verbose: bool = False
) -> ProductData:
    """Extract product data from Shopify JSON."""
    raw_description = product_json.get("description", "")
    clean_description = html_module.unescape(
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
        print(f"[Variants] {len(variants)} variant(s) from JSON API")

    return product


def crawl_shopify_store(
    start_url: str,
    out_dir: str,
    max_pages: int = 20,
    api_key: Optional[str] = None,
    verbose: bool = True,
) -> List[PageData]:
    """
    Crawl Shopify store using Firecrawl's native link extraction.
    Uses only Firecrawl for rendering and link discovery.
    Product data comes from Shopify .js endpoint.
    """
    firecrawl_key = api_key or os.getenv("FIRECRAWL_API_KEY")
    if not firecrawl_key:
        raise ValueError("Firecrawl API key required")

    try:
        firecrawl = Firecrawl(api_key=firecrawl_key)
    except Exception as e:
        raise ValueError(f"Failed to initialize Firecrawl: {e}")

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
            # Render with Firecrawl - get links directly from response
            if verbose:
                print(f"[Firecrawl] Rendering page...")

            scrape_result = firecrawl.scrape(
                normalized_url,
                formats=['html', 'links']  # Request links explicitly
            )

            metadata = getattr(scrape_result, 'metadata', {}) or {}
            page_title = metadata.get('title', '') if isinstance(metadata, dict) else ''

            if verbose:
                print(f"[Firecrawl] ✓ Page rendered")

            # Determine if product page by URL pattern
            is_product = _is_shopify_product_url(normalized_url)
            print(f"[Detection] Product page: {is_product}")

            products: List[ProductData] = []

            if is_product:
                base_url = f"{urlparse(normalized_url).scheme}://{urlparse(normalized_url).netloc}"

                # Only JSON API (.js) extraction
                product_json = _fetch_shopify_product_json(normalized_url, verbose=verbose)

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
                        print(f"[Skip] No JSON API data available")

            # Extract links directly from Firecrawl response (NO BeautifulSoup!)
            firecrawl_links = getattr(scrape_result, 'links', None) or []
            
            if verbose:
                print(f"[Firecrawl Links] Found {len(firecrawl_links)} links")

            links = []
            for link in firecrawl_links[:500]:
                try:
                    # Handle both string URLs and dict formats
                    if isinstance(link, str):
                        full_url = urljoin(normalized_url, link)
                    elif isinstance(link, dict):
                        href = link.get('href') or link.get('url', '')
                        full_url = urljoin(normalized_url, href)
                    else:
                        continue

                    normalized_link = normalize_url(full_url)

                    # Filter links
                    if urlparse(normalized_link).netloc != base_domain:
                        continue

                    skip_patterns = ['/cart', '/checkout', '/account', '/login', '/register']
                    if any(p in normalized_link.lower() for p in skip_patterns):
                        continue

                    if normalized_link not in links:
                        links.append(normalized_link)

                except:
                    continue

            # Prioritize product-like URLs
            priority_links = []
            normal_links = []

            for link in links:
                if link not in visited_urls and link not in to_visit:
                    if any(p in link.lower() for p in ['/products/', '/supplements/', '/shop/']):
                        priority_links.append(link)
                    else:
                        normal_links.append(link)

            to_visit.extend(priority_links)
            to_visit.extend(normal_links)

            if verbose:
                print(f"[Queue] {len(priority_links)} product pages, {len(normal_links)} other pages")

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
            print(f"[Error] {e}")
            if verbose:
                import traceback
                traceback.print_exc()
            continue

    total_products = sum(len(r.products) for r in results)
    print(f"\n{'='*60}")
    print(f"[Summary] Crawl Complete")
    print(f"{'='*60}")
    print(f"  Pages crawled: {len(visited_urls)}")
    print(f"  Products found: {total_products}")
    print(f"{'='*60}\n")

    return results


def save_results(results: List[PageData], out_dir: str) -> None:
    """Save results to JSON files."""
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
        print(f"\n[Saved] {output_file}")

        # Save unique products only
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
            print(f"[Saved] {products_file}")
            print(f"[Info] {len(products_only)} unique products")

    except Exception as e:
        print(f"[Error] Failed to save: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shopify Scraper - Firecrawl Final (Optimized, No BeautifulSoup)"
    )
    parser.add_argument("url", nargs='?', help="URL to scrape")
    parser.add_argument("--out-dir", default="shopify_firecrawl_final_output", help="Output directory")
    parser.add_argument("--max-pages", type=int, default=5, help="Max pages to crawl")
    parser.add_argument("--api-key", help="Firecrawl API key")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    url = args.url
    if not url:
        url = input("Enter URL to scrape: ").strip()
        if not url:
            print("Error: No URL provided")
            return 1
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"

    print(f"\n{'='*60}")
    print(f"Shopify Scraper - Firecrawl Final (Optimized)")
    print(f"{'='*60}")
    print(f"Target: {url}")
    print(f"Max pages: {args.max_pages}")
    print(f"{'='*60}\n")

    try:
        results = crawl_shopify_store(
            start_url=url,
            out_dir=args.out_dir,
            max_pages=args.max_pages,
            api_key=args.api_key,
            verbose=args.verbose,
        )

        save_results(results, args.out_dir)
        return 0

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

