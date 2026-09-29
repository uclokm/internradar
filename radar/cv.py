"""Tailored CVs from a single master CV (config/master_cv.yaml).

What tailoring may do: reorder and choose bullets among the wordings you wrote in the master CV,
reorder coursework and skills, choose one of your headline/focus/goal sentences, and name the
role, company and your availability dates in the summary.
What it never does: add experience, skills, certifications, achievements, numbers or keywords
that aren't in the master CV. A "missing keyword" is shown to you; it is never inserted.

What the tests (tests/test_cv.py) actually guarantee:
  * every bullet, skill, coursework item, certification and award in a tailored CV is copied
    verbatim from the master CV;
  * the summary is assembled only from master-CV sentences (intro, focus, goal), master skills,
    the posting's role title and company, and your availability dates;
  * keywords from a posting that aren't in the master CV never appear in the output.
They do NOT check that the master CV itself is accurate, or that your wording variants are fair
paraphrases of each other — you review those once, in master_cv.yaml.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from fpdf import FPDF

from .paths import CONFIG

# Role expectations are about POSTINGS, not about you, so they live in code: what each family's
# postings commonly ask for. They're used only to report coverage and gaps.
EXPECTED_KEYWORDS = {
    "INV": ["equity research", "investment research", "financial analysis", "financial markets", "excel", "powerpoint", "python", "risk",
            "financial modelling", "valuation", "due diligence", "bloomberg"],
    "AM": ["portfolio", "risk", "diversification", "investment research", "financial markets", "excel", "python", "reporting",
           "performance attribution", "asset allocation", "bloomberg"],
    "DATA": ["python", "sql", "power bi", "tableau", "dashboard", "data integrity", "stakeholder", "excel",
             "pandas", "machine learning", "statistics"],
    "OPS": ["audit", "compliance", "data integrity", "variance analysis", "excel", "risk", "reporting",
            "reconciliation", "settlement", "vba"],
    "STRAT": ["financial analysis", "stakeholder", "cross-functional", "powerpoint", "excel", "insight", "root-cause", "python",
              "market research", "business case"],
}
POSTING_TERMS = ["equity research", "investment research", "investment", "private equity", "private credit", "credit", "portfolio",
                 "asset management", "wealth", "treasury", "fx", "fixed income", "trading", "markets", "risk", "compliance", "operations",
                 "reporting", "data analytics", "analytics", "data science", "dashboard", "power bi", "sql", "python", "automation",
                 "valuation", "m&a", "corporate finance", "strategy", "pricing", "insight", "fintech", "excel", "financial modelling",
                 "tableau", "bloomberg", "vba", "due diligence", "stakeholder", "reconciliation", "statistics", "machine learning"]
_SPELLING = {"modeling": "modelling", "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing"}


def load_master(path: Path | None = None) -> dict:
    """Master CV from $MASTER_CV (YAML text, for hosting), config/master_cv.yaml, or the public example."""
    if path:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    if os.environ.get("MASTER_CV"):
        return yaml.safe_load(os.environ["MASTER_CV"])
    for name in ("master_cv.yaml", "master_cv.example.yaml"):
        p = CONFIG / name
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8"))
    raise FileNotFoundError("No master CV found in config/")


def using_example() -> bool:
    return not os.environ.get("MASTER_CV") and not (CONFIG / "master_cv.yaml").exists()


def versions(master: dict) -> dict:
    return master.get("versions", {})


@dataclass
class Block:
    kind: str       # name | contact | headline | h | row | sub | bullet | para | skill
    text: str
    right: str = ""  # dates for rows; label for skills


def _pick(bank: dict, order: list[str]) -> list[str]:
    """Bullets in the version's order. A variant id missing from this item (e.g. build_data) falls back to its base (build)."""
    out = []
    for k in order:
        k = k if k in bank else k.split("_")[0]
        if k in bank and bank[k] not in out:
            out.append(bank[k])
    return out or list(bank.values())


def availability(tier: str | None) -> str:
    if tier == "T1":
        return "Available full-time from 30 Nov 2026 to 19 Feb 2027."
    if tier == "T2":
        return "Available full-time for up to 6 months from December 2026."
    return ""


def clean_role(title: str) -> str:
    t = re.sub(r"\s*[\[(](?:[^\])]*20\d\d[^\])]*|[^\])]*\bmonths?\b[^\])]*|[^\])]*\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s?'?\d{2}\b[^\])]*)[\])]\s*",
               " ", title, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -–")


def role_phrase(title: str) -> str:
    """'Intern, Asian Equities' -> 'Asian Equities internship'; 'Wealth Management Intern' -> 'Wealth Management Intern role'."""
    t = clean_role(title)
    m = re.match(r"^(?:off-cycle\s+)?intern(?:ship)?\s*[,:\-–]\s*(.+)$", t, re.I)
    if m:
        return m.group(1).strip() + " internship"
    return t + (" role" if re.search(r"intern|trainee|attachment", t, re.I) else " internship")


def default_summary(master: dict, version: str, company: str = "", title: str = "", tier: str | None = None) -> str:
    V = versions(master).get(version)
    if not (V and title):
        return master["summary"]
    return (f"{master['intro']} {V['focus']}. Proficient in {', '.join(V['tech'][:5])}. "
            f"Seeking the {role_phrase(title)} at {company}, where I can {V['goal']}. {availability(tier)}").strip()


def selection(master: dict, version: str) -> dict:
    """Default bullet choice for a version: {"experience": [[texts per item]], "projects": [[...]]}."""
    V = versions(master).get(version, {})
    base = lambda bank: [k for k in bank if "_" not in k]   # the original CV uses base wordings, not variants
    return {
        "experience": [_pick(x["bullets"], V.get("experience", base(x["bullets"]))) for x in master["experience"]],
        "projects": [_pick(p["bullets"], V.get("projects", base(p["bullets"]))) for p in master["projects"]],
    }


def build(master: dict, version: str = "master", company: str = "", title: str = "", tier: str | None = None,
          *, summary: str | None = None, headline: str | None = None, chosen: dict | None = None) -> list[Block]:
    """Assemble a CV. `summary`/`headline` are your own edits; `chosen` picks bullets, and only
    bullets that exist in the master CV are accepted."""
    V = versions(master).get(version)
    chosen = chosen or selection(master, version)
    B = [Block("name", master["name"]), Block("contact", master["contact"]),
         Block("headline", headline or (V["headline"] if V else master["headline"]))]
    B += [Block("h", "SUMMARY"), Block("para", summary or default_summary(master, version, company, title, tier)), Block("h", "EDUCATION")]
    course_order = V["coursework"] if V else list(master["coursework"])
    for e in master["education"]:
        B += [Block("row", e["title"], e["dates"]), Block("sub", e["org"])]
        if e.get("coursework"):
            B.append(Block("bullet", "Relevant coursework: " + ", ".join(master["coursework"][c] for c in course_order if c in master["coursework"])))
    B.append(Block("h", "PROFESSIONAL EXPERIENCE"))
    for x, picked in zip(master["experience"], chosen["experience"]):
        allowed = set(x["bullets"].values())
        B += [Block("row", x["title"], x["dates"]), Block("sub", x["org"])]
        B += [Block("bullet", b) for b in picked if b in allowed]
    B.append(Block("h", "PROJECTS"))
    for p, picked in zip(master["projects"], chosen["projects"]):
        allowed = set(p["bullets"].values())
        B += [Block("row", p["title"]), Block("sub", p["sub"])]
        B += [Block("bullet", b) for b in picked if b in allowed]
    B += [Block("h", "SKILLS"),
          Block("skill", ", ".join(V["tech"] if V else master["tech"]), "Technical:"),
          Block("skill", ", ".join(V["analytical"] if V else master["analytical"]), "Financial & Analytical:"),
          Block("h", "CERTIFICATIONS"), *[Block("bullet", c) for c in master["certifications"]],
          Block("h", "HONORS AND AWARDS"), *[Block("bullet", a) for a in master["awards"]]]
    return B


def to_text(blocks: list[Block]) -> str:
    lines = []
    for b in blocks:
        if b.kind == "h":
            lines += ["", b.text]
        elif b.kind == "bullet":
            lines.append("• " + b.text)
        elif b.kind == "row":
            lines.append(b.text + (f"   {b.right}" if b.right else ""))
        elif b.kind == "skill":
            lines.append(f"{b.right} {b.text}")
        else:
            lines.append(b.text)
    return "\n".join(lines).strip() + "\n"


# ---------------- keyword coverage ----------------
def _norm(text: str) -> str:
    t = text.lower()
    for us, uk in _SPELLING.items():
        t = re.sub(rf"\b{us}\b", uk, t)
    return t


def has_term(text: str, term: str) -> bool:
    """Whole word/phrase match (plural allowed): 'valuation' never matches 'evaluation', 'sql' never 'nosql'."""
    t = re.escape(_norm(term)).replace(r"\ ", r"[\s-]").replace(r"\-", r"[\s-]")
    return re.search(r"(?<![a-z0-9])" + t + r"(?:s|es)?(?![a-z0-9])", _norm(text)) is not None


def master_text(master: dict) -> str:
    """All factual content in the master CV (used to tell 'missing from this version' from 'not on your CV at all')."""
    parts = [master["summary"], master["intro"], " ".join(master["tech"]), " ".join(master["analytical"]),
             " ".join(master["coursework"].values()), " ".join(master["certifications"]), " ".join(master["awards"])]
    for sec in ("experience", "projects"):
        for item in master[sec]:
            parts += [item["title"], item.get("sub", ""), *item["bullets"].values()]
    for V in versions(master).values():
        parts += [V["focus"], V["goal"], V["headline"]]
    return "\n".join(parts)


def keyword_report(blocks: list[Block], version: str, posting_text: str = "", master: dict | None = None) -> dict:
    """covered   – the role asks for it and this CV shows it
       missing   – the role asks for it, this CV version doesn't show it, but your master CV does (pick another bullet/version)
       gaps      – the role asks for it and nothing in your master CV evidences it: add only if true"""
    cv = to_text(blocks)
    full = master_text(master) if master else cv
    wanted = [t for t in POSTING_TERMS if has_term(posting_text, t)] + EXPECTED_KEYWORDS.get(version, EXPECTED_KEYWORDS["DATA"])
    wanted = list(dict.fromkeys(wanted))
    covered = [k for k in wanted if has_term(cv, k)]
    missing = [k for k in wanted if k not in covered and has_term(full, k)]
    gaps = [k for k in wanted if k not in covered and k not in missing]
    return {"covered": covered, "missing": missing, "gaps": gaps}


# ---------------- PDF ----------------
NAVY, INK, MUTED = (31, 56, 100), (27, 36, 48), (74, 85, 99)
_SUBS = {"–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "•": "-", " ": " ", "→": "->"}


def _latin1(s: str) -> str:
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def to_pdf(blocks: list[Block]) -> bytes:
    """A4, one column, real text (not an image) so applicant tracking systems can read it."""
    pdf = FPDF(format="A4", unit="pt")
    pdf.set_title(_latin1(blocks[0].text + " - CV"))
    pdf.set_margins(46, 40, 46)
    pdf.set_auto_page_break(True, margin=40)
    pdf.add_page()
    W = pdf.w - 92
    for b in blocks:
        t = _latin1(b.text)
        if b.kind == "name":
            pdf.set_font("Helvetica", "B", 18); pdf.set_text_color(*NAVY)
            pdf.cell(W, 22, t, align="C", new_x="LMARGIN", new_y="NEXT")
        elif b.kind == "contact":
            pdf.set_font("Helvetica", "", 8.5); pdf.set_text_color(*MUTED)
            pdf.multi_cell(W, 11, t, align="C", new_x="LMARGIN", new_y="NEXT")
        elif b.kind == "headline":
            pdf.set_font("Helvetica", "B", 9.5); pdf.set_text_color(*NAVY)
            pdf.cell(W, 16, t, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(*NAVY); pdf.set_line_width(1.4); pdf.line(46, pdf.get_y() + 1, 46 + W, pdf.get_y() + 1); pdf.ln(4)
        elif b.kind == "h":
            if pdf.get_y() > pdf.h - 90:
                pdf.add_page()
            pdf.ln(7); pdf.set_font("Helvetica", "B", 10.5); pdf.set_text_color(*NAVY)
            pdf.cell(W, 14, t, new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(185, 193, 204); pdf.set_line_width(0.6); pdf.line(46, pdf.get_y(), 46 + W, pdf.get_y()); pdf.ln(3)
        elif b.kind == "row":
            pdf.ln(2); y = pdf.get_y()
            pdf.set_font("Helvetica", "I", 9.5); pdf.set_text_color(*MUTED)
            rw = pdf.get_string_width(_latin1(b.right)) if b.right else 0
            if b.right:
                pdf.set_xy(46 + W - rw, y); pdf.cell(rw, 12.5, _latin1(b.right))
            pdf.set_xy(46, y); pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(*INK)
            pdf.multi_cell(W - rw - 12, 12.5, t, new_x="LMARGIN", new_y="NEXT")
        elif b.kind == "sub":
            pdf.set_font("Helvetica", "I", 9.5); pdf.set_text_color(*MUTED)
            pdf.multi_cell(W, 12, t, new_x="LMARGIN", new_y="NEXT")
        elif b.kind == "bullet":
            pdf.set_font("Helvetica", "", 9.5); pdf.set_text_color(*INK)
            y = pdf.get_y()
            pdf.set_fill_color(*INK); pdf.ellipse(50, y + 5, 2.6, 2.6, style="F")
            pdf.set_x(60); pdf.multi_cell(W - 14, 12.5, t, new_x="LMARGIN", new_y="NEXT")
        elif b.kind == "para":
            pdf.set_font("Helvetica", "", 9.5); pdf.set_text_color(*INK)
            pdf.multi_cell(W, 12.5, t, align="J", new_x="LMARGIN", new_y="NEXT")
        elif b.kind == "skill":
            pdf.set_text_color(*INK)
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.write(12.5, _latin1(b.right) + " ")
            pdf.set_font("Helvetica", "", 9.5)
            pdf.write(12.5, t); pdf.ln(12.5)
    return bytes(pdf.output())
