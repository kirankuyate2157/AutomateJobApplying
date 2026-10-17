"""The Easy Apply state machine.

    open modal -> [ read fields -> answer -> fill -> upload resume -> Next/Review ]*
               -> Submit (or discard in dry-run) -> verify

Design rules that fix the legacy bot's weak spots:
  * a REQUIRED question without a confident answer => discard + 'needs_review'
    (never random answers, never an endless Next-loop)
  * dry_run stops at the final screen and discards: you can watch everything
    work with zero risk
  * every failure keeps a screenshot named after the job for debugging
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from ...core.context import AppContext
from ...domain.models import ApplyResult, Job
from ...exceptions import DailyLimitReached
from ..helpers import find_first, page_text_contains, pause, safe_click
from . import forms
from . import selectors as S

log = logging.getLogger(__name__)
MAX_STEPS = 12          # an Easy Apply flow is normally 2-6 steps


class EasyApplier:
    def __init__(self, ctx: AppContext):
        self.ctx, self.driver = ctx, ctx.driver

    # ----------------------------------------------------------------- api
    def apply(self, job: Job, resume_path: str = "") -> ApplyResult:
        d = self.driver
        button = find_first(d, S.EASY_APPLY_BUTTON, timeout=2)
        if button is None:
            return self._external(job)
        if not safe_click(d, button):
            return ApplyResult("failed", "could not click Easy Apply")
        modal = find_first(d, S.MODAL, timeout=6)
        if modal is None:
            self._check_limit()
            return ApplyResult("failed", "Easy Apply modal did not open")
        try:
            return self._run_modal(job, modal, resume_path)
        except DailyLimitReached:
            raise
        except Exception as exc:                       # anything unexpected: record, clean up, move on
            log.exception("easy apply crashed for %s", job.job_id)
            self._screenshot(job, "crash")
            self.discard()
            return ApplyResult("failed", f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------- internals
    def _run_modal(self, job: Job, modal, resume_path: str) -> ApplyResult:
        d, cfg = self.driver, self.ctx.settings.apply
        used_resume = ""
        last_signature, repeats = None, 0

        for _step in range(MAX_STEPS):
            pause(0.5, 1.1)
            pending = self._answer_step(job, modal)
            if pending:                                        # required + unanswerable
                self._screenshot(job, "needs-review")
                self.discard()
                return ApplyResult("needs_review", "unanswered: " + "; ".join(pending[:3]), used_resume, pending=pending)

            if resume_path and forms.upload_resume(modal, resume_path):
                used_resume = Path(resume_path).name

            submit = find_first(modal, S.SUBMIT_BUTTON)
            if submit is not None:
                return self._finish(job, modal, submit, used_resume)

            nxt = find_first(modal, S.REVIEW_BUTTON) or find_first(modal, S.NEXT_BUTTON)
            if nxt is None:
                self._screenshot(job, "no-next")
                self.discard()
                return ApplyResult("failed", "no Next/Review/Submit button found", used_resume)
            safe_click(d, nxt)
            pause(0.8, 1.5)

            errors = [forms.text_of(e) for e in _errors(modal)]
            signature = tuple(f.label for f in forms.read_fields(modal))
            repeats = repeats + 1 if (errors and signature == last_signature) else 0
            last_signature = signature
            if repeats >= 1:                                   # same step, still erroring: give up cleanly
                self._screenshot(job, "validation")
                self.discard()
                return ApplyResult("failed", "validation error: " + "; ".join(errors[:2]), used_resume)
        self.discard()
        return ApplyResult("failed", f"more than {MAX_STEPS} steps", used_resume)

    def _answer_step(self, job: Job, modal) -> list[str]:
        """Fill every field on the current step. Returns labels of REQUIRED fields we could not answer."""
        pending: list[str] = []
        overwrite = self.ctx.settings.apply.overwrite_prefilled
        for f in forms.read_fields(modal):
            if forms.is_prefilled(f) and not overwrite:
                continue                                       # keep LinkedIn's pre-filled values
            answer = self.ctx.engine.resolve(f, job)
            if answer is None:
                if f.required or f.kind == "radio":
                    pending.append(f.label)
                continue
            if not forms.fill_field(self.driver, f, answer.value) and f.required:
                pending.append(f.label)
        return pending

    def _finish(self, job: Job, modal, submit_btn, resume: str) -> ApplyResult:
        d = self.driver
        if self.ctx.settings.apply.unfollow_company:
            box = find_first(modal, S.FOLLOW_CHECKBOX)
            if box is not None and box.is_selected():
                lab = find_first(modal, S.FOLLOW_CHECKBOX_LABEL)
                if lab is not None:
                    safe_click(d, lab)
        if self.ctx.dry_run:
            log.info("[dry-run] would submit %s | %s", job.title, job.company)
            self.discard()
            return ApplyResult("dry_run_ok", "dry run: stopped at final screen", resume)
        safe_click(d, submit_btn)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if any(page_text_contains(d, t) for t in S.SUCCESS_TEXTS):
                done = find_first(d, S.DONE_BUTTON) or find_first(d, S.DISMISS_BUTTON)
                if done is not None:
                    safe_click(d, done)
                return ApplyResult("applied", "", resume)
            time.sleep(0.5)
        self._check_limit()
        self._screenshot(job, "submit-unverified")
        return ApplyResult("failed", "submit clicked but success was not confirmed", resume)

    def _external(self, job: Job) -> ApplyResult:
        """No Easy Apply: record the external application URL (opened in a new tab)."""
        d = self.driver
        btn = find_first(d, S.ANY_APPLY_BUTTON, timeout=1)
        if btn is None:
            return ApplyResult("external", "no apply button")
        origin, before = d.current_window_handle, set(d.window_handles)
        try:
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
        """Close the modal and confirm 'Discard' so no half-finished draft lingers."""
        d = self.driver
        try:
            d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            pause(0.4, 0.8)
            confirm = find_first(d, S.DISCARD_CONFIRM, timeout=1.5)
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


def _errors(modal) -> list:
    return modal.find_elements(*S.FIELD_ERRORS[0])
