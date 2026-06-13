import os
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# =========================
# CONFIG
# =========================
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

USERS_FILE = "users.json"

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

job_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet9")

# =========================
# FILTER
# =========================
CANADA_KEYWORDS = [
    "canada", "ontario", "toronto", "ottawa", "mississauga", "brampton",
    "hamilton", "vancouver", "surrey", "burnaby", "calgary", "edmonton",
    "winnipeg", "montreal", "quebec", "halifax",
    "remote - canada", "canada remote", "remote canada"
]

def is_canada(location):
    if not location:
        return False

    location = location.lower()
    return any(keyword in location for keyword in CANADA_KEYWORDS)

# =========================
# USERS
# =========================
def load_users():
    with open(USERS_FILE, "r") as file:
        data = json.load(file)

    users = []

    for user in data:
        users.append({
            "email": user["email"].strip().lower(),
            "titles": [
                title.strip().lower()
                for title in user.get("titles", [])
                if title.strip()
            ]
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
# LINKEDIN SCRAPER
# =========================
def fetch_jobs(title):
    params = {
        "keywords": title,
        "location": "Canada",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }

    response = requests.get(
        BASE_URL,
        headers=HEADERS,
        params=params,
        timeout=20
    )

    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.find_all("li")

    jobs = []

    for card in cards:
        link = card.select_one("a.base-card__full-link")
        title_tag = card.select_one("h3.base-search-card__title")
        company_tag = card.select_one("h4.base-search-card__subtitle")
        location_tag = card.select_one("span.job-search-card__location")
        time_tag = card.select_one("time")

        if not link or not title_tag or not company_tag:
            continue

        jobs.append({
            "url": link["href"].split("?")[0],
            "title": title_tag.text.strip().lower(),
            "company": company_tag.text.strip(),
            "location": location_tag.text.strip() if location_tag else "",
            "posted_time": time_tag.get("datetime", "") if time_tag else ""
        })

    return jobs

# =========================
# MAIN PROCESS
# =========================
def process_jobs():
    users = load_users()

    try:
        existing_jobs = set(job_sheet.col_values(1))
    except Exception:
        existing_jobs = set()

    first_run = len(existing_jobs) == 0

    all_titles = set()
    for user in users:
        all_titles.update(user["titles"])

    new_rows = []
    seen_in_current_run = set()

    for search_title in all_titles:
        jobs = fetch_jobs(search_title)

        for job in jobs:
            url = job["url"]

            if url in seen_in_current_run:
                continue

            seen_in_current_run.add(url)

            if url in existing_jobs:
                continue

            if not is_canada(job["location"]):
                continue

            matched_users = []

            for user in users:
                if any(title in job["title"] for title in user["titles"]):
                    matched_users.append(user["email"])

            if not matched_users:
                continue

            status = "baseline" if first_run else "emailed"

            new_rows.append([
                url,
                job["title"],
                job["company"],
                job["location"],
                job["posted_time"],
                ", ".join(matched_users),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status
            ])

            existing_jobs.add(url)

            if first_run:
                continue

            body = f"""
New job posted in Canada

Job Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Posted Time: {job['posted_time']}

Apply here:
{url}
"""

            for email in matched_users:
                send_email("🚨 New LinkedIn Job Alert - Canada", body, email)

    if new_rows:
        job_sheet.append_rows(new_rows)

# =========================
# FLASK ROUTES
# =========================
@app.route("/")
def home():
    return "LinkedIn Job Scraper is running"

@app.route("/run")
def run_jobs():
    process_jobs()
    return "Jobs processed successfully"

# =========================
# LOCAL RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
