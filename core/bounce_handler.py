import imaplib
import email
import re
import json
import csv
import os
import io
import sys
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Force flush on every print so logs stream in real-time
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

load_dotenv(ENV_FILE)

EMAIL_ACCOUNT = os.getenv("EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

def clean_bounces():
    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        print("❌ ERROR: Email credentials missing.")
        return

    try:
        print("🔄 Connecting to Gmail IMAP...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_ACCOUNT, APP_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, '(OR FROM "mailer-daemon@googlemail.com" FROM "postmaster")')
        
        if status != "OK":
            print("   ✅ No bounce messages found.")
            return

        email_ids = messages[0].split()
        bounced_emails = set()

        if not email_ids:
            print("   ✅ No bounce messages found in inbox.")
            mail.close()
            mail.logout()
            return

        print(f"🧹 Found {len(email_ids)} bounce messages. Analyzing...")

        for e_id in email_ids:
            status, msg_data = mail.fetch(e_id, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ["text/plain", "message/delivery-status"]:
                                try:
                                    body += part.get_payload(decode=True).decode(errors='ignore')
                                except:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode(errors='ignore')
                        except:
                            pass
                    
                    matches = re.findall(r"wasn't delivered to\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", body, re.IGNORECASE)
                    for match in matches:
                        bounced_emails.add(match.lower())

            mail.store(e_id, '+FLAGS', '\\Deleted')

        mail.expunge()
        mail.close()
        mail.logout()

        if not bounced_emails:
            print("   ✅ Could not extract specific bounced addresses.")
            return

        print(f"   🗑️ Extracted {len(bounced_emails)} bounced addresses.")

        bounced_domains = set()
        if os.path.exists(BOUNCED_JSON):
            try:
                with open(BOUNCED_JSON, 'r') as f:
                    bounced_domains = set(json.load(f))
            except:
                pass
        
        for em in bounced_emails:
            if '@' in em:
                bounced_domains.add(em.split('@')[1])
        
        with open(BOUNCED_JSON, 'w') as f:
            json.dump(list(bounced_domains), f, indent=2)

        rows = []
        removed_count = 0
        if os.path.exists(FIRMS_CSV):
            with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    em = row['contact_email'].lower()
                    domain = em.split('@')[1] if '@' in em else ''
                    if em in bounced_emails or domain in bounced_domains:
                        removed_count += 1
                    else:
                        rows.append(row)
            
            with open(FIRMS_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        print(f"   ✅ Removed {removed_count} bounced companies from firms.csv!")
        print("🎉 Inbox cleaned up!")

    except Exception as e:
        print(f"❌ Error handling bounces: {e}")

if __name__ == "__main__":
    clean_bounces()
