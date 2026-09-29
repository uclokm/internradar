"""End-to-end daily run with the network replaced by recorded fixtures."""
import json
from datetime import date
from pathlib import Path

import radar.pipeline as pl
from radar.classify import Profile, title_candidate
from radar.sources import greenhouse, internsg, workable, workday
from radar.store import connect

FX = Path(__file__).parent / "fixtures"
never = lambda: 0


def fake_sources(monkeypatch, drop_lion=False):
    monkeypatch.setattr(pl, "boards", lambda cfg: [
        ("greenhouse:drweng", lambda **k: greenhouse.parse(json.loads((FX / "greenhouse_drweng.json").read_text()), "DRW", "drweng"), never),
        ("workday:ocbc", lambda **k: [workday.parse_detail(json.loads((FX / "workday_ocbc_detail.json").read_text()),
                                                          {"tenant": "ocbc", "host": "wd102", "site": "External", "company": "OCBC"},
                                                          workday.parse_list(json.loads((FX / "workday_ocbc_list.json").read_text()))[0], date(2026, 9, 29))], never),
        ("workable:qcp-group", lambda **k: [workable.parse_detail(json.loads((FX / "workable_qcp_detail.json").read_text()), {"account": "qcp-group", "company": "QCP"})], never),
        ("internsg", lambda **k: [] if drop_lion else [internsg.parse_detail((FX / "internsg_detail.html").read_text(),
                                                                             internsg.parse_listing((FX / "internsg_list.html").read_text())[0])], never),
        ("workday:broken", lambda **k: (_ for _ in ()).throw(ConnectionError("down")), never),
    ])


def test_daily_run(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(pl, "DATA", tmp_path)
    fake_sources(monkeypatch)

    day1 = pl.run(today=date(2026, 9, 29))
    # DRW trading-ops intern (T1), OCBC Jan–Jun (T2), QCP risk Jan–Jun (T2), Lion Global Jan 2027 + 6 months (T2)
    assert day1["new_relevant"] == 4 and day1["new_tier1"] == 1 and day1["new_tier2"] == 3
    assert (day1["boards_configured"], day1["boards_checked"], day1["boards_failed"]) == (5, 4, 1)
    assert [b["board"] for b in day1["boards"] if not b["ok"]] == ["workday:broken"]
    report = (tmp_path / "changes" / "latest.md").read_text()
    assert report.startswith("# InternRadar")
    assert "Trading Operations Intern" in report and "could not be checked" in report
    assert "checked 4 of 5 configured boards" in report
    rows = (tmp_path / "jobs.csv").read_text().splitlines()
    assert len(rows) == 5 and rows[0].startswith("score,")

    with connect(tmp_path / "radar.db") as con:   # every stored job has a score and breakdown
        scored = con.execute("SELECT score, score_json FROM jobs").fetchall()
        assert all(r["score"] is not None and json.loads(r["score_json"])["parts"] for r in scored)

    fake_sources(monkeypatch, drop_lion=True)
    day2 = pl.run(today=date(2026, 9, 30))
    assert day2["new_relevant"] == 0 and day2["closed"] == 1 and day2["open"] == 3
    assert "Lion Global Investors" in (tmp_path / "changes" / "latest.md").read_text()


def test_failed_board_never_closes_its_postings(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(pl, "DATA", tmp_path)
    fake_sources(monkeypatch)
    pl.run(today=date(2026, 9, 29))
    monkeypatch.setattr(pl, "boards", lambda cfg: [
        ("internsg", lambda **k: (_ for _ in ()).throw(TimeoutError("slow")), never)])
    day2 = pl.run(today=date(2026, 9, 30))
    assert day2["closed"] == 0 and day2["open"] == 4 and day2["boards_checked"] == 0


def test_title_prefilter_skips_detail_fetches_for_excluded_roles():
    prof = Profile.load()
    assert title_candidate("Investment Analyst Intern", prof)
    assert title_candidate("Risk Intern", prof)
    assert not title_candidate("Marketing Intern", prof)
    assert not title_candidate("Software Engineer Intern (Data)", prof)
    assert not title_candidate("Investment Analyst", prof)   # not an internship
