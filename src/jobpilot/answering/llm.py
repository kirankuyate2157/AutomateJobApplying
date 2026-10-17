"""LLM providers behind one tiny interface.

WHY plain `requests` instead of vendor SDKs: one dependency covers Gemini,
OpenAI and every OpenAI-compatible server (Groq, OpenRouter, Ollama, LM Studio),
so switching to a FREE provider is a config change, not a code change.

The LLM is the LAST resort (after bank, canned answers and rules) and is told
it may only use facts from the profile, so it cannot invent employers/degrees.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Protocol

import requests

from ..domain.models import FormField, Job
from ..profile.profile import Profile
from ..settings import LLMSettings, env

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class GeminiClient:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, cfg: LLMSettings):
        self.cfg, self.key = cfg, env(cfg.api_key_env)

    def complete(self, prompt: str) -> str:
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}}
        data = _post_with_retry(self.URL.format(model=self.cfg.model), body,
                                {"x-goog-api-key": self.key}, self.cfg)
        return data["candidates"][0]["content"]["parts"][0]["text"]


class OpenAICompatClient:
    def __init__(self, cfg: LLMSettings):
        self.cfg, self.key = cfg, env(cfg.api_key_env)

    def complete(self, prompt: str) -> str:
        body = {"model": self.cfg.model, "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}]}
        data = _post_with_retry(self.cfg.base_url.rstrip("/") + "/chat/completions", body,
                                {"Authorization": f"Bearer {self.key}"}, self.cfg)
        return data["choices"][0]["message"]["content"]


def _post_with_retry(url: str, body: dict, headers: dict, cfg: LLMSettings) -> dict:
    last: Exception | None = None
    for attempt in range(cfg.max_retries + 1):
        try:
            r = requests.post(url, json=body, headers=headers, timeout=cfg.timeout_s)
            if r.status_code == 429 or r.status_code >= 500:     # rate limited / server hiccup
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))                      # simple linear backoff
    raise RuntimeError(f"LLM request failed after retries: {last}")


def make_llm(cfg: LLMSettings) -> LLMClient | None:
    """Factory. Returns None when the LLM is disabled or its key is missing."""
    if cfg.provider == "none":
        return None
    if cfg.provider not in ("gemini", "openai"):
        raise ValueError(f"unknown llm.provider {cfg.provider!r} (none|gemini|openai)")
    if not env(cfg.api_key_env):
        log.warning("llm.provider=%s but env %s is empty: LLM disabled", cfg.provider, cfg.api_key_env)
        return None
    return GeminiClient(cfg) if cfg.provider == "gemini" else OpenAICompatClient(cfg)


# ------------------------------------------------------------------ prompts --
PROMPT = """You are filling a job application form on behalf of the candidate below.
Use ONLY facts from the CANDIDATE section. Never invent employers, degrees, skills or numbers.
If the candidate data does not contain the answer, set "confidence" to 0.2 or lower.

Rules for "answer":
- Yes/No question -> exactly "Yes" or "No".
- Question with OPTIONS -> exactly one of the options, copied verbatim.
- Numeric question (years, salary, count) -> digits only (decimals allowed), no text.
- Free text -> first person, professional, at most {max_chars} characters.
Return ONLY JSON: {{"answer": "...", "confidence": 0.0-1.0}}

CANDIDATE:
{profile}

{job_block}QUESTION: {label}
FIELD TYPE: {kind}
{options_block}"""


def build_prompt(profile: Profile, field: FormField, job: Job | None) -> str:
    job_block = ""
    if job is not None:
        job_block = f"JOB: {job.title} at {job.company} ({job.location})\n{job.description[:1500]}\n\n"
    options = [o for o in field.options if o.strip()]
    return PROMPT.format(
        max_chars=600 if field.kind == "textarea" else 120, profile=profile.llm_context(),
        job_block=job_block, label=field.label, kind=field.kind,
        options_block=("OPTIONS: " + " | ".join(options) + "\n") if options else "")


def parse_llm_json(text: str) -> tuple[str, float] | None:
    """Tolerant parser: strips markdown fences and extra prose around the JSON."""
    text = re.sub(r"```(?:json)?", "", text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        answer = str(obj.get("answer", "")).strip()
        conf = float(obj.get("confidence", 0))
    except (ValueError, TypeError):
        return None
    return (answer, max(0.0, min(1.0, conf))) if answer else None
