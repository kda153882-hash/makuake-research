import gspread
from google.oauth2.service_account import Credentials
import time
from datetime import datetime
import os
import json
import random

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Configuration ---
# Using the "New" projects page which is often a good source
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
        return sheet
    except Exception as e:
        print(f"Error opening sheet: {e}")
        raise

def check_amazon_existence(product_name):
    search_query = product_name.replace(" ", "+")
    amazon_url = f"https://www.amazon.co.jp/s?k={search_query}"
    return amazon_url

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") # Run in background
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Mimic a real user agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver



def scrape_makuake():
    print("Setting up Selenium Driver...")
    driver = setup_driver()
    projects = []
    
    try:
        print(f"Navigating to {MAKUAKE_URL}...")
        driver.get(MAKUAKE_URL)
        time.sleep(5) 
        
        print(f"DEBUG: Page Title = {driver.title}")
        
        # Scroll
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(3)

        print("Parsing projects...")
        elements = driver.find_elements(By.TAG_NAME, "a")
        
        seen_urls = set()
        
        for i, elem in enumerate(elements):
            try:
                url = elem.get_attribute("href")
                if not url or "/project/" not in url or "search" in url:
                    continue
                if url in seen_urls:
                    continue
                
                # Use textContent to get text even if hidden
                text = elem.get_attribute("textContent")
                
                # Basic length filter
                if not text or len(text) < 5: 
                    continue

                seen_urls.add(url)
                
                funding = 0
                title = ""
                
                # Extract funding
                import re
                
                # Regex to find money: supports ￥1000, ¥1000, 1000円
                # Pattern 1: ￥1,234,567 (Common in new Makuake UI)
                match_yen = re.search(r'[￥¥]([0-9,]+)', text)
                
                # Pattern 2: 1,234,567円 (Old Makuake UI or specific parts)
                match_en = re.search(r'([0-9,]+)円', text)
                
                if match_yen:
                    num_str = match_yen.group(1).replace(",", "")
                    try: 
                        funding = int(num_str)
                    except: 
                        pass
                elif match_en:
                    num_str = match_en.group(1).replace(",", "")
                    try:
                        funding = int(num_str)
                    except:
                        pass
                
                # If no funding in link, try parent text (sometimes link is inside a card div)
                if funding == 0:
                    try:
                        parent = elem.find_element(By.XPATH, "./..")
                        parent_text = parent.get_attribute("textContent")
                        
                        match_yen_p = re.search(r'[￥¥]([0-9,]+)', parent_text)
                        match_en_p = re.search(r'([0-9,]+)円', parent_text)
                        
                        if match_yen_p:
                             num_str = match_yen_p.group(1).replace(",", "")
                             funding = int(num_str)
                        elif match_en_p:
                             num_str = match_en_p.group(1).replace(",", "")
                             funding = int(num_str)
                    except:
                        pass

                if funding == 0:
                    continue

                # Title extraction
                # Text is mashed: "Title... | Valerion￥250..."
                # Heuristic: Title is usually before the Yen symbol
                
                title_candidate = ""
                if "￥" in text:
                    title_candidate = text.split("￥")[0].strip()
                elif "¥" in text:
                    title_candidate = text.split("¥")[0].strip()
                elif "円" in text:
                    title_parts = text.split("円")
                    pass
                
                if title_candidate and len(title_candidate) > 5:
                    title = title_candidate
                    # Remove trailing junk if any (like | Valerion) checks
                    # Clean up trailing pipes often seen in meta tags like "Title | Brand"
                    if "|" in title:
                         title = title.split("|")[0].strip()
                else:
                    lines = [l.strip() for l in text.split('\n') if l.strip()]
                    for line in lines:
                        if "円" not in line and "￥" not in line and len(line) > 10:
                            title = line
                            break
                
                if not title:
                    title = text[:50] # Fallback to first 50 chars

                if funding >= MIN_FUNDING:
                    projects.append({
                        "title": title,
                        "url": url,
                        "funding": funding
                    })
                    print(f"MATCH: {title[:30]}... ({funding} JPY)")

            except Exception as e:
                continue

    except Exception as e:
        print(f"Scraping error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()
            
    return projects


def main():
    try:
        sheet = setup_google_sheets()
        projects = scrape_makuake()
        
        if not projects:
            print("No projects found matching criteria.")
            # Don't fail the job, just finish
            return

        today = datetime.now().strftime("%Y-%m-%d")
        new_rows = []
        
        for p in projects:
            amazon_search_url = check_amazon_existence(p["title"])
            row = [today, p["title"], p["funding"], p["url"], amazon_search_url]
            new_rows.append(row)
            
        if new_rows:
            sheet.append_rows(new_rows)
            print(f"Added {len(new_rows)} projects to sheet.")
        else:
            print("No high-funding projects found today.")
            
    except Exception as e:
        print(f"Script failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
