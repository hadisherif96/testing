# Product Scraper V2 - Enhanced with Buying Options Detection

A powerful web scraping tool built with Playwright that extracts product information from e-commerce websites, including comprehensive buying options detection (quantities, subscriptions, variants, and pricing tiers).

## 🚀 Features

### Core Functionality
- **URL Normalization**: Prevents hash fragment duplicates
- **Smart Product Detection**: Uses Schema.org, OpenGraph, and URL patterns
- **Main Product Image Extraction**: Targets the primary product image (like "Save image as")
- **Image Format Conversion**: Converts WebP/JPG to PNG for better compatibility
- **Automatic Deduplication**: Prevents duplicate product entries
- **Page Scrolling**: Loads lazy-loaded content and infinite scroll
- **Buy Button Detection**: Auto-detects "Buy Now" buttons and scrapes in new tabs
- **Screenshots**: Takes full-page screenshots of product pages
- **Cookie Acceptance**: Automatically handles cookie banners

### 🆕 NEW: Buying Options Detection
- **Quantity Options**: Detects quantity selectors (1, 3, 6 bottles, etc.)
- **Subscription Options**: Parses subscription plans with pricing
- **Product Variants**: Identifies size, flavor, and other variant options
- **Pricing Tiers**: Extracts bundle and package pricing
- **Price Parsing**: Separates original and discounted prices
- **Currency Detection**: Automatically detects USD, GBP, EUR

## 📦 Installation

### Prerequisites
```bash
pip install playwright pillow
playwright install chromium
```

### Dependencies
- `playwright`: Web scraping and browser automation
- `pillow`: Image format conversion
- `dataclasses`: Data structure management
- `json`: JSON serialization
- `re`: Regular expressions for pattern matching

## 🎯 Usage

### Basic Usage
```bash
python scrapper/product_scaper_final_v2.py "https://example.com"
```

### Full Featured Run
```bash
python scrapper/product_scaper_final_v2.py "https://example.com" \
  --out-dir product_data_v2 \
  --max-pages 20 \
  --headless \
  --buying-options
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `url` | Starting URL to crawl | Required |
| `--out-dir` | Output directory for data and media | `product_data` |
| `--max-pages` | Maximum number of pages to crawl | `20` |
| `--no-download` | Skip downloading product images | `False` |
| `--headless` | Run browser in headless mode | `False` |
| `--quiet` | Suppress verbose output | `False` |
| `--no-scroll` | Disable page scrolling | `False` |
| `--no-buy-buttons` | Disable buy button detection | `False` |
| `--no-screenshots` | Disable taking screenshots | `False` |
| `--no-cookies` | Disable automatic cookie acceptance | `False` |
| `--buying-options` | Enable buying options detection | `False` |

## 📊 Output Structure

### Directory Structure
```
product_data_v2/
├── crawl_results.json      # Complete crawl data
├── products.json          # Deduplicated products only
├── media/                 # Downloaded product images
├── screenshots/           # Product page screenshots
└── diagnostics/           # Debug screenshots
```

### Product Data Format
```json
{
  "page_url": "https://example.com/product",
  "product_name": "Omega-3 Supplement",
  "price": "29.99",
  "currency": "USD",
  "description": "High-quality omega-3 supplement...",
  "sku": "OMEGA-001",
  "availability": "InStock",
  "brand": "Example Brand",
  "images": ["https://example.com/image.png"],
  "media_files": ["product_data_v2/media/Omega-3_Supplement.png"],
  "buying_options": [
    {
      "option_type": "subscription",
      "original_price": "47.34",
      "updated_price": "40.24",
      "currency": "USD",
      "value": "710701875573",
      "unit": "subscription",
      "is_default": false,
      "is_available": true,
      "raw_data": {
        "selector": "[class*=\"subscription\"] input[type=\"radio\"]",
        "value": "710701875573"
      }
    }
  ],
  "raw_data": {
    "@context": "http://schema.org",
    "@type": "Product",
    "name": "Omega-3 Supplement"
  }
}
```

### Buying Options Types

#### 1. Subscription Options
```json
{
  "option_type": "subscription",
  "original_price": "47.34",
  "updated_price": "40.24",
  "currency": "USD",
  "value": "710701875573",
  "unit": "subscription"
}
```

#### 2. Quantity Options
```json
{
  "option_type": "quantity",
  "original_price": "29.99",
  "updated_price": "29.99",
  "currency": "USD",
  "value": "3",
  "unit": "units"
}
```

#### 3. Product Variants
```json
{
  "option_type": "variant",
  "original_price": null,
  "updated_price": null,
  "currency": null,
  "value": "500mg",
  "unit": "variant"
}
```

#### 4. Pricing Tiers
```json
{
  "option_type": "pricing_tier",
  "original_price": "99.99",
  "updated_price": "99.99",
  "currency": "USD",
  "value": "bundle",
  "unit": "tier"
}
```

## 🔍 Detection Strategies

### Product Page Detection
1. **Schema.org Product markup**
2. **OpenGraph product metadata**
3. **Product-related URL patterns** (`/product/`, `/products/`, `/supplement/`)
4. **Common e-commerce page elements** (buy buttons, prices, product titles)

### Buying Options Detection
1. **Quantity Selectors**: Dropdowns, radio buttons, button groups
2. **Subscription Options**: Radio buttons with subscription text
3. **Product Variants**: Select dropdowns for variants
4. **Pricing Tiers**: Bundle and package options

### Image Extraction
1. **Smart Matching**: Matches product variants (500mg, 720mg)
2. **Container-based**: Looks in product-specific containers
3. **Size-based**: Finds the largest suitable image
4. **Layout-based**: Analyzes page layout for main product image
5. **Fallback**: Gets any reasonably large image

## 🛠️ Advanced Configuration

### Customizing Selectors
The scraper uses comprehensive CSS selectors for different elements. You can modify these in the code:

```python
# Quantity selectors
quantity_selectors = [
    'select[name*="quantity"]',
    '[class*="quantity"] select',
    # Add your custom selectors here
]

# Subscription selectors
subscription_selectors = [
    'input[type="radio"][name*="subscription"]',
    '[class*="subscription"] input[type="radio"]',
    # Add your custom selectors here
]
```

### Price Pattern Customization
Modify the price detection patterns:

```python
PRICE_PATTERNS = [
    re.compile(r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', re.I),
    re.compile(r'£\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', re.I),
    # Add your custom patterns here
]
```

## 📈 Performance Tips

### Optimization
- Use `--headless` for faster execution
- Use `--no-scroll` if pages don't have lazy loading
- Use `--no-screenshots` to save disk space
- Use `--no-buy-options` if you don't need buying options

### Memory Management
- The scraper automatically limits image processing
- Screenshots are taken only when needed
- Media files are converted to PNG for consistency

## 🐛 Troubleshooting

### Common Issues

#### 1. No Products Found
- Check if the website uses JavaScript for product loading
- Enable `--buying-options` to find products via buy buttons
- Increase `--max-pages` to crawl more pages

#### 2. Images Not Downloading
- Check internet connection
- Verify the website allows image downloads
- Install Pillow: `pip install Pillow`

#### 3. Cookie Banners
- The scraper automatically handles most cookie banners
- If issues persist, check the cookie selectors in the code

#### 4. Buy Options Not Detected
- Enable verbose mode to see detection attempts
- Check the diagnostic screenshots in the `diagnostics/` folder
- Verify the website uses standard HTML patterns

### Debug Mode
Run with verbose output to see detailed detection information:

```bash
python scrapper/product_scaper_final_v2.py "https://example.com" --buying-options
```

## 📝 Example Output

### Terminal Output
```
============================================================
Product Scraper V2 - Enhanced with Buying Options Detection
============================================================
Features:
  ✓ URL normalization (no hash fragment duplicates)
  ✓ Targets main product image (like 'Save image as')
  ✓ Saves image with product name as filename
  ✓ Converts WebP/JPG to PNG format
  ✓ Page scrolling for lazy-loaded content
  ✓ Auto-detect 'Buy Now' buttons and scrape in new tabs
  ✓ Screenshots of product pages (named by product)
  ✓ Automatic cookie acceptance
  ✓ Automatic deduplication
  ✓ NEW: Buying options detection (quantities, subscriptions, variants)
  ✓ Clean, production-ready output
============================================================

[Crawling 1/20] https://example.com
[Product] Omega-3 Supplement
[Price] 29.99 USD
[Buying Options] Found 3 option(s)
  - subscription: 710701875573 subscription - $47.34 → $40.24
  - subscription: 710701908341 subscription - $59.51 → $49.14
  - subscription: 710701941109 subscription - $79.99 → $66.59

============================================================
[Summary] Crawl Complete
============================================================
  📄 Pages crawled: 20
  📦 Total products scraped: 17
============================================================
```

## 🤝 Contributing

### Adding New Detection Patterns
1. Identify the HTML structure of the new pattern
2. Add appropriate CSS selectors to the relevant arrays
3. Test with verbose mode to verify detection
4. Update this README with new patterns

### Extending Buying Options
1. Add new option types to the `BuyingOption` dataclass
2. Implement detection logic in `_extract_buying_options()`
3. Add parsing logic for the new option type
4. Update the verbose output formatting