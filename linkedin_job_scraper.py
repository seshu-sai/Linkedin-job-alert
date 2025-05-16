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

# Keywords for Java-related roles
KEYWORDS_JAVA = [
    "java", "spring boot", "spring cloud", "microservices", "rest", "graphql",
    "jwt", "oauth2", "spring security", "angular", "react", "javascript", "html", "css",
    "kafka", "redis", "docker", "kubernetes", "aws", "azure", "gcp", "ec2", "lambda", "s3",
    "jenkins", "github actions", "mysql", "postgresql", "mongodb", "jpa", "hibernate",
    "ci/cd", "prometheus", "elk", "saml", "soap", "junit", "mockito", "jira", "eureka",
    "openfeign", "apache camel", "spring cloud stream"
]

# Keywords for DevOps/SRE roles
KEYWORDS_DEVOPS = [
    "devops", "site reliability", "sre", "cloud engineer", "aws devops", "azure devops",
    "platform engineer", "infrastructure engineer", "cloud operations", "reliability engineer",
    "automation engineer", "terraform", "ansible", "jenkins", "docker", "kubernetes",
    "ci/cd", "cloudformation", "eks", "gke", "aks", "prometheus", "grafana", "helm"
]

# Email configuration
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER_JAVA = os.getenv("EMAIL_RECEIVER")
EMAIL_RECEIVER_DEVOPS = os.getenv("EMAIL_RECEIVER_DEVOPS")

# Google Sheets configuration
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.load(StringIO(GOOGLE_CREDENTIALS))
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").sheet1  # For tracking sent jobs

# LinkedIn Job Scraping URL
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
QUERY_PARAMS = {
    "keywords": "java developer OR java full stack developer OR devops OR sre OR cloud engineer",
    "location": "Ontario, Canada",
    "f_TPR": "r3600",  # jobs posted in last 1 hour
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
                company = company_tag.get_text(strip=True)
                location = location_tag.get_text(strip=True) if location_tag else "Unknown"

                if job_already_sent(job_url):
                    continue

                combined_text = f"{title.lower()} {company.lower()}"

                # Match Java roles
                if any(keyword in combined_text for keyword in KEYWORDS_JAVA):
                    email_body = f"{title} at {company} — {location}\n{job_url}"
                    send_email("🚨 New Matching Java Job!", email_body, EMAIL_RECEIVER_JAVA)
                    mark_job_as_sent(job_url)
                    print("✅ Sent Java job:", title)

                # Match DevOps/SRE roles
                elif any(keyword in combined_text for keyword in KEYWORDS_DEVOPS):
                    email_body = f"{title} at {company} — {location}\n{job_url}"
                    send_email("🚨 New Matching DevOps Job!", email_body, EMAIL_RECEIVER_DEVOPS)
                    mark_job_as_sent(job_url)
                    print("✅ Sent DevOps job:", title)

@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Checked for new jobs."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
