from datetime import date

import pytest

from radar.classify import Profile, classify, family_for
from radar.models import RawJob

TODAY = date(2026, 9, 29)
PROF = Profile.load()


def raw(title, period="", desc="", dept=""):
    return RawJob("internsg", title[:20], "Acme", title, "https://x", period_text=period, description=desc, department=dept)


@pytest.mark.parametrize("title,period,tier,fit", [
    ("One Deals Year-End Internship (Dec 26 - Feb 27)", "", "T1", "strong"),
    ("Investment Analyst intern", "Flexible start, minimum commitment of two (2) months", "T1", "strong"),
    ("Data & AI Analytics Intern", "minimum of 12 weeks", "T1", "stretch"),
    ("Treasury Operations Intern", "Immediate Start, For At Least 3 Months", "T1", "stretch"),
    ("Investment Analyst Internship", "From Dec 2026 - May 2027", "T2", "strong"),
    ("Intern, Asian Equities", "From Dec 2026, For At Least 6 Months", "T2", "strong"),
    ("Leveraged Finance Intern", "Internship Period: 11 January 2027 – 30 June 2027", "T2", "strong"),
    ("Winter Finance Internship", "From 07 Dec 2026 - 18 Dec 2026", "T1", "weak"),
    ("Research Data & Analytics Intern", "", "?", "unclear"),
])
def test_tiers(title, period, tier, fit):
    job = classify(raw(title, period), PROF, TODAY)
    assert job is not None, title
    assert (job.tier, job.fit) == (tier, fit)


@pytest.mark.parametrize("title", [
    "Private Equity Intern (July to December 2027)",   # outside both windows
    "Software Engineer Intern (Jan - Jun 2027)",       # not a target role
    "Marketing Intern (Jan - Jun 2027)",
    "2027 Summer Internship – Account Analyst",         # summer programme
    "Investment Analyst",                               # not an internship
])
def test_dropped(title):
    assert classify(raw(title), PROF, TODAY) is None


def test_data_titles_survive_engineering_filter():
    assert classify(raw("Data Engineer Intern (Dec 2026 - May 2027)", dept="Analytics"), PROF, TODAY) is not None


@pytest.mark.parametrize("title,area,fam", [
    ("Intern (TGI – Equity Research / AI Automation)", "", "INV"),
    ("Intern, Multi-Asset Strategies Team (MAST)", "", "AM"),
    ("Data Analyst Intern (Finance)", "", "DATA"),
    ("Intern, Treasury (FX Management)", "", "OPS"),
    ("Growth Intern – Business Development", "", "STRAT"),
    ("Consulting – Cloud, Digital, Data Year-End Internship", "Data / Analytics", "DATA"),
])
def test_family(title, area, fam):
    assert family_for(title, area) == fam


# ---- Ambiguous titles (InternRadar brief) ----------------------------------------------------

@pytest.mark.parametrize("title,fam", [
    ("Investment Operations Intern", "OPS"),                 # operations work, not investing
    ("Intern, Fund Operations (Jan - Jun 2027)", "OPS"),
    ("Markets Operations Intern", "OPS"),
    ("Trading Operations Intern", "OPS"),
    ("Portfolio Analytics Intern", "AM"),                    # portfolio context beats "analytics"
    ("Treasury Analyst Intern", "OPS"),
    ("Quantitative Research Intern, Quantitative Strategy", "INV"),
    ("Business Analyst Intern", "DATA"),
    ("Financial Analyst Intern", "OPS"),                     # FP&A-style finance role
    ("Pricing Analyst Intern", "DATA"),
    ("Strategy Analyst Intern", "STRAT"),
    ("Strategy & Commercial Analytics Intern", "STRAT"),
    ("Commercial Analytics Intern", "STRAT"),
    ("Pricing Analytics Intern", "DATA"),
    ("Corporate Finance Intern", "INV"),                     # "finance" alone must not make it OPS
    ("Leveraged and Acquisition Finance Intern", "INV"),
    ("2027 Real Estate Finance, Off Cycle Intern", "INV"),
    ("Investment & Analytics Intern", "INV"),                # investing context first
    ("Data & Finance Intern, Finance (Governance & Technology)", "DATA"),
    ("Intern, Strategic Investments (M&A)", "INV"),
    ("Intern, Multi-Asset Strategies Team (MAST)", "AM"),
    ("Wealth Management Intern", "AM"),
    ("Private Equity Intern", "INV"),
    ("Equity Research Intern", "INV"),
    ("Intern, Asia Client Group", "AM"),
    ("Risk Analytics Intern", "OPS"),
    ("Sector Data Analyst – Intern (Asia)", "DATA"),
])
def test_ambiguous_titles(title, fam):
    assert family_for(title) == fam


def test_description_breaks_ties_when_title_is_generic():
    desc = "You will build SQL queries and Power BI dashboards for the analytics team using Python."
    assert family_for("Intern", description=desc) == "DATA"
    desc2 = "Support the treasury team with cash reconciliation, settlement and controls."
    assert family_for("Intern", description=desc2) == "OPS"


@pytest.mark.parametrize("title", [
    "Risk Intern (Jan - Jun 2027)",
    "Operations Intern (Jan - Jun 2027)",
    "Data Analyst Intern (Jan - Jun 2027)",
    "Business Analyst Intern (Jan - Jun 2027)",
])
def test_broad_finance_words_are_not_excluded(title):
    assert classify(raw(title), PROF, TODAY) is not None


@pytest.mark.parametrize("title", [
    "Software Engineer Intern (Data Engineering) (Jan - Jun 2027)",   # data wording can't rescue software roles
    "Quantitative Developer Intern (Jan - Jun 2027)",
    "Backend Developer Intern (Jan - Jun 2027)",
    "HR Intern (Jan - Jun 2027)",
    "Graphic Design Intern (Jan - Jun 2027)",
    "Retail Sales Intern (Jan - Jun 2027)",
])
def test_avoided_roles_are_excluded(title):
    assert classify(raw(title), PROF, TODAY) is None


def test_t2_outside_preferred_range_is_stretch():
    job = classify(raw("Investment Intern", "From 01 Dec 2026 - 31 Jul 2027"), PROF, TODAY)   # ~8 months > 7.5 -> dropped
    assert job is None
    job = classify(raw("Investment Intern", "From 01 Dec 2026 - 30 Jun 2027"), PROF, TODAY)   # ~7 months
    assert (job.tier, job.fit) == ("T2", "stretch") and "longer than your preferred" in job.note


def test_manual_roles_kept_even_outside_windows():
    r = raw("Private Equity Intern", "July to December 2027")
    assert classify(r, PROF, TODAY) is None
    kept = classify(r, PROF, TODAY, require_relevant=False, keep_out_of_window=True)
    assert kept.tier == "?" and "outside both" in kept.note
