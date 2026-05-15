"""
hunter.py — Role-based company discovery engine.

Features:
  - Experience level: fresher, junior, mid, senior, lead, executive
  - Company size filter: startup, small, mid, large, mnc
  - Multi-engine: DuckDuckGo → Bing → Google → Yahoo → Brave
  - Two-phase: get URLs from search → visit pages → extract career emails
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
                   'duckduckgo.com', 'bing.com', 'microsoft.com',
                   'brave.com', 'yahoo.com', 'yandex.com'}

GENERIC_PROVIDERS = {'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
                     'protonmail.com', 'aol.com', 'live.com', 'icloud.com',
                     'yahoo.co.in', 'rediffmail.com'}

SKIP_SITES = ['linkedin.com', 'indeed.com', 'glassdoor.com', 'youtube.com',
              'facebook.com', 'twitter.com', 'wikipedia.org', 'quora.com',
              'reddit.com', 'instagram.com', 'pinterest.com', 'amazon.com',
              'naukri.com']

BAD_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg',
                  '.css', '.js', '.woff', '.ttf', '.ico', '.mp4', '.mp3'}


# ── Experience level keywords ────────────────
EXP_KEYWORDS = {
    'any':       ['hiring', 'openings', 'vacancy'],
    'fresher':   ['fresher', 'entry level', 'graduate', 'trainee', '0-1 years', 'campus', 'intern'],
    'junior':    ['junior', '1-2 years', '1-3 years', 'associate', 'early career'],
    'mid':       ['mid level', 'mid-level', '3-5 years', '2-5 years', 'experienced'],
    'senior':    ['senior', '5+ years', '5-10 years', 'lead', 'experienced professional'],
    'lead':      ['lead', 'manager', 'team lead', '10+ years', 'principal', 'head of'],
    'executive': ['director', 'VP', 'CTO', 'executive', 'chief', 'C-level', 'head'],
}

# ── Company size keywords ────────────────────
SIZE_KEYWORDS = {
    'any':     ['company'],
    'startup': ['startup', 'early stage', 'seed funded', 'small team', 'bootstrap'],
    'small':   ['small company', 'growing company', 'SMB', 'small business'],
    'mid':     ['mid-size company', 'mid size', 'growing enterprise', 'scale-up'],
    'large':   ['enterprise', 'large company', 'corporation', 'established'],
    'mnc':     ['MNC', 'Fortune 500', 'multinational', 'global company', 'top company'],
}


def generate_queries(roles, locations, experience, company_size):
    """Generate smart search queries using all filters."""
    queries = []

    exp_kws = EXP_KEYWORDS.get(experience, EXP_KEYWORDS['any'])
    size_kws = SIZE_KEYWORDS.get(company_size, SIZE_KEYWORDS['any'])

    for role in roles:
        # Core queries with experience
        for ekw in exp_kws[:2]:
            queries.append(f'{role} {ekw} careers email apply')
            queries.append(f'{role} {ekw} company HR email')

        # Core queries with company size
        for skw in size_kws[:2]:
            queries.append(f'{role} {skw} hiring email')
            queries.append(f'{role} {skw} careers contact')

        # Combined experience + size
        queries.append(f'{role} {exp_kws[0]} {size_kws[0]} hiring email')

        # Location-specific
        for loc in locations:
            queries.append(f'{role} {exp_kws[0]} {loc} company careers email')
            queries.append(f'{role} {size_kws[0]} {loc} hiring contact HR')

        # General fallbacks
        queries.append(f'{role} companies list HR data email')
        queries.append(f'"{role}" hiring contact email resume')
        queries.append(f'"send resume" "{role}" {exp_kws[0]} company')

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


# ══════════════════════════════════════════════
# SEARCH ENGINES (5 engines with fallback)
# ══════════════════════════════════════════════

def _make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def search_duckduckgo(query, session):
    """DuckDuckGo HTML search."""
    url = f'https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}'
    try:
        res = session.get(url, timeout=20)
        if res.status_code != 200:
            return []
        if 'captcha' in res.text.lower() or 'anomaly' in res.text.lower():
            return []

        soup = BeautifulSoup(res.text, 'html.parser')
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
        return urls
    except:
        return []


def search_bing(query, session):
    """Bing search."""
    url = f'https://www.bing.com/search?q={urllib.parse.quote(query)}&count=15'
    try:
        res = session.get(url, timeout=20)
        if res.status_code != 200:
            return []
        soup = BeautifulSoup(res.text, 'html.parser')
        urls = []
        for li in soup.find_all('li', class_='b_algo'):
            a = li.find('a')
            if a and a.get('href', '').startswith('http'):
                urls.append(a['href'])
        if not urls:
            for h2 in soup.find_all('h2'):
                a = h2.find('a')
                if a:
                    href = a.get('href', '')
                    if href.startswith('http') and 'bing.com' not in href:
                        urls.append(href)
        return urls[:15]
    except:
        return []


def search_google(query, session):
    """Google search (scrape)."""
    url = f'https://www.google.com/search?q={urllib.parse.quote(query)}&num=10'
    try:
        res = session.get(url, timeout=20)
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


def search_yahoo(query, session):
    """Yahoo search."""
    url = f'https://search.yahoo.com/search?p={urllib.parse.quote(query)}&n=10'
    try:
        res = session.get(url, timeout=20)
        if res.status_code != 200:
            return []
        soup = BeautifulSoup(res.text, 'html.parser')
        urls = []
        for a in soup.find_all('a', class_='d-ib'):
            href = a.get('href', '')
            if href.startswith('http') and 'yahoo.com' not in href:
                urls.append(href)
        # Fallback: any external <a> in result divs
        if not urls:
            for div in soup.find_all('div', class_='dd'):
                for a in div.find_all('a'):
                    href = a.get('href', '')
                    if href.startswith('http') and 'yahoo.com' not in href:
                        urls.append(href)
        # Broader fallback: RU links (Yahoo redirect)
        if not urls:
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if 'RU=' in href:
                    try:
                        real = urllib.parse.unquote(href.split('RU=')[1].split('/')[0])
                        if real.startswith('http'):
                            urls.append(real)
                    except:
                        pass
        return urls[:15]
    except:
        return []


def search_brave(query, session):
    """Brave search."""
    url = f'https://search.brave.com/search?q={urllib.parse.quote(query)}'
    try:
        res = session.get(url, timeout=20)
        if res.status_code != 200:
            return []
        soup = BeautifulSoup(res.text, 'html.parser')
        urls = []
        for a in soup.find_all('a', class_='result-header'):
            href = a.get('href', '')
            if href.startswith('http'):
                urls.append(href)
        if not urls:
            for a in soup.find_all('a', attrs={'data-type': 'web'}):
                href = a.get('href', '')
                if href.startswith('http') and 'brave.com' not in href:
                    urls.append(href)
        return urls[:15]
    except:
        return []


ENGINES = [
    ("DuckDuckGo", search_duckduckgo),
    ("Bing", search_bing),
    ("Google", search_google),
    ("Yahoo", search_yahoo),
    ("Brave", search_brave),
]


def get_result_urls(query, session):
    """Try all engines in order, return URLs from the first that works."""
    for name, fn in ENGINES:
        urls = fn(query, session)
        if urls:
            return urls, name
        time.sleep(0.5)
    return [], "None"


def scrape_emails_from_url(url, session):
    """Visit a URL and extract email addresses from its content."""
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


# ══════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════

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
    experience = os.environ.get("HUNTER_EXPERIENCE", "any")
    company_size = os.environ.get("HUNTER_COMPANY_SIZE", "any")

    roles = [r.strip() for r in roles_input.split(',') if r.strip()]
    locations = [l.strip() for l in locations_input.split(',') if l.strip()]

    if not roles:
        print("No roles specified. Set roles in Settings.")
        return

    exp_labels = {'any':'Any','fresher':'Fresher','junior':'Junior','mid':'Mid-Level',
                  'senior':'Senior','lead':'Lead/Manager','executive':'Executive'}
    size_labels = {'any':'Any','startup':'Startup','small':'Small','mid':'Mid-size',
                   'large':'Enterprise','mnc':'MNC'}

    print(f"Roles:       {', '.join(roles)}")
    print(f"Locations:   {', '.join(locations)}")
    print(f"Experience:  {exp_labels.get(experience, experience)}")
    print(f"Company Size:{size_labels.get(company_size, company_size)}")

    queries = generate_queries(roles, locations, experience, company_size)
    queries = queries[:max_queries]
    existing_emails = load_existing_emails()
    bounced = load_bounced_domains()

    print(f"Existing leads: {len(existing_emails)}")
    print(f"Search queries: {len(queries)}")
    print(f"Bounced domains: {len(bounced)}\n")

    session = _make_session()
    new_firms = []
    visited_urls = set()
    engine_stats = {}

    for qi, query in enumerate(queries, 1):
        print(f"\n[{qi}/{len(queries)}] Searching: {query[:65]}...")

        result_urls, engine = get_result_urls(query, session)
        engine_stats[engine] = engine_stats.get(engine, 0) + 1
        print(f"   Engine: {engine} | URLs: {len(result_urls)}")

        if not result_urls:
            print(f"   No results from any engine.")
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
                        "notes": f"Hunted for '{role}' ({exp_labels.get(experience,'')}, {size_labels.get(company_size,'')})"
                    })
                    existing_emails.add(email)
                    print(f"   Found: {company_name} ({email})")

            time.sleep(1)

    # Save
    print(f"\n{'='*56}")
    print(f"  HUNTER SUMMARY")
    print(f"{'='*56}")
    print(f"  Experience:   {exp_labels.get(experience, experience)}")
    print(f"  Company Size: {size_labels.get(company_size, company_size)}")
    print(f"  Pages visited: {len(visited_urls)}")
    print(f"  Engines used: {', '.join(f'{k}({v})' for k,v in engine_stats.items())}")
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
        print("  Possible reasons:")
        print("    - Search engines blocking (captcha/rate limit)")
        print("    - Internet connection issues")
        print("    - Very niche role/filters — try broader search")

    print(f"{'='*56}\n")


if __name__ == "__main__":
    hunt_for_companies()
