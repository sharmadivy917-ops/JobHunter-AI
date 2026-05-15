"""
sender.py — Personalized HTML email sender with resume attachment.
Ported from the mature root email_sender.py with full template and MX verification.
"""
import smtplib
import csv
import json
import os
import sys
import io
import time
import random
import dns.resolver
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv

# Fix Windows console encoding
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
EMAIL_LOG = os.path.join(BASE_DIR, "email_log.json")
BOUNCED_JSON = os.path.join(BASE_DIR, "bounced_domains.json")

load_dotenv(ENV_FILE)


def get_config():
    """Load all config from environment."""
    return {
        "email": os.getenv("EMAIL", ""),
        "password": os.getenv("APP_PASSWORD", ""),
        "name": os.getenv("YOUR_NAME", "Applicant"),
        "title": os.getenv("YOUR_TITLE", "Software Developer"),
        "skills": os.getenv("YOUR_SKILLS", "Python, JavaScript, React"),
        "portfolio": os.getenv("YOUR_PORTFOLIO", ""),
        "linkedin": os.getenv("YOUR_LINKEDIN", ""),
        "resume": os.getenv("RESUME_PATH", ""),
        "delay_min": int(os.environ.get("SEND_DELAY", os.getenv("SEND_DELAY", "8"))),
        "delay_max": int(os.environ.get("SEND_DELAY", os.getenv("SEND_DELAY", "8"))) + 7,
        "max_sends": int(os.environ.get("SEND_MAX", os.getenv("MAX_DAY", "50"))),
    }


def load_email_log():
    if os.path.exists(EMAIL_LOG):
        try:
            with open(EMAIL_LOG, 'r') as f:
                return json.load(f)
        except:
            return []
    return []


def save_email_log(log):
    with open(EMAIL_LOG, 'w') as f:
        json.dump(log, f, indent=2)


def get_already_sent():
    """Get set of emails already sent to."""
    log = load_email_log()
    return {entry.get("email", "").lower() for entry in log if entry.get("status") == "sent"}


def load_bounced_domains():
    if os.path.exists(BOUNCED_JSON):
        try:
            with open(BOUNCED_JSON, 'r') as f:
                return set(json.load(f))
        except:
            pass
    return set()


def verify_mx(domain):
    """Check if a domain has valid MX records."""
    try:
        records = dns.resolver.resolve(domain, 'MX')
        return len(records) > 0
    except:
        return False


def get_email_html(cfg, company, role, hr_name):
    """Generate the rich HTML email body."""
    portfolio_btn = ""
    if cfg["portfolio"]:
        portfolio_btn = f'<a href="{cfg["portfolio"]}" target="_blank" style="display:inline-block;background:#1A56A0;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;margin-right:10px;">GitHub Portfolio</a>'

    linkedin_btn = ""
    if cfg["linkedin"]:
        linkedin_btn = f'<a href="{cfg["linkedin"]}" target="_blank" style="display:inline-block;background:#0077B5;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">LinkedIn Profile</a>'

    return f"""
    <html>
    <body style="font-family:'Segoe UI',Arial,sans-serif;max-width:680px;margin:auto;padding:24px;color:#222;line-height:1.7;">
        <div style="height:4px;background:linear-gradient(90deg,#1A56A0,#4A90D9,#6CB4EE);border-radius:4px;margin-bottom:28px;"></div>

        <p style="margin-bottom:16px;">Dear {hr_name},</p>

        <p>I hope this message finds you well. I am writing to express my keen interest in the
        <strong>{role}</strong> position at <strong>{company}</strong>.
        As a <strong>passionate developer</strong> skilled in <strong>{cfg['skills']}</strong>,
        I am eager to contribute meaningfully to your team.</p>

        <p>Here are some highlights of my profile:</p>

        <ul style="padding-left:20px;color:#333;">
            <li>Proficient in <strong>{cfg['skills']}</strong></li>
            <li>Built <strong>automation tools and full-stack projects</strong> independently</li>
            <li>Strong problem-solving skills with a focus on <strong>clean, scalable code</strong></li>
            <li>Quick learner with a <strong>passion for continuous improvement</strong></li>
            <li>Open to <strong>on-site, hybrid, and remote</strong> work arrangements</li>
        </ul>

        <p>I have attached my resume for your review.</p>

        <div style="margin:20px 0;">{portfolio_btn}{linkedin_btn}</div>

        <p>I would welcome the opportunity to discuss how my background aligns with the needs of your team
        at <strong>{company}</strong>. I am available for an interview at your earliest convenience.</p>

        <p>Thank you for considering my application.</p>

        <div style="margin-top:32px;padding-top:16px;border-top:1px solid #e0e0e0;">
            <p style="margin:0;font-weight:600;color:#1A56A0;font-size:15px;">{cfg['name']}</p>
            <p style="margin:4px 0;color:#666;font-size:13px;">{cfg['email']}</p>
        </div>
    </body>
    </html>
    """


def get_email_plain(cfg, company, role, hr_name):
    """Plain text fallback."""
    return f"""Dear {hr_name},

I am writing to express my interest in the {role} position at {company}.

As a developer skilled in {cfg['skills']}, I would love the opportunity to contribute to your team.

I have attached my resume for your review.

Best regards,
{cfg['name']}
{cfg['email']}
"""


def attach_resume(msg, resume_path):
    """Attach resume if the file exists."""
    if not resume_path or not os.path.exists(resume_path):
        if resume_path:
            print(f"   Resume not found at: {resume_path}")
        return
    try:
        filename = os.path.basename(resume_path)
        with open(resume_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={filename}")
        msg.attach(part)
    except Exception as e:
        print(f"   Could not attach resume: {e}")


def send_emails():
    """Main sender — reads firms.csv and sends personalized emails."""
    cfg = get_config()

    if not cfg["email"] or not cfg["password"]:
        print("ERROR: Email credentials missing. Set them in Settings.")
        return

    if not os.path.exists(FIRMS_CSV):
        print("ERROR: firms.csv not found. Run the Hunter first.")
        return

    # Read firms
    firms = []
    with open(FIRMS_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("company_name") and row.get("contact_email"):
                firms.append({k: v.strip() for k, v in row.items()})

    if not firms:
        print("No firms in database.")
        return

    # Filter already sent
    already_sent = get_already_sent()
    bounced = load_bounced_domains()

    pending = []
    for firm in firms:
        email = firm["contact_email"].lower()
        domain = email.split('@')[1] if '@' in email else ''
        if email not in already_sent and domain not in bounced:
            pending.append(firm)

    if not pending:
        print("All firms already emailed. Add new leads or use Hunter.")
        return

    # Apply limit
    to_send = pending[:cfg["max_sends"]]

    print(f"\nSending {len(to_send)} emails (skipping {len(firms)-len(pending)} already sent)...\n")

    # Connect to Gmail
    print("Connecting to Gmail SMTP...")
    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(cfg["email"], cfg["password"])
    except Exception as e:
        print(f"Failed to login to Gmail: {e}")
        return

    print("Connected! Starting campaign...\n")

    log = load_email_log()
    sent_count = 0

    for i, firm in enumerate(to_send, 1):
        company = firm["company_name"]
        to_email = firm["contact_email"].strip()
        role = firm.get("role", cfg["title"])
        hr_name = firm.get("hr_name", "Hiring Manager")
        domain = to_email.split('@')[1] if '@' in to_email else ''

        print(f"[{i}/{len(to_send)}] Sending to {company} ({to_email})...")

        # MX verification
        if not verify_mx(domain):
            print(f"   MX verification failed for {domain}. Skipping.")
            log.append({
                "company": company, "email": to_email,
                "role": role, "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "bounced"
            })
            save_email_log(log)
            continue

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Application for {role} \u2014 {cfg['name']}"
            msg["From"] = f"{cfg['name']} <{cfg['email']}>"
            msg["To"] = to_email

            msg.attach(MIMEText(get_email_plain(cfg, company, role, hr_name), "plain"))
            msg.attach(MIMEText(get_email_html(cfg, company, role, hr_name), "html"))

            attach_resume(msg, cfg["resume"])

            server.sendmail(cfg["email"], to_email, msg.as_string())
            print(f"   Sent successfully!")
            sent_count += 1

            log.append({
                "company": company, "email": to_email,
                "role": role, "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "sent"
            })
            save_email_log(log)

            # Random delay
            if i < len(to_send):
                delay = random.randint(cfg["delay_min"], cfg["delay_max"])
                print(f"   Waiting {delay}s...")
                time.sleep(delay)

        except Exception as e:
            print(f"   Failed: {e}")
            log.append({
                "company": company, "email": to_email,
                "role": role, "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "failed"
            })
            save_email_log(log)

    try:
        server.quit()
    except:
        pass

    print(f"\nCampaign Finished! Sent {sent_count}/{len(to_send)} emails.")


if __name__ == "__main__":
    send_emails()
