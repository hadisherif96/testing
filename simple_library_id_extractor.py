#!/usr/bin/env python3
"""
Simple Facebook Ad Library ID Extractor
Focused specifically on extracting Library IDs from search results
"""

from playwright.sync_api import sync_playwright
import re
import json
from urllib.parse import quote_plus

def extract_library_ids_simple(search_term, country="GB", headless=False):
    """
    Simple function to extract Library IDs from Facebook Ad Library
    
    Args:
        search_term: Brand/company name to search for
        country: Country code (default: GB for UK)
        headless: Whether to run browser in headless mode
    
    Returns:
        List of Library IDs found
    """
    library_ids = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            # Build search URL
            query = quote_plus(search_term)
            url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={country}&q={query}"
            
            print(f"Searching: {search_term}")
            print(f"URL: {url}")
            
            # Navigate to search page
            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)
            
            # Scroll to load more ads
            print("Loading ads by scrolling...")
            for i in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
            
            # Method 1: Look for "Library ID" text and extract the number
            print("Extracting Library IDs...")
            try:
                # Find all elements containing "Library ID"
                elements = page.query_selector_all('text=Library ID')
                for element in elements:
                    try:
                        # Get the parent element that contains the full text
                        parent = element.query_selector('xpath=..')
                        if parent:
                            text = parent.inner_text()
                            # Extract the ID number after "Library ID"
                            match = re.search(r'Library ID[:\s]*(\d+)', text)
                            if match:
                                library_ids.append(match.group(1))
                                print(f"Found Library ID: {match.group(1)}")
                    except Exception as e:
                        print(f"Error processing element: {e}")
                        continue
            except Exception as e:
                print(f"Error in Method 1: {e}")
            
            # Method 2: If no IDs found, try extracting from URLs
            if not library_ids:
                print("Trying alternative method...")
                try:
                    # Look for ad detail links
                    links = page.query_selector_all('a[href*="/ads/library/?id="]')
                    for link in links:
                        try:
                            href = link.get_attribute('href')
                            match = re.search(r'id=(\d+)', href)
                            if match and match.group(1) not in library_ids:
                                library_ids.append(match.group(1))
                                print(f"Found Library ID from URL: {match.group(1)}")
                        except Exception:
                            continue
                except Exception as e:
                    print(f"Error in Method 2: {e}")
            
            # Method 3: Search in page content
            if not library_ids:
                print("Trying regex search on page content...")
                try:
                    content = page.content()
                    # Look for long numeric strings (Facebook IDs are typically 15-16 digits)
                    matches = re.findall(r'\b\d{15,17}\b', content)
                    for match in matches:
                        if match not in library_ids:
                            library_ids.append(match)
                            print(f"Found potential Library ID: {match}")
                except Exception as e:
                    print(f"Error in Method 3: {e}")
            
        except Exception as e:
            print(f"Error during scraping: {e}")
        finally:
            browser.close()
    
    return library_ids

def main():
    """Example usage"""
    # Search for DR.VEGAN ads (as shown in your screenshot)
    search_term = "DR.VEGAN"
    
    print("=" * 60)
    print("Facebook Ad Library - Library ID Extractor")
    print("=" * 60)
    
    # Extract Library IDs
    library_ids = extract_library_ids_simple(search_term, country="GB", headless=False)
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    if library_ids:
        print(f"Found {len(library_ids)} Library IDs:")
        for i, lib_id in enumerate(library_ids, 1):
            print(f"{i}. {lib_id}")
            print(f"   URL: https://www.facebook.com/ads/library/?id={lib_id}")
        
        # Save to JSON
        output = {
            "search_term": search_term,
            "library_ids": library_ids,
            "total_found": len(library_ids)
        }
        
        with open("library_ids_simple.json", "w") as f:
            json.dump(output, f, indent=2)
        
        print(f"\nResults saved to: library_ids_simple.json")
    else:
        print("No Library IDs found. This could mean:")
        print("1. No ads found for this search term")
        print("2. Facebook has changed their page structure")
        print("3. The ads are not currently active")
        print("\nTry running with headless=False to see what's happening")

if __name__ == "__main__":
    main()
