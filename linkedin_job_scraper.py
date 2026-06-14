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
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

USERS_FILE = "users.json"
SPREADSHEET_NAME = "LinkedIn Job Tracker"
WORKSHEET_NAME = "Sheet9"

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

CANADA_KEYWORDS = [
    "canada", "ontario", "toronto", "ottawa", "mississauga", "brampton",
    "hamilton", "vancouver", "surrey", "burnaby", "calgary", "edmonton",
    "winnipeg", "montreal", "quebec", "halifax",
    "remote - canada", "canada remote", "remote canada"
]

scheduler_started = False


# =========================
# GOOGLE SHEET
# =========================
def get_google_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open(SPREADSHEET_NAME)

    try:
        return spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=5000, cols=10)


def ensure_headers(sheet):
    headers = [
        "Job ID",
        "URL",
        "Job Title",
        "Company",
        "Location",
        "Posted Time",
        "Matched Search Title",
        "Sent To",
        "Processed At",
        "Status"
    ]

    if sheet.row_values(1) != headers:
        sheet.clear()
        sheet.append_row(headers, value_input_option="USER_ENTERED")


def load_existing_job_ids(sheet):
    values = sheet.col_values(1)
    return set(v.strip() for v in values[1:] if v.strip())


# =========================
# USERS
# =========================
def load_users():
    with open(USERS_FILE, "r") as file:
        data = json.load(file)

    users = []

    for user in data:
        email = user.get("email", "").strip().lower()
        titles = [
            t.strip().lower()
            for t in user.get("titles", [])
            if t.strip()
        ]

        if email and titles:
            users.append({
                "email": email,
                "titles": titles
            })

    return users


# =========================
# HELPERS
# =========================
def get_job_id(url):
    return url.rstrip("/").split("/")[-1]


def is_canada(location):
    if not location:
        return False

    location = location.lower()
    return any(k in location for k in CANADA_KEYWORDS)


# =========================
# EMAIL
# =========================
def send_email(subject, body, to_email):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email

    server = None

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, [to_email], msg.as_string())
        print(f"Email sent to {to_email}")
        return True

    except Exception as e:
        print(f"Email failed for {to_email}: {e}")
        return False

    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass


# =========================
# LINKEDIN SCRAPER
# =========================
def fetch_jobs(search_title):
    params = {
        "keywords": search_title,
        "location": "Canada",
        "f_TPR": "r600",   # last 10 minutes
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
        print(f"LinkedIn request failed for {search_title}: {e}")
        return []

    if response.status_code != 200:
        print(f"LinkedIn returned {response.status_code} for {search_title}")
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

        url = link["href"].split("?")[0]

        jobs.append({
            "job_id": get_job_id(url),
            "url": url,
            "title": title_tag.text.strip().lower(),
            "company": company_tag.text.strip(),
            "location": location_tag.text.strip() if location_tag else "",
            "posted_time": time_tag.get("datetime", "") if time_tag else "",
            "matched_search_title": search_title
        })

    return jobs


# =========================
# MAIN JOB PROCESS
# =========================
def process_jobs():
    print("Checking LinkedIn jobs...")

    sheet = get_google_sheet()
    ensure_headers(sheet)

    users = load_users()
    existing_job_ids = load_existing_job_ids(sheet)

    first_run = len(existing_job_ids) == 0

    all_titles = set()
    for user in users:
        all_titles.update(user["titles"])

    new_rows = []
    pending_emails = []
    seen_this_run = set()

    for search_title in all_titles:
        jobs = fetch_jobs(search_title)
        print(f"{search_title}: {len(jobs)} jobs found")

        for job in jobs:
            job_id = job["job_id"]

            if job_id in seen_this_run:
                continue

            seen_this_run.add(job_id)

            if job_id in existing_job_ids:
                continue

            if not is_canada(job["location"]):
                continue

            matched_users = []

            for user in users:
                if any(title in job["title"] for title in user["titles"]):
                    matched_users.append(user["email"])

            if not matched_users:
                continue

            status = "baseline" if first_run else "pending_email"

            new_rows.append([
                job["job_id"],
                job["url"],
                job["title"],
                job["company"],
                job["location"],
                job["posted_time"],
                job["matched_search_title"],
                ", ".join(matched_users),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status
            ])

            existing_job_ids.add(job_id)

            if not first_run:
                body = f"""
New job posted in Canada

Job Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Posted Time: {job['posted_time']}

Apply here:
{job['url']}
"""

                for email in matched_users:
                    pending_emails.append({
                        "email": email,
                        "body": body
                    })

    if not new_rows:
        print("No new jobs found")
        return

    try:
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"Saved {len(new_rows)} new jobs to Sheet9")
    except Exception as e:
        print(f"Sheet9 save failed. Emails not sent. Error: {e}")
        return

    if first_run:
        print("Baseline saved. No emails sent on first run.")
        return

    for item in pending_emails:
        send_email(
            "🚨 New LinkedIn Job Alert - Canada",
            item["body"],
            item["email"]
        )


# =========================
# SCHEDULER
# =========================
def start_scheduler():
    global scheduler_started

    if scheduler_started:
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=process_jobs,
        trigger="interval",
        minutes=5,
        id="linkedin_job_checker",
        replace_existing=True
    )
    scheduler.start()

    scheduler_started = True
    print("Scheduler started. Checking jobs every 5 minutes.")


start_scheduler()


# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return "LinkedIn Job Scraper is running. It checks every 5 minutes.", 200


@app.route("/run")
def run_now():
    process_jobs()
    return "Manual job check completed.", 200


@app.route("/test-sheet")
def test_sheet():
    sheet = get_google_sheet()
    ensure_headers(sheet)

    sheet.append_row([
        "TEST123",
        "https://test.com/job/TEST123",
        "test job",
        "test company",
        "Toronto, Ontario, Canada",
        "",
        "data analyst",
        "test@gmail.com",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test"
    ], value_input_option="USER_ENTERED")

    return "Test row inserted into Sheet9", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
