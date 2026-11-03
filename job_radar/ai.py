"""Short summaries and an assessment of each finalist with Gemini (free tier).

Only the public text of the job posting is sent, never personal data.
Without GEMINI_API_KEY, or if the quota runs out, the email simply goes without summaries.
"""
from __future__ import annotations

import json
import logging
import os
import time

import requests

from .models import Job

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """Eres un asistente que analiza ofertas de empleo para un candidato junior de cloud y DevOps.
Perfil del candidato (solo para valorar el encaje): {profile}

Para CADA oferta devuelve un objeto JSON con estas claves, usando SOLO lo que dice el texto (si algo no aparece, pon "No indicado"; no inventes nada):
- "id": el id de la oferta, tal cual
- "resumen": 2 frases en español: qué haría la persona y qué tipo de empresa es
- "modalidad": "Remoto", "Híbrido", "Presencial" o "No indicado"
- "ubicacion": ciudad y país
- "duracion": duración si son prácticas o contrato temporal, si no "No indicado"
- "remunerada": "Sí", "No" o "No indicado"
- "sueldo": sueldo o beca si el texto lo menciona, si no ""
- "requisitos": lista de hasta 4 requisitos clave, muy cortos
- "a_favor": lista de hasta 3 puntos positivos concretos (formación, mentoría, tecnologías, remoto…)
- "alertas": lista de hasta 3 señales de alerta concretas (prácticas sin pagar, pide experiencia senior, descripción vaga, intermediaria…). Lista vacía si no hay
- "valoracion": entero 1-5, calidad de la oferta para alguien junior
- "encaje": entero 1-5, encaje con el perfil del candidato

Devuelve SOLO un array JSON con un objeto por oferta.

OFERTAS:
{jobs}"""


def _payload(jobs: list[Job]) -> str:
    items = []
    for j in jobs:
        items.append(json.dumps({
            "id": j.key,
            "titulo": j.title,
            "empresa": j.company,
            "ubicacion": j.location,
            "texto": (j.description or "(sin descripción)")[:3500],
        }, ensure_ascii=False))
    return "\n".join(items)


def _call(model: str, key: str, prompt: str) -> requests.Response:
    return requests.post(
        API.format(model=model),
        headers={"x-goog-api-key": key, "content-type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        },
        timeout=90,
    )


def _parse(resp: requests.Response) -> list[dict]:
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)
    return parsed if isinstance(parsed, list) else [parsed]


def check(cfg: dict) -> str:
    """Tiny call used by the check-setup mode. Returns the model that answered."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("falta el secret GEMINI_API_KEY")
    last = ""
    for model in cfg.get("models", []):
        r = _call(model, key, 'Responde solo con este JSON: [{"ok": true}]')
        if r.status_code == 200:
            _parse(r)
            return model
        last = f"{model}: HTTP {r.status_code}"
    raise RuntimeError(f"Gemini no responde ({last})")


def enrich(jobs: list[Job], cfg: dict, profile: str, errors: list[str]) -> None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not cfg.get("enabled") or not key or not jobs:
        return
    models = list(cfg.get("models", []))
    batch = int(cfg.get("batch_size", 5))
    by_key = {j.key: j for j in jobs}

    for i in range(0, len(jobs), batch):
        chunk = jobs[i:i + batch]
        prompt = PROMPT.format(profile=profile, jobs=_payload(chunk))
        done = False
        while models and not done:
            model = models[0]
            try:
                r = _call(model, key, prompt)
                if r.status_code == 404:  # model name retired: try the next one
                    models.pop(0)
                    continue
                if r.status_code == 429:
                    time.sleep(40)
                    r = _call(model, key, prompt)
                if r.status_code != 200:
                    errors.append(f"gemini · {model}: HTTP {r.status_code}, el resto va sin resumen")
                    return
                for item in _parse(r):
                    job = by_key.get(str(item.get("id", "")))
                    if job:
                        job.ai = item
                done = True
            except Exception as exc:
                errors.append(f"gemini: {type(exc).__name__}")
                return
        if not models:
            errors.append("gemini: ningún modelo disponible, revisa ai.models en config.yaml")
            return
        time.sleep(float(cfg.get("pause_seconds", 5)))


def apply_to_score(jobs: list[Job]) -> None:
    """Small, explained adjustment from the AI assessment."""
    for j in jobs:
        a = j.ai or {}
        try:
            fit = int(a.get("encaje", 3))
        except (TypeError, ValueError):
            fit = 3
        if fit != 3:
            j.score = round(j.score + (fit - 3) * 0.5, 1)
            j.reasons.append(f"encaje IA {fit}/5")
        if str(a.get("remunerada", "")).strip().lower() == "no":
            j.score = round(j.score - 1, 1)
            j.reasons.append("parece no remunerada")
