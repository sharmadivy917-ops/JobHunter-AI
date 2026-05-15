"""
sender.py — Personalized HTML email sender with resume attachment.
Ported from the mature root email_sender.py with full template and MX verification.
ENHANCED: Comprehensive role-specific body content and personalization.
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


def _get_role_context(role: str, cfg: dict) -> dict:
    """Classify the role string into a category and return tailored copy blocks with comprehensive personalization."""
    role_lower = role.lower()

    CATEGORIES = [
        (["frontend", "front-end", "react", "vue", "angular", "ui", "ux", "css", "html", "javascript", "typescript", "web dev"], "frontend"),
        (["backend", "back-end", "django", "flask", "node", "api", "server", "sql", "postgres", "python", "java", "golang"], "backend"),
        (["fullstack", "full-stack", "mern", "lamp", "full stack"], "fullstack"),
        (["data scientist", "machine learning", "ml", "ai", "deep learning", "nlp", "computer vision", "pytorch", "tensorflow"], "ml"),
        (["data analyst", "power bi", "tableau", "analytics", "reporting", "sql analyst", "business intelligence"], "data_analyst"),
        (["devops", "sre", "cloud", "aws", "azure", "docker", "kubernetes", "ci/cd", "infrastructure", "terraform"], "devops"),
        (["mechanical", "manufacturing", "production", "design engineer", "cad", "solidworks", "catia"], "mechanical"),
        (["finance", "account", "audit", "tax", "banking", "financial analyst", "accountant"], "finance"),
        (["marketing", "seo", "content", "social media", "growth", "brand", "campaign"], "marketing"),
        (["hr ", "human resources", "talent", "recruitment"], "hr"),
    ]

    category = "general"
    for keywords, cat in CATEGORIES:
        if any(kw in role_lower for kw in keywords):
            category = cat
            break

    skills = cfg.get("skills", "")
    title = cfg.get("title", "professional")

    COPY = {
        "frontend": {
            "intro": f"I am reaching out to express my strong interest in the <strong>{role}</strong> position at your organization. As a frontend-focused developer, I specialize in crafting fast, accessible, and visually polished user interfaces using <strong>{skills}</strong>.",
            "body": "I'm passionate about creating exceptional user experiences that combine aesthetic design with robust functionality. My approach prioritizes performance optimization, cross-browser compatibility, and adherence to modern web standards. I specialize in building scalable component libraries, implementing complex state management, and mentoring junior developers in frontend best practices. I have a proven track record of reducing bundle sizes, improving Core Web Vitals, and delivering responsive designs that work seamlessly across all devices.",
            "highlights": [
                f"Expert in component-driven UI development with <strong>{skills}</strong> and design systems",
                "Strong focus on Core Web Vitals, accessibility (WCAG 2.1), and responsive design",
                "Proficient in state management solutions, testing frameworks, and performance profiling tools",
                "Experience integrating REST and GraphQL APIs into seamless, real-time user experiences",
                "Proven track record improving page load times by 40%+ and reducing bundle sizes significantly",
                "Experience leading frontend architecture decisions and implementing modern development practices",
                "Open to <strong>on-site, hybrid, and remote</strong> engagements"
            ],
            "closing": "I believe my dedication to frontend excellence, performance, and user-centric design aligns perfectly with your team's vision and roadmap."
        },
        "backend": {
            "intro": f"I am writing to apply for the <strong>{role}</strong> position with your organization. I build robust, scalable server-side systems and APIs using <strong>{skills}</strong>, maintaining a strong emphasis on reliability, security, and clean architecture.",
            "body": "I excel at designing system architectures that scale with business demands, implementing efficient database schemas, and crafting APIs that are both powerful and intuitive. My experience spans from monolithic architectures to microservices, with deep understanding of trade-offs, caching strategies, and eventual consistency patterns. I'm committed to writing maintainable code, implementing comprehensive logging and monitoring, and ensuring production systems remain stable under high load.",
            "highlights": [
                f"Proficient in <strong>{skills}</strong> for high-performance backend systems and API design",
                "Experienced in scalable API design, OAuth/JWT authentication, and advanced database optimization",
                "Strong expertise in microservices, event-driven architectures, and message queue systems (RabbitMQ, Kafka)",
                "Familiar with containerization, load balancing, CDN integration, and cloud-native deployments",
                "Demonstrated ability to reduce database query times by 60%+ through intelligent indexing",
                "Experience implementing comprehensive error handling, logging, and health check systems",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm confident I can contribute to building backend systems that power your platform's growth, reliability, and ability to serve millions of requests."
        },
        "fullstack": {
            "intro": f"I am excited to apply for the <strong>{role}</strong> role with your team. I work across the full tech stack using <strong>{skills}</strong>, and I thrive in environments that value end-to-end ownership, autonomy, and rapid iteration.",
            "body": "As a full-stack developer, I bring the ability to understand and optimize every layer of the application, from database schema design to user interface interactions. I'm comfortable making architectural decisions, setting up development infrastructure, implementing CI/CD pipelines, and delivering complete features from conception to production. My strength lies in shipping fast while maintaining code quality, and in my ability to debug issues across the entire stack.",
            "highlights": [
                f"End-to-end development expertise with <strong>{skills}</strong>, from backend APIs to modern frontends",
                "Ability to own complete feature lifecycles independently—architecture, implementation, testing, deployment",
                "Proficient with modern development tools: Git workflows, CI/CD pipelines, Docker, cloud platforms",
                "Strong communication skills enabling effective collaboration with product, design, and ops teams",
                "Experience optimizing both frontend performance and backend efficiency for maximum throughput",
                "Proven ability to set up and maintain development infrastructure and deployment pipelines",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm eager to join a team where I can leverage my full-stack capabilities to ship meaningful features quickly and maintain high code quality."
        },
        "ml": {
            "intro": f"I am writing to express my strong interest in the <strong>{role}</strong> position. I design, train, and deploy machine learning systems using <strong>{skills}</strong>, with hands-on experience spanning exploratory data analysis, model development, validation, and production serving.",
            "body": "I'm passionate about translating business problems into data science solutions that drive measurable impact. My approach combines statistical rigor with practical engineering: I focus deeply on feature engineering, model selection, hyperparameter tuning, and deploying models that improve key metrics. I'm also committed to monitoring model performance in production, implementing automated retraining pipelines, and ensuring models remain fair and interpretable.",
            "highlights": [
                f"Hands-on expertise with <strong>{skills}</strong> for predictive modeling, computer vision, and NLP applications",
                "End-to-end ML workflows: data collection → EDA → feature engineering → training → evaluation → production deployment",
                "Experience building recommendation systems, classification models, time-series forecasting, and clustering solutions",
                "Strong foundation in statistics, probability theory, and understanding fundamental model trade-offs",
                "Skilled in evaluating models using appropriate metrics (precision, recall, F1, AUC) and communicating results to stakeholders",
                "Experience with MLOps: model versioning, automated testing, deployment pipelines, and monitoring",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm committed to applying machine learning to solve real-world challenges and contributing to your team's ML initiatives in a production-focused way."
        },
        "data_analyst": {
            "intro": f"I am excited to apply for the <strong>{role}</strong> position. With a strong background in data analysis using <strong>{skills}</strong>, I excel at transforming raw data into actionable insights that drive strategic business decisions.",
            "body": "I specialize in querying large datasets efficiently, building intuitive dashboards for executive stakeholders, and performing deep exploratory analysis to uncover trends, patterns, and opportunities. I combine technical SQL and visualization skills with strong business acumen to ensure insights translate into measurable impact and drive decision-making across the organization.",
            "highlights": [
                f"Proficient in <strong>{skills}</strong> for complex data querying, transformation, and visualization",
                "Experienced in building interactive dashboards and automated reporting solutions that executives rely on",
                "Strong analytical mindset: identifying key questions, formulating hypotheses, validating insights with data",
                "Skilled in communicating complex findings to both technical and non-technical audiences",
                "Experience optimizing SQL queries for performance on datasets with millions of rows",
                "Proficiency in statistical analysis, A/B testing, and experimental design for decision-making",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm ready to contribute to your analytics team and support data-driven decision-making across all levels of the organization."
        },
        "devops": {
            "intro": f"I am writing to apply for the <strong>{role}</strong> position with your organization. I design, build, and maintain cloud infrastructure and CI/CD pipelines using <strong>{skills}</strong>, enabling development teams to ship reliably and frequently.",
            "body": "I'm passionate about automating infrastructure, reducing deployment friction, and maintaining comprehensive observability across systems. I bring expertise in containerization, orchestration, infrastructure-as-code, and advanced monitoring—ensuring systems are resilient, scalable, secure, and efficient. I'm experienced in debugging production issues, implementing disaster recovery procedures, and optimizing cloud costs.",
            "highlights": [
                f"Deep expertise in <strong>{skills}</strong> for infrastructure provisioning and automation",
                "Proficient in containerization (Docker), orchestration (Kubernetes), and infrastructure-as-code (Terraform, CloudFormation)",
                "Strong background in CI/CD pipeline design, GitOps practices, and blue-green deployment strategies",
                "Experience with cloud platforms (AWS, Azure, GCP): VPCs, managed databases, networking, security",
                "Skilled in setting up comprehensive logging (ELK, DataDog), metrics collection, and intelligent alerting",
                "Experience securing infrastructure, implementing least-privilege access, and ensuring compliance",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm ready to streamline your infrastructure, empower your development team with robust deployment pipelines, and ensure your systems remain reliable at scale."
        },
        "mechanical": {
            "intro": f"I am writing to apply for the <strong>{role}</strong> position. As an engineering professional with a strong background in mechanical design and analysis using <strong>{skills}</strong>, I bring expertise in translating innovative concepts into manufacturable, cost-effective products.",
            "body": "I excel at detailed CAD modeling, performing structural and thermal analysis, and collaborating closely with manufacturing and production teams. My approach balances innovation with practicality, ensuring designs are both cutting-edge and producible. I'm committed to quality standards compliance, continuous improvement initiatives, and staying current with emerging materials and manufacturing techniques.",
            "highlights": [
                f"Proficient in mechanical engineering tools and CAD software: <strong>{skills}</strong>",
                "Strong experience in CAD modeling, finite element analysis (FEA), thermal analysis, and PLM systems",
                "Demonstrated ability in design optimization, tolerance stack-up analysis, and materials selection",
                "Deep knowledge of manufacturing processes, quality control, and design-for-manufacturability (DFM)",
                "Experience collaborating with cross-functional teams from concept through production launch",
                "Skilled in technical documentation, creating assembly instructions, and managing product revisions",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm eager to contribute my engineering expertise to your team's product development, innovation initiatives, and drive toward manufacturing excellence."
        },
        "finance": {
            "intro": f"I am excited to apply for the <strong>{role}</strong> position with your organization. With a strong foundation in financial analysis, modeling, and strategy, alongside expertise in <strong>{skills}</strong>, I'm well-positioned to support your team's financial objectives.",
            "body": "I combine technical financial acumen with analytical rigor, excelling in financial modeling, variance analysis, and strategic forecasting. My experience includes working cross-functionally with operations and leadership to align financial strategies with business goals. I'm skilled at identifying cost optimization opportunities, managing complex budgets, and presenting financial insights clearly to senior management.",
            "highlights": [
                f"Expertise in financial modeling, analysis, and reporting using <strong>{skills}</strong>",
                "Strong understanding of accounting principles, compliance requirements, and regulatory standards",
                "Proven track record in budget forecasting, variance analysis, financial planning, and FP&A",
                "Skilled in data visualization and presenting complex financial insights clearly to executives",
                "Experience with audit preparation, risk management frameworks, and internal controls",
                "Ability to analyze financial statements and provide strategic recommendations for improvement",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm ready to contribute to your finance team and support strategic financial planning, analysis, and decision-making."
        },
        "marketing": {
            "intro": f"I am writing to express my strong interest in the <strong>{role}</strong> position. With expertise in <strong>{skills}</strong> and a data-driven approach to marketing, I'm committed to driving growth and engagement for your brand.",
            "body": "I excel at developing integrated marketing campaigns that blend creative storytelling with analytics-driven optimization. I'm experienced in leveraging digital channels strategically, interpreting performance metrics deeply, and continuously improving ROI through A/B testing and experimentation. My approach combines art and science to build brand awareness while delivering measurable business results.",
            "highlights": [
                f"Proficient in <strong>{skills}</strong> for campaign execution, optimization, and analytics",
                "Strong background in digital marketing strategy, content creation, and audience engagement",
                "Data-driven approach: A/B testing, analytics interpretation, attribution modeling, and ROI tracking",
                "Experience managing marketing budgets, demonstrating clear ROI, and optimizing spend allocation",
                "Skilled in cross-functional collaboration with sales, product, design, and customer success teams",
                "Experience building marketing campaigns that increase conversions by 30%+ and reduce CAC",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm eager to bring marketing expertise, creativity, and a growth mindset to your team's success and expansion."
        },
        "general": {
            "intro": f"I am writing to express my keen interest in the <strong>{role}</strong> position with your organization. As a dedicated <strong>{title}</strong> with expertise in <strong>{skills}</strong>, I am eager to contribute meaningfully to your team.",
            "body": "I bring a proven track record of delivering high-quality work, solving complex problems effectively, and collaborating seamlessly across teams. I'm passionate about continuous learning, adapting to new technologies and methodologies, and bringing a positive, solution-oriented mindset to every challenge.",
            "highlights": [
                f"Proficient in <strong>{skills}</strong> with a strong growth mindset and passion for learning new tools",
                "Proven ability to deliver high-quality projects and solutions with meticulous attention to detail",
                "Strong problem-solving skills combined with a focus on efficiency, accuracy, and impact",
                "Experience collaborating effectively with cross-functional teams in fast-paced, dynamic environments",
                "Committed to professional development and staying current with industry trends and best practices",
                "Open to <strong>on-site, hybrid, and remote</strong> work arrangements"
            ],
            "closing": "I'm confident I can make a meaningful contribution to your organization's success and growth."
        }
    }
    
    # Fallback to general if category not fully defined
    return COPY.get(category, COPY["general"])


def get_email_html(cfg, company, role, hr_name):
    """Generate the rich HTML email body with comprehensive role-specific content."""
    portfolio_btn = ""
    if cfg["portfolio"]:
        portfolio_btn = f'<a href="{cfg["portfolio"]}" target="_blank" style="display:inline-block;background:#1A56A0;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;margin-right:10px;">Portfolio</a>'

    linkedin_btn = ""
    if cfg["linkedin"]:
        linkedin_btn = f'<a href="{cfg["linkedin"]}" target="_blank" style="display:inline-block;background:#0077B5;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">LinkedIn Profile</a>'

    ctx = _get_role_context(role, cfg)
    intro = ctx["intro"]
    body = ctx["body"]
    bullets = "".join(f"<li style='margin-bottom:8px;color:#333;'>{h}</li>" for h in ctx["highlights"])
    closing = ctx["closing"]

    return f"""
    <html>
    <body style="font-family:'Segoe UI',Arial,sans-serif;max-width:700px;margin:auto;padding:12px;color:#222;line-height:1.6;background-color:#f9f9f9;">
        <div style="background-color:#fff;border-radius:8px;padding:20px;box-shadow:0 2px 4px rgba(0,0,0,0.05);">
            <div style="height:4px;background:linear-gradient(90deg,#1A56A0,#4A90D9,#6CB4EE);border-radius:4px;margin-bottom:28px;"></div>

            <p style="margin-bottom:16px;font-size:16px;">Dear {hr_name},</p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;">{intro}</p>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;color:#444;">{body}</p>

            <p style="margin-bottom:12px;font-size:15px;font-weight:600;color:#1A56A0;">Key Strengths & Experience:</p>

            <ul style="padding-left:24px;color:#333;margin-bottom:20px;">
                {bullets}
            </ul>

            <p style="margin-bottom:16px;font-size:15px;line-height:1.8;">I have attached my resume for your detailed review. It outlines my specific achievements, certifications, and relevant project experience.</p>

            <div style="margin:24px 0;padding:16px;background-color:#f0f4f8;border-left:4px solid #1A56A0;border-radius:4px;">
                <p style="margin:0;font-size:14px;color:#333;font-style:italic;line-height:1.7;">{closing} I would welcome the opportunity to discuss how my background aligns with the needs of your team at <strong>{company}</strong>.</p>
            </div>

            <div style="margin:20px 0;">{portfolio_btn}{linkedin_btn}</div>

            <p style="margin-bottom:24px;font-size:15px;">I am available for an interview at your earliest convenience and look forward to connecting with you.</p>

            <p style="margin-bottom:8px;font-size:15px;">Thank you for considering my application.</p>

            <div style="margin-top:32px;padding-top:16px;border-top:2px solid #e0e0e0;">
                <p style="margin:0;font-weight:700;color:#1A56A0;font-size:16px;">{cfg['name']}</p>
                <p style="margin:4px 0;color:#666;font-size:14px;">{cfg['email']}</p>
                <p style="margin:4px 0;color:#999;font-size:13px;">Applied for: <strong>{role}</strong> at <strong>{company}</strong></p>
            </div>
        </div>
    </body>
    </html>
    """


def get_email_plain(cfg, company, role, hr_name):
    """Plain text fallback with full personalization."""
    import re
    ctx = _get_role_context(role, cfg)
    intro = re.sub(r"<[^>]+>", "", ctx["intro"])
    body = re.sub(r"<[^>]+>", "", ctx["body"])
    bullets = "\n".join(f"  • {re.sub(r'<[^>]+>', '', h)}" for h in ctx["highlights"])
    closing = re.sub(r"<[^>]+>", "", ctx["closing"])

    return f"""Dear {hr_name},

{intro}

{body}

Key Strengths & Experience:
{bullets}

I have attached my resume for your detailed review.

{closing} I would welcome the opportunity to discuss how my background aligns with the needs of your team at {company}.

I am available for an interview at your earliest convenience and look forward to connecting with you.

Thank you for considering my application.

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
            msg["Subject"] = f"Application for {role} — {cfg['name']}"
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
