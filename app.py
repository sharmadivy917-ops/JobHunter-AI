import os
import sys
import csv
import json
import time
import threading
import subprocess
import imaplib
import smtplib
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv, set_key
from markupsafe import escape
from core import suppression
from filelock import FileLock

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, '.env')
FIRMS_CSV = os.path.join(BASE_DIR, 'firms.csv')
EMAIL_LOG = os.path.join(BASE_DIR, 'email_log.json')
BOUNCED_JSON = os.path.join(BASE_DIR, 'bounced_domains.json')

# File locking to prevent race conditions between main app and subprocess scripts
file_lock = FileLock(os.path.join(BASE_DIR, 'jobhunter.lock'), timeout=30)

if not os.path.exists(ENV_FILE):
    open(ENV_FILE, 'w').close()
load_dotenv(ENV_FILE)

# ── Thread-safe state ────────────────────────
lock = threading.Lock()
state = {
    "running": False,
    "stop_requested": False,
    "log": [],       # list of {id, msg, level, ts}
    "log_counter": 0,
    "process": None,
}

# ── Stats cache (avoids re-reading files every 2.5s poll) ─────
_stats_cache = {"data": None, "timestamp": 0}
STATS_CACHE_TTL = 10  # seconds

# ── Auto-Pilot scheduler ─────────────────────
# When enabled, a background daemon periodically scans for replies and sends
# any due follow-ups, so the pipeline keeps moving even with no browser open.
AUTOPILOT_DEFAULT_INTERVAL_MIN = 30
AUTOPILOT_REPLY_WAIT_SECONDS = 25      # pause between reply-scan and follow-up
_autopilot_started = False


def is_autopilot_enabled():
    return os.getenv("AUTOPILOT_ENABLED", "0") == "1"


def _autopilot_interval_seconds():
    """User-configurable cadence (minutes) via AUTOPILOT_INTERVAL_MIN; min 5."""
    try:
        minutes = int(os.getenv("AUTOPILOT_INTERVAL_MIN", AUTOPILOT_DEFAULT_INTERVAL_MIN))
    except (TypeError, ValueError):
        minutes = AUTOPILOT_DEFAULT_INTERVAL_MIN
    return max(5, minutes) * 60


def _wait_until_idle(timeout=600):
    """Block until no task is running, or until timeout (seconds) elapses."""
    waited = 0
    while waited < timeout:
        with lock:
            if not state["running"]:
                return True
        threading.Event().wait(2)
        waited += 2
    return False


def _autopilot_cycle():
    """One Auto-Pilot pass: scan for replies, then send due follow-ups."""
    with lock:
        if state["running"]:
            return  # a manual task is active; skip this cycle

    add_log("Auto-Pilot: scanning for replies...", "info")
    run_script("reply_scanner.py")

    # run_script is synchronous here, so the scan has finished by now.
    threading.Event().wait(AUTOPILOT_REPLY_WAIT_SECONDS)

    add_log("Auto-Pilot: sending due follow-ups...", "info")
    run_script("follow_up.py", script_args=["--auto"])


def _autopilot_loop():
    """Daemon loop. Sleeps in short slices so toggling off is responsive."""
    elapsed = _autopilot_interval_seconds()  # run one cycle shortly after enable
    while True:
        threading.Event().wait(10)
        if not is_autopilot_enabled():
            elapsed = _autopilot_interval_seconds()
            continue
        elapsed += 10
        if elapsed >= _autopilot_interval_seconds():
            elapsed = 0
            try:
                _autopilot_cycle()
            except Exception as e:
                add_log(f"Auto-Pilot error: {e}", "err")


def start_autopilot_scheduler():
    """Start the background scheduler thread exactly once."""
    global _autopilot_started
    if _autopilot_started:
        return
    _autopilot_started = True
    t = threading.Thread(target=_autopilot_loop, daemon=True)
    t.start()

def add_log(msg, level=""):
    with lock:
        state["log_counter"] += 1
        state["log"].append({
            "id": state["log_counter"],
            "msg": msg,
            "level": level,
            "ts": datetime.now().strftime("%H:%M:%S")
        })
        # Keep manageable size
        if len(state["log"]) > 300:
            state["log"] = state["log"][-300:]

def _compute_stats():
    """Compute live stats from files (internal — use get_stats() for caching)."""
    sent_emails = set()
    bounced_emails_log = set()
    replied_count = 0
    interview_count = 0
    followup_count = 0
    emails_today = 0
    today_str = datetime.now().strftime("%Y-%m-%d")

    if os.path.exists(EMAIL_LOG):
        try:
            with file_lock:
                with open(EMAIL_LOG, 'r') as f:
                    log = json.load(f)
                for e in log:
                    st = e.get('status')
                    em = e.get('email', '').lower().strip()
                    if st in ['sent', 'emailed']:
                        sent_emails.add(em)
                        sent_at = e.get('sent_at', '') or e.get('updated_at', '')
                        if sent_at.startswith(today_str):
                            emails_today += 1
                    elif st == 'replied':
                        replied_count += 1
                    elif st == 'interview':
                        interview_count += 1
                    elif st in ['bounced', 'failed']:
                        bounced_emails_log.add(em)
                    # Count follow-up stages
                    fus = e.get('follow_up_stage', 0)
                    if fus and fus > 0:
                        followup_count += fus
        except Exception:
            pass

    bounced_domains = set()
    if os.path.exists(BOUNCED_JSON):
        try:
            with file_lock:
                with open(BOUNCED_JSON, 'r') as f:
                    bounced_domains = set(json.load(f))
        except Exception:
            pass

    total = 0
    sent = 0
    bounced_in_csv = 0
    pending = 0

    if os.path.exists(FIRMS_CSV):
        try:
            with file_lock:
                with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        total += 1
                        email_raw = row.get('contact_email')
                        em = (email_raw or '').lower().strip()
                        dom = em.split('@')[1] if '@' in em else ''
                        if em in sent_emails:
                            sent += 1
                        elif dom and dom in bounced_domains or em and em in bounced_emails_log:
                            bounced_in_csv += 1
                        else:
                            pending += 1
        except Exception:
            pass

    total_bounced = len(bounced_domains) + len(bounced_emails_log)
    total_sent = len(sent_emails) if len(sent_emails) > sent else sent
    response_rate = round((replied_count / total_sent) * 100, 1) if total_sent > 0 else 0

    return {
        "total": total, "sent": sent, "pending": pending,
        "bounced": total_bounced, "replied": replied_count,
        "interview": interview_count, "followups": followup_count,
        "emails_today": emails_today, "response_rate": response_rate
    }


def get_stats():
    """Cached stats — avoids re-reading 3 files every 2.5s poll."""
    now = time.time()
    if _stats_cache["data"] is not None and (now - _stats_cache["timestamp"]) < STATS_CACHE_TTL:
        return _stats_cache["data"]
    data = _compute_stats()
    _stats_cache["data"] = data
    _stats_cache["timestamp"] = now
    return data


def run_script(script_name, env_overrides=None, script_args=None):
    """Run a core script in a subprocess, streaming output to the log."""
    with lock:
        if state["running"]:
            add_log("Another task is already running.", "err")
            return
        state["running"] = True
        state["stop_requested"] = False

    add_log(f"Starting {script_name}...", "info")

    try:
        env = os.environ.copy()
        # Inject dotenv values
        load_dotenv(ENV_FILE, override=True)
        for key in ['EMAIL', 'APP_PASSWORD', 'YOUR_NAME', 'YOUR_TITLE', 'YOUR_SKILLS',
                     'ROLES', 'LOCATIONS', 'RESUME_PATH', 'YOUR_PORTFOLIO', 'YOUR_LINKEDIN', 'PHONE',
                     'SEND_DELAY', 'MAX_DAY']:
            val = os.getenv(key)
            if val:
                env[key] = val

        if env_overrides:
            env.update(env_overrides)

        # Ensure BASE_DIR is in PYTHONPATH so absolute imports work
        env['PYTHONPATH'] = BASE_DIR + os.pathsep + env.get('PYTHONPATH', '')

        # Force unbuffered output so logs stream line-by-line
        env['PYTHONUNBUFFERED'] = '1'
        # Force UTF-8 encoding for standard output/error to prevent UnicodeEncodeError with emojis
        env['PYTHONIOENCODING'] = 'utf-8'

        cmd = [sys.executable, '-u', os.path.join(BASE_DIR, "core", script_name)]
        if script_args:
            cmd.extend(script_args)
            
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            env=env, cwd=BASE_DIR, bufsize=1
        )

        with lock:
            state["process"] = process

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            # Auto-detect log level from emoji/keywords
            level = ""
            if any(w in line for w in ['✅', 'success', 'Saved', 'Sent', 'Finished']):
                level = "ok"
            elif any(w in line for w in ['❌', 'Error', 'Failed', 'SKIP', '⛔']):
                level = "err"
            elif any(w in line for w in ['🔍', '🔄', 'Search', 'Start', 'Connect', 'info', '📋', '🎯']):
                level = "info"
            add_log(line, level)

            with lock:
                if state["stop_requested"]:
                    process.terminate()
                    add_log("Task stopped by user.", "err")
                    break

        process.wait()
        add_log(f"Finished {script_name}", "ok")

    except Exception as e:
        add_log(f"Error running {script_name}: {e}", "err")
    finally:
        with lock:
            state["running"] = False
            state["process"] = None


# ── Routes ────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    stats = get_stats()
    with lock:
        log_copy = list(state["log"])
        running = state["running"]
    return jsonify({"running": running, **stats, "log": log_copy})


@app.route('/api/run/<action>', methods=['POST'])
def run_action(action):
    data = request.json or {}

    with lock:
        if state["running"]:
            return jsonify({"error": "A task is already running. Wait or stop it first."})

    if action == 'hunt':
        env = {}
        if data.get('roles'):
            env['HUNTER_ROLES'] = data['roles']
        if data.get('locations'):
            env['HUNTER_LOCATIONS'] = data['locations']
        if data.get('max'):
            env['HUNTER_MAX'] = str(data['max'])
        if data.get('delay'):
            env['HUNTER_DELAY'] = str(data['delay'])
        if data.get('experience'):
            env['HUNTER_EXPERIENCE'] = data['experience']
        if data.get('company_size'):
            env['HUNTER_COMPANY_SIZE'] = data['company_size']
        if data.get('target_type'):
            env['HUNTER_TARGET_TYPE'] = data['target_type']
            
        if data.get('source') == 'linkedin':
            script_name = "linkedin_hunter.py"
        else:
            script_name = "apify_hunter.py" if data.get('use_ai') else "hunter.py"
        t = threading.Thread(target=run_script, args=(script_name,), kwargs={"env_overrides": env})
        t.daemon = True
        t.start()

    elif action == 'send':
        env = {}
        if data.get('delay'):
            env['SEND_DELAY'] = str(data['delay'])
        if data.get('max'):
            env['SEND_MAX'] = str(data['max'])
        if 'use_ai' in data:
            env['USE_AI'] = '1' if data['use_ai'] else '0'
        t = threading.Thread(target=run_script, args=("sender.py",), kwargs={"env_overrides": env})
        t.daemon = True
        t.start()

    elif action == 'follow_up':
        t = threading.Thread(target=run_script, args=("follow_up.py",), kwargs={"script_args": ["--auto"]})
        t.daemon = True
        t.start()

    elif action == 'clean':
        t = threading.Thread(target=run_script, args=("bounce_handler.py",))
        t.daemon = True
        t.start()

    elif action == 'scan_replies':
        def _scan():
            run_script("reply_scanner.py")
        t = threading.Thread(target=_scan)
        t.daemon = True
        t.start()
        
    elif action == 'deduplicate':
        t = threading.Thread(target=run_script, args=("deduplicate_leads.py",))
        t.daemon = True
        t.start()

    elif action == 'ats_check':
        # Provide instant ATS check using Gemini API (if available)
        desc = data.get('description', '')
        user_skills = os.getenv("YOUR_SKILLS", "")
        if not desc:
            return jsonify({"error": "No description provided."})
        
        try:
            from google import genai
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return jsonify({"error": "Please set GEMINI_API_KEY in settings to use ATS Optimizer."})
            
            client = genai.Client(api_key=api_key)
            
            prompt = f"""
            You are an expert ATS (Applicant Tracking System) optimizer.
            The user has these skills: {user_skills}
            
            They want to apply for a job with this description:
            {desc}
            
            Compare their skills to the job description. Output a concise list of KEYWORDS or SKILLS they are missing that they should add to their resume to beat the ATS.
            Keep it brief, actionable, and formatted nicely. Do NOT output markdown headers, just bullet points.
            """
            
            model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return jsonify({"ok": True, "result": response.text})
            
        except Exception as e:
            return jsonify({"error": f"AI error: {str(e)}"})

    else:
        return jsonify({"error": f"Unknown action: {action}"})

    return jsonify({"ok": True})


@app.route('/api/suppression', methods=['GET'])
def api_suppression():
    """List do-not-contact entries."""
    return jsonify(suppression.list_suppressed())


@app.route('/api/suppress', methods=['POST'])
def api_suppress():
    """Add an email or domain to the do-not-contact list."""
    data = request.json or {}
    email = (data.get('email') or '').strip()
    domain = (data.get('domain') or '').strip()
    if email:
        suppression.suppress_email(email)
        add_log(f"Suppressed (do-not-contact): {email}", "info")
    if domain:
        suppression.suppress_domain(domain)
        add_log(f"Suppressed domain (do-not-contact): {domain}", "info")
    if not email and not domain:
        return jsonify({"error": "Provide 'email' or 'domain'."}), 400
    return jsonify({"ok": True})


@app.route('/unsubscribe')
def unsubscribe():
    """Public opt-out target for List-Unsubscribe links. Records the address
    on the do-not-contact list so it is never emailed again."""
    email = (request.args.get('email') or '').strip()
    if email and '@' in email:
        suppression.suppress_email(email)
        add_log(f"Unsubscribe request honored: {email}", "info")
        safe_email = escape(email)
        return (f"<h2>You have been unsubscribed.</h2>"
                f"<p>The address {safe_email} will not be contacted again.</p>"), 200
    return ("<h2>Invalid unsubscribe link.</h2>"
            "<p>No valid email address was provided.</p>"), 400


@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    """Test Gmail SMTP and IMAP connectivity with current credentials."""
    load_dotenv(ENV_FILE, override=True)
    email_addr = os.getenv("EMAIL", "")
    app_pass = os.getenv("APP_PASSWORD", "")

    if not email_addr or not app_pass:
        return jsonify({"ok": False, "error": "Email and App Password not configured. Set them in Settings first."})

    results = {"smtp": False, "imap": False, "error": ""}
    # Test SMTP
    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10)
        server.login(email_addr, app_pass)
        server.quit()
        results["smtp"] = True
    except Exception as e:
        results["error"] = f"SMTP: {str(e)}"

    # Test IMAP
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=10)
        mail.login(email_addr, app_pass)
        mail.logout()
        results["imap"] = True
    except Exception as e:
        if results["error"]:
            results["error"] += f" | IMAP: {str(e)}"
        else:
            results["error"] = f"IMAP: {str(e)}"

    results["ok"] = results["smtp"] and results["imap"]
    if results["ok"]:
        add_log("Gmail connection test: PASSED ✅", "ok")
    else:
        add_log(f"Gmail connection test: FAILED — {results['error']}", "err")

    return jsonify(results)


@app.route('/api/autopilot', methods=['GET', 'POST'])
def autopilot():
    """Get or toggle the headless Auto-Pilot scheduler."""
    if request.method == 'POST':
        data = request.json or {}
        enabled = bool(data.get('enabled'))
        set_key(ENV_FILE, "AUTOPILOT_ENABLED", "1" if enabled else "0")
        load_dotenv(ENV_FILE, override=True)
        start_autopilot_scheduler()  # ensure the loop is alive
        add_log(f"Auto-Pilot {'enabled' if enabled else 'disabled'}.", "info")
        return jsonify({"ok": True, "enabled": enabled})

    return jsonify({"enabled": is_autopilot_enabled(),
                    "interval_minutes": _autopilot_interval_seconds() // 60})


@app.route('/api/stop', methods=['POST'])
def stop_task():
    with lock:
        state["stop_requested"] = True
        if state["process"]:
            try:
                state["process"].terminate()
            except Exception:
                pass
    add_log("Stop signal sent.", "err")
    return jsonify({"ok": True})


# ── Leads CRUD ────────────────────────────────

@app.route('/api/leads')
def get_leads():
    leads = []
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"leads": []})

    email_status_map = {}
    if os.path.exists(EMAIL_LOG):
        try:
            with file_lock:
                with open(EMAIL_LOG, 'r') as f:
                    for entry in json.load(f):
                        st = entry.get('status', '').lower().strip()
                        em = entry.get('email', '').lower().strip()
                        if em and st:
                            if st == 'emailed':
                                st = 'sent'
                            email_status_map[em] = st
        except Exception:
            pass

    # Load bounced domains
    bounced_domains = set()
    if os.path.exists(BOUNCED_JSON):
        try:
            with file_lock:
                with open(BOUNCED_JSON, 'r') as f:
                    bounced_domains = set(json.load(f))
        except Exception:
            pass

    try:
        with file_lock:
            with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    try:
                        email_raw = row.get('contact_email')
                        email = (email_raw or '').lower().strip()
                        domain = email.split('@')[1] if '@' in email else ''
                        
                        status = 'pending'
                        if email in email_status_map:
                            status = email_status_map[email]
                        elif domain in bounced_domains:
                            status = 'bounced'
                        leads.append({
                            "company": row.get('company_name', ''),
                            "email": email,
                            "role": row.get('role', ''),
                            "type": row.get('type', 'job'),
                            "status": status,
                            "found": row.get('notes', ''),
                        })
                    except Exception as e:
                        print(f"Error parsing row: {e}")
                        pass
    except Exception as e:
        print(f"Error reading firms.csv: {e}")
        pass

    return jsonify({"leads": leads})


@app.route('/api/leads', methods=['POST'])
def add_lead():
    data = request.json or {}
    company = data.get('company', '').strip()
    email = data.get('email', '').strip()
    role = data.get('role', '').strip() or 'Software Developer / Intern'
    lead_type = data.get('type', '').strip().lower() or 'job'
    hr = data.get('hr', 'HR Team').strip()

    if not company or not email:
        return jsonify({"error": "Company and email are required"}), 400

    with file_lock:
        file_exists = os.path.exists(FIRMS_CSV)
        with open(FIRMS_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['company_name', 'contact_email', 'role', 'hr_name', 'notes', 'type'])
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'company_name': company,
                'contact_email': email,
                'role': role,
                'hr_name': hr,
                'notes': 'Manually added',
                'type': lead_type
            })

    add_log(f"Lead added: {company} ({email})", "ok")
    return jsonify({"ok": True})


@app.route('/api/leads/<path:email>', methods=['DELETE'])
def delete_lead(email):
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"error": "No leads file"}), 404

    with file_lock:
        rows = []
        fieldnames = None
        with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if row.get('contact_email') != email:
                    rows.append(row)

        with open(FIRMS_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    add_log(f"Lead deleted: {email}", "ok")
    return jsonify({"ok": True})


@app.route('/api/leads/<path:email>/status', methods=['POST'])
def update_status(email):
    email = email.lower().strip()
    data = request.json or {}
    new_status = data.get('status', 'replied')
    try:
        with file_lock:
            with open(EMAIL_LOG, 'r') as f:
                log = json.load(f)
    except Exception:
        log = []

    updated = False
    # Update only the latest entry for this email
    for entry in reversed(log):
        if entry.get('email', '').lower().strip() == email:
            entry['status'] = new_status
            updated = True
            break
            
    if not updated:
        # Create a stub entry so we can track status even if not emailed yet
        log.append({
            "email": email,
            "status": new_status,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    with file_lock:
        with open(EMAIL_LOG, 'w') as f:
            json.dump(log, f, indent=4)
        
    return jsonify({"ok": True})


@app.route('/api/leads_bulk_delete', methods=['POST'])
def delete_bulk_leads():
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"ok": True})
        
    data = request.json or {}
    emails_to_delete = set(e.lower().strip() for e in data.get('emails', []))
    
    if not emails_to_delete:
        return jsonify({"ok": True})

    with file_lock:
        rows = []
        fieldnames = None
        with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                email_raw = row.get('contact_email')
                email_val = (email_raw or '').lower().strip()
                if email_val not in emails_to_delete:
                    rows.append(row)

        with open(FIRMS_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    add_log(f"Deleted {len(emails_to_delete)} selected leads", "ok")
    return jsonify({"ok": True})


@app.route('/api/clear_all_leads', methods=['POST'])
def clear_all_leads():
    with file_lock:
        if os.path.exists(FIRMS_CSV):
            os.remove(FIRMS_CSV)
    add_log("All leads cleared", "ok")
    return jsonify({"ok": True})


@app.route('/api/leads/export')
def export_leads():
    """Download firms.csv directly."""
    from flask import send_file
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"error": "No leads file"}), 404
    return send_file(FIRMS_CSV, mimetype='text/csv', as_attachment=True, download_name='leads_export.csv')


@app.route('/api/leads/import', methods=['POST'])
def import_leads():
    """Import leads from uploaded CSV file."""
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "Only CSV files are supported"}), 400
    
    try:
        content = file.read().decode('utf-8')
        reader = csv.DictReader(content.splitlines())
        
        with file_lock:
            existing = set()
            if os.path.exists(FIRMS_CSV):
                with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        email_raw = row.get('contact_email')
                        existing.add((email_raw or '').lower().strip())
            
            fieldnames = ['company_name', 'contact_email', 'role', 'hr_name', 'notes', 'type']
            file_exists = os.path.exists(FIRMS_CSV)
            added = 0
            
            with open(FIRMS_CSV, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                
                for row in reader:
                    email = (row.get('contact_email') or row.get('email', '')).lower().strip()
                    if not email or email in existing:
                        continue
                    writer.writerow({
                        'company_name': row.get('company_name') or row.get('company', 'Unknown'),
                        'contact_email': email,
                        'role': row.get('role', 'Software Developer'),
                        'hr_name': row.get('hr_name') or row.get('hr', 'HR Team'),
                        'notes': row.get('notes', 'Imported from CSV'),
                        'type': row.get('type', 'job'),
                    })
                    existing.add(email)
                    added += 1
        
        add_log(f"Imported {added} leads from CSV", "ok")
        return jsonify({"ok": True, "imported": added})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/clear_sent', methods=['POST'])
def clear_sent():
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"ok": True})

    sent_emails = set()
    if os.path.exists(EMAIL_LOG):
        try:
            with file_lock:
                with open(EMAIL_LOG, 'r') as f:
                    for entry in json.load(f):
                        if entry.get('status') == 'sent':
                            sent_emails.add(entry.get('email', '').lower())
        except Exception:
            pass

    if not sent_emails:
        return jsonify({"ok": True})

    with file_lock:
        rows = []
        fieldnames = None
        with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                email_raw = row.get('contact_email')
                email_val = (email_raw or '').lower().strip()
                if email_val not in sent_emails:
                    rows.append(row)

        with open(FIRMS_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    add_log(f"Cleared {len(sent_emails)} sent leads from CSV", "ok")
    return jsonify({"ok": True})


@app.route('/api/email_history')
def get_email_history():
    history = []
    if os.path.exists(EMAIL_LOG):
        try:
            with file_lock:
                with open(EMAIL_LOG, 'r') as f:
                    history = json.load(f)
        except Exception:
            pass
    # Sort history by sent_at descending
    history.sort(key=lambda x: x.get('sent_at', ''), reverse=True)
    return jsonify({"history": history})


@app.route('/api/preview_email', methods=['GET'])
def preview_email():
    """Generates an HTML preview of the email with current settings."""
    try:
        sys.path.append(BASE_DIR)
        from core.sender import get_email_html, _get_role_context, PS_LINES
        import random
        
        cfg = {
            "name": os.getenv("YOUR_NAME", "John Doe"),
            "title": os.getenv("YOUR_TITLE", "Software Engineer"),
            "skills": os.getenv("YOUR_SKILLS", "Python, React"),
            "portfolio": os.getenv("YOUR_PORTFOLIO", ""),
            "linkedin": os.getenv("YOUR_LINKEDIN", ""),
            "phone": os.getenv("PHONE", ""),
            "email": os.getenv("EMAIL", "test@example.com")
        }
        
        company = "Acme Corp"
        role = "Backend Developer"
        hr_name = "Hiring Manager"
        notes = "Focus on cloud infrastructure."
        lead_type = "job"
        
        ctx = _get_role_context(role, cfg, lead_type)
        ps_pool = PS_LINES.get(lead_type, PS_LINES["job"])
        ps_text = random.choice(ps_pool).format(phone=cfg.get("phone", ""))
        
        html = get_email_html(cfg, company, role, hr_name, ctx, ps_text, notes, lead_type)
        return jsonify({"ok": True, "html": html})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Settings ──────────────────────────────────

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    ALLOWED_KEYS = {
        "YOUR_NAME", "YOUR_TITLE", "YOUR_SKILLS", "RESUME_PATH", "YOUR_PORTFOLIO",
        "YOUR_LINKEDIN", "PHONE", "EMAIL", "APP_PASSWORD", "ROLES", "LOCATIONS",
        "SEND_DELAY", "MAX_DAY", "GEMINI_API_KEY", "ZEROBOUNCE_API_KEY", "AI_CUSTOM_PROMPT",
        "AUTOPILOT_ENABLED", "AUTOPILOT_INTERVAL_MIN", "APP_BASE_URL",
        "APIFY_API_TOKEN", "ANTHROPIC_API_KEY"
    }
    
    if request.method == 'POST':
        data = request.json or {}
        for key, value in data.items():
            if key.upper() in ALLOWED_KEYS and value is not None:
                if key.upper() in ["APP_PASSWORD", "GEMINI_API_KEY", "ZEROBOUNCE_API_KEY", "APIFY_API_TOKEN", "ANTHROPIC_API_KEY"] and value == "***":
                    continue
                set_key(ENV_FILE, key.upper(), str(value))
        load_dotenv(ENV_FILE, override=True)
        return jsonify({"ok": True})

    # GET
    load_dotenv(ENV_FILE, override=True)
    return jsonify({
        "YOUR_NAME":      os.getenv("YOUR_NAME", ""),
        "YOUR_TITLE":     os.getenv("YOUR_TITLE", ""),
        "YOUR_SKILLS":    os.getenv("YOUR_SKILLS", ""),
        "RESUME_PATH":    os.getenv("RESUME_PATH", ""),
        "YOUR_PORTFOLIO": os.getenv("YOUR_PORTFOLIO", ""),
        "YOUR_LINKEDIN":  os.getenv("YOUR_LINKEDIN", ""),
        "PHONE":          os.getenv("PHONE", ""),
        "EMAIL":          os.getenv("EMAIL", ""),
        "APP_PASSWORD":   "***" if os.getenv("APP_PASSWORD") else "",
        "ROLES":          os.getenv("ROLES", ""),
        "LOCATIONS":      os.getenv("LOCATIONS", "Remote, India"),
        "SEND_DELAY":     os.getenv("SEND_DELAY", "10"),
        "MAX_DAY":        os.getenv("MAX_DAY", "50"),
        "GEMINI_API_KEY": "***" if os.getenv("GEMINI_API_KEY") else "",
        "ZEROBOUNCE_API_KEY": "***" if os.getenv("ZEROBOUNCE_API_KEY") else "",
        "APIFY_API_TOKEN": "***" if os.getenv("APIFY_API_TOKEN") else "",
        "ANTHROPIC_API_KEY": "***" if os.getenv("ANTHROPIC_API_KEY") else "",
        "AI_CUSTOM_PROMPT": os.getenv("AI_CUSTOM_PROMPT", ""),
        "AUTOPILOT_INTERVAL_MIN": os.getenv("AUTOPILOT_INTERVAL_MIN", "30"),
        "APP_BASE_URL":   os.getenv("APP_BASE_URL", "http://127.0.0.1:5000"),
    })


if __name__ == '__main__':
    import webbrowser
    from threading import Timer
    def open_browser():
        webbrowser.open_new('http://127.0.0.1:5000/')
    Timer(1, open_browser).start()
    # Start headless Auto-Pilot scheduler (resumes if AUTOPILOT_ENABLED=1).
    start_autopilot_scheduler()
    app.run(host='127.0.0.1', port=5000, debug=False)
