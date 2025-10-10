"""
product_scraper.py

Product scraping tool using Playwright that:
- Crawls website pages
- Detects if a page is a product page
- Extracts product details (name, price, description, images, etc.)
- Downloads media files for detected products
- Organizes results by page

Usage:
  python scrapper/product_scraper.py "https://example.com" \
    --out-dir product_data \
    --max-pages 20 \
    --headless
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Set
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, Page, BrowserContext


@dataclass
class ProductData:
    """Represents a product found on a page."""
    page_url: str
    product_name: Optional[str]
    price: Optional[str]
    currency: Optional[str]
    description: Optional[str]
    sku: Optional[str]
    availability: Optional[str]
    brand: Optional[str]
    images: List[str]
    media_files: List[str]  # Downloaded media file paths
    is_bundle: bool = False  # Whether this is a bundle product
    bundle_name: Optional[str] = None  # Name of the bundle (if is_bundle=True)
    bundle_price: Optional[str] = None  # Price of the bundle (if is_bundle=True)
    bundle_items: List[str] = None  # SKUs of products in bundle (if is_bundle=True)
    raw_data: Dict = None  # Additional structured data if available
    
    def __post_init__(self):
        if self.bundle_items is None:
            self.bundle_items = []
        if self.raw_data is None:
            self.raw_data = {}


@dataclass
class PageData:
    """Represents a crawled page."""
    url: str
    is_product_page: bool
    page_title: Optional[str]
    crawled_at: str
    products: List[ProductData]
    links_found: List[str]


# Price detection patterns
PRICE_PATTERNS = [
    re.compile(r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', re.I),  # $99.99, $1,299.99
    re.compile(r'(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:USD|EUR|GBP)', re.I),  # 99.99 USD
    re.compile(r'(?:USD|EUR|GBP)\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', re.I),  # USD 99.99
    re.compile(r'£\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', re.I),  # £99.99
    re.compile(r'€\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', re.I),  # €99.99
]

# Currency symbols
CURRENCY_MAP = {
    '$': 'USD',
    '£': 'GBP',
    '€': 'EUR',
}


def _is_product_page(page: Page) -> bool:
    """
    Detect if a page is a product page using multiple heuristics:
    1. Schema.org Product markup
    2. OpenGraph product metadata
    3. Product-related patterns in URL
    4. Common e-commerce page structures
    """
    try:
        # Check for Schema.org Product
        schema_product = page.locator('[itemtype*="schema.org/Product"]').count() > 0
        if schema_product:
            return True
        
        # Check for JSON-LD Product schema
        json_ld = page.locator('script[type="application/ld+json"]')
        for i in range(json_ld.count()):
            try:
                content = json_ld.nth(i).inner_text()
                data = json.loads(content)
                if isinstance(data, dict):
                    if data.get('@type') in ['Product', 'ProductModel']:
                        return True
                    if 'product' in str(data).lower():
                        return True
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') in ['Product', 'ProductModel']:
                            return True
            except:
                continue
        
        # Check for OpenGraph product metadata
        og_type = page.locator('meta[property="og:type"]').first
        if og_type.count() > 0:
            og_content = og_type.get_attribute('content') or ''
            if 'product' in og_content.lower():
                return True
        
        # Check URL patterns
        url = page.url.lower()
        product_url_patterns = ['/product/', '/products/', '/item/', '/p/', '/dp/', '/buy/']
        if any(pattern in url for pattern in product_url_patterns):
            return True
        
        # Check for common product page elements
        buy_button = page.locator('button:has-text("Add to Cart"), button:has-text("Buy Now"), button:has-text("Add to Bag")').count() > 0
        price_element = page.locator('[class*="price"], [id*="price"], [data-testid*="price"]').count() > 0
        
        if buy_button and price_element:
            return True
        
        return False
    except Exception:
        return False


def _extract_product_data(page: Page) -> List[ProductData]:
    """
    Extract product information from a product page.
    Returns a list of ProductData objects.
    For bundle pages, returns the bundle + all individual products.
    For regular product pages, returns a single product.
    """
    products = []
    
    # Check if this is a bundle page
    is_bundle_page = 'bundle' in page.url.lower() or 'bundle' in page.title().lower()
    
    # Try JSON-LD first (most reliable for structured data)
    all_json_ld_products = []
    json_ld = page.locator('script[type="application/ld+json"]')
    for i in range(json_ld.count()):
        try:
            content = json_ld.nth(i).inner_text()
            data = json.loads(content)
            
            # Handle both single objects and arrays
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            
            for item in items:
                if isinstance(item, dict) and item.get('@type') in ['Product', 'ProductModel']:
                    # Create a clean copy without review data
                    clean_data = {k: v for k, v in item.items() 
                               if k not in ['review', 'reviews', 'aggregateRating', 'reviewCount']}
                    all_json_ld_products.append(clean_data)
        except:
            continue
    
    # Extract bundle information if this is a bundle page
    if is_bundle_page:
        # Get bundle name and price from page
        bundle_name = None
        bundle_price = None
        bundle_currency = None
        
        # Try to get bundle name from h1 or title
        h1 = page.locator('h1').first
        if h1.count() > 0:
            bundle_name = h1.inner_text().strip()
        else:
            bundle_name = page.title()
        
        # Try to get bundle price - look for the main price on the page
        bundle_price, bundle_currency = _extract_price_from_page(page)
        
        # Extract all products within the bundle
        bundle_product_skus = []
        for product_data in all_json_ld_products:
            sku = product_data.get('sku')
            name = product_data.get('name')
            image = product_data.get('image')
            
            if sku:
                bundle_product_skus.append(sku)
                
                # Create individual product entry
                product = ProductData(
                    page_url=page.url,
                    product_name=name,
                    price=None,  # Individual products in bundle don't have separate prices
                    currency=None,
                    description=product_data.get('description', '')[:500] if product_data.get('description') else None,
                    sku=sku,
                    availability=None,
                    brand=_extract_brand(product_data),
                    images=[image] if isinstance(image, str) else (image[:5] if isinstance(image, list) else []),
                    media_files=[],
                    is_bundle=False,
                    bundle_name=None,
                    bundle_price=None,
                    bundle_items=[],
                    raw_data=product_data
                )
                products.append(product)
        
        # Create the bundle product entry
        bundle_product = ProductData(
            page_url=page.url,
            product_name=bundle_name,
            price=bundle_price,
            currency=bundle_currency,
            description=None,
            sku=f"BUNDLE-{'-'.join(bundle_product_skus[:3])}" if bundle_product_skus else f"BUNDLE-{hash(page.url) % 10000}",
            availability=None,
            brand=None,
            images=_extract_images_from_page(page)[:5],
            media_files=[],
            is_bundle=True,
            bundle_name=bundle_name,
            bundle_price=bundle_price,
            bundle_items=bundle_product_skus,
            raw_data={'bundle_products': all_json_ld_products}
        )
        products.insert(0, bundle_product)  # Bundle first, then individual products
        
    else:
        # Regular product page - extract single product
        if all_json_ld_products:
            # Use first product from JSON-LD
            product_data = all_json_ld_products[0]
            
            # Extract offer/price info
            price = None
            currency = None
            availability = None
            
            if 'offers' in product_data:
                offer = product_data['offers']
                if isinstance(offer, dict):
                    price = str(offer.get('price', ''))
                    currency = offer.get('priceCurrency')
                    availability = offer.get('availability')
            
            # Fallback price extraction from page
            if not price:
                price, currency = _extract_price_from_page(page)
            
            product = ProductData(
                page_url=page.url,
                product_name=product_data.get('name'),
                price=price,
                currency=currency,
                description=product_data.get('description', '')[:500] if product_data.get('description') else None,
                sku=product_data.get('sku'),
                availability=availability,
                brand=_extract_brand(product_data),
                images=_extract_images_from_data(product_data)[:10],
                media_files=[],
                is_bundle=False,
                raw_data=product_data
            )
            products.append(product)
        else:
            # Fallback: Extract from page structure
            product_name = None
            h1 = page.locator('h1').first
            if h1.count() > 0:
                product_name = h1.inner_text().strip()
            else:
                product_name = page.title()
            
            price, currency = _extract_price_from_page(page)
            
            product = ProductData(
                page_url=page.url,
                product_name=product_name,
                price=price,
                currency=currency,
                description=None,
                sku=None,
                availability=None,
                brand=None,
                images=_extract_images_from_page(page)[:10],
                media_files=[],
                is_bundle=False,
                raw_data={}
            )
            products.append(product)
    
    return products


def _extract_brand(product_data: Dict) -> Optional[str]:
    """Extract brand from product data."""
    if 'brand' in product_data:
        brand_obj = product_data['brand']
        return brand_obj.get('name') if isinstance(brand_obj, dict) else str(brand_obj)
    return None


def _extract_images_from_data(product_data: Dict) -> List[str]:
    """Extract images from product JSON-LD data."""
    images = []
    if 'image' in product_data:
        img = product_data['image']
        if isinstance(img, str):
            images.append(img)
        elif isinstance(img, list):
            images.extend([i for i in img if isinstance(i, str)])
    return images


def _extract_images_from_page(page: Page) -> List[str]:
    """Extract images from page HTML."""
    images = []
    
    # Try product-specific image selectors first
    img_selectors = [
        'img[class*="product"]',
        'img[class*="Product"]',
        'img[id*="product"]',
        '.product-image img',
        '[data-testid*="product"] img',
    ]
    
    for selector in img_selectors:
        try:
            imgs = page.locator(selector)
            for j in range(min(5, imgs.count())):
                src = imgs.nth(j).get_attribute('src')
                if src and not src.startswith('data:'):
                    full_url = urljoin(page.url, src)
                    if full_url not in images:
                        images.append(full_url)
        except:
            continue
    
    # If still no images, get large images from the page
    if not images:
        try:
            all_images = page.locator('img[src]')
            for i in range(min(10, all_images.count())):
                img = all_images.nth(i)
                src = img.get_attribute('src')
                if src and not src.startswith('data:'):
                    try:
                        dims = img.evaluate("el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})")
                        w = dims.get('w', 0)
                        h = dims.get('h', 0)
                        if w * h > 40000:  # Only large images (e.g., > 200x200)
                            full_url = urljoin(page.url, src)
                            if full_url not in images:
                                images.append(full_url)
                    except:
                        continue
        except:
            pass
    
    return images


def _extract_price_from_page(page: Page) -> tuple[Optional[str], Optional[str]]:
    """
    Extract price and currency from page using multiple methods.
    Returns (price, currency) tuple.
    """
    price = None
    currency = None
    
    # Try Schema.org markup
    try:
        schema_price = page.locator('[itemprop="price"]').first
        if schema_price.count() > 0:
            price_text = schema_price.get_attribute('content') or schema_price.inner_text()
            price = price_text.strip()
        
        schema_currency = page.locator('[itemprop="priceCurrency"]').first
        if schema_currency.count() > 0:
            currency = schema_currency.get_attribute('content') or schema_currency.inner_text()
    except:
        pass
    
    # Try common price selectors
    if not price:
        price_selectors = [
            '.price',
            '[class*="price"]',
            '[id*="price"]',
            '[data-testid*="price"]',
            '.product-price',
            '#product-price',
            '.product__price',
            '.money',
            '[class*="Money"]',
        ]
        
        for selector in price_selectors:
            try:
                elems = page.locator(selector)
                # Try first few matches
                for idx in range(min(3, elems.count())):
                    elem = elems.nth(idx)
                    price_text = elem.inner_text().strip()
                    
                    # Skip if it looks like a label
                    if price_text.lower() in ['price', 'sale price', 'regular price']:
                        continue
                    
                    # Try to extract price with regex
                    for pattern in PRICE_PATTERNS:
                        match = pattern.search(price_text)
                        if match:
                            price = match.group(1).replace(',', '')
                            # Try to detect currency from the text
                            for symbol, curr in CURRENCY_MAP.items():
                                if symbol in price_text:
                                    currency = curr if not currency else currency
                                    break
                            # Check for currency codes
                            if 'USD' in price_text or '$' in price_text:
                                currency = 'USD'
                            elif 'GBP' in price_text or '£' in price_text:
                                currency = 'GBP'
                            elif 'EUR' in price_text or '€' in price_text:
                                currency = 'EUR'
                            break
                    if price:
                        break
                if price:
                    break
            except:
                continue
    
    return price, currency


def _download_media(context: BrowserContext, url: str, filename: str, out_dir: str) -> Optional[str]:
    """
    Download media file from URL using Playwright's request API.
    This is adapted from the fb_ad_full_media_metadata_download.py logic.
    """
    try:
        resp = context.request.get(url)
        if not resp.ok:
            return None
        
        body = resp.body()
        ctype = (resp.headers.get("content-type") or "").lower()
        
        # Determine extension from content-type or URL
        ext = _guess_ext(url, ctype) or ".bin"
        fname = f"{filename}{ext}"
        
        out_path = os.path.join(out_dir, _safe_name(fname))
        with open(out_path, "wb") as f:
            f.write(body)
        
        return out_path
    except Exception as e:
        print(f"[Download Error] Failed to download {url}: {e}")
        return None


def _guess_ext(url: str, ctype: str) -> str:
    """Guess file extension from URL or content-type."""
    m = re.search(r"\.([a-z0-9]{2,4})(?:[\?#]|$)", url, re.I)
    if m:
        return "." + m.group(1).lower()
    if "mp4" in ctype:
        return ".mp4"
    if "webm" in ctype:
        return ".webm"
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    if "png" in ctype:
        return ".png"
    if "gif" in ctype:
        return ".gif"
    if "webp" in ctype:
        return ".webp"
    return ""


def _safe_name(name: str) -> str:
    """Sanitize filename by replacing unsafe characters."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name or "file")


def _extract_links(page: Page, base_url: str) -> List[str]:
    """Extract all links from the current page."""
    links = []
    try:
        anchors = page.locator('a[href]')
        for i in range(min(100, anchors.count())):  # Limit to 100 links per page
            try:
                href = anchors.nth(i).get_attribute('href')
                if href:
                    full_url = urljoin(base_url, href)
                    # Only keep links from the same domain
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        links.append(full_url)
            except:
                continue
    except Exception:
        pass
    
    return list(set(links))  # Remove duplicates


def crawl_website(
    start_url: str,
    out_dir: str,
    max_pages: int = 20,
    download_media: bool = True,
    headless: bool = True
) -> List[PageData]:
    """
    Crawl website starting from start_url.
    
    Args:
        start_url: Starting URL to crawl
        out_dir: Output directory for data and media
        max_pages: Maximum number of pages to crawl
        download_media: Whether to download product images
        headless: Run browser in headless mode
    
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
        to_visit: List[str] = [start_url]
        results: List[PageData] = []
        
        base_domain = urlparse(start_url).netloc
        
        while to_visit and len(visited_urls) < max_pages:
            current_url = to_visit.pop(0)
            
            # Skip if already visited
            if current_url in visited_urls:
                continue
            
            # Skip non-http(s) URLs
            if not current_url.startswith(('http://', 'https://')):
                continue
            
            # Skip if different domain
            if urlparse(current_url).netloc != base_domain:
                continue
            
            print(f"\n[Crawling] {current_url}")
            visited_urls.add(current_url)
            
            try:
                page.goto(current_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)  # Wait for dynamic content
                
                # Get page title
                page_title = page.title()
                
                # Check if it's a product page
                is_product = _is_product_page(page)
                print(f"[Detection] Product page: {is_product}")
                
                products = []
                
                if is_product:
                    # Extract product data (returns list of products)
                    extracted_products = _extract_product_data(page)
                    
                    for product in extracted_products:
                        # Check for duplicates by SKU
                        if product.sku and product.sku in seen_ids:
                            print(f"[Skip] Duplicate product: {product.product_name} (SKU: {product.sku})")
                            continue
                        
                        if product.is_bundle:
                            print(f"[Bundle] {product.bundle_name}")
                            print(f"[Bundle Price] {product.bundle_price} {product.currency}")
                            print(f"[Bundle Items] {len(product.bundle_items)} products")
                        else:
                            print(f"[Product] {product.product_name}")
                            print(f"[Price] {product.price} {product.currency}")
                            print(f"[SKU] {product.sku}")
                        
                        print(f"[Images] Found {len(product.images)} images")
                        
                        # Download media if requested
                        if download_media and product.images:
                            media_dir = os.path.join(out_dir, "media")
                            os.makedirs(media_dir, exist_ok=True)
                            
                            # Create a safe filename from product name/SKU or URL
                            if product.sku:
                                base_name = _safe_name(product.sku)
                            elif product.product_name:
                                base_name = _safe_name(product.product_name[:50])
                            else:
                                base_name = _safe_name(urlparse(current_url).path.split('/')[-1] or "product")
                            
                            downloaded = []
                            for idx, img_url in enumerate(product.images[:5], start=1):  # Limit to 5 images
                                filename = f"{base_name}_{idx}"
                                media_path = _download_media(context, img_url, filename, media_dir)
                                if media_path:
                                    downloaded.append(media_path)
                                    print(f"[Downloaded] {os.path.basename(media_path)}")
                            
                            product.media_files = downloaded
                        
                        # Mark as seen and add to products
                        if product.sku:
                            seen_ids.add(product.sku)
                        products.append(product)
                
                # Extract links for further crawling
                links = _extract_links(page, current_url)
                
                # Add new links to the queue
                for link in links:
                    if link not in visited_urls and link not in to_visit:
                        to_visit.append(link)
                
                # Create page data
                page_data = PageData(
                    url=current_url,
                    is_product_page=is_product,
                    page_title=page_title,
                    crawled_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    products=products,
                    links_found=links[:20],  # Limit stored links
                )
                
                results.append(page_data)
                
            except Exception as e:
                print(f"[Error] Failed to crawl {current_url}: {e}")
                continue
        
        browser.close()
        
        print(f"\n[Summary] Crawled {len(visited_urls)} pages")
        print(f"[Summary] Found {sum(1 for r in results if r.is_product_page)} product pages")
        
        return results


def save_results(results: List[PageData], out_dir: str) -> None:
    """Save crawl results to JSON file."""
    try:
        output_file = os.path.join(out_dir, "crawl_results.json")
        
        data = {
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pages": len(results),
            "product_pages": sum(1 for r in results if r.is_product_page),
            "pages": [asdict(r) for r in results]
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[Saved] Results saved to {output_file}")
        
        # Also save a summary of products only
        products_only = []
        for page in results:
            if page.is_product_page and page.products:
                for product in page.products:
                    products_only.append(asdict(product))
        
        if products_only:
            products_file = os.path.join(out_dir, "products.json")
            with open(products_file, "w", encoding="utf-8") as f:
                json.dump({
                    "total_products": len(products_only),
                    "products": products_only
                }, f, ensure_ascii=False, indent=2)
            print(f"[Saved] Products saved to {products_file}")
            
    except Exception as e:
        print(f"[Error] Failed to save results: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crawl website and detect/extract product pages"
    )
    parser.add_argument("url", help="Starting URL to crawl")
    parser.add_argument(
        "--out-dir",
        default="product_data",
        help="Output directory for data and media files"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum number of pages to crawl"
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Skip downloading product images"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode"
    )
    
    args = parser.parse_args()
    
    results = crawl_website(
        start_url=args.url,
        out_dir=args.out_dir,
        max_pages=args.max_pages,
        download_media=not args.no_download,
        headless=args.headless
    )
    
    save_results(results, args.out_dir)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

