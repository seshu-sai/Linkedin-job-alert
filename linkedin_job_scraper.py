import os
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json


app = Flask(__name__)

# =========================
# ENV VARIABLES
# =========================
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

# =========================
# GOOGLE SHEETS SETUP
# =========================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

creds_dict = json.loads(GOOGLE_CREDENTIALS)
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")

# =========================
# USER STORAGE
# =========================
USER_FILE = "users.json"

def load_users():
    try:
        with open(USER_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_user(email, titles):
    users = load_users()
    users.append({
        "email": email,
        "titles": [t.strip().lower() for t in titles.split(",")]
    })
    with open(USER_FILE, "w") as f:
        json.dump(users, f, indent=2)

# =========================
# EMAIL FUNCTION
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
# GOOGLE SHEET HELPERS
# =========================
def job_already_sent(job_url):
    try:
        return job_url in sheet.col_values(1)
    except:
        return False

def mark_job_as_sent(job_url, title, company, location):
    try:
        sheet.append_row([job_url, title, company, location])
    except Exception as e:
        print("Sheet error:", e)

# =========================
# LINKEDIN CONFIG
# =========================
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# CORE LOGIC (FINAL)
# =========================
def process_jobs():
    users = load_users()
    print(f"👥 Users loaded: {len(users)}")

    # 🔥 Broad search once
    query_params = {
        "keywords": "developer OR engineer OR devops OR java OR cloud",
        "location": "Canada",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }

    response = requests.get(BASE_URL, headers=HEADERS, params=query_params)

    if response.status_code != 200:
        print("❌ Failed to fetch jobs")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.find_all("li")

    for card in cards:
        link_tag = card.select_one('[class*="_full-link"]')
        title_tag = card.select_one('[class*="_title"]')
        company_tag = card.select_one('[class*="_subtitle"]')
        location_tag = card.select_one('[class*="_location"]')

        if link_tag and title_tag and company_tag:
            job_url = link_tag['href'].strip().split('?')[0]

            # ❌ Skip duplicates globally
            if job_already_sent(job_url):
                continue

            title = title_tag.get_text(strip=True)
            title_lower = title.lower()
            company = company_tag.get_text(strip=True)
            location = location_tag.get_text(strip=True) if location_tag else "Unknown"

            print(f"\n🔍 Processing job: {title}")

            matched_users = []

            # 🔥 Match users
            for user in users:
                if any(t in title_lower for t in user["titles"]):
                    matched_users.append(user["email"])

            # ❌ No match → skip
            if not matched_users:
                print("❌ No matching users")
                continue

            body = f"{title} at {company} ({location})\n{job_url}"

            # ✅ Send to each matched user (ONLY ONCE PER JOB)
            for email in matched_users:
                send_email("🚨 New Job Alert", body, email)

            print(f"📧 Sent to: {matched_users}")

            # ✅ Mark job as sent AFTER sending
            mark_job_as_sent(job_url, title, company, location)

# =========================
# UI ROUTE
# =========================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        titles = request.form.get("titles")

        save_user(email, titles)
        return "✅ Registered!"

    return render_template_string("""
        <h2>Job Alert Signup</h2>
        <form method="post">
            Email:<br>
            <input type="email" name="email"><br><br>
            Job Titles (comma separated):<br>
            <textarea name="titles"></textarea><br><br>
            <button type="submit">Submit</button>
        </form>
    """)

# =========================
# TRIGGER
# =========================
@app.route("/")
def run_jobs():
    process_jobs()
    return "✅ Jobs processed!"

# =========================
# RUN APP
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
