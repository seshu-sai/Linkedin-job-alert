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
sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")  # Using Sheet2

# LinkedIn search config
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

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

def process_jobs(query_params, expected_category, expected_country):
    seen_jobs = set()  # Track duplicates using title+company key

    for start in range(0, 100, 25):
        query_params["start"] = start
        response = requests.get(BASE_URL, headers=HEADERS, params=query_params)
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
                dedup_key = f"{title_lower}::{company.lower()}"

                if dedup_key in seen_jobs or job_already_sent(job_url):
                    continue
                seen_jobs.add(dedup_key)

                email_body = f"{title} at {company} — {location}\n{job_url}"

                # DevOps (Canada only)
                if expected_category == "DevOps" and any(t in title_lower for t in TARGET_TITLES_DEVOPS) and country == expected_country:
                    send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_DEVOPS)
                    send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_2)
                    mark_job_as_sent(job_url, title, company, location, "DevOps", country)
                    print("✅ Sent DevOps job (Canada):", title)

                # EMC (India only)
                elif expected_category == "EMC" and any(t in title_lower for t in TARGET_TITLES_EMC) and country == expected_country:
                    send_email("📡 New EMC/Signal Integrity Job!", email_body, EMAIL_RECEIVER_EMC)
                    mark_job_as_sent(job_url, title, company, location, "EMC", country)
                    print("✅ Sent EMC job (India):", title)

def check_new_jobs():
    # --- Canada DevOps Jobs ---
    devops_query = {
        "keywords": " OR ".join(TARGET_TITLES_DEVOPS),
        "location": "Canada",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }
    process_jobs(devops_query, "DevOps", "Canada")

    # --- India EMC Jobs ---
    emc_query = {
        "keywords": " OR ".join(TARGET_TITLES_EMC),
        "location": "India",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }
    process_jobs(emc_query, "EMC", "India")

@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for DevOps (Canada) and EMC (India) jobs."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
