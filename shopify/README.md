# Shopify Product Scraper (JSON API Edition)

A clean, reliable Shopify product scraper that uses Shopify's built-in JSON API instead of HTML scraping.

## 🎯 Why This Approach?

Instead of scraping HTML with complex CSS selectors, this scraper leverages **Shopify's secret JSON endpoint**:

```
HTML Page: https://store.com/products/omega-3-supplement
JSON API:  https://store.com/products/omega-3-supplement.js
```

Every Shopify product page automatically has a `.js` endpoint that returns structured JSON data!

## ✨ Advantages Over HTML Scraping

| Feature | HTML Scraping | JSON API (This Tool) |
|---------|---------------|----------------------|
| **Reliability** | Breaks when HTML changes | ✅ Stable API format |
| **Complexity** | 2000+ lines of code | ✅ ~400 lines |
| **Maintenance** | CSS selectors need updates | ✅ Zero maintenance |
| **Data Quality** | Variable, needs fallbacks | ✅ Always complete |
| **Variants** | Hard to extract all | ✅ All variants included |
| **Subscription Pricing** | Difficult to detect | ✅ Built into API |
| **Speed** | Slower (DOM parsing) | ✅ Fast (JSON parsing) |

## 🚀 Installation

```bash
pip install playwright
playwright install chromium
```

## 📖 Usage

### Interactive Mode (No Arguments)

Simply run the scraper and it will prompt you for the URL:

```bash
python shopify/shopify_scraper_json.py
```

```
🚀 Shopify Product Scraper - JSON API Edition
============================================================
Enter Shopify store URL to crawl: drvegan.com
📝 Using URL: https://drvegan.com
```

**Note:** You can enter just the domain (e.g., `drvegan.com`) and it will automatically add `https://`

### Basic Usage (With URL)

```bash
python shopify/shopify_scraper_json.py "https://your-shopify-store.com"
```

### Advanced Options

```bash
python shopify/shopify_scraper_json.py "https://store.com" \
  --out-dir my_shopify_data \
  --max-pages 50 \
  --headless \
  --quiet
```

### Options

- `--out-dir` : Output directory for data files (default: `shopify_data`)
- `--max-pages` : Maximum pages to crawl (default: `20`)
- `--headless` : Run browser in headless mode
- `--quiet` : Suppress verbose output

## 📦 Output

The scraper creates two JSON files:

### 1. `crawl_results.json` - Complete crawl data
```json
{
  "crawl_time": "2025-10-16 11:30:00",
  "total_pages": 15,
  "product_pages": 8,
  "total_products": 8,
  "pages": [...]
}
```

### 2. `products.json` - Deduplicated products only
```json
{
  "total_products": 8,
  "products": [
    {
      "page_url": "https://store.com/products/omega-3",
      "product_id": 7234567890,
      "product_name": "Omega-3 Supplement",
      "handle": "omega-3",
      "description": "High-quality omega-3 from algae...",
      "available": true,
      "featured_image": "https://cdn.shopify.com/...",
      "variants": [
        {
          "id": 123456,
          "title": "500mg",
          "weight": 250,
          "buy_once_price": "49.99",
          "subscription_price": "42.49"
        },
        {
          "id": 123457,
          "title": "1000mg",
          "weight": 500,
          "buy_once_price": "79.99",
          "subscription_price": "67.99"
        }
      ]
    }
  ]
}
```

## 🔍 How It Works

### 1. **Crawling**
- Starts from the provided URL
- Extracts all links on each page
- Follows links within the same domain
- Normalizes URLs to prevent duplicates
- Respects `max_pages` limit

### 2. **Product Detection**
Simply checks if URL matches Shopify's product pattern:
```python
if '/products/' in url and has_product_handle:
    # It's a product page!
```

### 3. **Data Extraction**
For each product page:
1. Extract product handle from URL: `/products/omega-3` → `omega-3`
2. Call JSON API: `https://store.com/products/omega-3.js`
3. Parse structured JSON response
4. Extract all variants and pricing, including ALL subscription plan options per variant

### 4. **Pricing Logic**
Shopify stores prices as integers (cents/pence):
```python
# API returns: "price": 4999
# We convert to: "49.99"
buy_once_price = price / 100
```

Subscription pricing comes from `selling_plan_allocations` (and plan names/discounts from `selling_plan_groups`).
We output every subscription option per variant and also the lowest subscription price for convenience:
```python
# One-time (buy once): 49.99
# Subscription options (per frequency): [42.49, 42.49, 42.49, ...]
# Lowest subscription price exposed as `subscription_price`
```

## 🆚 Comparison with Previous Scraper

### Old Scraper (`product_scaper_final_v2.py`)
- ❌ 2099 lines of code
- ❌ Complex HTML parsing with 5 fallback strategies
- ❌ Multiple heuristics for product detection
- ❌ Breaks when websites redesign
- ❌ Works on any website (but unreliable)
- ❌ Needs images, screenshots, scrolling logic

### New Scraper (`shopify_scraper_json.py`)
- ✅ 489 lines of code
- ✅ Simple JSON parsing
- ✅ One detection method (URL pattern)
- ✅ Never breaks (uses stable API)
- ✅ **Shopify-only** (but 100% reliable)
- ✅ No images needed, pure data extraction

## 📊 What Data Is Extracted?

For each product:
- ✅ Product ID (Shopify internal ID)
- ✅ Product name
- ✅ Handle (URL slug)
- ✅ Full description (HTML tags removed)
- ✅ Availability status
- ✅ Featured image URL
- ✅ **All variants** with:
  - Variant ID
  - Variant title (e.g., "500mg", "Large", "Blue")
  - Weight/dimensions
  - Availability (per variant)
  - One-time purchase price
  - Compare-at price (when present)
  - Lowest subscription price (for quick use)
  - Subscription options array (all plans with name, discount, and price)

## 🎓 Example: Multi-Variant Product

For a product with multiple weights and subscription frequencies:

```json
{
  "product_name": "Protein & Creatine Superblend",
  "variants": [
    {
      "title": "900g",
      "weight": 900,
      "available": true,
      "buy_once_price": "50.99",
      "compare_at_price": "53.98",
      "subscription_price": "43.34",
      "subscription_options": [
        { "plan_name": "Every 30 days", "discount_percent": 15, "price": "43.34" },
        { "plan_name": "Every 60 days", "discount_percent": 15, "price": "43.34" },
        { "plan_name": "Delivery every 105 days", "discount_percent": 15, "price": "43.34" }
      ]
    }
  ]
}
```

## ⚠️ Limitations

### Only Works for Shopify Stores
This scraper is **Shopify-specific**. It will only work on stores powered by Shopify.

**To check if a store uses Shopify:**
1. View page source
2. Look for `/cdn.shopify.com/` in URLs
3. Or try accessing `/products/anything.js` - if it returns JSON, it's Shopify

### For Non-Shopify Stores
Use the general-purpose scraper in `scrapper/product_scaper_final_v2.py` instead.

## 🔧 Troubleshooting

### "Failed to fetch product JSON"
- The URL might not be a valid Shopify product page
- Try accessing the `.js` endpoint directly in your browser
- Some stores may have rate limiting

### "No products found"
- Make sure you're starting from a Shopify store URL
- Try starting from a specific product or collection page
- Increase `--max-pages` to crawl more pages

### "Could not extract product handle"
- The URL doesn't match Shopify's `/products/{handle}` pattern
- Make sure the URL contains `/products/` with a product slug

## 📚 Technical Details

### URL Normalization
Removes hash fragments to prevent duplicate visits:
```
https://store.com/products/item#review → https://store.com/products/item
https://store.com/products/item#specs  → https://store.com/products/item
```
(Treated as the same page)

### Deduplication
Products are deduplicated by `product_id` when saving to `products.json`.

### HTTP Headers
The scraper sends appropriate headers to the JSON API:
```python
{
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}
```

## 🚀 Future Enhancements

Possible improvements:
- [ ] Download product images
- [ ] Extract product reviews/ratings
- [ ] Support for product collections
- [ ] Export to CSV format
- [ ] Parallel/concurrent crawling
- [ ] Retry logic for failed requests

## 📝 License

This tool is for educational and research purposes. Always respect websites' `robots.txt` and terms of service.

## 🤝 Contributing

Found a bug or have a suggestion? Please open an issue!

---

**Note:** This scraper completely replaces the HTML-based product extraction logic with clean JSON API calls. No traces of the old HTML scraping methods remain.

