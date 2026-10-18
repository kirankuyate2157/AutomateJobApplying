# Operations

## First week plan
1. **Day 1**: `init`, fill profile, `doctor`, `answers import-legacy`, `jobpilot run` (dry). Watch the browser. Fix selectors if needed.
2. **Day 2**: answer pending questions (`jobpilot ui` is easiest), dry run again; `needs_review` should shrink.
3. **Day 3+**: `jobpilot --live run --only jobs` with `apply.daily_target: 10`, then raise to 30. The global `--live` option must come before the command; `jobpilot apply` also runs only the jobs stage.
4. Enable posts (already on) and review contacts/mail drafts before enabling `mail.enabled`.

## Scheduling
* Linux/macOS cron (weekdays 10:00): `0 10 * * 1-5 cd /path/to/jobpilot && .venv/bin/jobpilot --live run`
* Windows Task Scheduler: action `C:\path\jobpilot\.venv\Scripts\jobpilot.exe`, args `--live run`, start in the project folder.
The first run needs a visible browser to log in; afterwards `browser.headless: true` is possible (the profile keeps the session).

## Tuning targeting
* `apply.min_score` (default 50): raise to 60-70 for stricter fit. Each skipped job stores its reason in the `applications`/`all_jobs` sheet.
* `profile.max_required_years`, `avoid_keywords`, `target_roles`, `skills` drive scoring.
* `search.freshness_seconds` (default 24h) + fallback 7 days only when the quota is not met.
* The planner favours searches that historically produced applications (`search_yield` sheet).

## Fixing a broken selector (the usual failure)
Symptoms: "no results", fields not found, Easy Apply button not clicked.
1. Run with `-v` and look at `logs/jobpilot.log` and `logs/screenshots/<jobid>-*.png`.
2. In Chrome DevTools, inspect the element, copy a stable class/aria/data attribute.
3. Add it at the FRONT of the right list in `browser/linkedin/selectors.py`. Keep old ones as fallbacks.

## Checkpoint / captcha
The run pauses (up to 5 minutes) and waits while you solve it in the visible browser, then continues. No pop-ups.

## Data hygiene
* Back up `data/jobpilot.db` (single file). `jobpilot export` any time.
* Review `answers list --status cached`: LLM answers that are reused automatically. Override with `answers set`.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `Unknown key(s) in 'apply'` | typo in settings.yaml; the message lists valid keys |
| `needs_review` jobs pile up | `jobpilot answers list`, answer, rerun (they retry automatically) |
| LLM never answers | `doctor` shows missing key; confidence below `llm.min_confidence`; check `logs/` |
| Mail not sending | `mail.enabled`, drafts approved? `SMTP_USER/SMTP_APP_PASSWORD` in `.env`, Gmail App Password |
