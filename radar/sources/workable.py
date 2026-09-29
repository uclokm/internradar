"""Workable career pages (apply.workable.com/<account>).

  POST https://apply.workable.com/api/v3/accounts/<account>/jobs      (list)
  GET  https://apply.workable.com/api/v2/accounts/<account>/jobs/<shortcode>  (detail)
"""
from __future__ import annotations

from datetime import datetime

from ..models import RawJob
from .http import html_to_text, request

LIST = "https://apply.workable.com/api/v3/accounts/{account}/jobs"
DETAIL = "https://apply.workable.com/api/v2/accounts/{account}/jobs/{shortcode}"


def parse_list(payload: dict, location: str = "Singapore") -> list[dict]:
    keep = []
    for j in payload.get("results", []) or []:
        locs = [j.get("location") or {}] + (j.get("locations") or [])
        if any(location.lower() in f"{l.get('country','')} {l.get('city','')}".lower() for l in locs):
            keep.append(j)
    return keep


def parse_detail(d: dict, cfg: dict) -> RawJob:
    loc = d.get("location") or {}
    text = "\n".join(html_to_text(d.get(k, "")) for k in ("description", "requirements", "benefits"))
    pub = d.get("published")
    return RawJob(
        source="workable", external_id=f"{cfg['account']}-{d['shortcode']}", company=cfg["company"],
        title=d.get("title", ""), url=f"https://apply.workable.com/{cfg['account']}/j/{d['shortcode']}/",
        location=", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
        department=" ".join(d.get("department") or []),
        posted=datetime.fromisoformat(pub.replace("Z", "+00:00")).date() if pub else None,
        description=text,
    )


def fetch(cfg: dict, location: str = "Singapore", is_candidate=None) -> list[RawJob]:
    body = {"query": "intern", "location": [], "department": [], "worktype": [], "remote": []}
    results, token = [], None
    for _ in range(5):
        payload = request("POST", LIST.format(**cfg), json={**body, **({"token": token} if token else {})}).json()
        results += parse_list(payload, location)
        token = payload.get("nextPage")
        if not token:
            break
    out = []
    for j in results:
        if is_candidate and not is_candidate(j.get("title", "")):
            continue
        d = request("GET", DETAIL.format(account=cfg["account"], shortcode=j["shortcode"])).json()
        out.append(parse_detail(d, cfg))
    return out


def probe(cfg: dict) -> int:
    """Health check: total postings matching "intern" on the account."""
    body = {"query": "intern", "location": [], "department": [], "worktype": [], "remote": []}
    return int(request("POST", LIST.format(**cfg), json=body).json().get("total", 0))
