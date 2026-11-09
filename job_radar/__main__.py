"""Entry point: python -m job_radar [--dry-run | --check-setup] [--sources jobspy,remotive,adzuna]"""
from __future__ import annotations

import argparse
import logging
import os
import smtplib
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from . import ai, enrich, mailer, report, state, tracker
from . import board as board_mod
from .scoring import rank, score_job
from .sources import collect

log = logging.getLogger("job_radar")


def _gh(level: str, title: str, message: str) -> None:
    """GitHub Actions annotation (visible on the run page and through the API)."""
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::{level} title={title}::{message[:300]}")


def _fail(message: str) -> None:
    log.error(message)
    _gh("error", "job-radar", message)


def _send(subject: str, html: str, text: str) -> bool:
    try:
        mailer.send(subject, html, text)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        _fail(f"Gmail rejected the login (SMTP {exc.smtp_code}). Check GMAIL_USER and that GMAIL_APP_PASSWORD is an App Password.")
    except Exception as exc:  # never print the message itself: it could echo credentials
        _fail(f"Could not send the email: {type(exc).__name__}")
    return False


def check_setup(cfg: dict) -> int:
    """Fast check of every integration (≈1 minute). Also creates the board columns and fields."""
    results: list[tuple[str, bool, str]] = []

    try:
        model = ai.check(cfg.get("ai", {}))
        results.append(("Gemini", True, f"responde ({model})"))
    except Exception as exc:
        results.append(("Gemini", False, str(exc)[:200]))

    b = board_mod.from_env(cfg.get("board", {}))
    if b is None:
        results.append(("Tablero", False, "falta el secret PROJECT_TOKEN"))
    else:
        try:
            b.connect()
            changed = b.setup()
            n = len(b.items())
            detail = f"conectado a «{b.title}» ({n} tarjetas)"
            if changed:
                detail += "; configurado: " + ", ".join(changed)
            results.append(("Tablero", True, detail))
        except Exception as exc:
            results.append(("Tablero", False, f"{type(exc).__name__}: {str(exc)[:200]}"))

    missing = mailer.missing_settings()
    if missing:
        results.append(("Email", False, "faltan los secrets " + ", ".join(missing)))
    else:
        rows = "".join(f"<li>{'✅' if ok else '❌'} <b>{n}</b>: {d}</li>" for n, ok, d in results)
        ok = _send("job-radar · comprobación de la configuración",
                   f"<p>✅ El email funciona.</p><ul>{rows}</ul>",
                   "\n".join(f"{n}: {'OK' if ok else 'ERROR'} {d}" for n, ok, d in results))
        results.append(("Email", ok, "enviado" if ok else "no se pudo enviar"))

    for name, ok, detail in results:
        _gh("notice" if ok else "error", name, detail)
        log.info("%s %s: %s", "OK " if ok else "ERR", name, detail)
    return 0 if all(ok for _, ok, _ in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly cloud/DevOps job search")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--state", default=".state/seen.json", help="what job-radar remembers between weeks")
    parser.add_argument("--dry-run", action="store_true", help="write report.html; no email, no board changes")
    parser.add_argument("--sources", help="comma-separated subset: jobspy,remotive,adzuna")
    parser.add_argument("--check-setup", "--test-email", dest="check_setup", action="store_true",
                        help="only check email, Gemini and the board")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.check_setup:
        return check_setup(cfg)

    # Check the email settings before spending 15 minutes searching.
    if not args.dry_run and mailer.missing_settings():
        _fail(f"Missing repository secrets: {', '.join(mailer.missing_settings())}")
        return 1

    today = date.today()
    only = set(args.sources.split(",")) if args.sources else None
    errors: list[str] = []
    found = collect(cfg, errors, only)
    rules = cfg["scoring"]
    ranked = rank(found, rules, cfg.get("min_score", 0))

    state_path = Path(args.state)
    st = state.load(state_path)

    # Board: read what Arun marked
    bcfg = cfg.get("board", {})
    b = board_mod.from_env(bcfg)
    items: list[board_mod.Item] = []
    if b:
        try:
            b.connect()
            if not args.dry_run:
                b.setup()
            items = b.items()
            tracker.track_statuses(items, st, today)
        except Exception as exc:
            errors.append(f"tablero: {type(exc).__name__}: {str(exc)[:150]}")
            b = None

    p = tracker.plan(ranked, found, items, st, bcfg, today)
    new = p.new[: cfg.get("max_results", 30)]
    resurfaced = p.resurfaced[:5]
    finalists = new + resurfaced

    # Enrich only the finalists
    ecfg = cfg.get("enrich", {})
    enrich.company_info(finalists, found)
    if ecfg.get("linkedin_descriptions", True):
        enrich.linkedin_descriptions(finalists, errors, limit=int(ecfg.get("max_descriptions", 40)))
    for j in finalists:  # rescore now that LinkedIn offers have a description
        notes = j.notes
        if score_job(j, rules) is not None:
            j.notes = notes
    enrich.salary_estimates(finalists, cfg.get("salary_estimates", {}))
    try:  # summaries are a bonus: they must never stop the email
        ai.enrich(finalists, cfg.get("ai", {}), cfg.get("ai", {}).get("profile", ""), errors)
        ai.apply_to_score(finalists)
    except Exception as exc:
        errors.append(f"gemini: {type(exc).__name__}, las ofertas van sin resumen")
    new.sort(key=lambda j: (j.category != "internship", -j.score))

    per_source = Counter(j.source for j in found)
    log.info("found %d, relevant %d, new %d, board cards %d, warnings %d", len(found), len(ranked), len(new), len(items), len(errors))
    _gh("notice", "Summary", f"found {len(found)} ({', '.join(f'{k} {v}' for k, v in per_source.most_common())}) · "
        f"relevant {len(ranked)} · new {len(new)} · resurfaced {len(resurfaced)} · board {len(items)} · "
        f"summaries {sum(1 for j in finalists if j.ai)}/{len(finalists)}")
    regions = Counter(next((r.split("ubicación ")[1].rsplit(" ×", 1)[0] for r in j.reasons if r.startswith("ubicación ")), "España/sin peso")
                      for j in new)
    _gh("notice", "Regions", " · ".join(f"{k} {v}" for k, v in regions.most_common()))
    # Board: add the new offers and tidy up
    if b and not args.dry_run:
        for job in new:
            try:
                job.board_url = b.add(job, board_mod.card_body(job))
            except Exception as exc:
                errors.append(f"tablero · no se pudo añadir «{job.title}»: {type(exc).__name__}: {str(exc)[:120]}")
        for it in p.archive:
            try:
                b.archive(it.id)
            except Exception as exc:
                errors.append(f"tablero · no se pudo archivar: {type(exc).__name__}")

    added = sum(1 for j in new if j.board_url)
    if b and not args.dry_run:
        _gh("notice", "Board", f"{added}/{len(new)} cards added, {len(p.archive)} archived")
    for e in errors[:10]:
        _gh("warning", "Source", e)

    extras = report.Extras(
        board_url=b.url if b else None,
        resurfaced=resurfaced,
        news=[(it.title, b.item_url(it.db_id) if b else "", msg) for it, msg in p.news],
        follow_ups=[(it.title, b.item_url(it.db_id) if b else "", d) for it, d in p.follow_ups],
    )
    html = report.build_html(new, len(found), errors, today, extras)
    text = report.build_text(new)
    interns = sum(j.category == "internship" for j in new)
    subject = f"job-radar · {len(new)} ofertas nuevas ({interns} de prácticas) · {today:%d/%m}"

    if args.dry_run:
        Path("report.html").write_text(html, encoding="utf-8")
        for j in new[:15]:
            _gh("notice", "Top", f"{j.score:g} [{j.category}] {j.title} — {j.company} ({j.location}) · {j.source}"
                + (f" · {j.ai.get('resumen', '')[:120]}" if j.ai else ""))
        log.info("dry run: report written to report.html, nothing sent")
        return 0

    if not _send(subject, html, text):
        return 1
    st.setdefault("sent", {}).update({j.key: today.isoformat() for j in new})
    tracker.update_last_seen(items, found, st, today)
    state.save(state_path, st)
    log.info("email sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
