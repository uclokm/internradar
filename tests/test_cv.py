"""CV grounding: tailored CVs may only contain content from the master CV.

See radar/cv.py for exactly what these tests do and do not guarantee.
"""
import io
import re

import pytest
from pypdf import PdfReader

from radar import cv

MASTER = cv.load_master()
VERSIONS = list(cv.versions(MASTER))
ALL_BULLETS = {b for sec in ("experience", "projects") for item in MASTER[sec] for b in item["bullets"].values()}
POSTING = ("We need strong financial modelling, DCF valuation, Bloomberg, VBA and C++ skills, plus Python and SQL. "
           "Experience with LBO models and due diligence is essential.")


def tailored(version, company="Acme Capital", title="Intern, Asian Equities (Jan - Jun 2027)", tier="T2"):
    return cv.build(MASTER, version, company, title, tier)


def test_every_version_references_real_bullets():
    """A typo in a version's bullet ids would silently drop content; every id must exist."""
    for name, V in cv.versions(MASTER).items():
        for key, sec in (("experience", "experience"), ("projects", "projects")):
            for bid in V[key]:
                assert any(bid in item["bullets"] or bid.split("_")[0] in item["bullets"] for item in MASTER[sec]), (name, bid)
        assert set(V["coursework"]) <= set(MASTER["coursework"]), name


@pytest.mark.parametrize("version", VERSIONS)
def test_bullets_come_verbatim_from_master(version):
    certs = set(MASTER["certifications"]) | set(MASTER["awards"])
    for b in tailored(version):
        if b.kind != "bullet":
            continue
        if b.text.startswith("Relevant coursework: "):
            items = b.text.removeprefix("Relevant coursework: ").split(", ")
            assert set(items) <= set(MASTER["coursework"].values())
        else:
            assert b.text in ALL_BULLETS or b.text in certs, b.text


@pytest.mark.parametrize("version", VERSIONS)
def test_skills_are_a_reordering_of_master_skills(version):
    V = cv.versions(MASTER)[version]
    assert sorted(V["tech"]) == sorted(MASTER["tech"])
    assert sorted(V["analytical"]) == sorted(MASTER["analytical"])


@pytest.mark.parametrize("version", VERSIONS)
def test_summary_is_assembled_only_from_master_sentences(version):
    V = cv.versions(MASTER)[version]
    summary = next(b.text for b in tailored(version) if b.kind == "para")
    m = re.fullmatch(r"(?P<intro>.+?) (?P<focus>with .+?)\. Proficient in (?P<tech>.+?)\. Seeking the (?P<role>.+?) at "
                     r"(?P<company>.+?), where I can (?P<goal>.+?)\. (?P<avail>Available .+\.)", summary)
    assert m, summary
    assert m["intro"] == MASTER["intro"] and m["focus"] == V["focus"] and m["goal"] == V["goal"]
    assert set(m["tech"].split(", ")) <= set(MASTER["tech"])
    assert m["role"] == "Asian Equities internship" and m["company"] == "Acme Capital"
    assert m["avail"] == cv.availability("T2")


@pytest.mark.parametrize("version", VERSIONS)
def test_posting_keywords_are_never_inserted(version):
    text = cv.to_text(cv.build(MASTER, version, "Acme", "Investment Intern", "T2")).lower()
    for term in ("financial modelling", "dcf", "bloomberg", "vba", "c++", "lbo", "due diligence"):
        if not cv.has_term(cv.master_text(MASTER), term):
            assert not cv.has_term(text, term), term


def test_bullet_selection_only_accepts_master_bullets():
    chosen = cv.selection(MASTER, "DATA")
    chosen["experience"][0] = chosen["experience"][0][:2] + ["Managed a $50m portfolio"]   # not in the master CV
    bullets = [b.text for b in cv.build(MASTER, "DATA", "Acme", "Analyst Intern", "T1", chosen=chosen) if b.kind == "bullet"]
    assert "Managed a $50m portfolio" not in bullets
    assert chosen["experience"][0][0] in bullets


def test_summary_and_headline_edits_are_respected():
    blocks = cv.build(MASTER, "INV", "Acme", "Analyst Intern", "T1", summary="My own words.", headline="MY HEADLINE")
    assert next(b.text for b in blocks if b.kind == "para") == "My own words."
    assert next(b.text for b in blocks if b.kind == "headline") == "MY HEADLINE"


def test_role_phrase():
    assert cv.role_phrase("One Deals Year-End Internship (Dec 26 - Feb 27)") == "One Deals Year-End Internship role"
    assert cv.role_phrase("Internship: Global Markets, Equity Research [Jan - Jun 2027]") == "Global Markets, Equity Research internship"
    assert cv.role_phrase("Wealth Management Intern (Dec 2026 Start)") == "Wealth Management Intern role"


# ---------------- keyword matching ----------------
@pytest.mark.parametrize("text,term,expected", [
    ("portfolio evaluation", "valuation", False),        # the bug this guards against
    ("DCF valuation work", "valuation", True),
    ("NoSQL databases", "sql", False),
    ("SQL and Python", "sql", True),
    ("Power BI dashboards", "dashboard", True),          # plural allowed
    ("financial modeling", "financial modelling", True), # US/UK spelling
    ("root cause analysis", "root-cause", True),        # hyphen/space
    ("riskier trades", "risk", False),
])
def test_whole_phrase_matching(text, term, expected):
    assert cv.has_term(text, term) is expected


def test_keyword_report_three_buckets():
    blocks = cv.build(MASTER, "INV", "Acme", "Investment Intern", "T2")
    rep = cv.keyword_report(blocks, "INV", POSTING + " Tableau dashboards", MASTER)
    assert "python" in rep["covered"] and "sql" in rep["covered"]
    assert "financial modelling" in rep["gaps"] and "bloomberg" in rep["gaps"]   # not evidenced anywhere: add only if true
    assert "valuation" in rep["gaps"]
    assert not set(rep["covered"]) & set(rep["gaps"]) and not set(rep["missing"]) & set(rep["gaps"])


def test_missing_means_available_elsewhere_in_master():
    """A term in the master CV but not in this version's bullets is 'missing', not a 'gap'."""
    chosen = cv.selection(MASTER, "DATA")
    chosen["experience"] = [[b for b in bl if "dashboard" not in b.lower()] for bl in chosen["experience"]]
    chosen["projects"] = [[b for b in bl if "dashboard" not in b.lower()] for bl in chosen["projects"]]
    blocks = cv.build(MASTER, "DATA", "Acme", "Data Analyst Intern", "T1", chosen=chosen,
                      summary="Data science student.", headline="DATA")
    rep = cv.keyword_report(blocks, "DATA", "We use dashboards daily.", MASTER)
    assert "dashboard" in rep["missing"]


# ---------------- PDF ----------------
@pytest.mark.parametrize("version", ["master", *VERSIONS])
def test_pdf_is_one_page_and_text_extractable(version):
    blocks = tailored(version) if version != "master" else cv.build(MASTER)
    pdf = cv.to_pdf(blocks)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert MASTER["name"] in text
    for b in blocks:
        if b.kind == "bullet":
            assert b.text[:25].replace("–", "-").replace("—", "-") in text.replace("\n", " ")


def test_pdf_has_no_encoding_damage():
    text = PdfReader(io.BytesIO(cv.to_pdf(tailored("INV")))).pages[0].extract_text()
    assert "?" not in text   # latin-1 conversion replaces unsupported characters with "?"; none should appear
    assert "Asian Equities internship at Acme Capital" in text.replace("\n", " ")
