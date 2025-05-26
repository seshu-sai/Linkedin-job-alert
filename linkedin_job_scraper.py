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

# DevOps-related job titles to track
TARGET_TITLES = [
    "devops engineer",
    "site reliability engineer",
    "sre",
    "cloud engineer",
    "aws devops engineer",
    "azure devops engineer",
    "platform engineer",
    "infrastructure engineer",
    "cloud operations engineer",
    "reliability engineer",
    "automation engineer"
]

# Email credentials and target recipient
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER_DEVOPS = os.getenv("EMAIL_RECEIVER_DEVOPS")
EMAIL_RECEIVER_2 = os.getenv("EMAIL_RECEIVER_2")

# Google Sheets configuration
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.load(StringIO(GOOGLE_CREDENTIALS))
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").sheet1  # Make sure this sheet exists

# LinkedIn scraping config
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
QUERY_PARAMS = {
    "keywords": "devops engineer OR sre OR cloud engineer OR site reliability engineer",
    "location": "Ontario, Canada",
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

def mark_job_as_sent(job_url):
    try:
        sheet.append_row([job_url])
    except Exception as e:
        print(f"❌ Error writing to sheet: {e}")

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
                title_clean = title.lower().strip()
                company = company_tag.get_text(strip=True)
                location = location_tag.get_text(strip=True) if location_tag else "Unknown"

                if job_already_sent(job_url):
                    continue

                if any(t in title_clean for t in TARGET_TITLES):
                    email_body = f"{title} at {company} — {location}\n{job_url}"
                    send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_DEVOPS)
                    send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_2)
                    mark_job_as_sent(job_url)
                    print("✅ Sent DevOps job:", title)

@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for DevOps/SRE jobs."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
