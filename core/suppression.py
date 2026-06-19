"""
suppression.py - Do-not-contact list.

Addresses (or whole domains) placed here are NEVER emailed again, even if they
reappear in firms.csv via a future hunt. This honors unsubscribe requests and
manual opt-outs, which is both good practice and legally required for outreach
(CAN-SPAM, GDPR, India DPDP).

Storage: suppression.json at the project root, shape:
    { "emails": [...], "domains": [...] }
"""
import os
import json
import time
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUPPRESSION_JSON = os.path.join(BASE_DIR, "suppression.json")

_lock = threading.Lock()

# In-memory cache to avoid re-reading suppression.json on every call
_cached_data = None
_cached_at = 0
_CACHE_TTL = 60  # seconds


def _load():
    if os.path.exists(SUPPRESSION_JSON):
        try:
            with open(SUPPRESSION_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "emails": set(e.lower().strip() for e in data.get("emails", [])),
                    "domains": set(d.lower().strip() for d in data.get("domains", [])),
                }
        except Exception:
            pass
    return {"emails": set(), "domains": set()}


def _save(data):
    try:
        with open(SUPPRESSION_JSON, "w", encoding="utf-8") as f:
            json.dump(
                {"emails": sorted(data["emails"]), "domains": sorted(data["domains"])},
                f, indent=2,
            )
    except Exception:
        pass


def _cached_load():
    """Return suppression data from in-memory cache, re-reading disk at most every 60s."""
    global _cached_data, _cached_at
    now = time.time()
    if _cached_data is None or (now - _cached_at) >= _CACHE_TTL:
        _cached_data = _load()
        _cached_at = now
    return _cached_data


def _invalidate_cache():
    """Force the next read to reload from disk."""
    global _cached_data, _cached_at
    _cached_data = None
    _cached_at = 0


def is_suppressed(email):
    """True if the email or its domain is on the do-not-contact list."""
    if not email or "@" not in email:
        return False
    email = email.lower().strip()
    domain = email.split("@")[1]
    data = _cached_load()
    return email in data["emails"] or domain in data["domains"]


def suppress_email(email):
    """Add a single address to the do-not-contact list."""
    if not email or "@" not in email:
        return False
    email = email.lower().strip()
    with _lock:
        data = _load()
        data["emails"].add(email)
        _save(data)
        _invalidate_cache()
    return True


def suppress_domain(domain):
    """Add a whole domain to the do-not-contact list."""
    if not domain:
        return False
    domain = domain.lower().strip()
    with _lock:
        data = _load()
        data["domains"].add(domain)
        _save(data)
        _invalidate_cache()
    return True


def list_suppressed():
    data = _cached_load()
    return {"emails": sorted(data["emails"]), "domains": sorted(data["domains"])}
