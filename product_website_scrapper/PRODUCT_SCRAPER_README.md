# Product Scraper

A powerful Playwright-based web scraper that automatically detects product pages, extracts product information, and downloads product images from any e-commerce website.

## Features

✅ **Smart Product Detection** - Automatically identifies product pages using:
- Schema.org Product markup
- JSON-LD structured data
- OpenGraph metadata
- URL patterns
- Page structure analysis

✅ **Comprehensive Data Extraction**:
- Product name
- Price and currency
- SKU
- Brand
- Description
- Availability
- Product images

✅ **Image Download** - Downloads one product image per product, named after the product

✅ **Organized Output** - Results organized by page with separate product-only JSON

✅ **No Reviews** - Excludes all review and rating data from output

## Installation

### Prerequisites

```bash
# Install Python dependencies
pip install playwright

# Install Chromium browser
playwright install chromium
```

### Verify Installation

```bash
python scrapper/product_scraper.py --help
```

## Usage

### Basic Command

```bash
python scrapper/product_scraper.py "https://example.com/shop"
```

### With Options

```bash
python scrapper/product_scraper.py "https://example.com/shop" \
  --out-dir my_products \
  --max-pages 50 \
  --headless
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `url` | Starting URL to crawl (required) | - |
| `--out-dir` | Output directory for data and media | `product_data` |
| `--max-pages` | Maximum number of pages to crawl | `20` |
| `--no-download` | Skip downloading product images | `False` |
| `--headless` | Run browser in headless mode | `False` |

## Examples

### Example 1: Quick Test (5 pages, visible browser)

```bash
python scrapper/product_scraper.py "https://store.example.com" --max-pages 5
```

### Example 2: Full Crawl (headless, 100 pages)

```bash
python scrapper/product_scraper.py "https://store.example.com" \
  --max-pages 100 \
  --headless
```

### Example 3: Extract Data Only (no image downloads)

```bash
python scrapper/product_scraper.py "https://store.example.com" \
  --max-pages 30 \
  --no-download \
  --headless
```

## Output Structure

The scraper creates the following structure:

```
product_data/
├── crawl_results.json    # Complete crawl data organized by page
├── products.json         # Product-only summary
└── media/               # Downloaded product images
    ├── Product_Name_1.png
    ├── Product_Name_2.jpg
    └── ...
```

### crawl_results.json

Complete information about each crawled page:

```json
{
  "crawl_time": "2025-10-10 14:30:00",
  "total_pages": 25,
  "product_pages": 15,
  "pages": [
    {
      "url": "https://example.com/products/item-123",
      "is_product_page": true,
      "page_title": "Amazing Product - Store",
      "crawled_at": "2025-10-10 14:30:05",
      "products": [
        {
          "page_url": "https://example.com/products/item-123",
          "product_name": "Amazing Product",
          "price": "99.99",
          "currency": "USD",
          "description": "Product description...",
          "sku": "PROD-123",
          "availability": "InStock",
          "brand": "Brand Name",
          "images": ["https://..."],
          "media_files": ["product_data/media/Amazing_Product.jpg"],
          "raw_data": {
            "@context": "http://schema.org",
            "@type": "Product",
            "name": "Amazing Product",
            "sku": "PROD-123",
            "offers": {...}
          }
        }
      ],
      "links_found": [...]
    }
  ]
}
```

### products.json

Simplified product-only data:

```json
{
  "total_products": 15,
  "products": [
    {
      "page_url": "https://example.com/products/item-123",
      "product_name": "Amazing Product",
      "price": "99.99",
      "currency": "USD",
      "description": "Product description...",
      "sku": "PROD-123",
      "availability": "InStock",
      "brand": "Brand Name",
      "images": ["https://..."],
      "media_files": ["product_data/media/Amazing_Product.jpg"],
      "raw_data": {...}
    }
  ]
}
```

### Image Files

- **One image per product** downloaded to `media/` directory
- **Filename matches product name** (sanitized for filesystem)
- **Automatic extension detection** (.png, .jpg, .webp, etc.)

Example:
```
Organic_Vitamin_D3.png
Magnesium_Glycinate.jpg
pH_Hero.webp
```

## How It Works

### 1. Product Page Detection

The scraper uses multiple methods to identify product pages:

1. **Structured Data**: Looks for `@type: "Product"` in JSON-LD
2. **Schema.org**: Checks for `itemtype="schema.org/Product"`
3. **OpenGraph**: Examines `og:type` meta tags
4. **URL Patterns**: Identifies `/product/`, `/products/`, `/p/`, etc.
5. **Page Elements**: Detects "Add to Cart" buttons + price elements

### 2. Data Extraction Priority

1. **JSON-LD structured data** (most reliable)
2. **Schema.org microdata** (itemprop attributes)
3. **Common CSS selectors** (class/id patterns)
4. **Fallback heuristics** (h1 tags, page structure)

### 3. Image Handling

- Extracts all product images from structured data
- Downloads only the **first image**
- Names file after the **product name**
- Auto-detects file extension from content-type

### 4. Review Filtering

All review-related data is automatically excluded:
- `review` and `reviews` arrays
- `aggregateRating` objects
- `reviewCount` fields

## Tips & Best Practices

### Testing New Sites

1. **Start small**: Use `--max-pages 5` to test detection
2. **Visual debugging**: Run without `--headless` to see the browser
3. **Check output**: Verify `crawl_results.json` for accuracy

```bash
python scrapper/product_scraper.py "https://newsite.com" \
  --max-pages 5 \
  --no-download
```

### Production Crawling

1. **Use headless mode**: Faster and more efficient
2. **Increase max-pages**: Crawl more products
3. **Enable downloads**: Get product images

```bash
python scrapper/product_scraper.py "https://store.com" \
  --max-pages 100 \
  --headless
```

### Programmatic Usage

```python
from scrapper.product_scraper import crawl_website, save_results

# Run the scraper
results = crawl_website(
    start_url="https://example.com/shop",
    out_dir="my_data",
    max_pages=50,
    download_media=True,
    headless=True
)

# Save results
save_results(results, "my_data")

# Process results
for page in results:
    if page.is_product_page:
        for product in page.products:
            print(f"{product.product_name}: ${product.price}")
```

## Troubleshooting

### No Products Detected

**Possible causes:**
- Site uses heavy JavaScript (increase wait time)
- Site lacks structured data
- Product detection patterns don't match site structure

**Solutions:**
```bash
# Run without headless to inspect pages
python scrapper/product_scraper.py "https://site.com" --max-pages 3

# Check browser console for errors
# View page source for Schema.org or JSON-LD markup
```

### Images Not Downloading

**Possible causes:**
- Images require authentication
- Image URLs are dynamically generated
- Network issues

**Solutions:**
- Check if images load in browser
- Verify image URLs in `crawl_results.json`
- Check network connectivity

### Crawler Not Finding Pages

**Possible causes:**
- Links are dynamically loaded
- Site uses non-standard navigation
- Links point to external domains

**Solutions:**
- Increase wait time in code (line 453: `page.wait_for_timeout`)
- Manually provide product page URLs
- Adjust link extraction logic

## Output Fields Reference

### ProductData Fields

| Field | Type | Description |
|-------|------|-------------|
| `page_url` | string | URL of the product page |
| `product_name` | string | Product name/title |
| `price` | string | Product price (numeric string) |
| `currency` | string | Currency code (USD, GBP, EUR) |
| `description` | string | Product description (max 500 chars) |
| `sku` | string | Product SKU/ID |
| `availability` | string | Stock status (InStock, OutOfStock) |
| `brand` | string | Brand name |
| `images` | array | List of image URLs |
| `media_files` | array | Downloaded image file paths |
| `raw_data` | object | Full structured data (no reviews) |

### PageData Fields

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Page URL |
| `is_product_page` | boolean | Whether page is a product page |
| `page_title` | string | Page title |
| `crawled_at` | string | Timestamp of crawl |
| `products` | array | List of ProductData objects |
| `links_found` | array | Links discovered on page |

## Advanced Usage

### Custom Processing

```python
import json
from scrapper.product_scraper import crawl_website

# Crawl site
results = crawl_website(
    start_url="https://example.com",
    out_dir="output",
    max_pages=50,
    download_media=False,
    headless=True
)

# Extract only products over $50
expensive_products = []
for page in results:
    for product in page.products:
        if product.price and float(product.price) > 50:
            expensive_products.append({
                'name': product.product_name,
                'price': product.price,
                'url': product.page_url
            })

# Save custom output
with open("expensive_products.json", "w") as f:
    json.dump(expensive_products, f, indent=2)
```

### Export to CSV

```python
import csv
from scrapper.product_scraper import crawl_website

results = crawl_website("https://example.com", "output", 30)

with open("products.csv", "w", newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['Name', 'Price', 'Currency', 'SKU', 'Brand', 'URL'])
    
    for page in results:
        for product in page.products:
            writer.writerow([
                product.product_name,
                product.price,
                product.currency,
                product.sku,
                product.brand,
                product.page_url
            ])
```

## Performance Notes

- **Crawl Speed**: ~2-3 seconds per page (with downloads)
- **Memory Usage**: Minimal (streaming approach)
- **Disk Space**: Depends on number of images (typically 50-200KB per image)
- **Network**: Respects same-domain restriction (no external sites)

## Limitations

- Only crawls pages within the same domain
- Respects 30-second timeout per page
- Maximum 100 links extracted per page
- Product images limited to 10 URLs (downloads only first one)
- Description limited to 500 characters