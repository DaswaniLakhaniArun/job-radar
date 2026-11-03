"""Extra information for the offers that make it into the email (only the finalists, to stay light)."""
from __future__ import annotations

import logging
import random
import re
import time

import requests

from .models import Job, company_key, normalise
from .scoring import _found

log = logging.getLogger(__name__)

LINKEDIN_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9,es;q=0.8",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def company_info(finalists: list[Job], everything: list[Job]) -> None:
    """Indeed returns the company rating, size and industry; copy them to offers of the same company from other boards."""
    known: dict[str, Job] = {}
    for j in everything:
        if j.company_rating or j.company_size or j.company_industry:
            k = company_key(j.company)
            if k and (k not in known or (j.company_reviews or 0) > (known[k].company_reviews or 0)):
                known[k] = j
    for j in finalists:
        src = known.get(company_key(j.company))
        if not src:
            continue
        j.company_rating = j.company_rating or src.company_rating
        j.company_reviews = j.company_reviews or src.company_reviews
        j.company_size = j.company_size or src.company_size
        j.company_industry = j.company_industry or src.company_industry


def linkedin_descriptions(finalists: list[Job], errors: list[str], limit: int = 40) -> None:
    """LinkedIn search results come without description; fetch it only for the finalists."""
    from bs4 import BeautifulSoup

    todo = [j for j in finalists if j.source == "linkedin" and len(j.description) < 200][:limit]
    blocked = 0
    for j in todo:
        m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d+)", j.url)
        if not m:
            continue
        try:
            r = requests.get(f"https://www.linkedin.com/jobs/view/{m.group(1)}", headers=LINKEDIN_HEADERS, timeout=30)
            if r.status_code in (403, 429):
                blocked += 1
                if blocked >= 3:  # LinkedIn is throttling us: stop and keep what we have
                    errors.append("linkedin · descripciones: demasiadas peticiones, se omiten las restantes")
                    break
                time.sleep(20)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            div = soup.find("div", class_="show-more-less-html__markup")
            if div:
                j.description = div.get_text("\n", strip=True)
            for h3 in soup.find_all("h3", class_="description__job-criteria-subheader"):
                span = h3.find_next_sibling("span", class_="description__job-criteria-text")
                label = h3.get_text(strip=True)
                if span and "Seniority" in label:
                    j.job_level = span.get_text(strip=True)
                if span and "Industries" in label and not j.company_industry:
                    j.company_industry = span.get_text(strip=True)
        except Exception as exc:
            log.warning("linkedin description %s: %s", j.url, exc)
        time.sleep(random.uniform(3, 6))


def salary_estimates(finalists: list[Job], cfg: dict) -> None:
    """Approximate range for the region and level, only when the offer doesn't publish a salary."""
    regions = cfg.get("regions", [])
    for j in finalists:
        if j.salary:
            continue
        loc = normalise(f"{j.location} {j.search_label}")
        for region in regions:
            if _found(region["match"], loc):
                value = region.get("internship" if j.category == "internship" else "junior")
                if value:
                    j.salary_estimate = f"{value} · estimado ({region['name']})"
                break
