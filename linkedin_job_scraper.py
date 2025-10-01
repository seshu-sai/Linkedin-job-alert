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

# -------------------------
# Job Titles
# -------------------------
TARGET_TITLES_DEVOPS = [...]
TARGET_TITLES_EMC = [...]
TARGET_TITLES_CYBER = [...]

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
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)

def load_sent_urls():
    try:
        urls = sheet.col_values(1)
        return set(urls or [])
    except Exception as e:
        print(f"❌ Error reading sheet: {e}")
        return set()

def append_rows_batch(rows):
    try:
        if rows:
            sheet.append_rows(rows, value_input_option="RAW")
    except Exception as e:
        print(f"❌ Error writing to sheet: {e}")

def extract_country(location):
    location_lower = location.lower()
    if "canada" in location_lower: return "Canada"
    if "india" in location_lower: return "India"
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
            company = company_tag.get_text(strip=True)
            location = location_tag.get_text(strip=True) if location_tag else "Unknown"
            country = extract_country(location)

            dedup_key = f"{title.lower()}::{company.lower()}"
            if dedup_key in seen_jobs or job_url in sent_urls:
                continue
            seen_jobs.add(dedup_key)

            if country != expected_country: continue
            if not any(t in title.lower() for t in title_list): continue

            email_body = f"{title} at {company} — {location}\n{job_url}"

            if expected_category == "DevOps":
                send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_DEVOPS)
                send_email("🚨 New DevOps/SRE Job!", email_body, EMAIL_RECEIVER_2)
            elif expected_category == "EMC":
                send_email("📡 New EMC/Signal Integrity Job!", email_body, EMAIL_RECEIVER_EMC)
            elif expected_category == "Cybersecurity":
                send_email("🛡️ New Cybersecurity Job!", e_
