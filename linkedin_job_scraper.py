import os
import requests
from bs4 import BeautifulSoup
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import base64

app = Flask(__name__)

# -------------------------
# Target job titles
# -------------------------
TARGET_TITLES_DEVOPS = [
    "devops engineer", "site reliability engineer", "sre", "cloud engineer",
    "aws devops engineer", "azure devops engineer", "platform engineer",
    "infrastructure engineer", "cloud operations engineer", "reliability engineer",
    "automation engineer", "cloud consultant", "build engineer", "cicd engineer",
    "systems reliability engineer", "observability engineer", "kubernetes engineer",
    "devsecops engineer", "infrastructure developer", "platform reliability engineer",
    "automation specialist"
]

TARGET_TITLES_EMC = [
    "emc", "signal integrity", "emi/emc", "conducted emission", "radiated emission",
    "pcb level emi/emc", "antenna simulations", "electromagnetics",
    "electromagnetic simulations", "interference"
]

TARGET_TITLES_CYBER = [
    "cybersecurity analyst", "soc analyst", "incident response analyst", "threat detection analyst",
    "siem analyst", "splunk analyst", "qradar analyst", "sentinel analyst", "sr. cybersecurity analyst",
    "security monitoring analyst", "information security analyst", "edr analyst", "cloud security analyst",
    "azure security analyst", "aws security analyst", "iam analyst", "iam engineer",
    "identity & access specialist", "identity governance analyst",
    "privileged access management engineer", "sailpoint developer", "okta administrator",
    "access control analyst", "azure iam engineer", "cloud iam analyst"
]

# -------------------------
# Email config (Gmail API)
# -------------------------
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")  # service account JSON string
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
GMAIL_SENDER = os.getenv("GMAIL_SENDER", "seshusai71@gmail.com")  # 👈 set in Railway variables

# -------------------------
# Recipients per category
# -------------------------
CATEGORY_RECIPIENTS = {
    "DevOps": ["mannemtarun51@gmail.com", "contact.hemanth550@gmail.com"],
    "EMC": ["Dushyanthgala@gmail.com"],
    "Cybersecurity": ["achyuth2806@gmail.com"],
}

SUBJECT_MAP = {
    "DevOps": "🚨 New DevOps/SRE Job!",
    "EMC": "📡 New EMC/Signal Integrity Job!",
    "Cybersecurity": "🛡️ New Cybersecurity Job!",
}

# -------------------------
# Gmail API Helper
# -------------------------
def get_gmail_service():
    if not GOOGLE_CREDENTIALS:
        raise Exception("Missing GOOGLE_CREDENTIALS env var")
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    delegated_creds = creds.with_subject(GMAIL_SENDER)
    return build("gmail", "v1", credentials=delegated_creds)

def send_email(subject, body, to_email):
    try:
        service = get_gmail_service()
        message = MIMEText(body)
        message["to"] = to_email
        message["from"] = GMAIL_SENDER
        message["subject"] = subject

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw_message}).execute()
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Gmail API send failed to {to_email}: {e}")

# -------------------------
# Google Sheets setup (optional)
# -------------------------
GOOGLE_SHEETS_CREDS = os.getenv("GOOGLE_SHEETS_CREDS")
SCOPE_SHEETS = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

sheet = None
if GOOGLE_SHEETS_CREDS:
    try:
        creds_dict = json.loads(GOOGLE_SHEETS_CREDS)
        CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE_SHEETS)
        client = gspread.authorize(CREDS)
        sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")
    except Exception as e:
        print(f"⚠️ Sheets disabled: {e}")
        sheet = None

# -------------------------
# LinkedIn Search
# -------------------------
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def extract_country(location):
    location_lower = (location or "").lower()
    if "canada" in location_lower: return "Canada"
    if "india" in location_lower: return "India"
    if "united states" in location_lower or "usa" in location_lower: return "United States"
    return "Other"

# -------------------------
# Core Logic
# -------------------------
def process_jobs(query_params, expected_category, expected_country, title_list):
    seen_jobs = set()
    for start in range(0, 50, 25):
        params = dict(query_params, start=start)
        try:
            response = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=20)
        except Exception as e:
            print(f"❌ Request error: {e}")
            break
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
            if not (link_tag and title_tag and company_tag):
                continue
            job_url = (link_tag.get("href") or "").split("?")[0]
            title = title_tag.get_text(strip=True)
            company = company_tag.get_text(strip=True)
            location = location_tag.get_text(strip=True) if location_tag else "Unknown"
            country = extract_country(location)
            dedup_key = f"{title.lower()}::{company.lower()}"
            if dedup_key in seen_jobs:
                continue
            seen_jobs.add(dedup_key)
            if country != expected_country:
                continue
            if not any(t in title.lower() for t in title_list):
                continue
            email_body = f"{title} at {company} — {location}\n{job_url}"
            subject = SUBJECT_MAP.get(expected_category, "🔔 New Job!")
            for recipient in CATEGORY_RECIPIENTS.get(expected_category, []):
                send_email(subject, email_body, recipient)
            print(f"✅ Sent {expected_category} job ({country}): {title} | {company}")

def check_new_jobs():
    devops_query = {"keywords": " OR ".join(TARGET_TITLES_DEVOPS), "location": "Canada", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(devops_query, "DevOps", "Canada", TARGET_TITLES_DEVOPS)

    emc_query = {"keywords": " OR ".join(TARGET_TITLES_EMC), "location": "India", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(emc_query, "EMC", "India", TARGET_TITLES_EMC)

    cyber_query = {"keywords": " OR ".join(TARGET_TITLES_CYBER), "location": "Canada", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(cyber_query, "Cybersecurity", "Canada", TARGET_TITLES_CYBER)

# -------------------------
# Flask Endpoints
# -------------------------
@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for jobs and sent alerts via Gmail API."

@app.route("/test-email")
def test_email():
    send_email("Test Gmail API Email", "This is a test email body", "your_gmail@gmail.com")
    return "✅ Test Gmail API email sent"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
