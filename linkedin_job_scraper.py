import os
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from flask import Flask
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Initialize Flask app
app = Flask(__name__)

# Email configuration (set these in Railway environment variables)
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# Google Sheets API setup
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").sheet1  # Make sure this matches your sheet name

# LinkedIn scraping configuration
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
QUERY_PARAMS = {
    "keywords": "java developer OR java full stack developer",
    "location": "Ontario, Canada",
    "f_TPR": "r86400",  # jobs posted in the last 24 hours
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
        existing_urls = sheet.col_values(1)  # check column A
        return job_url in existing_urls
    except Exception as e:
        print(f"Google Sheets check error: {e}")
        return False

def mark_job_as_sent(job_url):
    try:
        sheet.append_row([job_url])
    except Exception as e:
        print(f"Google Sheets write error: {e}")

def check_new_jobs():
    new_jobs = []

    for start in range(0, 100, 25):  # paginate
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
            title = card.select_one('[class*="_title"]')
            company = card.select_one('[class*="_subtitle"]')
            location = card.select_one('[class*="_location"]')

            if link_tag and time_tag:
                job_url = link_tag['href'].strip()
                post_time = time_tag.get_text(strip=True)

                if "hour" in post_time or "Just now" in post_time:
                    if not job_already_sent(job_url):
                        mark_job_as_sent(job_url)
                        job_details = f"{post_time} ➜ {title.get_text(strip=True)} at {company.get_text(strip=True)} — {location.get_text(strip=True)}\n{job_url}\n"
                        new_jobs.append(job_details)

    if new_jobs:
        message = "\n\n".join(new_jobs)
        send_email("🚨 New LinkedIn Java Jobs (Ontario)", message)
        print("✅ Email sent.")
    else:
        print("ℹ️ No new jobs found.")

@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Job check done."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
