"""Opportunity score: how worthwhile is this role for me to investigate or apply to? (0–100)

Deterministic and explainable. Six dimensions, each with a reason:

    Role alignment      25   in-scope, analysis-oriented finance/investment/data work (not quant/software-heavy)
    Availability        20   how well the dates fit Tier 1 / Tier 2 (Tier 1 is ideal: no leave needed)
    Skills              20   skills the posting asks for that your CV evidences vs. ones it doesn't
    Role priority       15   your personal priority groups (config/profile.yaml)
    Eligibility         10   location and stated eligibility (citizenship, student status)
    Posting clarity     10   are dates, duties, requirements and pay actually stated?

Unknown is not negative: when a posting doesn't say something (no dates, too little text to judge
skills), that dimension gets neutral partial credit and is marked unknown in the breakdown.
"""
from __future__ import annotations

import re
from datetime import date

from .classify import Profile

WEIGHTS = {"Role alignment": 25, "Availability": 20, "Skills": 20, "Role priority": 15, "Eligibility": 10, "Posting clarity": 10}
LABELS = [(85, "Excellent match"), (70, "Strong match"), (55, "Worth a look"), (40, "Weak match"), (0, "Poor match")]
MIN_TEXT_FOR_SKILLS = 250


def _term(term: str) -> re.Pattern:
    t = re.escape(term.lower()).replace(r"\ ", r"[\s-]")
    return re.compile(r"(?<![a-z0-9])" + t + r"(?:s|es)?(?![a-z0-9])")


def _has(text: str, term: str) -> bool:
    return bool(_term(term).search(text))


def label_for(total: int) -> str:
    return next(lbl for cut, lbl in LABELS if total >= cut)


def _part(name: str, points: float, reason: str, known: bool = True) -> dict:
    mx = WEIGHTS[name]
    return {"name": name, "points": int(round(max(0, min(mx, points)))), "max": mx, "reason": reason, "known": known}


# ---------------- dimensions ----------------
def priority_group(title: str, department: str, prof: Profile) -> tuple[str | None, str | None]:
    """First priority group (highest → acceptable) whose term appears in the title, else department."""
    for text in (title.lower(), department.lower()):
        for group, cfg in prof.priorities.items():
            for term in cfg["terms"]:
                if _has(text, term):
                    return group, term
    return None, None


def role_alignment(title: str, department: str, desc: str, prof: Profile) -> dict:
    t, full = title.lower(), f"{title} {department} {desc[:5000]}".lower()
    group, term = priority_group(title, "", prof)
    if group in ("highest", "strong", "data"):
        pts, why = 25, f"Core target role ({term})"
    elif group == "acceptable":
        pts, why = 19, f"Acceptable target area ({term})"
    elif priority_group("", f"{department} {desc[:1500]}", prof)[0]:
        pts, why = 16, "In scope, based on the department/description rather than the title"
    else:
        pts, why = 10, "Only loosely matches your target areas"
    heavy = sorted({h for h in prof.heavy_quant_terms if _has(full, h)})
    if heavy:
        cut = 12 if re.search(r"quant|systematic|algorithmic", t) else (6 if len(heavy) >= 2 else 2)
        pts -= cut
        why += f"; quant/software-heavy signals ({', '.join(heavy[:3])})"
    if re.search(r"compliance|\bkyc\b|\baml\b|audit", t) and pts > 16:
        pts, why = 16, why + "; compliance/audit-focused, less analytical"
    if re.search(r"\bsales\b|customer service|admin", t) and pts > 14:
        pts, why = 14, why + "; mostly sales/admin"
    return _part("Role alignment", pts, why)


def availability(job: dict, prof: Profile) -> dict:
    tier, fit = job.get("tier"), job.get("fit")
    start, end = job.get("start"), job.get("end")
    weeks = None
    if start and end:
        weeks = (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days / 7
    elif job.get("min_months"):
        weeks = float(job["min_months"]) * 4.345
    lo, hi = prof.t1_pref_weeks
    approx = bool(job.get("approximate"))
    if tier == "T1" and fit == "strong":
        if weeks is None or lo - 1 <= weeks <= hi + 1:
            return _part("Availability", 20, "Fits your break with no leave needed" + (f" (~{weeks:.0f} weeks)" if weeks else ""))
        if weeks > hi + 1:
            return _part("Availability", 19, f"Fits your break (~{weeks:.0f} weeks)")
        return _part("Availability", 15, f"Fits your break but only ~{weeks:.0f} weeks (you prefer {lo:g}–{hi:g})")
    if tier == "T1" and fit == "stretch":
        return _part("Availability", 13 if approx else 14, "Close to your break; needs a small date adjustment or confirmation"
                     + (" (dates approximate)" if approx else ""))
    if tier == "T1" and fit == "weak":
        return _part("Availability", 5, "Very short programme (under four weeks)")
    if tier == "T2" and fit == "strong":
        return _part("Availability", 17, "Fits a 4–6 month Tier 2 internship (needs a leave of absence)")
    if tier == "T2":
        return _part("Availability", 12, "Tier 2, but outside your preferred 4–6 months or start to confirm")
    return _part("Availability", 10, "The posting doesn't state dates, so treated as unknown (not a mismatch)", known=False)


def skills(title: str, desc: str, prof: Profile) -> dict:
    text = f"{title} {desc}".lower()
    if len(desc) < MIN_TEXT_FOR_SKILLS:
        return _part("Skills", 12, "Posting text is too short to judge skills (unknown)", known=False)
    have = [s for s in prof.skills.get("have", []) if len(s) > 1 and _has(text, s)]
    if re.search(r"(?<![a-z])r(?:\s*/\s*python|,\s*python| programming| studio)|python\s*(?:/|or|,)\s*r(?![a-z])", text):
        have.append("r")
    gaps = [s for s in prof.skills.get("gaps", []) if _has(text, s)]
    if not have and not gaps:
        return _part("Skills", 12, "The posting doesn't list specific skills (unknown)", known=False)
    ratio = len(have) / (len(have) + len(gaps))
    why = []
    if have:
        why.append("you have " + ", ".join(have[:6]))
    if gaps:
        why.append("not on your CV: " + ", ".join(gaps[:5]))
    return _part("Skills", 6 + 14 * ratio, "Asks for skills — " + "; ".join(why))


def role_priority(title: str, department: str, prof: Profile) -> dict:
    group, term = priority_group(title, department, prof)
    if not group:
        return _part("Role priority", 3, "Not in your priority groups")
    names = {"highest": "Highest priority", "strong": "Strong interest", "data": "Data / analytics", "acceptable": "Acceptable"}
    return _part("Role priority", prof.priorities[group]["points"], f"{names.get(group, group)} ({term})")


def eligibility(job: dict, desc: str, prof: Profile) -> dict:
    loc = f"{job.get('location') or ''}".lower()
    text = desc.lower()
    known_loc = "singapore" in loc or "sgp" in loc or loc.endswith(", sg") or job.get("source") in ("internsg",)
    pts, why, known = (7, ["Singapore-based"], True) if known_loc else (5, ["location not confirmed"], False)
    el = prof.eligibility
    if re.search(r"(?:must|should) have graduated|graduated within|fresh graduates? only|graduates only|postgraduate (?:students? )?only"
                 r"|(?:master'?s|phd|mba) (?:students? )?(?:only|required)|completed (?:a|your) (?:bachelor|degree)", text):
        return _part("Eligibility", 3, "Appears to require graduates/postgraduates; check before applying")
    if el.get("singapore_citizen") and re.search(r"singaporeans?(?: citizens?)?\s*(?:and|/|or|&)\s*(?:singapore\s+)?(?:prs?|permanent residents?)|singaporeans? only|\bsc\s*/\s*pr\b", text):
        pts, known = pts + 3, True
        why.append("open to Singaporeans/PRs (you qualify)")
    if el.get("enrolled_undergraduate") and re.search(r"undergraduate|currently (?:enrolled|pursuing)|university students?|penultimate|pursuing (?:a|your) (?:bachelor|degree)", text):
        pts += 2
        why.append("aimed at current students")
    if re.search(r"penultimate|final[- ]year", text):
        why.append("mentions penultimate/final-year students (check your year)")
    reason = "; ".join(why)
    return _part("Eligibility", pts, reason[:1].upper() + reason[1:], known)


def clarity(job: dict, desc: str) -> dict:
    if not desc and job.get("source") == "manual":
        return _part("Posting clarity", 5, "Not assessed: no posting text saved for this role", known=False)
    pts, why = 0, []
    if job.get("start") and job.get("end") and not job.get("approximate"):
        pts += 4; why.append("exact dates")
    elif job.get("start") or job.get("min_months"):
        pts += 2; why.append("partial or approximate dates")
    elif job.get("fit") == "stretch":
        pts += 1; why.append("flexible timing")
    else:
        why.append("no dates")
    n = len(desc)
    pts += 3 if n >= 1200 else 2 if n >= 400 else 1 if n >= 100 else 0
    why.append("detailed description" if n >= 1200 else "short description" if n >= 100 else "little description")
    low = desc.lower()
    if re.search(r"responsibilit|what you(?:'ll| will) do|you will|duties|job description|key tasks", low):
        pts += 1; why.append("duties listed")
    if re.search(r"requirement|qualification|looking for|you have|pre-?requisite|must be", low):
        pts += 1; why.append("requirements listed")
    if re.search(r"\$\s?\d|allowance|stipend|salary|\bsgd\b", low):
        pts += 1; why.append("pay stated")
    reason = ", ".join(why)
    return _part("Posting clarity", pts, reason[:1].upper() + reason[1:])


def score(job: dict, prof: Profile) -> dict:
    """job: dict with title, department, description, tier, fit, start, end, min_months, approximate, location, source."""
    title, dept, desc = job.get("title") or "", job.get("department") or "", job.get("description") or ""
    parts = [
        role_alignment(title, dept, desc, prof),
        availability(job, prof),
        skills(title, desc, prof),
        role_priority(title, dept, prof),
        eligibility(job, desc, prof),
        clarity(job, desc),
    ]
    total = sum(p["points"] for p in parts)
    return {"total": total, "label": label_for(total), "parts": parts, "unknown": [p["name"] for p in parts if not p["known"]]}
