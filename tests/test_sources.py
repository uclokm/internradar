"""Parsers are tested against real response shapes captured from each site (tests/fixtures)."""
import json
from datetime import date
from pathlib import Path

from radar.sources import greenhouse, internsg, workable, workday

FX = Path(__file__).parent / "fixtures"
load = lambda n: json.loads((FX / n).read_text())


def test_greenhouse_keeps_singapore_only_and_cleans_html():
    jobs = greenhouse.parse(load("greenhouse_drweng.json"), "DRW", "drweng")
    assert [j.title for j in jobs] == ["IT Intern", "Trading Operations Intern (Dec 2026 - Feb 2027)", "ECM Portfolio Manager"]
    j = jobs[1]
    assert j.key == "greenhouse:drweng-9000001"
    assert j.posted == date(2026, 9, 20)
    assert "P&L reporting" in j.description and "<" not in j.description


def test_workday_detail():
    cfg = {"tenant": "ocbc", "host": "wd102", "site": "External", "company": "OCBC"}
    lst = workday.parse_list(load("workday_ocbc_list.json"))
    assert len(lst) == 2
    job = workday.parse_detail(load("workday_ocbc_detail.json"), cfg, lst[0], date(2026, 9, 29))
    assert job.external_id == "ocbc-JR00011432"
    assert job.url.startswith("https://ocbc.wd102.myworkdayjobs.com/External/job/")
    assert "at least 6 months" in job.description
    assert workday.posted_on("Posted 3 Days Ago", date(2026, 9, 29)) == date(2026, 9, 26)
    assert workday.posted_on("Posted 30+ Days Ago", date(2026, 9, 29)) == date(2026, 8, 30)


def test_workable():
    cfg = {"account": "qcp-group", "company": "QCP"}
    sg = workable.parse_list(load("workable_qcp_list.json"))
    assert [j["shortcode"] for j in sg] == ["6B1690698E", "982BD19023"]   # Hong Kong role dropped
    job = workable.parse_detail(load("workable_qcp_detail.json"), cfg)
    assert job.url == "https://apply.workable.com/qcp-group/j/6B1690698E/"
    assert job.department == "Market Risk" and "FX, Rates" in job.description


def test_internsg_listing_and_detail():
    rows = internsg.parse_listing((FX / "internsg_list.html").read_text())
    assert rows[0] == {"slug": "lion-global-investors-ltd-intern-multi-asset-strategies-team-mast",
                       "title": "Intern, Multi-Asset Strategies Team (MAST)", "company": "Lion Global Investors Ltd",
                       "location": "Downtown Core, SG", "period": "From Jan 2027, For At Least 6 Months"}
    job = internsg.parse_detail((FX / "internsg_detail.html").read_text(), rows[0])
    assert job.posted == date(2026, 9, 15)
    assert job.period_text == "From Jan 2027, For At Least 6 Months"
    assert "performance attribution" in job.description
    assert internsg.parse_detail((FX / "internsg_closed.html").read_text(), rows[1]) is None
