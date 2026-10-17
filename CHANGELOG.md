# Changelog
Newest first. Format follows Keep a Changelog.

## [0.1.0] - 2026-10-17
### Added
- Modular architecture: registries for stages, commands and exporters; plugin loading.
- SQLite storage with versioned migrations; legacy CSV import (jobs + questions).
- Master profile (`config/profile.yaml`) replacing personals/questions/search/resume drift.
- Answer engine: user bank > canned > rules > cached LLM > LLM > review queue; every question logged.
- Job scoring, resume variant selection, URL-based fresh-first search with yield-learning planner.
- LinkedIn adapters: session, job search, Easy Apply state machine, hiring-post scraper.
- Contact extraction (email incl. obfuscated, phone, forms/ATS) and hiring-post classifier.
- Outreach: relevance-gated drafts, editable templates, rate-limited SMTP.
- Excel/CSV export, text report, local dashboard, `doctor`, `init`.
### Changed
- Dry-run by default; secrets only in `.env`; no random answers.
### Removed
- Hard-coded API key, pyautogui pop-ups, manual chromedriver setup, CSV-based tracking.
