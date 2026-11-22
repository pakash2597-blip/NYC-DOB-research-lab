"""Streamlit controls and exports for the research cohort."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from cohort import API, DobClient, Selection, collect


@st.cache_data(ttl=3600, show_spinner=False)
def filter_options():
    client = DobClient()
    return [
        sorted(row[field] for row in client.get(API, {"$select": field, "$group": field}) if row.get(field))
        for field in ("borough", "job_type")
    ]


@st.cache_data(ttl=900, max_entries=4, show_spinner=False)
def cached_cohort(selection):
    result = collect(selection)
    if not result["metadata"]["source_version_stable"] or result["metadata"]["api_error_entries"]:
        raise PartialCollection(result)
    return result


class PartialCollection(Exception):
    def __init__(self, result):
        super().__init__("Some public filing histories could not be verified.")
        self.result = result


DEFINITIONS = {
    "job_root": "DOB filing number without its filing-type and sequence suffix.",
    "filing_kind": "Filing type derived from the filing-number suffix.",
    "filing_sequence": "Digits following the filing-type letter, within that type.",
    "filing_day": "Calendar day of the public filing date.",
    "approval_day": "Calendar day of the public approval date.",
    "duplicate_filing_number": "Multiple source rows share the normalized filing number.",
    "conflicting_filing_number": "Rows sharing the normalized number differ in public values.",
    "observed_paa_count": "Distinct, nonconflicting PAAs with filing dates from initial filing through cutoff.",
    "first_observed_paa_date": "Earliest qualifying observed PAA filing date. May be provisional for uncertain histories.",
    "days_to_first_observed_paa": "Calendar days from initial filing to first observed PAA.",
    "available_observation_days": "Calendar days from initial filing through the cutoff, measured as date difference.",
    "history_uncertain": "A retrieval, linkage, conflicting-row, unknown-suffix, or PAA date problem was detected.",
    "retrieval_uncertain": "A history batch failed or the dataset update timestamp could not be verified.",
    "in_observation_window": "Filing day falls between the initial filing and cutoff inclusive.",
    "reported_cost_change": "Filing estimate minus the original filing estimate, in dollars.",
    "absolute_reported_cost_difference": "Magnitude of the recorded estimated-cost difference in dollars.",
    "reported_cost_change_pct": "Signed percentage change relative to a strictly positive initial estimate.",
    "cost_field_comparison": "Changed or unchanged when both estimates are comparable.",
    "cost_reporting_era": "Filing-day period relative to the February 2, 2026 DOB cost-reporting update.",
    "paa_within_selected_followup": "Outcome using the chosen 12- or 24-month horizon.",
    "selected_followup_months": "Selected calendar-month horizon.",
    "baseline_reported_cost": "Parsed initial_cost from the selected I1 record.",
    "filing_reported_cost": "Parsed initial_cost from the current source record.",
    "initial_filing_number": "Full filing number of the selected I1 record.",
    "initial_filing_date": "Calendar day of the selected I1 filing, used as time zero.",
    "initial_approval_date": "Calendar day of the selected I1 approval, when available.",
    "initial_reported_cost": "Parsed initial_cost from the selected I1 record.",
    ":id": "Socrata system row ID.",
}
for months in (12, 24):
    DEFINITIONS[f"full_{months}m_followup"] = f"Cutoff reaches the {months}-month anniversary."
    DEFINITIONS[f"paa_within_{months}m"] = "True for an observed qualifying PAA, false for verified full follow-up without one, blank otherwise."


def download(label, frame, filename):
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), filename, "text/csv")


def show_cohort():
    st.header("Research cohort")
    st.caption("Select original filings, then retrieve their full public histories. Follow-up starts on the initial filing date.")
    try:
        boroughs, types = filter_options()
    except Exception as exc:
        st.error(f"Could not load DOB filters. Reopen this view to retry. {exc}")
        return
    today = datetime.now(ZoneInfo("America/New_York")).date()
    with st.form("research_cohort"):
        start, end, cutoff = st.columns(3)
        start = start.date_input("First initial filing date", date(today.year - 3, 1, 1), max_value=today)
        end = end.date_input("Last initial filing date", date(today.year - 3, 1, 31), max_value=today)
        cutoff = cutoff.date_input("Observation cutoff", today, max_value=today)
        borough = st.selectbox("Borough", ["All", *boroughs])
        job_type = st.selectbox("Job type", ["All", *types])
        maximum = st.number_input("Maximum initial jobs", 1, 5000, 100)
        months = st.radio("Follow-up in months", [12, 24], horizontal=True)
        run = st.form_submit_button("Collect cohort", type="primary")
    if run:
        st.session_state.pop("research_cohort_result", None)
        try:
            selection = Selection(start, end, cutoff, months, maximum, "" if borough == "All" else borough,
                                  "" if job_type == "All" else job_type)
            with st.spinner("Collecting DOB filing histories…"):
                st.session_state["research_cohort_result"] = cached_cohort(selection)
        except PartialCollection as exc:
            st.session_state["research_cohort_result"] = exc.result
        except Exception as exc:
            st.error(f"Cohort collection failed. {exc}")
    if "research_cohort_result" in st.session_state:
        show_results(st.session_state["research_cohort_result"])


def show_results(result):
    raw, history, projects, quality, issues = (
        pd.DataFrame(result[key]) for key in ("raw", "history", "projects", "quality", "issues")
    )
    metadata = result["metadata"]
    st.caption(f"Initial filings {metadata['start']} to {metadata['end']} · cutoff {metadata['cutoff']} · "
               f"{metadata['months']}-month outcome · collected {metadata['collection_finished_utc']}")
    if metadata["cohort_capped"]:
        st.warning("Additional eligible jobs exist. This cohort contains the earliest jobs up to the selected cap.")
    if metadata["api_error_entries"] or not metadata["source_version_stable"]:
        st.warning("Some public histories may be incomplete. Review collection diagnostics before using the results.")
    if projects.empty:
        st.info("No eligible initial filings were found.")

    analysis, costs, diagnostics, exports = st.tabs(["Amendments", "Estimated costs", "Data quality", "Exports"])
    with analysis:
        if not projects.empty:
            outcomes = projects["paa_within_selected_followup"]
            for column, (label, count) in zip(st.columns(3), [
                ("PAA observed", outcomes.eq(True).sum()), ("No PAA in full follow-up", outcomes.eq(False).sum()),
                ("Unknown outcome", outcomes.isna().sum()),
            ]):
                column.metric(label, int(count))
            st.caption("Unknown outcomes include insufficient follow-up and uncertain histories without a verified event.")
            st.dataframe(projects, hide_index=True)
    with costs:
        st.markdown("These are differences in DOB reported estimates. From February 2, 2026, an initial filing may include "
                    "estimated costs for work filed later. [DOB cost reporting guidance]"
                    "(https://www.nyc.gov/assets/buildings/pdf/report_cost-sn.pdf)")
        if not history.empty:
            followups = history[history["filing_kind"].isin(["PAA", "Subsequent"])]
            fields = ["job_root", "job_filing_number", "filing_day", "in_observation_window", "baseline_reported_cost",
                      "filing_reported_cost", "reported_cost_change", "absolute_reported_cost_difference",
                      "reported_cost_change_pct", "cost_field_comparison", "cost_reporting_era"]
            st.dataframe(followups[fields], hide_index=True)
    with diagnostics:
        st.write({
            "retrieved source rows": len(raw), "unique selected jobs": len(projects),
            "initial filing rows": int(history.get("filing_kind", pd.Series(dtype=str)).eq("Initial").sum()),
            "PAA filing rows": int(history.get("filing_kind", pd.Series(dtype=str)).eq("PAA").sum()),
            "histories without detected problems": int(quality.get("history_uncertain", pd.Series(dtype=bool)).eq(False).sum()),
            "incomplete selected follow-up windows": int(projects.get(f"full_{metadata['months']}m_followup", pd.Series(dtype=bool)).eq(False).sum()),
            "API error entries": metadata["api_error_entries"], "source data update timestamp": metadata["source_rows_updated_at"],
        })
        if not quality.empty:
            st.dataframe(quality, hide_index=True)
        if not issues.empty:
            st.dataframe(issues, hide_index=True)
    with exports:
        frames = {"raw": raw, "linked_history": history, "projects": projects,
                  "quality": pd.concat([quality.assign(record_type="job"), issues.assign(record_type="issue")], ignore_index=True)}
        dictionary = []
        for name, frame in frames.items():
            download(f"Download {name.replace('_', ' ')}", frame, f"dob_cohort_{name}.csv")
            for field in frame:
                source = result["schema"].get(field, {})
                description = DEFINITIONS.get(field, source.get("description") or source.get("name") or field.replace("_", " "))
                dictionary.append({"table": name, "field": field, "description": description,
                                   "source_type": source.get("dataTypeName")})
        for field, source in result["schema"].items():
            if field not in raw:
                dictionary.append({"table": "raw", "field": field,
                                   "description": source.get("description") or source.get("name"),
                                   "source_type": source.get("dataTypeName")})
        download("Download data dictionary", pd.DataFrame(dictionary), "dob_cohort_dictionary.csv")
        download("Download collection metadata", pd.DataFrame([metadata]), "dob_cohort_metadata.csv")
