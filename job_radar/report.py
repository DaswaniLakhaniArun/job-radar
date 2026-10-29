"""Builds the weekly HTML email (inline styles, so it renders in Gmail)."""
from __future__ import annotations

from datetime import date
from html import escape

from .models import Job

SOURCE_NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "remotive": "Remotive", "adzuna": "Adzuna"}


def _card(job: Job) -> str:
    when = job.date_posted.strftime("%d/%m") if job.date_posted else "—"
    source = SOURCE_NAMES.get(job.source, job.source)
    extra = []
    if job.salary:
        extra.append(f"💶 {escape(job.salary)}")
    if job.missing_skills:
        extra.append("🧩 No está en tu CV: " + escape(", ".join(job.missing_skills)))
    extra_html = "".join(f'<div style="margin-top:4px;color:#555">{e}</div>' for e in extra)
    return f"""
<tr><td style="padding:12px 0;border-bottom:1px solid #e5e5e5">
  <div style="font-size:15px;font-weight:600">
    <a href="{escape(job.url, quote=True)}" style="color:#1F4E79;text-decoration:none">{escape(job.title)}</a>
    <span style="float:right;background:#1F4E79;color:#fff;border-radius:10px;padding:1px 8px;font-size:12px">{job.score:g}</span>
  </div>
  <div style="color:#333">{escape(job.company or "—")} · {escape(job.location or "—")}</div>
  <div style="color:#777;font-size:12px">{source} · publicada {when}</div>
  <div style="margin-top:4px;color:#555;font-size:13px">✅ {escape(" · ".join(job.reasons))}</div>
  {extra_html}
</td></tr>"""


def _section(title: str, jobs: list[Job]) -> str:
    if not jobs:
        return f'<h2 style="font-size:17px;color:#1F4E79;margin:24px 0 4px">{title}</h2><p style="color:#777">Nada nuevo esta semana.</p>'
    rows = "".join(_card(j) for j in jobs)
    return f"""
<h2 style="font-size:17px;color:#1F4E79;margin:24px 0 4px">{title} ({len(jobs)})</h2>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{rows}</table>"""


def build_html(jobs: list[Job], total_found: int, errors: list[str], today: date | None = None) -> str:
    today = today or date.today()
    interns = [j for j in jobs if j.category == "internship"]
    juniors = [j for j in jobs if j.category != "internship"]
    errors_html = ""
    if errors:
        items = "".join(f"<li>{escape(e[:200])}</li>" for e in errors[:15])
        errors_html = f'<details style="margin-top:24px;color:#999;font-size:12px"><summary>Avisos de las fuentes ({len(errors)})</summary><ul>{items}</ul></details>'
    return f"""<!doctype html>
<html><body style="margin:0;background:#f6f6f6">
<div style="max-width:680px;margin:0 auto;background:#fff;padding:24px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#222">
  <h1 style="font-size:20px;margin:0">job-radar · semana del {today.strftime('%d/%m/%Y')}</h1>
  <p style="color:#555;margin:6px 0 0">{len(jobs)} ofertas nuevas para ti, de {total_found} revisadas. El número de la derecha es la puntuación.</p>
  {_section("🎓 Prácticas", interns)}
  {_section("💼 Junior", juniors)}
  <p style="margin-top:24px;color:#777;font-size:12px">Revisa cada oferta antes de aplicar. Ofertas de Remotive vía <a href="https://remotive.com">Remotive</a>.</p>
  {errors_html}
</div></body></html>"""


def build_text(jobs: list[Job]) -> str:
    lines = ["job-radar: ofertas nuevas", ""]
    for j in jobs:
        lines.append(f"[{j.score:g}] {j.title} — {j.company} ({j.location})")
        lines.append(f"    {j.url}")
    return "\n".join(lines)
