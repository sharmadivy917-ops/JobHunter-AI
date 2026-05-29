import smtplib
import imaplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import os
import time
import argparse
from datetime import datetime, timedelta
import random
import sys
import io

# Fix Windows console encoding for emoji support
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


import sys
import io
import json
import random
from dotenv import load_dotenv

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
ENV_FILE = os.path.join(BASE_DIR, '.env')
EMAIL_LOG = os.path.join(BASE_DIR, 'email_log.json')
load_dotenv(ENV_FILE)

YOUR_EMAIL = os.getenv('EMAIL')
YOUR_PASSWORD = os.getenv('APP_PASSWORD')
YOUR_NAME = os.getenv('YOUR_NAME', 'Applicant')
YOUR_SKILLS = os.getenv('YOUR_SKILLS', 'Python, JS')
YOUR_PHONE = os.getenv('PHONE', '')
YOUR_PORTFOLIO = os.getenv('YOUR_PORTFOLIO', '')
YOUR_LINKEDIN = os.getenv('YOUR_LINKEDIN', '')
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 465




GENERIC_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "rediffmail.com", "protonmail.com"}
BOUNCED_JSON = os.path.join(BASE_DIR, 'bounced_domains.json')

def load_bounced_domains():
    if os.path.exists(BOUNCED_JSON):
        try:
            with open(BOUNCED_JSON, 'r') as f:
                return set(json.load(f))
        except: pass
    return set()

def get_imap_connection():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(YOUR_EMAIL, YOUR_PASSWORD)
        mail.select("inbox")
        return mail
    except Exception as e:
        print(f"   ⚠️ Could not connect to IMAP for reply checking: {e}")
        return None

def check_if_replied(mail, email):
    if not mail or not email:
        return False
    domain = email.split('@')[1] if '@' in email else ""
    search_term = email if domain in GENERIC_DOMAINS else domain
    if not search_term:
        return False
    try:
        # Search for any email FROM this domain/address
        status, messages = mail.search(None, f'FROM "{search_term}"')
        if status == "OK" and messages[0]:
            return True
        return False
    except:
        return False

def load_email_log():
    if not os.path.exists(EMAIL_LOG):
        return []
    try:
        with open(EMAIL_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_email_log(log):
    with open(EMAIL_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=4)


# ─────────────────────────────────────────────
#  STAGE-SPECIFIC HTML TEMPLATES
# ─────────────────────────────────────────────

def _buttons_html():
    """Reusable GitHub + LinkedIn buttons matching email_sender.py design."""
    portfolio_btn = ""
    if YOUR_PORTFOLIO:
        portfolio_btn = f'<a href="{YOUR_PORTFOLIO}" target="_blank" style="display:inline-block;background:#1A56A0;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;margin-right:10px;">🔗 GitHub Portfolio</a>'
    linkedin_btn = ""
    if YOUR_LINKEDIN:
        linkedin_btn = f'<a href="{YOUR_LINKEDIN}" target="_blank" style="display:inline-block;background:#0077B5;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">💼 LinkedIn Profile</a>'
    return f"{portfolio_btn}{linkedin_btn}"

def _signature_html():
    """Reusable signature block matching email_sender.py design."""
    return f"""
            <div style="margin-top:32px;padding-top:16px;border-top:2px solid #e0e0e0;">
                <p style="margin:0;font-weight:700;color:#1A56A0;font-size:16px;">{YOUR_NAME}</p>
                <p style="margin:4px 0;color:#666;font-size:14px;">📧 {YOUR_EMAIL}</p>
                <p style="margin:4px 0;color:#666;font-size:14px;">📞 {YOUR_PHONE}</p>
            </div>"""

def _wrap_template(inner_html):
    """Wrap content in the standard email container matching email_sender.py design."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @media only screen and (max-width: 600px) {{
                .email-body {{ padding: 12px !important; line-height: 1.6 !important; }}
                .email-container {{ padding: 20px !important; border-radius: 4px !important; }}
                .email-p {{ font-size: 15px !important; }}
            }}
        </style>
    </head>
    <body class="email-body" style="font-family:'Segoe UI',Arial,sans-serif;max-width:700px;margin:auto;padding:32px;color:#222;line-height:1.8;background-color:#f9f9f9;">
        <div class="email-container" style="background-color:#fff;border-radius:8px;padding:40px;box-shadow:0 2px 4px rgba(0,0,0,0.05);">
            <div style="height:4px;background:linear-gradient(90deg,#1A56A0,#4A90D9,#6CB4EE);border-radius:4px;margin-bottom:28px;"></div>
{inner_html}
        </div>
    </body>
    </html>
    """


def get_stage1_html(company_name, role, hr_name):
    """Stage 1 (Day 5) — Gentle check-in."""
    inner = f"""
            <p style="margin-bottom:16px;font-size:16px;">Dear {hr_name},</p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;">
                I hope this message finds you well. I recently submitted my application for the
                <strong>{role}</strong> role at <strong>{company_name}</strong> and wanted to
                quickly check in to confirm it was received.
            </p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;color:#444;">
                I remain very enthusiastic about the opportunity to contribute my skills in
                <strong>{YOUR_SKILLS}</strong> to your team. Please don't hesitate to reach out
                if you need any additional information or materials from my end.
            </p>

            <div style="margin:20px 0;">{_buttons_html()}</div>

            <p style="margin-bottom:8px;font-size:15px;">Thank you for your time and consideration.</p>
{_signature_html()}"""
    return _wrap_template(inner)


def get_stage2_html(company_name, role, hr_name):
    """Stage 2 (Day 12) — Value-add follow-up."""
    inner = f"""
            <p style="margin-bottom:16px;font-size:16px;">Dear {hr_name},</p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;">
                I am following up on my application for the <strong>{role}</strong> role at
                <strong>{company_name}</strong>. I wanted to share a project that I believe
                demonstrates my fit for this role.
            </p>

            <div style="margin:24px 0;padding:16px;background-color:#f0f4f8;border-left:4px solid #1A56A0;border-radius:4px;">
                <p style="margin:0;font-size:14px;color:#333;line-height:1.7;">
                    🚀 <strong>Featured Project:</strong> You can explore my recent work on my
                    <a href="{YOUR_PORTFOLIO}" style="color:#1A56A0;text-decoration:underline;">GitHub portfolio</a>,
                    which showcases practical applications of <strong>{YOUR_SKILLS}</strong> — the
                    very skills required for this role.
                </p>
            </div>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;color:#444;">
                I would also be happy to complete a short technical assessment or trial task if
                that would help demonstrate my capabilities. I am confident in my ability to add
                value to your team from day one.
            </p>

            <div style="margin:20px 0;">{_buttons_html()}</div>

            <p style="margin-bottom:8px;font-size:15px;">Looking forward to hearing from you.</p>
{_signature_html()}"""
    return _wrap_template(inner)


def get_stage3_html(company_name, role, hr_name):
    """Stage 3 (Day 20) — Final follow-up."""
    inner = f"""
            <p style="margin-bottom:16px;font-size:16px;">Dear {hr_name},</p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;">
                I hope you are doing well. I am writing one final time regarding my application
                for the <strong>{role}</strong> role at <strong>{company_name}</strong>.
            </p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;color:#444;">
                I completely understand if the role has been filled or if my profile is not
                the right fit at this time. That said, I remain very interested and am
                <strong>available to join immediately</strong> — whether as a full-time hire, intern, or trainee.
            </p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;">
                If there are other openings in the future where my skills in
                <strong>{YOUR_SKILLS}</strong> could be a match, I would love to be considered.
            </p>

            <div style="margin:20px 0;">{_buttons_html()}</div>

            <p style="margin-bottom:8px;font-size:15px;">Thank you for your time, and I wish your team continued success.</p>
{_signature_html()}"""
    return _wrap_template(inner)


# ─────────────────────────────────────────────
#  STAGE-SPECIFIC PLAIN TEXT TEMPLATES
# ─────────────────────────────────────────────

def get_stage1_plain(company_name, role, hr_name):
    return f"""Dear {hr_name},

I hope this message finds you well. I recently submitted my application for the {role} role at {company_name} and wanted to quickly check in to confirm it was received.

I remain very enthusiastic about the opportunity to contribute my skills in {YOUR_SKILLS} to your team. Please don't hesitate to reach out if you need any additional information or materials from my end.

- GitHub: {YOUR_PORTFOLIO}
- LinkedIn: {YOUR_LINKEDIN}

Thank you for your time and consideration.

Best regards,
{YOUR_NAME}
{YOUR_EMAIL}
{YOUR_PHONE}
"""

def get_stage2_plain(company_name, role, hr_name):
    return f"""Dear {hr_name},

I am following up on my application for the {role} role at {company_name}. I wanted to share a project that I believe demonstrates my fit for this role.

Featured Project: You can explore my recent work on my GitHub portfolio ({YOUR_PORTFOLIO}), which showcases practical applications of {YOUR_SKILLS} — the very skills required for this role.

I would also be happy to complete a short technical assessment or trial task if that would help demonstrate my capabilities. I am confident in my ability to add value to your team from day one.

- GitHub: {YOUR_PORTFOLIO}
- LinkedIn: {YOUR_LINKEDIN}

Looking forward to hearing from you.

Best regards,
{YOUR_NAME}
{YOUR_EMAIL}
{YOUR_PHONE}
"""

def get_stage3_plain(company_name, role, hr_name):
    return f"""Dear {hr_name},

I hope you are doing well. I am writing one final time regarding my application for the {role} role at {company_name}.

I completely understand if the role has been filled or if my profile is not the right fit at this time. That said, I remain very interested and am available to join immediately — whether as a full-time hire, intern, or trainee.

If there are other openings in the future where my skills in {YOUR_SKILLS} could be a match, I would love to be considered.

- GitHub: {YOUR_PORTFOLIO}
- LinkedIn: {YOUR_LINKEDIN}

Thank you for your time, and I wish your team continued success.

Best regards,
{YOUR_NAME}
{YOUR_EMAIL}
{YOUR_PHONE}
"""


# ─────────────────────────────────────────────
#  SUBJECT LINES PER STAGE
# ─────────────────────────────────────────────
STAGE_SUBJECTS = {
    "job": {
        1: "Quick Check-in: {role} Application — {name}",
        2: "Following Up: {role} at {company} — {name}",
        3: "Still Interested: {role} Position — {name}",
    },
    "internship": {
        1: "Quick Check-in: {role} Internship — {name}",
        2: "Following Up: {role} Internship at {company} — {name}",
        3: "Still Interested: {role} Internship — {name}",
    },
    "trainee": {
        1: "Quick Check-in: {role} Trainee Role — {name}",
        2: "Following Up: {role} Trainee Role at {company} — {name}",
        3: "Still Interested: {role} Trainee Role — {name}",
    }
}

STAGE_LABELS = {
    1: "Stage 1 — Gentle check-in",
    2: "Stage 2 — Value-add follow-up",
    3: "Stage 3 — Final follow-up",
}

# Map stage → (html_fn, plain_fn)
STAGE_TEMPLATES = {
    1: (get_stage1_html, get_stage1_plain),
    2: (get_stage2_html, get_stage2_plain),
    3: (get_stage3_html, get_stage3_plain),
}


def send_follow_up(entry, stage, dry_run=False):
    company_name = entry.get("company", "your company")
    role = entry.get("role", "Software Developer")
    hr_name = entry.get("hr_name", "Hiring Manager")
    target_email = entry.get("email")
    lead_type = entry.get("type", "job")

    if not target_email:
        return False

    subjects = STAGE_SUBJECTS.get(lead_type, STAGE_SUBJECTS["job"])
    subject = subjects[stage].format(role=role, company=company_name, name=YOUR_NAME)

    html_fn, plain_fn = STAGE_TEMPLATES[stage]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{YOUR_NAME} <{YOUR_EMAIL}>"
    msg["To"] = target_email

    msg.attach(MIMEText(plain_fn(company_name, role, hr_name), "plain"))
    msg.attach(MIMEText(html_fn(company_name, role, hr_name), "html"))

    if dry_run:
        print(f"   📧 TO:      {target_email}")
        print(f"   📝 SUBJECT: {subject}")
        print(f"   🏢 COMPANY: {company_name}")
        print(f"   🏷️ TYPE:    {lead_type.title()}")
        print(f"   🔄 STAGE:   {STAGE_LABELS[stage]}")
        print("   ──────────────────────────────────────────────────")
        return True

    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        server.login(YOUR_EMAIL, YOUR_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"   ❌ Failed to send follow-up to {company_name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Send multi-stage follow-up emails to companies you already applied to.")
    parser.add_argument("--dry-run", action="store_true", help="Preview emails without sending")
    parser.add_argument("--days", type=int, default=5, help="Minimum days before Stage 1 follow-up (default: 5)")
    parser.add_argument("--auto", action="store_true", help="Run automatically without asking for confirmation")
    args = parser.parse_args()

    if mail:
        try:
            mail.close()
            mail.logout()
        except: pass

    print(f"\n========================================================")
    print(f"  📬  FOLLOW-UP AUTOMATION — {YOUR_NAME}")
    if args.dry_run:
        print(f"  🔍 DRY RUN MODE (no emails sent)")
    else:
        print(f"  🚀 LIVE MODE (emails will be sent)")
    print(f"  {datetime.now().strftime('%d %b %Y, %I:%M %p')}")
    print(f"========================================================\n")

    log = load_email_log()
    if not log:
        print("📭 No email log found. Run email_sender.py first to apply to jobs.")
        return

    now = datetime.now()
    targets = []

    # Stage timing: days after initial send for each stage
    # Stage 1 = args.days (default 5), Stage 2 = 12, Stage 3 = 20
    days_needed = [args.days, 12, 20]

    # Find eligible targets
    for i, entry in enumerate(log):
        if entry.get("status") == "sent":
            current_stage = entry.get("follow_up_stage", 0)
            if current_stage >= 3:
                continue  # All stages done

            sent_at_str = entry.get("sent_at")
            if not sent_at_str:
                continue

            try:
                sent_at = datetime.strptime(sent_at_str, "%Y-%m-%d %H:%M:%S")
                days_since_send = (now - sent_at).days

                if days_since_send >= days_needed[current_stage]:
                    targets.append((i, entry, current_stage + 1))
            except ValueError:
                continue

    if not targets:
        print(f"😴 No companies need a follow-up right now.")
        print(f"   Stage 1 after {days_needed[0]}d | Stage 2 after {days_needed[1]}d | Stage 3 after {days_needed[2]}d")
        return

    print(f"📨 Found {len(targets)} follow-ups to send!\n")
    for _, entry, stage in targets:
        print(f"   • {entry.get('company')} → {STAGE_LABELS[stage]}")
    print()

    if not args.dry_run and not args.auto:
        print("⚠️  You are about to send REAL follow-up emails to:")
        for _, entry, stage in targets:
            print(f"   • {entry.get('company')} → {entry.get('email')} [{STAGE_LABELS[stage]}]")
        print()
        confirm = input("Type 'yes' to confirm and send: ").strip().lower()
        if confirm != "yes":
            print("❌ Cancelled. No emails sent.")
            sys.exit(0)
        print()
    elif args.auto and not args.dry_run:
        print("🤖 AUTO MODE ENABLED: Skipping confirmation prompt.\n")

        bounced = load_bounced_domains()
    mail = get_imap_connection()
    if mail:
        print(f"🔍 Connected to inbox for reply detection.")
    
    sent_count = 0
    for idx, (log_idx, entry, stage) in enumerate(targets):
        company = entry.get("company", "Unknown")
        email = entry.get("email")
        
        print(f"[{idx+1}/{len(targets)}] 📨 Following up with {company} ({email}) — {STAGE_LABELS[stage]}")
        
        domain = email.split('@')[1] if '@' in email else ""
        
        if domain in bounced or email in bounced:
            print(f"   🚫 Skipping: Domain/Email is on the bounce list.")
            if not args.dry_run:
                log[log_idx]["status"] = "bounced"
                save_email_log(log)
            continue
            
        if mail and check_if_replied(mail, email):
            print(f"   🎉 SUCCESS: They already replied! Cancelling all follow-ups.")
            if not args.dry_run:
                log[log_idx]["status"] = "replied"
                save_email_log(log)
            continue

        if send_follow_up(entry, stage, dry_run=args.dry_run):
            if not args.dry_run:
                # Update log with stage tracking
                log[log_idx]["follow_up_stage"] = stage
                log[log_idx][f"follow_up_{stage}_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_email_log(log)
                print("   ✅ Sent successfully!")
                sent_count += 1

                # Delay
                if idx < len(targets) - 1:
                    delay = random.randint(8, 15)
                    print(f"   ⏳ Waiting {delay}s before next email...")
                    time.sleep(delay)
            else:
                sent_count += 1

    if mail:
        try:
            mail.close()
            mail.logout()
        except: pass

    print(f"\n========================================================")
    print(f"  📊  FOLLOW-UP SUMMARY")
    print(f"========================================================")
    if args.dry_run:
        print(f"  👀 Previewed: {sent_count} follow-ups")
    else:
        print(f"  ✅ Sent:      {sent_count}")
        stage_counts = {}
        for _, _, stage in targets:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        for s in sorted(stage_counts):
            print(f"     {STAGE_LABELS[s]}: {stage_counts[s]}")
    print(f"========================================================\n")

if __name__ == "__main__":
    main()
