import imaplib
import email
import json
import os
import re
import csv
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, ".env")
EMAIL_LOG = os.path.join(BASE_DIR, "email_log.json")
FIRMS_CSV = os.path.join(BASE_DIR, "firms.csv")

load_dotenv(ENV_FILE)
YOUR_EMAIL = os.environ.get("EMAIL", "")
YOUR_PASSWORD = os.environ.get("APP_PASSWORD", "")

def recover_sent_emails():
    YOUR_EMAIL = os.getenv("EMAIL")
    YOUR_PASSWORD = os.getenv("APP_PASSWORD")
    print("🔌 Connecting to Gmail IMAP for Sent Mail recovery...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
        mail.login(YOUR_EMAIL, YOUR_PASSWORD)
        
        # Try different names for the Sent folder
        sent_folder = None
        for folder in ['"[Gmail]/Sent Mail"', '"[Gmail]/Sent"', 'Sent']:
            status, _ = mail.select(folder)
            if status == 'OK':
                sent_folder = folder
                break
                
        if not sent_folder:
            print("❌ Could not find Sent Mail folder.")
            return

        print(f"✅ Scanning {sent_folder} for sent emails...")
        since_date = (datetime.now() - timedelta(days=60)).strftime("%d-%b-%Y")
        
        # Search for emails sent by us
        search_query = f'(FROM "{YOUR_EMAIL}" SINCE {since_date})'
        status, messages = mail.search(None, search_query)
        
        if status != "OK" or not messages[0]:
            print("No sent emails found.")
            return

        email_ids = messages[0].split()
        print(f"📬 Found {len(email_ids)} sent emails in the last 60 days.")
        
        # Load existing log
        try:
            with open(EMAIL_LOG, 'r') as f:
                log = json.load(f)
        except:
            log = []
            
        existing_emails = {e.get('email', '').lower() for e in log}
        recovered_count = 0
        
        # Fetch in batches of 100 to speed up
        batch_size = 100
        for i in range(0, len(email_ids), batch_size):
            batch = email_ids[i:i+batch_size]
            eid_str = b','.join(batch)
            try:
                status, msg_data = mail.fetch(eid_str, '(BODY[HEADER.FIELDS (TO DATE)])')
                if status != 'OK': continue
                
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        to_header = msg.get("To", "")
                        if not to_header: continue
                        
                        # Extract email address
                        emails = re.findall(r'[\w\.-]+@[\w\.-]+', to_header)
                        for to_email in emails:
                            to_email = to_email.lower().strip()
                            if to_email and to_email not in existing_emails:
                                print(f"  + Recovered sent email to: {to_email}")
                                log.append({
                                    "email": to_email,
                                    "status": "sent",
                                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                                existing_emails.add(to_email)
                                recovered_count += 1
            except Exception as e:
                pass
                
        # Cross-reference with firms.csv to fill in company and role
        firms_lookup = {}
        if os.path.exists(FIRMS_CSV):
            try:
                with open(FIRMS_CSV, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        fe = row.get("contact_email", "").lower().strip()
                        if fe:
                            firms_lookup[fe] = row
            except Exception as e:
                print(f"   ⚠️ Could not load firms.csv for cross-reference: {e}")

        enriched = 0
        if firms_lookup:
            for entry in log:
                entry_email = entry.get("email", "").lower().strip()
                if entry_email and not entry.get("company") and entry_email in firms_lookup:
                    firm = firms_lookup[entry_email]
                    entry["company"] = firm.get("company_name", "")
                    entry["role"] = firm.get("role", "")
                    entry["hr_name"] = firm.get("hr_name", "Hiring Manager")
                    entry["type"] = firm.get("type", "job")
                    enriched += 1
            if enriched:
                print(f"📋 Enriched {enriched} log entries with company/role from firms.csv.")

        if recovered_count > 0 or (firms_lookup and enriched > 0):
            with open(EMAIL_LOG, 'w') as f:
                json.dump(log, f, indent=4)
            if recovered_count > 0:
                print(f"\n🎉 Successfully recovered {recovered_count} sent emails into email_log.json!")
        else:
            print("\n✅ All sent emails are already in the log.")
            
    except Exception as e:
        print(f"❌ Error during Sent Mail recovery: {e}")

if __name__ == "__main__":
    recover_sent_emails()
