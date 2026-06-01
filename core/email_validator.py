import smtplib
import time

try:
    import dns.resolver
    HAS_DNS = True
except ImportError:
    HAS_DNS = False

# Cache for MX lookups to speed up hunting and sending
# Format: { "domain.com": (is_valid, timestamp) }
MX_CACHE = {}
CACHE_TTL = 3600  # 1 hour

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
            
    MX_CACHE[domain] = (is_valid, time.time())
    return is_valid

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
