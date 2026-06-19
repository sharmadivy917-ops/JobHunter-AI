"""
linkedin_hunter.py — Scrapes LinkedIn Jobs locally via Python Requests (100% Free) and uses Gemini to extract HR emails.
"""
import os
import sys
import io
import time
import csv
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from filelock import FileLock
from dotenv import load_dotenv

try:
    from google import genai
except ImportError:
    genai = None

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import builtins
_original_print = builtins.print
def _flush_print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _original_print(*args, **kwargs)
builtins.print = _flush_print

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMS_CSV = os.path.join(BASE_DIR, "firms.csv")
MANUAL_JOBS_CSV = os.path.join(BASE_DIR, "linkedin_manual_jobs.csv")
ENV_FILE = os.path.join(BASE_DIR, ".env")
file_lock = FileLock(os.path.join(BASE_DIR, 'jobhunter.lock'), timeout=30)

load_dotenv(ENV_FILE)

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")

def load_existing_emails():
    existing = set()
    if os.path.exists(FIRMS_CSV):
        try:
            with file_lock:
                with open(FIRMS_CSV, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row.get("contact_email"):
                            existing.add(row["contact_email"].lower().strip())
        except Exception:
            pass
    return existing

def ask_ai_for_email(description, company_name, role):
    if not genai or not GEMINI_KEY:
        return ""
        
    retries = 3
    for attempt in range(retries):
        try:
            client = genai.Client(api_key=GEMINI_KEY)
            prompt = f"""
            You are an AI assistant analyzing a LinkedIn Job Description.
            Company: {company_name}
            Role: {role}
            
            Analyze the following text and look specifically for any email addresses mentioned (e.g. "send your resume to hr@company.com" or "contact career@company.com").
            
            Job Description:
            {description}
            
            If you find a valid email address that applicants should use, output ONLY the email address (no other text).
            If you do not find any email address, output exactly "NONE".
            """
            model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            text = response.text.strip()
            if "NONE" in text.upper() or not "@" in text:
                return ""
            
            match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
            if match:
                return match.group(0).lower()
            return ""
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                print(f"   [Gemini Rate Limit] Pausing for 30 seconds to clear quota... (Retry {attempt+1}/{retries})")
                time.sleep(30)
                continue
            else:
                print(f"   [Gemini Error] {e}")
                return ""
    return ""

def scrape_linkedin_jobs_locally(roles, locations, max_items):
    jobs_found = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    for role in roles:
        for loc in locations:
            if len(jobs_found) >= max_items:
                break
            q_role = urllib.parse.quote(role)
            q_loc = urllib.parse.quote(loc)
            search_url = f"https://www.linkedin.com/jobs/search?keywords={q_role}&location={q_loc}&f_TPR=r2592000"
            
            try:
                res = requests.get(search_url, headers=headers, timeout=10)
                if res.status_code != 200:
                    continue
                soup = BeautifulSoup(res.text, 'html.parser')
                cards = soup.find_all('div', class_='base-card')
                
                for card in cards:
                    if len(jobs_found) >= max_items:
                        break
                    title_el = card.find('h3', class_='base-search-card__title')
                    company_el = card.find('h4', class_='base-search-card__subtitle')
                    loc_el = card.find('span', class_='job-search-card__location')
                    link_el = card.find('a', class_='base-card__full-link')
                    
                    if title_el and company_el and link_el:
                        title = title_el.text.strip()
                        company = company_el.text.strip()
                        location = loc_el.text.strip() if loc_el else "Unknown"
                        link = link_el.get('href', '').split('?')[0]
                        
                        jobs_found.append({
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": link
                        })
            except Exception as e:
                print(f"   [Error scraping {role} in {loc}] {e}")
            time.sleep(2)
            
    return jobs_found

def get_job_description(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            desc_div = soup.find('div', class_='show-more-less-html__markup')
            if desc_div:
                return desc_div.text.strip()
    except Exception:
        pass
    return ""

def run_linkedin_hunt():
    print(f"\n{'='*56}")
    print(f"  LINKEDIN HUNTER - 100% Free Local Scraping")
    print(f"{'='*56}\n")

    if not GEMINI_KEY:
        print("❌ Error: Gemini API Key is missing. Please add it in Settings.")
        return
        
    roles_input = os.environ.get("HUNTER_ROLES", "Python Developer")
    locations_input = os.environ.get("HUNTER_LOCATIONS", "Remote")
    roles = [r.strip() for r in roles_input.split(',') if r.strip()]
    locations = [l.strip() for l in locations_input.split(',') if l.strip()]
    max_items = int(os.environ.get("HUNTER_MAX", 20))

    print(f"Roles: {', '.join(roles)}")
    print(f"Locations: {', '.join(locations)}")
    print("Scraping LinkedIn locally (No Apify credits required!)...")

    jobs = scrape_linkedin_jobs_locally(roles, locations, max_items)
    print(f"Found {len(jobs)} active jobs. Processing descriptions with Gemini...")
    
    existing_emails = load_existing_emails()
    new_auto_leads = []
    new_manual_jobs = []
    
    for item in jobs:
        company = item["company"]
        role = item["title"]
        location = item["location"]
        job_url = item["url"]
        
        print(f"\nAnalyzing Job: {company[:20]} - {role[:30]}...")
        description = get_job_description(job_url)
        
        if not description or len(description) < 20:
            print("   ⚠️ Could not load full description. Saving to Manual Jobs.")
            new_manual_jobs.append({
                "company": company,
                "role": role,
                "location": location,
                "link": job_url
            })
            continue
            
        email = ask_ai_for_email(description, company, role)
        
        if email:
            if email in existing_emails:
                print(f"   ⚠️ Skipped duplicate email: {email}")
                continue
            print(f"   ✅ FOUND EMAIL: {email}")
            new_auto_leads.append({
                "company_name": company,
                "contact_email": email,
                "role": role,
                "hr_name": "HR Team",
                "notes": "Found in LinkedIn job description",
                "type": "job"
            })
            existing_emails.add(email)
        else:
            print("   📌 No direct email found. Saving to Manual Jobs.")
            new_manual_jobs.append({
                "company": company,
                "role": role,
                "location": location,
                "link": job_url
            })
            
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        delay = 30 if "pro" in model_name.lower() else 12
        time.sleep(delay) # Pace requests to respect Free Tier RPM limits
        
    if new_auto_leads:
        file_exists = os.path.exists(FIRMS_CSV)
        with file_lock:
            with open(FIRMS_CSV, "a", newline='', encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["company_name", "contact_email", "role", "hr_name", "notes", "type"])
                if not file_exists:
                    writer.writeheader()
                for lead in new_auto_leads:
                    writer.writerow(lead)
        print(f"\n✨ Saved {len(new_auto_leads)} auto-leads to firms.csv for AI Engine!")
        
    if new_manual_jobs:
        file_exists = os.path.exists(MANUAL_JOBS_CSV)
        with file_lock:
            with open(MANUAL_JOBS_CSV, "a", newline='', encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["company", "role", "location", "link"])
                if not file_exists:
                    writer.writeheader()
                for job in new_manual_jobs:
                    writer.writerow(job)
        print(f"✨ Saved {len(new_manual_jobs)} jobs without emails to Manual Jobs board!")

    if not new_auto_leads and not new_manual_jobs:
        print("\n⚠️ No new jobs found.")

if __name__ == "__main__":
    run_linkedin_hunt()
