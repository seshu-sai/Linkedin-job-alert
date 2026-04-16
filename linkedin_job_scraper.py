import os
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import stripe

app = Flask(__name__)

# =========================
# CONFIG
# =========================
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

stripe.api_key = os.getenv("STRIPE_API_KEY")
endpoint_secret = os.getenv("WEBHOOK_KEY")

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# GOOGLE SHEETS SETUP
# =========================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(GOOGLE_CREDENTIALS)
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)

job_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")
user_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet6")

# =========================
# CANADA FILTER
# =========================
CANADA_KEYWORDS = [
    "canada","ontario","toronto","ottawa","mississauga","brampton","hamilton",
    "vancouver","surrey","burnaby","calgary","edmonton","winnipeg",
    "montreal","quebec","halifax","remote - canada","canada remote"
]

def is_canada(location):
    if not location:
        return False
    location = location.lower()
    return any(k in location for k in CANADA_KEYWORDS)

# =========================
# USERS
# =========================
def load_users():
    rows = user_sheet.get_all_values()
    users = []

    for row in rows:
        if len(row) >= 2:
            users.append({
                "email": row[0].strip().lower(),
                "titles": [t.strip().lower() for t in row[1].split(",") if t.strip()]
            })

    return users

# =========================
# EMAIL
# =========================
def send_email(subject, body, to_email):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)

# =========================
# FETCH JOBS
# =========================
def fetch_jobs(title):
    params = {
        "keywords": title,
        "location": "Canada",
        "f_TPR": "r86400",
        "sortBy": "DD"
    }

    res = requests.get(BASE_URL, headers=HEADERS, params=params)

    if res.status_code != 200:
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    cards = soup.find_all("li")

    jobs = []

    for card in cards:
        link = card.select_one("a.base-card__full-link")
        title_tag = card.select_one("h3.base-search-card__title")
        company_tag = card.select_one("h4.base-search-card__subtitle")
        location_tag = card.select_one("span.job-search-card__location")

        if not link or not title_tag or not company_tag:
            continue

        jobs.append({
            "url": link["href"].split("?")[0],
            "title": title_tag.text.strip().lower(),
            "company": company_tag.text.strip(),
            "location": location_tag.text.strip() if location_tag else ""
        })

    return jobs

# =========================
# PROCESS JOBS
# =========================
def process_jobs():
    users = load_users()
    if not users:
        return

    # 🔥 load existing jobs ONCE
    try:
        existing_jobs = set(job_sheet.col_values(1))
    except:
        existing_jobs = set()

    new_rows = []
    seen = set()

    all_titles = set()
    for u in users:
        all_titles.update(u["titles"])

    for search_title in all_titles:
        jobs = fetch_jobs(search_title)

        for job in jobs:
            url = job["url"]

            if url in seen:
                continue
            seen.add(url)

            if url in existing_jobs:
                continue

            if not is_canada(job["location"]):
                continue

            matched_users = []
            for u in users:
                if any(t in job["title"] for t in u["titles"]):
                    matched_users.append(u["email"])

            if not matched_users:
                continue

            body = f"{job['title']} at {job['company']}\n{job['location']}\n{url}"

            for email in matched_users:
                send_email("🚨 Job Alert - Canada", body, email)

            new_rows.append([url, job["title"], job["company"], job["location"]])
            existing_jobs.add(url)

    # 🔥 batch write (fix 429)
    if new_rows:
        job_sheet.append_rows(new_rows)

# =========================
# ROUTE
# =========================
@app.route("/")
def run():
    process_jobs()
    return "jobs processed"

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run()
