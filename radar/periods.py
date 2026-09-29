"""Extract an internship's timing from free text.

Postings describe timing in dozens of ways: "[Dec26 to May27]", "Jan - Jun 2027",
"11 January 2027 – 30 June 2027", "From Dec 2026, For At Least 6 Months",
"minimum of 12 weeks", "4–6 months", "1H 2027", "Winter 2026"... This module turns that
text into a structured Period so the classifier can compare it with your availability.

Principle: unknown stays unknown. A month with no year is only accepted when the text is
clearly about the internship's start ("available to start by mid December"), never from
unrelated sentences such as "applications close late December".
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}

_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_YR = r"(?:'|\s|-)?((?:20)?2\d)?"  # 2026, 26, '26 or nothing
_DAY = r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?"
_SEP = r"\s*(?:-|–|—|to|until|till|through)\s*"
_WHEN = r"(?:(?:early|mid|late|end(?:\s+of)?)(?:[/-](?:early|mid|late))?\s+)?"

RANGE_RE = re.compile(_DAY + _MON + r"\.?" + _YR + _SEP + _DAY + _MON + r"\.?" + _YR + r"\b", re.IGNORECASE)
# Only phrases that are about STARTING the internship.
START_RE = re.compile(
    r"(?:\bfrom|\bstarting(?:\s+(?:in|from|on))?|\bstart(?:s|ing)?(?:\s+date)?(?:\s+(?:is|of))?[:\s]+(?:in\s+|by\s+|from\s+|on\s+)?"
    r"|\bcommenc\w*\s+(?:in\s+|on\s+|from\s+)?|\bavailable\s+(?:to\s+start\s+)?(?:from\s+|in\s+|by\s+)|\bable\s+to\s+start\s+(?:by\s+|in\s+|from\s+)?)\s*"
    + _WHEN + _DAY + _MON + r"\.?" + _YR + r"\b",
    re.IGNORECASE,
)
# "from" in these contexts is not a start date ("applications open from November").
NOT_START_CONTEXT = re.compile(r"appl|deadline|close|graduat|hear|receiv|submit|interview|shortlist|open", re.IGNORECASE)
HALF_RE = re.compile(r"\b(?:([12])h\s?(20\d\d)|h([12])\s?(20\d\d)|s([12])\s+(20\d\d))\b", re.IGNORECASE)
SEASON_YEAR_RE = re.compile(r"\b(winter|spring|summer|fall|autumn|year[- ]end)\b\s*(?:intake\s*|internship\s*|programme\s*)?[(,]?\s*(20\d\d)\b", re.IGNORECASE)
SEASON_INTERN_RE = re.compile(r"\b(winter|year[- ]end)\s+intern(?:ship)?s?\b", re.IGNORECASE)
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
_NUM = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"
MIN_RE = re.compile(
    r"(?:at\s+least|minimum(?:\s+(?:commitment|duration|period))?(?:\s+of)?|min\.?|commit(?:ment)?(?:\s+(?:of|for))?)\s*(?:\(\d+\)\s*)?"
    + _NUM + r"\s*(?:\(\d+\)\s*)?[- ]?(weeks?|months?)",
    re.IGNORECASE,
)
SPAN_RE = re.compile(r"\b" + _NUM + r"\s*(?:-|–|—|to)\s*" + _NUM + r"[- ]?(weeks?|months?)\b", re.IGNORECASE)
LEN_RE = re.compile(r"\b" + _NUM + r"[- ]?(week|month)s?(?:[- ]long)?\s*(?:full[- ]time\s*)?(?:paid\s*)?(?:internship|intern|contract|programme|program|attachment)", re.IGNORECASE)
PAREN_LEN_RE = re.compile(r"\(\s*" + _NUM + r"\s*(weeks?|months?)", re.IGNORECASE)


@dataclass
class Period:
    start: date | None = None
    end: date | None = None
    min_months: float | None = None      # stated minimum commitment ("at least 3 months", lower end of "4–6 months")
    max_months: float | None = None      # upper end of a stated span ("4–6 months" -> 6)
    flexible_start: bool = False         # "immediate" / "flexible" start
    flexible_duration: bool = False
    approximate: bool = False            # dates inferred from a season ("Winter 2026", "Spring 2027")
    source_text: str = ""

    @property
    def months(self) -> float | None:
        if self.start and self.end:
            return round((self.end - self.start).days / 30.44, 1)
        return self.min_months

    def is_empty(self) -> bool:
        return not (self.start or self.end or self.min_months or self.flexible_start or self.flexible_duration)

    def describe(self) -> str:
        """Short human label, e.g. 'Dec 2026 – May 2027' or 'Flexible start, min 3 months'."""
        def fmt(d: date) -> str:
            whole_month = d.day == 1 or d.day == calendar.monthrange(d.year, d.month)[1]
            return d.strftime("%b %Y") if whole_month else f"{d.day} {d.strftime('%b %Y')}"

        if self.start and self.end:
            label = f"{fmt(self.start)} – {fmt(self.end)}"
            return label + (" (approx.)" if self.approximate else "")
        parts = []
        if self.start:
            parts.append("From " + fmt(self.start))
        elif self.flexible_start:
            parts.append("Flexible start")
        if self.min_months and self.max_months and self.max_months > self.min_months:
            parts.append(f"{self.min_months:g}–{self.max_months:g} months")
        elif self.min_months:
            weeks = self.min_months * 4.345
            parts.append(f"min {round(weeks)} weeks" if self.min_months < 3 and abs(weeks - round(weeks)) < .3 else f"min {self.min_months:g} months")
        elif self.flexible_duration:
            parts.append("flexible duration")
        return ", ".join(parts) or "Dates not stated"


def _num(tok: str) -> float:
    return float(WORD_NUM.get(tok.lower(), tok))


def _year(tok: str | None) -> int | None:
    if not tok:
        return None
    y = int(tok)
    return y + 2000 if y < 100 else y


def _month(tok: str) -> int:
    return MONTHS[tok.lower()[:3]]


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _to_months(n: float, unit: str) -> float:
    return round(n / 4.345, 2) if unit.lower().startswith("week") else n


def end_from(start: date, months: float) -> date:
    """Last day of an internship of `months` length starting on `start`."""
    whole = int(months)
    return start + relativedelta(months=whole, days=round((months - whole) * 30.44)) - timedelta(days=1)


def _next_year_for(month: int, today: date) -> int:
    """A month with no year means its next occurrence (December seen in September -> this year)."""
    return today.year if month >= today.month else today.year + 1


def parse_period(text: str, today: date | None = None) -> Period:
    """Best-effort parse. Earlier, more specific patterns win over later, vaguer ones."""
    today = today or date.today()
    t = re.sub(r"\s+", " ", text or "")
    p = Period(source_text=t[:300])

    # 1. Explicit ranges: "Dec 2026 - Feb 2027", "Dec26 to May27", "11 January 2027 – 30 June 2027"
    for m in RANGE_RE.finditer(t):
        d1, m1, y1, d2, m2, y2 = m.groups()
        mo1, mo2 = _month(m1), _month(m2)
        yr1, yr2 = _year(y1), _year(y2)
        if yr2 is None and yr1 is None:
            continue  # "Jan - Jun" with no year anywhere is too vague
        if yr2 is None:
            yr2 = yr1 if mo2 >= mo1 else yr1 + 1
        if yr1 is None:
            yr1 = yr2 if mo1 <= mo2 else yr2 - 1
        start = date(yr1, mo1, int(d1) if d1 else 1)
        end = date(yr2, mo2, int(d2)) if d2 else _month_end(yr2, mo2)
        if end > start and (end - start).days < 400:
            p.start, p.end = start, end
            break

    # 2. Half-years: "1H 2027", "H1 2027", "S1 2027"
    if not p.start:
        h = HALF_RE.search(t)
        if h:
            half = int(h.group(1) or h.group(3) or h.group(5))
            yr = int(h.group(2) or h.group(4) or h.group(6))
            p.start = date(yr, 1 if half == 1 else 7, 1)
            p.end = _month_end(yr, 6 if half == 1 else 12)

    # 3. Start phrases: "From Dec 2026", "starting January 2027", "available to start by mid December"
    if not p.start:
        for s in START_RE.finditer(t):
            if s.group(0).lower().startswith("from") and NOT_START_CONTEXT.search(t[max(0, s.start() - 30):s.start()]):
                continue
            d1, mo, yr = s.groups()
            mo_i = _month(mo)
            p.start = date(_year(yr) or _next_year_for(mo_i, today), mo_i, int(d1) if d1 else 1)
            break

    # 4. Seasons: "Winter 2026", "Spring 2027", or a yearless "Winter internship" (next December)
    if not p.start:
        s = SEASON_YEAR_RE.search(t)
        season, yr = (s.group(1).lower(), int(s.group(2))) if s else (None, None)
        if not s:
            s2 = SEASON_INTERN_RE.search(t)
            if s2:
                season, yr = s2.group(1).lower(), _next_year_for(12, today)
        if season:
            p.approximate = True
            if season in ("winter", "year-end", "year end"):
                p.start, p.end = date(yr, 12, 1), _month_end(yr + 1, 2)
            elif season == "spring":
                p.start, p.end = date(yr, 1, 1), _month_end(yr, 6)
            elif season == "summer":
                p.start, p.end = date(yr, 5, 1), _month_end(yr, 8)
            else:  # fall / autumn
                p.start, p.end = date(yr, 8, 1), _month_end(yr, 12)

    # Duration: "at least 3 months", "minimum of 12 weeks", "4–6 months", "6-month internship"
    sp = SPAN_RE.search(t)
    mm = MIN_RE.search(t)
    if mm:
        p.min_months = _to_months(_num(mm.group(1)), mm.group(2))
    if sp:
        lo, hi = _to_months(_num(sp.group(1)), sp.group(3)), _to_months(_num(sp.group(2)), sp.group(3))
        if hi > lo:
            p.min_months = p.min_months or lo
            p.max_months = hi
    if not p.min_months:
        ln = LEN_RE.search(t) or PAREN_LEN_RE.search(t)
        if ln:
            p.min_months = _to_months(_num(ln.group(1)), ln.group(2))

    low = t.lower()
    if re.search(r"immediate(ly)? start|start immediately|asap", low):
        p.flexible_start = True
    if re.search(r"flexible start|start date(s)? (is|are) flexible|flexib\w+ (on|with) (the )?(start|timing|dates)", low):
        p.flexible_start = True
    if re.search(r"flexible duration|duration is flexible", low):
        p.flexible_duration = True

    # A start + minimum length implies an end if none was given.
    if p.start and not p.end and p.min_months:
        p.end = end_from(p.start, p.min_months)
    return p
