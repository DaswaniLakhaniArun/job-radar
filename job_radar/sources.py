"""Job sources: LinkedIn and Indeed (via JobSpy), Remotive and Adzuna."""
from __future__ import annotations

import logging
import math
import os
import random
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import requests

from .models import Job

log = logging.getLogger(__name__)
TIMEOUT = 30


def _clean(value) -> str:
    """JobSpy returns NaN for empty cells; turn anything empty into ''."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _as_date(value) -> date | None:
    if value is None or _clean(value) == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


# ---------------------------------------------------------------- JobSpy ---

def jobspy_jobs(cfg: dict, errors: list[str]) -> Iterable[Job]:
    from jobspy import scrape_jobs  # imported lazily: heavy dependency

    s = cfg["searches"]
    for loc in s["locations"]:
        spanish = loc.get("indeed_country") == "spain"
        terms = list(s["terms"]) + (list(cfg.get("spanish_terms", [])) if spanish else [])
        for term in terms:
            for site in s["sites"]:
                if site == "indeed" and not loc.get("indeed_country"):
                    continue
                label = f"{term} · {loc['name']}"
                try:
                    df = scrape_jobs(
                        site_name=[site],
                        search_term=term,
                        location=loc["query"],
                        is_remote=bool(loc.get("remote", False)),
                        results_wanted=s.get("results_per_search", 20),
                        hours_old=cfg.get("hours_old", 168),
                        country_indeed=loc.get("indeed_country", "usa"),
                        fetch_description=bool(s.get("linkedin_descriptions")) if site == "linkedin" else False,
                        verbose=0,
                    )
                except Exception as exc:  # one failing search must not stop the run
                    errors.append(f"{site} · {label}: {exc}")
                    log.warning("search failed: %s %s: %s", site, label, exc)
                    continue

                for site_name, site_error in (df.attrs.get("errors") or {}).items():
                    errors.append(f"{site_name} · {label}: {site_error}")

                for row in df.to_dict("records"):
                    salary = ""
                    if _clean(row.get("min_amount")):
                        salary = f"{_clean(row.get('min_amount'))}–{_clean(row.get('max_amount'))} {_clean(row.get('currency'))}/{_clean(row.get('interval'))}"
                    yield Job(
                        source=_clean(row.get("site")) or site,
                        title=_clean(row.get("title")),
                        company=_clean(row.get("company")),
                        location=_clean(row.get("location")) or loc["name"],
                        url=_clean(row.get("job_url_direct")) or _clean(row.get("job_url")),
                        description=_clean(row.get("description")),
                        date_posted=_as_date(row.get("date_posted")),
                        is_remote=bool(row.get("is_remote")) if _clean(row.get("is_remote")) else loc.get("remote"),
                        salary=salary or None,
                        search_label=label,
                    )
                # be polite: LinkedIn starts answering 429 if searches come too fast
                time.sleep(random.uniform(8, 14) if site == "linkedin" else random.uniform(2, 4))


# -------------------------------------------------------------- Remotive ---

def remotive_jobs(cfg: dict, errors: list[str]) -> Iterable[Job]:
    rc = cfg.get("remotive", {})
    if not rc.get("enabled"):
        return
    since = datetime.now(timezone.utc) - timedelta(hours=cfg.get("hours_old", 168))
    for category in rc.get("categories", []):
        try:
            resp = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"category": category},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get("jobs", [])
        except Exception as exc:
            errors.append(f"remotive · {category}: {exc}")
            continue
        for item in data:
            published = item.get("publication_date") or ""
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < since:
                    continue
            except ValueError:
                pub_dt = None
            yield Job(
                source="remotive",
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location") or "Remote",
                url=item.get("url", ""),
                description=item.get("description", ""),
                date_posted=pub_dt.date() if pub_dt else None,
                is_remote=True,
                salary=item.get("salary") or None,
                search_label=f"Remotive · {category}",
            )
        time.sleep(31)  # Remotive blocks more than 2 requests per minute


# ---------------------------------------------------------------- Adzuna ---

def adzuna_jobs(cfg: dict, errors: list[str]) -> Iterable[Job]:
    ac = cfg.get("adzuna", {})
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not ac.get("enabled") or not app_id or not app_key:
        return
    max_days = max(1, round(cfg.get("hours_old", 168) / 24))
    for country in ac.get("countries", []):
        for term in ac.get("terms", []):
            try:
                resp = requests.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "what": term,
                        "results_per_page": 50,
                        "max_days_old": max_days,
                        "content-type": "application/json",
                    },
                    timeout=TIMEOUT,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
            except Exception as exc:
                # never put the URL in the error: it contains the API key
                errors.append(f"adzuna · {country} · {term}: {type(exc).__name__}")
                continue
            for item in results:
                salary = None
                if item.get("salary_min"):
                    salary = f"{item.get('salary_min')}–{item.get('salary_max')} (Adzuna)"
                yield Job(
                    source="adzuna",
                    title=item.get("title", ""),
                    company=(item.get("company") or {}).get("display_name", ""),
                    location=(item.get("location") or {}).get("display_name", country.upper()),
                    url=item.get("redirect_url", ""),
                    description=item.get("description", ""),
                    date_posted=_as_date(item.get("created")),
                    is_remote=None,
                    salary=salary,
                    search_label=f"Adzuna · {term} · {country}",
                )
            time.sleep(1)


def collect(cfg: dict, errors: list[str], only: set[str] | None = None) -> list[Job]:
    """Run every enabled source; `only` limits the run to some sources (used in tests and dry runs)."""
    sources = {"jobspy": jobspy_jobs, "remotive": remotive_jobs, "adzuna": adzuna_jobs}
    jobs: list[Job] = []
    for name, fn in sources.items():
        if only and name not in only:
            continue
        before = len(jobs)
        jobs.extend(j for j in fn(cfg, errors) if j.title and j.url)
        log.info("%s: %d offers", name, len(jobs) - before)
    return jobs
