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
from datetime import datetime

app = Flask(__name__)

# Resume-based skill filters
KEYWORDS = [
    "java", "spring boot", "spring cloud", "microservices", "rest", "graphql",
    "jwt", "oauth2", "spring security", "angular", "react", "javascript", "html", "css",
    "kafka", "redis", "docker", "kubernetes", "aws", "azure", "gcp", "ec2", "lambda", "s3",
    "jenkins", "github actions", "mysql", "postgresql", "mongodb", "jpa", "hibernate",
    "ci/cd", "prometheus", "elk", "saml", "soap", "junit", "mockito", "jira", "eureka",
    "openfeign", "apache camel", "spring cloud stream"
]

# Email configuration
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# Google Sheets configuration
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.load(StringIO(GOOGLE_CREDENTIALS))
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").sheet1  # Use for tracking sent jobs

# LinkedIn job scraping setup (past 1 hour only)
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
QUERY_PARAMS = {
    "keywords": "java developer OR java full stack developer",
    "location": "Ontario, Canada",
    "f_TPR": "r3600",  # jobs posted in last 1 hour
    "sortBy": "DD"
}

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
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
    now = datetime.now()

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
                company = company_tag.get_text(strip=True)
                location = location_tag.get_text(strip=True) if location_tag else "Unknown"

                combined_text = f"{title.lower()} {company.lower()}"
                if not job_already_sent(job_url) and any(keyword in combined_text for keyword in KEYWORDS):
                    # Send immediately
                    email_body = f"{title} at {company} — {location}\n{job_url}"
                    send_email("🚨 New Matching LinkedIn Job!", email_body)
                    print("✅ Sent:", title)
                    mark_job_as_sent(job_url)

@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for new jobs."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
