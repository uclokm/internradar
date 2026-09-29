"""Decide whether a posting is relevant, which tier it falls into, how well it fits, and which
role family (CV version) it belongs to.

Tier 1: fits inside your break (default 30 Nov 2026 – 19 Feb 2027) without leave.
Tier 2: a longer role (technical bounds 3.5–7.5 months, preferred 4–6) starting around your
        break, so it needs a leave of absence.
Fit:    strong  = the stated dates work as written
        stretch = close (a week or two over, "minimum 3 months", outside the preferred 4–6
                  months, or flexible timing to confirm)
        weak    = very short programme (under four weeks)
        unclear = no usable dates in the posting ("?" tier), kept for a manual look
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml

from .models import Job, RawJob
from .paths import CONFIG
from .periods import Period, end_from, parse_period

FAMILY_LABELS = {
    "INV": "Investment, research & IB",
    "AM": "Asset & wealth management",
    "DATA": "Data & business analytics",
    "OPS": "Finance ops, treasury & risk",
    "STRAT": "Strategy & commercial",
}

# Title phrases checked in order; the first match decides. Specific phrases come before broad
# ones so "Investment Operations" is OPS (not INV) and "Portfolio Analytics" is AM (not DATA).
TITLE_RULES: list[tuple[str, str]] = [
    ("OPS", r"(investment|fund|trade|trading|markets?|securities|wealth|payments?|treasury|finance|business)\s+(operations|ops|support)\b"
            r"|\b(operations|ops)\b|middle office|back office|settlements?\b|reconciliation|trade support"),
    ("DATA", r"data (analyst|analytics|science|scientist|intern)|data\s*&\s*(ai|analytics|finance)|business intelligence|\bbi\b(?! -)"),
    ("AM", r"portfolio (analytics|management|construction|strateg\w*|monitoring)|asset management|multi[- ]asset|\bwealth\b|private bank"
           r"|fund management|\betfs?\b|investment solutions|client (solutions|group|services)|investor relations|\bequities\b"),
    ("OPS", r"treasury|fp\s*&\s*a|financial planning|financial analyst|(?<!corporate )(?<!acquisition )(?<!project )(?<!leveraged )(?<!trade )(?<!estate )(?<!structured )\bfinance\b"
            r"|product control|controll(er|ing)|\brisk\b|compliance|financial crime|\bkyc\b|\baml\b|audit"),
    ("INV", r"quant(itative)?\s+(research|strateg\w*|analyst|trading)|equity research|investment research|credit research|research analyst"
            r"|markets research|macro research|\bresearch\b"),
    ("INV", r"private (equity|markets?|credit|debt)|venture|\binvest|investment banking|\bib\b|corporate finance|\bm\s*&\s*a\b|mergers|deals"
            r"|capital markets|leveraged|acquisition finance|project finance|real estate finance|structured finance|valuation|transaction|trading|sales\s*&\s*trading|\bmarkets\b|\bcredit\b|hedge fund"),
    ("STRAT", r"commercial analytics|strategy analytics|strategy\s*(&|and)\s*commercial|strategy analyst|corporate strategy|strategic planning"),
    ("DATA", r"business analy|\banalytics\b|insights|pricing|data\b"),
    ("STRAT", r"strateg|commercial|growth|business development|consult|corporate development|planning"),
]

# Fallback evidence when no title phrase matches: (pattern, weight) per family, counted across
# title (x3), department (x2) and description (x1, capped).
FAMILY_TERMS: dict[str, list[str]] = {
    "INV": [r"invest", r"valuation", r"due diligence", r"deal", r"equity", r"credit", r"capital markets", r"m&a", r"research"],
    "AM": [r"portfolio", r"asset management", r"fund", r"wealth", r"client", r"allocation", r"performance"],
    "DATA": [r"\bsql\b", r"python", r"dashboard", r"power bi", r"tableau", r"analytics", r"\bdata\b", r"insight"],
    "OPS": [r"treasury", r"reconcil", r"settlement", r"operations", r"risk", r"compliance", r"control", r"reporting"],
    "STRAT": [r"strateg", r"market research", r"business case", r"commercial", r"competitor", r"growth"],
}

# Exclusions that no "data"/"analytics" wording can rescue: pure software/dev roles.
HARD_EXCLUDE = r"software|developer|front[- ]?end|back[- ]?end|full[- ]?stack|devops|site reliability|\bsre\b"


@dataclass
class Profile:
    t1_start: date
    t1_end: date
    t2_earliest: date
    t2_latest: date
    t2_min: float
    t2_max: float
    grace: int
    intern_terms: list[str]
    exclude_terms: list[str]
    target_terms: list[str]
    location: str = "Singapore"
    t1_pref_weeks: tuple[float, float] = (8, 12)
    t2_pref_months: tuple[float, float] = (4, 6)
    priorities: dict = field(default_factory=dict)
    skills: dict = field(default_factory=dict)
    heavy_quant_terms: list[str] = field(default_factory=list)
    eligibility: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Profile":
        cfg = yaml.safe_load((path or CONFIG / "profile.yaml").read_text())
        a = cfg["availability"]
        return cls(
            t1_start=a["tier1_start"], t1_end=a["tier1_end"],
            t2_earliest=a["tier2_earliest_start"], t2_latest=a["tier2_latest_start"],
            t2_min=a["tier2_min_months"], t2_max=a["tier2_max_months"], grace=a["grace_days"],
            t1_pref_weeks=tuple(a.get("tier1_preferred_weeks", (8, 12))),
            t2_pref_months=tuple(a.get("tier2_preferred_months", (4, 6))),
            intern_terms=cfg["intern_terms"], exclude_terms=cfg["exclude_title_terms"],
            target_terms=cfg["target_terms"], location=cfg.get("location", "Singapore"),
            priorities=cfg.get("role_priorities", {}), skills=cfg.get("skills", {}),
            heavy_quant_terms=cfg.get("heavy_quant_terms", []), eligibility=cfg.get("eligibility", {}),
        )


def _has(text: str, terms: list[str]) -> bool:
    t = text.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(term.lower()), t) for term in terms)


def title_candidate(title: str, prof: Profile) -> bool:
    """Cheap pre-filter used before fetching a posting's detail page: an internship title that
    isn't clearly an excluded role. (Target-area checks wait for the department/description.)"""
    t = title.lower()
    if not _has(t, prof.intern_terms) or re.search(HARD_EXCLUDE, t):
        return False
    return not (_has(t, prof.exclude_terms) and not re.search(r"data|analytic|quant|financ|invest", t))


def is_relevant(raw: RawJob, prof: Profile) -> bool:
    """Keep internships in target areas; drop software, marketing, HR, legal, summer programmes etc.
    Broad words like analyst, operations, risk or data never cause an exclusion on their own."""
    title = raw.title.lower()
    if not _has(title, prof.intern_terms):
        return False
    if re.search(HARD_EXCLUDE, title):
        return False
    if _has(title, prof.exclude_terms) and not re.search(r"data|analytic|quant|financ|invest", title):
        return False
    return _has(title + " " + raw.department, prof.target_terms)


def family_for(title: str, area_hint: str = "", department: str = "", description: str = "") -> str:
    """Role family, which picks the CV version. Title phrases decide first; otherwise weighted
    evidence from title, department and description. `area_hint` is an explicit label (manual roles)."""
    a = area_hint.lower()
    for fam, label in FAMILY_LABELS.items():
        if a and a == label.lower():
            return fam
    if re.search(r"^data|^fintech|pricing", a):
        return "DATA"
    if re.search(r"^commercial|^strategy", a):
        return "STRAT"
    t = f"{title} {area_hint}".lower()
    for fam, pattern in TITLE_RULES:
        if re.search(pattern, t):
            return fam
    scores = {}
    for fam, pats in FAMILY_TERMS.items():
        s = 0
        for p in pats:
            s += 3 * bool(re.search(p, title.lower())) + 2 * bool(re.search(p, department.lower()))
            s += min(len(re.findall(p, description.lower())), 3)
        scores[fam] = s
    best = max(scores, key=lambda f: (scores[f], f == "DATA"))
    return best if scores[best] > 0 else "DATA"


def tier_and_fit(p: Period, prof: Profile, today: date) -> tuple[str, str, str]:
    """Return (tier, fit, note)."""
    g = timedelta(days=prof.grace)
    start, end, months = p.start, p.end, p.months
    lo, hi = prof.t2_pref_months

    # Very short programmes (e.g. two-week winter camps)
    if start and end and (end - start).days < 28 and prof.t1_start - g <= start <= prof.t1_end:
        return "T1", "weak", "Short programme (under four weeks)."

    if start and end:
        in_t1 = prof.t1_start - g <= start and end <= prof.t1_end + g and start <= prof.t1_end
        if in_t1:
            approx = " Dates are approximate (from a season name); confirm them." if p.approximate else ""
            exact = start >= prof.t1_start - timedelta(days=3) and end <= prof.t1_end + timedelta(days=10)
            if exact and not p.approximate:
                return "T1", "strong", "Dates fit your break as written."
            if exact:
                return "T1", "stretch", "Likely fits your break." + approx
            return "T1", "stretch", "Slightly outside your break; ask about adjusting a week or two." + approx
        if prof.t2_earliest - g <= start <= prof.t2_latest and months and prof.t2_min <= months <= prof.t2_max:
            if lo - 0.3 <= months <= hi + 0.5:
                return "T2", "strong", f"About {months:.0f} months from {start:%b %Y}; needs a leave of absence."
            side = "longer" if months > hi else "shorter"
            return "T2", "stretch", f"About {months:.0f} months from {start:%b %Y}, {side} than your preferred {lo:g}–{hi:g}; needs a leave of absence."
        if prof.t2_earliest - g <= start <= prof.t2_latest and months and months < prof.t2_min:
            return ("T1" if end <= prof.t1_end + timedelta(days=45) else "T2"), "stretch", f"Runs to {end:%d %b %Y}; ask whether it can end sooner."
        return "", "", ""  # outside both windows (e.g. a Jul–Dec 2027 role)

    if p.min_months:
        window_weeks = (prof.t1_end - prof.t1_start).days / 7
        need_weeks = p.min_months * 4.345
        s = start or (today if p.flexible_start else None)
        if s is None or prof.t2_earliest - g <= s <= prof.t2_latest or (p.flexible_start and s <= prof.t1_start):
            if need_weeks <= window_weeks:
                return "T1", "strong", f"Minimum {need_weeks:.0f} weeks fits your {window_weeks:.0f}-week break."
            if need_weeks <= window_weeks + 3:
                return "T1", "stretch", f"Asks for about {need_weeks:.0f} weeks; your break is ~{window_weeks:.1f}. Ask about a slightly shorter stint."
            if p.min_months <= prof.t2_max:
                fit = "strong" if start and lo - 0.3 <= p.min_months <= hi + 0.5 else "stretch"
                return "T2", fit, f"Needs {p.min_months:g}+ months" + ("" if start else "; confirm a Dec–Feb start") + "."
        return "", "", ""

    if p.flexible_start or p.flexible_duration:
        return "T1", "stretch", "Flexible timing; propose 30 Nov – 19 Feb."
    return "?", "unclear", "No dates in the posting; check before applying."


def parse_job_period(raw: RawJob, today: date) -> Period:
    """Title and period snippets are the most reliable; the description fills gaps."""
    p = parse_period(f"{raw.title}. {raw.period_text}", today)
    if not (p.start and p.end):
        d = parse_period(f"{raw.title}. {raw.period_text}. {raw.description[:6000]}", today)
        if not p.start and d.start:
            p.start, p.end, p.approximate = d.start, d.end, d.approximate
        p.min_months = p.min_months or d.min_months
        p.max_months = p.max_months or d.max_months
        p.flexible_start = p.flexible_start or d.flexible_start
        p.flexible_duration = p.flexible_duration or d.flexible_duration
        if p.start and not p.end and p.min_months:
            p.end = end_from(p.start, p.min_months)
    return p


def classify(raw: RawJob, prof: Profile, today: date | None = None, *, require_relevant: bool = True,
             keep_out_of_window: bool = False) -> Job | None:
    """Turn a raw posting into a Job, or None if it isn't relevant / doesn't fit either tier.
    Manual roles use require_relevant=False and keep_out_of_window=True: you chose them, so they're kept."""
    today = today or date.today()
    if require_relevant and not is_relevant(raw, prof):
        return None
    p = parse_job_period(raw, today)
    tier, fit, note = tier_and_fit(p, prof, today)
    if not tier:
        if not keep_out_of_window:
            return None
        tier, fit, note = "?", "unclear", "Dates given are outside both of your windows; check before applying."
    fam = family_for(raw.title, "", raw.department, raw.description)
    return Job(
        key=raw.key, source=raw.source, company=raw.company, title=raw.title.strip(), url=raw.url,
        location=raw.location, posted=raw.posted, dates=p.describe(), start=p.start, end=p.end,
        min_months=p.min_months, tier=tier, fit=fit, family=fam, area=FAMILY_LABELS[fam],
        note=note, description=raw.description[:20000],
        extra={"max_months": p.max_months, "approximate": p.approximate, "department": raw.department},
    )
