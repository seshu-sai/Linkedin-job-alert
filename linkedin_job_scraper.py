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

# =========================
# GOOGLE SHEETS
# =========================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

creds_dict = json.loads(GOOGLE_CREDENTIALS)
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")

# =========================
# USER STORAGE
# =========================
USER_FILE = "users.json"

def load_users():
    try:
        with open(USER_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_user(email, titles):
    users = load_users()
    users.append({
        "email": email,
        "titles": [t.strip().lower() for t in titles.split(",")]
    })
    with open(USER_FILE, "w") as f:
        json.dump(users, f, indent=2)

# =========================
# EMAIL FUNCTION
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
# GOOGLE SHEET HELPERS
# =========================
def job_already_sent(job_url):
    try:
        return job_url in sheet.col_values(1)
    except:
        return False

def mark_job_as_sent(job_url, title, company, location):
    try:
        sheet.append_row([job_url, title, company, location])
    except:
        pass

# =========================
# LINKEDIN CONFIG
# =========================
BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# JOB PROCESSING
# =========================
def process_jobs():
    users = load_users()

    query_params = {
        "keywords": "developer OR engineer OR devops OR java OR cloud",
        "location": "Canada",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }

    response = requests.get(BASE_URL, headers=HEADERS, params=query_params)

    if response.status_code != 200:
        return

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.find_all("li")

    for card in cards:
        link_tag = card.select_one('[class*="_full-link"]')
        title_tag = card.select_one('[class*="_title"]')
        company_tag = card.select_one('[class*="_subtitle"]')

        if link_tag and title_tag and company_tag:
            job_url = link_tag['href'].split('?')[0]

            if job_already_sent(job_url):
                continue

            title = title_tag.get_text(strip=True).lower()
            company = company_tag.get_text(strip=True)

            matched_users = []

            for user in users:
                if any(t in title for t in user["titles"]):
                    matched_users.append(user["email"])

            if not matched_users:
                continue

            body = f"{title} at {company}\n{job_url}"

            for email in matched_users:
                send_email("🚨 Job Alert", body, email)

            mark_job_as_sent(job_url, title, company, "Canada")

# =========================
# STRIPE REGISTER PAGE
# =========================
@app.route("/register")
def register():
    return render_template_string("""
        <h2>Subscribe for Job Alerts</h2>
        <form action="/create-checkout-session" method="post">
            Email:<br>
            <input type="email" name="email"><br><br>

            Job Titles:<br>
            <textarea name="titles"></textarea><br><br>

            <button type="submit">Subscribe ($5)</button>
        </form>
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
                "unit_amount": 50,
            },
            "quantity": 1,
        }],
        mode="payment",
        metadata={
            "email": email,
            "titles": titles
        },
        success_url="http://localhost:8080/success",
        cancel_url="http://localhost:8080/register",
    )

    return redirect(session.url)

# =========================
# WEBHOOK (CRITICAL)
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_data(as_text=True)
    event = json.loads(payload)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        email = session["metadata"]["email"]
        titles = session["metadata"]["titles"]

        save_user(email, titles)

    return "", 200

# =========================
# SUCCESS PAGE
# =========================
@app.route("/success")
def success():
    return "✅ Payment successful! Subscription activated."

# =========================
# RUN JOBS
# =========================
@app.route("/")
def run_jobs():
    process_jobs()
    return "Jobs processed"

# =========================
# RUN APP
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
