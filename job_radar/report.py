"""Builds the weekly HTML email (inline styles, so it renders in Gmail)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html import escape

from .models import Job

SOURCE_NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "remotive": "Remotive", "adzuna": "Adzuna"}
ACCENT = "#1F4E79"


@dataclass
class Extras:
    """Board-related sections of the email."""
    board_url: str | None = None
    resurfaced: list[Job] = field(default_factory=list)
    news: list[tuple[str, str, str]] = field(default_factory=list)       # (title, url, message)
    follow_ups: list[tuple[str, str, int]] = field(default_factory=list)  # (title, url, days)


def _line(icon: str, text: str, color: str = "#555") -> str:
    return f'<div style="margin-top:4px;color:{color};font-size:13px">{icon} {text}</div>'


def _card(job: Job) -> str:
    a = job.ai or {}
    when = job.date_posted.strftime("%d/%m") if job.date_posted else "—"
    source = SOURCE_NAMES.get(job.source, job.source)
    facts = []
    for label in ("modalidad", "duracion", "remunerada"):
        v = a.get(label)
        if v and v != "No indicado":
            facts.append({"modalidad": "", "duracion": "Duración: ", "remunerada": "Remunerada: "}[label] + str(v))

    lines = []
    for note in job.notes:
        lines.append(_line("⚠️", escape(note), "#9a5b00"))
    if a.get("resumen"):
        lines.append(f'<div style="margin-top:6px;color:#222;font-size:13px">{escape(a["resumen"])}</div>')
    if facts:
        lines.append(_line("📍", escape(" · ".join(facts))))
    salary = job.salary or a.get("sueldo")
    if salary:
        lines.append(_line("💶", escape(str(salary))))
    elif job.salary_estimate:
        lines.append(_line("💶", escape(job.salary_estimate), "#777"))
    if job.company_rating:
        size = f" · {escape(job.company_size)}" if job.company_size else ""
        lines.append(_line("🏢", f"{job.company_rating:.1f}/5 en Indeed ({job.company_reviews or 0} reseñas){size}"))
    try:
        rating = int(a.get("valoracion", 0))
    except (TypeError, ValueError):
        rating = 0
    if rating:
        lines.append(_line("⭐", f"Valoración de la oferta: {'★' * rating}{'☆' * (5 - rating)}"))
    if a.get("a_favor"):
        lines.append(_line("👍", escape(" · ".join(map(str, a["a_favor"])))))
    if a.get("alertas"):
        lines.append(_line("🚩", escape(" · ".join(map(str, a["alertas"]))), "#a33"))
    if job.missing_skills:
        lines.append(_line("🧩", "No está en tu CV: " + escape(", ".join(job.missing_skills))))
    lines.append(_line("✅", escape(" · ".join(job.reasons)), "#777"))

    links = f'<a href="{escape(job.url, quote=True)}" style="color:{ACCENT}">Ver oferta</a>'
    if job.board_url:
        links += f' · <a href="{escape(job.board_url, quote=True)}" style="color:{ACCENT}">Abrir en el tablero</a>'

    return f"""
<tr><td style="padding:12px 0;border-bottom:1px solid #e5e5e5">
  <div style="font-size:15px;font-weight:600">
    <a href="{escape(job.url, quote=True)}" style="color:{ACCENT};text-decoration:none">{escape(job.title)}</a>
    <span style="float:right;background:{ACCENT};color:#fff;border-radius:10px;padding:1px 8px;font-size:12px">{job.score:g}</span>
  </div>
  <div style="color:#333">{escape(job.company or "—")} · {escape(job.location or "—")}</div>
  <div style="color:#777;font-size:12px">{source} · publicada {when}</div>
  {''.join(lines)}
  <div style="margin-top:6px;font-size:13px">{links}</div>
</td></tr>"""


def _h2(title: str) -> str:
    return f'<h2 style="font-size:17px;color:{ACCENT};margin:24px 0 4px">{title}</h2>'


def _section(title: str, jobs: list[Job], empty: str | None = "Nada nuevo esta semana.") -> str:
    if not jobs:
        return f'{_h2(title)}<p style="color:#777">{empty}</p>' if empty else ""
    rows = "".join(_card(j) for j in jobs)
    return f'{_h2(f"{title} ({len(jobs)})")}<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{rows}</table>'


def _list(title: str, rows: list[str]) -> str:
    if not rows:
        return ""
    items = "".join(f'<li style="margin:4px 0">{r}</li>' for r in rows)
    return f'{_h2(title)}<ul style="padding-left:18px;margin:4px 0">{items}</ul>'


def build_html(jobs: list[Job], total_found: int, errors: list[str], today: date | None = None,
               extras: Extras | None = None) -> str:
    today = today or date.today()
    ex = extras or Extras()
    interns = [j for j in jobs if j.category == "internship"]
    juniors = [j for j in jobs if j.category != "internship"]
    link = lambda t, u: f'<a href="{escape(u, quote=True)}" style="color:{ACCENT}">{escape(t)}</a>'

    news = _list("🔔 Novedades en ofertas que te interesan", [f"{link(t, u)}: {escape(m)}" for t, u, m in ex.news])
    follow = _list("⏰ Seguimiento", [f"{link(t, u)}: aplicaste hace {d} días sin cambios. ¿Escribes al reclutador o actualizas el estado?" for t, u, d in ex.follow_ups])

    errors_html = ""
    if errors:
        items = "".join(f"<li>{escape(e[:200])}</li>" for e in errors[:15])
        errors_html = f'<details style="margin-top:24px;color:#999;font-size:12px"><summary>Avisos de las fuentes ({len(errors)})</summary><ul>{items}</ul></details>'
    board = f' · <a href="{escape(ex.board_url, quote=True)}" style="color:{ACCENT}">Abrir el tablero</a>' if ex.board_url else ""

    return f"""<!doctype html>
<html><body style="margin:0;background:#f6f6f6">
<div style="max-width:680px;margin:0 auto;background:#fff;padding:24px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#222">
  <h1 style="font-size:20px;margin:0">job-radar · semana del {today.strftime('%d/%m/%Y')}</h1>
  <p style="color:#555;margin:6px 0 0">{len(jobs)} ofertas nuevas para ti, de {total_found} revisadas. El número de la derecha es la puntuación{board}.</p>
  {news}
  {follow}
  {_section("🎓 Prácticas", interns)}
  {_section("💼 Junior", juniors)}
  {_section("♻️ Vuelven a estar publicadas", ex.resurfaced, empty=None)}
  <p style="margin-top:24px;color:#777;font-size:12px">Los sueldos marcados como «estimado» son rangos orientativos de la zona, no datos de la oferta. Los resúmenes los genera Gemini a partir del texto de la oferta: revísala antes de aplicar. Ofertas de Remotive vía <a href="https://remotive.com">Remotive</a>.</p>
  {errors_html}
</div></body></html>"""


def build_text(jobs: list[Job]) -> str:
    lines = ["job-radar: ofertas nuevas", ""]
    for j in jobs:
        lines.append(f"[{j.score:g}] {j.title} — {j.company} ({j.location})")
        lines.append(f"    {j.url}")
    return "\n".join(lines)
