from datetime import date

import pytest

from radar.periods import parse_period

TODAY = date(2026, 9, 29)


@pytest.mark.parametrize("text,start,end", [
    ("One Deals Year-End Internship (Dec 26 - Feb 27)", date(2026, 12, 1), date(2027, 2, 28)),
    ("Product Control [Dec26 to May27]", date(2026, 12, 1), date(2027, 5, 31)),
    ("Corporate Finance [Jan - Jun 2027]", date(2027, 1, 1), date(2027, 6, 30)),
    ("Internship Period: 11 January 2027 – 30 June 2027", date(2027, 1, 11), date(2027, 6, 30)),
    ("From 07 Dec 2026 - 18 Dec 2026", date(2026, 12, 7), date(2026, 12, 18)),
    ("Audit - Winter Internship (Nov 2026 to Jan 2027)", date(2026, 11, 1), date(2027, 1, 31)),
    ("1H 2027 Private Equity Intern", date(2027, 1, 1), date(2027, 6, 30)),
    ("Trading Analyst Intern (H1 2027)", date(2027, 1, 1), date(2027, 6, 30)),
    ("INTERNSHIP - VENTURE - S1 2027", date(2027, 1, 1), date(2027, 6, 30)),
    ("Growth Intern (Winter 2026)", date(2026, 12, 1), date(2027, 2, 28)),
])
def test_ranges(text, start, end):
    p = parse_period(text, TODAY)
    assert (p.start, p.end) == (start, end)


@pytest.mark.parametrize("text,months", [
    ("Immediate Start, For At Least 3 Months", 3),
    ("with a minimum commitment of two (2) months", 2),
    ("Life Pricing Intern (6 Months Contract)", 6),
    ("paid, full-time opportunities lasting a minimum of 12 weeks", 12 / 4.345),
    ("commence in December 2026 for 25 to 35 weeks", 25 / 4.345),
])
def test_min_duration(text, months):
    assert parse_period(text, TODAY).min_months == pytest.approx(months, abs=0.01)


def test_start_plus_minimum_gives_end():
    p = parse_period("From Dec 2026, For At Least 6 Months", TODAY)
    assert p.start == date(2026, 12, 1) and p.end.month == 5 and p.end.year == 2027


def test_fuzzy_start_words():
    p = parse_period("Preferred start date: by mid/late Dec 2026, minimum of 6 months", TODAY)
    assert p.start == date(2026, 12, 1) and p.min_months == 6


def test_flexible_and_empty():
    assert parse_period("Flexible Start, Flexible Duration", TODAY).flexible_duration
    assert parse_period("Analyst intern, great team", TODAY).is_empty()


def test_describe_is_readable():
    assert parse_period("[Dec26 to May27]", TODAY).describe() == "Dec 2026 – May 2027"


# ---- Realistic phrasing from the InternRadar brief ----------------------------------------

@pytest.mark.parametrize("text,start,end", [
    ("Internship period: Dec 2026 – Feb 2027", date(2026, 12, 1), date(2027, 2, 28)),
    ("Internship period: Dec 2026 – Jun 2027", date(2026, 12, 1), date(2027, 6, 30)),
    ("Off-cycle internship, Jan – Jun 2027", date(2027, 1, 1), date(2027, 6, 30)),
    ("Duration: 1H 2027", date(2027, 1, 1), date(2027, 6, 30)),
])
def test_brief_ranges(text, start, end):
    p = parse_period(text, TODAY)
    assert (p.start, p.end) == (start, end)
    assert not p.approximate


@pytest.mark.parametrize("text,lo,hi", [
    ("Candidates must commit to a minimum 12 weeks", 12 / 4.345, None),
    ("minimum 3 months", 3, None),
    ("minimum 6 months, full-time", 6, None),
    ("This is a 4–6 months internship", 4, 6),
    ("4-6 month internship", 4, 6),
    ("for 25 to 35 weeks", 25 / 4.345, 35 / 4.345),
])
def test_brief_durations(text, lo, hi):
    p = parse_period(text, TODAY)
    assert p.min_months == pytest.approx(lo, abs=0.01)
    assert (p.max_months == pytest.approx(hi, abs=0.01)) if hi else p.max_months is None


@pytest.mark.parametrize("text,start", [
    ("Internship starting December 2026", date(2026, 12, 1)),
    ("starting January 2027 for six months", date(2027, 1, 1)),
    ("Available to start by mid December", date(2026, 12, 1)),     # no year: next December
    ("Start date: late December", date(2026, 12, 1)),
    ("Able to start in January", date(2027, 1, 1)),                 # January after September -> next year
])
def test_brief_start_phrases(text, start):
    assert parse_period(text, TODAY).start == start


@pytest.mark.parametrize("text", [
    "Applications close late December",                  # a deadline, not a start
    "Please apply by mid December",
    "Shortlisted candidates will hear from December 2026",
    "Off-cycle internship",                              # no dates at all
    "Summer and winter breaks are busy for our team",   # season words without an internship/year
    "Jan to Jun",                                        # months with no year anywhere
])
def test_unknown_stays_unknown(text):
    p = parse_period(text, TODAY)
    assert p.start is None and p.end is None


def test_flexible_and_immediate_start():
    assert parse_period("Flexible start, minimum 3 months", TODAY).flexible_start
    p = parse_period("Immediate start", TODAY)
    assert p.flexible_start and p.start is None


def test_season_dates_are_flagged_approximate():
    p = parse_period("Deloitte Growth Intern (Winter 2026)", TODAY)
    assert p.approximate and "(approx.)" in p.describe()
    y = parse_period("Winter internship programme", TODAY)
    assert y.start == date(2026, 12, 1) and y.approximate


def test_span_label():
    assert parse_period("4–6 months", TODAY).describe() == "4–6 months"
