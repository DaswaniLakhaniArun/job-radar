"""Rule-based scoring: free, fast and explainable (every point comes with a reason)."""
from __future__ import annotations

import re
from functools import lru_cache

from .models import Job, normalise

REMOTE_OK_REGIONS = (
    "worldwide", "anywhere", "europe", "emea", "eu", "spain", "espana",
    "cet", "gmt", "utc", "global", "international",
)


@lru_cache(maxsize=None)
def _pattern(keyword: str) -> re.Pattern:
    # whole-word match: "sr" must not match "sre", "lead" must not match "leading"
    return re.compile(rf"(?<![a-z0-9]){re.escape(normalise(keyword))}(?![a-z0-9])")


def _found(keywords, text: str) -> list[str]:
    return [k for k in keywords if _pattern(k).search(text)]


_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?|anos?)(?![a-z])(?!\s+(?:old|de edad))"
)


def _years_required(text: str) -> int | None:
    nums = [int(m.group(1)) for m in _YEARS.finditer(text) if int(m.group(1)) < 20]
    return min(nums) if nums else None


def score_job(job: Job, rules: dict) -> Job | None:
    """Return the job with score and reasons, or None if it should be dropped."""
    title = normalise(job.title)
    desc = normalise(job.description)
    text = f"{title} {desc}"
    reasons: list[str] = []

    if not _found(rules["role_keywords"], title):
        return None
    if _found(rules["exclude_title"], title):
        return None

    score = 3.0
    reasons.append("rol cloud/DevOps")

    if _found(rules["internship_keywords"], title):
        job.category = "internship"
        score += 3
        reasons.append("prácticas")
    elif _found(rules["junior_keywords"], title):
        job.category = "junior"
        score += 2
        reasons.append("junior")
    elif _found(rules["internship_keywords"] + rules["junior_keywords"], desc):
        job.category = "junior"
        score += 1
        reasons.append("nivel de entrada (según la descripción)")
    else:
        job.category = "junior"
        reasons.append("nivel sin especificar")

    skills = _found(rules["skills"], text)
    if skills:
        score += min(len(skills), 5) * 0.6
        reasons.append("tecnologías: " + ", ".join(skills[:6]))
    cv = {normalise(s) for s in rules.get("cv_skills", [])}
    job.missing_skills = [s for s in skills if normalise(s) not in cv]

    years = _years_required(desc)
    if years is not None and years > rules.get("max_years_experience", 2):
        score -= min(years - rules.get("max_years_experience", 2), 4)
        reasons.append(f"pide {years}+ años de experiencia")

    langs = _found(rules.get("language_penalties", []), desc)
    if langs:
        score -= 2
        reasons.append("idioma requerido: " + ", ".join(langs))

    if job.is_remote:
        loc = normalise(job.location)
        if job.source == "remotive" and loc and not any(r in loc for r in REMOTE_OK_REGIONS):
            score -= 3
            reasons.append(f"remoto solo para: {job.location}")
        else:
            score += 1
            reasons.append("remoto")

    job.score = round(score, 1)
    job.reasons = reasons
    return job


def rank(jobs: list[Job], rules: dict, min_score: float) -> list[Job]:
    """Score, drop irrelevant offers, merge duplicates across sources and sort best first."""
    best: dict[str, Job] = {}
    for job in jobs:
        scored = score_job(job, rules)
        if scored is None or scored.score < min_score:
            continue
        current = best.get(scored.key)
        # keep the richer copy (with description) when the same offer appears twice
        if current is None or len(scored.description) > len(current.description):
            best[scored.key] = scored
    return sorted(
        best.values(),
        key=lambda j: (j.category != "internship", -j.score, -(j.date_posted.toordinal() if j.date_posted else 0)),
    )
