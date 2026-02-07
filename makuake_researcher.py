import gspread
from google.oauth2.service_account import Credentials
import time
from datetime import datetime
import os
import json
import random
import re
import urllib.parse

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from deep_translator import GoogleTranslator

# --- Configuration ---
MAKUAKE_URL = "https://www.makuake.com/discover/projects/search/"
SHEET_URL = "https://docs.google.com/spreadsheets/d/12oitsHeVnaPzHhciTLxm0C-s9Q6l40tmkfbQFL9ovp0/edit?gid=0#gid=0"
MIN_FUNDING = 1000000 # 1 million JPY

def setup_google_sheets():
    # Load credentials from environment variable (GitHub Secret)
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        raise ValueError("GOOGLE_SHEETS_CREDENTIALS environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    try:
        sheet = client.open_by_url(SHEET_URL).sheet1
        # Set headers if empty
        if not sheet.get_values("A1:H1"):
            headers = ["Date", "Image", "Title", "Funding", "Makuake URL", "Amazon Check", "Rakuten Check", "1688/Lens"]
            sheet.append_row(headers)
            # Basic formatting can be done here if using gspread-formatting, but skipping to keep deps low
        return sheet
    except Exception as e:
        print(f"Error opening sheet: {e}")
        raise

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Mimic a real user agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def translate_to_chinese(text):
    try:
        # Translate Japanese to Simplified Chinese
        translated = GoogleTranslator(source='ja', target='zh-CN').translate(text)
        return translated
    except:
        return text

def generate_1688_link(text_zh):
    query = urllib.parse.quote(text_zh)
    return f"https://s.1688.com/selloffer/offer_search.htm?keywords={query}"

def generate_google_lens_link(image_url):
    query = urllib.parse.quote(image_url)
    return f"https://lens.google.com/uploadbyurl?url={query}"

def check_market_existence(driver, keyword, site="amazon"):
    """
    Checks if a product exists on Amazon or Rakuten.
    Returns a status string and a search URL.
    """
    search_query = urllib.parse.quote(keyword)
    
    if site == "amazon":
        url = f"https://www.amazon.co.jp/s?k={search_query}"
        selector = "div.s-result-item" # Generic result item
        no_result_selector = "#noResultsTitle" # "No results for..."
    # Rakuten check is harder to do without getting blocked, lets stick to link generation + simple check if possible
    elif site == "rakuten":
        url = f"https://search.rakuten.co.jp/search/mall/{search_query}/"
        selector = "div.searchresultitem"
        no_result_selector = "div.no-results" # Hypothetical, varies

    try:
        # We will iterate through these checks in the main loop to reuse the driver
        driver.get(url)
        time.sleep(2) # Polite delay
        
        if "amazon" in site:
            if "captcha" in driver.title.lower():
                return "⚠️Bot Block", url
            
            # Check for "No results"
            page_source = driver.page_source
            if "検索結果はありません" in page_source or "No results for" in page_source:
                return "🔥0件 (Blue Ocean)", url
            else:
                return "あり (Exists)", url

        elif "rakuten" in site:
             page_source = driver.page_source
             if "ご指定の検索条件に該当する商品はありません" in page_source:
                 return "🔥0件 (Blue Ocean)", url
             else:
                 return "あり (Exists)", url
                 
    except Exception:
        return "⚠️Check Failed", url
        
    return "Check Failed", url

def scrape_makuake(driver):
    print(f"Navigating to {MAKUAKE_URL}...")
    driver.get(MAKUAKE_URL)
    time.sleep(5)
    
    # Scroll
    driver.execute_script("window.scrollTo(0, 1000);")
    time.sleep(3)

    print("Parsing projects...")
    elements = driver.find_elements(By.TAG_NAME, "a")
    
    projects = []
    seen_urls = set()
    
    for i, elem in enumerate(elements):
        try:
            url = elem.get_attribute("href")
            if not url or "/project/" not in url or "search" in url:
                continue
            if url in seen_urls:
                continue
            
            # Get text and clean it
            text = elem.get_attribute("textContent")
            if not text or len(text) < 5: 
                continue

            # Try to find an image url inside this link or parent
            image_url = ""
            try:
                img_tag = elem.find_element(By.TAG_NAME, "img")
                if img_tag:
                    image_url = img_tag.get_attribute("src")
                    # Optimize Makuake image URLs for spreadsheet (remove resize params if possible)
                    # format: https://static.makuake.com/upload/project/123/main_123.jpg?width=...
                    if "?" in image_url:
                        image_url = image_url.split("?")[0]
            except:
                pass

            seen_urls.add(url)
            
            funding = 0
            
            # Extract funding
            match_yen = re.search(r'[￥¥]([0-9,]+)', text)
            match_en = re.search(r'([0-9,]+)円', text)
            
            if match_yen:
                funding = int(match_yen.group(1).replace(",", ""))
            elif match_en:
                funding = int(match_en.group(1).replace(",", ""))
            
            # Check parent if not found
            if funding == 0:
                try:
                    parent = elem.find_element(By.XPATH, "./..")
                    parent_text = parent.get_attribute("textContent")
                    match_p = re.search(r'([0-9,]+)円', parent_text)
                    if match_p:
                         funding = int(match_p.group(1).replace(",", ""))
                except:
                    pass

            if funding == 0:
                continue

            # Title extraction
            title = ""
            # Simple heuristic matching our previous valid title logic
            title_candidate = ""
            if "￥" in text:
                title_candidate = text.split("￥")[0].strip()
            elif "¥" in text:
                title_candidate = text.split("¥")[0].strip()
            elif "円" in text:
                title_parts = text.split("円")
                if len(title_parts) > 0: title_candidate = title_parts[0].strip()

            if title_candidate and len(title_candidate) > 5:
                title = title_candidate
                if "|" in title: title = title.split("|")[0].strip()
            else:
                 # Fallback
                 title = text[:30]

            if funding >= MIN_FUNDING:
                projects.append({
                    "title": title,
                    "url": url,
                    "funding": funding,
                    "image": image_url
                })
                print(f"MATCH: {title[:20]}... ({funding} JPY)")

        except Exception as e:
            continue
            
    return projects

def get_existing_urls(sheet):
    try:
        # Assuming URL is in column 5 (E)
        urls = sheet.col_values(5)
        return set(urls)
    except:
        return set()

def format_currency_jp(amount):
    if amount >= 100000000:
        oku = amount // 100000000
        man = (amount % 100000000) // 10000
        if man > 0:
            return f"{oku}億{man}万円"
        return f"{oku}億円"
    elif amount >= 10000:
        man = amount // 10000
        return f"{man}万円"
    return f"{amount}円"

def is_likely_japan_made(text):
    keywords = ["日本製", "国産", "伝統工芸", "職人", "京都", "燕三条", "老舗"]
    for kw in keywords:
        if kw in text:
            return True
    return False

def main():
    driver = None
    try:
        sheet = setup_google_sheets()
        
        # 0. Load existing URLs to prevent duplicates
        print("Loading existing projects...")
        existing_urls = get_existing_urls(sheet)
        print(f"Found {len(existing_urls)} existing projects in sheet.")
        
        print("Setting up Selenium Driver...")
        driver = setup_driver()
        
        projects = scrape_makuake(driver)
        
        if not projects:
            print("No projects found matching criteria.")
            return

        today = datetime.now().strftime("%Y-%m-%d")
        new_rows = []
        
        print(f"Analyzing {len(projects)} projects...")
        
        count_duplicates = 0
        
        for p in projects:
            # DEDUPLICATION CHECK
            if p["url"] in existing_urls:
                count_duplicates += 1
                continue
            
            # 1. Amazon Check
            amz_status, amz_url = check_market_existence(driver, p["title"], "amazon")
            amz_cell = f'=HYPERLINK("{amz_url}", "{amz_status}")'
            
            # 2. Rakuten Check
            rak_status, rak_url = check_market_existence(driver, p["title"], "rakuten")
            rak_cell = f'=HYPERLINK("{rak_url}", "{rak_status}")'
            
            # 3. 1688/Lens Links
            clean_title = p["title"].replace("【", "").replace("】", "").split("|")[0].strip()
            title_zh = translate_to_chinese(clean_title)
            link_1688 = generate_1688_link(title_zh)
            
            link_lens = generate_1688_link(title_zh) 
            if p["image"]:
                link_lens = generate_google_lens_link(p["image"])
            
            china_cell = f'=HYPERLINK("{link_1688}", "🇨🇳1688 Search") & CHAR(10) & HYPERLINK("{link_lens}", "📷Lens Search")'
            
            # 4. Japan Check (Origin Hint)
            # We add a hint column so user can easily filter/exclude
            origin_hint = ""
            if is_likely_japan_made(p["title"]):
                origin_hint = "🇯🇵Japan?"
            
            # Image Cell
            image_cell = ""
            if p["image"]:
                image_cell = f'=IMAGE("{p["image"]}")'
            
            # Funding (Billions/Millions format)
            funding_fmt = format_currency_jp(p['funding'])

            row = [
                today,
                image_cell,
                f'=HYPERLINK("{p["url"]}", "{p["title"]}")',
                funding_fmt,
                p["url"], # Hidden-ish URL col for deduplication
                amz_cell,
                rak_cell,
                china_cell,
                origin_hint # New column
            ]
            new_rows.append(row)
            
            # Respect rate limits
            time.sleep(2)
            
        print(f"Skipped {count_duplicates} duplicates.")
            
        if new_rows:
            # Append rows
            sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
            print(f"Added {len(new_rows)} new analyzed projects to sheet.")
            
            # --- AUTO FORMATTING START ---
            print("Formatting spreadsheet layout...")
            try:
                sheet_id = sheet.id
                
                requests = [
                    # 1. Resize Rows to 200px (Requested 2x size)
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": 1, 
                                "endIndex": sheet.row_count
                            },
                            "properties": {
                                "pixelSize": 200
                            },
                            "fields": "pixelSize"
                        }
                    },
                    # 2. Resize Columns
                    # Col 2 (Image): 250px (Larger)
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": 1, 
                                "endIndex": 2
                            },
                            "properties": {
                                "pixelSize": 250
                            },
                            "fields": "pixelSize"
                        }
                    },
                     # Col 3 (Title): 250px (Limit width so it wraps)
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": 2, 
                                "endIndex": 3
                            },
                            "properties": {
                                "pixelSize": 250
                            },
                            "fields": "pixelSize"
                        }
                    },
                    # Wrap Text
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 1,
                                "startColumnIndex": 2, 
                                "endColumnIndex": 10   
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "wrapStrategy": "WRAP",
                                    "verticalAlignment": "MIDDLE"
                                }
                            },
                            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"
                        }
                    }
                ]
                
                sheet.spreadsheet.batch_update({"requests": requests})
                print("Formatting complete.")
                
            except Exception as e:
                print(f"Formatting warning: {e}")
            # --- AUTO FORMATTING END ---
            
    except Exception as e:
        print(f"Script failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()
