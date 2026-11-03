from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date


def normalise(text: str | None) -> str:
    """Lowercase, strip accents and collapse spaces, for matching and de-duplication."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def company_key(name: str | None) -> str:
    """Company name without legal suffixes, to match the same company across job boards."""
    n = normalise(name)
    n = re.sub(r"\b(s\.?l\.?u?|s\.?a\.?u?|inc|ltd|llc|gmbh|ag|plc|corp(oration)?|co|limited|group|grupo)\b\.?", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    date_posted: date | None = None
    is_remote: bool | None = None
    salary: str | None = None
    search_label: str = ""

    # Company data (Indeed returns it; LinkedIn offers are matched by company name)
    company_rating: float | None = None
    company_reviews: int | None = None
    company_size: str | None = None
    company_industry: str | None = None
    job_level: str | None = None

    # Filled in by scoring and enrichment
    score: float = 0.0
    category: str = ""  # "internship" or "junior"
    reasons: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    salary_estimate: str | None = None
    ai: dict | None = None  # summary, modality, pros, red flags... (see ai.py)
    notes: list[str] = field(default_factory=list)  # e.g. "they rejected you here on 12/01"
    board_url: str | None = None

    @property
    def key(self) -> str:
        """Stable id used to remember offers across weeks and merge duplicates across sources."""
        company = re.sub(r"[^a-z0-9]", "", normalise(self.company))
        title = re.sub(r"[^a-z0-9]", "", normalise(self.title))
        return hashlib.sha1(f"{company}|{title}".encode()).hexdigest()[:16]
