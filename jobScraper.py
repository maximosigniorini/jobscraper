import os
import cloudscraper
import json
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict

# --- Load environment variables ---
load_dotenv()

URL = "https://devbrada.com/jobs"

# ⬅️ Fetch from .env (Updated variable names)
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
EMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")  # New variable for your App Password

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
    scraper = cloudscraper.create_scraper()
    response = scraper.get(URL)
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

def get_audio_gigs_from_reddit(seen_jobs, limit_per_sub=5):
    """
    Scrapes subreddits for STRICTLY PAID audio/music gigs, filtering out portfolios and hobby projects.
    Uses cloudscraper to attempt bypassing 403 blocks.
    """
    subreddits = ["INAT", "gameDevClassifieds", "gameaudio", "Filmmakers"]
    
    # Using more robust browser-like headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.reddit.com/'
    }
    
    # 1. Must contain at least one of these (What the job is)
    audio_keywords = ["sound designer", "sound design", "composer", "music", "sfx", "audio", "ost"]
    
    # 2. Must ALSO contain at least one of these (Proof that it pays)
    paid_keywords = ["[paid]", "paid", "hiring", "contract", "freelance", "budget", "compensation"]
    
    # 3. Must NOT contain any of these (Filtering out competitors and unpaid work)
    exclude_keywords = [
        "for hire", "forhire", "portfolio", "my music", "hire me", 
        "hobby", "revshare", "rev-share", "revenue share", "unpaid"
    ]

    reddit_results = []
    all_fetched_reddit_urls = set()
    
    scraper = cloudscraper.create_scraper()

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=35" 
        try:
            # Adding a small sleep to be polite and avoid rate limits
            time.sleep(2)
            response = scraper.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            matched_count = 0
            for post in data['data']['children']:
                title = post['data']['title'].lower()
                permalink = post['data']['permalink']
                post_url = f"https://www.reddit.com{permalink}"
                
                all_fetched_reddit_urls.add(post_url)
                
                if post_url in seen_jobs:
                    continue
                
                # Check our three conditions
                has_audio = any(kw in title for kw in audio_keywords)
                has_paid = any(kw in title for kw in paid_keywords)
                has_exclusion = any(kw in title for kw in exclude_keywords)
                
                # STRICT FILTER: Needs Audio AND Needs Paid AND NO Exclusions
                if has_audio and has_paid and not has_exclusion:
                    display_title = post['data']['title']
                    reddit_results.append(f"""
                        <li style="margin-bottom:15px;">
                            <span style="color:#555; font-weight:bold;">[r/{sub}]</span><br>
                            <a href='{post_url}' style="font-weight:bold; font-size:14px; color:#ff4500; text-decoration:none;">
                                {display_title}
                            </a>
                        </li>
                    """)
                    matched_count += 1
                    
                if matched_count >= limit_per_sub:
                    break
        except Exception as e:
            print(f"Error fetching from r/{sub}: {e}")
            
    return reddit_results, all_fetched_reddit_urls


def send_email(new_jobs, reddit_jobs):
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
    
    # 1. DevBrada Jobs Section
    if new_jobs:
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
                <ul style="list-style-type:none; padding:0; margin:0 20px 20px 0;">
                    {''.join(jobs_html)}
                </ul>
            """
            sections.append(section_html)
    else:
        sections.append("<p>No new DevBrada jobs today.</p>")

    # 2. Reddit Gigs Section
    reddit_section = f"""
        <h3 style="color:#222; border-bottom:1px solid #ddd; padding-bottom:5px; margin-top:30px;">🎧 Reddit Audio Gigs</h3>
        <ul style="list-style-type:none; padding:0; margin:0 20px 20px 0;">
    """
    if reddit_jobs:
        reddit_section += ''.join(reddit_jobs)
    else:
        reddit_section += "<li>No new relevant Reddit posts today.</li>"
    reddit_section += "</ul>"
    
    sections.append(reddit_section)

    html_body = f"""
    <html>
    <body style="font-family:Arial, sans-serif; line-height:1.5; color:#333;">
        <h2 style="color:#333;">Daily Job & Gig Scrape</h2>
        {''.join(sections)}
    </body>
    </html>
    """

    # --- SMTP Email Sending Logic ---
    message = MIMEMultipart("alternative")
    message["Subject"] = f"{len(new_jobs)} DevBrada Job(s) & {len(reddit_jobs)} Reddit Gig(s)"
    message["From"] = EMAIL_SENDER
    message["To"] = EMAIL_RECEIVER

    # Attach HTML content
    message.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(
                EMAIL_SENDER, EMAIL_RECEIVER, message.as_string()
            )
        print(f"Email sent successfully to {EMAIL_RECEIVER}!")
    except Exception as e:
        print(f"Error sending email: {e}")

def check_for_new_jobs():
    seen_jobs = load_seen_jobs()
    
    # 1. Fetch DevBrada
    jobs = fetch_jobs()
    jobs = filter_jobs(jobs)
    new_jobs = [job for job in jobs if job["href"] not in seen_jobs]
    current_devbrada_hrefs = {job["href"] for job in jobs}

    # 2. Fetch Reddit (passing in the seen_jobs list)
    print("Fetching Reddit gigs...")
    reddit_jobs, current_reddit_urls = get_audio_gigs_from_reddit(seen_jobs)

    # 3. Evaluate and Send Email
    if new_jobs or reddit_jobs:
        print(f"Found {len(new_jobs)} new DevBrada job(s) and {len(reddit_jobs)} Reddit gig(s)!")
        send_email(new_jobs, reddit_jobs)
        
        # Combine both sets of URLs
        combined_urls_to_save = current_devbrada_hrefs.union(current_reddit_urls)
        
        # Save the combined list to seen_jobs.json
        save_seen_jobs(combined_urls_to_save)
        print("Updated seen_jobs.json with the latest URLs.")
    else:
        print("No new jobs or Reddit gigs found today.")

if __name__ == "__main__":
    check_for_new_jobs()