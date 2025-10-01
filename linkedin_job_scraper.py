import os
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

app = Flask(__name__)

# -------------------------
# Job Titles
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
    "privileged access management engineer", "sailpoint developer",
    "okta administrator", "access control analyst", "azure iam engineer", "cloud iam analyst"
]

# -------------------------
# Email Config
# -------------------------
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

EMAIL_RECEIVER_DEVOPS = os.getenv("EMAIL_RECEIVER_DEVOPS")
EMAIL_RECEIVER_2 = os.getenv("EMAIL_RECEIVER_2")
EMAIL_RECEIVER_EMC = "Dushyanthgala@gmail.com"
EMAIL_RECEIVER_CYBER = "achyuth2806@gmail.com"

# -------------------------
# Google Sheets Setup
# -------------------------
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

creds_dict = json.loads(GOOGLE_CREDENTIALS)
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")

# -------------------------
# LinkedIn Config
# -------------------------
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -------------------------
# Helpers
# -------------------------
def send_email(subject, body, to_email):
    """Send email via Gmail SMTP"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"📧 Sent email to {to_email}")
    except Exception as e:
        print(f"❌ Email send failed to {to_email}: {e}")

def load_sent_urls():
    """Read sheet only once per run"""
    try:
        urls = sheet.col_values(1)
        return set(urls or [])
    except Exception as e:
        print(f"❌ Error reading sheet: {e}")
        return set()

def append_rows_batch(rows):
    """Batch write new rows"""
    try:
        if rows:
            sheet.append_rows(rows, value_input_option="RAW")
    except Exception as e:
        print(f"❌ Error writing to sheet: {e}")

def extract_country(location):
    location_lower = location.lower()
    if "canada" in location_lower:
        return "Canada"
    if "india" in location_lower:
        return "India"
    return "Other"

# -------------------------
# Core Logic
# -------------------------
def process_jobs(query_params, expected_category, expected_country, title_list, sent_urls, rows_out):
    seen_jobs = set()

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

            if not (link_tag and title_tag and company_tag):
                continue

            job_url = (link_tag["href"] or "").strip().split("?")[0]
            title = title_tag.get_text(strip=True)
            title_lower = title.lower()
            company = company_tag.get_text(strip=True)
            location = location_tag.get_text(strip=True) if location_tag else "Unknown"
            country = extract_country(location)

            dedup_key = f"{title_lower}::{company.lower()}"
            if dedup_key in seen_jobs or job_url in sent_urls:
                continue
            seen_jobs.add(dedup_key)

            if country != expected_country:
                continue
            if not any(t in title_lower for t in title_list):
                continue

            email_body = f"{title} at {company} — {location}\n{job_url}"

            if expected_category == "DevOps":
                send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_DEVOPS)
                send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_2)
                send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_CYBER)  # also to Achyuth

            elif expected_category == "EMC":
                send_email("📡 New EMC/Signal Integrity Job!", email_body, EMAIL_RECEIVER_EMC)

            elif expected_category == "Cybersecurity":
                send_email("🛡️ New Cybersecurity Job!", email_body, EMAIL_RECEIVER_CYBER)

            rows_out.append([job_url, title, company, location, expected_category, country])
            sent_urls.add(job_url)
            print(f"✅ Sent {expected_category} job ({country}): {title}")

def check_new_jobs():
    sent_urls = load_sent_urls()
    rows_out = []

    devops_query = {"keywords": " OR ".join(TARGET_TITLES_DEVOPS), "location": "Canada", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(devops_query, "DevOps", "Canada", TARGET_TITLES_DEVOPS, sent_urls, rows_out)

    emc_query = {"keywords": " OR ".join(TARGET_TITLES_EMC), "location": "India", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(emc_query, "EMC", "India", TARGET_TITLES_EMC, sent_urls, rows_out)

    cyber_query = {"keywords": " OR ".join(TARGET_TITLES_CYBER), "location": "Canada", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(cyber_query, "Cybersecurity", "Canada", TARGET_TITLES_CYBER, sent_urls, rows_out)

    append_rows_batch(rows_out)

# -------------------------
# Flask Endpoint
# -------------------------
@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked and sent job alerts."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
