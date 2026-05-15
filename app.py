import os
import sys
import csv
import json
import threading
import subprocess
from collections import deque
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv, set_key

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, '.env')
FIRMS_CSV = os.path.join(BASE_DIR, 'firms.csv')
EMAIL_LOG = os.path.join(BASE_DIR, 'email_log.json')
BOUNCED_JSON = os.path.join(BASE_DIR, 'bounced_domains.json')

if not os.path.exists(ENV_FILE):
    open(ENV_FILE, 'w').close()
load_dotenv(ENV_FILE)

# ── Thread-safe state ────────────────────────
lock = threading.Lock()
state = {
    "running": False,
    "stop_requested": False,
    "log": [],       # list of {msg, level, ts}
    "process": None,
}

def add_log(msg, level=""):
    with lock:
        state["log"].append({
            "msg": msg,
            "level": level,
            "ts": datetime.now().strftime("%H:%M:%S")
        })
        # Keep manageable size
        if len(state["log"]) > 300:
            state["log"] = state["log"][-300:]

def get_stats():
    """Compute live stats from files."""
    total = 0
    if os.path.exists(FIRMS_CSV):
        try:
            with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
                total = sum(1 for _ in csv.DictReader(f))
        except:
            pass

    sent = 0
    bounced_log = 0
    if os.path.exists(EMAIL_LOG):
        try:
            with open(EMAIL_LOG, 'r') as f:
                log = json.load(f)
                sent = sum(1 for e in log if e.get('status') == 'sent')
                bounced_log = sum(1 for e in log if e.get('status') == 'bounced')
        except:
            pass

    bounced_domains = 0
    if os.path.exists(BOUNCED_JSON):
        try:
            with open(BOUNCED_JSON, 'r') as f:
                bounced_domains = len(json.load(f))
        except:
            pass

    bounced = max(bounced_log, bounced_domains)
    pending = max(0, total - sent)

    return {"total": total, "sent": sent, "pending": pending, "bounced": bounced}


def run_script(script_name, env_overrides=None):
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
                     'ROLES', 'LOCATIONS', 'RESUME_PATH', 'YOUR_PORTFOLIO', 'YOUR_LINKEDIN',
                     'SEND_DELAY', 'MAX_DAY']:
            val = os.getenv(key)
            if val:
                env[key] = val

        if env_overrides:
            env.update(env_overrides)

        cmd = [sys.executable, os.path.join(BASE_DIR, "core", script_name)]
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            env=env, cwd=BASE_DIR
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
        t = threading.Thread(target=run_script, args=("hunter.py",), kwargs={"env_overrides": env})
        t.daemon = True
        t.start()

    elif action == 'send':
        env = {}
        if data.get('delay'):
            env['SEND_DELAY'] = str(data['delay'])
        if data.get('max'):
            env['SEND_MAX'] = str(data['max'])
        t = threading.Thread(target=run_script, args=("sender.py",), kwargs={"env_overrides": env})
        t.daemon = True
        t.start()

    elif action == 'clean':
        t = threading.Thread(target=run_script, args=("bounce_handler.py",))
        t.daemon = True
        t.start()

    else:
        return jsonify({"error": f"Unknown action: {action}"})

    return jsonify({"ok": True})


@app.route('/api/stop', methods=['POST'])
def stop_task():
    with lock:
        state["stop_requested"] = True
        if state["process"]:
            try:
                state["process"].terminate()
            except:
                pass
    add_log("Stop signal sent.", "err")
    return jsonify({"ok": True})


# ── Leads CRUD ────────────────────────────────

@app.route('/api/leads')
def get_leads():
    leads = []
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"leads": []})

    # Load sent emails
    sent_emails = set()
    if os.path.exists(EMAIL_LOG):
        try:
            with open(EMAIL_LOG, 'r') as f:
                for entry in json.load(f):
                    if entry.get('status') == 'sent':
                        sent_emails.add(entry.get('email', '').lower())
        except:
            pass

    # Load bounced domains
    bounced_domains = set()
    if os.path.exists(BOUNCED_JSON):
        try:
            with open(BOUNCED_JSON, 'r') as f:
                bounced_domains = set(json.load(f))
        except:
            pass

    try:
        with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                email = row.get('contact_email', '').lower().strip()
                domain = email.split('@')[1] if '@' in email else ''
                status = 'pending'
                if email in sent_emails:
                    status = 'sent'
                elif domain in bounced_domains:
                    status = 'bounced'
                leads.append({
                    "company": row.get('company_name', ''),
                    "email": row.get('contact_email', ''),
                    "role": row.get('role', ''),
                    "status": status,
                    "found": row.get('notes', ''),
                })
    except:
        pass

    return jsonify({"leads": leads})


@app.route('/api/leads', methods=['POST'])
def add_lead():
    data = request.json or {}
    company = data.get('company', '').strip()
    email = data.get('email', '').strip()
    role = data.get('role', '').strip() or 'Software Developer'
    hr = data.get('hr', 'HR Team').strip()

    if not company or not email:
        return jsonify({"error": "Company and email are required"}), 400

    file_exists = os.path.exists(FIRMS_CSV)
    with open(FIRMS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['company_name', 'contact_email', 'role', 'hr_name', 'notes'])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            'company_name': company,
            'contact_email': email,
            'role': role,
            'hr_name': hr,
            'notes': 'Manually added'
        })

    add_log(f"Lead added: {company} ({email})", "ok")
    return jsonify({"ok": True})


@app.route('/api/leads/<path:email>', methods=['DELETE'])
def delete_lead(email):
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"error": "No leads file"}), 404

    rows = []
    fieldnames = None
    with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row.get('contact_email', '').lower().strip() != email.lower().strip():
                rows.append(row)

    with open(FIRMS_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    add_log(f"Lead deleted: {email}", "ok")
    return jsonify({"ok": True})


@app.route('/api/clear_sent', methods=['POST'])
def clear_sent():
    if not os.path.exists(FIRMS_CSV):
        return jsonify({"ok": True})

    sent_emails = set()
    if os.path.exists(EMAIL_LOG):
        try:
            with open(EMAIL_LOG, 'r') as f:
                for entry in json.load(f):
                    if entry.get('status') == 'sent':
                        sent_emails.add(entry.get('email', '').lower())
        except:
            pass

    if not sent_emails:
        return jsonify({"ok": True})

    rows = []
    fieldnames = None
    with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row.get('contact_email', '').lower().strip() not in sent_emails:
                rows.append(row)

    with open(FIRMS_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    add_log(f"Cleared {len(sent_emails)} sent leads from CSV", "ok")
    return jsonify({"ok": True})


# ── Settings ──────────────────────────────────

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        data = request.json or {}
        for key, value in data.items():
            if value is not None:
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
        "EMAIL":          os.getenv("EMAIL", ""),
        "APP_PASSWORD":   os.getenv("APP_PASSWORD", ""),
        "ROLES":          os.getenv("ROLES", ""),
        "LOCATIONS":      os.getenv("LOCATIONS", "Remote, India"),
        "SEND_DELAY":     os.getenv("SEND_DELAY", "10"),
        "MAX_DAY":        os.getenv("MAX_DAY", "50"),
    })


if __name__ == '__main__':
    import webbrowser
    from threading import Timer
    def open_browser():
        webbrowser.open_new('http://127.0.0.1:5000/')
    Timer(1, open_browser).start()
    app.run(host='127.0.0.1', port=5000, debug=False)
