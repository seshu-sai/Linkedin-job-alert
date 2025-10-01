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
# Email configuration
# -------------------------
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# (Kept for compatibility if you ever want to reuse)
EMAIL_RECEIVER_DEVOPS = os.getenv("EMAIL_RECEIVER_DEVOPS")
EMAIL_RECEIVER_2 = os.getenv("EMAIL_RECEIVER_2")
EMAIL_RECEIVER_BHANU = os.getenv("EMAIL_RECEIVER_BHANU", "thigullaprasad6@gmail.com")
EMAIL_RECEIVER_PRANEETH = os.getenv("EMAIL_RECEIVER_PRANEETH", "pranithduvva@gmail.com")

EMAIL_RECEIVER_EMC = "Dushyanthgala@gmail.com"
EMAIL_RECEIVER_CYBER = "achyuth2806@gmail.com"
EMAIL_RECEIVER_TARUN = "mannemtarun51@gmail.com"
EMAIL_RECEIVER_VARUN = "contact.hemanth550@gmail.com"

# Centralized fanout per category
CATEGORY_RECIPIENTS = {
    # Per request: DevOps → ONLY Tarun & Varun
    "DevOps": [EMAIL_RECEIVER_TARUN, EMAIL_RECEIVER_VARUN],
    "EMC": [EMAIL_RECEIVER_EMC],
    "Cybersecurity": [EMAIL_RECEIVER_CYBER],
}

SUBJECT_MAP = {
    "DevOps": "🚨 New DevOps/SRE Job!",
    "EMC": "📡 New EMC/Signal Integrity Job!",
    "Cybersecurity": "🛡️ New Cybersecurity Job!",
}

# -------------------------
# Google Sheets setup (Sheet2)
# -------------------------
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

sheet = None
if GOOGLE_CREDENTIALS:
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        client = gspread.authorize(CREDS)
        sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")  # Using Sheet2
    except Exception as e:
        print(f"⚠️ Sheets disabled (auth/init failed): {e}")
        sheet = None

# -------------------------
# LinkedIn search config
# -------------------------
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -------------------------
# Helpers
# -------------------------
def send_email(subject, body, to_email):
    if not to_email:
        return
    if not (EMAIL_SENDER and EMAIL_PASSWORD):
        print(f"📭 [DRY-RUN EMAIL] To: {to_email} | {subject}\n{body}\n")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"❌ Email send failed to {to_email}: {e}")

def load_sent_urls():
    """ONE read per run to avoid quota errors."""
    if not sheet:
        return set()
    try:
        urls = sheet.col_values(1)  # Column A
        return set(urls or [])
    except Exception as e:
        print(f"❌ Error reading sheet once: {e}")
        return set()

def append_rows_batch(rows):
    """ONE write per run."""
    if not rows:
        return
    if not sheet:
        for r in rows:
            print(f"📝 [DRY-RUN SHEET] {r}")
        return
    try:
        if hasattr(sheet, "append_rows"):
            sheet.append_rows(rows, value_input_option="RAW")
        else:
            for r in rows:
                sheet.append_row(r, value_input_option="RAW")
    except Exception as e:
        print(f"❌ Error batch appending to sheet: {e}")

def extract_country(location):
    location_lower = (location or "").lower()
    if "canada" in location_lower:
        return "Canada"
    if "india" in location_lower:
        return "India"
    return "Other"

# -------------------------
# Core logic
# -------------------------
def process_jobs(query_params, expected_category, expected_country, title_list, sent_urls, rows_out):
    seen_jobs = set()

    for start in range(0, 100, 25):
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

            job_url = (link_tag.get("href") or "").strip().split("?")[0]
            if not job_url:
                continue

            title = title_tag.get_text(strip=True)
            title_lower = title.lower()
            company = company_tag.get_text(strip=True)
            location = location_tag.get_text(strip=True) if location_tag else "Unknown"
            country = extract_country(location)

            # per-run and historical dedup
            dedup_key = f"{title_lower}::{company.lower()}"
            if dedup_key in seen_jobs or job_url in sent_urls:
                continue
            seen_jobs.add(dedup_key)

            # filters
            if country != expected_country:
                continue
            if not any(t in title_lower for t in title_list):
                continue

            # email fanout (category-based)
            email_body = f"{title} at {company} — {location}\n{job_url}"
            subject = SUBJECT_MAP.get(expected_category, "🔔 New Job!")

            for recipient in CATEGORY_RECIPIENTS.get(expected_category, []):
                send_email(subject, email_body, recipient)

            # queue for single batch write and mark in-memory
            rows_out.append([job_url, title, company, location, expected_category, country])
            sent_urls.add(job_url)
            print(f"✅ Sent {expected_category} job ({country}): {title} | {company}")

def check_new_jobs():
    sent_urls = load_sent_urls()  # ONE read
    rows_to_append = []

    # --- Canada DevOps Jobs ---
    devops_query = {
        "keywords": " OR ".join(TARGET_TITLES_DEVOPS),
        "location": "Canada",
        "f_TPR": "r3600",  # last hour
        "sortBy": "DD"
    }
    process_jobs(devops_query, "DevOps", "Canada", TARGET_TITLES_DEVOPS, sent_urls, rows_to_append)

    # --- India EMC Jobs ---
    emc_query = {
        "keywords": " OR ".join(TARGET_TITLES_EMC),
        "location": "India",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }
    process_jobs(emc_query, "EMC", "India", TARGET_TITLES_EMC, sent_urls, rows_to_append)

    # --- Canada Cybersecurity Jobs ---
    cyber_query = {
        "keywords": " OR ".join(TARGET_TITLES_CYBER),
        "location": "Canada",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }
    process_jobs(cyber_query, "Cybersecurity", "Canada", TARGET_TITLES_CYBER, sent_urls, rows_to_append)

    append_rows_batch(rows_to_append)  # ONE write

# -------------------------
# Flask endpoint
# -------------------------
@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for DevOps (Canada), EMC (India), and Cybersecurity (Canada) jobs."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
