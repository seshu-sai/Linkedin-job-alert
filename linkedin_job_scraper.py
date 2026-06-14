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

# =========================
# GOOGLE SHEETS
# =========================
def get_google_sheet():
    if not GOOGLE_CREDENTIALS:
        raise Exception("GOOGLE_CREDENTIALS env variable is missing")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open(SPREADSHEET_NAME)

    try:
        sheet = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(
            title=WORKSHEET_NAME,
            rows=5000,
            cols=10
        )

    return sheet


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

    existing_headers = sheet.row_values(1)

    if existing_headers != headers:
        sheet.clear()
        sheet.append_row(headers, value_input_option="USER_ENTERED")


def load_existing_job_ids(sheet):
    values = sheet.col_values(1)

    return set(
        value.strip()
        for value in values[1:]
        if value.strip()
    )


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

        clean_titles = [
            title.strip().lower()
            for title in titles
            if title.strip()
        ]

        if email and clean_titles:
            users.append({
                "email": email,
                "titles": clean_titles
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
    return any(keyword in location for keyword in CANADA_KEYWORDS)


# =========================
# EMAIL
# =========================
def send_email(subject, body, to_email):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("Email credentials missing")
        return False

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
            except Exception as e:
                print(f"SMTP quit ignored: {e}")


# =========================
# LINKEDIN SCRAPER
# =========================
def fetch_jobs(search_title):
    params = {
        "keywords": search_title,
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
        job_id = get_job_id(url)

        jobs.append({
            "job_id": job_id,
            "url": url,
            "title": title_tag.text.strip().lower(),
            "company": company_tag.text.strip(),
            "location": location_tag.text.strip() if location_tag else "",
            "posted_time": time_tag.get("datetime", "") if time_tag else "",
            "matched_search_title": search_title
        })

    return jobs


# =========================
# MAIN PROCESS
# =========================
def process_jobs():
    print("Starting LinkedIn job process...")

    sheet = get_google_sheet()
    ensure_headers(sheet)

    users = load_users()
    print(f"Users loaded: {len(users)}")

    existing_job_ids = load_existing_job_ids(sheet)
    print(f"Existing jobs in Sheet9: {len(existing_job_ids)}")

    first_run = len(existing_job_ids) == 0
    print(f"First run: {first_run}")

    all_titles = set()

    for user in users:
        all_titles.update(user["titles"])

    new_rows = []
    pending_emails = []
    seen_this_run = set()

    for search_title in all_titles:
        jobs = fetch_jobs(search_title)
        print(f"{search_title}: fetched {len(jobs)} jobs")

        for job in jobs:
            job_id = job["job_id"]

            if job_id in seen_this_run:
                continue

            seen_this_run.add(job_id)

            if job_id in existing_job_ids:
                print(f"Skipped duplicate job: {job_id}")
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

            status = "baseline" if first_run else "pending_email"

            row = [
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
            ]

            new_rows.append(row)
            existing_job_ids.add(job_id)

            print(f"Prepared row for Sheet9: {job['title']} | {job['company']}")

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
        print(f"Saved {len(new_rows)} rows to Sheet9 successfully")
    except Exception as e:
        print(f"Failed to save rows to Sheet9. Emails will NOT be sent. Error: {e}")
        return

    if first_run:
        print("First run completed. Jobs saved as baseline. No emails sent.")
        return

    sent_count = 0

    for item in pending_emails:
        sent = send_email(
            "🚨 New LinkedIn Job Alert - Canada",
            item["body"],
            item["email"]
        )

        if sent:
            sent_count += 1

    print(f"Emails sent after Sheet9 save: {sent_count}")


# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return "LinkedIn Job Scraper is running", 200


@app.route("/run", methods=["GET", "POST"])
def run_jobs():
    try:
        process_jobs()
        return "Jobs processed successfully. Check Render logs.", 200
    except Exception as e:
        print(f"Run failed: {e}")
        return f"Run failed: {e}", 500


@app.route("/test-sheet")
def test_sheet():
    try:
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

    except Exception as e:
        print(f"Sheet test failed: {e}")
        return f"Sheet test failed: {e}", 500


# =========================
# LOCAL RUN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
