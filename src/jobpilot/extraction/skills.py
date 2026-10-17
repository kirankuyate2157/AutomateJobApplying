"""Skill vocabulary + extraction from free text (job descriptions, questions).

WHY a local vocabulary instead of asking an LLM for every job: it is instant,
free, deterministic and works offline. The LLM stays reserved for questions
rules cannot answer.

HOW TO EXTEND: add a canonical name with its aliases to SKILLS. The canonical
name (lowercase) is what profile.yaml `skills:` must use.
"""
from __future__ import annotations

import re
from functools import lru_cache

# canonical -> aliases (all matched case-insensitively, as whole tokens)
SKILLS: dict[str, list[str]] = {
    "python": ["python", "python3"], "java": ["java"], "javascript": ["javascript", "js", "es6"],
    "typescript": ["typescript", "ts"], "c++": ["c++", "cpp"], "c#": ["c#", "csharp"],
    "golang": ["golang"], "php": ["php"], "ruby": ["ruby", "rails", "ruby on rails"],
    "kotlin": ["kotlin"], "swift": ["swift"], "ios": ["ios"], "android": ["android"],
    ".net": [".net", "dotnet", "asp.net"],
    "node.js": ["node.js", "nodejs", "node js", "node"], "express": ["express", "express.js", "expressjs"],
    "react": ["react", "reactjs", "react.js"], "next.js": ["next.js", "nextjs", "next js"],
    "vue": ["vue", "vue.js", "vuejs"], "angular": ["angular", "angularjs"],
    "django": ["django"], "flask": ["flask"], "fastapi": ["fastapi", "fast api"],
    "spring boot": ["spring boot", "springboot", "spring"], "graphql": ["graphql"],
    "rest": ["rest", "restful", "rest api", "rest apis", "restful api", "restful apis"],
    "microservices": ["microservices", "microservice"], "celery": ["celery"],
    "html": ["html", "html5"], "css": ["css", "css3"], "tailwind": ["tailwind", "tailwind css", "tailwindcss"],
    "bootstrap": ["bootstrap"], "redux": ["redux"], "electron.js": ["electron", "electron.js"],
    "postgresql": ["postgresql", "postgres", "psql"], "mysql": ["mysql"], "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"], "sql": ["sql"], "elasticsearch": ["elasticsearch", "elastic search"],
    "firebase": ["firebase"], "dynamodb": ["dynamodb"], "kafka": ["kafka"],
    "rabbitmq": ["rabbitmq", "rabbit mq"],
    "aws": ["aws", "amazon web services", "ec2", "s3", "lambda"], "azure": ["azure"],
    "gcp": ["gcp", "google cloud"], "docker": ["docker"], "kubernetes": ["kubernetes", "k8s"],
    "terraform": ["terraform"], "ansible": ["ansible"], "jenkins": ["jenkins"],
    "ci/cd": ["ci/cd", "cicd", "ci cd", "github actions", "gitlab ci"], "git": ["git", "github", "gitlab"],
    "linux": ["linux", "ubuntu"], "nginx": ["nginx"],
    "machine learning": ["machine learning", "ml"], "nlp": ["nlp"], "opencv": ["opencv"],
    "tensorflow": ["tensorflow"], "pytorch": ["pytorch"], "llm": ["llm", "llms", "genai", "generative ai"],
    "rag": ["rag"], "selenium": ["selenium"], "pandas": ["pandas"], "numpy": ["numpy"],
    "agile": ["agile", "scrum", "kanban"], "system design": ["system design", "hld", "lld"],
}

# words that mean "software experience in general" (used for generic year questions)
GENERIC_EXPERIENCE_WORDS = (
    "software", "development", "developer", "engineering", "engineer", "programming", "coding",
    "web", "backend", "back-end", "back end", "full stack", "full-stack", "fullstack", "it industry",
    "industry", "total", "overall", "relevant", "professional", "work experience", "technical",
)


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, re.Pattern[str]]]:
    """One regex per canonical skill.

    The lookarounds replace \\b because skills like 'c++', '.net' and 'c#'
    contain symbols where \\b misbehaves; they also stop 'java' matching
    inside 'javascript'.
    """
    out = []
    for canonical, aliases in SKILLS.items():
        alts = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
        out.append((canonical, re.compile(rf"(?<![\w+#.]){'(?:' + alts + ')'}(?![\w+#]|\.\w)", re.I)))
    return out


def find_skills(text: str) -> list[str]:
    """Canonical skills mentioned in `text`, ordered by first occurrence."""
    hits: list[tuple[int, str]] = []
    for canonical, rx in _compiled():
        m = rx.search(text or "")
        if m:
            hits.append((m.start(), canonical))
    return [c for _, c in sorted(hits)]


def extract_skills(text: str) -> set[str]:
    return set(find_skills(text))


_YEARS = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:[-–to]+\s*(\d{1,2})\s*)?(?:\+\s*)?(?:years?|yrs?)", re.I)


def required_years(text: str) -> tuple[float | None, float | None]:
    """Headline experience requirement as (min, max), e.g. '3-5 years' -> (3, 5).

    WHY the FIRST match: job posts state the overall requirement first
    ("3-5 years overall; 2+ years in Python"). The legacy bot took the max of
    all numbers, which wrongly rejected jobs for a secondary '8 years' phrase.
    Only matches that sit near the word 'experience' count.
    """
    for m in _YEARS.finditer(text or ""):
        window = (text[max(0, m.start() - 60): m.end() + 60]).lower()
        if "experience" in window or "exp" in window:
            lo = float(m.group(1))
            hi = float(m.group(2)) if m.group(2) else None
            if lo > 20 or (hi is not None and hi < lo):   # '2024-2025 years' style noise
                continue
            return lo, hi
    return None, None
