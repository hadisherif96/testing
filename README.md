# Facebook Ad Media Downloader

A Python script that automatically downloads all media files (videos, images, and streaming segments) from Facebook Ad Library pages (and WEBSITES) using Playwright to intercept network requests.

## Overview

This tool captures all media responses from Facebook Ad Library URLs by:
- Intercepting network requests in real-time
- Identifying media files by content type and file extensions
- Automatically saving videos, images, and streaming segments (m3u8, ts, etc.)
- Scrolling through the page to trigger lazy-loaded content

## Features

- ✅ Downloads videos (mp4, mov)
- ✅ Downloads images (jpg, jpeg, png, webp, gif)
- ✅ Captures streaming segments (m3u8, ts files)
- ✅ Handles dynamic content loading
- ✅ Automatic file naming and organization
- ✅ Real-time progress feedback

## Prerequisites

- Python 3.7 or higher
- Playwright browser automation library

## Installation

1. **Install Playwright:**
   ```bash
   pip install playwright
   ```

2. **Install Chromium browser:**
   ```bash
   playwright install chromium
   ```

## Usage

### Basic Usage

```bash
python fb_ad_video_downloader.py <facebook_ad_library_url>
```

### Example

```bash
python fb_ad_video_downloader.py "https://www.facebook.com/ads/library/?id=123456789"
```

### What Happens

1. The script launches a Chromium browser (visible by default)
2. Navigates to the provided Facebook Ad Library URL
3. Scrolls through the page 10 times to load ads progressively
4. Intercepts and saves all media files automatically
5. Waits 15 seconds for final background downloads to complete
6. All media files are saved to the `downloads_full/` directory

## Output

All downloaded media files are saved in:
```
downloads_full/
├── video_file_1.mp4
├── image_file_1.jpg
├── segment_1.ts
├── playlist.m3u8
└── ...
```

### File Naming

- Files are named based on their URL path
- Special characters are replaced with underscores
- Extensions are auto-detected from content-type headers if missing
- Duplicate filenames will overwrite previous files

## How It Works

1. **Request Interception**: Listens to all network responses during page load
2. **Media Detection**: Identifies media files by:
   - File extensions: `.mp4`, `.mov`, `.m3u8`, `.ts`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`
   - Content-Type headers: `video/*`, `image/*`, `application/vnd.apple.mpegurl`
3. **Immediate Saving**: Downloads and saves media files as soon as they're detected
4. **Progressive Loading**: Scrolls the page to trigger lazy-loaded content
5. **Wait Period**: Allows time for chunked/segmented downloads to complete

## Configuration

You can modify these variables in the script:

```python
SAVE_DIR = Path("downloads_full")  # Change output directory
```

Scroll behavior (lines 74-76):
```python
for _ in range(10):  # Number of scroll iterations
    page.evaluate("window.scrollBy(0, window.innerHeight)")
    page.wait_for_timeout(2000)  # Wait time between scrolls (ms)
```

Final wait time (line 80):
```python
page.wait_for_timeout(15000)  # Wait time for final downloads (ms)
```

## Troubleshooting

### Browser doesn't open
- Ensure Chromium is installed: `playwright install chromium`
- Check if another browser is running on the same port

### No media files downloaded
- Verify the URL is correct and accessible
- Check if the ad has media content
- Try increasing scroll iterations or wait times
- Some ads may use different media delivery methods

### Headless Mode

To run without visible browser window, modify line 60:
```python
browser = p.chromium.launch(headless=True)  # Change False to True
```

### Permission Errors

Ensure you have write permissions for the `downloads_full/` directory.

## Notes

- The script uses a Chrome user-agent for better compatibility
- Network interception happens at the browser level, capturing all requests
- Large video files may take time to download completely
- The script waits 15 seconds at the end to ensure all chunked downloads finish

## License

This is a utility script for educational and research purposes. Ensure you comply with Facebook's Terms of Service when scraping ad content.

