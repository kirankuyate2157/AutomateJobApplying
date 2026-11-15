# JobPilot — Easy Apply Automation

Complete system for automated LinkedIn Easy Apply job applications with full manual control.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Apply Modes](#apply-modes)
3. [Command Reference](#command-reference)
4. [Configuration](#configuration)
5. [Profile Setup](#profile-setup)
6. [Manual Control Workflow](#manual-control-workflow)
7. [Score Criteria](#score-criteria)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Kill any leftover Chrome processes
pkill -9 -f chrome 2>/dev/null; pkill -9 -f chromedriver 2>/dev/null; sleep 2

# 2. Remove Chrome lock files
rm -f data/chrome-profile/DevToolsActivePort data/chrome-profile/SingletonLock

# 3. Run jobpilot
cd /home/neosoft/myWork/AutomateJobApplying
.venv/bin/jobpilot --live run --only jobs
```

Or use the dedicated apply command with a specific mode:

```bash
# Auto mode: search + apply with score filtering
.venv/bin/jobpilot apply auto --min-score 40 --limit 10

# Manual mode: you click Easy Apply, bot fills forms
.venv/bin/jobpilot apply manual --limit 5

# Browse mode: skip searching, wait for you to click Easy Apply
.venv/bin/jobpilot apply browse --limit 10

# Dry run: test without submitting
.venv/bin/jobpilot apply dry-run --min-score 40 --limit 5
```

---

## Apply Modes

### 1. Auto Mode (`jobpilot apply auto`)

The bot searches LinkedIn for Easy Apply jobs, scores them, and applies automatically.

- **Searches**: Uses your target roles, locations, and freshness settings
- **Scoring**: Jobs are scored 0-100 based on profile match
- **Filtering**: Jobs below `--min-score` are skipped
- **Application**: Bot clicks Easy Apply, fills all forms, submits

**Best for**: Hands-off automated applying with score-based filtering.

```bash
.venv/bin/jobpilot apply auto --min-score 40 --limit 10
```

### 2. Manual Mode (`jobpilot apply manual`)

You filter jobs in Chrome and click "Easy Apply" on each job you want. The bot takes over form filling and submission.

- **No auto-searching**: You control which jobs to apply to
- **Any job works**: Even low-score or skipped jobs can be applied to
- **Bot fills forms**: All form fields are auto-filled from your profile
- **Submit automatically**: Bot clicks Submit at the end

**Best for**: When you want to pick specific jobs but don't want to fill forms manually.

```bash
.venv/bin/jobpilot apply manual --limit 10
```

### 3. Browse Mode (`jobpilot apply browse`)

Skip all searching. Just open Chrome on LinkedIn and wait for you to click Easy Apply on any job you find yourself.

- **No searching at all**: Complete manual browsing
- **Any LinkedIn page works**: Notifications, job pages, your own searches
- **Bot fills forms**: Same auto-fill as manual mode

**Best for**: When you want to browse LinkedIn naturally and apply to jobs you discover.

```bash
.venv/bin/jobpilot apply browse --limit 10
```

### 4. Dry Run Mode (`jobpilot apply dry-run`)

Test the application flow without actually submitting. Useful for verifying forms fill correctly.

- **Fills all forms**: Same as live mode
- **Stops before Submit**: Stops at the final review screen
- **No applications sent**: Safe for testing

```bash
.venv/bin/jobpilot apply dry-run --min-score 40 --limit 5
```

---

## Command Reference

| Command | Description | Key Options |
|---------|-------------|-------------|
| `jobpilot apply auto` | Auto search + apply | `--min-score`, `--limit`, `--no-filter`, `--live`, `--dry-run` |
| `jobpilot apply manual` | You click Easy Apply, bot fills forms | `--limit`, `--live`, `--dry-run` |
| `jobpilot apply browse` | Skip searching, wait for you to click | `--limit`, `--live`, `--dry-run` |
| `jobpilot apply dry-run` | Test without submitting | `--min-score`, `--limit`, `--no-filter` |

### Global Options

| Option | Description |
|--------|-------------|
| `--live` | Really submit applications (overrides dry_run setting) |
| `--dry-run` | Force dry run (overrides settings) |
| `--limit N` | Maximum jobs to apply in this run |
| `--min-score N` | Minimum score 0-100 (default: from settings) |
| `--no-filter` | Apply to all jobs regardless of score |

---

## Configuration

### `config/settings.yaml`

Key settings for job application:

```yaml
apply:
  daily_target: 30        # max applications per day
  dry_run: false          # false = live submissions, true = test only
  min_score: 10           # minimum score 0-100 (lower = more jobs)
  max_per_hour: 12        # sliding window cap to avoid flags
  delay_min_s: 3          # min delay between applications (seconds)
  delay_max_s: 9          # max delay between applications (seconds)
  manual_control: false   # wait for you to click Easy Apply on each job
  manual_browse_only: false  # skip searching entirely
  unfollow_company: True  # untick "follow company" on submit
  overwrite_prefilled: False  # keep LinkedIn's pre-filled values

search:
  locations: ["India", "Remote", "Pune", "Mumbai", "Bengaluru", "Hyderabad", "Delhi", "Chennai"]
  freshness_seconds: 604800          # 7 days (newest jobs)
  fallback_freshness_seconds: 2592000 # 30 days (wider search)
  easy_apply_only: true              # only Easy Apply jobs
  experience_levels: [2, 3, 4]       # Entry, Associate, Mid-Senior
```

**Score thresholds:**
- `0-30`: Very low match (usually not worth applying)
- `30-49`: Low match (might apply if desperate)
- `40-59`: Good match (recommended minimum)
- `60-79`: Strong match
- `80-100`: Excellent match

---

## Profile Setup

### `config/profile.yaml`

Your personal profile is the single source of truth for form answers:

```yaml
first_name: Kiran
last_name: Kuyate
email: kiranrkuyate2021@gmail.com
phone: "7083418824"
city: Mumbai
state: Maharashtra
country: India
linkedin_url: https://www.linkedin.com/in/kirankuyate
github_url: https://github.com/kirankuyate2157
portfolio_url: https://kiran-kuyate-portfolio.vercel.app/

total_years: 3
current_company: NeoSoft
current_title: Software Engineer (Full Stack)
notice_period_days: 15       # 15 days = immediate joiner
current_ctc: 790000          # INR per annum
expected_ctc: 1800000        # INR per annum
degrees: [bachelor]

skills:
  python: 3
  node.js: 3
  react: 3
  postgresql: 3
  docker: 3
  aws: 3
  # ... 38 skills total
  java: 1                    # only 1 year (not full-time)

resumes:
  - path: /home/neosoft/Downloads/Kiran_Kuyate_2024_Full_Stack.pdf
    label: fullstack
    default: true
```

**Skills are used to answer:**
- "Years of experience with [skill]?"
- "Do you have experience with [skill]?"

**Notice period is used to answer:**
- "How soon can you join?"
- "Notice period in days?"
- "Can you start immediately?" (≤15 days = Yes)

**CTC is used to answer:**
- "Current CTC"
- "Expected CTC"
- "Salary expectation"

---

## Manual Control Workflow

When using `manual` or `browse` mode:

```
┌─────────────────────────────────────────────────────────┐
│  JOBPILOT MANUAL BROWSE ONLY MODE                       │
│  ====================================================== │
│  Chrome is now open on LinkedIn.                        │
│  1. Browse LinkedIn jobs however you want               │
│  2. Manually click 'Easy Apply' on any job              │
│  3. The bot will auto-fill the form and submit          │
│  4. After submit, click Easy Apply on the next job      │
│  5. Press Ctrl+C in this terminal to stop               │
└─────────────────────────────────────────────────────────┘
```

**Step-by-step:**

1. Run `jobpilot apply browse` (or `manual`)
2. Chrome opens — you're already logged in via your Chrome profile
3. Browse LinkedIn jobs however you want
4. When you see a job you like, click "Easy Apply"
5. The bot detects the form and fills it automatically
6. Bot submits the application
7. Repeat: click Easy Apply on another job
8. Press `Ctrl+C` in terminal when done

**What the bot fills automatically:**
- Name, email, phone, location
- Years of experience (per skill)
- Notice period
- CTC (current and expected)
- LinkedIn/GitHub/portfolio URLs
- Cover letter
- Resume upload
- Yes/No eligibility questions
- Radio button selections

---

## Score Criteria

Jobs are scored 0-100 based on:

| Factor | Weight |
|--------|--------|
| Role match (target_roles) | 25 points |
| Skill match (skills overlap) | 25 points |
| Experience level (≤ max_required_years) | 20 points |
| Location match (authorized_countries) | 15 points |
| Freshness (recently posted) | 10 points |
| Avoid keywords (penalty) | -25 points per match |
| Avoid companies (penalty) | -25 points per match |

**Recommended min_score:**
- `40`: Only good matches (recommended)
- `30`: Accept most jobs
- `10`: Accept almost everything
- `0`: Apply to everything

---

## Troubleshooting

### Chrome crashes between runs

```bash
# Kill all Chrome processes
pkill -9 -f chrome 2>/dev/null; pkill -9 -f chromedriver 2>/dev/null; sleep 3

# Remove lock files
rm -f data/chrome-profile/DevToolsActivePort data/chrome-profile/SingletonLock

# Re-run
.venv/bin/jobpilot --live run --only jobs
```

### No Easy Apply jobs found

- Widen `freshness_seconds` (try 604800 for 7 days)
- Add more locations to `search.locations`
- Set `easy_apply_only: false` to see all jobs
- Check your LinkedIn profile is logged in

### Fields not being filled

- Check `logs/jobpilot.log` for "UNANSWERABLE required field" messages
- Add canned answers in `config/profile.yaml` under `canned_answers`
- Use `jobpilot answers list` to review pending questions
- Some questions need manual answers once — they're saved for next time

### Submit not confirmed

- LinkedIn may take time to process — the bot waits 15 seconds
- Check `logs/screenshots/` for failure screenshots
- Some jobs redirect to external sites (shown as "external" status)

---

## Files

| File | Purpose |
|------|---------|
| `config/settings.yaml` | Application settings (modes, scores, locations) |
| `config/profile.yaml` | Personal profile (skills, experience, CTC, projects) |
| `data/resumes/Kiran_Kuyate_2024_Full_Stack.pdf` | Resume file |
| `logs/jobpilot.log` | Application logs |
| `logs/screenshots/` | Failure screenshots |
| `src/jobpilot/features/jobs/stage.py` | Apply command implementation |
| `src/jobpilot/browser/linkedin/easy_apply.py` | Easy Apply state machine |
| `src/jobpilot/browser/linkedin/forms.py` | Form reading and filling |
| `src/jobpilot/browser/linkedin/selectors.py` | LinkedIn DOM selectors |
| `src/jobpilot/answering/rules.py` | Answer rules for form questions |
| `src/jobpilot/profile/profile.py` | Profile data model |

---

## Example Usage

```bash
# Test without submitting (dry run)
.venv/bin/jobpilot apply dry-run --limit 5

# Auto apply to good matches only
.venv/bin/jobpilot apply auto --min-score 40 --limit 10

# Manual: you pick jobs, bot fills forms
.venv/bin/jobpilot apply manual --limit 10

# Browse LinkedIn yourself, click Easy Apply on any job
.venv/bin/jobpilot apply browse --limit 10

# Apply to everything regardless of score
.venv/bin/jobpilot apply auto --no-filter --limit 20
```

---

---

## Automatic Morning Scheduling (Cron)

Set up JobPilot to run automatically every weekday morning between 11:00 AM and 11:30 AM, but **only when your computer is on**.

### Install Cron Job

```bash
# Make scripts executable
chmod +x scripts/morning_apply.sh scripts/install_cron.sh

# Install the cron job
./scripts/install_cron.sh
```

This adds a cron entry that runs every 15 minutes between 11:00-11:30 AM on weekdays (Mon-Fri):

```
*/15 11 * * 1-5 /home/neosoft/myWork/AutomateJobApplying/scripts/morning_apply.sh
```

### How It Works

1. **Computer must be on** — If your computer is off/sleeping at 11:00 AM, the job simply won't run (no missed applications)
2. **Time window** — Only runs between 11:00 AM and 11:30 AM
3. **Weekdays only** — Monday through Friday
4. **Every 15 minutes** — If you miss the first run, it tries again at 11:15, 11:30
5. **Manual browse mode** — Uses `apply browse` mode, so you still click Easy Apply on jobs you want, and the bot fills forms

### Cron Management

```bash
# View installed cron jobs
crontab -l

# Edit cron jobs manually
crontab -e

# Remove all cron jobs (careful — removes everything)
crontab -r

# Remove just the JobPilot job
crontab -e  # then delete the morning_apply.sh line
```

### Cron Logs

Cron output is logged to:
```
logs/cron_jobpilot.log
```

### Example Cron Output

```
[Mon Nov 16 11:00:15 IST 2026] JobPilot auto-apply check started
[Mon Nov 16 11:00:15 IST 2026] Time window active (11:00-11:30). Starting JobPilot...
[Mon Nov 16 11:00:20 IST 2026] starting Chrome (profile=..., headless=False)
[Mon Nov 16 11:00:30 IST 2026] Easy Apply form detected! Taking over form filling...
[Mon Nov 16 11:00:35 IST 2026] Application complete! Click Easy Apply on the next job, or Ctrl+C to stop.
[Mon Nov 16 11:01:00 IST 2026] JobPilot finished with exit code: 0
[Mon Nov 16 11:01:00 IST 2026] JobPilot auto-apply check completed
```

### Manual Override

You can still run JobPilot manually at any time:
```bash
.venv/bin/jobpilot --live run --only jobs
```

The cron job won't interfere — it only runs during its scheduled window.
