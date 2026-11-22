# NYC DOB Research Lab — GitHub / Streamlit Cloud edition (v0.2-deploy)

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

## Scientific cautions

- This is **not** a trained AI model or a population-wide complete longitudinal cohort.
- A PAA is not equivalent to a construction change order or cost overrun.
- DOB `initial_cost` is an administrative estimate, not actual paid contractor cost.
- Capped sample rates cannot be interpreted as NYC-wide incidence.
- The single-job lookup is complete within the matching public dataset if fewer than 5,000 rows are returned; publication-grade checks should verify suffix logic and records against the DOB NOW portal.
- Dataset access and API behavior must be confirmed in the deployed environment.

## Research roadmap

1. **v0.3:** Reproducible extraction of all filings for defined initial-job cohorts, with follow-up window and log.
2. **v0.4:** Cohort-level EDA, completeness checks, and missing-data report.
3. **v0.5:** Risk-model baseline (logistic regression and time-to-first-PAA); no leakage across time.
4. **v0.6:** Explainable ML and calibration; pre-registered evaluation and external/temporal validation.
5. **v1.0:** Paper tables and source-linked reproducibility bundle.
