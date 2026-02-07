import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
import time
from datetime import datetime
import os
import json
import random

# --- Configuration ---
MAKUAKE_URL = "https://www.makuake.com/project/search/new" # Search for new projects
SHEET_URL = "https://docs.google.com/spreadsheets/d/12oitsHeVnaPzHhciTLxm0C-s9Q6l40tmkfbQFL9ovp0/edit?gid=0#gid=0"
MIN_FUNDING = 1000000 # 1 million JPY

# User Agents to mimic real browsers
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
]

def get_random_header():
    return {"User-Agent": random.choice(USER_AGENTS)}

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
    # Simple check: Search Amazon and see if exact match or high relevance exists
    # Note: Scraping Amazon is hard. We will use a gentle search and check for 'No results' text or similar.
    # For stability in GitHub Actions, we might just log the search URL for manual check if strict scraping fails.
    
    search_query = product_name.replace(" ", "+")
    amazon_url = f"https://www.amazon.co.jp/s?k={search_query}"
    
    # In a real rigorous tool, we'd use an API (Product Advertising API). 
    # Here we will return the Search URL for the user to click.
    # Automated "Unreleased" judgment is very prone to false positives without expensive APIs.
    return amazon_url

def scrape_makuake():
    print("Scraping Makuake...")
    response = requests.get(MAKUAKE_URL, headers=get_random_header())
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    
    projects = []
    
    # This selector needs to be adjusted based on actual Makuake HTML structure
    # Assuming standard project card structure. 
    # Note: Makuake class names change. We look for project boxes.
    project_boxes = soup.find_all("div", class_="project-box") # Placeholder class
    
    # If standard class search fails (likely), we might need more robust traversal or use an API offering if available.
    # Let's try to find common elements.
    if not project_boxes:
         # Fallback: Try to find articles
         project_boxes = soup.find_all("article")

    for box in project_boxes:
        try:
            title_tag = box.find("h3") or box.find("h2") or box.find("a", class_="project-title")
            if not title_tag: continue
            
            title = title_tag.get_text(strip=True)
            link = title_tag.find_parent("a")["href"] if title_tag.find_parent("a") else ""
            if link and not link.startswith("http"):
                link = "https://www.makuake.com" + link

            # Funding logic
            money_tag = box.find(string=lambda text: "円" in text if text else False)
            if not money_tag: continue
            
            funding_str = money_tag.strip().replace(",", "").replace("円", "")
            try:
                funding = int(funding_str)
            except ValueError:
                continue
                
            if funding >= MIN_FUNDING:
                projects.append({
                    "title": title,
                    "url": link,
                    "funding": funding
                })
        except Exception as e:
            continue
            
    return projects

def main():
    try:
        sheet = setup_google_sheets()
        projects = scrape_makuake()
        
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
        # In GitHub Actions, a non-zero exit code marks the run as failed
        exit(1)

if __name__ == "__main__":
    main()
