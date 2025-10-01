import os
import requests
from bs4 import BeautifulSoup
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

TARGET_TITLES_SALESFORCE = [
    "salesforce admin", "salesforce administrator",
    "salesforce developer", "salesforce consultant",
    "salesforce engineer", "salesforce architect",
    "salesforce specialist", "salesforce analyst"
]

# -------------------------
# Email configuration (Gmail SMTP)
# -------------------------
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")   # your Gmail
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # app password

def send_email(subject, body, to_email):
    """Send email using Gmail SMTP"""
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())

        print(f"✅ Email sent to {to_email}")

    except Exception as e:
        print(f"❌ Error sending email: {e}")

# -------------------------
# Category Recipients
# -------------------------
CATEGORY_RECIPIENTS = {
    "DevOps": ["mannemtarun51@gmail.com", "contact.hemanth550@gmail.com", "achyuth2806@gmail.com"],
    "EMC": ["Dushyanthgala@gmail.com"],
    "Cybersecurity": ["achyuth2806@gmail.com"],
    "Salesforce": ["chepyalasatvika7@gmail.com"],
}

SUBJECT_MAP = {
    "DevOps": "🚨 New DevOps/SRE Job!",
    "EMC": "📡 New EMC/Signal Integrity Job!",
    "Cybersecurity": "🛡️ New Cybersecurity Job!",
    "Salesforce": "☁️ New Salesforce Job!",
}

# -------------------------
# Google Sheets setup (optional)
# -------------------------
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

sheet = None
if GOOGLE_CREDENTIALS:
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        client = gspread.authorize(CREDS)
        sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")
    except Exception as e:
        print(f"⚠️ Sheets disabled: {e}")
        sheet = None

# -------------------------
# LinkedIn search config
# -------------------------
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -------------------------
# Helpers
# -------------------------
def load_sent_urls():
    if not sheet:
        return set()
    try:
        urls = sheet.col_values(1)  # Column A
        return set(urls or [])
    except Exception as e:
        print(f"❌ Error reading sheet: {e}")
        return set()

def append_rows_batch(rows):
    if not rows:
        return
    if not sheet:
        for r in rows:
            print(f"📝 [NO-SHEET] {r}")
        return
    try:
        sheet.append_rows(rows, value_input_option="RAW")
    except Exception as e:
        print(f"❌ Error appending to sheet: {e}")

def extract_country(location):
    location_lower = (location or "").lower()
    if "canada" in location_lower: return "Canada"
    if "india" in location_lower: return "India"
    if "united states" in location_lower or "usa" in location_lower: return "United States"
    return "Other"

# -------------------------
# Core logic
# -------------------------
def process_jobs(query_params, expected_category, expected_country, title_list, sent_urls, rows_out):
    seen_jobs = set()
    seen_companies = set()

    for start in range(0, 50, 25):  # limit for speed
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
            if dedup_key in seen_jobs or job_url in sent_urls:
                continue

            if company.lower() in seen_companies:
                continue
            seen_companies.add(company.lower())
            seen_jobs.add(dedup_key)

            if country != expected_country:
                continue
            if not any(t in title.lower() for t in title_list):
                continue

            email_body = f"{title} at {company} — {location}\n{job_url}"
            subject = SUBJECT_MAP.get(expected_category, "🔔 New Job!")

            for recipient in CATEGORY_RECIPIENTS.get(expected_category, []):
                send_email(subject, email_body, recipient)

            rows_out.append([job_url, title, company, location, expected_category, country])
            sent_urls.add(job_url)
            print(f"✅ Sent {expected_category} job ({country}): {title} | {company}")

def check_new_jobs():
    sent_urls = load_sent_urls()
    rows_to_append = []

    devops_query = {"keywords": " OR ".join(TARGET_TITLES_DEVOPS), "location": "Canada", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(devops_query, "DevOps", "Canada", TARGET_TITLES_DEVOPS, sent_urls, rows_to_append)

    emc_query = {"keywords": " OR ".join(TARGET_TITLES_EMC), "location": "India", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(emc_query, "EMC", "India", TARGET_TITLES_EMC, sent_urls, rows_to_append)

    cyber_query = {"keywords": " OR ".join(TARGET_TITLES_CYBER), "location": "Canada", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(cyber_query, "Cybersecurity", "Canada", TARGET_TITLES_CYBER, sent_urls, rows_to_append)

    salesforce_query = {"keywords": " OR ".join(TARGET_TITLES_SALESFORCE), "location": "United States", "f_TPR": "r3600", "sortBy": "DD"}
    process_jobs(salesforce_query, "Salesforce", "United States", TARGET_TITLES_SALESFORCE, sent_urls, rows_to_append)

    append_rows_batch(rows_to_append)

# -------------------------
# Flask endpoints
# -------------------------
@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked and sent job alerts via Gmail SMTP."

@app.route("/test-email")
def test_email():
    send_email("Test Email from JobTracker", "This is a test email body", "your_email@gmail.com")
    return "✅ Test email triggered"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
