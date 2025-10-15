"""
product_scraper_final_v2.py

Enhanced product scraping tool using Playwright that:
- Crawls website pages with URL normalization (no hash fragment duplicates)
- Detects product pages accurately
- Extracts product details (same extraction logic as V1)
- Downloads the main product image with product name as filename
- Converts WebP/JPG to PNG format
- Deduplicates products automatically
- Scrolls pages to load all content (lazy loading, infinite scroll)
- Detects "Buy Now" buttons and scrapes product pages in new tabs
- NEW: Detects buying options (quantities, subscriptions, variants, pricing tiers)

Key Enhancements:
- Page scrolling to ensure all products are detected
- Handles lazy-loaded content and infinite scroll
- Waits for dynamic content to load
- Auto-detects "Buy" buttons on catalog pages
- Opens product pages in new tabs, scrapes, then closes them
- Continues from where it left off after scraping buy button pages
- NEW: Comprehensive buying options detection

Usage:
  python scrapper/product_scraper_final_v2.py "https://example.com" \
    --out-dir product_data \
    --max-pages 20 \
    --headless \
    --buying-options
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Set
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.sync_api import sync_playwright, Page, BrowserContext


def normalize_url(url: str) -> str:
    """
    Normalize URL by removing fragments (hash) and trailing slashes.
    This prevents treating the same page with different hash fragments as different pages.
    
    Example:
        https://example.com/page#section1 -> https://example.com/page
        https://example.com/page#section2 -> https://example.com/page
    """
    parsed = urlparse(url)
    # Remove fragment and rebuild URL
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
class BuyingOption:
    """Represents a buying option for a product."""
    option_type: str  # "quantity", "subscription", "variant", "pricing_tier"
    original_price: Optional[str]  # Higher price (before discount)
    updated_price: Optional[str]   # Lower price (after discount)
    currency: Optional[str]
    value: Optional[str]  # The actual value (1, 3, 6 for quantities)
    unit: Optional[str]  # "bottles", "months", "mg", etc.
    is_default: bool = False
    is_available: bool = True
    raw_data: Optional[Dict] = None


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
    buying_options: List[BuyingOption]  # NEW: Buying options
    raw_data: Dict  # Additional structured data if available


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


def _accept_cookies(page: Page, verbose: bool = False) -> None:
    """
    Accept cookies by clicking common cookie banner buttons.
    This prevents cookie banners from interfering with product detection.
    """
    try:
        if verbose:
            print(f"[Cookies] Looking for cookie banner to accept...")
        
        # Common cookie acceptance button selectors
        cookie_selectors = [
            'button:has-text("Accept")',
            'button:has-text("Accept All")',
            'button:has-text("Accept Cookies")',
            'button:has-text("Accept All Cookies")',
            'button:has-text("I Accept")',
            'button:has-text("Agree")',
            'button:has-text("OK")',
            'button:has-text("Allow")',
            'button:has-text("Allow All")',
            'button:has-text("Yes")',
            'button:has-text("Continue")',
            '[data-testid*="accept"]',
            '[data-testid*="cookie"]',
            '[class*="accept"]',
            '[class*="cookie-accept"]',
            '[id*="accept"]',
            '[id*="cookie-accept"]',
            '.cookie-accept',
            '.accept-cookies',
            '.btn-accept',
            '.cookie-banner button',
            '.cookie-notice button',
            '.gdpr-banner button',
            '#cookie-accept',
            '#accept-cookies',
            '[onclick*="accept"]',
            '[onclick*="cookie"]',
        ]
        
        # Try to find and click cookie acceptance button
        for selector in cookie_selectors:
            try:
                button = page.locator(selector).first
                if button.count() > 0:
                    # Check if button is visible and clickable
                    if button.is_visible():
                        button.click()
                        if verbose:
                            print(f"[Cookies] ✓ Accepted cookies using selector: {selector}")
                        # Wait a moment for banner to disappear
                        page.wait_for_timeout(1000)
                        return
            except:
                continue
        
        # Also try to find by text content in buttons
        button_texts = [
            "Accept", "Accept All", "Accept Cookies", "I Accept", 
            "Agree", "OK", "Allow", "Allow All", "Yes", "Continue"
        ]
        
        for text in button_texts:
            try:
                button = page.locator(f'button:has-text("{text}")').first
                if button.count() > 0 and button.is_visible():
                    button.click()
                    if verbose:
                        print(f"[Cookies] ✓ Accepted cookies using text: {text}")
                    page.wait_for_timeout(1000)
                    return
            except:
                continue
        
        if verbose:
            print(f"[Cookies] No cookie banner found or already accepted")
            
    except Exception as e:
        if verbose:
            print(f"[Cookies] Error handling cookies: {e}")


def _scroll_page_to_load_content(page: Page, verbose: bool = False) -> None:
    """
    Scroll the page to load all content, including lazy-loaded images and infinite scroll.
    
    This ensures all products are detected, especially on pages with:
    - Lazy-loaded product grids
    - Infinite scroll
    - Dynamic content loading
    - Product carousels
    """
    try:
        if verbose:
            print(f"[Scroll] Starting page scroll to load all content...")
        
        # Get initial page height
        initial_height = page.evaluate("document.body.scrollHeight")
        if verbose:
            print(f"[Scroll] Initial page height: {initial_height}px")
        
        # Scroll to bottom in increments
        scroll_step = 1000  # pixels
        current_scroll = 0
        scroll_attempts = 0
        max_scroll_attempts = 50  # Prevent infinite scrolling
        no_change_count = 0
        max_no_change = 3  # Stop if height doesn't change for 3 attempts
        
        while scroll_attempts < max_scroll_attempts:
            # Scroll down by step
            current_scroll += scroll_step
            page.evaluate(f"window.scrollTo(0, {current_scroll})")
            
            # Wait for content to load
            page.wait_for_timeout(1000)  # Wait 1 second for lazy loading
            
            # Check new page height
            new_height = page.evaluate("document.body.scrollHeight")
            
            if verbose and scroll_attempts % 5 == 0:
                print(f"[Scroll] Attempt {scroll_attempts}: Scrolled to {current_scroll}px, height: {new_height}px")
            
            # If we've reached the bottom or height hasn't changed
            if current_scroll >= new_height - 1000:  # 1000px buffer
                if verbose:
                    print(f"[Scroll] Reached bottom of page")
                break
            
            # Check if height increased (new content loaded)
            if new_height > initial_height:
                initial_height = new_height
                no_change_count = 0
            else:
                no_change_count += 1
                
            # If height hasn't changed for several attempts, stop
            if no_change_count >= max_no_change:
                if verbose:
                    print(f"[Scroll] No new content loaded, stopping scroll")
                break
            
            scroll_attempts += 1
        
        # Scroll back to top
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)  # Brief pause
        
        final_height = page.evaluate("document.body.scrollHeight")
        if verbose:
            print(f"[Scroll] Scroll complete. Final page height: {final_height}px")
            
        # Additional wait for any remaining lazy-loaded images
        page.wait_for_timeout(2000)
        
    except Exception as e:
        if verbose:
            print(f"[Scroll Error] Failed to scroll page: {e}")


def _is_product_page(page: Page, verbose: bool = False) -> bool:
    """
    Detect if a page is a product page using multiple heuristics:
    1. Schema.org Product markup
    2. OpenGraph product metadata
    3. Product-related patterns in URL
    4. Common e-commerce page structures
    
    Important: Must be STRICT to avoid false positives (home pages, shop pages, etc.)
    """
    try:
        # Get URL for filtering
        url = page.url.lower()
        
        if verbose:
            print(f"[Product Detection] Checking URL: {url}")
        
        # EXCLUSION FILTERS: These are NOT product pages
        exclusion_patterns = [
            '/shop',
            '/category',
            '/categories',
            '/collection',
            '/collections',
            '/search',
            '?__geom=',  # Country selector parameters
            '/en-us',    # US store
            '/en-au',    # Australian store
            '/en-ca',    # Canadian store
            '/en-ie',    # Irish store
            '/en-eu',    # EU store
            '/en-nz',    # New Zealand store
            '/de-de',    # German store
            '/fr-fr',    # French store
            '/es-es',    # Spanish store
            '/it-it',    # Italian store
            '/cart',
            '/checkout',
            '/account',
            '/login',
            '/register',
        ]
        
        # Exclude if URL matches exclusion patterns
        for pattern in exclusion_patterns:
            if pattern in url:
                if verbose:
                    print(f"[Product Detection] Excluded by pattern: {pattern}")
                return False
        
        # Exclude home pages (/, /index, /home, or ends with domain)
        path = url.split('?')[0]  # Remove query params
        if path.endswith('/') and path.count('/') <= 3:  # e.g., https://domain.com/
            return False
        if any(x in path for x in ['/index', '/home']):
            return False
        
        # Check for Schema.org Product
        schema_product = page.locator('[itemtype*="schema.org/Product"]').count() > 0
        if schema_product:
            return True
        
        # Check for JSON-LD Product schema (STRICT - must be exact @type match)
        json_ld = page.locator('script[type="application/ld+json"]')
        for i in range(json_ld.count()):
            try:
                content = json_ld.nth(i).inner_text()
                data = json.loads(content)
                
                # Check if it's a single product
                if isinstance(data, dict):
                    if data.get('@type') in ['Product', 'ProductModel']:
                        # Additional check: must have offers or price
                        if 'offers' in data or 'price' in data:
                            return True
                
                # Check if it's a list with products
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') in ['Product', 'ProductModel']:
                            # Additional check: must have offers or price
                            if 'offers' in item or 'price' in item:
                                return True
            except:
                continue
        
        # Check for OpenGraph product metadata
        og_type = page.locator('meta[property="og:type"]').first
        if og_type.count() > 0:
            og_content = og_type.get_attribute('content') or ''
            if og_content.lower() == 'product':  # Exact match only
                return True
        
        # Check URL patterns (STRICT - must have product ID or slug)
        product_url_patterns = [
            '/product/',
            '/products/',
            '/supplement/',     # Added for supplement sites
            '/supplements/',    # Added for supplement sites
            '/item/',
            '/p/',
            '/dp/',
        ]
        
        # URL must contain pattern AND have additional path segments (not just /products)
        for pattern in product_url_patterns:
            if pattern in url:
                # Check if there's content after the pattern (product ID/slug)
                parts = url.split(pattern)
                if len(parts) > 1 and parts[1].strip('/'):
                    if verbose:
                        print(f"[Product Detection] ✓ Matched URL pattern: {pattern}")
                    return True
        
        # Check for common product page elements (STRICT - need multiple indicators)
        buy_button = page.locator('button:has-text("Add to Cart"), button:has-text("Buy Now"), button:has-text("Add to Bag")').count() > 0
        price_element = page.locator('[class*="price"], [id*="price"], [data-testid*="price"]').count() > 0
        product_title = page.locator('h1[class*="product"], h1[itemprop="name"]').count() > 0
        
        # Need at least 2 out of 3 product indicators
        indicators = sum([buy_button, price_element, product_title])
        if indicators >= 2:
            return True
        
        return False
    except Exception:
        return False


def _parse_subscription_prices(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse subscription prices from text like:
    "1 pouch – Every 30 days\n\nSAVE 15%\n$47.34\n$40.24"
    
    Returns: (original_price, updated_price, currency)
    """
    try:
        # Split by newlines to get individual lines
        lines = text.split('\n')
        
        # Look for price patterns in the lines
        prices = []
        currency = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Look for price patterns with currency symbols
            price_matches = re.findall(r'[\$£€](\d+(?:\.\d{2})?)', line)
            if price_matches:
                prices.extend(price_matches)
                
                # Detect currency from the line
                if '$' in line and not currency:
                    currency = 'USD'
                elif '£' in line and not currency:
                    currency = 'GBP'
                elif '€' in line and not currency:
                    currency = 'EUR'
        
        # If we found exactly 2 prices, the first is original, second is updated
        if len(prices) >= 2:
            return prices[0], prices[1], currency
        elif len(prices) == 1:
            # Only one price found, use it as updated price
            return None, prices[0], currency
        else:
            return None, None, currency
            
    except Exception:
        return None, None, None


def _extract_buying_options(page: Page, verbose: bool = False) -> List[BuyingOption]:
    """
    Extract buying options from a product page.
    
    Looks for:
    - Quantity selectors (1, 3, 6 bottles)
    - Subscription options (one-time, monthly, etc.)
    - Product variants (size, flavor, etc.)
    - Pricing tiers
    """
    buying_options = []
    
    try:
        if verbose:
            print(f"[Buying Options] Extracting buying options...")
        
        # Strategy 1: Look for quantity selectors
        quantity_selectors = [
            'select[name*="quantity"]',
            'select[id*="quantity"]',
            '[class*="quantity"] select',
            '[class*="qty"] select',
            'select[data-quantity]',
            '.quantity-selector select',
            '.qty-selector select',
            # Radio buttons for quantities
            'input[type="radio"][name*="quantity"]',
            'input[type="radio"][id*="quantity"]',
            '[class*="quantity"] input[type="radio"]',
            '[class*="qty"] input[type="radio"]',
            # Button groups for quantities
            '[class*="quantity"] button',
            '[class*="qty"] button',
            '.quantity-option',
            '.qty-option',
        ]
        
        for selector in quantity_selectors:
            try:
                elements = page.locator(selector)
                count = elements.count()
                
                if count > 0:
                    if verbose:
                        print(f"[Buying Options] Found {count} quantity element(s) with selector: {selector}")
                    
                    # Handle select dropdowns
                    if 'select' in selector:
                        for i in range(count):
                            try:
                                select = elements.nth(i)
                                options = select.locator('option')
                                
                                for j in range(options.count()):
                                    option = options.nth(j)
                                    value = option.get_attribute('value')
                                    text = option.inner_text().strip()
                                    
                                    if value and text and value != '':
                                        # Try to extract price from the text
                                        price_match = re.search(r'[\$£€]?(\d+(?:\.\d{2})?)', text)
                                        price = price_match.group(1) if price_match else None
                                        
                                        # Try to extract quantity number
                                        qty_match = re.search(r'(\d+)', text)
                                        qty_value = qty_match.group(1) if qty_match else value
                                        
                                        buying_options.append(BuyingOption(
                                            option_type="quantity",
                                            original_price=price,
                                            updated_price=price,  # Same price for quantity options
                                            currency=None,  # Will be detected from page
                                            value=qty_value,
                                            unit="units",
                                            is_default=(j == 0),
                                            raw_data={"selector": selector, "value": value}
                                        ))
                            except:
                                continue
                    
                    # Handle radio buttons
                    elif 'radio' in selector:
                        for i in range(count):
                            try:
                                radio = elements.nth(i)
                                value = radio.get_attribute('value')
                                # Try to find associated label
                                label = page.locator(f'label[for="{radio.get_attribute("id")}"]').first
                                if label.count() == 0:
                                    # Try to find parent label
                                    label = radio.locator('xpath=ancestor::label').first
                                
                                text = label.inner_text().strip() if label.count() > 0 else value
                                
                                if value and text:
                                    # Try to extract price and quantity
                                    price_match = re.search(r'[\$£€]?(\d+(?:\.\d{2})?)', text)
                                    price = price_match.group(1) if price_match else None
                                    
                                    qty_match = re.search(r'(\d+)', text)
                                    qty_value = qty_match.group(1) if qty_match else value
                                    
                                    is_checked = radio.is_checked()
                                    
                                    buying_options.append(BuyingOption(
                                        option_type="quantity",
                                        original_price=price,
                                        updated_price=price,  # Same price for quantity options
                                        currency=None,
                                        value=qty_value,
                                        unit="units",
                                        is_default=is_checked,
                                        raw_data={"selector": selector, "value": value}
                                    ))
                            except:
                                continue
                    
                    # Handle button groups
                    elif 'button' in selector:
                        for i in range(count):
                            try:
                                button = elements.nth(i)
                                text = button.inner_text().strip()
                                value = button.get_attribute('data-value') or button.get_attribute('value') or text
                                
                                if text and value:
                                    # Try to extract price and quantity
                                    price_match = re.search(r'[\$£€]?(\d+(?:\.\d{2})?)', text)
                                    price = price_match.group(1) if price_match else None
                                    
                                    qty_match = re.search(r'(\d+)', text)
                                    qty_value = qty_match.group(1) if qty_match else value
                                    
                                    # Check if button is selected/active
                                    is_active = 'active' in (button.get_attribute('class') or '').lower()
                                    
                                    buying_options.append(BuyingOption(
                                        option_type="quantity",
                                        original_price=price,
                                        updated_price=price,  # Same price for quantity options
                                        currency=None,
                                        value=qty_value,
                                        unit="units",
                                        is_default=is_active,
                                        raw_data={"selector": selector, "value": value}
                                    ))
                            except:
                                continue
            except:
                continue
        
        # Strategy 2: Look for subscription options
        subscription_selectors = [
            'input[type="radio"][name*="subscription"]',
            'input[type="radio"][name*="recurring"]',
            '[class*="subscription"] input[type="radio"]',
            '[class*="recurring"] input[type="radio"]',
            '.subscription-option',
            '.recurring-option',
            'select[name*="subscription"]',
            'select[name*="recurring"]',
        ]
        
        for selector in subscription_selectors:
            try:
                elements = page.locator(selector)
                count = elements.count()
                
                if count > 0:
                    if verbose:
                        print(f"[Buying Options] Found {count} subscription element(s) with selector: {selector}")
                    
                    for i in range(count):
                        try:
                            element = elements.nth(i)
                            
                            if element.get_attribute('type') == 'radio':
                                value = element.get_attribute('value')
                                # Find associated label
                                label = page.locator(f'label[for="{element.get_attribute("id")}"]').first
                                if label.count() == 0:
                                    label = element.locator('xpath=ancestor::label').first
                                
                                text = label.inner_text().strip() if label.count() > 0 else value
                                is_checked = element.is_checked()
                                
                                if text and value:
                                    # Parse prices from subscription text
                                    original_price, updated_price, currency = _parse_subscription_prices(text)
                                    
                                    buying_options.append(BuyingOption(
                                        option_type="subscription",
                                        original_price=original_price,
                                        updated_price=updated_price,
                                        currency=currency,
                                        value=value,
                                        unit="subscription",
                                        is_default=is_checked,
                                        raw_data={"selector": selector, "value": value}
                                    ))
                        except:
                            continue
            except:
                continue
        
        # Strategy 3: Look for product variants (size, flavor, etc.)
        variant_selectors = [
            'select[name*="variant"]',
            'select[name*="option"]',
            '[class*="variant"] select',
            '[class*="option"] select',
            'input[type="radio"][name*="variant"]',
            'input[type="radio"][name*="option"]',
            '.variant-selector select',
            '.option-selector select',
            '.product-variant',
            '.variant-option',
        ]
        
        for selector in variant_selectors:
            try:
                elements = page.locator(selector)
                count = elements.count()
                
                if count > 0:
                    if verbose:
                        print(f"[Buying Options] Found {count} variant element(s) with selector: {selector}")
                    
                    # Handle select dropdowns for variants
                    if 'select' in selector:
                        for i in range(count):
                            try:
                                select = elements.nth(i)
                                options = select.locator('option')
                                
                                for j in range(options.count()):
                                    option = options.nth(j)
                                    value = option.get_attribute('value')
                                    text = option.inner_text().strip()
                                    
                                    if value and text and value != '':
                                        buying_options.append(BuyingOption(
                                            option_type="variant",
                                            original_price=None,
                                            updated_price=None,
                                            currency=None,
                                            value=value,
                                            unit="variant",
                                            is_default=(j == 0),
                                            raw_data={"selector": selector, "value": value}
                                        ))
                            except:
                                continue
            except:
                continue
        
        # Strategy 4: Look for pricing tiers or bundles
        pricing_tier_selectors = [
            '[class*="pricing-tier"]',
            '[class*="bundle-option"]',
            '[class*="package-option"]',
            '.pricing-option',
            '.bundle-selector',
            '.package-selector',
        ]
        
        for selector in pricing_tier_selectors:
            try:
                elements = page.locator(selector)
                count = elements.count()
                
                if count > 0:
                    if verbose:
                        print(f"[Buying Options] Found {count} pricing tier element(s) with selector: {selector}")
                    
                    for i in range(count):
                        try:
                            element = elements.nth(i)
                            text = element.inner_text().strip()
                            
                            if text:
                                # Try to extract price
                                price_match = re.search(r'[\$£€]?(\d+(?:\.\d{2})?)', text)
                                price = price_match.group(1) if price_match else None
                                
                                # Try to extract quantity
                                qty_match = re.search(r'(\d+)', text)
                                qty_value = qty_match.group(1) if qty_match else None
                                
                                buying_options.append(BuyingOption(
                                    option_type="pricing_tier",
                                    original_price=price,
                                    updated_price=price,  # Same price for pricing tiers
                                    currency=None,
                                    value=qty_value,
                                    unit="tier",
                                    is_default=False,
                                    raw_data={"selector": selector, "text": text}
                                ))
                        except:
                            continue
            except:
                continue
        
        if verbose:
            print(f"[Buying Options] Found {len(buying_options)} total buying option(s)")
            for option in buying_options:
                price_info = ""
                if option.original_price and option.updated_price:
                    if option.original_price == option.updated_price:
                        price_info = f" - ${option.updated_price}"
                    else:
                        price_info = f" - ${option.original_price} → ${option.updated_price}"
                elif option.updated_price:
                    price_info = f" - ${option.updated_price}"
                print(f"  - {option.option_type}: {option.value} {option.unit}{price_info}")
        
        return buying_options
        
    except Exception as e:
        if verbose:
            print(f"[Buying Options Error] Failed to extract buying options: {e}")
        return []


def _extract_product_data(page: Page, extract_buying_options: bool = True) -> ProductData:
    """Extract product information from a product page (using V1 extraction logic)."""
    product_name = None
    price = None
    currency = None
    description = None
    sku = None
    availability = None
    brand = None
    images = []
    raw_data = {}
    
    try:
        # Try to extract from Schema.org markup
        schema_name = page.locator('[itemprop="name"]').first
        if schema_name.count() > 0:
            product_name = schema_name.inner_text().strip()
        
        schema_price = page.locator('[itemprop="price"]').first
        if schema_price.count() > 0:
            price_text = schema_price.get_attribute('content') or schema_price.inner_text()
            price = price_text.strip()
        
        schema_currency = page.locator('[itemprop="priceCurrency"]').first
        if schema_currency.count() > 0:
            currency = schema_currency.get_attribute('content') or schema_currency.inner_text()
        
        schema_description = page.locator('[itemprop="description"]').first
        if schema_description.count() > 0:
            description = schema_description.inner_text().strip()[:500]  # Limit length
        
        schema_sku = page.locator('[itemprop="sku"]').first
        if schema_sku.count() > 0:
            sku = schema_sku.inner_text().strip()
        
        schema_brand = page.locator('[itemprop="brand"]').first
        if schema_brand.count() > 0:
            brand = schema_brand.inner_text().strip()
        
        schema_availability = page.locator('[itemprop="availability"]').first
        if schema_availability.count() > 0:
            availability = schema_availability.get_attribute('content') or schema_availability.inner_text()
        
        # Try JSON-LD
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
                        raw_data = {k: v for k, v in item.items() 
                                   if k not in ['review', 'reviews', 'aggregateRating', 'reviewCount']}
                        
                        if not product_name and 'name' in item:
                            product_name = item['name']
                        if not brand and 'brand' in item:
                            brand_obj = item['brand']
                            brand = brand_obj.get('name') if isinstance(brand_obj, dict) else str(brand_obj)
                        if not sku and 'sku' in item:
                            sku = item['sku']
                        if not description and 'description' in item:
                            description = item['description'][:500]
                        
                        # Extract offers data
                        if 'offers' in item:
                            offer = item['offers']
                            if isinstance(offer, dict):
                                if not price and 'price' in offer:
                                    price = str(offer['price'])
                                if not currency and 'priceCurrency' in offer:
                                    currency = offer['priceCurrency']
                                if not availability and 'availability' in offer:
                                    availability = offer['availability']
                        break
            except:
                continue
        
        # Fallback: Try to find product name from h1 or title
        if not product_name:
            h1 = page.locator('h1').first
            if h1.count() > 0:
                product_name = h1.inner_text().strip()
            else:
                product_name = page.title()
        
        # Fallback: Try to find price with common selectors
        if not price:
            price_selectors = [
                '[class*="price"]',
                '[id*="price"]',
                '[data-testid*="price"]',
                '.product-price',
                '#product-price',
            ]
            for selector in price_selectors:
                try:
                    elem = page.locator(selector).first
                    if elem.count() > 0:
                        price_text = elem.inner_text().strip()
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
                                break
                        if price:
                            break
                except:
                    continue
        
        # NEW SIMPLIFIED IMAGE EXTRACTION: Target the main product image
        # This targets the large image next to the product name (like the bottle image)
        main_image = _extract_main_product_image(page, verbose=False)
        if main_image:
            images = [main_image]
        
        # NEW: Extract buying options if enabled
        buying_options = []
        if extract_buying_options:
            buying_options = _extract_buying_options(page, verbose=False)
        
    except Exception as e:
        print(f"[Error] Failed to extract product data: {e}")
    
    return ProductData(
        page_url=page.url,
        product_name=product_name,
        price=price,
        currency=currency,
        description=description,
        sku=sku,
        availability=availability,
        brand=brand,
        images=images[:1],  # Only keep the main image
        media_files=[],
        buying_options=buying_options,  # NEW: Add buying options
        raw_data=raw_data,
    )


def _extract_main_product_image(page: Page, verbose: bool = False) -> Optional[str]:
    """
    Extract the main product image (large image next to product name).
    
    This targets the main product photo that would be "right-clicked and saved as"
    in the browser - typically the largest, most prominent product image.
    
    Smart matching: Try to find images that match the product variant (e.g., 720mg image for 720mg product).
    """
    try:
        # Get product name for smart matching
        product_name = None
        h1 = page.locator('h1').first
        if h1.count() > 0:
            product_name = h1.inner_text().strip().lower()
        
        # Strategy 1: Smart matching - look for images that match product variant
        if product_name:
            if verbose:
                print(f"[Debug] Looking for images matching product: {product_name}")
            all_images = page.locator('img[src]')
            
            # First pass: Look for exact variant matches
            for i in range(min(20, all_images.count())):
                try:
                    img = all_images.nth(i)
                    src = img.get_attribute('src')
                    if src and not src.startswith('data:'):
                        full_url = urljoin(page.url, src)
                        
                        # Check if image URL matches product variant
                        if '500mg' in product_name and '500mg' in full_url.lower():
                            dims = img.evaluate("el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})")
                            w = dims.get('w', 0)
                            h = dims.get('h', 0)
                            if w * h > 50000:  # Reasonably large
                                if verbose:
                                    print(f"[Debug] ✓ Found matching 500mg image: {full_url[:80]}")
                                return full_url
                        elif '720mg' in product_name and '720mg' in full_url.lower():
                            dims = img.evaluate("el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})")
                            w = dims.get('w', 0)
                            h = dims.get('h', 0)
                            if w * h > 50000:  # Reasonably large
                                if verbose:
                                    print(f"[Debug] ✓ Found matching 720mg image: {full_url[:80]}")
                                return full_url
                except:
                    continue
            
            if verbose:
                print(f"[Debug] No exact variant matches found, trying alternative approaches...")
        
        # Strategy 2: Look for product-specific containers first
        product_containers = [
            '.product-image',
            '.product-photo', 
            '.product-gallery',
            '.main-image',
            '.hero-image',
            '[class*="product"][class*="image"]',
            '[class*="main"][class*="image"]',
            '.product-single__photo',
            '.product__media',
            '[data-product-image]',
            # More specific product image selectors
            '.product-main-image',
            '.product-hero-image',
            '.product-primary-image',
            '.main-product-image',
            '[class*="product-main"]',
            '[class*="product-hero"]',
            '[class*="product-primary"]',
            '[class*="main-product"]',
        ]
        
        for container_selector in product_containers:
            try:
                container = page.locator(container_selector).first
                if container.count() > 0:
                    if verbose:
                        print(f"[Debug] Found container: {container_selector}")
                    imgs = container.locator('img[src]')
                    for j in range(min(5, imgs.count())):
                        img = imgs.nth(j)
                        src = img.get_attribute('src')
                        if src and not src.startswith('data:'):
                            # Get dimensions
                            dims = img.evaluate("el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})")
                            w = dims.get('w', 0)
                            h = dims.get('h', 0)
                            area = w * h
                            
                            if area > 50000:  # At least 223x223 pixels
                                full_url = urljoin(page.url, src)
                                if verbose:
                                    print(f"[Debug] ✓ Found image in container ({w}x{h}): {full_url[:80]}")
                                return full_url
            except:
                continue
        
        # Strategy 3: Find the largest image on the page (excluding obvious non-product images)
        if verbose:
            print(f"[Debug] Using size-based detection...")
        all_images = page.locator('img[src]')
        largest_image = None
        largest_area = 0
        
        for i in range(min(20, all_images.count())):
            try:
                img = all_images.nth(i)
                src = img.get_attribute('src')
                if src and not src.startswith('data:'):
                    full_url = urljoin(page.url, src)
                    
                    # Enhanced filtering - skip obvious non-product images
                    skip_patterns = [
                        'logo', 'icon', 'menu', 'header', 'footer', 'cart', 'search',
                        'badge', 'sticker', 'award', 'certificate', 'approval', 'seal',
                        'social', 'facebook', 'twitter', 'instagram', 'youtube',
                        'payment', 'visa', 'mastercard', 'paypal',
                        'trust', 'security', 'ssl', 'verified',
                        'flag', 'country', 'language', 'currency',
                        'star', 'rating', 'review', 'badge',
                        'nav', 'breadcrumb', 'back', 'close', 'x',
                        'loading', 'spinner', 'placeholder'
                    ]
                    
                    if any(skip in full_url.lower() for skip in skip_patterns):
                        if verbose:
                            print(f"[Debug] Skipped non-product image: {full_url[:60]}...")
                        continue
                    
                    # Get dimensions
                    dims = img.evaluate("el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})")
                    w = dims.get('w', 0)
                    h = dims.get('h', 0)
                    area = w * h
                    
                    # Skip very small images (likely icons/logos)
                    if area > 100000:  # At least 316x316 pixels
                        if area > largest_area:
                            largest_area = area
                            largest_image = full_url
                            if verbose:
                                print(f"[Debug] New largest candidate ({w}x{h}): {full_url[:60]}...")
            except:
                continue
        
        if largest_image:
            if verbose:
                print(f"[Debug] ✓ Selected largest image: {largest_image[:80]}")
            return largest_image
        
        # Strategy 4: Look for the main product image by page layout analysis
        if verbose:
            print(f"[Debug] Trying layout-based product image detection...")
        
        # Look for images that are likely to be the main product image
        # These are usually in the left column or main content area
        layout_selectors = [
            'main img',
            '[role="main"] img',
            '.main-content img',
            '.content img',
            '.left img',
            '.product-left img',
            '.product-main img',
            '.product-details img',
            'section img',
            '.product-section img',
        ]
        
        for layout_selector in layout_selectors:
            try:
                layout_imgs = page.locator(layout_selector)
                for i in range(min(5, layout_imgs.count())):
                    try:
                        img = layout_imgs.nth(i)
                        src = img.get_attribute('src')
                        if src and not src.startswith('data:'):
                            full_url = urljoin(page.url, src)
                            
                            # Skip obvious non-product images
                            if any(skip in full_url.lower() for skip in ['badge', 'sticker', 'award', 'logo', 'icon']):
                                continue
                            
                            # Get dimensions
                            dims = img.evaluate("el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})")
                            w = dims.get('w', 0)
                            h = dims.get('h', 0)
                            area = w * h
                            
                            # Look for reasonably large images
                            if area > 50000:  # At least 223x223 pixels
                                if verbose:
                                    print(f"[Debug] ✓ Found layout-based product image ({w}x{h}): {full_url[:60]}...")
                                return full_url
                    except:
                        continue
            except:
                continue
        
        # Strategy 5: Fallback - get any reasonably large image
        if verbose:
            print(f"[Debug] Fallback: getting any large image...")
        for i in range(min(10, all_images.count())):
            try:
                img = all_images.nth(i)
                src = img.get_attribute('src')
                if src and not src.startswith('data:'):
                    full_url = urljoin(page.url, src)
                    
                    # Skip obvious non-product images
                    if any(skip in full_url.lower() for skip in ['badge', 'sticker', 'award', 'logo', 'icon']):
                        continue
                    
                    dims = img.evaluate("el => ({w: el.naturalWidth || 0, h: el.naturalHeight || 0})")
                    w = dims.get('w', 0)
                    h = dims.get('h', 0)
                    
                    if w * h > 40000:  # At least 200x200 pixels
                        if verbose:
                            print(f"[Debug] ✓ Fallback image: {full_url[:80]}")
                        return full_url
            except:
                continue
        
        if verbose:
            print(f"[Debug] No suitable images found")
        return None
        
    except Exception as e:
        print(f"[Error] Failed to extract main product image: {e}")
        return None


def _take_product_screenshot(page: Page, filename: str, out_dir: str, verbose: bool = False) -> Optional[str]:
    """
    Take a screenshot of the product page and save it with the product name.
    This captures the entire product page like the browser screenshots shown.
    """
    try:
        media_dir = os.path.join(out_dir, "screenshots")
        os.makedirs(media_dir, exist_ok=True)
        
        # Create filename for screenshot
        screenshot_filename = f"{filename}.png"
        screenshot_path = os.path.join(media_dir, _safe_name(screenshot_filename))
        
        # Take full page screenshot
        page.screenshot(path=screenshot_path, full_page=True)
        
        if verbose:
            print(f"[Screenshot] Saved: {os.path.basename(screenshot_path)}")
        
        return screenshot_path
        
    except Exception as e:
        if verbose:
            print(f"[Screenshot Error] Failed to take screenshot: {e}")
        return None


def _download_media(context: BrowserContext, url: str, filename: str, out_dir: str) -> Optional[str]:
    """
    Download media file from URL using Playwright's request API.
    Converts WebP images to PNG format for better compatibility.
    """
    try:
        resp = context.request.get(url)
        if not resp.ok:
            return None
        
        body = resp.body()
        ctype = (resp.headers.get("content-type") or "").lower()
        
        # Always save as PNG for better compatibility
        # Determine original extension for conversion detection
        original_ext = _guess_ext(url, ctype) or ".bin"
        
        # Save as PNG regardless of original format
        fname = f"{filename}.png"
        out_path = os.path.join(out_dir, _safe_name(fname))
        
        # Check if we need to convert from WebP
        if "webp" in ctype or original_ext == ".webp":
            try:
                # Convert WebP to PNG using PIL
                from PIL import Image
                import io
                
                # Open WebP image from bytes
                webp_image = Image.open(io.BytesIO(body))
                
                # Convert to RGB if necessary (WebP can have transparency)
                if webp_image.mode in ('RGBA', 'LA', 'P'):
                    # Create a white background for transparency
                    background = Image.new('RGB', webp_image.size, (255, 255, 255))
                    if webp_image.mode == 'P':
                        webp_image = webp_image.convert('RGBA')
                    background.paste(webp_image, mask=webp_image.split()[-1] if webp_image.mode in ('RGBA', 'LA') else None)
                    webp_image = background
                elif webp_image.mode != 'RGB':
                    webp_image = webp_image.convert('RGB')
                
                # Save as PNG
                webp_image.save(out_path, 'PNG')
                print(f"[Converted] WebP → PNG: {os.path.basename(out_path)}")
                
            except ImportError:
                print(f"[Warning] PIL not available, saving WebP as-is. Install Pillow for conversion: pip install Pillow")
                # Fallback: save as WebP if conversion fails
                fname = f"{filename}.webp"
                out_path = os.path.join(out_dir, _safe_name(fname))
                with open(out_path, "wb") as f:
                    f.write(body)
            except Exception as e:
                print(f"[Warning] WebP conversion failed: {e}, saving as WebP")
                # Fallback: save as WebP if conversion fails
                fname = f"{filename}.webp"
                out_path = os.path.join(out_dir, _safe_name(fname))
                with open(out_path, "wb") as f:
                    f.write(body)
        else:
            # For non-WebP images, save directly as PNG
            try:
                # Try to convert any image format to PNG using PIL
                from PIL import Image
                import io
                
                # Open image from bytes
                img = Image.open(io.BytesIO(body))
                
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Save as PNG
                img.save(out_path, 'PNG')
                
            except ImportError:
                print(f"[Warning] PIL not available, saving as original format. Install Pillow for PNG conversion: pip install Pillow")
                # Fallback: save with original extension
                fname = f"{filename}{original_ext}"
                out_path = os.path.join(out_dir, _safe_name(fname))
                with open(out_path, "wb") as f:
                    f.write(body)
            except Exception as e:
                print(f"[Warning] Image conversion failed: {e}, saving as original format")
                # Fallback: save with original extension
                fname = f"{filename}{original_ext}"
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
    """Extract all links from the current page (normalized)."""
    links = []
    try:
        anchors = page.locator('a[href]')
        for i in range(min(100, anchors.count())):  # Limit to 100 links per page
            try:
                href = anchors.nth(i).get_attribute('href')
                if href:
                    full_url = urljoin(base_url, href)
                    # Normalize URL to remove hash fragments
                    normalized_url = normalize_url(full_url)
                    # Only keep links from the same domain
                    if urlparse(normalized_url).netloc == urlparse(base_url).netloc:
                        # FILTER: Skip country selector and regional URLs
                        # This prevents looping through different country stores
                        skip_patterns = [
                            '?__geom=',  # Country selector parameter
                            '/en-us',    # US store
                            '/en-au',    # Australian store
                            '/en-ca',    # Canadian store
                            '/en-ie',    # Irish store
                            '/en-eu',    # EU store
                            '/en-nz',    # New Zealand store
                            '/de-de',    # German store
                            '/fr-fr',    # French store
                            '/es-es',    # Spanish store
                            '/it-it',    # Italian store
                        ]
                        
                        # Skip if URL contains any regional patterns
                        if any(pattern in normalized_url.lower() for pattern in skip_patterns):
                            continue
                        
                        if normalized_url not in links:
                            links.append(normalized_url)
            except:
                continue
    except Exception:
        pass
    
    return links


def _detect_and_scrape_buy_buttons(
    page: Page,
    context: BrowserContext,
    out_dir: str,
    download_media: bool,
    visited_urls: Set[str],
    verbose: bool = True,
    take_screenshots: bool = True,
    accept_cookies: bool = True,
    extract_buying_options: bool = True
) -> List[ProductData]:
    """
    Detect "Buy Now" or "Buy" buttons on the current page, open them in new tabs,
    scrape the product pages, then close the tabs.
    
    This is useful for catalog/listing pages that have product cards with buy buttons.
    
    Returns:
        List of ProductData scraped from the buy button links
    """
    scraped_products = []
    
    try:
        # ENHANCED: Take a diagnostic screenshot to see the page state
        if verbose:
            try:
                screenshot_dir = os.path.join(out_dir, "diagnostics")
                os.makedirs(screenshot_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_url = _safe_name(page.url.split('/')[-1] or "homepage")
                diagnostic_path = os.path.join(screenshot_dir, f"buy_detection_{safe_url}_{timestamp}.png")
                page.screenshot(path=diagnostic_path, full_page=True)
                print(f"[Diagnostic] Screenshot saved: {os.path.basename(diagnostic_path)}")
            except:
                pass
        
        # Look for "Buy Now" or "Buy" buttons/links
        # ENHANCED: More comprehensive selectors
        buy_button_selectors = [
            # Text-based (case insensitive)
            'a:has-text("Buy Now")',
            'a:has-text("Buy now")',
            'a:has-text("buy now")',
            'a:has-text("BUY NOW")',
            'button:has-text("Buy Now")',
            'button:has-text("Buy now")',
            'button:has-text("buy now")',
            'a:has-text("Buy")',
            'button:has-text("Buy")',
            'a:has-text("buy")',
            'button:has-text("buy")',
            'a:has-text("Shop Now")',
            'a:has-text("shop now")',
            'button:has-text("Shop Now")',
            'a:has-text("View Product")',
            'a:has-text("Learn More")',
            # Class and data attributes
            '[data-action*="buy"]',
            '[class*="buy-button"]',
            '[class*="buy-btn"]',
            '[class*="shop-now"]',
            '[class*="shop-button"]',
            '[class*="product-link"]',
            '[data-testid*="buy"]',
            '[data-testid*="shop"]',
            # Product card links
            '.product-card a',
            '.product-item a',
            '[class*="product-card"] a',
            '[class*="product-item"] a',
        ]
        
        buy_links = []
        total_buttons_found = 0
        skipped_already_visited = 0
        skipped_different_domain = 0
        skipped_no_href = 0
        
        # Collect all buy button links
        for selector in buy_button_selectors:
            try:
                elements = page.locator(selector)
                count = elements.count()
                
                if count > 0:
                    total_buttons_found += count
                    if verbose:
                        print(f"[Buy Detection] '{selector}' → {count} element(s)")
                
                for i in range(min(count, 50)):  # Increased limit to 50 to catch more products
                    try:
                        element = elements.nth(i)
                        
                        # Get the href if it's a link
                        href = element.get_attribute('href')
                        
                        # If it's a button, try to find the closest parent link
                        if not href:
                            # Try multiple strategies to find the link
                            parent_link = element.locator('xpath=ancestor::a[@href]').first
                            if parent_link.count() > 0:
                                href = parent_link.get_attribute('href')
                            else:
                                # Try to find sibling link
                                sibling_link = element.locator('xpath=following-sibling::a[@href] | preceding-sibling::a[@href]').first
                                if sibling_link.count() > 0:
                                    href = sibling_link.get_attribute('href')
                                else:
                                    # Try to find any nearby link in the same container
                                    nearby_link = element.locator('xpath=ancestor::*[contains(@class, "product") or contains(@class, "card") or contains(@class, "item")]//a[@href]').first
                                    if nearby_link.count() > 0:
                                        href = nearby_link.get_attribute('href')
                        
                        if href:
                            full_url = urljoin(page.url, href)
                            normalized_url = normalize_url(full_url)
                            
                            # Check domain first
                            if urlparse(normalized_url).netloc != urlparse(page.url).netloc:
                                skipped_different_domain += 1
                                continue
                            
                            # Check if already visited
                            if normalized_url in visited_urls:
                                skipped_already_visited += 1
                                if verbose:
                                    print(f"[Buy Button] Already visited, skipping: {normalized_url}")
                                continue
                            
                            # Check if already in current buy_links list
                            if normalized_url in buy_links:
                                continue
                            
                            # Valid new link
                            buy_links.append(normalized_url)
                            if verbose:
                                print(f"[Buy Button] Found new product URL: {normalized_url}")
                        else:
                            skipped_no_href += 1
                    except:
                        continue
            except:
                continue
        
        print(f"\n[Buy Button Summary]")
        print(f"  Total clickable elements detected: {total_buttons_found}")
        print(f"  Unique product URLs to scrape: {len(buy_links)}")
        print(f"  Skipped - no href: {skipped_no_href}")
        print(f"  Skipped - different domain: {skipped_different_domain}")
        print(f"  Skipped - already visited: {skipped_already_visited}")
        
        # FALLBACK: If no buy buttons found, try to find product links in containers
        if not buy_links and total_buttons_found == 0:
            if verbose:
                print(f"[Buy Detection] No buy buttons found, trying fallback product link detection...")
            
            # Look for product containers and extract links from them
            product_container_selectors = [
                '[class*="product-card"]',
                '[class*="product-item"]',
                '[class*="product-tile"]',
                '[class*="product-box"]',
                '.product',
                '[data-product-id]',
                '[data-testid*="product"]',
            ]
            
            for container_selector in product_container_selectors:
                try:
                    containers = page.locator(container_selector)
                    container_count = containers.count()
                    
                    if container_count > 0:
                        if verbose:
                            print(f"[Buy Detection] Found {container_count} product container(s) with selector: {container_selector}")
                        
                        for j in range(min(container_count, 20)):
                            try:
                                container = containers.nth(j)
                                # Look for any link in this container
                                links = container.locator('a[href]')
                                link_count = links.count()
                                
                                for k in range(min(link_count, 3)):  # Max 3 links per container
                                    try:
                                        link = links.nth(k)
                                        href = link.get_attribute('href')
                                        
                                        if href:
                                            full_url = urljoin(page.url, href)
                                            normalized_url = normalize_url(full_url)
                                            
                                            # Check domain
                                            if urlparse(normalized_url).netloc != urlparse(page.url).netloc:
                                                continue
                                            
                                            # Check if already visited
                                            if normalized_url in visited_urls:
                                                continue
                                            
                                            # Check if already in current buy_links list
                                            if normalized_url in buy_links:
                                                continue
                                            
                                            # Add to buy_links
                                            buy_links.append(normalized_url)
                                            if verbose:
                                                print(f"[Buy Button] Fallback found product URL: {normalized_url}")
                                    except:
                                        continue
                            except:
                                continue
                except:
                    continue
        
        if buy_links:
            print(f"[Buy Buttons] Starting to scrape {len(buy_links)} product(s)...\n")
        else:
            print(f"[Buy Buttons] No new product URLs found to scrape\n")
        
        # Scrape each buy button link in a new tab
        for idx, buy_url in enumerate(buy_links, 1):
            try:
                if verbose:
                    print(f"\n[Buy Button {idx}/{len(buy_links)}] Opening: {buy_url}")
                
                # Mark as visited to prevent duplicate scraping
                visited_urls.add(buy_url)
                
                # Open new tab/page
                new_page = context.new_page()
                new_page.set_default_timeout(30000)
                
                try:
                    # Navigate to the product page
                    new_page.goto(buy_url, wait_until="domcontentloaded")
                    new_page.wait_for_timeout(2000)  # Wait for content
                    
                    # Accept cookies on the new page
                    if accept_cookies:
                        _accept_cookies(new_page, verbose=verbose)
                    
                    # Check if it's a product page
                    is_product = _is_product_page(new_page, verbose=verbose)
                    
                    if verbose:
                        print(f"[Buy Button] URL: {buy_url}")
                        print(f"[Buy Button] Product detection result: {is_product}")
                    
                    if is_product:
                        if verbose:
                            print(f"[Buy Button] Product page detected!")
                        
                        # Extract product data (including buying options if enabled)
                        product = _extract_product_data(new_page, extract_buying_options=extract_buying_options)
                        product.page_url = buy_url
                        
                        print(f"[Product] {product.product_name}")
                        print(f"[Price] {product.price} {product.currency or 'N/A'}")
                        if product.buying_options:
                            print(f"[Buying Options] Found {len(product.buying_options)} option(s)")
                            for option in product.buying_options[:3]:  # Show first 3
                                price_info = ""
                                if option.original_price and option.updated_price:
                                    if option.original_price == option.updated_price:
                                        price_info = f" - ${option.updated_price}"
                                    else:
                                        price_info = f" - ${option.original_price} → ${option.updated_price}"
                                elif option.updated_price:
                                    price_info = f" - ${option.updated_price}"
                                print(f"  - {option.option_type}: {option.value} {option.unit}{price_info}")
                        
                        # Take screenshot of the buy button product page
                        if take_screenshots and product.product_name:
                            safe_filename = _safe_name(product.product_name[:100])
                            screenshot_path = _take_product_screenshot(new_page, safe_filename, out_dir, verbose=verbose)
                            if screenshot_path:
                                print(f"[Screenshot] Buy button product page saved: {os.path.basename(screenshot_path)}")
                        
                        # Extract and download the main product image next to product name
                        if download_media and product.product_name:
                            media_dir = os.path.join(out_dir, "media")
                            os.makedirs(media_dir, exist_ok=True)
                            
                            # Create filename from product name
                            safe_filename = _safe_name(product.product_name[:100])
                            
                            # Extract the main product image (image next to product name)
                            if verbose:
                                print(f"[Buy Button] Extracting main product image...")
                            
                            main_image_url = _extract_main_product_image(new_page, verbose=verbose)
                            
                            if main_image_url:
                                # Update product images if extraction found something
                                if main_image_url not in product.images:
                                    product.images = [main_image_url]
                                
                                # Download the image
                                media_path = _download_media(context, main_image_url, safe_filename, media_dir)
                                if media_path:
                                    product.media_files = [media_path]
                                    print(f"[Downloaded] {os.path.basename(media_path)}")
                                else:
                                    if verbose:
                                        print(f"[Buy Button] Failed to download image")
                            else:
                                # Fallback: try to use images from product data extraction
                                if product.images:
                                    if verbose:
                                        print(f"[Buy Button] Using fallback image from product data")
                                    img_url = product.images[0]
                                    media_path = _download_media(context, img_url, safe_filename, media_dir)
                                    if media_path:
                                        product.media_files = [media_path]
                                        print(f"[Downloaded] {os.path.basename(media_path)}")
                                else:
                                    if verbose:
                                        print(f"[Buy Button] No images found for product")
                        
                        scraped_products.append(product)
                    else:
                        if verbose:
                            print(f"[Buy Button] Not a product page, skipping")
                
                finally:
                    # Always close the tab
                    new_page.close()
                    if verbose:
                        print(f"[Buy Button] Tab closed, continuing...")
                
            except Exception as e:
                if verbose:
                    print(f"[Buy Button Error] Failed to scrape {buy_url}: {e}")
                continue
        
        if scraped_products:
            print(f"[Buy Buttons] Successfully scraped {len(scraped_products)} product(s)")
        
    except Exception as e:
        if verbose:
            print(f"[Buy Button Detection Error] {e}")
    
    return scraped_products


def crawl_website(
    start_url: str,
    out_dir: str,
    max_pages: int = 20,
    download_media: bool = True,
    headless: bool = True,
    verbose: bool = True,
    scroll_enabled: bool = True,
    buy_button_scraping: bool = True,
    take_screenshots: bool = True,
    accept_cookies: bool = True,
    extract_buying_options: bool = True  # NEW: Enable buying options extraction
) -> List[PageData]:
    """
    Crawl website starting from start_url.
    
    Args:
        start_url: Starting URL to crawl
        out_dir: Output directory for data and media
        max_pages: Maximum number of pages to crawl
        download_media: Whether to download product images
        headless: Run browser in headless mode
        verbose: Show detailed output
        scroll_enabled: Whether to scroll pages to load all content
        buy_button_scraping: Whether to detect and scrape "Buy" buttons in new tabs
        take_screenshots: Whether to take screenshots of product pages
        accept_cookies: Whether to automatically accept cookie banners
        extract_buying_options: Whether to extract buying options (quantities, subscriptions, variants)
    
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
            
            # Normalize URL to prevent hash fragment duplicates
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
                page.wait_for_timeout(2000)  # Wait for dynamic content
                
                # NEW: Accept cookies first to avoid interference
                if accept_cookies:
                    _accept_cookies(page, verbose=verbose)
                
                # NEW: Scroll page to load all content
                if scroll_enabled:
                    _scroll_page_to_load_content(page, verbose=verbose)
                
                # DIAGNOSTIC: Take screenshot after page load to verify content
                if verbose:
                    try:
                        screenshot_dir = os.path.join(out_dir, "diagnostics")
                        os.makedirs(screenshot_dir, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        safe_url = _safe_name(normalized_url.split('/')[-1] or f"page_{len(visited_urls)}")
                        diagnostic_path = os.path.join(screenshot_dir, f"crawl_{len(visited_urls)}_{safe_url}_{timestamp}.png")
                        page.screenshot(path=diagnostic_path, full_page=True)
                        print(f"[Diagnostic] Page screenshot: {os.path.basename(diagnostic_path)}")
                    except:
                        pass
                
                # Get page title
                page_title = page.title()
                
                # Check if it's a product page
                is_product = _is_product_page(page, verbose=verbose)
                print(f"[Detection] Product page: {is_product}")
                
                products = []
                
                if is_product:
                    # Extract product data (including buying options if enabled)
                    product = _extract_product_data(page, extract_buying_options=extract_buying_options)
                    # Update URL to normalized version
                    product.page_url = normalized_url
                    
                    print(f"[Product] {product.product_name}")
                    print(f"[Price] {product.price} {product.currency or 'N/A'}")
                    print(f"[Images] Found {len(product.images)} main image(s)")
                    if product.buying_options:
                        print(f"[Buying Options] Found {len(product.buying_options)} option(s)")
                        for option in product.buying_options[:3]:  # Show first 3
                            price_info = ""
                            if option.original_price and option.updated_price:
                                if option.original_price == option.updated_price:
                                    price_info = f" - ${option.updated_price}"
                                else:
                                    price_info = f" - ${option.original_price} → ${option.updated_price}"
                            elif option.updated_price:
                                price_info = f" - ${option.updated_price}"
                            print(f"  - {option.option_type}: {option.value} {option.unit}{price_info}")
                    
                    # Take screenshot of the product page
                    if take_screenshots and product.product_name:
                        safe_filename = _safe_name(product.product_name[:100])
                        screenshot_path = _take_product_screenshot(page, safe_filename, out_dir, verbose=verbose)
                        if screenshot_path:
                            print(f"[Screenshot] Product page saved: {os.path.basename(screenshot_path)}")
                    
                    # Download media if requested
                    if download_media and product.images and product.product_name:
                        media_dir = os.path.join(out_dir, "media")
                        os.makedirs(media_dir, exist_ok=True)
                        
                        # Create filename from product name (like "Save image as" with product name)
                        product_name = product.product_name
                        # Clean the product name for filename
                        safe_filename = _safe_name(product_name[:100])  # Limit length
                        
                        # Download the main product image
                        downloaded = []
                        if product.images:
                            img_url = product.images[0]  # Get the main image
                            media_path = _download_media(context, img_url, safe_filename, media_dir)
                            if media_path:
                                downloaded.append(media_path)
                                print(f"[Downloaded] {os.path.basename(media_path)}")
                        
                        product.media_files = downloaded
                    
                    products.append(product)
                else:
                    # NEW: If not a product page, check for "Buy Now" or "Buy" buttons
                    # and scrape their target pages in new tabs
                    if buy_button_scraping:
                        buy_button_products = _detect_and_scrape_buy_buttons(
                            page=page,
                            context=context,
                            out_dir=out_dir,
                            download_media=download_media,
                            visited_urls=visited_urls,
                            verbose=verbose,
                            take_screenshots=take_screenshots,
                            accept_cookies=accept_cookies,
                            extract_buying_options=extract_buying_options  # NEW: Pass buying options flag
                        )
                        
                        if buy_button_products:
                            products.extend(buy_button_products)
                
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
                    links_found=links[:20],  # Limit stored links
                )
                
                results.append(page_data)
                
            except Exception as e:
                print(f"[Error] Failed to crawl {normalized_url}: {e}")
                continue
        
        browser.close()
        
        # Count total products (including buy button products)
        total_products = sum(len(r.products) for r in results)
        
        print(f"\n{'='*60}")
        print(f"[Summary] Crawl Complete")
        print(f"{'='*60}")
        print(f"  📄 Pages crawled: {len(visited_urls)}")
        print(f"  📦 Total products scraped: {total_products}")
        print(f"{'='*60}\n")
        
        return results


def save_results(results: List[PageData], out_dir: str) -> None:
    """Save crawl results to JSON file."""
    try:
        output_file = os.path.join(out_dir, "crawl_results.json")
        
        # Count all products (including buy button products)
        total_products_count = sum(len(r.products) for r in results)
        buy_button_count = sum(len(r.products) for r in results if not r.is_product_page and r.products)
        
        data = {
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pages": len(results),
            "product_pages": sum(1 for r in results if r.is_product_page),
            "total_products": total_products_count,
            "buy_button_products": buy_button_count,
            "pages": [asdict(r) for r in results]
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[Saved] Results saved to {output_file}")
        
        # Also save a summary of products only (deduplicated)
        # IMPORTANT: Include ALL products, not just from product pages
        products_only = []
        seen_urls = set()
        
        for page in results:
            # Check ALL pages for products (including buy button products)
            if page.products:
                for product in page.products:
                    normalized_url = normalize_url(product.page_url)
                    # Skip if we've already seen this product
                    if normalized_url in seen_urls:
                        continue
                    seen_urls.add(normalized_url)
                    
                    # Convert buying options to dict for JSON serialization
                    product_dict = asdict(product)
                    if hasattr(product, 'buying_options') and product.buying_options:
                        product_dict['buying_options'] = [
                            asdict(option) for option in product.buying_options
                        ]
                    
                    products_only.append(product_dict)
        
        if products_only:
            products_file = os.path.join(out_dir, "products.json")
            with open(products_file, "w", encoding="utf-8") as f:
                json.dump({
                    "total_products": len(products_only),
                    "products": products_only
                }, f, ensure_ascii=False, indent=2)
            print(f"[Saved] Products saved to {products_file}")
            print(f"[Info] Total unique products: {len(products_only)}")
            print(f"[Info] Including {buy_button_count} products from 'Buy' buttons")
            
            # Count products with buying options
            products_with_options = sum(1 for p in products_only if p.get('buying_options'))
            if products_with_options > 0:
                print(f"[Info] Products with buying options: {products_with_options}")
            
    except Exception as e:
        print(f"[Error] Failed to save results: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Product Scraper V2 - Enhanced with buying options detection"
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
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output"
    )
    parser.add_argument(
        "--no-scroll",
        action="store_true",
        help="Disable page scrolling (faster but may miss lazy-loaded content)"
    )
    parser.add_argument(
        "--no-buy-buttons",
        action="store_true",
        help="Disable automatic 'Buy Now' button detection and scraping"
    )
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Disable taking screenshots of product pages"
    )
    parser.add_argument(
        "--no-cookies",
        action="store_true",
        help="Disable automatic cookie acceptance"
    )
    parser.add_argument(
        "--buying-options",
        action="store_true",
        help="Enable detection of buying options (quantities, subscriptions, variants)"
    )
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"Product Scraper V2 - Enhanced with Buying Options Detection")
    print(f"{'='*60}")
    print(f"Features:")
    print(f"  ✓ URL normalization (no hash fragment duplicates)")
    print(f"  ✓ Targets main product image (like 'Save image as')")
    print(f"  ✓ Saves image with product name as filename")
    print(f"  ✓ Converts WebP/JPG to PNG format")
    print(f"  ✓ Page scrolling for lazy-loaded content")
    print(f"  ✓ Auto-detect 'Buy Now' buttons and scrape in new tabs")
    print(f"  ✓ Screenshots of product pages (named by product)")
    print(f"  ✓ Automatic cookie acceptance")
    print(f"  ✓ Automatic deduplication")
    print(f"  ✓ NEW: Buying options detection (quantities, subscriptions, variants)")
    print(f"  ✓ Clean, production-ready output")
    print(f"{'='*60}\n")
    
    results = crawl_website(
        start_url=args.url,
        out_dir=args.out_dir,
        max_pages=args.max_pages,
        download_media=not args.no_download,
        headless=args.headless,
        verbose=not args.quiet,
        scroll_enabled=not args.no_scroll,
        buy_button_scraping=not args.no_buy_buttons,
        take_screenshots=not args.no_screenshots,
        accept_cookies=not args.no_cookies,
        extract_buying_options=args.buying_options  # NEW: Enable buying options detection
    )
    
    save_results(results, args.out_dir)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())