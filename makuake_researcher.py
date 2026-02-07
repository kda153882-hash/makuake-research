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

        print("Parsing projects (broad search)...")
        elements = driver.find_elements(By.TAG_NAME, "a")
        
        seen_urls = set()
        debug_html_printed = False
        
        for i, elem in enumerate(elements):
            try:
                url = elem.get_attribute("href")
                if not url or "/project/" not in url or "search" in url:
                    continue
                if url in seen_urls:
                    continue
                
                # Use textContent to get text even if hidden
                text = elem.get_attribute("textContent")
                
                # DEBUG: Print the HTML of the VERY FIRST project link found
                # This is critical to understanding why we aren't finding the price
                if not debug_html_printed:
                    print(f"\n--- DEBUG PROJECT HTML START ---")
                    print(f"URL: {url}")
                    # Print full inner HTML to see structure
                    html_snippet = elem.get_attribute('innerHTML')
                    # Remove excessive whitespace for readable logs
                    clean_html = " ".join(html_snippet.split())
                    print(f"HTML: {clean_html[:1000]}...") 
                    print(f"TextContent: {text}")
                    print(f"--- DEBUG PROJECT HTML END ---\n")
                    debug_html_printed = True
                
                # Basic length filter
                if not text or len(text) < 5: 
                    continue

                seen_urls.add(url)
                
                funding = 0
                title = ""
                
                # Extract funding
                import re
                match = re.search(r'([0-9,]+)円', text)
                if match:
                    num_str = match.group(1).replace(",", "")
                    funding = int(num_str)
                
                # If no funding in link, try parent text (sometimes link is inside a card div)
                if funding == 0:
                    try:
                        parent = elem.find_element(By.XPATH, "./..")
                        parent_text = parent.get_attribute("textContent")
                        match_p = re.search(r'([0-9,]+)円', parent_text)
                        if match_p:
                             num_str = match_p.group(1).replace(",", "")
                             funding = int(num_str)
                             if not title and len(parent_text) > 10:
                                 title = parent_text.split("円")[0].strip()[-30:] # Guesswork
                    except:
                        pass

                if funding == 0:
                    continue

                # Title extraction
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                for line in lines:
                    if "円" not in line and len(line) > 10:
                        title = line
                        break
                
                if not title:
                    title = "Title not found"

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
