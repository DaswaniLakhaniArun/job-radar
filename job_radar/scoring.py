"""Rule-based scoring: free, fast and explainable (every point comes with a reason)."""
from __future__ import annotations

import re
from functools import lru_cache

from .models import Job, normalise

REMOTE_OK_REGIONS = (
    "worldwide", "anywhere", "europe", "emea", "eu", "spain", "espana",
    "cet", "gmt", "utc", "global", "international",
)


# Words that say how the offer is worked. "hybrid cloud" is a technology, not a work mode, so in the
# description only phrases about the job itself count; in the title or location any mention counts.
_HYBRID_WORD = re.compile(r"(?<![a-z0-9])(hybrid|hibrido|hibrida|hibrid)(?![a-z0-9])")
_HYBRID_PHRASE = re.compile(
    r"hybrid (work|working|role|position|model|schedule|setup|arrangement|mode|environment)"
    r"|(work|working|role|position|job) (is |will be )?hybrid"
    r"|(trabajo|modalidad|modelo|puesto|jornada|regimen|esquema) (hibrid[oa])"
    r"|hibrid[oa] (\(|en |con |de )"
    r"|\d\s*(days?|dias?)\s*(a|per|/|por)\s*(week|semana)\s*(in|at|en)?\s*(the )?(office|oficina)"
)
_REMOTE_WORD = re.compile(r"(?<![a-z0-9])(remote|remoto|remota|teletrabajo|telework|teleworking|wfh)(?![a-z0-9])")
_REMOTE_PHRASE = re.compile(
    r"(fully|100%|100 %|full|totally|completamente) (remote|remoto)|remote[- ]first|work(ing)? remotely"
    r"|remote (position|role|job|work|opportunity|only)|work from home|teletrabajo|trabajo (en )?remoto"
    r"|(puesto|modalidad|posicion) (en )?remot[oa]"
)


def work_mode(job: Job) -> str:
    """'remote', 'hybrid' or 'onsite' (also used when the offer does not say)."""
    head = normalise(f"{job.title} {job.location}")
    desc = normalise(job.description)
    if _HYBRID_WORD.search(head):
        return "hybrid"
    if job.is_remote or _REMOTE_WORD.search(head):
        return "remote"
    if _HYBRID_PHRASE.search(desc):
        return "hybrid"
    if _REMOTE_PHRASE.search(desc):
        return "remote"
    return "onsite"


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


_NOT_EXPERIENCE = r"(?!\s*(?:-\s*)?(?:contract|program|programme|internship|placement|term|old|de edad|de contrato|de duracion|de beca|de practicas))"
_WORD_NUM = {"un": 1, "uno": 1, "una": 1, "one": 1, "dos": 2, "two": 2, "tres": 3, "three": 3, "cuatro": 4, "four": 4,
             "cinco": 5, "five": 5, "seis": 6, "six": 6, "siete": 7, "seven": 7, "ocho": 8, "eight": 8}
_NUM = r"(\d{1,2}|" + "|".join(_WORD_NUM) + r")"
_YEARS_NUM = r"(?<![\d,.])" + _NUM + r"\s*\+?\s*(?:(?:-|a|to)\s*\d{1,2}\s*)?-?\s*(?:years?|yrs?|anos?)(?![a-z])" + _NOT_EXPERIENCE
_SOFT = re.compile(r"\b(deseable|valorable|valorara|valorarar|preferible|preferred|nice to have|bonus|plus|ideal|opcional|optional|not required|no es necesari)")
_NOT_ABOUT_PEOPLE = re.compile(r"hace|fundad|founded|since")
_EXPERIENCE_WORD = re.compile(r"experien|experience|pide|exige|minimo|at least|required|requires|mas de|more than")


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else _WORD_NUM[token]


def _experience_years(text: str) -> tuple[int, int]:
    """Years of experience asked for in general (not tied to a technology).
    Returns (required, optional): the highest lower bound found in "must have" sentences and in "nice to have" ones."""
    hard = soft = 0
    for sentence in re.split(r"[.\n;]", text):
        if not _EXPERIENCE_WORD.search(sentence):
            continue
        for m in re.finditer(_YEARS_NUM, sentence):
            years = _to_int(m.group(1))
            if not 1 <= years < 20:
                continue
            if _NOT_ABOUT_PEOPLE.search(sentence[max(0, m.start() - 30):m.start()]):  # "hace 10 años", "founded 10 years ago"
                continue
            if _SOFT.search(sentence):
                soft = max(soft, years)
            else:
                hard = max(hard, years)
    return hard, soft


def _tech_years(text: str, skills) -> list[tuple[int, str]]:
    """Offers that ask for years of experience *with a specific technology* ("1+ year of AWS").
    Arun has months of professional experience, so any such requirement of one year or more is a mismatch."""
    found: dict[str, int] = {}
    for skill in skills:
        sk = re.escape(normalise(skill))
        after = re.compile(_YEARS_NUM + rf"[^.\n;:]{{0,70}}?(?<![a-z0-9]){sk}(?![a-z0-9])")
        before = re.compile(rf"(?<![a-z0-9]){sk}(?![a-z0-9])[^.\n;]{{0,40}}?" + _YEARS_NUM)
        for rx in (after, before):
            for m in rx.finditer(text):
                if _SOFT.search(m.group(0)):
                    continue
                years = _to_int(m.group(1))
                if 1 <= years < 20:
                    found[skill] = min(years, found.get(skill, years))
    return [(y, s) for s, y in found.items()]


def experience_problems(text: str, skills) -> list[str]:
    """Reasons why the text asks for experience Arun doesn't have (empty list = nothing found)."""
    text = normalise(text)
    out: list[str] = []
    tech = _tech_years(text, skills)
    if tech:
        out.append("pide años de experiencia en: " + ", ".join(f"{s} ({y}+)" for y, s in tech))
    hard, _ = _experience_years(text)
    if hard >= 2 and not tech:
        out.append(f"pide {hard}+ años de experiencia")
    return out


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

    job.blocked = False
    problems = experience_problems(desc, rules["skills"])
    if problems:
        job.blocked = True
        score -= 5
        reasons.extend(problems)
    else:
        one_year, _ = _experience_years(normalise(desc))
        if one_year == 1:  # close to what Arun has (about nine months): lower it, don't drop it
            score -= 1.5
            reasons.append("pide 1 año de experiencia")
    if not problems and len(desc) < 200:
        reasons.append("sin descripción completa: mira los requisitos en el anuncio")

    langs = _found(rules.get("language_penalties", []), desc)
    if langs:
        score -= 2
        reasons.append("idioma requerido: " + ", ".join(langs))

    mode = work_mode(job)
    job.work_mode = mode
    if job.is_remote:
        loc = normalise(job.location)
        if job.source == "remotive" and loc and not any(r in loc for r in REMOTE_OK_REGIONS):
            score -= 3
            reasons.append(f"remoto solo para: {job.location}")
            mode = ""  # not really open to Arun: no remote bonus
    bonus = float(rules.get("work_mode_bonus", {}).get(mode, 0)) if mode else 0.0
    if bonus:
        score += bonus
    if mode:
        reasons.append({"remote": "remoto", "hybrid": "híbrido", "onsite": "presencial (no indica remoto ni híbrido)"}[mode])

    weight, region = location_weight(job.location, rules.get("location_weights"))
    if weight != 1.0:
        score *= weight
        reasons.append(f"ubicación {region} ×{weight:g}")

    job.score = round(score, 1)
    job.reasons = reasons
    return job


def location_weight(location: str, cfg: dict | None) -> tuple[float, str]:
    """Multiplier for where the job is (first matching region wins)."""
    if not cfg:
        return 1.0, ""
    loc = normalise(location)
    for region in cfg.get("regions", []):
        if _found(region["match"], loc):
            return float(region["weight"]), region["name"]
    return float(cfg.get("default", 1.0)), "sin identificar"


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
