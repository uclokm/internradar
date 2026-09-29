"""Fictional demo data so a fresh clone of InternRadar has something to show.

    python -m radar.demo        # rebuild data/demo/

Every company here is invented. The postings still go through the real classifier and scorer,
so the demo shows genuine behaviour; the applications are sample statuses for fictional roles.
"""
from __future__ import annotations

import json
import zlib
from datetime import date, timedelta

from .applications import update
from .classify import Profile, classify
from .identity import fingerprint
from .manual import new_row, to_csv
from .models import RawJob
from .paths import DEMO
from .pipeline import job_dict
from .score import score
from .store import connect, log_run, open_postings, upsert

TODAY = date(2026, 9, 29)
_D = ("Responsibilities: you will {duty}. Requirements: currently pursuing a bachelor's degree in finance, economics, "
      "data science or a related field; {skills}. {extra} Allowance: S$1,000 – S$1,500 per month.")

# (source, board, company, title, period text, duty, skills, extra, days since first seen)
POSTINGS = [
    ("greenhouse", "greenhouse:harbourline", "Harbourline Capital", "Private Equity Intern", "From 01 Dec 2026 - 12 Feb 2027",
     "support deal screening, prepare investment memos and industry research", "strong Excel and financial analysis; Python is a plus",
     "Singaporeans and PRs are welcome to apply.", 0),
    ("workday", "workday:merlion", "Merlion Asset Management", "Intern, Asian Equities", "From Dec 2026, For At Least 6 Months",
     "assist portfolio managers with company research and portfolio monitoring", "interest in financial markets; Excel, PowerPoint",
     "Undergraduates only.", 1),
    ("workday", "workday:merlion", "Merlion Asset Management", "Portfolio Analytics Intern (Jan - Jun 2027)", "",
     "build portfolio risk dashboards in Power BI and automate reporting with Python and SQL", "Python, SQL, Power BI; statistics",
     "", 2),
    ("internsg", "internsg", "Kestrel Research Pte Ltd", "Investment Research Intern", "Immediate Start, For At Least 3 Months",
     "write equity research notes and maintain financial models", "financial modelling and valuation; Bloomberg experience preferred",
     "", 0),
    ("greenhouse", "greenhouse:tidewater", "Tidewater Trading", "Trading Operations Intern (Dec 2026 - Feb 2027)", "",
     "support the trading desk with P&L reporting, reconciliation and trade support", "Excel, attention to detail, SQL",
     "", 5),
    ("workable", "workable:ledgerleaf", "LedgerLeaf", "Data Analyst Intern (Finance)", "Jan – May 2027",
     "analyse transaction data and build dashboards for the finance team", "SQL, Python, Tableau; data cleaning",
     "", 3),
    ("internsg", "internsg", "Straits Wealth Partners", "Wealth Management Intern", "From Dec 2026, For At Least 5 Months",
     "prepare client portfolio reviews and investment factsheets", "Excel, PowerPoint, interest in financial markets",
     "", 8),
    ("workday", "workday:orchid", "Orchid Bank", "Internship: Global Markets, Treasury [Jan - Jun 2027]", "",
     "support the treasury desk with FX and liquidity reporting", "Excel, VBA is a plus, risk and reporting",
     "", 10),
    ("greenhouse", "greenhouse:vector", "Vector Quant Partners", "Quantitative Research Intern (Jan - Jun 2027)", "",
     "research systematic trading signals", "C++ and Python, low latency systems, stochastic calculus; PhD preferred",
     "", 4),
    ("internsg", "internsg", "Lumen Consulting", "Strategy & Commercial Analytics Intern", "Flexible Start, Flexible Duration",
     "support market research and business cases for clients", "Excel, PowerPoint, strong stakeholder communication",
     "", 12),
    ("workday", "workday:orchid", "Orchid Bank", "Risk Analytics Intern (Dec 2026 - May 2027)", "",
     "analyse credit risk data and prepare risk reports", "Python, SQL, statistics", "Must have graduated within the last 12 months.", 6),
    ("internsg", "internsg", "Banyan Private Capital", "Private Credit Intern", "From Dec 2026, For At Least 4 Months",
     "analyse borrowers' financial statements and prepare credit memos", "financial analysis, accounting, Excel", "", 15),
    ("greenhouse", "greenhouse:harbourline", "Harbourline Capital", "Investment Analyst Intern (Winter 2026)", "",
     "support the investment team", "Excel", "", 20),
    ("internsg", "internsg", "Pier Seven Advisory", "Corporate Finance Intern", "",
     "support M&A and valuation work", "Excel, financial modelling", "", 9),
]

MANUAL = [  # roles "found on LinkedIn" etc. in the demo
    ("Northwind Asset Management", "Investment Analyst Intern", "https://example.com/northwind", "LinkedIn", "Dec 2026 – Feb 2027",
     "Support the equity team with research and portfolio monitoring using Excel and Python.", "Met the team at a careers fair"),
    ("Coral Fintech", "Pricing Analyst Intern", "https://example.com/coral", "Referral", "",
     "", "Referral from a friend; ask about dates"),
]

APPS = [  # (title, company, [(days ago, status)], extra fields)
    ("Private Equity Intern", "Harbourline Capital", [(0, "Shortlisted")], {}),
    ("Intern, Asian Equities", "Merlion Asset Management", [(1, "Applying")], {"notes": "Tailor CV with the AM version"}),
    ("Trading Operations Intern (Dec 2026 - Feb 2027)", "Tidewater Trading", [(5, "Applied")], {"follow_up_on": -1}),
    ("Data Analyst Intern (Finance)", "LedgerLeaf", [(3, "Applied"), (1, "Interview")], {"interview_on": 3}),
    ("Wealth Management Intern", "Straits Wealth Partners", [(8, "Applied"), (4, "Rejected")], {}),
    ("Private Credit Intern", "Banyan Private Capital", [(15, "Applied"), (10, "Interview"), (6, "Offer")], {}),
    ("Quantitative Research Intern (Jan - Jun 2027)", "Vector Quant Partners", [(4, "Not for me")], {}),
    ("Strategy & Commercial Analytics Intern", "Lumen Consulting", [(12, "Applied"), (7, "Withdrawn")], {}),
]


def build(today: date = TODAY) -> dict:
    DEMO.mkdir(parents=True, exist_ok=True)
    db = DEMO / "demo.db"
    if db.exists():
        db.unlink()
    prof = Profile.load()
    scores = {}
    with connect(db) as con:
        for src, board, company, title, period, duty, skills, extra, ago in POSTINGS:
            raw = RawJob(src, f"{board}-{zlib.crc32(title.encode()) % 10**6}", company, title, f"https://example.com/{board.split(':')[-1]}",
                         location="Singapore", period_text=period, description=_D.format(duty=duty, skills=skills, extra=extra))
            job = classify(raw, prof, today - timedelta(days=ago))
            assert job, f"demo posting was filtered out: {title}"
            s = score(job_dict(job), prof)
            upsert(con, job, board, today - timedelta(days=ago), s)
            scores[fingerprint(company, title)] = (job, s)
        con.execute("UPDATE jobs SET last_seen=?", (today.isoformat(),))
        for board in sorted({p[1] for p in POSTINGS}):
            log_run(con, f"{today.isoformat()}T21:52:00+00:00", board, True, 20, sum(p[1] == board for p in POSTINGS))
        log_run(con, f"{today.isoformat()}T21:52:00+00:00", "workday:example-offline", False, 0, 0, "ConnectionError: demo failure")
        n_open = len(open_postings(con))

    (DEMO / "manual_jobs.csv").write_text(to_csv([new_row(c, t, u, f, d, desc, n, today - timedelta(days=2))
                                                  for c, t, u, f, d, desc, n in MANUAL]), encoding="utf-8")
    apps: dict = {}
    for title, company, steps, extra in APPS:
        fp = fingerprint(company, title)
        job, s = scores[fp]
        snap = {"company": company, "title": title, "family": job.family, "tier": job.tier, "source": job.source,
                "score": s["total"], "url": job.url, "dates": job.dates}
        for ago, status in steps:
            update(apps, fp, today - timedelta(days=ago), status=status, snapshot=snap)
        fields = {k: (today + timedelta(days=v)) if k.endswith("_on") else v for k, v in extra.items()}
        if fields:
            update(apps, fp, today - timedelta(days=steps[-1][0]), **fields)
    (DEMO / "applications.json").write_text(json.dumps(apps, indent=1, sort_keys=True), encoding="utf-8")
    boards = sorted({p[1] for p in POSTINGS})
    summary = {"date": today.isoformat(), "run_at": f"{today.isoformat()}T21:52:00+00:00", "new_relevant": 2, "new_tier1": 1,
               "new_tier2": 1, "new_unclear": 0, "closed": 0, "open": n_open, "boards_configured": len(boards) + 1,
               "boards_checked": len(boards), "boards_failed": 1,
               "boards": [{"board": b, "ok": True, "fetched": 20, "kept": sum(p[1] == b for p in POSTINGS), "error": ""} for b in boards]
               + [{"board": "workday:example-offline", "ok": False, "fetched": 0, "kept": 0, "error": "ConnectionError: demo failure"}]}
    (DEMO / "last_run.json").write_text(json.dumps(summary, indent=2))
    (DEMO / "latest.md").write_text(
        f"# InternRadar — demo data\n\nFictional companies. {n_open} open roles · checked {len(boards)} of {len(boards) + 1} "
        "configured boards · **1 failed**\n\n## Boards that could not be checked\n- `workday:example-offline` — ConnectionError: demo failure\n",
        encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps({k: v for k, v in build().items() if k != "boards"}, indent=2))
