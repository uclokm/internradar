"""Your application tracker (private).

Stored as JSON in data/private/applications.json (git-ignored), or in a private GitHub repo when
the app is hosted. It is deliberately separate from data/radar.db: the job database is public
data committed by the daily run, while this file is your personal history.

Records are keyed by job fingerprint (company + role), so a status survives reposts and the same
role appearing on a different board. Each record keeps a small snapshot of the job so analytics
still work after a posting closes.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

STATUSES = ["Not started", "Shortlisted", "Applying", "Applied", "Interview", "Offer", "Rejected", "Withdrawn", "Not for me"]
PIPELINE = ["Shortlisted", "Applying", "Applied", "Interview", "Offer"]
ACTIVE = {"Shortlisted", "Applying", "Applied", "Interview"}
SUBMITTED = {"Applied", "Interview", "Offer", "Rejected", "Withdrawn"}   # statuses that imply an application went in
CLOSED_OUT = ["Rejected", "Withdrawn", "Not for me"]
DATE_FIELDS = ("applied_on", "follow_up_on", "interview_on")
SNAPSHOT_FIELDS = ("company", "title", "family", "tier", "source", "score", "url", "dates")


# ---------------- storage backends ----------------
@dataclass
class PrivateStore:
    """Reads/writes small private text files, locally or in a private GitHub repo."""
    directory: Path
    github_token: str | None = None
    github_repo: str | None = None      # "user/private-repo"
    read_only: bool = False             # demo mode: nothing is written anywhere

    @property
    def remote(self) -> bool:
        return bool(self.github_token and self.github_repo)

    def _api(self, name: str) -> str:
        return f"https://api.github.com/repos/{self.github_repo}/contents/{name}"

    def read(self, name: str) -> str | None:
        if self.remote:
            r = requests.get(self._api(name), headers={"Authorization": f"Bearer {self.github_token}"}, timeout=15)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return base64.b64decode(r.json()["content"]).decode("utf-8")
        p = self.directory / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write(self, name: str, text: str) -> None:
        if self.read_only:
            return
        if self.remote:
            h = {"Authorization": f"Bearer {self.github_token}"}
            cur = requests.get(self._api(name), headers=h, timeout=15)
            payload = {"message": f"Update {name}", "content": base64.b64encode(text.encode()).decode()}
            if cur.ok:
                payload["sha"] = cur.json()["sha"]
            requests.put(self._api(name), headers=h, json=payload, timeout=15).raise_for_status()
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.directory / (name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.directory / name)   # atomic: never leaves a half-written file


# ---------------- records ----------------
def load(store: PrivateStore) -> dict:
    text = store.read("applications.json")
    return json.loads(text) if text else {}


def save(store: PrivateStore, apps: dict) -> None:
    store.write("applications.json", json.dumps(apps, indent=1, sort_keys=True, ensure_ascii=False))


def update(apps: dict, fp: str, today: date, *, status: str | None = None, snapshot: dict | None = None, **fields) -> dict:
    """Change one record. Moving to a new status is added to its history; moving to a submitted
    status (Applied or later) fills applied_on if you haven't set it."""
    rec = apps.setdefault(fp, {"status": "Not started", "history": []})
    if status and status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    if status and status != rec.get("status"):
        rec["status"] = status
        rec.setdefault("history", []).append([today.isoformat(), status])
        if status in SUBMITTED and not rec.get("applied_on"):
            rec["applied_on"] = today.isoformat()
    for k, v in fields.items():
        if k in DATE_FIELDS:
            rec[k] = v.isoformat() if isinstance(v, date) else (v or None)
        elif k == "notes":
            rec[k] = v or ""
    if snapshot:
        rec["job"] = {k: snapshot.get(k) for k in SNAPSHOT_FIELDS if snapshot.get(k) is not None}
    rec["updated_on"] = today.isoformat()
    return rec


def reached(rec: dict, status: str) -> bool:
    """Did this application ever reach `status` (e.g. Interview), even if it later changed?"""
    order = PIPELINE.index(status)
    seen = {s for _, s in rec.get("history", [])} | {rec.get("status")}
    return any(s in PIPELINE and PIPELINE.index(s) >= order for s in seen)


def migrate_legacy(apps_old: dict, key_to_fp: dict[str, str]) -> dict:
    """Convert the earlier format ({job_key: {status, notes, updated}}) to fingerprint-keyed records."""
    out = {}
    for key, rec in apps_old.items():
        fp = key_to_fp.get(key, key)
        status = rec.get("status", "Not started")
        out[fp] = {"status": status, "notes": rec.get("notes", ""), "updated_on": rec.get("updated"),
                   "history": [[rec.get("updated") or date.today().isoformat(), status]] if status != "Not started" else []}
        if status in SUBMITTED:
            out[fp]["applied_on"] = rec.get("updated")
    return out
