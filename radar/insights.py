"""Daily priorities and application analytics (pure functions, no UI).

Priorities surface useful next actions only; nothing is flagged urgent unless a date you set
(follow-up, interview) makes it so.
"""
from __future__ import annotations

from datetime import date

from .applications import ACTIVE, CLOSED_OUT, SUBMITTED, reached

HIGH_SCORE = 75
NEW_DAYS = 3


def _d(v) -> date | None:
    if not v:
        return None
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def priorities(jobs: list[dict], apps: dict, today: date, limit: int = 8) -> list[dict]:
    """jobs: open roles as dicts with fp, company, title, score, first_seen. Returns ordered action items."""
    by_fp = {j["fp"]: j for j in jobs}
    items = []
    for fp, rec in apps.items():
        job = by_fp.get(fp) or rec.get("job", {})
        name = f"{job.get('company', '?')} — {job.get('title', '?')}"
        iv = _d(rec.get("interview_on"))
        if rec.get("status") == "Interview" and iv and 0 <= (iv - today).days <= 14:
            when = "today" if iv == today else "tomorrow" if (iv - today).days == 1 else f"on {iv:%a %d %b}"
            items.append({"kind": "Interview", "rank": 0, "fp": fp, "text": name, "detail": f"Interview {when}"})
        fu = _d(rec.get("follow_up_on"))
        if rec.get("status") in ACTIVE and fu and fu <= today:
            items.append({"kind": "Follow up", "rank": 1, "fp": fp, "text": name,
                          "detail": "Follow-up due today" if fu == today else f"Follow-up was due {fu:%d %b}"})
        if rec.get("status") == "Applying":
            items.append({"kind": "Finish application", "rank": 2, "fp": fp, "text": name, "detail": "Marked as Applying"})
    tracked = {fp for fp, r in apps.items() if r.get("status", "Not started") != "Not started"}
    fresh = [j for j in jobs if j["fp"] not in tracked and (j.get("score") or 0) >= HIGH_SCORE
             and _d(j.get("first_seen")) and (today - _d(j["first_seen"])).days < NEW_DAYS]
    for j in sorted(fresh, key=lambda j: -j["score"])[:3]:
        items.append({"kind": "New match", "rank": 3, "fp": j["fp"], "text": f"{j['company']} — {j['title']}",
                      "detail": f"New, scored {j['score']}/100"})
    seen = {i["fp"] for i in items}
    strong = [j for j in jobs if j["fp"] not in tracked and j["fp"] not in seen and (j.get("score") or 0) >= 80]
    for j in sorted(strong, key=lambda j: -j["score"])[:3]:
        items.append({"kind": "Worth applying", "rank": 4, "fp": j["fp"], "text": f"{j['company']} — {j['title']}",
                      "detail": f"Scored {j['score']}/100 and not shortlisted yet"})
    return sorted(items, key=lambda i: i["rank"])[:limit]


def summary(apps: dict, min_for_rate: int = 3) -> dict:
    """Honest application funnel. Rates are None when there isn't enough data to mean anything."""
    recs = list(apps.values())
    submitted = [r for r in recs if r.get("status") in SUBMITTED or r.get("applied_on")]
    interviews = [r for r in submitted if reached(r, "Interview")]
    offers = [r for r in submitted if reached(r, "Offer")]
    rate = lambda a, b: round(100 * len(a) / len(b)) if len(b) >= min_for_rate else None
    return {
        "applications": len(submitted),
        "active": sum(r.get("status") in ACTIVE for r in recs),
        "interviews": len(interviews),
        "offers": len(offers),
        "rejections": sum(r.get("status") == "Rejected" for r in recs),
        "withdrawn": sum(r.get("status") == "Withdrawn" for r in recs),
        "app_to_interview": rate(interviews, submitted),
        "interview_to_offer": rate(offers, interviews),
        "closed_out": sum(r.get("status") in CLOSED_OUT for r in recs),
    }


def breakdown(apps: dict, field: str) -> dict[str, int]:
    """Submitted applications counted by a snapshot field (family, source, tier)."""
    out: dict[str, int] = {}
    for r in apps.values():
        if r.get("status") in SUBMITTED or r.get("applied_on"):
            key = (r.get("job") or {}).get(field) or "Unknown"
            out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def score_vs_outcome(apps: dict, cut: int = HIGH_SCORE, min_each: int = 3) -> list[dict] | None:
    """Interview rate for higher- vs lower-scored applications; None until each group has enough data."""
    groups = {f"Score ≥ {cut}": [], f"Score < {cut}": []}
    for r in apps.values():
        s = (r.get("job") or {}).get("score")
        if s is None or not (r.get("status") in SUBMITTED or r.get("applied_on")):
            continue
        groups[f"Score ≥ {cut}" if s >= cut else f"Score < {cut}"].append(r)
    if any(len(v) < min_each for v in groups.values()):
        return None
    return [{"group": g, "applications": len(v), "interview_rate": round(100 * sum(reached(r, "Interview") for r in v) / len(v))}
            for g, v in groups.items()]
