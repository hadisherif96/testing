# Product Scraper Final - Comprehensive Web Scraping Tool

A powerful, production-ready web scraping tool built with Playwright that automatically detects and scrapes product information from e-commerce websites. This tool is specifically designed to handle modern web applications with dynamic content, lazy loading, and complex layouts.

## 🚀 Features

### Core Functionality
- **Smart Product Detection**: Automatically identifies product pages using multiple heuristics
- **Comprehensive Data Extraction**: Extracts product name, price, currency, description, SKU, availability, brand, and images
- **Main Product Image Targeting**: Intelligently selects the primary product image (not logos/badges)
- **Buy Button Detection**: Finds and scrapes products from catalog/listing pages via "Buy Now" buttons
- **URL Normalization**: Prevents duplicate products from hash fragments and regional variations
- **Automatic Deduplication**: Ensures unique products in output

### Advanced Features
- **Page Scrolling**: Handles lazy-loaded content and infinite scroll
- **Cookie Acceptance**: Automatically handles cookie banners
- **Regional Store Filtering**: Stays focused on specific regional stores (e.g., UK only)
- **Diagnostic Screenshots**: Captures page states for debugging
- **Image Format Conversion**: Converts WebP/JPG to PNG for better compatibility
- **Full-Page Screenshots**: Saves product page screenshots with product names

### Robust Error Handling
- **Multiple Detection Strategies**: Falls back through various image detection methods
- **Comprehensive Logging**: Detailed debug output and progress tracking
- **Graceful Failures**: Continues scraping even if individual pages fail
- **Timeout Management**: Handles slow-loading pages and network issues

## 📋 Requirements

### System Requirements
- Python 3.8+
- Modern browser (Chromium-based)

### Python Dependencies
```bash
pip install playwright pillow
playwright install chromium
```

### Optional Dependencies
- **Pillow (PIL)**: For image format conversion (recommended)
- **Playwright**: For browser automation (required)

## 🛠 Installation

1. **Clone or download the scraper:**
   ```bash
   # Download the file to your project directory
   # scrapper/product_scraper_final.py
   ```

2. **Install dependencies:**
   ```bash
   pip install playwright pillow
   ```

3. **Install browser:**
   ```bash
   playwright install chromium
   ```

## 📖 Usage

### Basic Usage
```bash
python scrapper/product_scraper_final.py "https://example.com"
```

### Advanced Usage
```bash
python scrapper/product_scraper_final.py "https://www.vegetology.com" \
  --out-dir product_data \
  --max-pages 50 \
  --headless
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
| `--no-screenshots` | Disable product page screenshots | `False` |
| `--no-cookies` | Disable automatic cookie acceptance | `False` |

### Usage Examples

#### 1. Basic Product Scraping
```bash
python scrapper/product_scraper_final.py "https://www.vegetology.com"
```

#### 2. Large-Scale Scraping (Headless)
```bash
python scrapper/product_scraper_final.py "https://www.vegetology.com" \
  --max-pages 100 \
  --headless \
  --quiet
```

#### 3. Data-Only Scraping (No Images)
```bash
python scrapper/product_scraper_final.py "https://www.vegetology.com" \
  --no-download \
  --no-screenshots
```

#### 4. Fast Scraping (Minimal Features)
```bash
python scrapper/product_scraper_final.py "https://www.vegetology.com" \
  --no-scroll \
  --no-buy-buttons \
  --no-cookies \
  --headless
```

## 📁 Output Structure

```
product_data/
├── products.json                    # Main product data (clean format)
├── crawl_results.json              # Complete crawl data with metadata
├── media/                          # Downloaded product images (PNG)
│   ├── Vegan_Omega_3_Supplements.png
│   ├── MultiVit_Vegan_Supplements.png
│   └── ...
├── screenshots/                    # Product page screenshots
│   ├── Vegan_Omega_3_Supplements.png
│   ├── MultiVit_Vegan_Supplements.png
│   └── ...
└── diagnostics/                    # Debug screenshots (verbose mode)
    ├── crawl_1_homepage_20251012_203000.png
    ├── buy_detection_homepage_20251012_203000.png
    └── ...
```

## 📊 Output Formats

### Products JSON (`products.json`)
```json
{
  "total_products": 15,
  "products": [
    {
      "page_url": "https://www.vegetology.com/supplements/omega-3",
      "product_name": "Vegan Omega-3 Supplements",
      "price": "19.99",
      "currency": "GBP",
      "description": "Vegan High Strength Omega-3 EPA and DHA",
      "sku": "VEG-2358",
      "availability": "InStock",
      "brand": "Vegetology",
      "images": ["https://example.com/product-image.png"],
      "media_files": ["product_data/media/Vegan_Omega_3_Supplements.png"],
      "raw_data": { /* Structured data from JSON-LD */ }
    }
  ]
}
```

### Crawl Results JSON (`crawl_results.json`)
```json
{
  "crawl_time": "2025-10-12 20:37:41",
  "total_pages": 25,
  "product_pages": 5,
  "total_products": 15,
  "buy_button_products": 10,
  "pages": [ /* Detailed page data */ ]
}
```

## 🔧 How It Works

### 1. Product Page Detection
The scraper uses multiple strategies to identify product pages:

- **Schema.org Product markup** detection
- **JSON-LD structured data** parsing
- **OpenGraph product metadata** checking
- **URL pattern matching** (`/product/`, `/supplements/`, etc.)
- **Page element analysis** (buy buttons, prices, product titles)

### 2. Buy Button Detection
For catalog/listing pages, the scraper:

- **Detects "Buy Now" buttons** using multiple selectors
- **Extracts product URLs** from button links
- **Opens new browser tabs** for each product
- **Scrapes product data** from individual pages
- **Closes tabs** and continues

### 3. Image Extraction
The scraper intelligently selects the main product image:

- **Filters out logos/badges** using URL pattern matching
- **Uses size-based detection** to find large images
- **Analyzes page layout** to target main content area
- **Falls back through multiple strategies** if needed

### 4. Regional Store Handling
Prevents crawling different country stores:

- **Filters regional URLs** (`/en-us`, `/en-au`, etc.)
- **Removes country selector parameters** (`?__geom=`)
- **Stays focused on the starting domain** region

## 🎯 Supported Websites

### E-commerce Platforms
- **Shopify stores** (most common)
- **WooCommerce sites**
- **Magento stores**
- **Custom e-commerce platforms**

### Product Types
- **Supplements and vitamins**
- **Electronics**
- **Clothing and fashion**
- **Home and garden**
- **Any product with structured data**

### URL Patterns Supported
- `/product/product-name`
- `/products/product-name`
- `/supplements/product-name`
- `/item/product-id`
- `/p/product-slug`

## 🐛 Troubleshooting

### Common Issues

#### 1. No Products Found
```bash
# Check if buy button detection is working
python scrapper/product_scraper_final.py "https://example.com" --quiet
# Look at diagnostic screenshots in diagnostics/ folder
```

#### 2. Wrong Images Downloaded
- The scraper now filters out logos/badges automatically
- Check debug output for image selection process
- Use `--quiet` to reduce noise in logs

#### 3. Regional Store Loops
- Regional filtering is automatic
- If you want a specific regional store, start with that URL:
  ```bash
  python scrapper/product_scraper_final.py "https://www.example.com/en-us"
  ```

#### 4. Cookie Banner Issues
- Cookie acceptance is automatic by default
- Use `--no-cookies` to disable if causing issues

### Debug Mode
```bash
# Enable verbose output for debugging
python scrapper/product_scraper_final.py "https://example.com"
# Check diagnostics/ folder for screenshots
# Look for detailed debug messages in console
```

## 📈 Performance Tips

### For Large Sites
```bash
# Use headless mode for speed
python scrapper/product_scraper_final.py "https://example.com" --headless

# Increase page limit
python scrapper/product_scraper_final.py "https://example.com" --max-pages 100

# Disable screenshots for speed
python scrapper/product_scraper_final.py "https://example.com" --no-screenshots
```

### For Development/Testing
```bash
# Disable features for faster testing
python scrapper/product_scraper_final.py "https://example.com" \
  --no-download \
  --no-scroll \
  --max-pages 5
```

## 🔒 Privacy and Ethics

### Responsible Scraping
- **Respect robots.txt** (manual check recommended)
- **Use reasonable delays** (built-in timeouts)
- **Don't overload servers** (limited concurrent requests)
- **Follow website terms of service**

### Data Usage
- **Only scrape publicly available data**
- **Respect copyright and trademarks**
- **Use data responsibly and legally**

## 🆘 Support

### Getting Help
1. **Check the diagnostic screenshots** in `diagnostics/` folder
2. **Review console output** for error messages
3. **Try different command line options** to isolate issues
4. **Test with a smaller page limit** first

### Common Error Messages
- `[Error] Failed to crawl`: Network or page loading issue
- `[Download Error]`: Image download failed (check URL accessibility)
- `[Screenshot Error]`: Screenshot capture failed (permissions issue)

## 📝 License

This tool is provided as-is for educational and research purposes. Please ensure you comply with the terms of service of any websites you scrape.
