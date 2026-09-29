import sqlite3
from datetime import date

from radar.classify import Profile, classify
from radar.models import RawJob
from radar.store import close_missing, connect, open_jobs, open_postings, upsert

PROF = Profile.load()
TITLES = {1: "Investment Analyst Internship (Dec 2026 - May 2027)", 2: "Equity Research Internship (Dec 2026 - May 2027)"}


def job(i, title=None, source="internsg", company="Acme"):
    return classify(RawJob(source, f"j{i}", company, title or TITLES.get(i, TITLES[1]), f"https://x/{i}"), PROF, date(2026, 9, 29))


def test_new_seen_and_closed(tmp_path):
    db = tmp_path / "t.db"
    d1, d2 = date(2026, 9, 29), date(2026, 9, 30)
    with connect(db) as con:
        assert upsert(con, job(1), "internsg", d1) is True        # new
        assert upsert(con, job(2), "internsg", d1) is True        # a different role
    with connect(db) as con:
        assert upsert(con, job(1), "internsg", d2) is False       # already known
        gone = close_missing(con, "internsg", {job(1).key}, d2)   # job 2 disappeared
        assert [r["key"] for r in gone] == [job(2).key]
        assert [r["key"] for r in open_jobs(con)] == [job(1).key]
        assert upsert(con, job(2), "internsg", d2) is True        # re-opened counts as new


def test_repost_is_not_new(tmp_path):
    """InternSG reposts a role under a new URL: same fingerprint, so no second 'new' alert."""
    with connect(tmp_path / "t.db") as con:
        assert upsert(con, job(1), "internsg", date(2026, 9, 29)) is True
        repost = job(3, title="Investment Analyst Intern (Dec 2026 – May 2027)", company="Acme Pte. Ltd.")
        assert upsert(con, repost, "internsg", date(2026, 10, 5)) is False
        postings = open_postings(con)
        assert len(postings) == 1 and postings[0]["first_seen"] == "2026-09-29"


def test_same_role_on_two_boards_shows_once_and_prefers_company_site(tmp_path):
    with connect(tmp_path / "t.db") as con:
        upsert(con, job(1, source="internsg"), "internsg", date(2026, 9, 29))
        upsert(con, job(9, source="workday", title="Intern, Investment Analyst [Dec 2026 to May 2027]"), "workday:acme", date(2026, 9, 30))
        [p] = open_postings(con)
        assert p["source"] == "workday" and p["sources"] == ["internsg", "workday"]


def test_closure_reported_only_when_no_other_listing_remains(tmp_path):
    with connect(tmp_path / "t.db") as con:
        upsert(con, job(1, source="internsg"), "internsg", date(2026, 9, 29))
        upsert(con, job(9, source="workday"), "workday:acme", date(2026, 9, 29))
        assert close_missing(con, "internsg", set(), date(2026, 9, 30)) == []      # still open on Workday
        assert len(close_missing(con, "workday:acme", set(), date(2026, 9, 30))) == 1


def test_old_database_migrates_in_place(tmp_path):
    """A database from the first version (no fingerprint/score columns) upgrades without data loss."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE jobs (key TEXT PRIMARY KEY, board TEXT NOT NULL, source TEXT NOT NULL, company TEXT, title TEXT, url TEXT,
        location TEXT, posted TEXT, dates TEXT, start TEXT, "end" TEXT, min_months REAL, tier TEXT, fit TEXT, family TEXT,
        area TEXT, note TEXT, description TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, closed_on TEXT);
      CREATE TABLE runs (run_at TEXT, board TEXT, ok INTEGER, fetched INTEGER, kept INTEGER, error TEXT);
      INSERT INTO jobs (key, board, source, company, title, url, first_seen, last_seen)
        VALUES ('internsg:x', 'internsg', 'internsg', 'Lion Global Investors Ltd', 'Intern, Asian Equities', 'u', '2026-09-01', '2026-09-28');
    """)
    con.commit(); con.close()
    with connect(db) as con:
        row = con.execute("SELECT * FROM jobs").fetchone()
        assert row["fingerprint"] == "lion global investors|asian equities"
        assert row["first_seen"] == "2026-09-01" and row["score"] is None
        assert con.execute("PRAGMA user_version").fetchone()[0] >= 2
