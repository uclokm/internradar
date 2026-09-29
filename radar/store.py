"""SQLite storage for collected postings, with change tracking and safe schema migration.

Identity has two levels:
  key          one posting on one board, e.g. "workday:ocbc-JR00011432" (drives close detection)
  fingerprint  normalised company + title (drives deduplication across boards and reposts)

A posting counts as NEW only when neither its key nor its fingerprint has been seen recently,
so an InternSG repost or the same role on two sites doesn't raise a second alert.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from .identity import fingerprint
from .models import Job

SCHEMA_VERSION = 2
BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  key TEXT PRIMARY KEY,
  board TEXT NOT NULL,
  source TEXT NOT NULL,
  company TEXT, title TEXT, url TEXT, location TEXT,
  posted TEXT, dates TEXT, start TEXT, "end" TEXT, min_months REAL,
  tier TEXT, fit TEXT, family TEXT, area TEXT, note TEXT, description TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, closed_on TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  run_at TEXT, board TEXT, ok INTEGER, fetched INTEGER, kept INTEGER, error TEXT
);
"""
# Columns added after version 1. Migration adds whichever are missing, so older databases upgrade in place.
ADDED_COLUMNS = {
    "fingerprint": "TEXT", "max_months": "REAL", "department": "TEXT",
    "score": "INTEGER", "score_json": "TEXT", "approximate": "INTEGER DEFAULT 0",
}
SOURCE_RANK = {"greenhouse": 0, "workday": 0, "workable": 0, "internsg": 1, "manual": 2}
REPOST_WINDOW_DAYS = 45


def migrate(con: sqlite3.Connection) -> None:
    """Bring any older database up to SCHEMA_VERSION without losing data."""
    con.executescript(BASE_SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    for col, typ in ADDED_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
    for key, company, title in con.execute("SELECT key, company, title FROM jobs WHERE fingerprint IS NULL").fetchall():
        con.execute("UPDATE jobs SET fingerprint=? WHERE key=?", (fingerprint(company, title), key))
    con.execute("CREATE INDEX IF NOT EXISTS jobs_open ON jobs(closed_on)")
    con.execute("CREATE INDEX IF NOT EXISTS jobs_fp ON jobs(fingerprint)")
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextmanager
def connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    migrate(con)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def upsert(con: sqlite3.Connection, job: Job, board: str, today: date, score: dict | None = None) -> bool:
    """Insert or refresh a job. Returns True only for a genuinely new posting (not a repost/duplicate)."""
    fp = fingerprint(job.company, job.title)
    row = con.execute("SELECT closed_on FROM jobs WHERE key=?", (job.key,)).fetchone()
    recent = (today - timedelta(days=REPOST_WINDOW_DAYS)).isoformat()
    twin = con.execute(
        "SELECT 1 FROM jobs WHERE fingerprint=? AND key<>? AND (closed_on IS NULL OR closed_on>=?) LIMIT 1",
        (fp, job.key, recent)).fetchone()
    d = {k: _iso(v) for k, v in asdict(job).items() if k != "extra"}
    extra = job.extra or {}
    values = {
        "board": board, "source": d["source"], "company": d["company"], "title": d["title"], "url": d["url"],
        "location": d["location"], "posted": d["posted"], "dates": d["dates"], "start": d["start"], "end": d["end"],
        "min_months": d["min_months"], "tier": d["tier"], "fit": d["fit"], "family": d["family"], "area": d["area"],
        "note": d["note"], "description": d["description"], "fingerprint": fp,
        "max_months": extra.get("max_months"), "department": extra.get("department", ""),
        "approximate": int(bool(extra.get("approximate"))),
        "score": score["total"] if score else None, "score_json": json.dumps(score) if score else None,
    }
    if row is None:
        cols = ["key", *values, "first_seen", "last_seen"]
        con.execute(f'INSERT INTO jobs ({",".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({",".join("?" * len(cols))})',
                    [job.key, *values.values(), today.isoformat(), today.isoformat()])
        return twin is None
    sets = ",".join(f'"{c}"=?' for c in values)
    con.execute(f"UPDATE jobs SET {sets}, last_seen=?, closed_on=NULL WHERE key=?", [*values.values(), today.isoformat(), job.key])
    return row["closed_on"] is not None and twin is None


def close_missing(con: sqlite3.Connection, board: str, seen: set[str], today: date) -> list[sqlite3.Row]:
    """Mark jobs from a SUCCESSFULLY checked board as closed if they weren't seen today.
    Never call this for a board whose fetch failed."""
    rows = con.execute("SELECT * FROM jobs WHERE board=? AND closed_on IS NULL", (board,)).fetchall()
    gone = [r for r in rows if r["key"] not in seen]
    con.executemany("UPDATE jobs SET closed_on=? WHERE key=?", [(today.isoformat(), r["key"]) for r in gone])
    # Report a closure only if no other open listing of the same role remains.
    return [r for r in gone if not con.execute(
        "SELECT 1 FROM jobs WHERE fingerprint=? AND closed_on IS NULL LIMIT 1", (r["fingerprint"],)).fetchone()]


def open_jobs(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM jobs WHERE closed_on IS NULL ORDER BY first_seen DESC, tier, company").fetchall()


def open_postings(con: sqlite3.Connection) -> list[dict]:
    """One entry per role: duplicates across boards/reposts are merged. The company's own board is
    preferred over InternSG; `first_seen` is the earliest sighting and `sources` lists every board."""
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in open_jobs(con):
        groups.setdefault(r["fingerprint"], []).append(r)
    earliest = dict(con.execute("SELECT fingerprint, MIN(first_seen) FROM jobs GROUP BY fingerprint").fetchall())
    out = []
    for fp, rows in groups.items():
        best = min(rows, key=lambda r: (SOURCE_RANK.get(r["source"], 3), -len(r["description"] or "")))
        rec = dict(best)
        rec["first_seen"] = earliest.get(fp, best["first_seen"])
        rec["sources"] = sorted({r["source"] for r in rows})
        out.append(rec)
    return out


def log_run(con, run_at: str, board: str, ok: bool, fetched: int, kept: int, error: str = ""):
    con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (run_at, board, int(ok), fetched, kept, error[:500]))
