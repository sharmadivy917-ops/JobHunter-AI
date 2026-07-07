"""
linkedin_hunter.py — Scrapes LinkedIn Jobs locally via Python Requests (100% Free) and uses Gemini to extract HR emails.
"""
import os
import sys
import io
import time
import csv
import re
import random
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from filelock import FileLock
from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

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

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

# Plain email + obfuscated forms like "name [at] company [dot] com".
_EMAIL_RE = re.compile(r'[\w.\-]+@[\w.\-]+\.\w+')
_OBFUSCATED_RE = re.compile(
    r'([\w.\-]+)\s*[\[(]?\s*(?:at|@)\s*[\])]?\s*([\w.\-]+)'
    r'(?:\s*[\[(]?\s*(?:dot|\.)\s*[\])]?\s*([\w.\-]+))+',
    re.IGNORECASE,
)

# Emails that are almost never a real HR contact.
_JUNK_EMAIL_HINTS = ("noreply", "no-reply", "donotreply", "example.com",
                     "sentry", "wixpress", "domain.com", ".png", ".jpg")


def extract_email_regex(text):
    """Pull an application email straight from the description (free, instant).

    Returns a lowercase email or "" if none found. Tries plain addresses first,
    then de-obfuscates "name [at] company [dot] com" style strings.
    """
    if not text:
        return ""
    for match in _EMAIL_RE.findall(text):
        low = match.lower()
        if not any(h in low for h in _JUNK_EMAIL_HINTS):
            return low

    m = _OBFUSCATED_RE.search(text)
    if m:
        cleaned = re.sub(r'\s*[\[(]?\s*(?:at|@)\s*[\])]?\s*', '@',
                         m.group(0), count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*[\[(]?\s*(?:dot|\.)\s*[\])]?\s*', '.',
                         cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip().lower()
        if _EMAIL_RE.fullmatch(cleaned) and not any(h in cleaned for h in _JUNK_EMAIL_HINTS):
            return cleaned
    return ""

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
    if not OpenAI or not OPENAI_KEY:
        return ""
        
    retries = 3
    for attempt in range(retries):
        try:
            client = OpenAI(api_key=OPENAI_KEY, base_url=OPENAI_BASE_URL)
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
            model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.choices[0].message.content.strip()
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
                print(f"   [OpenAI Error] {e}")
                return ""
    return ""

def scrape_linkedin_jobs_locally(roles, locations, max_items, session=None):
    """Scrape job cards via LinkedIn's keyless guest API (no login wall).

    The `jobs-guest/.../seeMoreJobPostings/search` endpoint returns the raw
    `base-card` HTML that the site lazy-loads on scroll, paginated by `start`
    in steps of 25. This works logged-out, unlike the full search page.
    """
    session = session or requests.Session()
    jobs_found = []
    seen_urls = set()

    for role in roles:
        for loc in locations:
            if len(jobs_found) >= max_items:
                break
            q_role = urllib.parse.quote(role)
            q_loc = urllib.parse.quote(loc)
            start = 0
            while len(jobs_found) < max_items:
                search_url = (
                    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                    f"?keywords={q_role}&location={q_loc}&f_TPR=r2592000&start={start}"
                )
                try:
                    res = session.get(search_url, headers=HEADERS, timeout=15)
                    # 429 = throttled, 400 = ran past the last page.
                    if res.status_code != 200:
                        break
                    soup = BeautifulSoup(res.text, 'html.parser')
                    cards = soup.find_all('div', class_='base-card')
                    if not cards:
                        break  # no more results for this role/location

                    for card in cards:
                        if len(jobs_found) >= max_items:
                            break
                        title_el = card.find('h3', class_='base-search-card__title')
                        company_el = card.find('h4', class_='base-search-card__subtitle')
                        loc_el = card.find('span', class_='job-search-card__location')
                        link_el = card.find('a', class_='base-card__full-link')

                        if title_el and company_el and link_el:
                            link = link_el.get('href', '').split('?')[0]
                            if not link or link in seen_urls:
                                continue  # dedupe across role/location combos
                            seen_urls.add(link)
                            jobs_found.append({
                                "title": title_el.text.strip(),
                                "company": company_el.text.strip(),
                                "location": loc_el.text.strip() if loc_el else "Unknown",
                                "url": link,
                            })
                except Exception as e:
                    print(f"   [Error scraping {role} in {loc}] {e}")
                    break

                start += 25
                time.sleep(1 + random.random())  # polite jitter between pages

    return jobs_found

def get_job_description(url, session=None):
    session = session or requests
    try:
        res = session.get(url, headers=HEADERS, timeout=15)
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

    # AI is only a fallback now (regex handles most emails), so a missing key
    # is a soft warning rather than a hard stop.
    if not OPENAI_KEY:
        print("⚠️ No OpenAI key set — will extract emails via regex only (AI fallback disabled).")

    roles_input = os.environ.get("HUNTER_ROLES", "Python Developer")
    locations_input = os.environ.get("HUNTER_LOCATIONS", "Remote")
    roles = [r.strip() for r in roles_input.split(',') if r.strip()]
    locations = [l.strip() for l in locations_input.split(',') if l.strip()]
    max_items = int(os.environ.get("HUNTER_MAX", 20))

    print(f"Roles: {', '.join(roles)}")
    print(f"Locations: {', '.join(locations)}")
    print("Scraping LinkedIn locally (No Apify credits required!)...")

    session = requests.Session()
    jobs = scrape_linkedin_jobs_locally(roles, locations, max_items, session=session)
    print(f"Found {len(jobs)} active jobs. Fetching descriptions in parallel...")

    # Fetch all descriptions concurrently — this used to be the slowest part.
    def _fetch(item):
        return item, get_job_description(item["url"], session=session)

    described = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch, item) for item in jobs]
        for future in as_completed(futures):
            try:
                described.append(future.result())
            except Exception:
                pass

    existing_emails = load_existing_emails()
    new_auto_leads = []
    new_manual_jobs = []
    ai_calls = 0

    for item, description in described:
        company = item["company"]
        role = item["title"]
        location = item["location"]
        job_url = item["url"]

        print(f"\nAnalyzing Job: {company[:20]} - {role[:30]}...")

        if not description or len(description) < 20:
            print("   ⚠️ Could not load full description. Saving to Manual Jobs.")
            new_manual_jobs.append({
                "company": company, "role": role,
                "location": location, "link": job_url,
            })
            continue

        # Regex first (free/instant); only spend an AI call when it finds nothing.
        email = extract_email_regex(description)
        if not email and OPENAI_KEY:
            email = ask_ai_for_email(description, company, role)
            ai_calls += 1
            time.sleep(2)  # brief pace between AI calls to respect rate limits

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
                "company": company, "role": role,
                "location": location, "link": job_url,
            })

    print(f"\n(AI fallback used on {ai_calls}/{len(described)} jobs)")

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
