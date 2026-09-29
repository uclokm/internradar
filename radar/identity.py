"""Job identity: recognise the same posting across sources and reposts.

A fingerprint is the normalised company plus the normalised role title, e.g.
    "Lion Global Investors Ltd" + "Intern, Asian Equities (Dec 2026)"
    "Lion Global Investors Limited" + "Asian Equities Intern"
both become  "lion global investors|asian equities".

Dates, durations, legal suffixes, punctuation and word order are ignored; the words that
describe the role are kept, so genuinely different roles at one company stay separate.
"""
from __future__ import annotations

import re

COMPANY_NOISE = {
    "pte", "ltd", "limited", "private", "inc", "llc", "llp", "plc", "co", "corp", "corporation", "company",
    "group", "holdings", "holding", "bank", "singapore", "sg", "asia", "pacific", "apac", "international", "intl", "the", "and",
}
TITLE_NOISE = {
    "intern", "interns", "internship", "internships", "the", "and", "of", "for", "a", "an", "in", "to", "at", "with",
    "programme", "program", "off", "cycle", "offcycle", "position", "role", "opportunity", "full", "time", "fulltime",
    "sg", "singapore", "apac", "asia", "uni", "university", "undergraduate", "student", "intake", "start",
}
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# Bracketed or trailing segments that only carry timing, e.g. "(Jan - Jun 2027)", "[Dec26 to May27]", "(6 Months)"
TIMING = re.compile(
    rf"[\[(][^\])]*(?:20\d\d|\b{MONTH}\s?'?\d{{2}}\b|\bmonths?\b|\bweeks?\b|\b[12]h\b|\bh[12]\b|intake|start)[^\])]*[\])]"
    rf"|\b(?:[12]h|h[12]|s[12])\s?20\d\d\b|\b20\d\d\b|\b{MONTH}\s?'?\d{{2}}\b|\b(?:winter|spring|summer|fall|autumn|year[- ]end)\b",
    re.IGNORECASE,
)


def normalize_company(name: str) -> str:
    s = re.sub(r"\(.*?\)", " ", (name or "").lower())
    s = s.replace("&", " and ")
    words = [w for w in re.findall(r"[a-z0-9]+", s) if w not in COMPANY_NOISE]
    return " ".join(words[:3])


def normalize_title(title: str) -> str:
    s = TIMING.sub(" ", (title or "").lower())
    s = s.replace("&", " and ").replace("m and a", "manda")
    words = {w for w in re.findall(r"[a-z0-9]+", s) if w not in TITLE_NOISE and not w.isdigit()}
    return " ".join(sorted(words))


def fingerprint(company: str, title: str) -> str:
    return f"{normalize_company(company)}|{normalize_title(title)}"
