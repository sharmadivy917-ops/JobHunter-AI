"""
reply_scanner.py — Auto-detect company replies via IMAP inbox scan.

Connects to Gmail via IMAP, searches for emails FROM domains matching
companies in the lead database. When a reply is found, the corresponding
email_log entry is marked as 'replied', which stops all future follow-ups.
"""
import imaplib
import email
import json
import csv
import os
import sys
import io
from datetime import datetime, timedelta
from dotenv import load_dotenv

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
ENV_FILE = os.path.join(BASE_DIR, ".env")
FIRMS_CSV = os.path.join(BASE_DIR, "firms.csv")
EMAIL_LOG = os.path.join(BASE_DIR, "email_log.json")

load_dotenv(ENV_FILE)

YOUR_EMAIL = os.environ.get("EMAIL", "")
YOUR_PASSWORD = os.environ.get("APP_PASSWORD", "")


def load_company_domains():
    """Load all company domains from firms.csv and email_log.json."""
    domains = {}  # domain -> list of company emails
    
    # From firms.csv
    if os.path.exists(FIRMS_CSV):
        try:
            with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    em = row.get('contact_email', '').lower().strip()
                    company = row.get('company_name', '')
                    if '@' in em:
                        domain = em.split('@')[1]
                        if domain not in domains:
                            domains[domain] = []
                        domains[domain].append({
                            'email': em,
                            'company': company
                        })
        except:
            pass
    
    # Also from email_log.json (for companies already sent to)
    if os.path.exists(EMAIL_LOG):
        try:
            with open(EMAIL_LOG, 'r') as f:
                for entry in json.load(f):
                    em = entry.get('email', '').lower().strip()
                    company = entry.get('company', '')
                    if '@' in em and entry.get('status') == 'sent':
                        domain = em.split('@')[1]
                        if domain not in domains:
                            domains[domain] = []
                        # Avoid duplicates
                        if not any(d['email'] == em for d in domains[domain]):
                            domains[domain].append({
                                'email': em,
                                'company': company
                            })
        except:
            pass
    
    return domains


def load_email_log():
    if os.path.exists(EMAIL_LOG):
        try:
            with open(EMAIL_LOG, 'r') as f:
                return json.load(f)
        except:
            pass
    return []


def save_email_log(log):
    with open(EMAIL_LOG, 'w') as f:
        json.dump(log, f, indent=4)


def scan_for_replies():
    """Scan Gmail inbox for replies from companies we've emailed."""
    print(f"\n{'='*56}")
    print(f"  REPLY SCANNER — Auto-detect Company Replies")
    print(f"{'='*56}\n")
    
    if not YOUR_EMAIL or not YOUR_PASSWORD:
        print("❌ Gmail credentials not set. Configure in Settings.")
        return
    
    company_domains = load_company_domains()
    if not company_domains:
        print("❌ No companies in database. Run the Hunter first.")
        return
    
    print(f"📧 Scanning inbox: {YOUR_EMAIL}")
    print(f"🏢 Tracking {len(company_domains)} company domains")
    print(f"   Domains: {', '.join(list(company_domains.keys())[:10])}{'...' if len(company_domains) > 10 else ''}\n")
    
    try:
        # Connect to Gmail IMAP
        print("🔌 Connecting to Gmail IMAP...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(YOUR_EMAIL, YOUR_PASSWORD)
        mail.select("inbox")
        print("✅ Connected successfully\n")
        
        # Search for emails from last 60 days
        since_date = (datetime.now() - timedelta(days=60)).strftime("%d-%b-%Y")
        
        replies_found = []
        domains_checked = 0
        
        for domain, companies in company_domains.items():
            domains_checked += 1
            
            # Skip our own domain and common providers
            skip_domains = {'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 
                           'googlemail.com', 'protonmail.com', 'aol.com'}
            if domain in skip_domains:
                continue
            
            # Search for emails FROM this domain
            try:
                search_query = f'(FROM "@{domain}" SINCE {since_date})'
                status, messages = mail.search(None, search_query)
                
                if status != "OK" or not messages[0]:
                    continue
                
                email_ids = messages[0].split()
                
                if email_ids:
                    print(f"📬 Found {len(email_ids)} email(s) from @{domain}")
                    
                    for eid in email_ids[:5]:  # Check up to 5 emails per domain
                        try:
                            status, msg_data = mail.fetch(eid, '(RFC822)')
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    msg = email.message_from_bytes(response_part[1])
                                    from_addr = msg.get('From', '')
                                    subject = msg.get('Subject', '(No Subject)')
                                    date = msg.get('Date', '')
                                    
                                    # Extract actual email from "Name <email>" format
                                    from_email = from_addr
                                    if '<' in from_addr:
                                        from_email = from_addr.split('<')[1].rstrip('>')
                                    from_email = from_email.lower().strip()
                                    
                                    # Check it's not a bounce or auto-reply system
                                    if any(skip in from_email for skip in ['mailer-daemon', 'postmaster', 'noreply', 'no-reply', 'donotreply', 'newsletter', 'marketing']):
                                        continue
                                        
                                    # Stricter detection: Must be an actual reply or mention keywords
                                    subject_lower = subject.lower()
                                    is_reply = (
                                        "re:" in subject_lower or 
                                        msg.get('In-Reply-To') or 
                                        msg.get('References') or
                                        any(kw in subject_lower for kw in ['interview', 'application', 'candidate', 'resume', 'divy', 'sharma', 'offer', 'assessment'])
                                    )
                                    
                                    if not is_reply:
                                        continue
                                    
                                    for comp in companies:
                                        replies_found.append({
                                            'from_email': from_email,
                                            'domain': domain,
                                            'company': comp['company'],
                                            'original_email': comp['email'],
                                            'subject': subject[:80] if subject else '',
                                            'date': date,
                                        })
                        except Exception as e:
                            pass
            except Exception as e:
                continue
        
        mail.close()
        mail.logout()
        
        print(f"\n{'='*56}")
        print(f"  SCAN RESULTS")
        print(f"{'='*56}")
        print(f"  Domains checked: {domains_checked}")
        print(f"  Replies found:   {len(replies_found)}")
        
        if not replies_found:
            print("\n  😴 No replies detected from any companies.")
            print("  This means no company has responded to your emails yet.")
            print(f"{'='*56}\n")
            return
        
        # Deduplicate by domain
        seen_domains = set()
        unique_replies = []
        for r in replies_found:
            if r['domain'] not in seen_domains:
                seen_domains.add(r['domain'])
                unique_replies.append(r)
        
        print(f"\n  📨 Unique company replies: {len(unique_replies)}\n")
        for r in unique_replies:
            print(f"  ✅ {r['company']} (@{r['domain']})")
            print(f"     From: {r['from_email']}")
            print(f"     Subject: {r['subject']}")
            print(f"     Sent to: {r['original_email']}")
            print()
        
        # Update email_log.json — mark matching entries as 'replied'
        log = load_email_log()
        updated_count = 0
        
        replied_domains = set(r['domain'] for r in unique_replies)
        replied_emails = set(r['original_email'] for r in unique_replies)
        
        for entry in log:
            em = entry.get('email', '').lower().strip()
            if entry.get('status') == 'sent':
                domain = em.split('@')[1] if '@' in em else ''
                if em in replied_emails or domain in replied_domains:
                    entry['status'] = 'replied'
                    entry['replied_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    entry['reply_detected'] = 'auto-scan'
                    updated_count += 1
                    print(f"  📝 Marked as replied: {entry.get('company')} ({em})")
        
        if updated_count > 0:
            save_email_log(log)
            print(f"\n  ✅ Updated {updated_count} entries in email_log.json")
            print(f"  ⏹️  Follow-ups will automatically stop for these companies.")
        else:
            print(f"\n  ℹ️  All replied companies were already marked.")
        
        print(f"{'='*56}\n")
        
    except imaplib.IMAP4.error as e:
        print(f"❌ IMAP login failed: {e}")
        print("   Make sure you're using an App Password (not your regular password).")
        print("   Enable 2FA and create an App Password at: https://myaccount.google.com/apppasswords")
    except Exception as e:
        print(f"❌ Error scanning inbox: {e}")


if __name__ == "__main__":
    scan_for_replies()
