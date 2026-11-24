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
    assert any("terraform" in r for r in j.reasons)


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
    state.save(p, {"sent": {j.key: date.today().isoformat(), "old": "2000-01-01"}})
    loaded = state.load(p)["sent"]
    assert j.key in loaded and "old" not in loaded


def test_state_migrates_first_version(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text('{"abc": "2026-10-29"}')
    assert state.load(p) == {"sent": {"abc": "2026-10-29"}, "board": {}, "last_seen": {}}


def test_location_weights():
    spain = score_job(job("DevOps Intern", "AWS", location="Madrid, Spain"), RULES)
    london = score_job(job("DevOps Intern", "AWS", location="London, United Kingdom"), RULES)
    usa = score_job(job("DevOps Intern", "AWS", location="Austin, TX"), RULES)
    assert spain.score > london.score > usa.score
    assert abs(london.score / spain.score - 0.85) < 0.02  # scores are rounded to one decimal
    assert any("Reino Unido" in r for r in london.reasons)


def test_ai_survives_malformed_json(monkeypatch):
    from job_radar import ai

    class R:
        status_code = 200
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '[{"id": "x",\n  , }]'}]}}]}

    monkeypatch.setattr(ai, "_call", lambda *a, **k: R())
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    errors = []
    j = job("DevOps Intern")
    ai.enrich([j], {"enabled": True, "models": ["m"]}, "perfil", errors)  # must not raise
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    ai.enrich([j], {"enabled": True, "models": ["m"]}, "perfil", errors)
    assert j.ai in (None, {}, False) or not j.ai


def test_work_mode_remote_hybrid_onsite_order():
    desc = "AWS, Docker and Terraform"
    remote = score_job(job("Junior DevOps Engineer", desc, location="Madrid, Spain", is_remote=True), RULES)
    hybrid = score_job(job("Junior DevOps Engineer (Hybrid)", desc, location="Madrid, Spain"), RULES)
    onsite = score_job(job("Junior DevOps Engineer", desc, location="Madrid, Spain"), RULES)
    assert remote.work_mode == "remote" and hybrid.work_mode == "hybrid" and onsite.work_mode == "onsite"
    assert remote.score > hybrid.score > onsite.score
    assert remote.score - hybrid.score < hybrid.score - onsite.score  # hybrid is much closer to remote


def test_hybrid_cloud_technology_is_not_a_work_mode():
    j = score_job(job("Cloud Engineer Junior", "Experience with hybrid cloud and multi-cloud"), RULES)
    assert j.work_mode == "onsite"


def test_work_mode_from_description_phrases():
    assert score_job(job("Cloud Intern", "This is a hybrid role, 3 days per week in the office"), RULES).work_mode == "hybrid"
    assert score_job(job("Cloud Intern", "Fully remote position"), RULES).work_mode == "remote"
    assert score_job(job("Prácticas Cloud", "Modalidad híbrida en Madrid"), RULES).work_mode == "hybrid"
    assert score_job(job("Prácticas Cloud", "Trabajo en remoto"), RULES).work_mode == "remote"


def test_onsite_offers_are_not_dropped():
    j = score_job(job("Junior DevOps Engineer", "AWS, Docker", location="Barcelona"), RULES)
    assert j is not None and j.score >= 4


def test_years_with_a_specific_technology_blocks_the_offer():
    cases = [
        "Minimum 1 year of experience with AWS",
        "2+ years working with Kubernetes in production",
        "AWS: 1+ years of hands-on experience",
        "Se requiere 1 año de experiencia en AWS",
        "3 years of hands-on experience in DevOps and Terraform",
    ]
    for desc in cases:
        j = score_job(job("Junior DevOps Engineer", desc), RULES)
        assert j.blocked, desc
        assert any("pide años de experiencia en" in r for r in j.reasons)


def test_other_year_mentions_do_not_block():
    cases = [
        "A 1-year contract working with AWS and Docker",
        "Paid internship of 6 months. Learn AWS. Founded 10 years ago.",
        "You must be over 18 years old. We use Terraform.",
        "1 year of experience in a technical role. AWS is a plus.",
    ]
    for desc in cases:
        j = score_job(job("Junior DevOps Engineer", desc), RULES)
        assert not j.blocked, desc


def test_general_years_of_experience_block_the_offer():
    blocked = [
        "Se requieren al menos 2 años de experiencia en sistemas.",
        "Mínimo dos años de experiencia en entornos cloud.",
        "2+ years of experience in DevOps or infrastructure.",
        "Más de 3 años de experiencia demostrable.",
        "Experiencia de 3-4 años en automatización.",
    ]
    for desc in blocked:
        j = score_job(job("Junior DevOps Engineer", desc), RULES)
        assert j.blocked, desc
        assert any("años de experiencia" in r for r in j.reasons)


def test_small_or_optional_experience_does_not_block():
    fine = [
        "Experiencia de 6 meses a 1,5 años en cloud.",
        "0-2 años de experiencia o recién graduado.",
        "Se valorarán 2 años de experiencia previa.",
        "Contrato temporal de 2 años. Prácticas en AWS.",
        "Empresa fundada hace 10 años, con experiencia en Cloud.",
    ]
    for desc in fine:
        j = score_job(job("Junior DevOps Engineer", desc + " " * 250), RULES)
        assert not j.blocked, desc


def test_one_year_of_experience_only_lowers_the_score():
    base = score_job(job("Junior DevOps Engineer", "Learn Docker."), RULES)
    one = score_job(job("Junior DevOps Engineer", "Learn Docker. 1 year of experience in IT."), RULES)
    assert not one.blocked and one.score < base.score


def test_closed_postings_are_recognised():
    from job_radar.enrich import looks_closed
    assert looks_closed("<figcaption>No longer accepting applications</figcaption>")
    assert looks_closed("Esta oferta ya no está disponible")
    assert not looks_closed("Estamos buscando un DevOps junior. Envía tu CV.")
