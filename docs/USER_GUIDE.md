# JobPilot User Guide

Complete guide to running the LinkedIn hiring-post scraper, email/contact extraction, and network outreach automation.

---

## Table of Contents

1. [What This Project Does](#what-this-project-does)
2. [Current Branch Status](#current-branch-status)
3. [Quick Start](#quick-start)
4. [Running the Scrapers](#running-the-scrapers)
5. [Running Network Outreach](#running-network-outreach)
6. [Running Email Outreach](#running-email-outreach)
7. [Exporting Data](#exporting-data)
8. [Data Integrity & Deduplication](#data-integrity--deduplication)
9. [Configuration](#configuration)
10. [File Structure](#file-structure)
11. [Troubleshooting](#troubleshooting)
12. [Daily Workflow](#daily-workflow)
13. [Exported Files](#exported-files)

---

## What This Project Does

JobPilot automates LinkedIn hiring-post discovery and contact extraction:

- **Posts Scraper**: Scrapes LinkedIn content search by hiring keywords (71 keywords: Python, Django, AI, RAG, LangChain, Node.js, FastAPI, Full Stack, React, Next.js, Java, Senior/Mid-level 3-4+ years, etc.)
- **Feed Scraper**: Scrapes LinkedIn main feed for organic hiring posts
- **Network Outreach**: Connects with HR/recruiters on LinkedIn via "Grow your network" page, with A/B message testing, deduplication, daily caps, and follow-up scheduling
- **Email Outreach**: Drafts and sends application emails via SMTP with rate limiting
- **Export**: Writes all data to CSV + Excel

All data is stored in SQLite (`data/jobpilot.db`) — nothing is ever erased. Re-running only adds new data and skips duplicates automatically.

---

## Current Branch Status

| Branch | Purpose | Status |
|---|---|---|
| `main` | Production (stable) | Do not commit directly |
| `dev` | Integration (all features merged) | **You are here** |
| `feature/linkedin-posts-hiring-scraper` | Content search scraper | Merged into dev |
| `feature/linkedin-feed-scraper` | Main feed scraper | Merged into dev |
| `feature/linkedin-network-outreach` | Connect/DM/followup/referral | Merged into dev |
| `feature/easy-apply-manual-control` | Easy Apply jobs | Existing |

**Working tree: clean** — all code committed and pushed to origin.

---

## Quick Start

### Activate Virtual Environment
```bash
cd /home/neosoft/myWork/AutomateJobApplying
source .venv/bin/activate
```

### Check Available Commands
```bash
.venv/bin/jobpilot --help
```

---

## Running the Scrapers

### Posts Scraper (Content Search)
Scrapes LinkedIn content search results for hiring keywords.

```bash
.venv/bin/jobpilot posts
```

- Scrapes **71 hiring keywords** across Python, Django, AI, RAG, LangChain, Node.js, FastAPI, Full Stack, React, Next.js, Java, Senior/Mid-level (3-4+ years), and more
- Each keyword scrolls through LinkedIn results, expands "…more" text, and extracts emails from post content
- ~826 posts/hour during active LinkedIn hours
- Deduplicates automatically (skips already-scraped posts)
- Stores in SQLite: `data/jobpilot.db`

### Feed Scraper (Main Feed)
Scrapes your LinkedIn main feed for organic hiring posts.

```bash
.venv/bin/jobpilot feed
```

- Opens `linkedin.com/feed/`
- Scrolls through feed, checks each post for hiring signals
- Skips non-hiring posts (LinkedIn News, puzzles, promotions, profile views)
- Faster but yields fewer results than keyword search

---

## Running Network Outreach

### Connect with HRs/Recruiters
```bash
.venv/bin/jobpilot network connect --limit 20
```

- Opens `linkedin.com/mynetwork/grow/` (reliable "Connect" buttons)
- Finds HR/recruiter/hiring professional posts
- Filters by job title keywords (hr, recruiter, talent, hiring, people ops, etc.)
- Clicks "Connect" buttons with randomized delays (30-90s)
- A/B tests 3 message variants per person
- Daily cap: 20 connections/day

### Send Direct Messages
```bash
.venv/bin/jobpilot network dm --limit 10
```

### Send Follow-ups (Auto-scheduled)
```bash
.venv/bin/jobpilot network followup --limit 10
```
- Sends follow-ups 3, 7, and 14 days after initial contact
- Stops after 5 messages per person

### Send Referral Requests
```bash
.venv/bin/jobpilot network referral --limit 10
```

### View Statistics
```bash
.venv/bin/jobpilot network stats
```

---

## Running Email Outreach

### Draft Emails from Extracted Contacts
```bash
.venv/bin/jobpilot mail draft
```
- Creates mail drafts from extracted email contacts
- Only drafts for hiring-related posts/jobs
- Deduplicates by email address

### Review Pending Drafts
```bash
.venv/bin/jobpilot mail list
```

### Approve Drafts
```bash
.venv/bin/jobpilot mail approve
```

### Send Approved Emails
```bash
.venv/bin/jobpilot mail send --limit 10
```
- Requires `mail.enabled: true` and SMTP credentials in `.env`
- Daily cap: 40 emails/day
- Per-domain cap: 2 emails/day
- Randomized delays between sends

---

## Exporting Data

### Export All Data to CSV + Excel
```bash
.venv/bin/jobpilot export
```

Creates:
| File | Description |
|---|---|
| `data/exports/jobpilot_YYYY-MM-DD.xlsx` | Full Excel with all datasets |
| `data/exports/csv/hiring_contacts.csv` | All contacts: email, company, requirements, author, source_url, search_keyword, context |
| `data/exports/csv/contacts.csv` | All extracted contacts (emails, phones, links) |
| `data/exports/csv/hiring_posts.csv` | All scraped hiring posts |
| `data/exports/csv/all_jobs.csv` | All job applications |
| `data/exports/csv/mail_queue.csv` | Mail queue status |

### Fresh Contacts Export (Recent Only)
The system also generates date-filtered exports:
- `data/exports/csv/hiring_contacts_fresh_nov24_26.csv` — 520 unique emails from Nov 24-26
- `data/exports/csv/hiring_contacts_fresh_nov25_26.csv` — Fresh emails Nov 25-26

---

## Data Integrity & Deduplication

### SQLite Database (`data/jobpilot.db`)

| Table | Purpose |
|---|---|
| `posts` | Scraped posts (post_id, url, author, text, query, is_hiring, hiring_score, company, requirements, first_seen) |
| `contacts` | Extracted emails/phones/links (kind, value, source_type, source_id, context, first_seen) |
| `outreach_contacts` | Outreach tracking with UNIQUE(kind, value) dedup |
| `outreach_messages` | Sent messages with A/B variant tracking |
| `outreach_campaigns` | Campaign management |
| `mail_queue` | Email draft queue |

### Safety Rules
- **Nothing is ever erased** — `INSERT OR IGNORE` on all tables
- **Duplicates are auto-skipped** — same email/person never processed twice
- **Re-running only adds new data** — safe to run repeatedly
- **Backup recommended** — `data/jobpilot.db` is a single file; copy it regularly

---

## Configuration (`config/settings.yaml`)

```yaml
posts:
  enabled: true
  date_filter: past-24h          # LinkedIn content-search filter
  max_scrolls: 15                # Scrolls per keyword
  max_posts_per_keyword: 60      # Max posts per keyword
  min_hiring_score: 3            # Minimum score to count as hiring
  ai_extract: false              # LLM refinement (needs API key)
  analyze_each_page: false       # Open each post page (slower, more emails)
  keywords:                      # 71 hiring keywords
    - "hiring python developer"
    - "hiring django developer"
    - "hiring AI engineer"
    - "hiring RAG engineer"
    - "hiring LangChain developer"
    - "hiring node js developer"
    - "hiring FastAPI developer"
    - "hiring full stack developer"
    - "hiring react developer"
    - "hiring Next.js developer"
    - "hiring java developer"
    - "hiring senior software engineer"
    - ... (and 60 more)

feed:
  enabled: true
  max_scrolls: 12
  max_posts: 60
  min_hiring_score: 3

outreach:
  enabled: true
  daily_cap_connection: 20       # Max connections/day
  daily_cap_dm: 15               # Max DMs/day
  daily_cap_followup: 15
  daily_cap_referral: 10
  delay_min_s: 30                # Min delay between messages (anti-spam)
  delay_max_s: 90
  delay_per_domain_min_s: 60
  delay_per_domain_max_s: 180
  followup_1_days: 3
  followup_2_days: 7
  followup_3_days: 14
  ai_extract: false
  max_messages_per_person: 5     # Stop contacting after 5 messages
  dry_run: true                  # Prepare drafts, review before sending

browser:
  headless: false                # Set true for headless mode
  user_data_dir: data/chrome-profile  # Persistent LinkedIn login
  window_size: 1366,900
  page_load_timeout_s: 40
```

---

## File Structure

```
src/jobpilot/
├── browser/
│   ├── linkedin/
│   │   ├── posts.py          # Content search scraper
│   │   ├── feed.py           # Main feed scraper
│   │   ├── selectors.py      # All LinkedIn CSS/XPath selectors
│   │   └── session.py        # Login/session handling
├── features/
│   ├── posts/
│   │   ├── runner.py         # Posts pipeline logic
│   │   └── stage.py          # CLI command: jobpilot posts
│   ├── feed/
│   │   ├── runner.py         # Feed pipeline logic
│   │   └── stage.py          # CLI command: jobpilot feed
│   ├── outreach/
│   │   ├── runner.py         # Email outreach logic
│   │   ├── stage.py          # CLI command: jobpilot mail
│   │   ├── network.py        # LinkedIn network automation
│   │   ├── network_stage.py  # CLI command: jobpilot network
│   │   ├── contacts.py       # Email extraction from post text
│   │   ├── mailer.py         # SMTP sender with rate limiting
│   │   └── templates.py      # Email templates
├── storage/
│   └── db.py                 # SQLite repository (migration v3)
├── settings.py               # All settings dataclasses
└── core/
    ├── plugins.py            # Module discovery
    └── registry.py           # Stage/command registry

data/
├── chrome-profile/           # Persistent LinkedIn login
├── jobpilot.db               # SQLite database
└── exports/
    ├── csv/
    │   ├── hiring_contacts.csv          # All contacts
    │   ├── hiring_contacts_fresh_nov24_26.csv  # Fresh contacts Nov 24-26
    │   ├── hiring_contacts_fresh_nov25_26.csv  # Fresh contacts Nov 25-26
    │   └── jobpilot_YYYY-MM-DD.xlsx     # Full Excel export
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `0 containers in DOM` | LinkedIn rotated CSS classes | Update `POST_CONTAINERS` in `selectors.py` with current class names (inspect LinkedIn DOM) |
| Chrome opens but no content loads | Login/checkpoint wall | Manually log in via the Chrome window, then re-run |
| `0 posts scanned` | No matching posts found | Try different keywords, increase `max_scrolls`, or use `jobpilot feed` |
| Emails not sending | `mail.enabled: false` or missing SMTP credentials | Set `mail.enabled: true`, configure `SMTP_USER`/`SMTP_APP_PASSWORD` in `.env` |
| Daily cap reached | Daily limit hit | Wait until tomorrow or increase `daily_cap_*` in settings |
| Chrome closes immediately | Profile/login issue | Run with `headless: false` first to manually log in |

### Fixing Broken Selectors
1. Run with `-v` and check `logs/jobpilot.log`
2. In Chrome DevTools, inspect the element, copy class/aria attribute
3. Add at the **front** of the relevant list in `browser/linkedin/selectors.py`
4. Keep old selectors as fallbacks

---

## Daily Workflow

```bash
# 1. Scrape new hiring posts
.venv/bin/jobpilot posts

# 2. Scrape feed (optional supplement)
.venv/bin/jobpilot feed

# 3. Connect with HR/recruiters (daily cap: 20)
.venv/bin/jobpilot network connect --limit 20

# 4. Send due follow-ups
.venv/bin/jobpilot network followup --limit 10

# 5. Export everything
.venv/bin/jobpilot export

# 6. Review email drafts
.venv/bin/jobpilot mail list

# 7. Approve drafts
.venv/bin/jobpilot mail approve

# 8. Send approved emails (daily cap: 40)
.venv/bin/jobpilot mail send
```

---

## Exported Files (Latest)

| File | Description |
|---|---|
| `data/exports/jobpilot_2026-11-26.xlsx` | Full Excel with all datasets |
| `data/exports/csv/hiring_contacts.csv` | All contacts (5,887 total) |
| `data/exports/csv/hiring_contacts_fresh_nov24_26.csv` | Fresh emails Nov 24-26 (520 unique) |
| `data/exports/csv/hiring_contacts_fresh_nov25_26.csv` | Fresh emails Nov 25-26 (2 unique) |

---

## Safety Rules

1. **Never commit to `main`** — always merge from `dev`
2. **Never modify existing feature branches** — create new ones for changes
3. **Never delete feature branches** — they serve as history
4. **Test before merging** — run `pytest`, `jobpilot posts`, `jobpilot feed`, `jobpilot export`
5. **One feature per branch** — don't mix unrelated changes
6. **Update `config/settings.yaml` carefully** — it's gitignored (user-specific)

---

## Support

- Check `logs/jobpilot.log` for detailed logs
- Check `logs/screenshots/` for browser screenshots on errors
- Run `.venv/bin/jobpilot doctor` for system diagnostics
- All data in `data/jobpilot.db` — SQLite, single file, easy to backup