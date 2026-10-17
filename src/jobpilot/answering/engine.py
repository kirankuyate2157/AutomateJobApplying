"""The answer engine: ONE entry point that decides what to type for a question.

Layers, in priority order (first confident hit wins):
  1. USER bank     answers you typed once (`jobpilot answers set` or the UI)
  2. CANNED        regex -> text pairs in profile.yaml
  3. RULES         deterministic facts from the profile (see rules.py)
  4. CACHED LLM    an earlier LLM answer to the identical question
  5. LLM           profile-grounded model call (optional, free providers work)
  6. REVIEW QUEUE  nothing confident -> remember the question, return None

WHY return None instead of guessing (legacy picked random options): a wrong
answer silently damages an application; an unanswered question is surfaced in
`jobpilot answers list` and answered ONCE, then reused forever.

Every question seen is recorded (what, how answered, how often), which is the
"log all LinkedIn questions" requirement and the training data for later tuning.
"""
from __future__ import annotations

import logging
import re

from ..domain.models import Answer, FormField, Job
from ..profile.profile import Profile
from ..settings import AnswerSettings
from ..storage.db import Repository
from .llm import LLMClient, build_prompt, parse_llm_json
from .normalize import clean_label, normalize_question
from .options import best_option, real_options
from .rules import Ctx, run_rules

log = logging.getLogger(__name__)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class AnswerEngine:
    def __init__(self, repo: Repository, profile: Profile, cfg: AnswerSettings,
                 llm: LLMClient | None = None, llm_min_confidence: float = 0.7):
        self.repo, self.profile, self.cfg = repo, profile, cfg
        self.llm, self.llm_min = llm, llm_min_confidence

    # --------------------------------------------------------------- public
    def resolve(self, field: FormField, job: Job | None = None) -> Answer | None:
        label = clean_label(field.label)
        key = normalize_question(label)
        field.label = label
        answer = self._resolve(key, field, job)
        if answer is not None:
            self._record(key, field, answer.value, answer.source, answer.confidence,
                         self._status_for(answer, field))
        else:
            self._record(key, field, None, "", 0.0, "pending")
        return answer

    # ------------------------------------------------------------- internals
    def _resolve(self, key: str, field: FormField, job: Job | None) -> Answer | None:
        saved = self.repo.get_question(key)

        # 1. user-confirmed answer always wins
        if saved is not None and saved["status"] == "user" and saved["answer"]:
            if (value := self._coerce(saved["answer"], field)) is not None:
                return Answer(value, "user", 1.0)

        # 2. canned regex answers from profile.yaml
        for canned in self.profile.canned_answers:
            if re.search(canned["match"], field.label, re.I):
                if (value := self._coerce(canned["answer"], field)) is not None:
                    return Answer(value, "canned", 1.0)

        # 3. deterministic rules
        ctx = Ctx(field.label, field.kind, field.options, self.profile, job)
        hit = run_rules(ctx)
        if hit is not None:
            raw, confidence, name = hit
            if confidence >= self.cfg.min_confidence and (value := self._coerce(raw, field)) is not None:
                return Answer(value, f"rule:{name}", confidence)

        # 4. cached LLM answer
        if saved is not None and saved["status"] == "cached" and saved["answer"]:
            if (value := self._coerce(saved["answer"], field)) is not None:
                return Answer(value, "cache", float(saved["confidence"] or 0.8))

        # 5. LLM
        return self._ask_llm(key, field, job)

    def _ask_llm(self, key: str, field: FormField, job: Job | None) -> Answer | None:
        if self.llm is None:
            return None
        try:
            parsed = parse_llm_json(self.llm.complete(build_prompt(self.profile, field, job)))
        except Exception as exc:           # network/quota problems must never crash an application run
            log.warning("LLM call failed for %r: %s", field.label, exc)
            return None
        if parsed is None:
            return None
        raw, confidence = parsed
        value = self._coerce(raw, field)
        if value is None or confidence < self.llm_min:
            log.info("LLM answer rejected (conf=%.2f, valid=%s) for %r", confidence, value is not None, field.label)
            return None
        return Answer(value, "llm", confidence)

    def _status_for(self, answer: Answer, field: FormField) -> str:
        """Bank status to store: only user answers and reusable LLM answers are
        ever reused automatically; rule/canned answers are recomputed each time
        (so fixing a rule or profile value takes effect immediately)."""
        if answer.source == "user":
            return "user"
        if answer.source == "cache":
            return "cached"
        # textareas depend on the job, so only short/choice answers are safe to reuse
        if answer.source == "llm" and self.cfg.cache_llm_answers and field.kind != "textarea":
            return "cached"
        return "auto"

    def _coerce(self, raw: str, field: FormField) -> str | None:
        """Make `raw` valid for this field type, or None if it cannot be."""
        raw = str(raw).strip()
        if not raw:
            return None
        if field.kind in ("select", "radio"):
            return best_option(raw, field.options)
        if field.kind == "checkbox":
            return "Yes" if raw.lower() in ("yes", "true", "1", "checked", "y") else "No"
        if field.kind == "number":
            m = _NUMBER.search(raw.replace(",", ""))
            return m.group(0) if m else None
        return raw

    def _record(self, key: str, field: FormField, answer: str | None, source: str,
                confidence: float, status: str) -> None:
        self.repo.record_question(key, field.label, field.kind, real_options(field.options),
                                  answer, source, confidence, status)
