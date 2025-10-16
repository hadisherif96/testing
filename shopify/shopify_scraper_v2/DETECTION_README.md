# Intelligent Product Scraper with Platform Detection

This scraper automatically detects whether a website is Shopify-based and uses the appropriate scraping strategy.

## Features

✅ **Automatic Platform Detection**
- Detects Shopify stores by checking for Shopify JS variables, API endpoints, and meta tags
- Displays "Platform: Shopify" or "Platform: Non-Shopify" after detection

✅ **Dual Scraping Modes**
- **Shopify Mode**: Fast JSON API scraper for Shopify stores
- **HTML Mode**: Universal HTML scraper for non-Shopify stores (using `product_scaper_final_v2.py`)

✅ **Smart Fallback**
- Automatically falls back to HTML scraper if site isn't Shopify
- Works with any e-commerce platform (WooCommerce, Magento, custom platforms, etc.)

## Usage

### Basic Usage

```bash
# Auto-detect platform and scrape
python shopify/shopify_detection_plus_scraper.py https://example.com --headless --max-pages 30
```

### With Custom Output Directory

```bash
python shopify/shopify_detection_plus_scraper.py https://vegetology.com \
  --headless \
  --max-pages 30 \
  --out-dir vegetology_data
```

### Force Shopify Mode (Skip Detection)

```bash
# If you know it's a Shopify store, skip detection for faster startup
python shopify/shopify_detection_plus_scraper.py https://drvegan.com \
  --force-shopify \
  --headless \
  --max-pages 30
```

### Interactive Mode

```bash
# Will prompt for URL
python shopify/shopify_detection_plus_scraper.py
```

## Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `url` | Starting URL to crawl (optional, will prompt if not provided) | - |
| `--out-dir` | Output directory for scraped data | `shopify_data` |
| `--max-pages` | Maximum number of pages to crawl | `20` |
| `--headless` | Run browser in headless mode (no UI) | `False` |
| `--quiet` | Suppress verbose output | `False` |
| `--force-shopify` | Skip detection, force Shopify scraper | `False` |

## How Platform Detection Works

The scraper checks for Shopify in this order:

1. **JavaScript Variables**: Looks for `window.Shopify`, `window.ShopifyAnalytics`
2. **Shopify Assets**: Checks for scripts/stylesheets from Shopify CDN
3. **API Endpoints**: Tests `/products.json` and `/collections.json`
4. **Meta Tags**: Searches for Shopify-specific meta tags and attributes

If any of these checks pass, the site is classified as Shopify.

## Example Output

### Shopify Store (e.g., drvegan.com)

```
============================================================
Intelligent Product Scraper with Platform Detection
============================================================
Target URL: https://drvegan.com
Max pages: 30
Output dir: shopify_data
Detecting platform...
[Shopify Detection] Found Shopify JS variables or assets
Platform: Shopify (detected)
============================================================

[Shopify Mode] Using fast JSON API scraper...

[Crawling 1/30] https://drvegan.com
[Detection] Product page: False
...
```

### Non-Shopify Store (e.g., vegetology.com)

```
============================================================
Intelligent Product Scraper with Platform Detection
============================================================
Target URL: https://vegetology.com
Max pages: 30
Output dir: vegetology_data
Detecting platform...
[Shopify Detection] No Shopify indicators found
Platform: Non-Shopify (detected)
============================================================
[Fallback] Using general-purpose HTML scraper

[HTML Mode] Using universal HTML scraper...
This scraper works with any e-commerce platform.

[Crawling 1/30] https://vegetology.com
[Detection] Product page: False
...
```

## Output Files

Both modes produce the same output structure:

- `crawl_results.json` - Full crawl data with all pages
- `products.json` - Deduplicated product data only

### Shopify Mode Output
- Uses Shopify JSON API for fast, reliable data extraction
- Includes full variant data, subscription options, pricing tiers
- Minimal page load times

### HTML Mode Output
- Parses HTML/JSON-LD for product information
- Includes product screenshots and images
- Works with any platform
- Automatic buy button detection

## Performance Comparison

| Store Type | Scraper Used | Speed | Reliability |
|------------|--------------|-------|-------------|
| Shopify | JSON API | ⚡ Fast | ✅ Excellent |
| Non-Shopify | HTML Parser | 🐢 Slower | ✅ Good |

## Troubleshooting

### False Positive (Non-Shopify detected as Shopify)

Use `--force-shopify` to skip detection if you're certain it's Shopify.

### Detection Fails

The script will automatically fall back to HTML mode if detection fails, ensuring products are still scraped.

### No Products Found

- For Shopify stores: Check if product URLs match `/products/{handle}` pattern
- For non-Shopify stores: The HTML scraper will detect products via multiple heuristics
