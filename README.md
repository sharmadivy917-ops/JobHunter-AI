

https://github.com/user-attachments/assets/47643ad1-393a-44a8-adcc-08271cd1d758

# JobHunter-AI

> Autonomous job application engine — finds companies hiring for any role, sends personalized emails with your resume, and cleans bounced addresses. All from a single dashboard.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000?logo=flask)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

| Module | What it does |
|--------|-------------|
| **Hunter** | Enter any job role → searches the web for companies hiring that role → extracts HR/career emails automatically |
| **Sender** | Sends personalized HTML emails with your resume attached, MX verification, random delays to avoid spam |
| **Bounce Handler** | Scans Gmail inbox for bounce-backs via IMAP, removes dead addresses from your lead database |
| **Dashboard** | Live stats, activity log, quick actions — everything in one place |
| **Leads Manager** | Searchable table of all discovered companies, add/delete leads manually |

## Screenshots

*Run the app and visit `http://127.0.0.1:5000` to see the dashboard*

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/sharmadivy917-ops/JobHunter-AI.git
cd JobHunter-AI
pip install -r requirements.txt
```

### 2. Configure

Create a `.env` file in the project root:

```env
EMAIL=you@gmail.com
APP_PASSWORD=xxxx xxxx xxxx xxxx
YOUR_NAME=Your Name
YOUR_TITLE=Software Developer
YOUR_SKILLS=Python, React, ML
ROLES=Python Developer, React Engineer
LOCATIONS=Remote, India
RESUME_PATH=C:\path\to\resume.pdf
YOUR_PORTFOLIO=https://github.com/yourname
YOUR_LINKEDIN=https://linkedin.com/in/yourname
```

> **Gmail App Password**: Go to [myaccount.google.com](https://myaccount.google.com) → Security → 2-Step Verification → App Passwords → Generate one for "Mail".

### 3. Run

```bash
python app.py
```

Opens automatically at `http://127.0.0.1:5000`

## How It Works

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│   Hunter     │────▶│  firms.csv   │────▶│    Sender     │
│ (find firms) │     │ (lead DB)    │     │ (send emails) │
└─────────────┘     └──────────────┘     └───────────────┘
                           │                      │
                           ▼                      ▼
                    ┌──────────────┐     ┌───────────────┐
                    │  Dashboard   │     │ Bounce Handler │
                    │  (live stats)│     │ (clean inbox)  │
                    └──────────────┘     └───────────────┘
```

1. **Hunter** searches DuckDuckGo/Bing/Google for companies hiring your target roles
2. Visits result pages and extracts career emails (hr@, careers@, jobs@, etc.)
3. Saves new leads to `firms.csv`
4. **Sender** reads `firms.csv`, sends personalized HTML emails with your resume
5. **Bounce Handler** checks Gmail for bounced emails and removes dead addresses

## Project Structure

```
JobHunter-AI/
├── app.py                 # Flask backend + API endpoints
├── .env                   # Your config (git-ignored)
├── requirements.txt       # Python dependencies
├── core/
│   ├── hunter.py          # Multi-engine company discovery
│   ├── sender.py          # Email sender with HTML templates
│   └── bounce_handler.py  # Gmail bounce scanner
├── templates/
│   └── index.html         # Dashboard UI
└── static/
    ├── style.css           # Dark terminal-inspired theme
    └── script.js           # Frontend logic
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Live stats + engine state + log |
| `/api/run/hunt` | POST | Start the hunter |
| `/api/run/send` | POST | Start the email sender |
| `/api/run/clean` | POST | Start the bounce handler |
| `/api/stop` | POST | Stop any running task |
| `/api/leads` | GET | List all leads with status |
| `/api/leads` | POST | Add a new lead |
| `/api/leads/<email>` | DELETE | Delete a lead |
| `/api/settings` | GET/POST | Load/save .env config |

## Tech Stack

- **Backend**: Python, Flask
- **Frontend**: Vanilla HTML/CSS/JS
- **Email**: Gmail SMTP/IMAP
- **Search**: DuckDuckGo, Bing, Google (multi-engine fallback)
- **Fonts**: IBM Plex Mono, Syne

## License

MIT — use it however you want.
