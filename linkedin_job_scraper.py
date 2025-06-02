import os
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from io import StringIO

app = Flask(__name__)

# DevOps job titles
TARGET_TITLES_DEVOPS = [
    "devops engineer", "site reliability engineer", "sre", "cloud engineer",
    "aws devops engineer", "azure devops engineer", "platform engineer",
    "infrastructure engineer", "cloud operations engineer", "reliability engineer",
    "automation engineer", "cloud consultant", "build engineer", "cicd engineer",
    "systems reliability engineer", "observability engineer", "kubernetes engineer",
    "devsecops engineer", "infrastructure developer", "platform reliability engineer",
    "automation specialist"
]

# EMC/Signal Integrity job titles
TARGET_TITLES_EMC = [
    "emc", "signal integrity", "emi/emc", "conducted emission", "radiated emission",
    "pcb level emi/emc", "antenna simulations", "electromagnetics",
    "electromagnetic simulations", "interference"
]

# Email configuration
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER_DEVOPS = os.getenv("EMAIL_RECEIVER_DEVOPS")
EMAIL_RECEIVER_2 = os.getenv("EMAIL_RECEIVER_2")
EMAIL_RECEIVER_EMC = "Dushanthgala@gmail.com"

# Google Sheets setup (Sheet2 used here)
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.load(StringIO(GOOGLE_CREDENTIALS))
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")  # ← use Sheet2

# LinkedIn search config
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
QUERY_PARAMS = {
    "keywords": (
        "devops engineer OR sre OR site reliability engineer OR cloud engineer OR "
        "aws devops engineer OR azure devops engineer OR platform engineer OR "
        "infrastructure engineer OR cloud operations engineer OR reliability engineer OR "
        "automation engineer OR cloud consultant OR build engineer OR cicd engineer OR "
        "systems reliability engineer OR observability engineer OR kubernetes engineer OR "
        "devsecops engineer OR infrastructure developer OR platform reliability engineer OR "
        "automation specialist OR emc OR emi/emc OR signal integrity OR conducted emission OR "
        "radiated emission OR pcb level emi/emc OR antenna simulations OR electromagnetics OR "
        "electromagnetic simulations OR interference"
    ),
    "location": "Worldwide",
    "f_TPR": "r3600",  # Posted in last 1 hour
    "sortBy": "DD"
}

def send_email(subject, body, to_email):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)

def job_already_sent(job_url):
    try:
        existing_urls = sheet.col_values(1)
        return job_url in existing_urls
    except Exception as e:
        print(f"❌ Error reading sheet: {e}")
        return False

def mark_job_as_sent(job_url, title, company, location, category, country):
    try:
        sheet.append_row([job_url, title, company, location, category, country])
    except Exception as e:
        print(f"❌ Error writing to sheet: {e}")

def extract_country(location):
    location_lower = location.lower()
    if "canada" in location_lower:
        return "Canada"
    elif "india" in location_lower:
        return "India"
    else:
        return "Other"

def check_new_jobs():
    for start in range(0, 100, 25):
        QUERY_PARAMS["start"] = start
        response = requests.get(BASE_URL, headers=HEADERS, params=QUERY_PARAMS)
        if response.status_code != 200 or not response.text.strip():
            break

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.find_all("li")
        if not cards:
            break

        for card in cards:
            link_tag = card.select_one('[class*="_full-link"]')
            title_tag = card.select_one('[class*="_title"]')
            company_tag = card.select_one('[class*="_subtitle"]')
            location_tag = card.select_one('[class*="_location"]')

            if link_tag and title_tag and company_tag:
                job_url = link_tag['href'].strip().split('?')[0]
                title = title_tag.get_text(strip=True)
                title_lower = title.lower()
                company = company_tag.get_text(strip=True)
                location = location_tag.get_text(strip=True) if location_tag else "Unknown"
                country = extract_country(location)

                if job_already_sent(job_url):
                    continue

                email_body = f"{title} at {company} — {location}\n{job_url}"

                # DevOps Job
                if any(t in title_lower for t in TARGET_TITLES_DEVOPS):
                    send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_DEVOPS)
                    send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_2)
                    mark_job_as_sent(job_url, title, company, location, "DevOps", country)
                    print("✅ Sent DevOps job:", title)

                # EMC Job
                elif any(t in title_lower for t in TARGET_TITLES_EMC):
                    send_email("📡 New EMC/Signal Integrity Job!", email_body, EMAIL_RECEIVER_EMC)
                    mark_job_as_sent(job_url, title, company, location, "EMC", country)
                    print("✅ Sent EMC job:", title)

@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for DevOps and EMC jobs."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
