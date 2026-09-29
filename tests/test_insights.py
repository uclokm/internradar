import json
from datetime import date, timedelta

from radar import applications as A
from radar import insights as I

T = date(2026, 10, 10)


def job(fp, score, days_ago):
    return {"fp": fp, "company": fp.upper(), "title": "Intern", "score": score, "first_seen": (T - timedelta(days=days_ago)).isoformat()}


def test_priorities_order_and_content():
    jobs = [job("a", 90, 0), job("b", 60, 0), job("c", 85, 10), job("d", 88, 1)]
    apps = {}
    A.update(apps, "d", T, status="Interview", interview_on=T + timedelta(days=2))
    A.update(apps, "e", T, status="Applied", follow_up_on=T - timedelta(days=1), snapshot={"company": "E", "title": "Analyst"})
    A.update(apps, "f", T, status="Applying", snapshot={"company": "F", "title": "Intern"})
    kinds = [i["kind"] for i in I.priorities(jobs, apps, T)]
    assert kinds == ["Interview", "Follow up", "Finish application", "New match", "Worth applying"]
    items = I.priorities(jobs, apps, T)
    assert items[3]["fp"] == "a"            # new and high-scoring; "b" scored too low to surface
    assert items[4]["fp"] == "c"            # strong but older, not yet shortlisted
    assert "E — Analyst" in items[1]["text"]  # closed postings still show via the snapshot


def test_no_fake_urgency():
    """No dates set and no strong untracked roles -> nothing to do."""
    jobs = [job("a", 50, 20)]
    apps = {}
    A.update(apps, "a", T, status="Applied")
    assert I.priorities(jobs, apps, T) == []


def test_future_follow_up_is_not_due_yet():
    apps = {}
    A.update(apps, "a", T, status="Applied", follow_up_on=T + timedelta(days=3))
    assert I.priorities([], apps, T) == []


def test_summary_rates_need_enough_data():
    apps = {}
    A.update(apps, "a", T, status="Applied")
    A.update(apps, "b", T, status="Interview")
    s = I.summary(apps)
    assert s["applications"] == 2 and s["interviews"] == 1 and s["app_to_interview"] is None   # fewer than 3 applications


def test_summary_funnel():
    apps = {}
    for fp, path in {"a": ["Applied"], "b": ["Applied", "Interview", "Rejected"], "c": ["Applied", "Interview", "Offer"],
                     "d": ["Applied", "Withdrawn"], "e": ["Shortlisted"], "f": ["Not for me"]}.items():
        for s in path:
            A.update(apps, fp, T, status=s)
    s = I.summary(apps)
    assert (s["applications"], s["interviews"], s["offers"], s["rejections"], s["withdrawn"]) == (4, 2, 1, 1, 1)
    assert s["app_to_interview"] == 50 and s["interview_to_offer"] is None   # only 2 interviews
    assert s["active"] == 2   # a (Applied) and e (Shortlisted)


def test_breakdown_and_score_vs_outcome():
    apps = {}
    for i, (score, reach) in enumerate([(90, True), (85, True), (80, False), (60, False), (55, False), (50, True)]):
        A.update(apps, str(i), T, status="Applied", snapshot={"family": "INV" if score > 70 else "DATA", "score": score})
        if reach:
            A.update(apps, str(i), T, status="Interview")
    assert I.breakdown(apps, "family") == {"INV": 3, "DATA": 3}
    rows = I.score_vs_outcome(apps)
    assert rows[0] == {"group": "Score ≥ 75", "applications": 3, "interview_rate": 67}
    assert I.score_vs_outcome({k: apps[k] for k in list(apps)[:4]}) is None   # too few low-score applications


def test_demo_data_builds_and_is_consistent(tmp_path, monkeypatch):
    import radar.demo as demo
    monkeypatch.setattr(demo, "DEMO", tmp_path)
    summary = demo.build()
    apps = json.loads((tmp_path / "applications.json").read_text())
    assert summary["open"] == len(demo.POSTINGS) and len(apps) == len(demo.APPS)
    assert all(r["job"]["score"] for r in apps.values())
    assert I.summary(apps)["offers"] == 1
