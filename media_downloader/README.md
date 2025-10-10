# Facebook Ad Library Media Scraper

A Python script that extracts ad metadata and downloads media files (images and videos) from Facebook Ad Library pages. The scraper intelligently detects video thumbnails and associates downloaded videos with their corresponding Library IDs.

## Features

- **Smart Media Detection**: Automatically detects and downloads both images and videos
- **Video Thumbnail Recognition**: Uses visual detection to identify cards with video content
- **Precise Video Matching**: Associates downloaded videos with correct Library IDs using timestamp-based mapping
- **Metadata Extraction**: Extracts Library ID, status, start date, and active time for each ad
- **Dual JSON Output**: Creates both detailed and simplified JSON formats
- **Network Interception**: Captures videos directly from network traffic for reliable downloading
- **Clean Terminal Output**: Minimal, focused output showing only essential results

## Installation

### Prerequisites
- Python 3.8+
- Playwright browser automation library

### Setup
1. Install Python dependencies:
```bash
pip install playwright
```

2. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Basic Usage
```bash
python scrapper/fb_ad_full_media_metadata_download.py "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=GB&search_type=page&view_all_page_id=YOUR_PAGE_ID"
```

### Advanced Usage
```bash
python scrapper/fb_ad_full_media_metadata_download.py "https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=GB&search_type=page&view_all_page_id=YOUR_PAGE_ID" \
  --out-dir custom_output \
  --max-cards 50 \
  --scrolls 20 \
  --headless
```

### Command Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `url` | Required | Facebook Ad Library URL to scrape |
| `--out-dir` | `ad_media` | Output directory for downloaded files |
| `--max-cards` | `30` | Maximum number of ad cards to process |
| `--scrolls` | `30` | Number of scroll iterations to load more ads |
| `--headless` | False | Run browser in headless mode (no GUI) |

## Output Files

The scraper creates the following files in the output directory:

### Media Files
- **Images**: `{Library_ID}.jpg` (or appropriate extension)
- **Videos**: `{Library_ID}.mp4` (or .webm/.mov based on file type)

### JSON Files
1. **`ads_summary.json`** - Detailed format with all extracted data:
```json
[
  {
    "status": "Active",
    "library_id": "1329406172069699",
    "started_running": "08 Oct 2025",
    "total_active_time": "17 hrs",
    "media_urls": ["https://..."],
    "media_files": ["/path/to/1329406172069699.jpg"]
  }
]
```

2. **`ad_cards.json`** - Simplified format matching standard output:
```json
{
  "time_of_scrapping": "2025-10-10 02:30:00",
  "results": [
    {
      "status": "Active",
      "library_id": "1329406172069699",
      "started_running": "08 Oct 2025",
      "total_active_time": "17 hrs"
    }
  ]
}
```

## How It Works

### 1. Page Navigation
- Opens the Facebook Ad Library URL
- Zooms out to 67% for optimal card visibility
- Scrolls through the page to load more ads

### 2. Card Detection
- Identifies ad cards using multiple selectors
- Extracts metadata (Library ID, status, dates, active time)
- Detects video thumbnails using visual indicators

### 3. Media Processing
- **Images**: Downloaded directly from DOM elements
- **Videos**: Captured via network interception for reliability
- Files are named using Library IDs for easy identification

### 4. Video Assignment
- Uses timestamp-based mapping to associate videos with correct Library IDs
- Only assigns videos to cards that were detected as having video thumbnails
- Handles file type detection and extension assignment

### 5. Output Generation
- Creates both detailed and simplified JSON formats
- Provides clean terminal output with summary table

## Technical Details

### Video Detection Algorithm
The scraper uses multiple methods to detect video thumbnails:
- Play button icons and overlays
- Video HTML elements
- Play button styling classes
- Video-related HTML attributes
- Content analysis for video indicators

### Network Interception
- Captures all video responses from network traffic
- Saves videos to temporary files with timestamps
- Queues videos for later assignment to Library IDs

### File Type Detection
- Reads file headers to determine correct extensions
- Supports MP4, WebM, and MOV formats
- Falls back to MP4 as default extension

## Error Handling

- Graceful handling of network timeouts and failures
- Automatic retry mechanisms for failed downloads
- Cleanup of temporary files
- Comprehensive exception handling throughout

## Performance Considerations

- Configurable scroll limits to control processing time
- Efficient DOM traversal and element selection
- Minimal memory usage with streaming file operations
- Optional headless mode for faster execution

## Troubleshooting

### Common Issues

1. **"Import playwright.sync_api could not be resolved"**
   - This is a linter warning, not an error
   - Install Playwright: `pip install playwright`
   - Install browsers: `playwright install chromium`

2. **No videos downloaded**
   - Check if the page actually contains video ads
   - Increase `--scrolls` parameter to load more content
   - Verify the URL is accessible and contains ads

3. **Permission errors**
   - Ensure write permissions for the output directory
   - Run with appropriate user privileges

### Debug Mode
To enable debug output (if needed), you can temporarily uncomment debug print statements in the code.

## License

This script is provided as-is for educational and research purposes. Please respect Facebook's Terms of Service and robots.txt when using this tool.

## Contributing

Feel free to submit issues and enhancement requests. When contributing code, please ensure:
- Code follows Python best practices
- Error handling is comprehensive
- Documentation is updated accordingly

## Disclaimer

This tool is for educational purposes only. Users are responsible for complying with Facebook's Terms of Service and applicable laws when using this scraper.