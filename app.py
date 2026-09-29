"""InternRadar — personal internship intelligence and application tracking.

    streamlit run app.py

With no data/radar.db yet (a fresh clone), the app opens on fictional demo data.
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.set_page_config(page_title="InternRadar", page_icon="📡", layout="wide")


def secret(name: str, default=None):
    try:
        return st.secrets.get(name, os.environ.get(name, default))
    except Exception:  # no secrets file
        return os.environ.get(name, default)


if secret("MASTER_CV"):  # hosted: the real CV lives in secrets, never in git
    os.environ["MASTER_CV"] = secret("MASTER_CV")

from radar import applications as A  # noqa: E402
from radar import cv, insights  # noqa: E402
from radar.classify import FAMILY_LABELS, Profile  # noqa: E402
from radar.identity import fingerprint  # noqa: E402
from radar.manual import FOUND_ON, new_row, parse_csv, to_csv, to_jobs  # noqa: E402
from radar.paths import DATA, DB_PATH, DEMO, PRIVATE  # noqa: E402
from radar.pipeline import job_dict  # noqa: E402
from radar.score import label_for, score  # noqa: E402
from radar.store import connect, open_postings  # noqa: E402

TZ = ZoneInfo("Australia/Melbourne")
TODAY = datetime.now(TZ).date()
SOURCE_LABELS = {"greenhouse": "Company site (Greenhouse)", "workday": "Company site (Workday)", "workable": "Company site (Workable)",
                 "internsg": "InternSG", "manual": "Added by me"}
TIER_LABELS = {"T1": "Tier 1", "T2": "Tier 2", "?": "Dates unclear"}
SHORT_FAMILY = {"INV": "Investment", "AM": "Asset & wealth", "DATA": "Data", "OPS": "Finance ops", "STRAT": "Strategy"}
SHORT_SOURCE = {"greenhouse": "Greenhouse", "workday": "Workday", "workable": "Workable", "internsg": "InternSG", "manual": "Added by me"}

st.markdown("""
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1380px;}
h1, h2, h3 {letter-spacing: -0.01em;}
[data-testid="stMetric"] {background: #ffffff; border: 1px solid #e1e6e3; border-radius: 10px; padding: 12px 16px;}
[data-testid="stMetricLabel"] p {font-size: .74rem; text-transform: uppercase; letter-spacing: .07em; color: #5d6a64; font-weight: 600;}
[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
.ir-sub {color: #5d6a64; font-size: .92rem; margin-top: -.6rem; margin-bottom: 1rem;}
.ir-chip {display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: .74rem; font-weight: 600; margin: 0 4px 4px 0; white-space: nowrap;}
.ir-good {background: #e1f0ea; color: #0f6b52;} .ir-warn {background: #f6ecd9; color: #8a5a12;}
.ir-bad {background: #f7e3de; color: #9b3b2a;} .ir-muted {background: #eceeed; color: #4f5b56;}
.ir-kind {font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #0f6b52;}
.ir-meta {color: #5d6a64; font-size: .84rem;}
.ir-score {font-size: 2.4rem; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; color: #17201c;}
.ir-row {display: grid; grid-template-columns: 128px 1fr 48px; gap: 10px; align-items: center; font-size: .88rem; margin-top: 6px;}
.ir-bar {height: 7px; background: #e7ebe9; border-radius: 4px; overflow: hidden;} .ir-bar > div {height: 100%; background: #0f6b52;}
.ir-bar.unknown > div {background: #b9c4bf;}
.ir-reason {color: #5d6a64; font-size: .79rem; margin: 1px 0 4px;}
.ir-num {text-align: right; font-variant-numeric: tabular-nums; color: #17201c;}
.ir-banner {background: #f6ecd9; border: 1px solid #ecd9b3; color: #5f430f; padding: 8px 14px; border-radius: 8px; font-size: .88rem; margin-bottom: 1rem;}
</style>
""", unsafe_allow_html=True)


# ---------------- access ----------------
if secret("APP_PASSWORD") and not st.session_state.get("authed"):
    st.title("InternRadar")
    pw = st.text_input("Password", type="password")
    if pw and pw == secret("APP_PASSWORD"):
        st.session_state.authed = True
        st.rerun()
    elif pw:
        st.error("That password isn't right.")
    st.stop()


# ---------------- data ----------------
MODE = "live" if DB_PATH.exists() else "demo"
DB = DB_PATH if MODE == "live" else DEMO / "demo.db"
PROF = Profile.load()


def private_store() -> A.PrivateStore:
    if MODE == "demo":
        return A.PrivateStore(DEMO, read_only=True)
    return A.PrivateStore(PRIVATE, github_token=secret("GITHUB_TOKEN"), github_repo=secret("GITHUB_REPO"))


STORE = private_store()


def migrate_legacy_files():
    """Earlier versions kept statuses and hand-added roles in data/. Move them into data/private/ once."""
    if MODE != "live" or STORE.remote or st.session_state.get("migrated"):
        return
    st.session_state.migrated = True
    old_apps, old_manual = DATA / "applications.json", DATA / "manual_jobs.csv"
    if old_manual.exists() and STORE.read("manual_jobs.csv") is None:
        STORE.write("manual_jobs.csv", old_manual.read_text(encoding="utf-8"))
        old_manual.rename(old_manual.with_suffix(".csv.migrated"))
        st.toast("Moved your hand-added roles into data/private/.")
    if old_apps.exists() and STORE.read("applications.json") is None:
        with connect(DB) as con:
            key_map = {k: fp for k, fp in con.execute("SELECT key, fingerprint FROM jobs")}
        for r in parse_csv(STORE.read("manual_jobs.csv")):   # hand-added roles were keyed by their URL
            key_map["manual:" + (r.get("id") or r["url"])] = fingerprint(r["company"], r["title"])
        A.save(STORE, A.migrate_legacy(json.loads(old_apps.read_text()), key_map))
        old_apps.rename(old_apps.with_suffix(".json.migrated"))
        st.toast("Moved your application statuses into data/private/.")


migrate_legacy_files()


@st.cache_data(ttl=300)
def load_postings(path: str, mtime: float) -> list[dict]:
    with connect(__import__("pathlib").Path(path)) as con:
        rows = open_postings(con)
    for r in rows:
        r["score_detail"] = json.loads(r["score_json"]) if r.get("score_json") else None
    return rows


def apps() -> dict:
    if "apps" not in st.session_state:
        st.session_state.apps = A.load(STORE)
    return st.session_state.apps


def manual_rows() -> list[dict]:
    if "manual_rows" not in st.session_state:
        st.session_state.manual_rows = parse_csv(STORE.read("manual_jobs.csv"))
    return st.session_state.manual_rows


def save_apps():
    try:
        A.save(STORE, apps())
    except Exception as e:  # e.g. GitHub unreachable
        st.warning(f"Saved for this session only; couldn't write to your private store ({type(e).__name__}).")


def build_jobs() -> pd.DataFrame:
    rows = []
    for r in load_postings(str(DB), DB.stat().st_mtime if DB.exists() else 0):
        s = r["score_detail"] or score(r, PROF)
        rows.append({**r, "fp": r["fingerprint"], "score": s["total"], "score_detail": s,
                     "sources": ", ".join(SOURCE_LABELS.get(x, x) for x in r.get("sources", [r["source"]])), "found_on": "", "manual_notes": ""})
    auto_fps = {r["fp"] for r in rows}
    for job in to_jobs(manual_rows(), PROF, TODAY):
        fp = fingerprint(job.company, job.title)
        if fp in auto_fps:
            continue   # the same role was found on a company board; show that listing
        d = job_dict(job)
        s = score({**d, "location": d["location"] or PROF.location}, PROF)
        rows.append({"key": job.key, "fp": fp, "source": "manual", "sources": f"Added by me ({job.extra.get('found_on') or 'other'})",
                     "company": job.company, "title": job.title, "url": job.url, "dates": job.dates, "tier": job.tier, "fit": job.fit,
                     "family": job.family, "area": job.area, "note": job.note, "description": job.description,
                     "first_seen": (job.posted or TODAY).isoformat(), "score": s["total"], "score_detail": s,
                     "location": PROF.location, "found_on": job.extra.get("found_on", ""), "manual_notes": job.extra.get("manual_notes", "")})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["first_seen"] = pd.to_datetime(df["first_seen"]).dt.date
    df["new"] = df["first_seen"].map(lambda d: (TODAY - d).days < insights.NEW_DAYS)
    a = apps()
    df["status"] = df["fp"].map(lambda fp: a.get(fp, {}).get("status", "Not started"))
    return df


JOBS = build_jobs()
LAST_RUN = json.loads(((DATA if MODE == "live" else DEMO) / "last_run.json").read_text()) \
    if ((DATA if MODE == "live" else DEMO) / "last_run.json").exists() else {}


def snapshot(job: pd.Series) -> dict:
    return {"company": job["company"], "title": job["title"], "family": job["family"], "tier": job["tier"],
            "source": job["source"], "score": int(job["score"]), "url": job["url"], "dates": job["dates"]}


def chip(text: str, kind: str = "muted") -> str:
    return f'<span class="ir-chip ir-{kind}">{html.escape(str(text))}</span>'


def fit_chip(fit: str) -> str:
    return chip(fit, {"strong": "good", "stretch": "warn", "weak": "bad"}.get(fit, "muted"))


def demo_banner():
    if MODE == "demo":
        st.markdown('<div class="ir-banner"><b>Demo data.</b> Every company here is fictional and nothing you change is saved. '
                    'Run <code>python -m radar.pipeline run</code> (or let the daily GitHub Action run) to load real postings.</div>',
                    unsafe_allow_html=True)


def open_in_discover(fp: str):
    st.session_state.focus_fp = fp
    st.switch_page(PAGES["discover"])


# ================= Overview =================
def overview():
    st.title("InternRadar")
    st.markdown('<div class="ir-sub">Personal internship intelligence and application tracking.</div>', unsafe_allow_html=True)
    demo_banner()
    if JOBS.empty:
        st.info("No roles yet. Run `python -m radar.pipeline run`, or add one from Discover.")
        return
    a = apps()
    summ = insights.summary(a)
    open_untracked = JOBS[JOBS.status.isin(["Not started", "Shortlisted"])]
    c = st.columns(6)
    c[0].metric("New roles", int(JOBS.new.sum()), help=f"First seen in the last {insights.NEW_DAYS} days")
    c[1].metric("High fit", int((JOBS.score >= 70).sum()), help="Open roles scoring 70 or more")
    c[2].metric("Tier 1 open", int((JOBS.tier == "T1").sum()), help="Fit 30 Nov – 19 Feb without leave")
    c[3].metric("Tier 2 open", int((JOBS.tier == "T2").sum()), help="Longer roles that need a leave of absence")
    c[4].metric("Active", summ["active"], help="Shortlisted, Applying, Applied or Interview")
    c[5].metric("Interviews", int(sum(r.get("status") == "Interview" for r in a.values())), help="Currently at interview stage")

    if LAST_RUN:
        failed = LAST_RUN.get("boards_failed", 0)
        st.caption(f"Last checked {LAST_RUN['date']} · {LAST_RUN.get('boards_checked', 0)} of {LAST_RUN.get('boards_configured', 0)} "
                   f"configured boards checked" + (f" · {failed} failed (see System)" if failed else ""))

    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.subheader("Today's priorities")
        items = insights.priorities(JOBS[["fp", "company", "title", "score", "first_seen"]].to_dict("records"), a, TODAY)
        if not items:
            st.markdown('<div class="ir-meta">Nothing needs attention today. New matches and any follow-ups you set will appear here.</div>',
                        unsafe_allow_html=True)
        for i, it in enumerate(items):
            with st.container(border=True):
                t, b = st.columns([5, 1], vertical_alignment="center")
                t.markdown(f'<div class="ir-kind">{html.escape(it["kind"])}</div><b>{html.escape(it["text"])}</b>'
                           f'<div class="ir-meta">{html.escape(it["detail"])}</div>', unsafe_allow_html=True)
                if it["fp"] in set(JOBS.fp) and b.button("Open", key=f"pri_{i}", width="stretch"):
                    open_in_discover(it["fp"])
    with right:
        st.subheader("Top matches")
        top = open_untracked.sort_values("score", ascending=False).head(6)
        for i, (_, j) in enumerate(top.iterrows()):
            with st.container(border=True):
                s, t, b = st.columns([0.7, 3.5, 1.1], vertical_alignment="center")
                s.markdown(f'<div class="ir-score" style="font-size:1.5rem">{j.score}</div>', unsafe_allow_html=True)
                t.markdown(f"**{html.escape(j.company)}**<br>{html.escape(j.title)}<br>"
                           f'<span class="ir-meta">{TIER_LABELS.get(j.tier, j.tier)} · {html.escape(j.dates)}</span>', unsafe_allow_html=True)
                if b.button("Open", key=f"top_{i}", type="tertiary", help="Open in Discover"):
                    open_in_discover(j.fp)
        st.subheader("Pipeline")
        counts = pd.Series([r.get("status") for r in a.values()]).value_counts() if a else pd.Series(dtype=int)
        st.markdown(" ".join(chip(f"{s}: {int(counts.get(s, 0))}", "good" if s in ("Interview", "Offer") else "muted")
                             for s in A.PIPELINE), unsafe_allow_html=True)


# ================= Discover =================
def score_breakdown(detail: dict):
    st.markdown(f'<div class="ir-score">{detail["total"]}<span style="font-size:1rem;color:#5d6a64">/100</span></div>'
                f'<div class="ir-meta" style="margin-bottom:6px">{html.escape(detail["label"])}</div>', unsafe_allow_html=True)
    rows = []
    for p in detail["parts"]:
        pct = 100 * p["points"] / p["max"]
        tag = " " + chip("unknown", "muted") if not p["known"] else ""
        rows.append(f'<div class="ir-row"><div>{html.escape(p["name"])}</div><div class="ir-bar{"" if p["known"] else " unknown"}">'
                    f'<div style="width:{pct:.0f}%"></div></div><div class="ir-num">{p["points"]}/{p["max"]}</div></div>'
                    f'<div class="ir-reason">{html.escape(p["reason"])}{tag}</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    if detail["unknown"]:
        st.caption("Unknown dimensions get neutral credit: the posting didn't say, so it isn't counted against the role.")


def application_form(job: pd.Series):
    a = apps()
    rec = a.get(job.fp, {})
    with st.form(f"app_{job.fp}", border=False):
        c1, c2 = st.columns(2)
        status = c1.selectbox("Status", A.STATUSES, index=A.STATUSES.index(rec.get("status", "Not started")))
        applied = c2.date_input("Applied on", value=date.fromisoformat(rec["applied_on"]) if rec.get("applied_on") else None, format="DD/MM/YYYY")
        c3, c4 = st.columns(2)
        follow = c3.date_input("Follow up on", value=date.fromisoformat(rec["follow_up_on"]) if rec.get("follow_up_on") else None, format="DD/MM/YYYY")
        interview = c4.date_input("Interview on", value=date.fromisoformat(rec["interview_on"]) if rec.get("interview_on") else None, format="DD/MM/YYYY")
        notes = st.text_area("Notes", rec.get("notes", "") or job.get("manual_notes", ""), placeholder="Contacts, deadlines, referral…", height=90)
        if st.form_submit_button("Save", type="primary"):
            A.update(a, job.fp, TODAY, status=status, snapshot=snapshot(job), applied_on=applied, follow_up_on=follow,
                     interview_on=interview, notes=notes)
            save_apps()
            st.success("Saved." if MODE == "live" else "Saved for this demo session.")
            st.rerun()


def cv_tools(job: pd.Series):
    master = cv.load_master()
    vers = cv.versions(master)
    fam = job.family if job.family in vers else next(iter(vers))
    v = st.selectbox("CV version", list(vers), index=list(vers).index(fam), format_func=lambda x: vers[x]["label"], key=f"ver_{job.fp}")
    k = f"{job.fp}_{v}"
    headline = st.text_input("Headline", vers[v]["headline"], key=f"hl_{k}")
    summary = st.text_area("Summary (edit freely: these are your words)", cv.default_summary(master, v, job.company, job.title, job.tier),
                           height=130, key=f"sm_{k}")
    default = cv.selection(master, v)
    chosen = {"experience": [], "projects": []}
    with st.expander("Choose bullets (only approved wordings from your master CV)"):
        for sec, label in (("experience", "title"), ("projects", "title")):
            for i, item in enumerate(master[sec]):
                opts = list(dict.fromkeys(item["bullets"].values()))
                chosen[sec].append(st.multiselect(item[label], opts, default=default[sec][i], key=f"b_{k}_{sec}_{i}",
                                                  format_func=lambda b: b[:110] + ("…" if len(b) > 110 else "")))
    blocks = cv.build(master, v, job.company, job.title, job.tier, summary=summary, headline=headline, chosen=chosen)
    rep = cv.keyword_report(blocks, v, f"{job.title} {job.description or ''}", master)
    st.markdown("**Covered** " + ("".join(chip(t, "good") for t in rep["covered"]) or '<span class="ir-meta">none</span>'), unsafe_allow_html=True)
    if rep["missing"]:
        st.markdown("**In your master CV, not in this version** " + "".join(chip(t, "warn") for t in rep["missing"]), unsafe_allow_html=True)
    if rep["gaps"]:
        st.markdown("**Potential gaps: add only if true** " + "".join(chip(t, "bad") for t in rep["gaps"]), unsafe_allow_html=True)
    st.caption("InternRadar never inserts a keyword into your CV. A gap only means the role mentions it and your master CV doesn't.")
    if cv.using_example():
        st.info("Using the public example CV (Alex Tan). Add config/master_cv.yaml to tailor your own.")
    safe = re.sub(r"[^A-Za-z0-9]+", "_", job.company).strip("_")
    name = master["name"].title().replace(" ", "_")
    d1, d2 = st.columns(2)
    d1.download_button("Download PDF", cv.to_pdf(blocks), file_name=f"{name}_CV_{safe}.pdf", mime="application/pdf",
                       type="primary", width="stretch", on_click="ignore", key=f"pdf_{k}")
    d2.download_button("Download text", cv.to_text(blocks), file_name=f"{name}_CV_{safe}.txt", width="stretch",
                       on_click="ignore", key=f"txt_{k}")
    with st.expander("Preview"):
        st.text(cv.to_text(blocks))


def job_detail(job: pd.Series):
    st.divider()
    head, link = st.columns([4, 1], vertical_alignment="bottom")
    head.markdown(f"### {html.escape(job.company)}\n**{html.escape(job.title)}**", unsafe_allow_html=True)
    link.link_button("Open posting ↗", job.url, width="stretch")
    st.markdown(chip(TIER_LABELS.get(job.tier, job.tier), "good" if job.tier == "T1" else "warn" if job.tier == "T2" else "muted")
                + fit_chip(job.fit) + chip(job.area) + chip(job.dates) + chip(job.sources), unsafe_allow_html=True)
    left, mid, right = st.columns([1.05, 1, 1.25], gap="large")
    with left:
        st.markdown("**Opportunity score**")
        score_breakdown(job.score_detail)
    with mid:
        st.markdown("**Availability**")
        st.markdown(f"{html.escape(job.note)}<br><span class='ir-meta'>Your windows: Tier 1 30 Nov 2026 – 19 Feb 2027 · "
                    f"Tier 2 about 4–6 months from Dec–Feb</span>", unsafe_allow_html=True)
        st.markdown("**Application**")
        application_form(job)
    with right:
        st.markdown("**Tailored CV**")
        cv_tools(job)
    if job.description:
        with st.expander("Posting text"):
            st.write(job.description[:8000])


def add_role_form():
    with st.expander("Add a role manually (LinkedIn, jorb.ai, referrals, career fairs…)"):
        with st.form("add_role", clear_on_submit=True):
            a1, a2 = st.columns(2)
            company = a1.text_input("Company")
            title = a2.text_input("Role title")
            b1, b2 = st.columns([3, 1])
            url = b1.text_input("Posting link")
            found = b2.selectbox("Found on", FOUND_ON)
            dates = st.text_input("Dates or duration, if known", placeholder="e.g. Dec 2026 – Feb 2027, or minimum 3 months")
            desc = st.text_area("Description (paste the posting: it improves tier, CV version and score)", height=110)
            notes = st.text_input("Notes")
            if st.form_submit_button("Add role", type="primary"):
                if not (company and title and url):
                    st.error("Add a company, role title and link.")
                else:
                    rows = manual_rows()
                    rows.append(new_row(company, title, url, found, dates, desc, notes, TODAY))
                    STORE.write("manual_jobs.csv", to_csv(rows))
                    [job] = to_jobs([rows[-1]], PROF, TODAY)
                    st.success(f"Added {company} – {title}: {TIER_LABELS.get(job.tier, job.tier)}, {job.fit} fit, "
                               f"CV version “{FAMILY_LABELS[job.family]}”.")
                    st.rerun()


def discover():
    st.title("Discover")
    demo_banner()
    add_role_form()
    if JOBS.empty:
        st.info("No roles yet.")
        return
    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([2.2, 1.3, 1.3, 1.2])
        q = f1.text_input("Search company or role", placeholder="e.g. equity research, OCBC")
        tiers = f2.multiselect("Tier", ["T1", "T2", "?"], default=["T1", "T2", "?"], format_func=TIER_LABELS.get)
        fits = f3.multiselect("Fit", ["strong", "stretch", "weak", "unclear"], default=["strong", "stretch", "unclear"])
        sort = f4.selectbox("Sort by", ["Score", "Newest", "Start date", "Company"])
        g1, g2, g3, g4, g5 = st.columns([1.6, 1.3, 1.3, 1.2, 1])
        fams = g1.multiselect("Role family", list(FAMILY_LABELS), format_func=FAMILY_LABELS.get)
        srcs = g2.multiselect("Source", sorted(JOBS.source.unique()), format_func=lambda s: SOURCE_LABELS.get(s, s))
        stats = g3.multiselect("Status", A.STATUSES)
        min_score = g4.slider("Min score", 0, 100, 0, 5)
        only_new = g5.checkbox("New only")
        hide_done = g5.checkbox("Hide closed out", value=True, help="Hide Rejected, Withdrawn and Not for me")
    f = JOBS[JOBS.tier.isin(tiers) & JOBS.fit.isin(fits) & (JOBS.score >= min_score)]
    if q:
        f = f[f.company.str.contains(q, case=False, regex=False) | f.title.str.contains(q, case=False, regex=False)]
    if fams:
        f = f[f.family.isin(fams)]
    if srcs:
        f = f[f.source.isin(srcs)]
    if stats:
        f = f[f.status.isin(stats)]
    if only_new:
        f = f[f.new]
    if hide_done:
        f = f[~f.status.isin(A.CLOSED_OUT)]
    order = {"Score": (["score", "company"], [False, True]), "Newest": (["first_seen", "score"], [False, False]),
             "Start date": (["start", "score"], [True, False]), "Company": (["company"], [True])}[sort]
    f = f.sort_values(by=order[0], ascending=order[1], na_position="last").reset_index(drop=True)
    st.caption(f"{len(f)} of {len(JOBS)} open roles · select a row for details, score breakdown, application and CV tools")
    view = pd.DataFrame({
        "Score": f.score, "New": f.new.map({True: "●", False: ""}),
        "Tier · fit": f.tier + " · " + f.fit, "Company": f.company, "Role": f.title, "Status": f.status, "Posting": f.url,
        "Dates": f.dates, "Area": f.family.map(SHORT_FAMILY), "Source": f.source.map(SHORT_SOURCE)})
    event = st.dataframe(view, hide_index=True, width="stretch", height=min(520, 38 + 35 * len(view)), on_select="rerun",
                         selection_mode="single-row", key="discover_table",
                         column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d", width=80),
                                        "New": st.column_config.TextColumn(width=40, help="First seen in the last 3 days"),
                                        "Tier · fit": st.column_config.TextColumn(width=100, help="T1 fits your break; T2 needs a leave of absence; ? dates unclear"),
                                        "Company": st.column_config.TextColumn(width=170),
                                        "Role": st.column_config.TextColumn(width=230),
                                        "Status": st.column_config.TextColumn(width=95),
                                        "Posting": st.column_config.LinkColumn(display_text="Open ↗", width=70)})
    rows = event.selection.rows if event and event.selection else []
    if rows:
        st.session_state.focus_fp = f.iloc[rows[0]].fp
    fp = st.session_state.get("focus_fp")
    match = JOBS[JOBS.fp == fp]
    if not match.empty:
        job_detail(match.iloc[0])


# ================= Applications =================
def applications_page():
    st.title("Applications")
    demo_banner()
    a = apps()
    by_fp = {r.fp: r for _, r in JOBS.iterrows()} if not JOBS.empty else {}
    tracked = [(fp, r) for fp, r in a.items() if r.get("status", "Not started") != "Not started"]
    if not tracked:
        st.info("Nothing tracked yet. Open a role in Discover and set its status to Shortlisted.")
        return
    info = lambda fp, r: {**(r.get("job") or {}), **({"company": by_fp[fp].company, "title": by_fp[fp].title, "url": by_fp[fp].url,
                                                       "score": int(by_fp[fp].score), "dates": by_fp[fp].dates} if fp in by_fp else {})}
    cols = st.columns(len(A.PIPELINE))
    for col, stage in zip(cols, A.PIPELINE):
        items = [(fp, r) for fp, r in tracked if r["status"] == stage]
        col.markdown(f"**{stage}** {chip(len(items), 'good' if stage in ('Interview', 'Offer') else 'muted')}", unsafe_allow_html=True)
        for fp, r in sorted(items, key=lambda x: -(info(*x).get("score") or 0)):
            j = info(fp, r)
            meta = []
            if r.get("interview_on"):
                meta.append(f"Interview {date.fromisoformat(r['interview_on']):%d %b}")
            if r.get("follow_up_on"):
                meta.append(f"Follow up {date.fromisoformat(r['follow_up_on']):%d %b}")
            if r.get("applied_on"):
                meta.append(f"Applied {date.fromisoformat(r['applied_on']):%d %b}")
            with col.container(border=True):
                st.markdown(f"**{html.escape(j.get('company', '?'))}**<br>{html.escape(j.get('title', ''))}<br>"
                            f"<span class='ir-meta'>{j.get('score', '–')}/100 · {' · '.join(meta) or html.escape(j.get('dates', ''))}</span>",
                            unsafe_allow_html=True)
                if fp in by_fp and st.button("Open", key=f"pipe_{fp}", width="stretch"):
                    open_in_discover(fp)
    out = [(fp, r) for fp, r in tracked if r["status"] in A.CLOSED_OUT]
    if out:
        with st.expander(f"Closed out ({len(out)}): rejected, withdrawn or not for me"):
            st.dataframe(pd.DataFrame([{"Company": info(fp, r).get("company"), "Role": info(fp, r).get("title"), "Status": r["status"],
                                        "Updated": r.get("updated_on")} for fp, r in out]), hide_index=True, width="stretch")

    st.subheader("Edit details")
    df = pd.DataFrame([{"fp": fp, "Company": info(fp, r).get("company"), "Role": info(fp, r).get("title"), "Status": r["status"],
                        "Applied": pd.to_datetime(r.get("applied_on")).date() if r.get("applied_on") else None,
                        "Follow up": pd.to_datetime(r.get("follow_up_on")).date() if r.get("follow_up_on") else None,
                        "Interview": pd.to_datetime(r.get("interview_on")).date() if r.get("interview_on") else None,
                        "Notes": r.get("notes", ""), "Updated": r.get("updated_on"), "Posting": info(fp, r).get("url")}
                       for fp, r in tracked])
    edited = st.data_editor(df, hide_index=True, width="stretch", key="apps_editor",
                            disabled=["Company", "Role", "Updated", "Posting"],
                            column_config={"fp": None, "Status": st.column_config.SelectboxColumn(options=A.STATUSES, required=True),
                                           "Applied": st.column_config.DateColumn(format="DD MMM YYYY"),
                                           "Follow up": st.column_config.DateColumn(format="DD MMM YYYY"),
                                           "Interview": st.column_config.DateColumn(format="DD MMM YYYY"),
                                           "Notes": st.column_config.TextColumn(width="large"),
                                           "Posting": st.column_config.LinkColumn(display_text="Open ↗")})
    if st.button("Save changes", type="primary"):
        changed = 0
        for _, r in edited.iterrows():
            old = a[r.fp]
            new = {"applied_on": r.Applied, "follow_up_on": r["Follow up"], "interview_on": r.Interview}
            iso = lambda v: v.isoformat() if isinstance(v, date) else (v or None)
            if r.Status != old.get("status") or (r.Notes or "") != old.get("notes", "") or any(iso(v) != old.get(k) for k, v in new.items()):
                A.update(a, r.fp, TODAY, status=r.Status, notes=r.Notes, **{k: (v if isinstance(v, date) else None) for k, v in new.items()})
                changed += 1
        save_apps()
        st.success(f"Saved {changed} change(s)." if MODE == "live" else f"Saved {changed} change(s) for this demo session.")


# ================= Analytics =================
def analytics():
    st.title("Analytics")
    demo_banner()
    a = apps()
    s = insights.summary(a)
    if not s["applications"]:
        st.info("Analytics appear once you've marked applications as Applied.")
        return
    c = st.columns(6)
    c[0].metric("Applications", s["applications"])
    c[1].metric("Active", s["active"])
    c[2].metric("Interviews", s["interviews"], help="Applications that reached an interview")
    c[3].metric("Offers", s["offers"])
    c[4].metric("Rejections", s["rejections"])
    c[5].metric("Withdrawn", s["withdrawn"])
    r1, r2 = st.columns(2)
    r1.metric("Application → interview", f"{s['app_to_interview']}%" if s["app_to_interview"] is not None else "—",
              help="Share of applications that reached an interview. Shown once there are at least 3 applications.")
    r2.metric("Interview → offer", f"{s['interview_to_offer']}%" if s["interview_to_offer"] is not None else "—",
              help="Shown once at least 3 applications reached an interview.")
    st.subheader("Where your applications went")
    g = st.columns(3)
    for col, (field, title, labels) in zip(g, [("family", "By role family", SHORT_FAMILY), ("source", "By source", SHORT_SOURCE),
                                              ("tier", "By tier", TIER_LABELS)]):
        data = insights.breakdown(a, field)
        col.markdown(f"**{title}**")
        col.bar_chart(pd.DataFrame({"Applications": list(data.values())}, index=[labels.get(k, k) for k in data]),
                      horizontal=True, height=200, color="#0f6b52")
    st.subheader("Do higher-scored roles go better?")
    rows = insights.score_vs_outcome(a)
    if rows is None:
        st.caption("Not enough data yet: this needs at least 3 applications scoring 75+ and 3 scoring below 75.")
    else:
        st.dataframe(pd.DataFrame(rows).rename(columns={"group": "Group", "applications": "Applications", "interview_rate": "Interview rate (%)"}),
                     hide_index=True)
        st.caption("A small sample: treat this as a hint, not a conclusion.")


# ================= CV =================
def cv_page():
    st.title("CV")
    master = cv.load_master()
    if cv.using_example():
        st.info("Using the public example CV (a fictional person). Copy config/master_cv.example.yaml to config/master_cv.yaml "
                "and fill in your own details; that file is git-ignored.")
    else:
        st.caption("Using your private master CV (config/master_cv.yaml or the MASTER_CV secret).")
    vers = cv.versions(master)
    v = st.radio("Version", ["master", *vers], horizontal=True, format_func=lambda x: "Original" if x == "master" else vers[x]["label"])
    blocks = cv.build(master, v)
    left, right = st.columns([1.6, 1], gap="large")
    with left, st.container(border=True):
        st.text(cv.to_text(blocks))
    with right:
        st.download_button("Download PDF", cv.to_pdf(blocks), file_name=f"CV_{v}.pdf", mime="application/pdf", type="primary", on_click="ignore")
        st.markdown("**How tailoring works**")
        st.markdown("- Each role family has a version defined in your master CV: headline, focus sentence, bullet order, skill and coursework order.\n"
                    "- Tailoring only **reorders and chooses** among wordings you wrote. It never adds experience, skills, numbers or keywords.\n"
                    "- The summary names the role, company and your availability; you can rewrite it before downloading.\n"
                    "- Keyword checks show what a role asks for that your CV doesn't show. Add it only if it's true.")


# ================= System =================
def system():
    st.title("System")
    demo_banner()
    folder = DATA if MODE == "live" else DEMO
    if LAST_RUN:
        c = st.columns(4)
        c[0].metric("Last run", LAST_RUN["date"])
        c[1].metric("Boards configured", LAST_RUN.get("boards_configured", 0))
        c[2].metric("Checked successfully", LAST_RUN.get("boards_checked", 0))
        c[3].metric("Failed", LAST_RUN.get("boards_failed", 0))
        boards = pd.DataFrame(LAST_RUN.get("boards", []))
        if not boards.empty:
            failed = boards[~boards.ok]
            if not failed.empty:
                st.warning("These boards couldn't be checked on the last run. Their postings were left open, not marked closed.")
                st.dataframe(failed[["board", "error"]].rename(columns={"board": "Board", "error": "Error"}), hide_index=True, width="stretch")
            with st.expander("All boards on the last run"):
                st.dataframe(boards.rename(columns={"board": "Board", "ok": "Checked", "fetched": "Postings fetched", "kept": "Relevant"}),
                             hide_index=True, width="stretch")
    else:
        st.info("No pipeline run recorded yet.")
    latest = folder / ("changes/latest.md" if MODE == "live" else "latest.md")
    if latest.exists():
        with st.container(border=True):
            st.markdown(re.sub(r"^(#{1,2}) ", lambda m: "#" * (len(m.group(1)) + 3) + " ", latest.read_text(), flags=re.M))
    with connect(DB) as con:
        runs = pd.read_sql_query("SELECT run_at AS 'Run', board AS 'Board', ok AS 'OK', fetched AS 'Fetched', kept AS 'Relevant', "
                                 "error AS 'Error' FROM runs ORDER BY run_at DESC LIMIT 200", con)
    with st.expander("Run history"):
        st.dataframe(runs, hide_index=True, width="stretch")
    st.subheader("Data")
    st.markdown(f"- Mode: **{'Live' if MODE == 'live' else 'Demo (fictional data)'}**\n"
                f"- Job database: `{DB.relative_to(DB.parents[1]) if MODE == 'demo' else DB}`\n"
                f"- Private store: **{'GitHub (private repo)' if STORE.remote else 'read-only demo' if STORE.read_only else f'local folder {PRIVATE}'}** "
                f"({len(apps())} tracked roles, {len(manual_rows())} added by hand)\n"
                f"- Master CV: **{'public example' if cv.using_example() else 'your private CV'}**")
    st.markdown("**Commands**")
    st.code("python -m radar.pipeline run     # collect today's postings\n"
            "python -m radar.pipeline check   # which configured boards respond right now\n"
            "python -m radar.demo             # rebuild the fictional demo data\n"
            "pytest                           # run the test suite", language="bash")


PAGES = {
    "overview": st.Page(overview, title="Overview", icon=":material/dashboard:", default=True),
    "discover": st.Page(discover, title="Discover", icon=":material/travel_explore:", url_path="discover"),
    "applications": st.Page(applications_page, title="Applications", icon=":material/checklist:", url_path="applications"),
    "analytics": st.Page(analytics, title="Analytics", icon=":material/insights:", url_path="analytics"),
    "cv": st.Page(cv_page, title="CV", icon=":material/description:", url_path="cv"),
    "system": st.Page(system, title="System", icon=":material/monitor_heart:", url_path="system"),
}
st.navigation(list(PAGES.values())).run()
