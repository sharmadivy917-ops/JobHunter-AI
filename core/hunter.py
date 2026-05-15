"""
hunter.py — Role-based company discovery engine.

Multi-engine strategy:
  1. Try DuckDuckGo HTML with session/cookies (handles some anti-bot)
  2. Fallback to Bing search
  3. Two-phase: get URLs from search → visit pages → extract career emails

The key insight: search engines DON'T show email addresses in snippets.
We must follow the result URLs and scrape the destination pages.
"""
import requests
from bs4 import BeautifulSoup
import re
import csv
import os
import json
import time
import io
import sys
import urllib.parse
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMS_CSV = os.path.join(BASE_DIR, "firms.csv")
ENV_FILE = os.path.join(BASE_DIR, ".env")
BOUNCED_JSON = os.path.join(BASE_DIR, "bounced_domains.json")

load_dotenv(ENV_FILE)

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}')

VALID_EMAIL_KEYWORDS = ['hr@', 'career', 'job', 'join', 'talent', 'resume',
                        'recruit', 'hiring', 'info@', 'contact@', 'admin@',
                        'office@', 'apply', 'enquir', 'support@']

INVALID_DOMAINS = {'example.com', 'email.com', 'yourdomain.com', 'test.com',
                   'domain.com', 'sentry.io', 'wixpress.com', 'w3.org',
                   'schema.org', 'googleapis.com', 'cloudflare.com',
                   'wordpress.org', 'jquery.com', 'bootstrapcdn.com',
                   'google.com', 'facebook.com', 'twitter.com', 'x.com',
                   'gstatic.com', 'gravatar.com', 'recaptcha.net',
                   'duckduckgo.com', 'bing.com', 'microsoft.com'}

GENERIC_PROVIDERS = {'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
                     'protonmail.com', 'aol.com', 'live.com', 'icloud.com',
                     'yahoo.co.in', 'rediffmail.com'}

SKIP_SITES = ['linkedin.com', 'indeed.com', 'glassdoor.com', 'youtube.com',
              'facebook.com', 'twitter.com', 'wikipedia.org', 'quora.com',
              'reddit.com', 'instagram.com', 'pinterest.com', 'amazon.com']

BAD_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg',
                  '.css', '.js', '.woff', '.ttf', '.ico', '.mp4', '.mp3'}


def generate_queries(roles, locations):
    """Generate search queries targeting company career/contact pages."""
    queries = []
    for role in roles:
        # Direct queries for career pages
        queries.append(f'{role} company careers email apply')
        queries.append(f'{role} hiring company HR email India')
        queries.append(f'{role} startup hiring email resume')
        queries.append(f'{role} company contact HR recruitment')
        queries.append(f'"{role}" hiring freshers company email')
        queries.append(f'{role} companies list HR data email India')

        for loc in locations:
            queries.append(f'{role} company {loc} careers contact')
            queries.append(f'{role} hiring {loc} apply email HR')

    # Deduplicate
    seen = set()
    return [q for q in queries if q not in seen and not seen.add(q)]


def load_existing_emails():
    existing = set()
    if os.path.exists(FIRMS_CSV):
        try:
            with open(FIRMS_CSV, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("contact_email"):
                        existing.add(row["contact_email"].lower().strip())
        except:
            pass
    return existing


def load_bounced_domains():
    if os.path.exists(BOUNCED_JSON):
        try:
            with open(BOUNCED_JSON, 'r') as f:
                return set(json.load(f))
        except:
            pass
    return set()


def is_valid_email(email):
    """Check if email is a valid career-related company email."""
    email = email.lower().strip()
    if not EMAIL_REGEX.fullmatch(email):
        return False
    domain = email.split('@')[1]
    if domain in INVALID_DOMAINS or domain in GENERIC_PROVIDERS:
        return False
    if any(email.endswith(e) for e in BAD_EXTENSIONS):
        return False
    if len(domain.split('.')[0]) < 3:
        return False
    return any(k in email for k in VALID_EMAIL_KEYWORDS)


def extract_company_name(email):
    domain = email.split('@')[1]
    name = domain.split('.')[0]
    name = name.replace('-', ' ').replace('_', ' ')
    return ' '.join(w.capitalize() for w in name.split())


# ── Search Engines ────────────────────────────

def search_ddg(query, session):
    """Search DuckDuckGo HTML and return result URLs."""
    url = f'https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}'
    try:
        res = session.get(url, timeout=25)
        if res.status_code != 200:
            return []

        soup = BeautifulSoup(res.text, 'html.parser')

        # Check for captcha
        if 'captcha' in res.text.lower() or 'anomaly' in res.text.lower():
            return []

        urls = []
        for link in soup.find_all('a', class_='result__a'):
            href = link.get('href', '')
            if 'uddg=' in href:
                try:
                    real = urllib.parse.unquote(href.split('uddg=')[1].split('&')[0])
                    urls.append(real)
                except:
                    pass
            elif href.startswith('http'):
                urls.append(href)

        # Also try result__url class
        if not urls:
            for link in soup.find_all('a', class_='result__url'):
                href = link.get('href', '')
                if href.startswith('http'):
                    urls.append(href)

        return urls
    except:
        return []


def search_bing(query, session):
    """Search Bing and return result URLs."""
    url = f'https://www.bing.com/search?q={urllib.parse.quote(query)}&count=15'
    try:
        res = session.get(url, timeout=25)
        if res.status_code != 200:
            return []

        soup = BeautifulSoup(res.text, 'html.parser')
        urls = []

        # Try multiple selectors
        # Method 1: <h2><a href=...> inside <li class="b_algo">
        for li in soup.find_all('li', class_='b_algo'):
            a = li.find('a')
            if a and a.get('href', '').startswith('http'):
                urls.append(a['href'])

        # Method 2: Just find all h2 > a links
        if not urls:
            for h2 in soup.find_all('h2'):
                a = h2.find('a')
                if a and a.get('href', '').startswith('http'):
                    href = a['href']
                    if 'bing.com' not in href and 'microsoft.com' not in href:
                        urls.append(href)

        # Method 3: All external links
        if not urls:
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if (href.startswith('http')
                        and 'bing.com' not in href
                        and 'microsoft.com' not in href
                        and 'go.microsoft' not in href):
                    urls.append(href)

        return urls[:15]
    except:
        return []


def search_google(query, session):
    """Search Google and return result URLs."""
    url = f'https://www.google.com/search?q={urllib.parse.quote(query)}&num=10'
    try:
        res = session.get(url, timeout=25)
        if res.status_code != 200:
            return []

        soup = BeautifulSoup(res.text, 'html.parser')
        urls = []

        for a in soup.find_all('a'):
            href = a.get('href', '')
            if '/url?q=' in href:
                real = urllib.parse.unquote(href.split('/url?q=')[1].split('&')[0])
                if real.startswith('http'):
                    urls.append(real)

        return urls[:15]
    except:
        return []


def get_result_urls(query, session):
    """Try multiple search engines, return URLs from the first that works."""
    # Try DuckDuckGo first
    urls = search_ddg(query, session)
    if urls:
        return urls, "DDG"

    time.sleep(1)

    # Fallback to Bing
    urls = search_bing(query, session)
    if urls:
        return urls, "Bing"

    time.sleep(1)

    # Fallback to Google
    urls = search_google(query, session)
    if urls:
        return urls, "Google"

    return [], "None"


def scrape_emails_from_url(url, session):
    """Visit a URL and extract career email addresses from its content."""
    if any(sd in url for sd in SKIP_SITES):
        return set()
    try:
        res = session.get(url, timeout=10, allow_redirects=True)
        if res.status_code != 200:
            return set()
        text = res.text[:500000]
        return set(EMAIL_REGEX.findall(text))
    except:
        return set()


def hunt_for_companies():
    """Main hunter: search -> follow URLs -> scrape emails from pages."""
    print(f"\n{'='*56}")
    print(f"  AUTO HUNTER - Multi-Engine Email Discovery")
    print(f"{'='*56}\n")

    # Config
    roles_input = os.environ.get("HUNTER_ROLES", os.getenv("ROLES", "Software Developer"))
    locations_input = os.environ.get("HUNTER_LOCATIONS", os.getenv("LOCATIONS", "Remote, India"))
    max_queries = int(os.environ.get("HUNTER_MAX", "15"))
    delay = int(os.environ.get("HUNTER_DELAY", "3"))

    roles = [r.strip() for r in roles_input.split(',') if r.strip()]
    locations = [l.strip() for l in locations_input.split(',') if l.strip()]

    if not roles:
        print("No roles specified. Set roles in Settings.")
        return

    print(f"Roles: {', '.join(roles)}")
    print(f"Locations: {', '.join(locations)}")

    queries = generate_queries(roles, locations)
    queries = queries[:max_queries]
    existing_emails = load_existing_emails()
    bounced = load_bounced_domains()

    print(f"Existing leads: {len(existing_emails)}")
    print(f"Search queries: {len(queries)}")
    print(f"Bounced domains: {len(bounced)}\n")

    # Use a persistent session for cookies
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    new_firms = []
    visited_urls = set()
    engine_used = "None"

    for qi, query in enumerate(queries, 1):
        print(f"\n[{qi}/{len(queries)}] Searching: {query[:65]}...")

        result_urls, engine_used = get_result_urls(query, session)
        print(f"   Engine: {engine_used} | URLs: {len(result_urls)}")

        if not result_urls:
            print(f"   No results. Retrying after delay...")
            time.sleep(delay * 2)
            continue

        time.sleep(delay)

        # Visit top pages and scrape emails
        pages_checked = 0
        for url in result_urls:
            if url in visited_urls or pages_checked >= 5:
                continue
            visited_urls.add(url)

            if any(sd in url for sd in SKIP_SITES):
                continue

            pages_checked += 1
            raw_emails = scrape_emails_from_url(url, session)

            for email in raw_emails:
                email = email.lower().strip()
                domain = email.split('@')[1] if '@' in email else ''

                if (email not in existing_emails
                        and is_valid_email(email)
                        and domain not in bounced):

                    company_name = extract_company_name(email)

                    # Match role to query
                    role = roles[0]
                    for r in roles:
                        if r.lower() in query.lower():
                            role = r
                            break

                    new_firms.append({
                        "company_name": company_name,
                        "contact_email": email,
                        "role": role,
                        "hr_name": "HR Team",
                        "notes": f"Hunted for '{role}'"
                    })
                    existing_emails.add(email)
                    print(f"   Found: {company_name} ({email})")

            time.sleep(1)

    # Save
    print(f"\n{'='*56}")
    print(f"  HUNTER SUMMARY")
    print(f"{'='*56}")
    print(f"  Search engine: {engine_used}")
    print(f"  Pages visited: {len(visited_urls)}")
    print(f"  New Firms Found: {len(new_firms)}")

    if new_firms:
        file_exists = os.path.exists(FIRMS_CSV)
        with open(FIRMS_CSV, "a", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["company_name", "contact_email", "role", "hr_name", "notes"])
            if not file_exists:
                writer.writeheader()
            for firm in new_firms:
                writer.writerow(firm)
        print(f"  Saved to: {FIRMS_CSV}")
    else:
        print("  No new career emails found this run.")
        print("  This can happen if:")
        print("    - Search engines are blocking (captcha/rate limit)")
        print("    - Internet connection is slow")
        print("    - Try again in a few minutes")

    print(f"{'='*56}\n")


if __name__ == "__main__":
    hunt_for_companies()
