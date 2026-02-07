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
        
        # Wait for project cards to load
        print("Waiting for page content...")
        try:
            # Wait until at least one link with '/project/' in href appears
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/project/']"))
            )
            # Scroll down a bit to trigger lazy loading if any
            driver.execute_script("window.scrollTo(0, 1000);")
            time.sleep(3)
        except Exception as e:
            print(f"Wait timed out or failed: {e}")
            # Continue anyway, maybe some content loaded
            
        print("Parsing projects...")
        # Find all anchor tags that look like project links
        # This is a broad selector: any link containing '/project/'
        # Then we look inside it for Title and Funding info.
        
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/project/']")
        print(f"Found {len(links)} potential project links.")
        
        seen_urls = set()
        
        for link in links:
            try:
                url = link.get_attribute("href")
                if not url or url in seen_urls:
                    continue
                if "/project/" not in url or "search" in url:
                    continue
                    
                seen_urls.add(url)
                
                # Extract text from the link element itself (often the title is inside)
                text_content = link.text
                if not text_content:
                    continue
                
                # Try to parse funding from the text content of the card
                # The card text usually contains "12,345,678円" or similar
                
                funding = 0
                title = ""
                
                # Split text by newlines to inspect parts
                lines = text_content.split('\n')
                
                # Simple heuristic: Longest line is likely the title, line with '円' is funding
                for line in lines:
                    if "円" in line:
                        try:
                            # Extract number: remove commas, '円', spaces
                            num_str = "".join(filter(str.isdigit, line))
                            if num_str:
                                funding = int(num_str)
                        except:
                            pass
                    elif len(line) > 5 and len(line) < 100:
                        # Candidate for title if we haven't found a better one
                        if not title:
                            title = line.strip()
                
                # If we couldn't find funding in the text, skip
                if funding == 0:
                    continue
                
                # If title is still empty, use the link text mostly
                if not title:
                    title = text_content[:50].replace("\n", " ")

                if funding >= MIN_FUNDING:
                    projects.append({
                        "title": title,
                        "url": url,
                        "funding": funding
                    })
                    print(f"Found: {title[:20]}... ({funding} JPY)")
                    
            except Exception as inner_e:
                continue

    except Exception as e:
        print(f"Scraping error: {e}")
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
