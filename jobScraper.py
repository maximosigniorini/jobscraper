import os
import requests
import json
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict

# --- Load environment variables ---
load_dotenv()

URL = "https://devbrada.com/jobs"

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
# ⬅️ Fetch from .env
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
# ⬅️ Fetch from .env
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

EXCLUDED_CATEGORIES = {"Software"}
EXCLUDED_COUNTRIES = {"United States"}

# --- Persistence file path ---
SEEN_JOBS_FILE = "seen_jobs.json"

def load_seen_jobs():
    """Load seen jobs from a JSON file, or return an empty set if the file doesn't exist."""
    try:
        with open(SEEN_JOBS_FILE, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen_jobs(jobs_set):
    """Save the set of seen jobs to a JSON file."""
    with open(SEEN_JOBS_FILE, 'w') as f:
        json.dump(list(jobs_set), f)

def fetch_jobs():
    response = requests.get(URL)
    response.raise_for_status()
    return response.json()

def filter_jobs(jobs):
    filtered = []
    for job in jobs:
        if job["category"] in EXCLUDED_CATEGORIES:
            continue
        if job["country"] in EXCLUDED_COUNTRIES:
            continue
        filtered.append(job)
    return filtered

def parse_date(iso_string):
    try:
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    except Exception:
        return None

def format_date(iso_string):
    dt = parse_date(iso_string)
    if dt:
        return dt.strftime("%b %d, %Y")
    return iso_string

def send_email(new_jobs):
    grouped = defaultdict(list)
    for job in new_jobs:
        grouped[job["category"]].append(job)

    for category in grouped:
        grouped[category].sort(
            key=lambda job: parse_date(job["date"]) or datetime.min,
            reverse=True
        )

    special_order = ["Post", "Media"]
    categories_in_order = (
        [c for c in special_order if c in grouped] +
        sorted([c for c in grouped.keys() if c not in special_order])
    )

    sections = []
    for category in categories_in_order:
        jobs_html = []
        for job in grouped[category]:
            posted_date = format_date(job['date'])
            jobs_html.append(f"""
                <li style="margin-bottom:15px;">
                    <a href="{job['href']}" style="font-weight:bold; font-size:14px; color:#1a73e8; text-decoration:none;">
                        {job['title']}
                    </a><br>
                    <span style="color:#555;">{job['studio']} — {job['city']}, {job['country']}</span><br>
                    <span style="font-size:12px; color:#888;">Posted: {posted_date}</span>
                </li>
            """)
        section_html = f"""
            <h3 style="color:#222; border-bottom:1px solid #ddd; padding-bottom:5px;">{category}</h3>
            <ul style="list-style-type:none; padding:0; margin:0 0 20px 0;">
                {''.join(jobs_html)}
            </ul>
        """
        sections.append(section_html)

    html_content = f"""
    <html>
    <body style="font-family:Arial, sans-serif; line-height:1.5; color:#333;">
        <h2 style="color:#333;">New Jobs on DevBrada</h2>
        {''.join(sections)}
    </body>
    </html>
    """

    message = Mail(
        from_email=EMAIL_SENDER,
        to_emails=EMAIL_RECEIVER,
        subject=f"{len(new_jobs)} New Job(s) on DevBrada",
        html_content=html_content
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"Email sent! Status: {response.status_code}")
    except Exception as e:
        print("Error sending email:", e)

def check_for_new_jobs():
    seen_jobs = load_seen_jobs()
    jobs = fetch_jobs()
    jobs = filter_jobs(jobs)

    new_jobs = [job for job in jobs if job["href"] not in seen_jobs]
    current_jobs_hrefs = {job["href"] for job in jobs}

    if new_jobs:
        print(f"Found {len(new_jobs)} new job(s) after filtering!")
        send_email(new_jobs)
        save_seen_jobs(current_jobs_hrefs)
    else:
        print("No new jobs found (after filtering).")

check_for_new_jobs()