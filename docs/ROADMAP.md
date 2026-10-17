# Roadmap / suggestions (incremental upgrades)

Each item is independent and fits the module system.

**Quality of answers**
- [ ] `profile import-resume resume.pdf`: pre-fill profile.yaml with the LLM, you only review.
- [ ] Per-job tailored summary / cover letter via LLM (cache by company+role).
- [ ] "Why this company" answers using the company's About text (scrape `jobs-company__box`).

**Targeting**
- [ ] Learn score weights from outcomes (record recruiter replies; logistic regression).
- [ ] Company watchlist: auto-search target companies' fresh postings.
- [ ] Salary-aware filtering when LinkedIn shows pay.

**Sources**
- [ ] `naukri`, `indeed`, `wellfound`, `instahyre` stages implementing `JobSource`/`Applier`.
- [ ] Follow external-apply links to ATS forms (Greenhouse/Lever) with a generic form filler.
- [ ] Resolve `lnkd.in` short links in posts to classify forms/ATS correctly.

**Outreach**
- [ ] Gmail API instead of SMTP; open/bounce tracking; follow-up mail after N days.
- [ ] Connect requests/messages to the HR person shown on job pages (`hr_link`).
- [ ] Mail-draft editor in the UI.

**Platform**
- [ ] Daily summary email/Telegram message after each run.
- [ ] Docker image + scheduled container.
- [ ] Charts page (applications per day, yield per search) in the UI.
- [ ] CI: run tests on every push (GitHub Actions).
- [ ] Swap hand-rolled settings loader for pydantic if configuration grows.
