# NYC DOB Research Lab — GitHub / Streamlit Cloud edition (v0.3)

Independent prototype to analyze NYC DOB NOW public filings and PAA records. Not affiliated with NYC DOB.

## Deploy in Streamlit Community Cloud

1. Create an empty GitHub repo such as `nyc-dob-research-lab`.
2. Upload **the contents of this folder directly to the repo root**: `app.py`, `requirements.txt`, `.gitignore`, `.streamlit/config.toml`, `README.md`. Do not upload the ZIP as the only repo file.
3. Open https://share.streamlit.io and sign in with GitHub.
4. Choose **Create app** > **Yup, I have an app**; select your repo, branch `main`, entrypoint `app.py`; then **Deploy**.
5. Open the deployed application and select **Test live API connection** in the sidebar. A successful check displays HTTP 200 for metadata and a one-row sample.
6. Enter a DOB NOW job root (example `B00244768`), click **Fetch complete job history**, and confirm initial/PAA rows appear.
7. Click **Load DOB filings** to explore a capped sample, or upload an official CSV.

If you encounter build errors, inspect Community Cloud app logs, verify the entrypoint is `app.py`, and verify package requirements are installed.

## Run locally

Python 3.10+:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Official dataset

- https://data.cityofnewyork.us/d/w9ak-ipjd
- API: https://data.cityofnewyork.us/resource/w9ak-ipjd.json
- Metadata: https://data.cityofnewyork.us/api/views/w9ak-ipjd.json

No Socrata app token is needed for basic access; usage limits may apply. The app does not store permanent data; Streamlit session state and cache can reset. Never commit private credentials to GitHub.

## Features

- API health check and actual schema view.
- Capped API exploration with upload/download CSV.
- Targeted initial/PAA job-history lookup.
- Reported `initial_cost` comparisons, charts, missingness, and linkage diagnostics.

## Research cohort

Select **Research cohort** in the sidebar. Choose the initial filing date range, borough,
job type, maximum jobs, cutoff date, and 12- or 24-month follow-up. Select **Collect cohort**,
then open **Amendments**, **Estimated costs**, **Data quality**, or **Exports**.

- The selection starts with public `-I1` rows and chooses distinct job roots in ascending
  filing-date order. A warning identifies a cap that excludes additional eligible jobs.
- History queries use the exact job root followed by a hyphen, in batches of 30 roots.
  They paginate by a deterministic order including Socrata row ID, without a history row cap.
  The extractor checks the published update timestamp before and after collection. The
  source remains a live public extract and this check provides an indication of stability.
- Time zero is the **initial filing day**. The event date is the **PAA filing day**.
  Both endpoints are inclusive. A qualifying event can produce a positive before the
  cohort reaches full follow-up. A negative requires full calendar-month follow-up and
  no detected history issue. Blank outcomes are unknown. Approval dates are retained.
- Raw and linked CSVs retain records after the cutoff so the retrieval is auditable.
  The project outcomes use only events through the cutoff. The data quality CSV contains
  per-job diagnostics and collection issues. Keep all six CSVs together, including the
  query log and collection timestamps in the metadata CSV.
- The public extract can omit records or reflect later updates. Archived CSVs preserve
  the collected data. Current values should be checked for availability at prediction
  time before any future modeling. A capped cohort describes its selected jobs.
- The estimated-cost comparison uses the public `initial_cost` field. Starting
  February 2, 2026, DOB allowed an initial filing to include costs for work filed later.
  The exports flag the reporting era for each filing. See the
  [DOB service notice](https://www.nyc.gov/assets/buildings/pdf/report_cost-sn.pdf).

Run the cohort tests from the repository root with `python -m unittest discover -s tests -v`.
For a live check, collect a small cohort, verify that a recent filing with no observed
PAA has a blank outcome when the cutoff precedes its anniversary, and download the
six exports. In **Existing filing explorer**, fetch `B00244768` to check the initial
filing and three published amendments.

## Scientific cautions

- This is **not** a trained AI model or a population-wide complete longitudinal cohort.
- A PAA is not equivalent to a construction change order or cost overrun.
- DOB `initial_cost` is an administrative estimate, not actual paid contractor cost.
- Capped sample rates cannot be interpreted as NYC-wide incidence.
- The single-job lookup paginates public records. Publication-grade checks should verify suffix logic and records against the DOB NOW portal.
- Dataset access and API behavior must be confirmed in the deployed environment.

## Research roadmap

1. **v0.3:** Research cohort extraction, follow-up outcomes, quality checks, and CSV exports.
2. **v0.4:** Cohort-level EDA, completeness checks, and missing-data report.
3. **v0.5:** Risk-model baseline (logistic regression and time-to-first-PAA); no leakage across time.
4. **v0.6:** Explainable ML and calibration; pre-registered evaluation and external/temporal validation.
5. **v1.0:** Paper tables and source-linked reproducibility bundle.
