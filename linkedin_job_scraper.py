import os
import re
import json
import time
import logging
import threading
import smtplib
from typing import Dict, Set, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText


import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, redirect
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import stripe

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ================= CONFIG =================
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

stripe.api_key = os.getenv("STRIPE_API_KEY")
WEBHOOK_KEY = os.getenv("WEBHOOK_KEY")

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

MAX_FETCH_WORKERS = 6
MAX_EMAIL_WORKERS = 10
CHUNK_SIZE = 20

# ================= GOOGLE SHEETS =================
scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]

creds_dict = json.loads(GOOGLE_CREDENTIALS)
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

user_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet6")
job_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")

# ================= HELPERS =================
def normalize(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def send_email(subject, body, to):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)

# ================= NEW ADMIN EMAIL =================
def notify_admin_new_user(email, titles):
    subject = "🆕 New User Registered"
    body = f"""
New user subscribed:

Email: {email}
Titles: {titles}

Time: {time.strftime("%Y-%m-%d %H:%M:%S")}
"""
    send_email(subject, body, "seshusai71@gmail.com")

# ================= USER LOAD =================
def load_users():
    rows = user_sheet.get_all_values()
    users = []
    title_map = {}

    for row in rows:
        if len(row) < 2:
            continue

        email = normalize(row[0])
        titles = [normalize(t) for t in row[1].split(",") if t.strip()]

        users.append({"email": email, "titles": titles})

        for t in titles:
            title_map.setdefault(t, set()).add(email)

    return users, title_map, list(title_map.keys())

# ================= SAVE USER =================
def save_user(email, titles):
    email = normalize(email)
    new_titles = {normalize(t) for t in titles.split(",") if t.strip()}

    rows = user_sheet.get_all_values()

    # existing user
    for idx, row in enumerate(rows, start=1):
        if normalize(row[0]) == email:
            existing = set(row[1].split(",")) if len(row) > 1 else set()
            merged = sorted(existing.union(new_titles))
            user_sheet.update_cell(idx, 2, ",".join(merged))
            return

    # new user
    user_sheet.append_row([email, ",".join(sorted(new_titles))])

    # 🔥 send admin email (async)
    threading.Thread(
        target=notify_admin_new_user,
        args=(email, ",".join(new_titles))
    ).start()

# ================= JOB PROCESS =================
def chunk(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]

def fetch_jobs(titles):
    keywords = " OR ".join([f'"{t}"' for t in titles])

    params = {
        "keywords": keywords,
        "location": "Canada",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }

    try:
        res = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        jobs = []
        for card in soup.find_all("li"):
            link = card.select_one("a")
            title = card.select_one("h3")
            company = card.select_one("h4")

            if link and title and company:
                jobs.append({
                    "url": link["href"].split("?")[0],
                    "title": normalize(title.text),
                    "company": company.text.strip()
                })

        return jobs

    except Exception as e:
        logging.warning(e)
        return []

def process_jobs():
    users, title_map, all_titles = load_users()
    sent = set(job_sheet.col_values(1))

    jobs = []

    # parallel fetch
    with ThreadPoolExecutor(MAX_FETCH_WORKERS) as ex:
        futures = [ex.submit(fetch_jobs, c) for c in chunk(all_titles, CHUNK_SIZE)]
        for f in as_completed(futures):
            jobs.extend(f.result())

    unique = {j["url"]: j for j in jobs}

    new_rows = []
    email_tasks = []

    with ThreadPoolExecutor(MAX_EMAIL_WORKERS) as ex:
        for job in unique.values():
            if job["url"] in sent:
                continue

            matched = set()
            for t, emails in title_map.items():
                if t in job["title"]:
                    matched.update(emails)

            if not matched:
                continue

            for email in matched:
                email_tasks.append(ex.submit(
                    send_email,
                    "🚨 Job Alert",
                    f"{job['title']} at {job['company']}\n{job['url']}",
                    email
                ))

            new_rows.append([job["url"], job["title"], job["company"], "Canada"])

    if new_rows:
        job_sheet.append_rows(new_rows)

    return {"new_jobs": len(new_rows)}

# ================= ROUTES =================
@app.route("/")
def home():
    return "Service running"

@app.route("/run")
def run():
    return process_jobs()

@app.route("/register")
def register():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Alerts</title>

<style>
body {
  margin: 0;
  font-family: 'Segoe UI', sans-serif;
  background: linear-gradient(135deg, #667eea, #764ba2);
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
}
.card {
  background: white;
  padding: 30px;
  border-radius: 15px;
  width: 90%;
  max-width: 420px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.2);
  text-align: center;
}
h2 { color: #333; }
input, textarea {
  width: 100%;
  padding: 12px;
  margin-top: 10px;
  margin-bottom: 15px;
  border-radius: 10px;
  border: 1px solid #ccc;
}
button {
  width: 100%;
  padding: 14px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  font-size: 16px;
  cursor: pointer;
}
</style>
</head>

<body>

<div class="card">
<h2>🚀 Job Alerts</h2>

<form action="/create-checkout-session" method="post">
<input type="email" name="email" placeholder="Enter your email" required>
<textarea name="titles" placeholder="devops engineer, java developer, sre" required></textarea>
<button type="submit">Subscribe for $20</button>
</form>

</div>

</body>
</html>
""")

@app.route("/create-checkout-session", methods=["POST"])
def create():
    email = request.form["email"]
    titles = request.form["titles"]

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Job Alerts"},
                "unit_amount": 2000,
            },
            "quantity": 1,
        }],
        mode="payment",
        metadata={"email": email, "titles": titles},
        success_url="https://linkedin-job-alert-7uhw.onrender.com/success",
        cancel_url="https://linkedin-job-alert-7uhw.onrender.com/register",
    )

    return redirect(session.url)

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_KEY)
    except:
        return "", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        save_user(session["metadata"]["email"], session["metadata"]["titles"])

    return "", 200

@app.route("/success")
def success():
    return "Payment success"

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
