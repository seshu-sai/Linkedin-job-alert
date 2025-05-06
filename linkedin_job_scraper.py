import requests
from bs4 import BeautifulSoup
from flask import Flask
import smtplib
from email.mime.text import MIMEText
import os

app = Flask(__name__)

EMAIL_SENDER = "seshusai71@gmail.com"
EMAIL_PASSWORD = "ahhk xnob ksho nrbn"  
EMAIL_RECEIVER = "sheshasai263@gmail.com"
SEEN_FILE = "seen_jobs.txt"

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}
QUERY_PARAMS = {
    "keywords": "java developer OR java full stack developer",
    "location": "Ontario, Canada",
    "f_TPR": "r86400",
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


def check_new_jobs():
    if not os.path.exists(SEEN_FILE):
        open(SEEN_FILE, 'w').close()

    with open(SEEN_FILE, 'r') as f:
        seen = set(f.read().splitlines())

    new_jobs = []

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
            time_tag = card.select_one('[class*="listdate"]')
            title = card.select_one('[class*="_title"]')
            company = card.select_one('[class*="_subtitle"]')
            location = card.select_one('[class*="_location"]')

            if link_tag and time_tag:
                job_url = link_tag['href'].strip()
                post_time = time_tag.get_text(strip=True)

                if "hour" in post_time or "Just now" in post_time:
                    if job_url not in seen:
                        seen.add(job_url)
                        with open(SEEN_FILE, 'a') as f:
                            f.write(job_url + "\n")
                        job_details = f"{post_time} ➜ {title.get_text(strip=True)} at {company.get_text(strip=True)} — {location.get_text(strip=True)}\n{job_url}\n"
                        new_jobs.append(job_details)

    if new_jobs:
        message = "\n\n".join(new_jobs)
        send_email("🚨 New LinkedIn Java Jobs (Ontario)", message)
        print("✅ Email sent.")


@app.route("/")
def ping():
    check_new_jobs()
    return "✅ Job check done."


# Keep Flask server running
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
