"""
hunter.py — Role-based company discovery engine.

Features:
  - Experience level: fresher, junior, mid, senior, lead, executive
  - Company size filter: startup, small, mid, large, mnc
  - Multi-engine: DuckDuckGo → Bing → Brave → Yahoo → Google
  - Parallel engine querying for faster results
  - Two-phase: get URLs from search → visit pages → extract career emails
  - Email scoring system to filter low-quality leads
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
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from dotenv import load_dotenv
from core.email_validator import verify_mx, is_generic_email, flush_mx_cache

# MX lookup cache
_mx_cache = {}

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Force flush on every print so logs stream to the dashboard in real-time
import builtins
_original_print = builtins.print
def _flush_print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _original_print(*args, **kwargs)
builtins.print = _flush_print

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMS_CSV = os.path.join(BASE_DIR, "firms.csv")
ENV_FILE = os.path.join(BASE_DIR, ".env")
BOUNCED_JSON = os.path.join(BASE_DIR, "bounced_domains.json")

from filelock import FileLock
file_lock = FileLock(os.path.join(BASE_DIR, 'jobhunter.lock'), timeout=30)

load_dotenv(ENV_FILE)
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080").rstrip('/')
# Query several engines so a single blocked engine doesn't zero out results.
SEARXNG_ENGINES = os.getenv("SEARXNG_ENGINES", "google,bing,duckduckgo,brave")

# In-process cache of SearXNG results, keyed by query. Avoids re-hitting the
# instance for repeated identical queries within a single hunt run.
_searxng_cache = {}
_SEARXNG_CACHE_TTL = 900  # seconds
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,8}\b')

VALID_EMAIL_KEYWORDS = ['hr@', 'career', 'job', 'join', 'talent', 'resume',
                        'recruit', 'hiring', 'careers@']

INVALID_DOMAINS = {'example.com', 'email.com', 'yourdomain.com', 'test.com',
                   'domain.com', 'sentry.io', 'wixpress.com', 'w3.org',
                   'schema.org', 'googleapis.com', 'cloudflare.com',
                   'wordpress.org', 'jquery.com', 'bootstrapcdn.com',
                   'google.com', 'facebook.com', 'twitter.com', 'x.com',
                   'gstatic.com', 'gravatar.com', 'recaptcha.net',
                   'duckduckgo.com', 'bing.com', 'microsoft.com',
                   'brave.com', 'yahoo.com', 'yandex.com', 'github.com'}

GENERIC_PROVIDERS = {'gmail', 'yahoo', 'outlook', 'hotmail',
                     'protonmail', 'aol', 'live', 'icloud',
                     'rediffmail'}

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
    'large':   ['"enterprise"', '"large company"', '"corporation"', '"established"'],
    'mnc':     ['"Fortune 500"', '"global enterprise"', '"multinational"', '"top companies"', '"industry leader"'],
}

# ── Target Type keywords ─────────────────────
TYPE_KEYWORDS = {
    'both':       [''],
    'job':        ['job', 'full time'],
    'internship': ['internship', 'intern', 'stipend'],
    'trainee':    ['trainee', 'apprentice', 'graduate program'],
}


def generate_queries(roles, locations, experience, company_size, target_type):
    """Generate smart search queries using all filters."""
    queries = []

    exp_kws = EXP_KEYWORDS.get(experience, EXP_KEYWORDS['any'])
    size_kws = SIZE_KEYWORDS.get(company_size, SIZE_KEYWORDS['any'])
    type_kw = TYPE_KEYWORDS.get(target_type, TYPE_KEYWORDS['both'])[0]
    
    type_prefix = f"{type_kw} " if type_kw else ""

    for role in roles:
        # Move urlparse import to module level for performance
        # (currently not used in this loop, but added for future use)
        
        # Core queries with experience
        for ekw in exp_kws[:2]:
            queries.append(f'{type_prefix}{role} {ekw} careers email apply')
            queries.append(f'{type_prefix}{role} {ekw} company HR email')

        # Core queries with company size
        for skw in size_kws[:2]:
            queries.append(f'{type_prefix}{role} {skw} hiring email')
            queries.append(f'{type_prefix}{role} {skw} careers contact')

        # Combined experience + size
        queries.append(f'{type_prefix}{role} {exp_kws[0]} {size_kws[0]} hiring email')

        # Location-specific
        for loc in locations:
            queries.append(f'{type_prefix}{role} {exp_kws[0]} {loc} company careers email')
            queries.append(f'{type_prefix}{role} {size_kws[0]} {loc} hiring contact HR')

        # Career page specific queries
        queries.append(f'{type_prefix}{role} company "careers page" email apply')
        queries.append(f'{type_prefix}{role} "we are hiring" email HR contact')
        queries.append(f'{type_prefix}{role} "apply now" company email india')
        queries.append(f'{type_prefix}{role} "open positions" company HR email')

        # Job board and aggregator queries
        queries.append(f'{type_prefix}site:angel.co {role} hiring')
        queries.append(f'{type_prefix}{role} "send your resume to" OR "mail your resume"')

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
            with file_lock:
                with open(FIRMS_CSV, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row.get("contact_email"):
                            existing.add(row["contact_email"].lower().strip())
        except Exception as e:
            print(f"Warning: Could not load existing emails: {e}")
    return existing


def load_existing_domains():
    """Load domains already present in firms.csv for dedup during hunt."""
    domains = set()
    if os.path.exists(FIRMS_CSV):
        try:
            with file_lock:
                with open(FIRMS_CSV, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        email = row.get("contact_email", "")
                        if email and '@' in email:
                            domains.add(email.split('@')[1].lower().strip())
        except Exception as e:
            print(f"Warning: Could not load existing domains: {e}")
    return domains


def load_existing_leads():
    """Read firms.csv once and return (emails, domains) sets for dedup.
    Replaces the two separate full-file reads done by load_existing_emails()
    and load_existing_domains().
    """
    emails = set()
    domains = set()
    if os.path.exists(FIRMS_CSV):
        try:
            with file_lock:
                with open(FIRMS_CSV, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        email = (row.get("contact_email") or "").lower().strip()
                        if email:
                            emails.add(email)
                            if '@' in email:
                                domains.add(email.split('@')[1])
        except Exception as e:
            print(f"Warning: Could not load existing leads: {e}")
    return emails, domains


def load_bounced_domains():
    if os.path.exists(BOUNCED_JSON):
        try:
            with file_lock:
                with open(BOUNCED_JSON, 'r') as f:
                    return set(json.load(f))
        except Exception as e:
            print(f"Warning: Could not load bounced domains: {e}")
    return set()


# ── Email Scoring System ─────────────────────
HR_PREFIXES = {'hr', 'careers', 'recruitment', 'hiring'}
GENERIC_PREFIXES = {'info', 'admin', 'support', 'contact', 'sales', 'marketing'}
FREEMAIL_DOMAINS = {'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com'}

def score_email(email, url="", company_name=""):
    """Score an email lead. Higher = more likely a real HR contact.
    Returns an integer score; only leads with score >= 1 should be kept.
    """
    if "@" not in email:
        return 0
    score = 0
    email_lower = email.lower()
    prefix = email_lower.split('@')[0]
    domain = email_lower.split('@')[1]

    # +3 for HR-related prefixes
    if prefix in HR_PREFIXES or prefix.startswith(tuple(HR_PREFIXES)):
        score += 3

    # +2 for domain matching or containing company_name
    if company_name:
        company_clean = company_name.lower().replace(' ', '').replace('-', '')
        domain_clean = domain.split('.')[0].replace('-', '')
        if company_clean and (company_clean in domain_clean or domain_clean in company_clean):
            score += 2

    # +1 for email found on a careers/jobs/about page
    url_lower = url.lower()
    if any(kw in url_lower for kw in ['/careers', '/jobs', '/about', '/work-with-us', '/join', '/hiring']):
        score += 1

    # -2 for generic prefixes
    if prefix in GENERIC_PREFIXES:
        score -= 2

    # -3 for freemail providers
    if domain in FREEMAIL_DOMAINS:
        score -= 3

    return score



def is_valid_email(email):
    email = email.lower().strip()
    if not EMAIL_REGEX.fullmatch(email):
        return False
    domain = email.split('@')[1]
    prefix = email.split('@')[0]
    
    if domain in INVALID_DOMAINS:
        return False
        
    # Intelligent freemail filtering: 
    # Only allow freemail (gmail, yahoo, etc.) if it clearly belongs to HR or recruitment
    freemail_domains = ['yahoo.com', 'outlook.com', 'hotmail.com', 'protonmail.com', 'aol.com', 'live.com', 'icloud.com', 'rediffmail.com', 'gmail.com']
    if domain in freemail_domains or domain in GENERIC_PROVIDERS:
        if not (prefix in HR_PREFIXES or prefix.startswith(('hr', 'career', 'recruit', 'hire', 'job'))):
            return False
            
    if is_generic_email(email): # exclude info/admin/support
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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1.2 Safari/605.1.15",
]

def _make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1"
    })
    return s



# Markers that indicate the engine served a block / CAPTCHA page.
BLOCK_MARKERS = ('captcha', 'anomaly', 'unusual traffic', 'are you a robot',
                 'verify you are human', 'detected unusual')


def _looks_blocked(text):
    low = text[:4000].lower()
    return any(m in low for m in BLOCK_MARKERS)


def _request_with_retry(session, url, *, timeout=20, retries=3, allow_redirects=True):
    """GET with exponential backoff + per-request UA rotation.

    Returns the Response on success, or None if all attempts fail or the
    response looks like a block/CAPTCHA page.
    """
    backoff = 1.5
    for attempt in range(retries):
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            res = session.get(url, timeout=timeout, allow_redirects=allow_redirects,
                              headers=headers)
            if res.status_code == 429:
                time.sleep(backoff ** (attempt + 1))
                continue
            if res.status_code != 200:
                return None
            if _looks_blocked(res.text):
                return None
            return res
        except requests.RequestException:
            time.sleep(backoff ** attempt)
    return None


def _restart_searxng():
    """Restart the SearXNG container, trying Docker Compose v2 then v1."""
    import subprocess
    for cmd in (["docker", "compose", "restart", "searxng"],
                ["docker-compose", "restart", "searxng"]):
        try:
            subprocess.run(cmd, cwd=BASE_DIR, timeout=30, capture_output=True)
            time.sleep(5)  # give the container a few seconds to boot
            return True
        except FileNotFoundError:
            continue  # this compose CLI isn't installed, try the next
        except Exception as e:
            print(f"   [SearXNG Restart Failed] {e}")
            return False
    print("   [SearXNG] No docker/docker-compose CLI found; skipping restart.")
    return False


def search_searxng(query, session):
    """Query a SearXNG instance (keyless, metasearch) and return result URLs.

    Aggregates several engines so one blocked engine doesn't zero out results.
    Results are cached per-query for the run; the container is only restarted
    when a query genuinely returns nothing while engines report as unresponsive.
    """
    if not SEARXNG_URL:
        return []

    cached = _searxng_cache.get(query)
    if cached and (time.time() - cached[0]) < _SEARXNG_CACHE_TTL:
        return cached[1]

    url = (f"{SEARXNG_URL}/search?q={urllib.parse.quote(query)}"
           f"&format=json&language=en&safesearch=0&engines={SEARXNG_ENGINES}")

    def _execute():
        res = session.get(url, timeout=20,
                          headers={"User-Agent": random.choice(USER_AGENTS),
                                   "Accept": "application/json",
                                   "X-Forwarded-For": "127.0.0.1",
                                   "X-Real-IP": "127.0.0.1"})
        if res.status_code != 200:
            raise Exception(f"HTTP {res.status_code}")

        data = res.json()
        urls = []
        for item in data.get("results", []):
            u = item.get("url", "")
            if u.startswith("http"):
                urls.append(u)

        # Only treat as a failure worth restarting for if we got NOTHING back
        # while engines were reported unresponsive (i.e. all blocked/throttled).
        if not urls and data.get("unresponsive_engines"):
            raise Exception("No results; engines unresponsive/blocked")
        return urls[:20]

    try:
        urls = _execute()
    except Exception as e:
        print(f"   [SearXNG Issue] {e}. Restarting container and retrying once...")
        if _restart_searxng():
            try:
                urls = _execute()
            except Exception as retry_e:
                print(f"   [SearXNG Retry Failed] {retry_e}")
                urls = []
        else:
            urls = []

    _searxng_cache[query] = (time.time(), urls)
    return urls


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
                except Exception:
                    pass
            elif href.startswith('http'):
                urls.append(href)
        return urls
    except Exception:
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
    except Exception:
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
    except Exception:
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
                    except Exception:
                        pass
        return urls[:15]
    except Exception:
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
    except Exception:
        return []


ENGINES = [
    ("DuckDuckGo", search_duckduckgo),
    ("Bing", search_bing),
    ("Brave", search_brave),
    ("Yahoo", search_yahoo),
    ("Google", search_google),
]


def get_result_urls(query, session):
    """SearXNG first (keyless, reliable); fall back to scraped engines."""
    merged_urls = []
    engines_used = []
    seen = set()

    # ── Primary: SearXNG (local/self-hosted, no key) ──
    sx_urls = search_searxng(query, session)
    if sx_urls:
        engines_used.append("SearXNG")
        for u in sx_urls:
            if u not in seen:
                seen.add(u)
                merged_urls.append(u)
        return merged_urls, "SearXNG"

    def _run_engine(name, fn):
        time.sleep(0.2)  # slight stagger to avoid simultaneous hits
        return name, fn(query, session)

    # Try first 3 engines in parallel
    batch = ENGINES[:3]
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_run_engine, name, fn): name for name, fn in batch}
        try:
            for future in as_completed(futures, timeout=30):
                try:
                    name, urls = future.result()
                    if urls:
                        engines_used.append(name)
                        for u in urls:
                            if u not in seen:
                                seen.add(u)
                                merged_urls.append(u)
                except Exception as e:
                    pass
        except TimeoutError:
            print("   [Timeout] Some search engines took too long to respond.")

    # If parallel batch returned nothing, fall back to remaining engines sequentially
    if not merged_urls:
        for name, fn in ENGINES[3:]:
            time.sleep(1.5)  # rate limiting between search engine requests
            urls = fn(query, session)
            if urls:
                engines_used.append(name)
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        merged_urls.append(u)
                break  # got results, stop fallback

    engine_label = '+'.join(engines_used) if engines_used else "None"
    return merged_urls, engine_label


# Matches obfuscated emails like "name [at] company [dot] com" or
# "name (at) company (dot) com" or "name at company dot com".
_OBFUSCATED_RE = re.compile(
    r'([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+)\s*'
    r'([A-Za-z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+)\s*'
    r'([A-Za-z]{2,8})',
    re.IGNORECASE,
)


def _extract_emails(html):
    """Pull emails from raw regex, mailto: links, and obfuscated forms."""
    found = set(EMAIL_REGEX.findall(html))

    # mailto: links are the highest-signal source
    for m in re.findall(r'mailto:([^"\'>?\s]+)', html, re.IGNORECASE):
        addr = m.strip().lower()
        if '@' in addr:
            found.add(addr)

    # de-obfuscate "name [at] company [dot] com"
    for user, dom, tld in _OBFUSCATED_RE.findall(html):
        found.add(f"{user}@{dom}.{tld}".lower())

    return found


def scrape_emails_from_url(url, session):
    """Visit a URL and extract email addresses from its content."""
    if any(sd in url for sd in SKIP_SITES):
        return set()
    res = _request_with_retry(session, url, timeout=10, retries=2)
    if res is None:
        return set()
    return _extract_emails(res.text[:500000])


def deep_crawl_career_page(base_url, session):
    """Follow internal /careers, /jobs, /work-with-us links to find more email addresses."""
    emails = set()
    try:
        res = session.get(base_url, timeout=10, allow_redirects=True)
        if res.status_code != 200:
            return emails

        soup = BeautifulSoup(res.text, 'html.parser')

        # Find career-related internal links
        career_keywords = ['career', 'job', 'hiring', 'work-with', 'join-us', 'openings', 'apply', 'vacancy']
        career_links = set()

        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if any(kw in href for kw in career_keywords):
                # Resolve relative URLs
                full_url = href
                if href.startswith('/'):
                    parsed = urlparse(base_url)
                    full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                elif not href.startswith('http'):
                    full_url = base_url.rstrip('/') + '/' + href

                if full_url.startswith('http'):
                    career_links.add(full_url)

        # Visit up to 3 career subpages
        for link in list(career_links)[:3]:
            try:
                sub_res = session.get(link, timeout=8, allow_redirects=True)
                if sub_res.status_code == 200:
                    emails.update(EMAIL_REGEX.findall(sub_res.text[:300000]))
            except Exception:
                pass
            time.sleep(0.5)
    except Exception:
        pass
    return emails


# ══════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════

def hunt_for_companies():
    """Main hunter: search -> follow URLs -> scrape emails from pages."""
    print(f"\n{'='*56}")
    print(f"  AUTO HUNTER - Multi-Engine Email Discovery")
    print(f"{'='*56}\n")

    # Config
    roles_input = os.environ.get("HUNTER_ROLES", os.getenv("ROLES", "Software Developer, Software Intern"))
    locations_input = os.environ.get("HUNTER_LOCATIONS", os.getenv("LOCATIONS", "Remote, India"))
    try:
        max_queries = int(os.environ.get("HUNTER_MAX", "15"))
    except ValueError:
        max_queries = 15
    delay = int(os.environ.get("HUNTER_DELAY", "3"))
    experience = os.environ.get("HUNTER_EXPERIENCE", "any")
    company_size = os.environ.get("HUNTER_COMPANY_SIZE", "any")
    target_type = os.environ.get("HUNTER_TARGET_TYPE", "both")

    roles = [r.strip() for r in roles_input.split(',') if r.strip()]
    locations = [l.strip() for l in locations_input.split(',') if l.strip()]

    if not roles:
        print("No roles specified. Set roles in Settings.")
        return

    exp_labels = {'any':'Any','fresher':'Fresher','junior':'Junior','mid':'Mid-Level',
                  'senior':'Senior','lead':'Lead/Manager','executive':'Executive'}
    size_labels = {'any':'Any','startup':'Startup','small':'Small','mid':'Mid-size',
                   'large':'Enterprise','mnc':'MNC'}
    type_labels = {'both':'Job & Internship', 'job':'Job Only', 'internship':'Internship Only', 'trainee':'Trainee Only'}

    print(f"Roles:       {', '.join(roles)}")
    print(f"Locations:   {', '.join(locations)}")
    print(f"Experience:  {exp_labels.get(experience, experience)}")
    print(f"Company Size:{size_labels.get(company_size, company_size)}")
    print(f"Target Type: {type_labels.get(target_type, target_type)}")

    queries = generate_queries(roles, locations, experience, company_size, target_type)
    queries = queries[:max_queries]
    existing_emails, existing_domains = load_existing_leads()
    bounced = load_bounced_domains()

    print(f"Existing leads: {len(existing_emails)}")
    print(f"Existing domains: {len(existing_domains)}")
    print(f"Search queries: {len(queries)}")
    print(f"Bounced domains: {len(bounced)}\n")

    session = _make_session()
    new_firms = []
    visited_urls = set()
    engine_stats = {}

    try:
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

            # Visit top pages and scrape emails using multi-threading
            pages_to_check = []
            for url in result_urls:
                if url in visited_urls or len(pages_to_check) >= 8:
                    continue

                try:
                    url_domain = urlparse(url).netloc.lower().replace('www.', '')
                    if url_domain in existing_domains:
                        continue
                except Exception:
                    pass

                visited_urls.add(url)
                if not any(sd in url for sd in SKIP_SITES):
                    pages_to_check.append(url)

            def _process_url(url):
                try:
                    raw = scrape_emails_from_url(url, session)
                    if not any(skip in url for skip in ['indeed', 'glassdoor', 'naukri', 'linkedin']):
                        deep = deep_crawl_career_page(url, session)
                        raw = raw.union(deep)
                    return url, raw
                except Exception:
                    return url, set()

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(_process_url, u) for u in pages_to_check]
                for future in as_completed(futures):
                    url, raw_emails = future.result()
                    
                    for email in raw_emails:
                        email = email.lower().strip()
                        email = re.sub(r'^(u003e|u003c|x22|22)+', '', email)
                        if not '@' in email: continue
                        
                        prefix = email.split('@')[0]
                        if prefix in {'info', 'admin', 'support', 'contact', 'sales', 'hello', 'team'}: continue
                        
                        domain = email.split('@')[1]

                        if (email not in existing_emails
                                and is_valid_email(email)
                                and domain not in bounced
                                and verify_mx(domain)):

                            company_name = extract_company_name(email)

                            email_score = score_email(email, url, company_name)
                            if email_score < 1:
                                print(f"   Skipped (score={email_score}): {email}")
                                continue

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
                                "notes": f"Hunted for '{role}' ({exp_labels.get(experience,'')}, {size_labels.get(company_size,'')}) [score={email_score}]",
                                "type": target_type if target_type != 'both' else 'job'
                            })
                            existing_emails.add(email)
                            existing_domains.add(domain)
                            print(f"   Found (score={email_score}): {company_name} ({email})")

            time.sleep(delay)  # rate limiting between queries
    except KeyboardInterrupt:
        print("\n[!] Hunter stopped by user. Saving leads found so far...")
    except Exception as e:
        print(f"\n[!] Hunter encountered an error: {e}")
        print("    Saving leads found so far...")

    # Persist any buffered MX lookups so the next run reuses them.
    flush_mx_cache()

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
        with file_lock:
            with open(FIRMS_CSV, "a", newline='', encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["company_name", "contact_email", "role", "hr_name", "notes", "type"])
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
