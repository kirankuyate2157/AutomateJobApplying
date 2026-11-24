"""The Easy Apply state machine.

    click Easy Apply -> [ read fields -> answer -> fill -> Next/Review ]*
                       -> Submit (or discard in dry-run) -> verify

LinkedIn Easy Apply is an INLINE multi-page form on the job detail page,
NOT a modal dialog. Each page shows "X/N pages" progress.

Design rules:
  * a REQUIRED question without a confident answer => discard + 'needs_review'
    (never random answers, never an endless Next-loop)
  * dry_run stops at the final screen and discards: you can watch everything
    work with zero risk
  * every failure keeps a screenshot named after the job for debugging
  * the form is re-scanned after every Next click because LinkedIn re-renders
    the page for each step
  * JavaScript fallbacks find elements when Selenium selectors miss them
  * User control: before first job, pause and let you apply custom filters
    in the Chrome window, then press Enter to continue
  * Manual control mode: wait for YOU to manually click Easy Apply on any job
    (even low-score or skipped jobs), then the bot takes over form filling
  * Manual browse only mode: skip searching entirely, just wait for YOU to
    manually click Easy Apply on any LinkedIn job you find yourself
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from ...core.context import AppContext
from ...domain.models import ApplyResult, Job
from ...exceptions import DailyLimitReached
from ..helpers import find_first, page_text_contains, pause, safe_click, scroll_into_view, text_of
from . import forms
from . import selectors as S

log = logging.getLogger(__name__)
MAX_STEPS = 12          # an Easy Apply flow is normally 4-8 steps


class EasyApplier:
    def __init__(self, ctx: AppContext):
        self.ctx, self.driver = ctx, ctx.driver
        self._user_control_done = False

    # ----------------------------------------------------------------- api
    def apply(self, job: Job, resume_path: str = "") -> ApplyResult:
        d = self.driver
        cfg = self.ctx.settings.apply

        # 0. User control: before first job, pause so you can apply custom
        #    filters in Chrome. Press Enter in this terminal to continue.
        if not self._user_control_done:
            self._user_control_pause(cfg.manual_control, cfg.manual_browse_only)
            self._user_control_done = True

        # 1. Manual browse only: skip searching entirely. Just wait for YOU
        #    to manually click Easy Apply on any LinkedIn job you find.
        if cfg.manual_browse_only:
            return self._apply_manual_browse_only(job, resume_path)

        # 2. Manual control mode: wait for YOU to manually click Easy Apply
        #    on any job you want (even low-score or skipped jobs). The bot
        #    takes over form filling once the form appears.
        if cfg.manual_control:
            return self._apply_manual(job, resume_path)

        # 3. Auto mode: find & click the Easy Apply button
        button = find_first(d, S.job_apply_buttons(job.job_id, easy_only=True) + S.EASY_APPLY_BUTTON, timeout=3)
        if button is None:
            button = self._js_find_button(d, "Easy Apply")
        if button is None:
            return self._external(job)
        scroll_into_view(d, button)
        if not safe_click(d, button):
            return ApplyResult("failed", "could not click Easy Apply")
        pause(1.0, 2.0)

        # 4. Wait for the inline Easy Apply form to appear.
        form_ready = self._wait_for_easy_apply_form(d, timeout=8)
        if not form_ready:
            self._check_limit()
            self._screenshot(job, "form-not-found")
            self._debug_log_dom(d, "form-not-found")
            return ApplyResult("failed", "Easy Apply form did not appear")

        try:
            return self._run_form(job, resume_path)
        except DailyLimitReached:
            raise
        except Exception as exc:
            log.exception("easy apply crashed for %s", job.job_id)
            self._screenshot(job, "crash")
            self._debug_log_dom(d, "crash")
            self.discard()
            return ApplyResult("failed", f"{type(exc).__name__}: {exc}")

    # ----------------------------------------------------------------------
    def _apply_manual_browse_only(self, job: Job, resume_path: str) -> ApplyResult:
        """Manual browse mode: skip searching entirely. Open Chrome on LinkedIn
        and wait for YOU to manually click Easy Apply on any job you find.
        The bot takes over form filling once the form appears."""
        d = self.driver
        log.info("=" * 60)
        log.info("  MANUAL BROWSE ONLY MODE")
        log.info("=" * 60)
        log.info("  1. Browse LinkedIn jobs however you want")
        log.info("  2. Manually click 'Easy Apply' on ANY job you want to apply to")
        log.info("  3. The bot will auto-fill the form and submit")
        log.info("  4. After submit, click Easy Apply on the next job")
        log.info("  5. Press Ctrl+C in this terminal to stop")
        log.info("=" * 60)

        while True:
            try:
                # Wait for Easy Apply form to appear (you clicked it manually)
                form_ready = self._wait_for_easy_apply_form(d, timeout=300)  # 5 min wait
                if not form_ready:
                    log.info("  No form detected within 5 minutes. Waiting longer...")
                    continue

                log.info("  Easy Apply form detected! Taking over form filling...")
                try:
                    result = self._run_form(job, resume_path)
                    if result.status in ("applied", "dry_run_ok"):
                        log.info("  Application complete! Click Easy Apply on the next job, or Ctrl+C to stop.")
                    else:
                        log.warning(f"  Application result: {result.status} - {result.reason}")
                    # Small pause before waiting for next manual click
                    pause(1.0, 2.0)
                except DailyLimitReached:
                    raise
                except Exception as exc:
                    log.exception("  Form filling crashed")
                    self._screenshot(job, "crash")
                    self._debug_log_dom(d, "crash")
                    self.discard()

            except KeyboardInterrupt:
                log.info("\n  Manual browse mode stopped by user.")
                return ApplyResult("failed", "manual browse mode stopped by user")
            except DailyLimitReached:
                raise

    # ----------------------------------------------------------------------
    def _apply_manual(self, job: Job, resume_path: str) -> ApplyResult:
        """Manual control mode: wait for YOU to click Easy Apply on any job,
        then the bot takes over form filling. After submit, waits for next
        manual click. Press Ctrl+C to exit manual mode."""
        d = self.driver
        log.info("=" * 60)
        log.info("  MANUAL CONTROL MODE ACTIVE")
        log.info("=" * 60)
        log.info("  1. Filter jobs in Chrome however you want")
        log.info("  2. Manually click 'Easy Apply' on ANY job you want to apply to")
        log.info("  3. The bot will auto-fill the form and submit")
        log.info("  4. After submit, click Easy Apply on the next job")
        log.info("  5. Press Ctrl+C in this terminal to stop")
        log.info("=" * 60)

        while True:
            try:
                # Wait for Easy Apply form to appear (you clicked it manually)
                form_ready = self._wait_for_easy_apply_form(d, timeout=300)  # 5 min wait
                if not form_ready:
                    log.info("  No form detected within 5 minutes. Waiting longer...")
                    continue

                log.info("  Easy Apply form detected! Taking over form filling...")
                try:
                    result = self._run_form(job, resume_path)
                    if result.status in ("applied", "dry_run_ok"):
                        log.info("  Application complete! Click Easy Apply on the next job, or Ctrl+C to stop.")
                    else:
                        log.warning(f"  Application result: {result.status} - {result.reason}")
                    # Small pause before waiting for next manual click
                    pause(1.0, 2.0)
                except DailyLimitReached:
                    raise
                except Exception as exc:
                    log.exception("  Form filling crashed")
                    self._screenshot(job, "crash")
                    self._debug_log_dom(d, "crash")
                    self.discard()

            except KeyboardInterrupt:
                log.info("\n  Manual control mode stopped by user.")
                return ApplyResult("failed", "manual mode stopped by user")
            except DailyLimitReached:
                raise

    # ------------------------------------------------------------- internals
    def _user_control_pause(self, manual_control: bool = False,
                            manual_browse_only: bool = False) -> None:
        """Pause before first application so you can apply custom
        filters in Chrome. Press Enter in this terminal to continue."""
        print("\n" + "=" * 60)
        if manual_browse_only:
            print("  JOBPILOT MANUAL BROWSE ONLY MODE")
        elif manual_control:
            print("  JOBPILOT MANUAL CONTROL MODE")
        else:
            print("  JOBPILOT USER CONTROL PAUSE")
        print("=" * 60)
        print("  Chrome is now open on LinkedIn.")
        if manual_browse_only:
            print("  1. Browse LinkedIn jobs however you want")
            print("  2. Manually click 'Easy Apply' on any job you want to apply to")
            print("  3. The bot will auto-fill the form and submit")
            print("  4. After submit, click Easy Apply on the next job")
            print("  5. Press Ctrl+C in this terminal to stop")
        elif manual_control:
            print("  1. Apply any custom filters you want (location, experience, etc.)")
            print("  2. Make sure Easy Apply filter is ON")
            print("  3. Manually click 'Easy Apply' on any job you want to apply to")
            print("  4. The bot will auto-fill the form and submit")
            print("  5. After submit, click Easy Apply on the next job")
            print("  6. Press Ctrl+C in this terminal to stop manual mode")
        else:
            print("  1. Apply any custom filters you want (location, experience, etc.)")
            print("  2. Make sure Easy Apply filter is ON")
            print("  3. Come back here and press ENTER to start applying")
        print("=" * 60 + "\n")
        try:
            input("  Press Enter to continue... ")
        except EOFError:
            pass
        print("\n  Continuing...\n")

    def _wait_for_easy_apply_form(self, d, timeout: int = 8) -> bool:
        """Wait for the inline Easy Apply form to appear after clicking
        the Easy Apply button. Returns True when form elements are detected."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Check for Next button (indicates form is active)
            if find_first(d, S.NEXT_BUTTON, timeout=0) is not None:
                return True
            # Check for Review button (final step)
            if find_first(d, S.REVIEW_BUTTON, timeout=0) is not None:
                return True
            # Check for Submit button
            if find_first(d, S.SUBMIT_BUTTON, timeout=0) is not None:
                return True
            # Check for page indicator "X/N pages"
            try:
                body = d.find_element(By.TAG_NAME, "body").get_attribute("innerText") or ""
                if re.search(r"\d+/\d+\s+pages?", body):
                    return True
            except WebDriverException:
                pass
            time.sleep(0.3)
        return False

    def _run_form(self, job: Job, resume_path: str) -> ApplyResult:
        """Walk the inline Easy Apply form page by page until Submit."""
        d, cfg = self.driver, self.ctx.settings.apply
        used_resume = ""
        resume_uploaded = False
        step = 0
        last_page_text = ""
        stuck_count = 0

        while step < MAX_STEPS:
            step += 1
            pause(0.5, 1.1)

            # Re-read the page each step (LinkedIn re-renders for each step)
            page_text = ""
            try:
                page_text = d.find_element(By.TAG_NAME, "body").get_attribute("innerText") or ""
            except WebDriverException:
                pass

            # Detect if we're stuck on the same page (Siebel loop)
            if page_text == last_page_text and last_page_text:
                stuck_count += 1
            else:
                stuck_count = 0
            last_page_text = page_text

            if stuck_count >= 3:
                self._screenshot(job, f"stuck-step{step}")
                self._debug_log_dom(d, f"stuck-step{step}")
                self.discard()
                return ApplyResult("failed", f"page not advancing at step {step} (stuck loop)", used_resume)

            # Log current step
            page_match = re.search(r"(\d+)/(\d+)\s+pages?", page_text)
            step_info = f"step {step}"
            if page_match:
                step_info += f" (page {page_match.group(1)}/{page_match.group(2)})"
            log.info("easy-apply %s for %s | %s", step_info, job.title, job.company)

            # --- Read all fields on the current page ---------------------
            fields = forms.read_fields(d)
            log.info("  fields found: %d", len(fields))
            for f in fields:
                log.info("    field: label=%r kind=%r required=%s current=%r options=%s",
                         f.label, f.kind, f.required, f.current, f.options[:3])

            # --- Fill every field ---------------------------------------
            pending = self._answer_step(job, fields)
            if pending:
                self._screenshot(job, f"needs-review-step{step}")
                self._debug_log_dom(d, f"needs-review-step{step}")
                self.discard()
                return ApplyResult(
                    "needs_review",
                    "unanswered: " + "; ".join(p for p in pending if p) or "unknown fields",
                    used_resume,
                    pending=pending,
                )

            # --- Upload resume once (page 2 offers resume selection) ----
            if resume_path and not resume_uploaded:
                if forms.upload_resume(d, resume_path):
                    used_resume = Path(resume_path).name
                    resume_uploaded = True
                    log.info("  resume uploaded: %s", used_resume)

            # --- Check for Submit (final step) ---------------------------
            submit = self._find_button_anywhere(d, S.SUBMIT_BUTTON)
            if submit is None:
                submit = self._js_find_button(d, "Submit application")
            if submit is not None:
                log.info("  submit button found -> finishing")
                return self._finish(job, submit, used_resume)

            # --- Click Next / Review to advance --------------------------
            nxt = self._find_button_anywhere(d, S.REVIEW_BUTTON)
            if nxt is None:
                nxt = self._find_button_anywhere(d, S.NEXT_BUTTON)
            if nxt is None:
                nxt = self._js_find_button(d, "Next") or self._js_find_button(d, "Review")
            if nxt is None:
                self._screenshot(job, f"no-next-step{step}")
                self._debug_log_dom(d, f"no-next-step{step}")
                self.discard()
                return ApplyResult("failed", f"no Next/Review/Submit button found at step {step}", used_resume)

            btn_text = (nxt.get_attribute("innerText") or nxt.text or "").strip() or "Next/Review"
            log.info("  clicking %s", btn_text)
            scroll_into_view(d, nxt)
            if not safe_click(d, nxt):
                try:
                    d.execute_script("arguments[0].click();", nxt)
                    log.info("  clicked %s via JavaScript fallback", btn_text)
                except WebDriverException:
                    self._screenshot(job, f"click-failed-step{step}")
                    self._debug_log_dom(d, f"click-failed-step{step}")
                    self.discard()
                    return ApplyResult("failed", f"could not click Next/Review at step {step}", used_resume)

            pause(1.0, 2.0)

        self.discard()
        return ApplyResult("failed", f"more than {MAX_STEPS} steps", used_resume)

    # ----------------------------------------------------------------------
    def _find_button_anywhere(self, d, selectors) -> object | None:
        """Find a button page-wide."""
        btn = find_first(d, selectors, timeout=0)
        if btn is not None:
            return btn
        return None

    def _js_find_button(self, d, text_substring: str) -> object | None:
        """Use JavaScript to find a button whose text or aria-label contains
        the given substring."""
        js = """
        const text = arguments[0].toLowerCase();
        const buttons = Array.from(document.querySelectorAll('button'));
        for (const btn of buttons) {
            const label = (btn.getAttribute('aria-label') || '').toLowerCase();
            const inner = (btn.innerText || btn.textContent || '').toLowerCase();
            if (label.includes(text) || inner.includes(text)) {
                return btn;
            }
        }
        return null;
        """
        try:
            result = d.execute_script(js, text_substring.lower())
            if result is not None:
                return result
        except WebDriverException:
            pass
        return None

    def _debug_log_dom(self, d, why: str) -> None:
        """Use JavaScript to log the DOM structure for debugging selector issues."""
        js = """
        const why = arguments[0];
        console.log('=== DOM DEBUG: ' + why + ' ===');
        const buttons = Array.from(document.querySelectorAll('button'));
        console.log('BUTTONS (' + buttons.length + '):');
        buttons.forEach((b, i) => {
            console.log('  [' + i + '] aria-label=' + JSON.stringify(b.getAttribute('aria-label')) +
                        ' class=' + JSON.stringify(b.className) +
                        ' text=' + JSON.stringify((b.innerText || b.textContent || '').trim().substring(0, 50)));
        });
        const fields = Array.from(document.querySelectorAll('input, select, textarea'));
        console.log('FIELDS (' + fields.length + '):');
        fields.forEach((f, i) => {
            const label = f.labels ? f.labels[0]?.textContent?.trim() : '';
            console.log('  [' + i + '] type=' + JSON.stringify(f.type) +
                        ' name=' + JSON.stringify(f.name) +
                        ' id=' + JSON.stringify(f.id) +
                        ' placeholder=' + JSON.stringify(f.placeholder) +
                        ' aria-label=' + JSON.stringify(f.getAttribute('aria-label')) +
                        ' label=' + JSON.stringify(label));
        });
        return 'logged';
        """
        try:
            d.execute_script(js, why)
        except WebDriverException:
            pass

    def _answer_step(self, job: Job, fields) -> list[str]:
        """Fill every field on the current page. Returns labels of REQUIRED
        fields we could not answer."""
        pending: list[str] = []
        overwrite = self.ctx.settings.apply.overwrite_prefilled
        for f in fields:
            if forms.is_prefilled(f) and not overwrite:
                log.info("    skip pre-filled: %r", f.label)
                continue
            answer = self.ctx.engine.resolve(f, job)
            if answer is None:
                if f.required or f.kind == "radio":
                    pending.append(f.label or f.kind)
                    log.warning("    UNANSWERABLE required field: %r (kind=%r)", f.label, f.kind)
                continue
            ok = forms.fill_field(self.driver, f, answer.value)
            if ok:
                log.info("    filled %r = %r (source=%s)", f.label, answer.value, answer.source)
            else:
                log.warning("    fill FAILED: %r", f.label)
                if f.required:
                    pending.append(f.label or f.kind)
        return pending

    def _finish(self, job: Job, submit_btn, resume: str) -> ApplyResult:
        d = self.driver
        # Unfollow company checkbox (if present on review page)
        try:
            box = find_first(d, S.FOLLOW_CHECKBOX, timeout=0)
            if box is not None and box.is_selected():
                lab = find_first(d, S.FOLLOW_CHECKBOX_LABEL, timeout=0)
                if lab is not None:
                    safe_click(d, lab)
        except WebDriverException:
            pass
        if self.ctx.dry_run:
            log.info("[dry-run] would submit %s | %s", job.title, job.company)
            self.discard()
            return ApplyResult("dry_run_ok", "dry run: stopped at final screen", resume)
        safe_click(d, submit_btn)
        # Wait longer for submission to complete - check for success text OR URL change
        deadline = time.monotonic() + 15
        submit_url = d.current_url
        while time.monotonic() < deadline:
            # Check for success text
            if any(page_text_contains(d, t) for t in S.SUCCESS_TEXTS):
                done = find_first(d, S.DONE_BUTTON, timeout=0) or find_first(d, S.DISMISS_BUTTON, timeout=0)
                if done is None:
                    done = self._js_find_button(d, "Done") or self._js_find_button(d, "Dismiss")
                if done is not None:
                    safe_click(d, done)
                return ApplyResult("applied", "", resume)
            # Check if page changed (redirect after submit)
            try:
                if d.current_url != submit_url and "apply" not in d.current_url.lower():
                    return ApplyResult("applied", "", resume)
            except WebDriverException:
                pass
            time.sleep(0.5)
        self._check_limit()
        self._screenshot(job, "submit-unverified")
        return ApplyResult("failed", "submit clicked but success was not confirmed", resume)

    def _external(self, job: Job) -> ApplyResult:
        """No Easy Apply: record the external application URL (opened in a new tab)."""
        d = self.driver
        btn = find_first(d, S.job_apply_buttons(job.job_id) + S.ANY_APPLY_BUTTON, timeout=2)
        if btn is None:
            btn = self._js_find_button(d, "Apply")
        if btn is None:
            return ApplyResult("external", "no apply button")
        origin, before = d.current_window_handle, set(d.window_handles)
        try:
            scroll_into_view(d, btn)
            if safe_click(d, btn):
                pause(1.5, 2.5)
                new = [h for h in d.window_handles if h not in before]
                if new:
                    d.switch_to.window(new[-1])
                    url = d.current_url
                    d.close()
                    d.switch_to.window(origin)
                    return ApplyResult("external", "external application", external_url=url)
        except WebDriverException:
            log.debug("external link capture failed", exc_info=True)
            d.switch_to.window(origin)
        return ApplyResult("external", "external application")

    def discard(self) -> None:
        """Close any open Easy Apply form/discard draft."""
        d = self.driver
        try:
            _ = d.current_window_handle
        except WebDriverException:
            return
        try:
            # Press Escape to close any open dropdowns/dialogs
            d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            pause(0.4, 0.8)
            # Look for a Discard button
            confirm = find_first(d, S.DISCARD_CONFIRM, timeout=1.0)
            if confirm is None:
                confirm = self._js_find_button(d, "Discard")
            if confirm is not None:
                safe_click(d, confirm)
        except WebDriverException:
            log.debug("discard failed", exc_info=True)

    def _check_limit(self) -> None:
        if page_text_contains(self.driver, S.DAILY_LIMIT_TEXT):
            raise DailyLimitReached("LinkedIn daily Easy Apply limit reached")

    def _screenshot(self, job: Job, why: str) -> None:
        try:
            out = self.ctx.settings.path(self.ctx.settings.paths.log_dir) / "screenshots"
            out.mkdir(parents=True, exist_ok=True)
            self.driver.save_screenshot(str(out / f"{job.job_id}-{why}.png"))
        except WebDriverException:
            pass
