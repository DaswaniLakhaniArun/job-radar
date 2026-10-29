"""Entry point: python -m job_radar [--dry-run] [--sources jobspy,remotive,adzuna]"""
from __future__ import annotations

import argparse
import logging
import os
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from . import mailer, report, state
from .scoring import rank
from .sources import collect

log = logging.getLogger("job_radar")


def _annotate(found, ranked, new, errors, dry_run: bool) -> None:
    """Short run summary as GitHub Actions annotations (visible in the run page and via the API)."""
    if not os.getenv("GITHUB_ACTIONS"):
        return
    per_source = Counter(j.source for j in found)
    by_source = ", ".join(f"{k} {v}" for k, v in per_source.most_common())
    print(f"::notice title=Summary::found {len(found)} ({by_source}) · relevant {len(ranked)} · new {len(new)}")
    for err in errors[:10]:
        print(f"::warning title=Source::{err[:180]}")
    if dry_run:
        for j in new[:15]:
            print(f"::notice title=Top::{j.score:g} [{j.category}] {j.title} — {j.company} ({j.location}) · {j.source}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly cloud/DevOps job search")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--state", default=".state/seen.json", help="offers already sent")
    parser.add_argument("--dry-run", action="store_true", help="write report.html instead of sending the email")
    parser.add_argument("--sources", help="comma-separated subset: jobspy,remotive,adzuna")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    only = set(args.sources.split(",")) if args.sources else None

    errors: list[str] = []
    found = collect(cfg, errors, only)
    ranked = rank(found, cfg["scoring"], cfg.get("min_score", 0))

    state_path = Path(args.state)
    seen = state.load(state_path)
    new = [j for j in ranked if j.key not in seen][: cfg.get("max_results", 30)]
    log.info("found %d, relevant %d, new %d, source warnings %d", len(found), len(ranked), len(new), len(errors))

    _annotate(found, ranked, new, errors, args.dry_run)

    html = report.build_html(new, len(found), errors)
    text = report.build_text(new)
    interns = sum(j.category == "internship" for j in new)
    subject = f"job-radar · {len(new)} ofertas nuevas ({interns} de prácticas) · {date.today():%d/%m}"

    if args.dry_run:
        Path("report.html").write_text(html, encoding="utf-8")
        log.info("dry run: report written to report.html, nothing sent")
        return 0

    mailer.send(subject, html, text)
    today = date.today().isoformat()
    seen.update({j.key: today for j in new})
    state.save(state_path, seen)
    log.info("email sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
