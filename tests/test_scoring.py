from datetime import date
from pathlib import Path

import yaml

from job_radar import report, state
from job_radar.models import Job
from job_radar.scoring import _years_required, rank, score_job

RULES = yaml.safe_load(Path(__file__).parents[1].joinpath("config.yaml").read_text())["scoring"]


def job(title, desc="", **kw):
    base = dict(source="linkedin", company="Acme", location="Madrid", url="https://example.com/1")
    base.update(kw)
    return Job(title=title, description=desc, **base)


def test_internship_ranks_as_internship():
    j = score_job(job("DevOps Intern", "AWS, Docker, Kubernetes and Terraform"), RULES)
    assert j.category == "internship"
    assert j.score >= 7
    assert "terraform" in j.reasons[-1]


def test_spanish_internship_with_accents():
    j = score_job(job("Prácticas Cloud Engineer"), RULES)
    assert j.category == "internship"


def test_senior_and_fullstack_are_dropped():
    assert score_job(job("Senior DevOps Engineer"), RULES) is None
    assert score_job(job("Full Stack Developer (AWS)"), RULES) is None


def test_sre_is_not_excluded_by_sr():
    j = score_job(job("SRE Junior"), RULES)
    assert j is not None and j.category == "junior"


def test_unrelated_roles_are_dropped():
    assert score_job(job("Marketing Intern"), RULES) is None


def test_experience_and_language_penalties():
    easy = score_job(job("Junior DevOps Engineer", "1 year of experience"), RULES)
    hard = score_job(job("Junior DevOps Engineer", "5+ years of experience, fluent German"), RULES)
    assert hard.score < easy.score
    assert any("German".lower() in r.lower() or "german" in r for r in hard.reasons)


def test_years_parser():
    assert _years_required("3+ years of experience") == 3
    assert _years_required("entre 2-4 anos de experiencia") == 2
    assert _years_required("candidates must be 18 years old") is None


def test_remotive_region_restriction():
    us_only = score_job(job("Junior Cloud Engineer", source="remotive", location="USA Only", is_remote=True), RULES)
    europe = score_job(job("Junior Cloud Engineer", source="remotive", location="Europe", is_remote=True), RULES)
    assert europe.score > us_only.score


def test_missing_skills_are_reported():
    j = score_job(job("DevOps Intern", "We use Helm, ArgoCD and AWS"), RULES)
    assert "helm" in j.missing_skills and "aws" not in j.missing_skills


def test_rank_merges_duplicates_and_keeps_richer_copy():
    a = job("DevOps Intern", "", source="linkedin")
    b = job("DevOps Intern", "Docker and AWS", source="indeed")
    ranked = rank([a, b], RULES, min_score=0)
    assert len(ranked) == 1 and ranked[0].source == "indeed"


def test_report_and_state(tmp_path):
    j = score_job(job("DevOps Intern", "AWS", date_posted=date(2026, 11, 2)), RULES)
    html = report.build_html([j], total_found=10, errors=["indeed: blocked"], today=date(2026, 11, 2))
    assert "DevOps Intern" in html and "Prácticas (1)" in html and "blocked" in html
    p = tmp_path / "seen.json"
    state.save(p, {j.key: date.today().isoformat(), "old": "2000-01-01"})
    loaded = state.load(p)
    assert j.key in loaded and "old" not in loaded
