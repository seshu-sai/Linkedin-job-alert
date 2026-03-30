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
HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# GOOGLE SHEETS SETUP
# =========================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

creds_dict = json.loads(GOOGLE_CREDENTIALS)
creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(CREDS)

job_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet2")
user_sheet = client.open("LinkedIn Job Tracker").worksheet("Sheet6")

# =========================
# USERS (NO DUPLICATES)
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
    new_titles = set([t.strip().lower() for t in titles.split(",") if t.strip()])

    rows = user_sheet.get_all_values()

    for idx, row in enumerate(rows, start=1):
        if len(row) >= 1 and row[0].strip().lower() == email:
            existing_titles = set(row[1].split(",")) if len(row) > 1 else set()

            merged = existing_titles.union(new_titles)
            updated_titles = ",".join(sorted(merged))

            user_sheet.update_cell(idx, 2, updated_titles)
            print(f"🔁 Updated user: {email}")
            return

    # new user
    user_sheet.append_row([email, ",".join(sorted(new_titles))])
    print(f"✅ New user added: {email}")

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
    except:
        return False


def mark_job_as_sent(job_url, title, company, location):
    try:
        job_sheet.append_row([job_url, title, company, location])
    except:
        pass

# =========================
# PROCESS JOBS (OPTIMIZED)
# =========================
def process_jobs():
    users = load_users()

    # 🔥 Collect all unique titles
    all_titles = set()
    for user in users:
        for t in user["titles"]:
            if t:
                all_titles.add(t)

    if not all_titles:
        print("❌ No keywords found")
        return

    keywords = " OR ".join(all_titles)
    print(f"🔍 Keywords: {keywords}")

    query_params = {
        "keywords": keywords,
        "location": "Canada",
        "f_TPR": "r3600",
        "sortBy": "DD"
    }

    response = requests.get(BASE_URL, headers=HEADERS, params=query_params)

    if response.status_code != 200:
        print("❌ Job fetch failed")
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
# STRIPE REGISTER
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

    h2 {
      margin-bottom: 10px;
      color: #333;
    }

    p {
      font-size: 14px;
      color: #777;
      margin-bottom: 20px;
    }

    input, textarea {
      width: 100%;
      padding: 12px;
      margin-top: 10px;
      margin-bottom: 15px;
      border-radius: 10px;
      border: 1px solid #ccc;
      font-size: 14px;
      transition: 0.2s;
    }

    input:focus, textarea:focus {
      border-color: #667eea;
      outline: none;
      box-shadow: 0 0 5px rgba(102,126,234,0.5);
    }

    textarea {
      resize: none;
      height: 90px;
    }

    button {
      width: 100%;
      padding: 14px;
      border: none;
      border-radius: 10px;
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: white;
      font-size: 16px;
      font-weight: bold;
      cursor: pointer;
      transition: 0.3s;
    }

    button:hover {
      opacity: 0.9;
      transform: scale(1.02);
    }

    .footer {
      margin-top: 15px;
      font-size: 12px;
      color: #999;
    }

    @media (max-width: 480px) {
      .card {
        padding: 20px;
      }
    }
  </style>
</head>

<body>

  <div class="card">
    <h2>🚀 Job Alerts</h2>
    <p>Get real-time job alerts directly to your inbox</p>

    <form action="/create-checkout-session" method="post">

      <input type="email" name="email" placeholder="Enter your email" required>

      <textarea name="titles" placeholder="e.g. devops engineer, java developer, sre" required></textarea>

      <button type="submit" onclick="this.innerText='Processing...'; this.disabled=true;">
        Subscribe for $5
      </button>

    </form>

    <div class="footer">
      🔔 Instant alerts • 💼 Latest jobs • 📩 Direct email
    </div>
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
                "unit_amount": 50,
            },
            "quantity": 1,
        }],
        mode="payment",
        metadata={
            "email": email,
            "titles": titles
        },
        success_url="https://linkedin-job-alert-7uhw.onrender.com/success",
        cancel_url="https://linkedin-job-alert-7uhw.onrender.com/register",
    )

    return redirect(session.url)

# =========================
# STRIPE WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except Exception as e:
        print("❌ Webhook error:", e)
        return "", 400

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
    return "✅ Payment successful! You will start receiving job alerts."

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
