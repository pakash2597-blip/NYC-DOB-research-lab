"""NYC DOB Research Lab: publicly available filing analyses, no credentials required."""
import io
import re
from datetime import date

import pandas as pd
import requests
import streamlit as st
import plotly.express as px

DATASET_ID = 'w9ak-ipjd'
API = f'https://data.cityofnewyork.us/resource/{DATASET_ID}.json'
METADATA = f'https://data.cityofnewyork.us/api/views/{DATASET_ID}.json'
TIMEOUT = 40
APP_VERSION = '0.2-deploy'


st.set_page_config(page_title='DOB Research Lab', page_icon='🏗️', layout='wide')
st.title('🏗️ NYC DOB Research Lab')
st.caption(f'Version {APP_VERSION} · Independent exploration of public NYC DOB NOW filings and PAAs')
st.info('DOB filing estimates are not contractor change-order prices or verified actual costs. Differences in an initial_cost field must not be called cost overruns.')

@st.cache_data(ttl=3600, show_spinner=False)
def schema():
    r = requests.get(METADATA, timeout=TIMEOUT)
    r.raise_for_status()
    m = r.json()
    return [c['fieldName'] for c in m['columns'] if c.get('fieldName') and not c['fieldName'].startswith(':')], m.get('rowsUpdatedAt')

@st.cache_data(ttl=1800, show_spinner=False)
def fetch(where, limit, page_size=1000):
    out=[]
    for offset in range(0, limit, page_size):
        params={'$limit':min(page_size,limit-offset),'$offset':offset,'$order':'job_filing_number ASC'}
        if where: params['$where']=where
        r=requests.get(API,params=params,timeout=TIMEOUT)
        r.raise_for_status()
        part=r.json()
        out.extend(part)
        if len(part)<params['$limit']:break
    return pd.DataFrame(out)

@st.cache_data(ttl=300, show_spinner=False)
def connectivity_test():
    metadata = requests.get(METADATA, timeout=15)
    metadata.raise_for_status()
    sample = requests.get(API, params={'$limit': 1}, timeout=15)
    sample.raise_for_status()
    records = sample.json()
    if not isinstance(records, list):
        raise ValueError('Expected a list of records from NYC Open Data API')
    return {'metadata_status': metadata.status_code, 'sample_status': sample.status_code,
            'sample_count': len(records), 'sample_columns': list(records[0]) if records else []}

@st.cache_data(ttl=900, show_spinner=False)
def complete_job_history(job_root):
    # Validate before including an identifier in a SoQL query.
    root = job_root.strip().upper()
    if not re.fullmatch(r'[A-Z][0-9]{5,12}', root):
        raise ValueError('Enter the root job number, such as B00244768 (without -I1 or -P1).')
    # Prefix matching fetches initial filing and amendments for the selected job.
    query = {'$where': f"job_filing_number like '{root}-%'",
             '$order': 'job_filing_number ASC', '$limit': 5000}
    r = requests.get(API, params=query, timeout=TIMEOUT)
    r.raise_for_status()
    records = r.json()
    if len(records) >= 5000:
        raise ValueError('History exceeds the safety cap; completeness cannot be assumed.')
    return pd.DataFrame(records)

def analyze(frame):
    d=frame.copy()
    d['job_filing_number']=d['job_filing_number'].astype('string').str.strip()
    d['filing_kind']=d['job_filing_number'].str.extract(r'-(I|P)\d+$',flags=re.I,expand=False).str.upper().map({'I':'Initial','P':'PAA'}).fillna('Other')
    d['job_root']=d['job_filing_number'].str.replace(r'-(?:I|P)\d+$','',regex=True,flags=re.I)
    if 'initial_cost' in d:
        d['reported_initial_cost']=pd.to_numeric(d['initial_cost'].astype('string').str.replace(r'[$,]','',regex=True),errors='coerce')
    else:d['reported_initial_cost']=float('nan')
    if 'filing_date' in d:d['filing_date_parsed']=pd.to_datetime(d['filing_date'],errors='coerce',utc=True)
    else:d['filing_date_parsed']=pd.NaT
    return d

def job_summary(d):
    # This is only a complete matched sample when all relevant rows for the chosen jobs were retrieved.
    rows=[]
    for root,g in d.groupby('job_root',dropna=True):
        init=g[g.filing_kind=='Initial'].sort_values('filing_date_parsed')
        paa=g[g.filing_kind=='PAA'].sort_values('filing_date_parsed')
        if init.empty:continue
        first=init.iloc[0]
        vals=paa['reported_initial_cost'].dropna()
        first_cost=first['reported_initial_cost']
        rows.append({'job_root':root,'initial_date':first['filing_date_parsed'],
                     'initial_recorded_cost':first_cost,'paa_count_in_sample':len(paa),
                     'latest_paa_recorded_cost':vals.iloc[-1] if len(vals) else float('nan'),
                     'cost_field_difference':(vals.iloc[-1]-first_cost) if len(vals) and pd.notna(first_cost) else float('nan'),
                     'first_paa_date':paa['filing_date_parsed'].min() if not paa.empty else pd.NaT,
                     'initial_work_type':first.get('job_type','')})
    return pd.DataFrame(rows)

with st.sidebar:
    st.header('Data source')
    source=st.radio('Source', ['Live NYC Open Data API','Upload CSV'],help='Upload a CSV previously exported from this or the official DOB dataset.')
    st.markdown('[Official NYC DOB dataset](https://data.cityofnewyork.us/d/w9ak-ipjd)')
    if st.button('Test live API connection'):
        try:
            status=connectivity_test()
            st.success(f"NYC API reachable (metadata HTTP {status['metadata_status']}; sample HTTP {status['sample_status']}).")
            st.caption(f"Sample returned {status['sample_count']} record(s).")
        except Exception as exc:
            st.error(f'Live API test failed: {type(exc).__name__}: {exc}')
    limit=st.number_input('Maximum records to retrieve',min_value=100,max_value=50000,value=5000,step=500)
    st.caption('Records are a capped sample, not a random sample and not a complete longitudinal cohort. API requests may be rate-limited.')

if source=='Live NYC Open Data API':
    try:
        fields,updated=schema()
        st.caption(f'Live metadata loaded. {len(fields)} public fields. Data last updated (source timestamp): {updated}.')
        must=['job_filing_number','initial_cost','filing_date']
        missing=[x for x in must if x not in fields]
        if missing:st.error(f'Expected fields not in current public schema: {missing}. Please review dataset changes.');st.stop()
        with st.expander('Inspect actual public schema',expanded=False):
            st.write(', '.join(fields))
            st.download_button('Download schema list',pd.DataFrame({'field':fields}).to_csv(index=False),'dob_schema.csv','text/csv')
        st.subheader('Load public records')
        st.caption('Optional year filter is applied to each filing’s date, **not** the original project date. This can hide related I/P records outside the range.')
        use_years=st.checkbox('Filter filing dates (may produce incomplete PAA histories)', value=False)
        if use_years:
            years=st.slider('Filing date years',2018,date.today().year,(2023,date.today().year))
            where=f"filing_date between '{years[0]}-01-01T00:00:00' and '{years[1]}-12-31T23:59:59'"
        else:where=''
        if st.button('Load DOB filings',type='primary'):
            with st.spinner('Retrieving data from NYC Open Data...'):
                st.session_state['dob_raw']=fetch(where,int(limit))
            st.session_state['dob_where']=where
    except Exception as exc:
        st.error(f'Could not load live DOB data. Check connection or API schema: {exc}')
        st.stop()
else:
    upload=st.file_uploader('Upload DOB CSV',type=['csv'])
    if upload is not None:
        try:st.session_state['dob_raw']=pd.read_csv(upload,dtype={'job_filing_number':'string'},low_memory=False)
        except Exception as exc:st.error(str(exc))

st.subheader('Find a full job filing history')
st.caption('Unlike capped samples, this retrieves initial and PAA filings for one specified DOB NOW job number directly from the public API.')
root_input = st.text_input('Job root (example: B00244768)', value='', placeholder='B00244768')
if st.button('Fetch complete job history'):
    try:
        full = complete_job_history(root_input)
        st.session_state['full_job_history'] = full
        st.session_state['full_job_root'] = root_input.strip().upper()
    except Exception as exc:
        st.error(f'Could not retrieve job: {type(exc).__name__}: {exc}')
if 'full_job_history' in st.session_state:
    h = st.session_state['full_job_history']
    st.write(f"Job {st.session_state['full_job_root']}: {len(h)} public filing record(s) returned.")
    if h.empty:
        st.info('No records found under this job root.')
    else:
        hd = analyze(h)
        show_cols=[c for c in ['job_filing_number','filing_date','filing_kind','filing_status','initial_cost','job_type','job_description'] if c in hd.columns]
        st.dataframe(hd[show_cols], hide_index=True, use_container_width=True)
        st.download_button('Export complete job history',h.to_csv(index=False).encode(),'dob_job_history.csv','text/csv')

if 'dob_raw' not in st.session_state:
    st.markdown('### Start by loading public records or uploading a CSV.')
    st.stop()
raw=st.session_state['dob_raw']
if 'job_filing_number' not in raw.columns:
    st.error('Missing job_filing_number. Confirm you are using DOB NOW Job Application Filings.');st.stop()
d=analyze(raw)
st.subheader('Dataset overview')
cols=st.columns(4)
cols[0].metric('Loaded filing records',f'{len(d):,}')
cols[1].metric('Unique job roots in sample',f'{d.job_root.nunique():,}')
cols[2].metric('Initial filings in sample',f'{(d.filing_kind=="Initial").sum():,}')
cols[3].metric('PAA filings in sample',f'{(d.filing_kind=="PAA").sum():,}')
st.warning('Important: paginated, capped API results and date filters may omit matching filings. PAA incidence and cost differences below describe the **loaded sample only**. They are not NYC population rates or a valid training cohort until full job histories and observation windows are constructed.')

tab1,tab2,tab3,tab4=st.tabs(['Explore records','Match initial filings & PAAs','Costs and distributions','Research-quality diagnostics'])
with tab1:
    st.dataframe(d,hide_index=True,use_container_width=True)
    st.download_button('Export loaded raw records',raw.to_csv(index=False).encode(),'dob_loaded_records.csv','text/csv')
    if 'job_type' in d:
        counts=d['job_type'].fillna('(Missing)').value_counts().head(15).reset_index()
        counts.columns=['Job type','Record count']
        st.plotly_chart(px.bar(counts,x='Job type',y='Record count',title='Top filing job types in loaded sample'),use_container_width=True)
with tab2:
    summary=job_summary(d)
    st.metric('Initial jobs with a matching PAA in loaded sample',f'{(summary.paa_count_in_sample>0).sum():,}' if len(summary) else '0')
    if len(summary):
        st.dataframe(summary,hide_index=True,use_container_width=True)
        st.download_button('Export matched job summary',summary.to_csv(index=False).encode(),'dob_matched_jobs_sample.csv','text/csv')
        candidates=summary[summary.paa_count_in_sample>0]
        if not candidates.empty:
            chosen=st.selectbox('Inspect one matched job',candidates.job_root.astype(str).tolist())
            detail=d[d.job_root.astype(str)==chosen].sort_values('filing_date_parsed')
            present=[x for x in ['job_filing_number','filing_date','filing_kind','filing_status','initial_cost','job_description','job_type'] if x in detail]
            st.dataframe(detail[present],hide_index=True,use_container_width=True)
with tab3:
    priced=d[d.reported_initial_cost.notna() & (d.reported_initial_cost>=0)].copy()
    st.metric('Records with numeric nonnegative initial_cost',f'{len(priced):,}')
    if not priced.empty:
        st.plotly_chart(px.histogram(priced,x='reported_initial_cost',color='filing_kind',nbins=60,log_y=True,title='Recorded initial_cost distribution (not project overruns)'),use_container_width=True)
    s=job_summary(d)
    if not s.empty:
        matched=s[s.paa_count_in_sample>0]
        num=matched['cost_field_difference'].notna().sum()
        unequal=((matched['cost_field_difference']!=0)&matched['cost_field_difference'].notna()).sum()
        st.write(f'Among **{num:,}** matched jobs with comparable numeric fields, **{unequal:,}** have a nonzero field difference. This does not establish a change in real construction cost.')
with tab4:
    st.write('**Missingness (loaded records):**')
    missing=d.isna().mean().mul(100).sort_values(ascending=False).reset_index()
    missing.columns=['Field','Missing (%)']
    st.dataframe(missing,hide_index=True,use_container_width=True)
    st.write('**Duplicates and linking diagnostics**')
    st.json({'duplicate_filing_numbers':int(d.job_filing_number.duplicated().sum()),
             'unrecognized_suffixes':int((d.filing_kind=='Other').sum()),
             'paa_records_without_initial_in_sample':int(d.loc[(d.filing_kind=='PAA') & (~d.job_root.isin(d.loc[d.filing_kind=='Initial','job_root']))].shape[0])})
    st.write('**Research safeguards**')
    st.markdown('''- Do not train a PAA risk model on a capped first-N API sample.
- Fetch all records for an initial-filing cohort and their subsequent amendments; verify stable job identifiers.
- Use only features available as of the initial-filing prediction time.
- Define 12/24-month follow-up and exclude right-censored cases.
- Audit whether the cost field is copied forward or amended, and DOB reporting-rule changes.
- Split by job and by calendar time; document schema and extraction timestamps.
- No claims of contractor change-order prices, actual overruns, or causal effects.''')
