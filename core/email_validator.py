import os
import json
import smtplib
import time

try:
    import dns.resolver
    HAS_DNS = True
except ImportError:
    HAS_DNS = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MX_CACHE_FILE = os.path.join(BASE_DIR, "mx_cache.json")

# In-memory cache for MX lookups, backed by an on-disk file so results survive
# process restarts (hunter/sender/follow_up all run as separate subprocesses).
# Format: { "domain.com": [is_valid, timestamp] }
CACHE_TTL = 86400  # 24 hours


def _load_mx_cache():
    if os.path.exists(MX_CACHE_FILE):
        try:
            with open(MX_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


MX_CACHE = _load_mx_cache()
_mx_cache_dirty = 0  # Counter for unsaved cache misses


def _save_mx_cache():
    try:
        with open(MX_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(MX_CACHE, f)
    except Exception:
        pass


BAD_PREFIXES = {'info', 'admin', 'support', 'contact', 'sales', 'hello', 'team', 'abuse', 'jobseeker'}

def is_generic_email(email):
    prefix = email.split('@')[0].lower()
    return prefix in BAD_PREFIXES

def verify_mx(domain):
    """Check if a domain can receive email (MX or A record fallback)."""
    if not domain or len(domain) < 3:
        return False
        
    domain = domain.lower()
    
    # Check cache
    if domain in MX_CACHE:
        is_valid, timestamp = MX_CACHE[domain]
        if time.time() - timestamp < CACHE_TTL:
            return is_valid
            
    if not HAS_DNS:
        return True # Fallback if dnspython not installed
        
    is_valid = False
    try:
        if len(dns.resolver.resolve(domain, 'MX', lifetime=5)) > 0:
            is_valid = True
    except Exception:
        try:
            if len(dns.resolver.resolve(domain, 'A', lifetime=5)) > 0:
                is_valid = True
        except Exception:
            pass
            
    global _mx_cache_dirty
    MX_CACHE[domain] = [is_valid, time.time()]
    _mx_cache_dirty += 1
    if _mx_cache_dirty >= 10:
        _save_mx_cache()
        _mx_cache_dirty = 0
    return is_valid


def flush_mx_cache():
    """Force-save the MX cache to disk. Call at the end of batch operations."""
    global _mx_cache_dirty
    if _mx_cache_dirty > 0:
        _save_mx_cache()
        _mx_cache_dirty = 0


def verify_zerobounce(email, api_key=None):
    """Validate an address via the ZeroBounce API.

    Returns True if the address is usable, False ONLY when ZeroBounce explicitly
    reports it invalid. Missing key, no network, or any error returns True so
    the pipeline degrades safely (no false negatives that block real sends).
    """
    api_key = api_key or os.getenv("ZEROBOUNCE_API_KEY", "")
    if not api_key or not HAS_REQUESTS or not email:
        return True
    try:
        resp = requests.get(
            "https://api.zerobounce.net/v2/validate",
            params={"api_key": api_key, "email": email},
            timeout=10,
        )
        if resp.status_code != 200:
            return True
        status = (resp.json() or {}).get("status", "").lower()
        # Block only confirmed-bad results; allow valid/catch-all/unknown.
        return status not in ("invalid", "spamtrap", "abuse", "do_not_mail")
    except Exception:
        return True


def validate_email(email, from_email=None, use_zerobounce=True, deep_smtp=False):
    """Single entry point: generic-prefix -> MX -> optional ZeroBounce.

    Returns (ok: bool, reason: str). `reason` is '' when ok is True.
    """
    if not email or "@" not in email:
        return False, "malformed"
    email = email.lower().strip()
    if is_generic_email(email):
        return False, "generic_prefix"
    domain = email.split("@")[1]
    if not verify_mx(domain):
        return False, "no_mx"
    if deep_smtp and from_email and not verify_smtp_mailbox(email, from_email):
        return False, "smtp_550"
    if use_zerobounce and not verify_zerobounce(email):
        return False, "zerobounce_invalid"
    return True, ""

def verify_smtp_mailbox(target_email, from_email):
    """Deep SMTP Ping to verify mailbox existence."""
    domain = target_email.split('@')[-1].lower()
    
    mx_record = domain
    if HAS_DNS:
        try:
            records = dns.resolver.resolve(domain, 'MX', lifetime=5)
            mx_record = sorted(records, key=lambda rec: rec.preference)[0].exchange.to_text()
        except Exception:
            pass
            
    try:
        server = smtplib.SMTP(timeout=5)
        server.connect(mx_record, 25)
        server.helo(from_email.split('@')[-1] if '@' in from_email else 'localhost')
        server.mail(from_email)
        code, message = server.rcpt(target_email)
        server.quit()
        if code == 550:
            return False
        return True
    except Exception:
        # If we can't connect, assume True to avoid false negatives
        return True
