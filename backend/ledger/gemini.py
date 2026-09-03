"""Translates a LedgerEntry's raw factor breakdown into a plain-English
explanation for a security officer, via Google's Gemini API (2026-09-03,
per the user -- they already have a Gemini key). Never persisted: this is a
fresh, on-demand read every time, not part of the audited Ledger record.
"""

import json

import requests
from django.conf import settings

# Gemini's response latency for this prompt size varies widely in practice
# (observed 14s-30s+ for the same request back to back) -- a generous
# timeout plus one automatic retry on a timeout/connection blip (not on a
# real 4xx/5xx from Gemini) absorbs that instead of surfacing a spurious
# failure to the security officer on the first click.
GEMINI_TIMEOUT_SECONDS = 45
GEMINI_MAX_ATTEMPTS = 2


class GeminiError(Exception):
    """Raised when the explanation can't be produced -- missing API key,
    a failed request, or an unexpected response shape. The view turns this
    into a 502 with the message, rather than letting the request crash."""


def _build_prompt(entry):
    lines = [
        "You explain hospital security-access decisions to a security officer "
        "who is not a programmer. Given the raw decision data below, write a "
        "clear, plain-English explanation in 2-4 sentences: what happened, "
        "and what specifically drove that outcome (score, which factors were "
        "strong or weak, a failed behavioral-match gate, an emergency-override "
        "reason, etc). Do not repeat raw field names verbatim -- translate them.",
        "",
        f"Event type: {entry.event_type}",
        f"Staff: {entry.staff_full_name} ({entry.staff_id}, role: {entry.staff_role or 'unknown'})",
    ]
    if entry.patient_hospital_number:
        lines.append(f"Patient: {entry.patient_hospital_number}")
    lines.append("Raw decision data:")
    lines.append(json.dumps(entry.details, indent=2, default=str))
    return "\n".join(lines)


def explain_entry(entry):
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise GeminiError("AI explanations aren't configured (GEMINI_API_KEY is unset).")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": _build_prompt(entry)}]}]}

    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(url, params={"key": api_key}, json=body, timeout=GEMINI_TIMEOUT_SECONDS)
            break
        except requests.RequestException as exc:
            if attempt == GEMINI_MAX_ATTEMPTS:
                raise GeminiError(f"Couldn't reach Gemini: {exc}") from exc

    if response.status_code != 200:
        raise GeminiError(f"Gemini request failed ({response.status_code}): {response.text[:300]}")

    try:
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise GeminiError(f"Unexpected response from Gemini: {exc}") from exc
