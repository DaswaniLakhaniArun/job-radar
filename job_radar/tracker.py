"""Rules that connect the weekly search with what Arun marks on the board. Pure functions, easy to test."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .board import APPLIED, IN_PROCESS, INTERESTED, NEW, NOT_INTERESTED, REJECTED, Item
from .models import Job, company_key


@dataclass
class Plan:
    new: list[Job] = field(default_factory=list)            # offers to email and add to the board
    resurfaced: list[Job] = field(default_factory=list)     # rejected a while ago and published again
    news: list[tuple[Item, str]] = field(default_factory=list)       # updates on "Me interesa"
    follow_ups: list[tuple[Item, int]] = field(default_factory=list)  # applied, no change for N days
    archive: list[Item] = field(default_factory=list)       # "Nueva" left untouched too long


def _days(since: str | None, today: date) -> int:
    try:
        return (today - date.fromisoformat(since)).days if since else 0
    except ValueError:
        return 0


def track_statuses(items: list[Item], st: dict, today: date) -> None:
    """Remember since when each card has its current status (the board API doesn't keep that history)."""
    board = st.setdefault("board", {})
    for it in items:
        if not it.key:
            continue
        prev = board.get(it.key)
        if not prev or prev.get("status") != it.status:
            board[it.key] = {"status": it.status, "since": today.isoformat()}


def plan(ranked: list[Job], found: list[Job], items: list[Item], st: dict, cfg: dict, today: date) -> Plan:
    p = Plan()
    by_key = {it.key: it for it in items if it.key}
    board_state = st.get("board", {})
    sent = st.get("sent", {})
    reapply = int(cfg.get("reapply_after_days", 90))
    found_by_key = {j.key: j for j in found}

    # Company-level context for new offers
    rejected_at, open_at = {}, {}
    for it in items:
        ck = company_key(str(it.values.get("Empresa") or ""))
        if not ck:
            continue
        if it.status == REJECTED:
            rejected_at[ck] = (it.title, board_state.get(it.key, {}).get("since"))
        elif it.status in IN_PROCESS:
            open_at[ck] = it.title

    for job in ranked:
        it = by_key.get(job.key)
        if it is None:
            if job.key in sent:
                continue
            ck = company_key(job.company)
            if ck in rejected_at:
                title, since = rejected_at[ck]
                when = f" el {date.fromisoformat(since):%d/%m/%Y}" if since else ""
                job.notes.append(f"En esta empresa te rechazaron{when} («{title}»)")
            if ck in open_at:
                job.notes.append(f"Ya tienes un proceso abierto aquí («{open_at[ck]}»)")
            p.new.append(job)
        elif it.status == REJECTED:
            since = board_state.get(job.key, {}).get("since")
            if _days(since, today) >= reapply:
                job.notes.append(
                    f"Te rechazaron aquí{' el ' + date.fromisoformat(since).strftime('%d/%m/%Y') if since else ''} "
                    "y la oferta vuelve a estar publicada. ¿Vuelves a aplicar?"
                )
                p.resurfaced.append(job)
        # NOT_INTERESTED and every other status: never recommended again

    for it in items:
        if it.archived or not it.key:
            continue
        since = board_state.get(it.key, {}).get("since")
        if it.status == INTERESTED:
            j = found_by_key.get(it.key)
            if j is not None:
                board_salary = str(it.values.get("Sueldo") or "")
                if j.salary and (not board_salary or board_salary == "No indicado" or "estimado" in board_salary):
                    p.news.append((it, f"Ahora publica sueldo: {j.salary}"))
                published = str(it.values.get("Publicada") or "")
                if j.date_posted and published and j.date_posted.isoformat() > published:
                    p.news.append((it, f"Se ha vuelto a publicar el {j.date_posted:%d/%m}"))
            else:
                last = st.get("last_seen", {}).get(it.key) or since
                if _days(last, today) >= int(cfg.get("stale_after_days", 21)):
                    p.news.append((it, "No la he vuelto a ver en las búsquedas: puede que ya no esté abierta"))
        elif it.status == APPLIED:
            days = _days(since, today)
            if days >= int(cfg.get("follow_up_after_days", 14)):
                p.follow_ups.append((it, days))
        elif it.status == NEW:
            if _days(since, today) >= int(cfg.get("archive_new_after_days", 21)):
                p.archive.append(it)
    return p


def update_last_seen(items: list[Item], found: list[Job], st: dict, today: date) -> None:
    keys = {it.key for it in items if it.key}
    seen = st.setdefault("last_seen", {})
    for j in found:
        if j.key in keys:
            seen[j.key] = today.isoformat()
    for k in list(seen):
        if k not in keys:
            del seen[k]


__all__ = ["Plan", "plan", "track_statuses", "update_last_seen", "NOT_INTERESTED"]
