import os
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, redirect
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import stripe

app = Flask(__name__)

# =========================
# CONFIG
# =========================
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

stripe.api_key = os.getenv("STRIPE_API_KEY")
endpoint_secret = os.getenv("WEBHOOK_KEY")

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# =========================
# GOOGLE SHEETS SETUP
# =========================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(GOOGLE_CREDENTIALS)
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)

job_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")
user_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet6")

# =========================
# CANADA LOCATION CHECK
# =========================
CANADA_LOCATION_KEYWORDS = {
    "canada",
    "ontario", "on",
    "alberta", "ab",
    "british columbia", "bc",
    "manitoba", "mb",
    "new brunswick", "nb",
    "newfoundland and labrador", "nl",
    "nova scotia", "ns",
    "prince edward island", "pe",
    "quebec", "qc",
    "saskatchewan", "sk",
    "northwest territories", "nt",
    "nunavut", "nu",
    "yukon", "yt",
    "toronto", "ottawa", "mississauga", "brampton", "hamilton",
    "scarborough", "markham", "vaughan", "richmond hill",
    "waterloo", "kitchener", "cambridge", "guelph", "london",
    "windsor", "burlington", "oakville", "milton", "ajax",
    "pickering", "oshawa", "whitby", "barrie", "kingston",
    "montreal", "montréal", "quebec city", "québec city", "laval",
    "longueuil", "gatineau", "sherbrooke",
    "vancouver", "surrey", "burnaby", "richmond", "victoria",
    "kelowna", "abbotsford", "nanaimo",
    "calgary", "edmonton", "red deer",
    "winnipeg", "regina", "saskatoon",
    "halifax", "st. john's", "st john's", "fredericton",
    "moncton", "charlottetown", "yellowknife", "whitehorse", "iqaluit",
    "remote - canada", "canada remote", "remote, canada", "remote in canada"
}

def is_canada_location(location_text: str) -> bool:
    if not location_text:
        return False

    text = location_text.strip().lower()

    if text in CANADA_LOCATION_KEYWORDS:
        return True

    for keyword in CANADA_LOCATION_KEYWORDS:
        if keyword in text:
            return True

    return False

# =========================
# USERS
# =========================
def load_users():
    rows = user_sheet.get_all_values()
    users = []

    for row in rows:
        if len(row) >= 2:
            email = row[0].strip().lower()
            titles = row[1].strip()

            users.append({
                "email": email,
                "titles": [t.strip().lower() for t in titles.split(",") if t.strip()]
            })

    return users


def save_user(email, titles):
    email = email.strip().lower()
    new_titles = {t.strip().lower() for t in titles.split(",") if t.strip()}

    rows = user_sheet.get_all_values()

    for idx, row in enumerate(rows, start=1):
        if len(row) >= 1 and row[0].strip().lower() == email:
            existing_titles = set()
            if len(row) > 1 and row[1].strip():
                existing_titles = {t.strip().lower() for t in row[1].split(",") if t.strip()}

            merged = existing_titles.union(new_titles)
            updated_titles = ",".join(sorted(merged))
            user_sheet.update_cell(idx, 2, updated_titles)
            print(f"updated user: {email}")
            return

    user_sheet.append_row([email, ",".join(sorted(new_titles))])
    print(f"new user added: {email}")

# =========================
# EMAIL
# =========================
def send_email(subject, body, to_email):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)

# =========================
# JOB DEDUP
# =========================
def job_already_sent(job_url):
    try:
        return job_url in job_sheet.col_values(1)
    except Exception:
        return False


def mark_job_as_sent(job_url, title, company, location):
    try:
        job_sheet.append_row([job_url, title, company, location])
    except Exception:
        pass

# =========================
# LINKEDIN FETCH
# =========================
def fetch_jobs_for_title(job_title):
    params = {
        "keywords": job_title,
        "location": "Canada",
        "f_TPR": "r86400",
        "sortBy": "DD"
    }

    try:
        response = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=20)
        if response.status_code != 200:
            print(f"linkedin failed for {job_title}: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.find_all("li")
        jobs = []

        for card in cards:
            link_tag = card.select_one('a.base-card__full-link')
            title_tag = card.select_one('h3.base-search-card__title')
            company_tag = card.select_one('h4.base-search-card__subtitle')
            location_tag = card.select_one('span.job-search-card__location')

            if not link_tag or not title_tag or not company_tag:
                continue

            job_url = link_tag.get("href", "").split("?")[0].strip()
            title = title_tag.get_text(" ", strip=True).lower()
            company = company_tag.get_text(" ", strip=True)
            location = location_tag.get_text(" ", strip=True) if location_tag else ""

            if not job_url:
                continue

            jobs.append({
                "job_url": job_url,
                "title": title,
                "company": company,
                "location": location
            })

        return jobs

    except Exception as e:
        print(f"error fetching {job_title}: {e}")
        return []

# =========================
# PROCESS JOBS
# =========================
def process_jobs():
    users = load_users()
    if not users:
        return

    all_titles = set()
    for user in users:
        for title in user["titles"]:
            all_titles.add(title)

    if not all_titles:
        return

    seen_urls = set()

    for search_title in all_titles:
        jobs = fetch_jobs_for_title(search_title)

        for job in jobs:
            job_url = job["job_url"]
            title = job["title"]
            company = job["company"]
            location = job["location"]

            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            if job_already_sent(job_url):
                continue

            # strict Canada validation
            if not is_canada_location(location):
                continue

            matched_users = []
            for user in users:
                if any(t in title for t in user["titles"]):
                    matched_users.append(user["email"])

            if not matched_users:
                continue

            body = f"{title} at {company}\n{location}\n{job_url}"

            for email in matched_users:
                try:
                    send_email("🚨 Job Alert - Canada", body, email)
                except Exception as e:
                    print(f"email failed for {email}: {e}")

            mark_job_as_sent(job_url, title, company, location)

# =========================
# REGISTER PAGE
# =========================
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
  box-sizing: border-box;
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
<textarea name="titles" placeholder="devops engineer, sre, platform engineer" required></textarea>
<button type="submit">Subscribe for $20</button>
</form>
</div>
</body>
</html>
""")

# =========================
# STRIPE CHECKOUT
# =========================
@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    email = request.form.get("email")
    titles = request.form.get("titles")

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

# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception:
        return "", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        save_user(session["metadata"]["email"], session["metadata"]["titles"])

    return "", 200

# =========================
# SUCCESS
# =========================
@app.route("/success")
def success():
    return "✅ Payment successful!"

# =========================
# RUN JOBS
# =========================
@app.route("/")
def run_jobs():
    process_jobs()
    return "Jobs processed"

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
