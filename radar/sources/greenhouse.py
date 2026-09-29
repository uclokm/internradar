"""Greenhouse public job board API: GET /v1/boards/<token>/jobs?content=true"""
from __future__ import annotations

from datetime import datetime

from ..models import RawJob
from .http import html_to_text, request

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


def parse(payload: dict, company: str, token: str, location: str = "Singapore") -> list[RawJob]:
    out = []
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        offices = " ".join(o.get("name", "") for o in j.get("offices", []) or [])
        if location.lower() not in f"{loc} {offices}".lower():
            continue
        posted = j.get("first_published") or j.get("updated_at")
        out.append(RawJob(
            source="greenhouse", external_id=f"{token}-{j['id']}", company=company,
            title=j.get("title", ""), url=j.get("absolute_url", ""), location=loc,
            department=" ".join(d.get("name", "") for d in j.get("departments", []) or []),
            posted=datetime.fromisoformat(posted).date() if posted else None,
            description=html_to_text(j.get("content", "")),
        ))
    return out


def fetch(cfg: dict, location: str = "Singapore") -> list[RawJob]:
    r = request("GET", API.format(token=cfg["token"]))
    return parse(r.json(), cfg["company"], cfg["token"], location)


def probe(cfg: dict) -> int:
    """Health check: how many postings the board lists (any location)."""
    return len(request("GET", API.format(token=cfg["token"]).replace("?content=true", "")).json().get("jobs", []))
