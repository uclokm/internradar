from datetime import date

import pytest

from radar import applications as A
from radar.classify import Profile
from radar.identity import fingerprint, normalize_company, normalize_title
from radar.manual import new_row, parse_csv, to_csv, to_jobs

D = date(2026, 10, 1)


def test_status_history_and_applied_date():
    apps = {}
    A.update(apps, "acme|analyst investment", D, status="Shortlisted")
    A.update(apps, "acme|analyst investment", date(2026, 10, 3), status="Applied")
    rec = A.update(apps, "acme|analyst investment", date(2026, 10, 20), status="Interview", interview_on=date(2026, 10, 27))
    assert [s for _, s in rec["history"]] == ["Shortlisted", "Applied", "Interview"]
    assert rec["applied_on"] == "2026-10-03" and rec["interview_on"] == "2026-10-27" and rec["updated_on"] == "2026-10-20"


def test_setting_same_status_does_not_duplicate_history():
    apps = {}
    A.update(apps, "k", D, status="Applying")
    A.update(apps, "k", D, status="Applying", notes="asked Jane for a referral")
    assert len(apps["k"]["history"]) == 1 and apps["k"]["notes"] == "asked Jane for a referral"


def test_unknown_status_rejected():
    with pytest.raises(ValueError):
        A.update({}, "k", D, status="Ghosted")


def test_reached_interview_survives_later_rejection():
    apps = {}
    for s in ("Applied", "Interview", "Rejected"):
        A.update(apps, "k", D, status=s)
    assert A.reached(apps["k"], "Interview") and not A.reached(apps["k"], "Offer")


def test_withdrawn_is_a_supported_status():
    apps = {}
    A.update(apps, "k", D, status="Withdrawn")
    assert apps["k"]["status"] == "Withdrawn" and "Withdrawn" in A.STATUSES


def test_local_store_round_trip_is_atomic(tmp_path):
    store = A.PrivateStore(tmp_path / "private")
    apps = {}
    A.update(apps, "k", D, status="Applied", snapshot={"company": "Acme", "title": "Analyst", "score": 81, "tier": "T2"})
    A.save(store, apps)
    assert A.load(store)["k"]["job"]["score"] == 81
    assert not list((tmp_path / "private").glob("*.tmp"))


def test_demo_store_never_writes(tmp_path):
    store = A.PrivateStore(tmp_path / "private", read_only=True)
    A.save(store, {"k": {"status": "Applied"}})
    assert not (tmp_path / "private").exists()


def test_legacy_statuses_migrate_to_fingerprints():
    old = {"internsg:lion-asian-equities": {"status": "Applied", "notes": "sent", "updated": "2026-09-30"}}
    fp = fingerprint("Lion Global Investors Ltd", "Intern, Asian Equities")
    new = A.migrate_legacy(old, {"internsg:lion-asian-equities": fp})
    assert new[fp]["status"] == "Applied" and new[fp]["applied_on"] == "2026-09-30" and new[fp]["notes"] == "sent"


@pytest.mark.parametrize("a,b", [
    (("Lion Global Investors Ltd", "Intern, Asian Equities"), ("Lion Global Investors Limited", "Asian Equities Intern (Dec 2026, 6 months)")),
    (("PwC Singapore", "One Deals Year-End Internship (Dec 26 - Feb 27)"), ("PwC", "One Deals Year-End Internship")),
    (("OCBC", "Internship: Global IB, Corporate Finance [Jan - Jun 2027]"), ("OCBC Bank", "Internship: Global IB, Corporate Finance [Jan to Jun 2027]")),
])
def test_fingerprint_merges_reposts(a, b):
    assert fingerprint(*a) == fingerprint(*b)


@pytest.mark.parametrize("a,b", [
    (("Franklin Templeton", "Intern (TGI – Equity Research / AI Automation)"), ("Franklin Templeton", "Intern (TGI – Portfolio Management / AI Automation)")),
    (("Temasek", "Intern, Treasury (FX Management)"), ("Temasek", "Intern, Treasury (Debt Capital Market)")),
])
def test_fingerprint_keeps_different_roles_apart(a, b):
    assert fingerprint(*a) != fingerprint(*b)


def test_normalisers():
    assert normalize_company("Keppel (Fund Management & Investment)") == "keppel"
    assert normalize_title("[Keppel Internship Programme 2027] Intern, RE Investment (Jan - May 2027)") == "investment re"


def test_manual_role_is_classified_like_any_other():
    prof = Profile.load()
    row = new_row("Acme Capital", "Private Equity Intern", "https://acme.example/job", "LinkedIn",
                  "Dec 2026 - May 2027", "Support deal screening and valuation work.", "Referral from Sam", D)
    rows = parse_csv(to_csv([row]))
    [job] = to_jobs(rows, prof, D)
    assert (job.tier, job.fit, job.family) == ("T2", "strong", "INV")
    assert job.extra["found_on"] == "LinkedIn" and job.extra["manual_notes"] == "Referral from Sam"


def test_manual_role_without_dates_is_kept_as_unclear():
    [job] = to_jobs([new_row("Acme", "Strategy Intern", "u", "Career fair", "", "", "", D)], Profile.load(), D)
    assert job.tier == "?" and job.fit == "unclear"


def test_hand_assessed_rows_from_earlier_versions_keep_their_tier():
    rows = [{"company": "Citadel", "title": "Sector Data Analyst – Intern (Asia)", "url": "u", "found_on": "jorb.ai",
             "dates": "Flexible (Jun–Aug default)", "tier": "T1", "fit": "stretch", "area": "Hedge Fund / Data", "note": "ask", "added": "2026-09-29"}]
    [job] = to_jobs(rows, Profile.load(), D)
    assert (job.tier, job.fit) == ("T1", "stretch")
