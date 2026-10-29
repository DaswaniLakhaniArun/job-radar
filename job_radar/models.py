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

    # Filled in by scoring
    score: float = 0.0
    category: str = ""  # "internship" or "junior"
    reasons: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable id used to remember offers across weeks and merge duplicates across sources."""
        company = re.sub(r"[^a-z0-9]", "", normalise(self.company))
        title = re.sub(r"[^a-z0-9]", "", normalise(self.title))
        return hashlib.sha1(f"{company}|{title}".encode()).hexdigest()[:16]
