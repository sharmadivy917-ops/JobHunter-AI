"""
apify_hunter.py — AI-Powered Job Discovery Engine using Apify & Claude.
"""
import os
import sys
import io
import time
import csv
import json
import re
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from filelock import FileLock
from dotenv import load_dotenv

# Optional AI / Scraper imports
try:
    from apify_client import ApifyClient
except ImportError:
    ApifyClient = None

try:
    from google import genai
except ImportError:
    genai = None

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Force flush on print
import builtins
_original_print = builtins.print
def _flush_print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _original_print(*args, **kwargs)
builtins.print = _flush_print

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMS_CSV = os.path.join(BASE_DIR, "firms.csv")
ENV_FILE = os.path.join(BASE_DIR, ".env")
file_lock = FileLock(os.path.join(BASE_DIR, 'jobhunter.lock'), timeout=30)

load_dotenv(ENV_FILE)

# API Keys
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")

# We re-use some basic query logic from hunter.py
def generate_search_queries(roles, locations):
    queries = []
    for role in roles:
        for loc in locations:
            queries.append(f'"{role}" hiring HR email {loc}')
            queries.append(f'{role} "careers" contact email {loc}')
            queries.append(f'{role} "send resume to" {loc}')
    return queries[:10]  # limit initial queries

def load_existing_emails():
    existing = set()
    if os.path.exists(FIRMS_CSV):
        try:
            with file_lock:
                with open(FIRMS_CSV, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row.get("contact_email"):
                            existing.add(row["contact_email"].lower().strip())
        except Exception as e:
            pass
    return existing

def load_sent_emails():
    sent = set()
    EMAIL_LOG = os.path.join(BASE_DIR, "email_log.json")
    if os.path.exists(EMAIL_LOG):
        try:
            with file_lock:
                with open(EMAIL_LOG, 'r') as f:
                    history = json.load(f)
                    for item in history:
                        if item.get("email"):
                            sent.add(item["email"].lower().strip())
        except Exception:
            pass
    return sent

def fetch_page_text(url):
    """Fetches a URL and extracts visible text to reduce token usage."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, 'html.parser')
        # Remove scripts, styles
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(separator=' ')
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text[:15000] # limit context window
    except Exception as e:
        return ""

def ask_ai_to_extract_leads(text, url, roles):
    """
    Passes the scraped text to Gemini to identify the company name, HR email, and evaluate the fit.
    """
    if not genai or not GEMINI_KEY:
        return []
    
    retries = 3
    for attempt in range(retries):
        try:
            client = genai.Client(api_key=GEMINI_KEY)
            
            prompt = f"""
            You are an AI recruitment assistant. I am scraping the web to find hiring contacts for these roles: {', '.join(roles)}.
            I have downloaded the text from the following URL: {url}
            
            Analyze the text and extract any valid hiring manager, recruiter, or HR email addresses. 
            Exclude generic support/info/admin emails unless they are specifically listed for job applications.
            Also, identify the Company Name.
            Finally, give a brief note (1 sentence) about why this email was selected.
            
            Output strictly in JSON format as a list of objects:
            [
              {{
                "company_name": "Name of the Company",
                "email": "hr@company.com",
                "role": "The role they are hiring for (must be somewhat related to {roles})",
                "hr_name": "Name of HR person if found, else 'HR Team'",
                "notes": "Found on careers page..."
              }}
            ]
            If no valid emails are found, output an empty list [].
            
            Text snippet:
            {text}
            """
            
            model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            content = response.text
            # extract JSON block
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                leads = json.loads(json_match.group(0))
                return leads
            return []
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                print(f"   [Gemini Rate Limit] Pausing for 30 seconds to clear quota... (Retry {attempt+1}/{retries})")
                time.sleep(30)
                continue
            else:
                print(f"   [Gemini Error] {e}")
                return []
    return []

def run_ai_hunt():
    print(f"\n{'='*56}")
    print(f"  AI HUNTER - Apify + Gemini Discovery")
    print(f"{'='*56}\n")

    if not APIFY_TOKEN:
        print("❌ Error: Apify API Token is missing. Please add it in Settings.")
        return
    if not GEMINI_KEY:
        print("❌ Error: Gemini API Key is missing. Please add it in Settings.")
        return
        
    roles_input = os.environ.get("HUNTER_ROLES", "Software Developer")
    locations_input = os.environ.get("HUNTER_LOCATIONS", "Remote")
    roles = [r.strip() for r in roles_input.split(',') if r.strip()]
    locations = [l.strip() for l in locations_input.split(',') if l.strip()]

    print(f"Roles: {', '.join(roles)}")
    print(f"Locations: {', '.join(locations)}")
    print("Connecting to Apify...")

    client = ApifyClient(APIFY_TOKEN)
    queries = generate_search_queries(roles, locations)
    
    # Run Google Search Scraper
    run_input = {
        "queries": "\n".join(queries),
        "resultsPerPage": 10,
        "maxPagesPerQuery": 1,
        "languageCode": "",
        "mobileResults": False,
        "includeUnfilteredResults": False,
        "saveHtml": False,
        "saveHtmlToKeyValueStore": False,
        "includeIcons": False,
    }
    
    print(f"Submitting {len(queries)} queries to Apify Google Search Actor...")
    try:
        run = client.actor("apify/google-search-scraper").call(run_input=run_input)
    except Exception as e:
        print(f"❌ Failed to run Apify actor: {e}")
        return
        
    print("Apify scraping complete. Processing results with Gemini...")
    
    urls_to_visit = set()
    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "defaultDatasetId", None)
    for item in client.dataset(dataset_id).iterate_items():
        org_results = item.get("organicResults", item.get("organic_results", []))
        for res in org_results:
            url = res.get("url")
            if url and "linkedin" not in url and "indeed" not in url:
                urls_to_visit.add(url)
                    
    urls_to_visit = list(urls_to_visit)[:15] # cap at 15 for demo / cost control
    print(f"Found {len(urls_to_visit)} unique company pages to analyze.")
    
    new_leads = []
    existing_emails = load_existing_emails()
    sent_emails = load_sent_emails()
    
    for i, url in enumerate(urls_to_visit, 1):
        print(f"\n[{i}/{len(urls_to_visit)}] Fetching: {url[:60]}...")
        text = fetch_page_text(url)
        if not text or len(text) < 100:
            print("   Skipped: Not enough text.")
            continue
            
        print("   Asking Gemini to extract leads...")
        leads = ask_ai_to_extract_leads(text, url, roles)
        
        for lead in leads:
            email = lead.get('email', '').lower().strip()
            if email in existing_emails or email in sent_emails:
                print(f"   ⚠️ Skipped duplicate/sent: {email}")
                continue
                
            print(f"   ✅ Found: {email} at {lead.get('company_name')}")
            lead['type'] = 'job'
            new_leads.append(lead)
            existing_emails.add(email)
            
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        delay = 30 if "pro" in model_name.lower() else 12
        time.sleep(delay) # Pace requests to respect Free Tier RPM limits
    # Save to CSV
    if new_leads:
        file_exists = os.path.exists(FIRMS_CSV)
        with file_lock:
            with open(FIRMS_CSV, "a", newline='', encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["company_name", "contact_email", "role", "hr_name", "notes", "type"])
                if not file_exists:
                    writer.writeheader()
                for firm in new_leads:
                    # Map properties to exact CSV headers
                    row = {
                        "company_name": firm.get("company_name", "Unknown"),
                        "contact_email": firm.get("email", ""),
                        "role": firm.get("role", roles[0]),
                        "hr_name": firm.get("hr_name", "HR Team"),
                        "notes": firm.get("notes", "AI Extracted"),
                        "type": firm.get("type", "job")
                    }
                    writer.writerow(row)
        print(f"\n✨ Success: Saved {len(new_leads)} new AI-verified leads to database.")
    else:
        print("\n⚠️ No new valid leads extracted in this run.")

if __name__ == "__main__":
    run_ai_hunt()
