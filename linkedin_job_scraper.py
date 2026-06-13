def process_jobs():
    users = load_users()

    if not users:
        return

    try:
        existing_jobs = set(job_sheet.col_values(1))
    except Exception:
        existing_jobs = set()

    first_run = len(existing_jobs) == 0

    new_rows = []
    seen_in_current_run = set()

    all_titles = set()
    for user in users:
        all_titles.update(user["titles"])

    for search_title in all_titles:
        jobs = fetch_jobs(search_title)

        for job in jobs:
            url = job["url"]

            if url in seen_in_current_run:
                continue

            seen_in_current_run.add(url)

            if url in existing_jobs:
                continue

            if not is_canada(job["location"]):
                continue

            matched_users = []

            for user in users:
                if any(title in job["title"] for title in user["titles"]):
                    matched_users.append(user["email"])

            if not matched_users:
                continue

            new_rows.append([
                url,
                job["title"],
                job["company"],
                job["location"],
                job["posted_time"],
                ", ".join(matched_users),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "baseline" if first_run else "emailed"
            ])

            existing_jobs.add(url)

            # First run: save only, don't email old jobs
            if first_run:
                continue

            body = f"""
New job posted in Canada

Job Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Posted Time: {job['posted_time']}

Apply here:
{url}
"""

            for email in matched_users:
                send_email("🚨 New LinkedIn Job Alert - Canada", body, email)

    if new_rows:
        job_sheet.append_rows(new_rows)
