"""
universal_firecrawl.py

Universal e-commerce product scraper using Firecrawl.

Works with ANY e-commerce website (Shopify, WooCommerce, Magento, custom, etc.)

Key Features:
- Auto-detects if site is Shopify
- Universal product page detection
- Extracts: prices, title, main image
- Shopify-specific optimizations when detected
- Generic HTML parsing for non-Shopify sites
- Clean JSON output

Requirements:
- pip install firecrawl-py httpx beautifulsoup4

Usage:
  export FIRECRAWL_API_KEY=your_api_key
  python universal_firecrawl.py "https://any-ecommerce-store.com" \
    --out-dir scraped_data \
    --max-pages 20
"""

from __future__ import annotations

import argparse
import json
import os
import re
import html as html_module
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

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

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")
    raise


def normalize_url(url: str) -> str:
    """
    Normalize URL by removing fragments, tracking parameters, and trailing slashes.
    This prevents treating the same page with different parameters as different pages.
    """
    parsed = urlparse(url)
    
    # Remove common tracking/recommendation parameters
    if parsed.query:
        from urllib.parse import parse_qs, urlencode
        query_params = parse_qs(parsed.query)
        
        # List of tracking parameters to remove
        tracking_params = [
            'pr_prod_strat', 'pr_rec_id', 'pr_rec_pid', 'pr_ref_pid', 'pr_seq',  # Product recommendations
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',  # UTM tracking
            'fbclid', 'gclid', 'msclkid',  # Ad tracking
            '_ga', '_gid', '_gac',  # Google Analytics
            'mc_cid', 'mc_eid',  # MailChimp
            'pb',  # Various tracking
        ]
        
        # Keep only non-tracking parameters
        clean_params = {k: v for k, v in query_params.items() if k not in tracking_params}
        clean_query = urlencode(clean_params, doseq=True) if clean_params else ''
    else:
        clean_query = ''
    
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip('/') if parsed.path != '/' else parsed.path,
        parsed.params,
        clean_query,  # Use cleaned query
        ''  # Remove fragment
    ))
    return normalized


@dataclass
class ProductData:
    """Universal product data structure."""
    page_url: str
    product_name: str
    prices: List[str]  # All prices found
    buy_once_prices: List[str]  # Buy once/one-time purchase prices
    subscription_prices: List[str]  # Subscription/recurring prices
    main_price: Optional[str]  # Primary price
    compare_price: Optional[str]  # Original/compare price
    main_image: str
    description: str
    is_shopify: bool
    shopify_id: Optional[int] = None
    additional_images: List[str] = None
    
    def __post_init__(self):
        if self.additional_images is None:
            self.additional_images = []
        if self.buy_once_prices is None:
            self.buy_once_prices = []
        if self.subscription_prices is None:
            self.subscription_prices = []


@dataclass
class PageData:
    """Represents a crawled page."""
    url: str
    is_product_page: bool
    is_shopify_site: bool
    page_title: Optional[str]
    crawled_at: str
    products: List[ProductData]
    links_found: List[str]


def detect_shopify(url: str, html_content: str = None) -> Tuple[bool, str]:
    """
    Detect if a website is powered by Shopify.
    
    Returns:
        Tuple[bool, str]: (is_shopify, detection_method)
    """
    # Method 1: Check for Shopify-specific patterns in HTML
    if html_content:
        shopify_indicators = [
            'Shopify.theme',
            'cdn.shopify.com',
            'shopify-section',
            'myshopify.com',
            'Shopify.routes',
            'shopifycloud.com'
        ]
        
        for indicator in shopify_indicators:
            if indicator in html_content:
                return True, f"HTML pattern: {indicator}"
    
    # Method 2: Try to access Shopify JSON endpoint
    try:
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        test_url = f"{base_url}/products.json"
        
        with httpx.Client(timeout=5.0) as client:
            response = client.get(test_url)
            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict) and 'products' in data:
                        return True, "Shopify JSON API found"
                except:
                    pass
    except:
        pass
    
    # Method 3: Check domain
    if 'myshopify.com' in url:
        return True, "myshopify.com domain"
    
    return False, "Not detected"


def is_product_page(url: str, html_content: str, is_shopify: bool) -> Tuple[bool, str]:
    """
    Detect if a page is a product page (universal detection).
    
    Returns:
        Tuple[bool, str]: (is_product, detection_reason)
    """
    # Shopify-specific detection
    if is_shopify and '/products/' in url.lower():
        return True, "Shopify URL pattern"
    
    # Generic e-commerce patterns in URL
    product_url_patterns = [
        r'/product[s]?/[^/]+',
        r'/item[s]?/[^/]+',
        r'/p/[^/]+',
        r'/pd/[^/]+',
        r'-p-\d+',
        r'/shop/[^/]+/[^/]+',
    ]
    
    for pattern in product_url_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True, f"URL pattern: {pattern}"
    
    # Analyze HTML content
    if html_content:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Check for product schema markup (JSON-LD)
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    schema_type = data.get('@type', '')
                    if schema_type in ['Product', 'ProductModel']:
                        return True, "Schema.org Product markup"
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') in ['Product', 'ProductModel']:
                            return True, "Schema.org Product markup (list)"
            except:
                continue
        
        # Check for Open Graph product tags
        og_type = soup.find('meta', property='og:type')
        if og_type and 'product' in og_type.get('content', '').lower():
            return True, "Open Graph product type"
        
        # Check for common e-commerce elements
        product_indicators = [
            soup.find(class_=re.compile(r'add[-_]to[-_]cart', re.I)),
            soup.find(class_=re.compile(r'product[-_]price', re.I)),
            soup.find(class_=re.compile(r'buy[-_]now', re.I)),
            soup.find('button', string=re.compile(r'add to (cart|bag|basket)', re.I)),
            soup.find(class_=re.compile(r'product[-_]details', re.I)),
        ]
        
        if any(product_indicators):
            return True, "Product page elements found"
    
    return False, "Not detected"


def _extract_shopify_prices(url: str) -> Tuple[List[str], List[str]]:
    """
    Extract buy-once and subscription prices from Shopify JSON API.
    Returns (buy_once_prices, subscription_prices)
    """
    buy_once = []
    subscription = []
    
    try:
        # Extract handle from URL
        match = re.search(r'/products/([^/?#]+)', url)
        if not match:
            return buy_once, subscription
        
        handle = match.group(1)
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        json_url = f"{base_url}/products/{handle}.js"
        
        with httpx.Client(timeout=5.0) as client:
            response = client.get(json_url)
            if response.status_code != 200:
                return buy_once, subscription
            
            product_json = response.json()
            
            # Detect currency symbol (try to get from page or use common symbols)
            currency_symbol = "£"  # Default
            # Try to detect from first variant if available
            if product_json.get('variants'):
                # Most Shopify stores will have currency in presentment_prices
                # but we'll use a simple default approach
                pass
            
            # Extract buy-once prices from variants
            for variant in product_json.get('variants', []):
                price = variant.get('price', 0) / 100
                if price > 0:
                    price_str = f"{currency_symbol}{price:.2f}"
                    if price_str not in buy_once:
                        buy_once.append(price_str)
            
            # Extract subscription prices from selling plans
            for variant in product_json.get('variants', []):
                allocations = variant.get('selling_plan_allocations', [])
                for alloc in allocations:
                    sub_price = alloc.get('price', 0) / 100
                    if sub_price > 0:
                        price_str = f"{currency_symbol}{sub_price:.2f}"
                        if price_str not in subscription:
                            subscription.append(price_str)
    
    except Exception:
        pass
    
    return buy_once, subscription


def extract_product_from_html(url: str, html_content: str, is_shopify: bool) -> Optional[ProductData]:
    """
    Extract product data from HTML (universal method).
    Works for any e-commerce site.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # For Shopify sites, try to get accurate prices from JSON API first
    if is_shopify:
        shopify_buy_once, shopify_subscription = _extract_shopify_prices(url)
    else:
        shopify_buy_once, shopify_subscription = [], []
    
    # Extract product name/title
    product_name = None
    
    # Try schema.org JSON-LD first (most reliable)
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        try:
            data = json.loads(script.string)
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            for item in items:
                if isinstance(item, dict) and item.get('@type') in ['Product', 'ProductModel']:
                    product_name = item.get('name')
                    break
            if product_name:
                break
        except:
            continue
    
    # Fallback: Try common title patterns
    if not product_name:
        # Try og:title
        og_title = soup.find('meta', property='og:title')
        if og_title:
            product_name = og_title.get('content', '')
        
        # Try h1 with product class
        if not product_name:
            h1 = soup.find('h1', class_=re.compile(r'product', re.I))
            if h1:
                product_name = h1.get_text(strip=True)
        
        # Try any h1
        if not product_name:
            h1 = soup.find('h1')
            if h1:
                product_name = h1.get_text(strip=True)
        
        # Last resort: page title
        if not product_name:
            title_tag = soup.find('title')
            if title_tag:
                product_name = title_tag.get_text(strip=True).split('|')[0].strip()
    
    if not product_name:
        product_name = "Unknown Product"
    
    # Extract prices (separated by type)
    prices = []
    buy_once_prices = []
    subscription_prices = []
    main_price = None
    compare_price = None
    
    # Find all price elements
    price_patterns = [
        r'\$\s*\d+(?:[,.]\d{2})?',
        r'£\s*\d+(?:[,.]\d{2})?',
        r'€\s*\d+(?:[,.]\d{2})?',
        r'\d+(?:[,.]\d{2})?\s*(?:USD|GBP|EUR|CAD|AUD)',
    ]
    
    # Keywords to identify subscription prices
    subscription_keywords = [
        'subscribe', 'subscription', 'recurring', 'auto-delivery',
        'save', 'subscribe and save', 'auto ship', 'delivery',
        'frequency', 'monthly', 'weekly', 'every'
    ]
    
    # Keywords to identify buy-once prices
    buy_once_keywords = [
        'one-time', 'one time', 'buy once', 'single purchase',
        'no subscription', 'just once'
    ]
    
    # Check schema.org for prices
    for script in scripts:
        try:
            data = json.loads(script.string)
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            for item in items:
                if isinstance(item, dict) and item.get('@type') in ['Product', 'ProductModel']:
                    offers = item.get('offers', {})
                    if isinstance(offers, dict):
                        price = offers.get('price')
                        currency = offers.get('priceCurrency', '')
                        if price:
                            price_str = f"{currency} {price}".strip()
                            prices.append(price_str)
                            if not main_price:
                                main_price = price_str
                    elif isinstance(offers, list):
                        for offer in offers:
                            price = offer.get('price')
                            currency = offer.get('priceCurrency', '')
                            if price:
                                price_str = f"{currency} {price}".strip()
                                prices.append(price_str)
                                if not main_price:
                                    main_price = price_str
        except:
            continue
    
    # Find prices in HTML with context
    price_elements = soup.find_all(class_=re.compile(r'price', re.I))
    for elem in price_elements:
        text = elem.get_text(strip=True).lower()
        full_text = text
        
        # Get parent context for better classification
        parent = elem.parent
        if parent:
            parent_text = parent.get_text(strip=True).lower()
            full_text = parent_text
        
        # Determine if this is subscription or buy-once
        is_subscription = any(keyword in full_text for keyword in subscription_keywords)
        is_buy_once = any(keyword in full_text for keyword in buy_once_keywords)
        
        for pattern in price_patterns:
            matches = re.findall(pattern, elem.get_text(strip=True))
            for match in matches:
                if match not in prices:
                    prices.append(match)
                    
                    # Categorize price
                    if is_subscription and match not in subscription_prices:
                        subscription_prices.append(match)
                    elif is_buy_once and match not in buy_once_prices:
                        buy_once_prices.append(match)
                    elif not is_subscription and not is_buy_once:
                        # Default: if no clear indication, assume buy-once
                        if match not in buy_once_prices:
                            buy_once_prices.append(match)
                    
                    if not main_price:
                        main_price = match
    
    # Look for compare/original price
    compare_elements = soup.find_all(class_=re.compile(r'compare|original|was|regular', re.I))
    for elem in compare_elements:
        text = elem.get_text(strip=True)
        for pattern in price_patterns:
            matches = re.findall(pattern, text)
            if matches and not compare_price:
                compare_price = matches[0]
                break
    
    # Extract main image
    main_image = ""
    
    # Try og:image first
    og_image = soup.find('meta', property='og:image')
    if og_image:
        main_image = og_image.get('content', '')
    
    # Try schema.org image
    if not main_image:
        for script in scripts:
            try:
                data = json.loads(script.string)
                items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
                for item in items:
                    if isinstance(item, dict) and item.get('@type') in ['Product', 'ProductModel']:
                        img = item.get('image')
                        if img:
                            if isinstance(img, str):
                                main_image = img
                            elif isinstance(img, list) and img:
                                main_image = img[0] if isinstance(img[0], str) else img[0].get('url', '')
                            elif isinstance(img, dict):
                                main_image = img.get('url', '')
                            break
                if main_image:
                    break
            except:
                continue
    
    # Try product image classes
    if not main_image:
        img = soup.find('img', class_=re.compile(r'product[-_]image|main[-_]image|featured[-_]image', re.I))
        if img:
            main_image = img.get('src', '') or img.get('data-src', '')
    
    # Try any large image
    if not main_image:
        img = soup.find('img')
        if img:
            main_image = img.get('src', '') or img.get('data-src', '')
    
    # Make image URL absolute
    if main_image and not main_image.startswith('http'):
        main_image = urljoin(url, main_image)
    
    # Extract description
    description = ""
    desc_elem = soup.find(class_=re.compile(r'description|detail', re.I))
    if desc_elem:
        description = desc_elem.get_text(strip=True)[:500]  # Limit to 500 chars
    
    # Extract additional images
    additional_images = []
    img_gallery = soup.find_all('img', class_=re.compile(r'gallery|thumbnail|product', re.I))
    for img in img_gallery[:5]:  # Limit to 5 additional images
        img_src = img.get('src', '') or img.get('data-src', '')
        if img_src and img_src != main_image:
            if not img_src.startswith('http'):
                img_src = urljoin(url, img_src)
            additional_images.append(img_src)
    
    # Check for Shopify ID if it's a Shopify site
    shopify_id = None
    if is_shopify:
        # Try to extract from meta tags or scripts
        meta_product = soup.find('meta', {'name': 'shopify-product-id'})
        if meta_product:
            try:
                shopify_id = int(meta_product.get('content', 0))
            except:
                pass
    
    # Use Shopify API prices if available (more accurate), otherwise use HTML prices
    if is_shopify and (shopify_buy_once or shopify_subscription):
        final_buy_once = shopify_buy_once if shopify_buy_once else buy_once_prices
        final_subscription = shopify_subscription if shopify_subscription else subscription_prices
        # Combine all prices
        all_prices = final_buy_once + final_subscription
        if not main_price and all_prices:
            main_price = all_prices[0]
    else:
        final_buy_once = buy_once_prices
        final_subscription = subscription_prices
        all_prices = prices
    
    return ProductData(
        page_url=url,
        product_name=product_name,
        prices=all_prices if all_prices else prices,
        buy_once_prices=final_buy_once,
        subscription_prices=final_subscription,
        main_price=main_price,
        compare_price=compare_price,
        main_image=main_image,
        description=description,
        is_shopify=is_shopify,
        shopify_id=shopify_id,
        additional_images=additional_images
    )


def extract_links_from_html(html_content: str, base_url: str, verbose: bool = False) -> List[str]:
    """Extract all links from HTML content."""
    links = []
    
    # Debug counters
    debug_stats = {
        'total': 0,
        'no_href': 0,
        'anchor_only': 0,
        'javascript': 0,
        'external': 0,
        'skip_pattern': 0,
        'duplicate_base': 0,
        'duplicate': 0,
        'added': 0
    }
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        anchors = soup.find_all('a', href=True)
        debug_stats['total'] = len(anchors)
        
        if verbose:
            print(f"[Link Extraction] Found {len(anchors)} total anchor tags")
        
        # Sample first few hrefs for debugging
        sample_hrefs = []
        
        for anchor in anchors[:500]:  # Increased limit
            try:
                href = anchor.get('href')
                if not href:
                    debug_stats['no_href'] += 1
                    continue
                
                # Collect samples
                if len(sample_hrefs) < 10:
                    sample_hrefs.append(href)
                
                # Skip anchors and javascript links
                if href.startswith('#'):
                    debug_stats['anchor_only'] += 1
                    continue
                if href.startswith('javascript:'):
                    debug_stats['javascript'] += 1
                    continue
                
                full_url = urljoin(base_url, href)
                normalized_url = normalize_url(full_url)
                
                # Only keep links from the same domain
                if urlparse(normalized_url).netloc != urlparse(base_url).netloc:
                    debug_stats['external'] += 1
                    continue
                
                # Skip common non-product pages (less restrictive now)
                skip_patterns = [
                    '/cart', '/checkout', '/account/login', '/account/register',
                    '?__geom=', 'javascript:'
                ]
                
                # Skip if matches skip patterns
                if any(pattern in normalized_url.lower() for pattern in skip_patterns):
                    debug_stats['skip_pattern'] += 1
                    continue
                
                # Skip if URL is just the base domain (avoid duplicates)
                if normalized_url == normalize_url(base_url):
                    debug_stats['duplicate_base'] += 1
                    continue
                
                if normalized_url not in links:
                    links.append(normalized_url)
                    debug_stats['added'] += 1
                else:
                    debug_stats['duplicate'] += 1
                    
            except Exception as e:
                if verbose:
                    print(f"[Link Extraction Warning] Error processing link: {e}")
                continue
        
        # Print debug info if very few links found
        if verbose and len(links) < 10:
            print(f"[Link Debug] Filtering breakdown:")
            print(f"  Total anchors: {debug_stats['total']}")
            print(f"  No href: {debug_stats['no_href']}")
            print(f"  Anchor-only (#): {debug_stats['anchor_only']}")
            print(f"  JavaScript: {debug_stats['javascript']}")
            print(f"  External domain: {debug_stats['external']}")
            print(f"  Skip patterns: {debug_stats['skip_pattern']}")
            print(f"  Duplicate base URL: {debug_stats['duplicate_base']}")
            print(f"  Duplicates: {debug_stats['duplicate']}")
            print(f"  ✓ Added: {debug_stats['added']}")
            if sample_hrefs:
                print(f"[Link Debug] Sample hrefs found:")
                for href in sample_hrefs[:5]:
                    print(f"    {href}")
                
    except Exception as e:
        print(f"[Warning] Error extracting links: {e}")
    
    if verbose and len(links) < 5:
        print(f"[Link Extraction Warning] Only found {len(links)} unique links")
    
    return links


def crawl_ecommerce_site(
    start_url: str,
    out_dir: str,
    max_pages: int = 20,
    api_key: Optional[str] = None,
    verbose: bool = True,
    use_map: bool = False,
) -> List[PageData]:
    """
    Crawl any e-commerce site using Firecrawl.
    Auto-detects Shopify and extracts product data universally.
    """
    # Initialize Firecrawl
    firecrawl_key = api_key or os.getenv("FIRECRAWL_API_KEY")
    if not firecrawl_key:
        raise ValueError(
            "Firecrawl API key required. Set FIRECRAWL_API_KEY environment variable "
            "or pass api_key parameter."
        )
    
    try:
        firecrawl = Firecrawl(api_key=firecrawl_key)
    except Exception as e:
        raise ValueError(f"Failed to initialize Firecrawl: {e}")
    
    os.makedirs(out_dir, exist_ok=True)
    
    visited_urls: Set[str] = set()
    results: List[PageData] = []
    base_domain = urlparse(start_url).netloc
    
    # Use Firecrawl's map feature to discover all URLs first (if enabled)
    if use_map:
        try:
            if verbose:
                print(f"[Map] Discovering all URLs on site...")
            # Note: map() might not be available in all Firecrawl versions
            # This is an advanced feature
            to_visit = [normalize_url(start_url)]
            if verbose:
                print(f"[Map] Map feature not fully implemented, using standard crawl")
        except Exception as e:
            if verbose:
                print(f"[Map Warning] Could not use map feature: {e}")
            to_visit = [normalize_url(start_url)]
    else:
        to_visit = [normalize_url(start_url)]
    
    # Detect if site is Shopify (check once at start)
    site_is_shopify = False
    shopify_detection_method = "Not checked yet"
    
    print(f"\n{'='*60}")
    print(f"Universal E-Commerce Scraper")
    print(f"{'='*60}")
    print(f"Detecting platform...")
    
    # Try to discover collections/products pages automatically
    if not any(x in start_url.lower() for x in ['/collections/', '/products/', '/shop/', '/store/']):
        if verbose:
            print(f"[Discovery] Starting from homepage - will try to find collection pages...")
    
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
            # Scrape page with Firecrawl
            if verbose:
                print(f"[Firecrawl] Scraping page...")
            
            scrape_result = firecrawl.scrape(
                normalized_url,
                formats=['html', 'markdown']
            )
            
            # Extract HTML and metadata from Document object
            html_content = getattr(scrape_result, 'html', '') or ''
            metadata = getattr(scrape_result, 'metadata', {}) or {}
            page_title = metadata.get('title', '') if isinstance(metadata, dict) else ''
            
            if verbose:
                print(f"[Firecrawl] Page rendered successfully (HTML size: {len(html_content)} chars)")
                if len(html_content) < 5000:
                    print(f"[Firecrawl Warning] HTML seems very small - might be incomplete")
            
            # Detect Shopify on first page
            if len(visited_urls) == 1:
                site_is_shopify, shopify_detection_method = detect_shopify(normalized_url, html_content)
                print(f"[Platform] Shopify: {site_is_shopify} ({shopify_detection_method})")
            
            # Detect if this is a product page
            is_product, detection_reason = is_product_page(normalized_url, html_content, site_is_shopify)
            print(f"[Detection] Product page: {is_product} ({detection_reason})")
            
            products = []
            
            if is_product and html_content:
                # Extract product data
                product = extract_product_from_html(normalized_url, html_content, site_is_shopify)
                
                if product:
                    products.append(product)
                    
                    if verbose:
                        print(f"[Product] {product.product_name}")
                        if product.buy_once_prices:
                            print(f"[Buy Once Prices] {', '.join(product.buy_once_prices)}")
                        if product.subscription_prices:
                            print(f"[Subscription Prices] {', '.join(product.subscription_prices)}")
                        if product.compare_price:
                            print(f"[Compare Price] {product.compare_price}")
                        if product.main_image:
                            print(f"[Image] {product.main_image[:80]}...")
            
            # Extract links for further crawling
            links = extract_links_from_html(html_content, normalized_url, verbose=verbose)
            
            if verbose:
                print(f"[Links] Found {len(links)} unique links on page")
            
            # Add new links to the queue (prioritize collection/product pages)
            priority_links = []
            normal_links = []
            
            for link in links:
                normalized_link = normalize_url(link)
                if normalized_link not in visited_urls and normalized_link not in to_visit:
                    # Prioritize collection, products, shop pages
                    if any(pattern in normalized_link.lower() for pattern in ['/collections/', '/products/', '/shop/', '/category/', '/catalogue/']):
                        priority_links.append(normalized_link)
                    else:
                        normal_links.append(normalized_link)
            
            # Add priority links first, then normal links
            to_visit.extend(priority_links)
            to_visit.extend(normal_links)
            
            if verbose and priority_links:
                print(f"[Discovery] Found {len(priority_links)} collection/product pages to explore first")
            
            # Create page data
            page_data = PageData(
                url=normalized_url,
                is_product_page=is_product,
                is_shopify_site=site_is_shopify,
                page_title=page_title,
                crawled_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                products=products,
                links_found=links[:20],
            )
            
            results.append(page_data)
            
        except Exception as e:
            print(f"[Error] Failed to crawl {normalized_url}: {e}")
            if verbose:
                import traceback
                traceback.print_exc()
            continue
    
    total_products = sum(len(r.products) for r in results)
    product_pages = sum(1 for r in results if r.is_product_page)
    
    print(f"\n{'='*60}")
    print(f"[Summary] Crawl Complete")
    print(f"{'='*60}")
    print(f"  Platform: {'Shopify' if site_is_shopify else 'Generic E-Commerce'}")
    print(f"  Pages crawled: {len(visited_urls)}")
    print(f"  Product pages: {product_pages}")
    print(f"  Products scraped: {total_products}")
    print(f"{'='*60}\n")
    
    return results


def save_results(results: List[PageData], out_dir: str) -> None:
    """Save crawl results to JSON files."""
    try:
        output_file = os.path.join(out_dir, "crawl_results.json")
        
        total_products_count = sum(len(r.products) for r in results)
        
        data = {
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pages": len(results),
            "product_pages": sum(1 for r in results if r.is_product_page),
            "total_products": total_products_count,
            "is_shopify": results[0].is_shopify_site if results else False,
            "pages": [asdict(r) for r in results]
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[Saved] Results saved to {output_file}")
        
        # Save products summary (deduplicated by product name + main price)
        products_only = []
        seen_products = set()
        
        for page in results:
            if page.products:
                for product in page.products:
                    # Create unique key from product name and main price (handles variants better)
                    product_key = f"{product.product_name}|{product.main_price}"
                    
                    if product_key not in seen_products:
                        seen_products.add(product_key)
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
        description="Universal E-Commerce Scraper - Works with Shopify and ANY e-commerce site"
    )
    parser.add_argument(
        "url",
        nargs='?',
        help="Starting URL to crawl. If not provided, will prompt for input."
    )
    parser.add_argument(
        "--out-dir",
        default="scraped_data",
        help="Output directory for data files"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum number of pages to crawl"
    )
    parser.add_argument(
        "--api-key",
        help="Firecrawl API key (defaults to FIRECRAWL_API_KEY env var)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output"
    )
    parser.add_argument(
        "--use-map",
        action="store_true",
        help="Use Firecrawl's map feature to discover URLs (experimental)"
    )
    
    args = parser.parse_args()
    
    # Get URL from command line or prompt user
    url = args.url
    if not url:
        print("🌐 Universal E-Commerce Product Scraper")
        print("=" * 60)
        url = input("Enter e-commerce site URL to crawl: ").strip()
        
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
    print(f"Universal E-Commerce Product Scraper")
    print(f"{'='*60}")
    print(f"Target URL: {url}")
    print(f"Max pages: {args.max_pages}")
    print(f"Output dir: {args.out_dir}")
    print(f"{'='*60}")
    print(f"Features:")
    print(f"  [+] Auto-detects Shopify")
    print(f"  [+] Works with ANY e-commerce platform")
    print(f"  [+] Extracts: prices, title, main image")
    print(f"  [+] Universal product page detection")
    print(f"  [+] Clean JSON output")
    print(f"{'='*60}\n")
    
    try:
        results = crawl_ecommerce_site(
            start_url=url,
            out_dir=args.out_dir,
            max_pages=args.max_pages,
            api_key=args.api_key,
            verbose=not args.quiet,
            use_map=args.use_map,
        )
        
        save_results(results, args.out_dir)
        
        return 0
    
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\n⚠️  Crawl interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

