"""Private GitHub Projects board where Arun tracks each offer (Nueva → Aplicado → Entrevista…).

job-radar adds new offers as draft items (they live only in the private board, not in the public repo)
and reads back the status he sets, so it never recommends discarded offers again.
Needs a classic token with the `project` scope in the PROJECT_TOKEN secret.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import requests

from .models import Job

log = logging.getLogger(__name__)
API = "https://api.github.com/graphql"

NEW = "🆕 Nueva"
INTERESTED = "⭐ Me interesa"
APPLIED = "✉️ Aplicado"
REJECTED = "❌ Rechazado"
NOT_INTERESTED = "🚫 No me interesa"

# (name, colour, description) — the board's columns, in order
STATUSES = [
    (NEW, "GRAY", "Recién llegada en el informe"),
    (INTERESTED, "YELLOW", "Guardada: job-radar te avisa de novedades"),
    (APPLIED, "BLUE", "Candidatura enviada"),
    ("📞 Entrevista RR. HH.", "PURPLE", "Primera entrevista"),
    ("🧑‍💻 Entrevista técnica", "PURPLE", "Entrevista técnica"),
    ("📝 Prueba técnica", "PINK", "Prueba o ejercicio técnico"),
    ("🎉 Oferta", "GREEN", "Te han hecho una oferta"),
    (REJECTED, "RED", "Proceso cerrado; puedes volver a aplicar más adelante"),
    (NOT_INTERESTED, "ORANGE", "No te la vuelve a recomendar"),
]
IN_PROCESS = {s[0] for s in STATUSES[2:7]}

TEXT_FIELDS = ["Empresa", "Ubicación", "Sueldo", "Valoración empresa", "Fuente", "Enlace", "Clave"]
TYPE_FIELD = ("Tipo", [("🎓 Prácticas", "BLUE", ""), ("💼 Junior", "GREEN", "")])

FIELDS_FRAGMENT = """
fields(first: 50) { nodes {
  ... on ProjectV2FieldCommon { id name dataType }
  ... on ProjectV2SingleSelectField { id name options { id name } }
} }"""


@dataclass
class Item:
    id: str
    db_id: int | None
    archived: bool
    title: str
    values: dict[str, object] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return str(self.values.get("Status") or "")

    @property
    def key(self) -> str:
        return str(self.values.get("Clave") or "")


class Board:
    def __init__(self, token: str, owner: str, title: str):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"bearer {token}", "Accept": "application/vnd.github+json"})
        self.owner, self.title = owner, title
        self.id = self.url = None
        self.number = 0
        self.fields: dict[str, dict] = {}

    # ------------------------------------------------------------- basics --
    def gql(self, query: str, variables: dict | None = None) -> dict:
        for attempt in range(3):
            r = self.s.post(API, json={"query": query, "variables": variables or {}}, timeout=60)
            if r.status_code in (502, 503) or (r.status_code == 403 and "secondary rate" in r.text.lower()):
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            if data.get("errors"):
                raise RuntimeError("; ".join(e.get("message", "?") for e in data["errors"])[:300])
            return data["data"]
        raise RuntimeError(f"GitHub GraphQL HTTP {r.status_code}")

    def _load_fields(self, nodes: list[dict]) -> None:
        self.fields = {n["name"]: n for n in nodes if n and n.get("name")}

    def connect(self) -> None:
        q = """query($login: String!, $q: String!) { user(login: $login) { id
          projectsV2(first: 20, query: $q) { nodes { id number title url %s } } } }""" % FIELDS_FRAGMENT
        user = self.gql(q, {"login": self.owner, "q": self.title})["user"]
        match = [p for p in user["projectsV2"]["nodes"] if p["title"].strip().lower() == self.title.lower()]
        if match:
            p = match[0]
        else:
            m = """mutation($owner: ID!, $title: String!) { createProjectV2(input: {ownerId: $owner, title: $title}) {
              projectV2 { id number title url %s } } }""" % FIELDS_FRAGMENT
            p = self.gql(m, {"owner": user["id"], "title": self.title})["createProjectV2"]["projectV2"]
        self.id, self.number, self.url = p["id"], p["number"], p["url"]
        self._load_fields(p["fields"]["nodes"])

    def setup(self) -> list[str]:
        """Create the columns and fields if they don't exist yet. Returns what was changed."""
        changed = []
        status = self.fields.get("Status")
        wanted = [s[0] for s in STATUSES]
        if status and [o["name"] for o in status.get("options", [])] != wanted:
            m = """mutation($f: ID!, $opts: [ProjectV2SingleSelectFieldOptionInput!]) {
              updateProjectV2Field(input: {fieldId: $f, singleSelectOptions: $opts}) { projectV2Field {
              ... on ProjectV2SingleSelectField { id name options { id name } } } } }"""
            opts = [{"name": n, "color": c, "description": d} for n, c, d in STATUSES]
            f = self.gql(m, {"f": status["id"], "opts": opts})["updateProjectV2Field"]["projectV2Field"]
            self.fields["Status"] = f
            changed.append("columnas de estado")

        create = """mutation($p: ID!, $name: String!, $type: ProjectV2CustomFieldType!, $opts: [ProjectV2SingleSelectFieldOptionInput!]) {
          createProjectV2Field(input: {projectId: $p, name: $name, dataType: $type, singleSelectOptions: $opts}) {
          projectV2Field { ... on ProjectV2FieldCommon { id name dataType } ... on ProjectV2SingleSelectField { id name options { id name } } } } }"""
        specs = [(n, "TEXT", None) for n in TEXT_FIELDS] + [
            ("Puntuación", "NUMBER", None),
            ("Publicada", "DATE", None),
            (TYPE_FIELD[0], "SINGLE_SELECT", [{"name": n, "color": c, "description": d} for n, c, d in TYPE_FIELD[1]]),
        ]
        for name, dtype, opts in specs:
            if name in self.fields:
                continue
            f = self.gql(create, {"p": self.id, "name": name, "type": dtype, "opts": opts})
            self.fields[name] = f["createProjectV2Field"]["projectV2Field"]
            changed.append(name)
        return changed

    # -------------------------------------------------------------- items --
    def items(self) -> list[Item]:
        q = """query($p: ID!, $after: String) { node(id: $p) { ... on ProjectV2 {
          items(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes {
            id databaseId isArchived
            content { ... on DraftIssue { title } ... on Issue { title } }
            fieldValues(first: 30) { nodes {
              ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
            } } } } } } }"""
        out, after = [], None
        while True:
            data = self.gql(q, {"p": self.id, "after": after})["node"]["items"]
            for n in data["nodes"]:
                values = {}
                for v in n["fieldValues"]["nodes"]:
                    if not v or not v.get("field"):
                        continue
                    val = v.get("text", v.get("number", v.get("date", v.get("name"))))
                    values[v["field"]["name"]] = val
                out.append(Item(n["id"], n.get("databaseId"), n["isArchived"], (n.get("content") or {}).get("title", ""), values))
            if not data["pageInfo"]["hasNextPage"]:
                return out
            after = data["pageInfo"]["endCursor"]

    def item_url(self, db_id: int | None) -> str:
        return f"{self.url}?pane=issue&itemId={db_id}" if db_id else self.url

    def _option(self, field_name: str, option_name: str) -> str | None:
        for o in self.fields.get(field_name, {}).get("options", []):
            if o["name"] == option_name:
                return o["id"]
        return None

    def add(self, job: Job, body: str) -> str:
        m = """mutation($p: ID!, $t: String!, $b: String) { addProjectV2DraftIssue(input: {projectId: $p, title: $t, body: $b}) {
          projectItem { id databaseId } } }"""
        item = self.gql(m, {"p": self.id, "t": f"{job.title} — {job.company}"[:250], "b": body})["addProjectV2DraftIssue"]["projectItem"]

        values: list[tuple[str, dict]] = [
            ("Status", {"singleSelectOptionId": self._option("Status", NEW)}),
            ("Tipo", {"singleSelectOptionId": self._option("Tipo", "🎓 Prácticas" if job.category == "internship" else "💼 Junior")}),
            ("Empresa", {"text": job.company or "—"}),
            ("Ubicación", {"text": job.location or "—"}),
            ("Sueldo", {"text": job.salary or job.salary_estimate or "No indicado"}),
            ("Fuente", {"text": job.source}),
            ("Enlace", {"text": job.url}),
            ("Clave", {"text": job.key}),
            ("Puntuación", {"number": float(job.score)}),
        ]
        if job.company_rating:
            values.append(("Valoración empresa", {"text": f"{job.company_rating:.1f}/5 ({job.company_reviews or 0} reseñas)"}))
        if job.date_posted:
            values.append(("Publicada", {"date": job.date_posted.isoformat()}))
        self._set_many(item["id"], values)
        return self.item_url(item.get("databaseId"))

    def _set_many(self, item_id: str, values: list[tuple[str, dict]]) -> None:
        usable = [
            (self.fields[name]["id"], value)
            for name, value in values
            if name in self.fields and None not in value.values()
        ]
        if not usable:
            return
        variables: dict[str, object] = {"p": self.id, "i": item_id}
        decl, parts = [], []
        for n, (field_id, value) in enumerate(usable):
            variables[f"f{n}"], variables[f"v{n}"] = field_id, value
            decl.append(f"$f{n}: ID!, $v{n}: ProjectV2FieldValue!")
            parts.append(f"m{n}: updateProjectV2ItemFieldValue(input: {{projectId: $p, itemId: $i, fieldId: $f{n}, value: $v{n}}}) {{ clientMutationId }}")
        self.gql(f"mutation($p: ID!, $i: ID!, {', '.join(decl)}) {{ {' '.join(parts)} }}", variables)

    def set_text(self, item_id: str, field_name: str, text: str) -> None:
        self._set_many(item_id, [(field_name, {"text": text})])

    def archive(self, item_id: str) -> None:
        self.gql("""mutation($p: ID!, $i: ID!) { archiveProjectV2Item(input: {projectId: $p, itemId: $i}) { clientMutationId } }""",
                 {"p": self.id, "i": item_id})


def from_env(cfg: dict) -> Board | None:
    token = os.getenv("PROJECT_TOKEN", "").strip()
    owner = os.getenv("GITHUB_REPOSITORY_OWNER", "").strip() or cfg.get("owner", "")
    if not cfg.get("enabled", True) or not token or not owner:
        return None
    return Board(token, owner, cfg.get("title", "job-radar"))


def card_body(job: Job) -> str:
    """Markdown body of the board card."""
    a = job.ai or {}
    lines = [f"**[Ver la oferta]({job.url})** · {job.source} · puntuación {job.score:g}", ""]
    if a.get("resumen"):
        lines += [a["resumen"], ""]
    facts = [
        ("Modalidad", a.get("modalidad")), ("Ubicación", a.get("ubicacion") or job.location),
        ("Duración", a.get("duracion")), ("Remunerada", a.get("remunerada")),
        ("Sueldo", job.salary or a.get("sueldo") or job.salary_estimate),
    ]
    lines += [f"- **{k}:** {v}" for k, v in facts if v and v != "No indicado"]
    if job.company_rating:
        lines.append(f"- **Empresa:** {job.company_rating:.1f}/5 en Indeed ({job.company_reviews or 0} reseñas)"
                     + (f" · {job.company_size}" if job.company_size else ""))
    for title, key in (("Requisitos", "requisitos"), ("A favor", "a_favor"), ("Alertas", "alertas")):
        if a.get(key):
            lines += ["", f"**{title}**"] + [f"- {x}" for x in a[key]]
    if job.missing_skills:
        lines += ["", "**No está en tu CV:** " + ", ".join(job.missing_skills)]
    lines += ["", "_Por qué aparece: " + " · ".join(job.reasons) + "_", "", "### Notas", ""]
    return "\n".join(lines)
