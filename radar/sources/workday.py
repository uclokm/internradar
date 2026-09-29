"""Workday career sites (used by OCBC, Keppel, MUFG, CapitaLand, PwC...).

The public careers page loads its data from:
  POST https://<tenant>.<host>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
  GET  https://<tenant>.<host>.myworkdayjobs.com/wday/cxs/<tenant>/<site><externalPath>
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from ..models import RawJob
from .http import html_to_text, request

BASE = "https://{tenant}.{host}.myworkdayjobs.com"



def posted_on(text: str, today: date) -> date | None:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago'."""
    t = (text or "").lower()
    if "today" in t:
        return today
    if "yesterday" in t:
        return today - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*days?", t)
    return today - timedelta(days=int(m.group(1))) if m else None


def parse_list(payload: dict) -> list[dict]:
    return payload.get("jobPostings", []) or []


def parse_detail(detail: dict, cfg: dict, listing: dict, today: date) -> RawJob:
    info = detail.get("jobPostingInfo", {})
    base = BASE.format(**cfg)
    return RawJob(
        source="workday",
        external_id=f"{cfg['tenant']}-{info.get('jobReqId') or listing.get('externalPath')}",
        company=cfg["company"],
        title=info.get("title") or listing.get("title", ""),
        url=info.get("externalUrl") or f"{base}/{cfg['site']}{listing.get('externalPath', '')}",
        location=info.get("location") or listing.get("locationsText", ""),
        posted=(date.fromisoformat(info["startDate"]) if info.get("startDate") else posted_on(listing.get("postedOn", ""), today)),
        description=html_to_text(info.get("jobDescription", "")),
    )


def _is_sg(text: str, location: str) -> bool:
    return location.lower() in (text or "").lower() or "sgp" in (text or "").lower()


def fetch(cfg: dict, location: str = "Singapore", is_candidate=None, today: date | None = None,
          search: str | None = None, max_jobs: int = 200) -> list[RawJob]:
    """List postings matching `search`, keep Singapore ones that `is_candidate(title)` accepts,
    and fetch details only for those (keeps requests low)."""
    today = today or date.today()
    search = search or cfg.get("search", "intern")   # global sites use e.g. "intern singapore"
    base = BASE.format(**cfg) + f"/wday/cxs/{cfg['tenant']}/{cfg['site']}"
    listings, offset = [], 0
    while offset < max_jobs:
        r = request("POST", base + "/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search},
                    headers={"Content-Type": "application/json", "Accept": "application/json"})
        payload = r.json()
        page = parse_list(payload)
        listings += page
        offset += 20
        if not page or offset >= payload.get("total", 0):
            break
    out = []
    for lst in listings:
        loc_text = lst.get("locationsText", "")
        if not _is_sg(loc_text, location) and "locations" not in loc_text.lower():
            continue
        if is_candidate and not is_candidate(lst.get("title", "")):
            continue
        d = request("GET", base + lst["externalPath"], headers={"Accept": "application/json"}).json()
        job = parse_detail(d, cfg, lst, today)
        if _is_sg(job.location + " " + str(d.get("jobPostingInfo", {}).get("country", "")), location):
            out.append(job)
    return out


def probe(cfg: dict) -> int:
    """Health check: total postings matching "intern" on the site."""
    base = BASE.format(**cfg) + f"/wday/cxs/{cfg['tenant']}/{cfg['site']}"
    r = request("POST", base + "/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": cfg.get("search", "intern")},
                headers={"Content-Type": "application/json", "Accept": "application/json"})
    return int(r.json().get("total", 0))
