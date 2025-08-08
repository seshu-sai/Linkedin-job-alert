import os
import smtplib
import time
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from flask import Flask
import json

# Optional deps (Google Sheets). Guard usage so script still runs without them.
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except Exception:
    gspread = None
    ServiceAccountCredentials = None

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
    "azure security analyst", "aws security analyst", "iam analyst", "iam engineer", "identity & access",
    "identity governance", "privileged access", "sailpoint", "okta", "access control"
]

# -------------------------
# Email configuration
# -------------------------
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER_DEVOPS = os.getenv("EMAIL_RECEIVER_DEVOPS")  # optional
EMAIL_RECEIVER_2 = os.getenv("EMAIL_RECEIVER_2")            # optional
EMAIL_RECEIVER_BHANU = "thigullaprasad6@gmail.com"
EMAIL_RECEIVER_EMC = "Dushyanthgala@gmail.com"
EMAIL_RECEIVER_CYBER = "achyuth2806@gmail.com"

EMAIL_SENDING_ENABLED = bool(EMAIL_SENDER and EMAIL_PASSWORD)

# -------------------------
# Google Sheets setup
# -------------------------
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

SHEETS_ENABLED = False
sheet = None
if GOOGLE_CREDENTIALS and gspread and ServiceAccountCredentials:
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        client = gspread.authorize(CREDS)
        sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")  # Sheet2
        SHEETS_ENABLED = True
    except Exception as e:
        print(f"⚠️ Sheets disabled (auth/init failed): {e}")

# -------------------------
# LinkedIn scraping config
# -------------------------
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}
SESSION = requests.Session()

# -------------------------
# Helpers
# -------------------------
def safe_send_email(subject: str, body: str, to_email: str):
    if not to_email:
        return
    if not EMAIL_SENDING_ENABLED:
        print(f"📭 [DRY-RUN EMAIL] To: {to_email} | {subject}\n{body}\n")
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = to_email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"❌ Email send failed to {to_email}: {e}")

def job_already_sent(job_url: str) -> bool:
    if not SHEETS_ENABLED:
        return False
    try:
        existing_urls = sheet.col_values(1)  # column A holds URLs
        return job_url in existing_urls
    except Exception as e:
        print(f"❌ Error reading sheet: {e}")
        return False

def mark_job_as_sent(job_url, title, company, location, category, country):
    if not SHEETS_ENABLED:
        print(f"📝 [DRY-RUN SHEET] {category} | {title} | {company} | {location} | {country} | {job_url}")
        return
    try:
        sheet.append_row([job_url, title, company, location, category, country])
    except Exception as e:
        print(f"❌ Error writing to sheet: {e}")

def extract_country(location: str) -> str:
    loc = (location or "").lower()
    if "canada" in loc:
        return "Canada"
    if "india" in loc:
        return "India"
    return "Other"

def fetch_with_retry(params, retries=3, backoff=1.5):
    last_exc = None
    for i in range(retries):
        try:
            resp = SESSION.get(BASE_URL, headers=HEADERS, params=params, timeout=20)
            if resp.status_code == 200 and resp.text.strip():
                return resp
        except Exception as e:
            last_exc = e
        time.sleep(backoff ** i)
    if last_exc:
        print(f"❌ Request failed after retries: {last_exc}")
    return None

def process_jobs(query_params, expected_category, expected_country, title_list):
    seen_jobs = set()

    for start in range(0, 100, 25):
        q = dict(query_params)
        q["start"] = start
        resp = fetch_with_retry(q)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
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

            job_url = link_tag.get("href", "").strip().split("?")[0]
            if not job_url:
                continue

            title = title_tag.get_text(strip=True)
            title_lower = title.lower()
            company = company_tag.get_text(strip=True)
            location = location_tag.get_text(strip=True) if location_tag else "Unknown"
            country = extract_country(location)

            dedup_key = f"{job_url}::{title_lower}::{company.lower()}"
            if dedup_key in seen_jobs or job_already_sent(job_url):
                continue
            seen_jobs.add(dedup_key)

            # Title filter
            if not any(t in title_lower for t in title_list):
                continue

            # Country filter
            if country != expected_country:
                continue

            email_body = f"{title} at {company} — {location}\n{job_url}"

            if expected_category == "DevOps":
                # Send to three recipients
                if EMAIL_RECEIVER_DEVOPS:
                    safe_send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_DEVOPS)
                if EMAIL_RECEIVER_2:
                    safe_send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_2)
                if EMAIL_RECEIVER_BHANU:
                    safe_send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_BHANU)

            elif expected_category == "EMC":
                safe_send_email("📡 New EMC/Signal Integrity Job!", email_body, EMAIL_RECEIVER_EMC)

            elif expected_category == "Cybersecurity":
                safe_send_email("🛡️ New Cybersecurity Job!", email_body, EMAIL_RECEIVER_CYBER)

            mark_job_as_sent(job_url, title, company, location, expected_category, country)
            print(f"✅ Sent {expected_category} job ({country}): {title} | {company}")

# -------------------------
# Main job checks
# -------------------------
def check_new_jobs():
    # --- Canada DevOps Jobs ---
    devops_query = {
        "keywords": " OR ".join(TARGET_TITLES_DEVOPS),
        "location": "Canada",
        "f_TPR": "r3600",  # last hour
        "sortBy": "DD"    # date posted, desc
    }
    process_jobs(devops_query, "DevOps", "Canada", TARGET_TITLES_DEVOPS)

    # --- India EMC Jobs ---
    emc_query = {
        "keywords": " OR ".join(TARGET_TITLES_EMC),
        "location": "India",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }
    process_jobs(emc_query, "EMC", "India", TARGET_TITLES_EMC)

    # --- India Cybersecurity Jobs ---
    cyber_query = {
        "keywords": " OR ".join(TARGET_TITLES_CYBER),
        "location": "India",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }
    process_jobs(cyber_query, "Cybersecurity", "India", TARGET_TITLES_CYBER)

# -------------------------
# Flask endpoint
# -------------------------
@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for DevOps (Canada), EMC (India), and Cybersecurity (India) jobs."

if __name__ == "__main__":
    # Bind to 0.0.0.0 for container platforms; default port 8080
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
