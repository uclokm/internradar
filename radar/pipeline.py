"""InternRadar daily run: fetch every configured board, classify, score, store, and report.

    python -m radar.pipeline run                   # all boards
    python -m radar.pipeline run --only internsg   # boards whose id starts with this
    python -m radar.pipeline check                 # quick health check: does each board still respond?
    python -m radar.pipeline report                # print the latest change report

Only public, automatically collected postings go into data/radar.db. Roles you add by hand live in
your private store (see radar/manual.py) and are merged in by the app, never written here.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import yaml

from .classify import Profile, classify, title_candidate
from .models import Job
from .paths import CONFIG, DATA, DB_PATH
from .score import score
from .sources import greenhouse, internsg, workable, workday
from .store import close_missing, connect, log_run, open_postings, upsert

TZ = ZoneInfo(os.environ.get("RADAR_TZ", "Australia/Melbourne"))
log = logging.getLogger("internradar")


def job_dict(job: Job) -> dict:
    """The fields the scorer needs, from a Job."""
    d = {k: getattr(job, k) for k in ("title", "tier", "fit", "start", "end", "min_months", "description", "location", "source")}
    d.update(department=job.extra.get("department", ""), approximate=job.extra.get("approximate", False),
             max_months=job.extra.get("max_months"))
    return d


def boards(cfg: dict):
    """Yield (board_id, fetch, probe) for every configured board."""
    for c in cfg.get("greenhouse", []):
        yield f"greenhouse:{c['token']}", (lambda c=c, **k: greenhouse.fetch(c)), (lambda c=c: greenhouse.probe(c))
    for c in cfg.get("workday", []):
        yield f"workday:{c['tenant']}", (lambda c=c, **k: workday.fetch(c, is_candidate=k["is_candidate"])), (lambda c=c: workday.probe(c))
    for c in cfg.get("workable", []):
        yield f"workable:{c['account']}", (lambda c=c, **k: workable.fetch(c, is_candidate=k["is_candidate"])), (lambda c=c: workable.probe(c))
    if cfg.get("internsg"):
        yield "internsg", (lambda **k: internsg.fetch(cfg["internsg"], is_candidate=k["is_candidate"])), (lambda: internsg.probe(cfg["internsg"]))


def load_sources() -> dict:
    return yaml.safe_load((CONFIG / "sources.yaml").read_text())


def run(only: str | None = None, today: date | None = None) -> dict:
    today = today or datetime.now(TZ).date()
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prof = Profile.load()
    cfg = load_sources()

    def is_candidate(title: str) -> bool:
        return title_candidate(title, prof)

    new: list[tuple[Job, dict]] = []
    closed, results = [], []
    with connect(DB_PATH) as con:
        for board, fetch, _ in boards(cfg):
            if only and not board.startswith(only):
                continue
            try:
                raws = fetch(is_candidate=is_candidate)
            except Exception as e:  # one bad board must not stop the run
                log.warning("%-40s FAILED: %s", board, e)
                results.append({"board": board, "ok": False, "fetched": 0, "kept": 0, "error": f"{type(e).__name__}: {e}"[:300]})
                log_run(con, run_at, board, False, 0, 0, str(e))
                continue   # a failed board never closes its postings
            seen = set()
            for raw in raws:
                job = classify(raw, prof, today)
                if not job:
                    continue
                s = score(job_dict(job), prof)
                seen.add(job.key)
                if upsert(con, job, board, today, s):
                    new.append((job, s))
            closed += close_missing(con, board, seen, today)
            results.append({"board": board, "ok": True, "fetched": len(raws), "kept": len(seen), "error": ""})
            log_run(con, run_at, board, True, len(raws), len(seen))
            log.info("%-40s fetched %3d  kept %3d", board, len(raws), len(seen))
        postings = open_postings(con)

    return write_outputs(postings, new, closed, results, today, run_at)


def write_outputs(postings: list[dict], new: list[tuple[Job, dict]], closed, results: list[dict], today: date, run_at: str) -> dict:
    (DATA / "changes").mkdir(parents=True, exist_ok=True)
    fields = ["score", "tier", "fit", "company", "title", "dates", "area", "source", "url", "first_seen", "note"]
    with (DATA / "jobs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in sorted(postings, key=lambda r: -(r.get("score") or 0)):
            w.writerow(r)

    relevant = sorted([(j, s) for j, s in new if j.tier in ("T1", "T2")], key=lambda x: -x[1]["total"])
    unclear = [(j, s) for j, s in new if j.tier not in ("T1", "T2")]
    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    line = lambda j, s: f"- **{s['total']}** · **{j.company}** — [{j.title}]({j.url}) · {j.dates} · {'Tier 1' if j.tier == 'T1' else 'Tier 2'} ({j.fit})"
    md = [f"# InternRadar — {today:%a %d %b %Y}", "",
          f"{len(relevant)} new relevant role(s) · {len(closed)} closed · {len(postings)} open · "
          f"checked {len(ok)} of {len(results)} configured boards" + (f" · **{len(failed)} failed**" if failed else "")]
    if relevant:
        md += ["", "## New roles (highest score first)", *[line(j, s) for j, s in relevant]]
    if unclear:
        md += ["", "## New, dates unclear (worth a manual look)", *[f"- {j.company} — [{j.title}]({j.url})" for j, _ in unclear]]
    if closed:
        md += ["", "## Closed since the last run", *[f"- {r['company']} — {r['title']}" for r in closed]]
    if failed:
        md += ["", "## Boards that could not be checked", "Their postings were left open (not marked closed).",
               *[f"- `{r['board']}` — {r['error']}" for r in failed]]
    text = "\n".join(md) + "\n"
    (DATA / "changes" / f"{today.isoformat()}.md").write_text(text, encoding="utf-8")
    (DATA / "changes" / "latest.md").write_text(text, encoding="utf-8")
    summary = {
        "date": today.isoformat(), "run_at": run_at,
        "new_relevant": len(relevant), "new_tier1": sum(j.tier == "T1" for j, _ in relevant),
        "new_tier2": sum(j.tier == "T2" for j, _ in relevant), "new_unclear": len(unclear),
        "closed": len(closed), "open": len(postings),
        "boards_configured": len(results), "boards_checked": len(ok), "boards_failed": len(failed),
        "boards": results,
    }
    (DATA / "last_run.json").write_text(json.dumps(summary, indent=2))
    return summary


def check() -> list[dict]:
    """Probe each configured board's list endpoint once, without storing anything."""
    out = []
    for board, _, probe in boards(load_sources()):
        try:
            n = probe()
            out.append({"board": board, "ok": True, "detail": f"{n} postings listed"})
        except Exception as e:
            out.append({"board": board, "ok": False, "detail": f"{type(e).__name__}: {e}"[:160]})
        print(f"{'OK  ' if out[-1]['ok'] else 'FAIL'}  {board:40} {out[-1]['detail']}")
    ok = sum(r["ok"] for r in out)
    print(f"\n{ok} of {len(out)} configured boards responded.")
    return out


def main():
    ap = argparse.ArgumentParser(description="InternRadar pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch, classify, score and store today's postings")
    r.add_argument("--only", help="limit to boards starting with this, e.g. internsg or workday:ocbc")
    sub.add_parser("check", help="check which configured boards respond (stores nothing)")
    sub.add_parser("report", help="print the latest change report")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.cmd == "run":
        summary = run(args.only)
        print(json.dumps({k: v for k, v in summary.items() if k != "boards"}, indent=2))
        if summary["boards_configured"] and not summary["boards_checked"]:
            sys.exit("No board could be checked; see data/changes/latest.md")   # fails the GitHub Action
    elif args.cmd == "check":
        check()
    else:
        print((DATA / "changes" / "latest.md").read_text())


if __name__ == "__main__":
    main()
