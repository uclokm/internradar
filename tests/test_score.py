from datetime import date

import pytest
import yaml

from radar.classify import Profile, classify
from radar.models import RawJob
from radar.paths import CONFIG
from radar.score import WEIGHTS, label_for, score

PROF = Profile.load()
TODAY = date(2026, 9, 29)
RICH = ("Responsibilities: you will support the investment team with company and industry research, prepare "
        "investment memos and build analyses in Excel and Python. Requirements: currently pursuing a bachelor's degree; "
        "strong financial analysis skills; Singaporeans and PRs are welcome to apply. Allowance: $1,200 per month. ") * 3


def job(title, period="", desc=RICH, dept="", source="internsg", location="Downtown Core, SG"):
    j = classify(RawJob(source, title[:20], "Acme", title, "u", location=location, period_text=period, description=desc, department=dept),
                 PROF, TODAY, require_relevant=False, keep_out_of_window=True)
    d = {k: getattr(j, k) for k in ("title", "tier", "fit", "start", "end", "min_months", "description", "location", "source")}
    d.update(department=dept, approximate=j.extra.get("approximate"), max_months=j.extra.get("max_months"))
    return d


def part(s, name):
    return next(p for p in s["parts"] if p["name"] == name)


def test_weights_total_100_and_breakdown_adds_up():
    assert sum(WEIGHTS.values()) == 100
    s = score(job("Private Equity Intern", "From 01 Dec 2026 - 12 Feb 2027"), PROF)
    assert s["total"] == sum(p["points"] for p in s["parts"])
    assert all(0 <= p["points"] <= p["max"] for p in s["parts"])


def test_ideal_role_scores_excellent():
    s = score(job("Private Equity Intern", "From 01 Dec 2026 - 12 Feb 2027"), PROF)
    assert s["total"] >= 85 and s["label"] == "Excellent match", s


def test_deterministic():
    j = job("Investment Analyst Intern", "From Dec 2026 - May 2027")
    assert score(j, PROF) == score(j, PROF)


def test_unknown_dates_get_neutral_credit_not_zero():
    s = score(job("Investment Analyst Intern", ""), PROF)
    a = part(s, "Availability")
    assert a["known"] is False and a["points"] == 10 and "Availability" in s["unknown"]


def test_short_posting_marks_skills_unknown():
    s = score(job("Investment Analyst Intern", "From Dec 2026 - May 2027", desc="Join our team."), PROF)
    sk = part(s, "Skills")
    assert sk["known"] is False and sk["points"] == 12


def test_missing_skills_lower_the_skills_score():
    good = score(job("Investment Analyst Intern", "From Dec 2026 - May 2027"), PROF)
    gap_desc = RICH.replace("Excel and Python", "financial modelling, DCF valuation, Bloomberg and VBA")
    worse = score(job("Investment Analyst Intern", "From Dec 2026 - May 2027", desc=gap_desc), PROF)
    assert part(worse, "Skills")["points"] < part(good, "Skills")["points"]
    assert "not on your CV" in part(worse, "Skills")["reason"]


def test_quant_heavy_roles_are_not_prioritised():
    quant_desc = RICH + " Strong C++ and low latency systems experience; PhD preferred; market making strategies."
    quant = score(job("Quantitative Research Intern", "From Dec 2026 - May 2027", desc=quant_desc), PROF)
    analyst = score(job("Investment Analyst Intern", "From Dec 2026 - May 2027"), PROF)
    assert part(quant, "Role alignment")["points"] < part(analyst, "Role alignment")["points"]
    assert quant["total"] < analyst["total"]


def test_tier1_preferred_length_beats_short_programme():
    ten_weeks = score(job("Investment Analyst Intern", "From 01 Dec 2026 - 12 Feb 2027"), PROF)
    two_weeks = score(job("Investment Analyst Intern", "From 07 Dec 2026 - 18 Dec 2026"), PROF)
    assert part(ten_weeks, "Availability")["points"] == 20
    assert part(two_weeks, "Availability")["points"] == 5


def test_tier2_preferred_range_beats_long_tier2():
    five_months = score(job("Investment Analyst Intern", "From 01 Dec 2026 - 30 Apr 2027"), PROF)
    seven_months = score(job("Investment Analyst Intern", "From 01 Dec 2026 - 30 Jun 2027"), PROF)
    assert part(five_months, "Availability")["points"] > part(seven_months, "Availability")["points"]


def test_tier1_ranks_above_equivalent_tier2():
    t1 = score(job("Investment Analyst Intern", "From 01 Dec 2026 - 12 Feb 2027"), PROF)
    t2 = score(job("Investment Analyst Intern", "From 01 Dec 2026 - 30 Apr 2027"), PROF)
    assert t1["total"] > t2["total"]


def test_graduates_only_flags_eligibility():
    desc = RICH.replace("currently pursuing a bachelor's degree", "must have graduated within the last 12 months")
    s = score(job("Investment Analyst Intern", "From Dec 2026 - May 2027", desc=desc), PROF)
    assert part(s, "Eligibility")["points"] == 3


def test_singaporean_pr_roles_count_as_eligible():
    s = score(job("Investment Analyst Intern", "From Dec 2026 - May 2027"), PROF)
    assert part(s, "Eligibility")["points"] == 10 and "you qualify" in part(s, "Eligibility")["reason"]


def test_priority_groups():
    assert part(score(job("Private Equity Intern"), PROF), "Role priority")["points"] == 15
    assert part(score(job("Treasury Intern"), PROF), "Role priority")["points"] == 11
    assert part(score(job("Data Analyst Intern"), PROF), "Role priority")["points"] == 10
    assert part(score(job("Strategy Intern"), PROF), "Role priority")["points"] == 6


def test_manual_role_without_text_is_not_penalised_for_clarity():
    s = score(job("Private Equity Intern", "", desc="", source="manual", location=""), PROF)
    c = part(s, "Posting clarity")
    assert c["known"] is False and c["points"] == 5


def test_labels():
    assert [label_for(x) for x in (95, 85, 72, 60, 45, 10)] == [
        "Excellent match", "Excellent match", "Strong match", "Worth a look", "Weak match", "Poor match"]


def test_profile_skills_are_evidenced_by_the_cv():
    """The score credits 'skills you have' — each must be visible in the (example) master CV."""
    cv_text = (CONFIG / "master_cv.example.yaml").read_text().lower()
    prof = yaml.safe_load((CONFIG / "profile.yaml").read_text())["skills"]
    for skill in prof["have"]:
        evidence = prof.get("evidence", {}).get(skill, skill)
        assert evidence.lower() in cv_text, f"'{skill}' is not evidenced in the master CV"
