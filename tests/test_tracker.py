from datetime import date, timedelta
from pathlib import Path

import yaml

from job_radar import ai, enrich
from job_radar.board import APPLIED, INTERESTED, NEW, NOT_INTERESTED, REJECTED, Item, card_body
from job_radar.models import Job, company_key
from job_radar.scoring import score_job
from job_radar.tracker import plan, track_statuses, update_last_seen

CFG = yaml.safe_load(Path(__file__).parents[1].joinpath("config.yaml").read_text())
RULES, BOARD = CFG["scoring"], CFG["board"]
TODAY = date(2026, 11, 9)


def job(title="DevOps Intern", company="Acme", **kw):
    base = dict(source="linkedin", location="Madrid, Spain", url="https://example.com/1", description="AWS Docker")
    base.update(kw)
    return score_job(Job(title=title, company=company, **base), RULES)


def item(j, status, **values):
    v = {"Status": status, "Clave": j.key, "Empresa": j.company}
    v.update(values)
    return Item(id=f"item-{j.key}", db_id=1, archived=False, title=f"{j.title} — {j.company}", values=v)


def state_with(items, days_ago):
    since = (TODAY - timedelta(days=days_ago)).isoformat()
    return {"sent": {}, "board": {it.key: {"status": it.status, "since": since} for it in items}, "last_seen": {}}


def test_new_offer_is_recommended():
    j = job()
    p = plan([j], [j], [], {"sent": {}, "board": {}}, BOARD, TODAY)
    assert p.new == [j]


def test_offers_on_the_board_are_not_repeated():
    a, b, c = job("DevOps Intern A"), job("DevOps Intern B"), job("DevOps Intern C")
    items = [item(a, NOT_INTERESTED), item(b, APPLIED), item(c, NEW)]
    p = plan([a, b, c], [a, b, c], items, state_with(items, 5), BOARD, TODAY)
    assert p.new == [] and p.resurfaced == []


def test_rejected_comes_back_only_after_the_waiting_period():
    j = job()
    items = [item(j, REJECTED)]
    early = plan([j], [j], items, state_with(items, 30), BOARD, TODAY)
    late = plan([j], [j], items, state_with(items, 120), BOARD, TODAY)
    assert early.resurfaced == [] and early.new == []
    assert late.resurfaced == [j] and "vuelve a estar publicada" in j.notes[-1]


def test_not_interested_never_comes_back():
    j = job()
    items = [item(j, NOT_INTERESTED)]
    p = plan([j], [j], items, state_with(items, 400), BOARD, TODAY)
    assert p.new == [] and p.resurfaced == []


def test_company_notes_for_new_offers():
    old = job("Cloud Intern", company="Acme S.L.")
    new_offer = job("DevOps Intern", company="ACME")
    items = [item(old, REJECTED)]
    p = plan([new_offer], [new_offer], items, state_with(items, 10), BOARD, TODAY)
    assert p.new == [new_offer] and "te rechazaron" in new_offer.notes[0]


def test_interested_news_and_stale():
    j = job(salary="30.000–35.000 EUR/yearly")
    gone = job("Cloud Intern")
    items = [item(j, INTERESTED, Sueldo="26.000–34.000 €/año · estimado (Madrid/Barcelona)"), item(gone, INTERESTED)]
    p = plan([], [j], items, state_with(items, 30), BOARD, TODAY)
    msgs = {it.key: m for it, m in p.news}
    assert "sueldo" in msgs[j.key] and "puede que ya no esté abierta" in msgs[gone.key]


def test_follow_up_and_archive():
    a, n = job("DevOps Intern A"), job("DevOps Intern N")
    items = [item(a, APPLIED), item(n, NEW)]
    p = plan([], [], items, state_with(items, 22), BOARD, TODAY)
    assert [it.key for it, _ in p.follow_ups] == [a.key]
    assert [it.key for it in p.archive] == [n.key]


def test_status_history_and_last_seen():
    j = job()
    st = {"board": {j.key: {"status": NEW, "since": "2026-10-01"}}}
    track_statuses([item(j, APPLIED)], st, TODAY)
    assert st["board"][j.key] == {"status": APPLIED, "since": TODAY.isoformat()}
    track_statuses([item(j, APPLIED)], st, TODAY + timedelta(days=7))
    assert st["board"][j.key]["since"] == TODAY.isoformat()
    update_last_seen([item(j, APPLIED)], [j], st, TODAY)
    assert st["last_seen"] == {j.key: TODAY.isoformat()}


def test_company_key_ignores_legal_suffixes():
    assert company_key("Brico Depôt Iberia S.L.U.") == company_key("Brico Depot Iberia")


def test_salary_estimate_only_without_published_salary():
    intern = job(location="London, England, UK")
    paid = job("Cloud Intern", location="London, England, UK", salary="£2.300/month")
    enrich.salary_estimates([intern, paid], CFG["salary_estimates"])
    assert "estimado (Reino Unido)" in intern.salary_estimate and paid.salary_estimate is None


def test_company_rating_copied_from_indeed():
    li = job(company="Accenture")
    ind = Job(source="indeed", title="x", company="Accenture", location="", url="", company_rating=3.9, company_reviews=100)
    enrich.company_info([li], [li, ind])
    assert li.company_rating == 3.9


def test_ai_adjusts_score_and_card_body():
    j = job()
    before = j.score
    j.ai = {"resumen": "Prácticas en el equipo de plataforma.", "encaje": 5, "remunerada": "No",
            "a_favor": ["Mentoría"], "alertas": ["Sin sueldo"], "modalidad": "Híbrido"}
    ai.apply_to_score([j])
    assert abs(j.score - before) < 1e-9  # +1 for fit 5/5, -1 for unpaid
    body = card_body(j)
    assert "Prácticas en el equipo de plataforma." in body and "Mentoría" in body and "### Notas" in body
