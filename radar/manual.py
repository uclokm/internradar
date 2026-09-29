"""Roles you add yourself (LinkedIn, jorb.ai, referrals, career fairs...).

Kept in the private store as manual_jobs.csv, never in the public job database. They go
through the same classifier and scorer as collected postings, except that they are always
kept (you chose them), even when the dates you entered fall outside your windows.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from .classify import FAMILY_LABELS, Profile, classify, family_for
from .models import Job, RawJob

FIELDS = ["id", "company", "title", "url", "found_on", "dates", "description", "notes", "tier", "fit", "area", "note", "added"]
FOUND_ON = ["LinkedIn", "jorb.ai", "Referral", "Career fair", "Company website", "Other"]


def parse_csv(text: str | None) -> list[dict]:
    if not text:
        return []
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in FIELDS})
    return buf.getvalue()


def new_row(company: str, title: str, url: str, found_on: str, dates: str, description: str, notes: str, today: date) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{company} {title}".lower()).strip("-")[:60]
    return {"id": f"{slug}-{today:%Y%m%d}", "company": company.strip(), "title": title.strip(), "url": url.strip(),
            "found_on": found_on, "dates": dates.strip(), "description": description.strip(), "notes": notes.strip(),
            "added": today.isoformat()}


def to_jobs(rows: list[dict], prof: Profile, today: date) -> list[Job]:
    jobs = []
    for r in rows:
        raw = RawJob(source="manual", external_id=r.get("id") or r["url"], company=r["company"], title=r["title"], url=r["url"],
                     location=prof.location, posted=date.fromisoformat(r["added"]) if r.get("added") else None,
                     period_text=r.get("dates", ""), description=r.get("description", ""))
        job = classify(raw, prof, today, require_relevant=False, keep_out_of_window=True)
        # Rows assessed by hand (earlier versions stored tier/fit/area) keep that assessment
        # when the entered text alone can't be dated.
        if r.get("tier") and job.tier == "?":
            job.tier, job.fit = r["tier"], r.get("fit") or job.fit
            job.note = r.get("note") or job.note
            job.dates = r.get("dates") or job.dates
        if r.get("area"):
            fam = family_for(r["title"], r["area"])
            job.family, job.area = fam, FAMILY_LABELS[fam]
        job.extra.update({"found_on": r.get("found_on", ""), "manual_notes": r.get("notes", "")})
        jobs.append(job)
    return jobs
