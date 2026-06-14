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

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# =========================
# GOOGLE SHEETS SETUP
# =========================
def get_google_sheet():
    if not GOOGLE_CREDENTIALS:
        raise Exception("GOOGLE_CREDENTIALS environment variable is missing")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open("LinkedIn Job Tracker")

    try:
        sheet = spreadsheet.worksheet("Sheet9")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Sheet9", rows=1000, cols=10)

    return sheet


job_sheet = get_google_sheet()

# =========================
# CANADA FILTER
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
    if not os.path.exists(USERS_FILE):
        raise Exception("users.json file is missing")

    with open(USERS_FILE, "r") as file:
        data = json.load(file)

    users = []

    for user in data:
        email = user.get("email", "").strip().lower()
        titles = user.get("titles", [])

        if not email or not titles:
            continue

        users.append({
            "email": email,
            "titles": [
                title.strip().lower()
                for title in titles
                if title.strip()
            ]
        })

    return users

# =========================
# EMAIL
# =========================
def send_email(subject, body, to_email):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        raise Exception("EMAIL_SENDER or EMAIL_PASSWORD is missing")

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
        "f_TPR": "r3600",
        "sortBy": "DD"
    }

    try:
        response = requests.get(
            BASE_URL,
            headers=HEADERS,
            params=params,
            timeout=20
        )
    except Exception as e:
        print(f"Request failed for {title}: {e}")
        return []

    if response.status_code != 200:
        print(f"LinkedIn returned {response.status_code} for {title}")
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
# PROCESS JOBS
# =========================
def process_jobs():
    print("Starting job process...")

    users = load_users()
    print(f"Users loaded: {len(users)}")

    if not users:
        print("No valid users found")
        return

    try:
        existing_jobs = set(job_sheet.col_values(1))
        print(f"Existing jobs in Sheet9: {len(existing_jobs)}")
    except Exception as e:
        print(f"Failed to read Sheet9: {e}")
        existing_jobs = set()

    # Add headers if sheet is empty
    if len(existing_jobs) == 0:
        headers = [
            "URL",
            "Job Title",
            "Company",
            "Location",
            "Posted Time",
            "Sent To",
            "Processed At",
            "Status"
        ]
        try:
            job_sheet.append_row(headers, value_input_option="USER_ENTERED")
            existing_jobs.add("URL")
            print("Headers added to Sheet9")
        except Exception as e:
            print(f"Failed to add headers: {e}")

    first_run = len(existing_jobs) <= 1
    print(f"First run: {first_run}")

    all_titles = set()

    for user in users:
        all_titles.update(user["titles"])

    print(f"Searching titles: {all_titles}")

    new_rows = []
    seen_in_current_run = set()

    for search_title in all_titles:
        jobs = fetch_jobs(search_title)
        print(f"{search_title}: fetched {len(jobs)} jobs")

        for job in jobs:
            url = job["url"]

            if url in seen_in_current_run:
                continue

            seen_in_current_run.add(url)

            if url in existing_jobs:
                print(f"Skipped duplicate job: {url}")
                continue

            if not is_canada(job["location"]):
                print(f"Skipped non-Canada job: {job['location']}")
                continue

            matched_users = []

            for user in users:
                if any(title in job["title"] for title in user["titles"]):
                    matched_users.append(user["email"])

            if not matched_users:
                print(f"No matched user for job: {job['title']}")
                continue

            status = "baseline" if first_run else "emailed"

            row = [
                url,
                job["title"],
                job["company"],
                job["location"],
                job["posted_time"],
                ", ".join(matched_users),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status
            ]

            new_rows.append(row)
            existing_jobs.add(url)

            print(f"Prepared row: {job['title']} | {job['company']}")

            # First run only stores jobs, no email
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
                try:
                    send_email(
                        "🚨 New LinkedIn Job Alert - Canada",
                        body,
                        email
                    )
                    print(f"Email sent to {email}")
                except Exception as e:
                    print(f"Email failed for {email}: {e}")

    print(f"Rows to save: {len(new_rows)}")

    if new_rows:
        try:
            job_sheet.append_rows(new_rows, value_input_option="USER_ENTERED")
            print("Rows saved to Sheet9 successfully")
        except Exception as e:
            print(f"Failed to save rows to Sheet9: {e}")
    else:
        print("No new jobs to save")

# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return "LinkedIn Job Scraper is running"


@app.route("/run")
def run_jobs():
    try:
        process_jobs()
        return "Jobs processed successfully. Check Render logs."
    except Exception as e:
        print(f"Run failed: {e}")
        return f"Run failed: {e}", 500

# =========================
# LOCAL RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
