"""InternSG (www.internsg.com), Singapore's main internship board.

Listing rows look like:
  <a class="ast-row job-listing-row" href="https://www.internsg.com/job/<slug>/?...">
    <span class="job-listing-title">Title</span><div class="job-listing-company">Company<span ...>domain</span></div>
    ... <div class="job-listing-dt">From Jan 2027, For At Least 6 Months</div> ... <span class="badge badge-success"> 15 Sep </span>
Detail pages have <dt>Job Period</dt><dd>...</dd>, <dt>Date Listed</dt><dd>15 Sep 2026</dd>, <dt>Job Description</dt><dd>...</dd>
and say "already closed" once a listing closes.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from ..models import RawJob
from .http import html_to_text, request

BASE = "https://www.internsg.com"


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for a in soup.select("a.job-listing-row"):
        href = a.get("href", "")
        m = re.search(r"/job/([^/?#]+)", href)
        if not m:
            continue
        title = a.select_one(".job-listing-title")
        comp = a.select_one(".job-listing-company")
        if comp:
            for badge in comp.select("span"):
                badge.extract()
        dts = [d.get_text(" ", strip=True) for d in a.select(".job-listing-dt")]
        rows.append({
            "slug": m.group(1),
            "title": title.get_text(" ", strip=True) if title else "",
            "company": comp.get_text(" ", strip=True) if comp else "",
            "location": dts[0] if dts else "",
            "period": dts[1] if len(dts) > 1 else "",
        })
    return rows


def _field(soup: BeautifulSoup, name: str) -> str:
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower() == name.lower():
            dd = dt.find_next_sibling("dd")
            return dd.decode_contents() if dd else ""
    return ""


def parse_detail(html: str, row: dict) -> RawJob | None:
    if re.search(r"already closed", html, re.IGNORECASE):
        return None
    soup = BeautifulSoup(html, "html.parser")
    listed = html_to_text(_field(soup, "Date Listed"))
    try:
        posted = datetime.strptime(listed, "%d %b %Y").date()
    except ValueError:
        posted = None
    period = html_to_text(_field(soup, "Job Period")) or row.get("period", "")
    desc = "\n".join(html_to_text(_field(soup, f)) for f in ("Company Profile", "Job Description", "Applicant Pre-requisites"))
    return RawJob(
        source="internsg", external_id=row["slug"], company=row["company"], title=row["title"],
        url=f"{BASE}/job/{row['slug']}/", location=row.get("location", ""),
        department=html_to_text(_field(soup, "Profession")), posted=posted,
        period_text=period, description=desc,
    )


def fetch(cfg: dict, location: str = "Singapore", is_candidate=None) -> list[RawJob]:
    seen: dict[str, dict] = {}
    for q in cfg.get("listing_queries", []):
        for page in range(1, cfg.get("max_pages", 3) + 1):
            html = request("GET", f"{BASE}/jobs/{page}/{q}").text
            rows = parse_listing(html)
            for row in rows:
                seen.setdefault(row["slug"], row)
            if len(rows) < 20:
                break
    out = []
    for row in seen.values():
        if is_candidate and not is_candidate(row["title"]):
            continue
        job = parse_detail(request("GET", f"{BASE}/job/{row['slug']}/", pace=1.2).text, row)
        if job:
            out.append(job)
    return out


def probe(cfg: dict) -> int:
    """Health check: listings on the first page of the first configured query."""
    q = (cfg.get("listing_queries") or [""])[0]
    return len(parse_listing(request("GET", f"{BASE}/jobs/1/{q}").text))
