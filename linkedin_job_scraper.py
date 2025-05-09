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

# Resume-based keyword filters
KEYWORDS = [
    "java", "spring boot", "spring cloud", "microservices", "rest", "graphql",
    "jwt", "oauth2", "spring security", "angular", "react", "javascript", "html", "css",
    "kafka", "redis", "docker", "kubernetes", "aws", "azure", "gcp", "ec2", "lambda", "s3",
    "jenkins", "github actions", "mysql", "postgresql", "mongodb", "jpa", "hibernate",
    "ci/cd", "prometheus", "elk", "saml", "soap", "junit", "mockito", "jira", "eureka",
    "openfeign", "apache camel", "spring cloud stream"
]

# Load email credentials from Railway env variables
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# Load Google Sheets credentials from env variable (minified JSON string)
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

creds_dict = json.load(StringIO(GOOGLE_CREDENTIALS))
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").sheet1  # Adjust sheet name if needed

# LinkedIn job scraping setup
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
QUERY_PARAMS = {
    "keywords": "java developer OR java full stack developer",
    "location": "Ontario, Canada",
    "f_TPR": "r86400",  # last 24 hours
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
        print(f"❌ Error checking Google Sheet: {e}")
        return False

def mark_job_as_sent(job_url):
    try:
        sheet.append_row([job_url])
    except Exception as e:
        print(f"❌ Error writing to Google Sheet: {e}")

def check_new_jobs():
    new_jobs = []

    for start in range(0, 100, 25):  # pagination
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
            time_tag = card.select_one('[class*="listdate"]')
            title_tag = card.select_one('[class*="_title"]')
            company_tag = card.select_one('[class*="_subtitle"]')
            location_tag = card.select_one('[class*="_location"]')

            if link_tag:
                job_url = link_tag['href'].strip()
                title = title_tag.get_text(strip=True).lower() if title_tag else ""
                company = company_tag.get_text(strip=True).lower() if company_tag else ""
                location = location_tag.get_text(strip=True) if location_tag else "Unknown"
                post_time = time_tag.get_text(strip=True) if time_tag else "Posted Recently"

                full_text = f"{title} {company}"

                if not job_already_sent(job_url):
                    if any(keyword in full_text for keyword in KEYWORDS):
                        mark_job_as_sent(job_url)
                        job_details = (
                            f"{post_time} ➜ {title_tag.get_text(strip=True)} "
                            f"at {company_tag.get_text(strip=True)} — {location}\n{job_url}\n"
                        )
                        new_jobs.append(job_details)

    if new_jobs:
        message = "\n\n".join(new_jobs)
        send_email("🚨 New LinkedIn Java Jobs Matched!", message)
        print("✅ Email sent with filtered jobs.")
    else:
        print("ℹ️ No matching new jobs found.")

@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Job check done."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
