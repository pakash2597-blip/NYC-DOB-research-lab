"""Reproducible cohort extraction from DOB NOW public filings."""

import calendar
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

API = "https://data.cityofnewyork.us/resource/w9ak-ipjd.json"
METADATA = "https://data.cityofnewyork.us/api/views/w9ak-ipjd.json"
COST_CHANGE = date(2026, 2, 2)
FILING = re.compile(r"([A-Z][0-9]{5,12})-([A-Z])([0-9]+)")
REQUIRED = {"job_filing_number", "filing_date", "approved_date", "initial_cost", "borough", "job_type"}
PROJECT_FIELDS = (
    "borough", "job_type", "job_description", "building_type", "bin", "bbl",
    "total_construction_floor_area", "existing_stories", "proposed_no_of_stories",
    "existing_dwelling_units", "proposed_dwelling_units", "filing_review_type",
)


@dataclass(frozen=True)
class Selection:
    start: date
    end: date
    cutoff: date
    months: int
    maximum: int
    borough: str = ""
    job_type: str = ""

    def __post_init__(self):
        if not self.start <= self.end <= self.cutoff:
            raise ValueError("Choose filing dates on or before the observation cutoff.")
        if self.months not in (12, 24) or not 1 <= self.maximum <= 5000:
            raise ValueError("Choose 12 or 24 months and 1–5,000 initial jobs.")


class DobClient:
    def __init__(self):
        self.last_request = None
        self.requests = 0
        self.retries = 0

    def get(self, url, params=None):
        url = f"{url}?{urlencode(params)}" if params else url
        for attempt in range(4):
            if self.last_request is not None:
                time.sleep(max(0, 0.25 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            self.requests += 1
            try:
                with urlopen(url, timeout=20) as response:
                    return json.load(response)
            except (HTTPError, URLError, TimeoutError) as exc:
                if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                    raise
                if attempt == 3:
                    raise
                retry_after = exc.headers.get("Retry-After") if isinstance(exc, HTTPError) else None
                delay = 2 ** attempt
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        retry_time = parsedate_to_datetime(retry_after)
                        delay = max(delay, (retry_time - datetime.now(timezone.utc)).total_seconds())
                if delay > 30:
                    raise RuntimeError("NYC Open Data requested a longer pause. Retry later.") from exc
                self.retries += 1
                time.sleep(delay)

    def pages(self, where, order, page_size=1000):
        offset = 0
        seen_ids = set()
        while True:
            rows = self.get(API, {"$select": "*, :id", "$where": where, "$order": order,
                                  "$limit": page_size, "$offset": offset})
            if not isinstance(rows, list) or len(rows) > page_size:
                raise ValueError("Unexpected DOB page response.")
            for row in rows:
                row_id = row.get(":id")
                if not row_id or row_id in seen_ids:
                    raise ValueError("DOB pagination returned a missing or repeated row ID.")
                seen_ids.add(row_id)
                yield row
            if len(rows) < page_size:
                return
            offset += len(rows)


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def filing_parts(row):
    return FILING.fullmatch(str(row.get("job_filing_number", "")).strip().upper())


def initial_filter(selection):
    clauses = [
        "job_filing_number like '%-I1'",
        f"filing_date >= '{selection.start}T00:00:00'",
        f"filing_date < '{date.fromordinal(selection.end.toordinal() + 1)}T00:00:00'",
    ]
    for field in ("borough", "job_type"):
        value = getattr(selection, field)
        if value:
            clauses.append(f"upper({field}) = {literal(value.upper())}")
    return " AND ".join(clauses)


def history_filter(roots):
    return " OR ".join(f"job_filing_number like '{root}-%'" for root in roots)


def read_date(value):
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


def money(value):
    try:
        amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
        return amount if amount.is_finite() and amount >= 0 else None
    except InvalidOperation:
        return None


def calendar_months(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def characterize(seed, rows, retrieval_uncertain, selection):
    root = filing_parts(seed)[1]
    by_number = defaultdict(list)
    for row in rows:
        by_number[str(row.get("job_filing_number", "")).strip().upper()].append(row)
    problems = Counter()
    initial_numbers = [number for number in by_number if (match := FILING.fullmatch(number)) and match[2] == "I"]
    baseline = by_number.get(f"{root}-I1", [])
    if not baseline:
        problems["missing_initial"] += 1
    if len(initial_numbers) > 1:
        problems["multiple_initial_numbers"] += 1
    if baseline and seed[":id"] not in {row[":id"] for row in baseline}:
        problems["seed_missing_from_history"] += 1
    baseline_variants = {
        json.dumps({k: v for k, v in row.items() if k != ":id"}, sort_keys=True)
        for row in baseline
    }
    ambiguous_baseline = (len(initial_numbers) != 1 or not baseline or
                          bool(problems["seed_missing_from_history"]) or len(baseline_variants) > 1)

    start = read_date(seed.get("filing_date"))
    initial_cost = money(seed.get("initial_cost"))
    linked, paa_dates = [], []
    for number, copies in by_number.items():
        match = FILING.fullmatch(number)
        kind = {"I": "Initial", "P": "PAA", "S": "Subsequent"}.get(match[2], "Other") if match else "Unrecognized"
        variants = {json.dumps({k: v for k, v in row.items() if k != ":id"}, sort_keys=True) for row in copies}
        conflicting = len(variants) > 1
        problems["duplicate_filing_rows"] += len(copies) - 1
        problems["conflicting_filing_numbers"] += int(conflicting)
        problems["unrecognized_filing_numbers"] += int(kind in ("Other", "Unrecognized"))
        for index, row in enumerate(copies):
            filed = read_date(row.get("filing_date"))
            approved = read_date(row.get("approved_date"))
            amount = money(row.get("initial_cost"))
            problems["missing_or_invalid_filing_dates"] += int(filed is None)
            problems["missing_or_invalid_approval_dates"] += int(approved is None)
            problems["missing_or_invalid_costs"] += int(amount is None)
            if index == 0 and kind == "PAA" and not conflicting:
                if filed is None or start is None or filed < start:
                    problems["paa_date_uncertain"] += 1
                elif filed <= selection.cutoff:
                    paa_dates.append(filed)
            comparable = (kind in ("PAA", "Subsequent") and not ambiguous_baseline and
                          not conflicting and amount is not None and initial_cost is not None)
            delta = amount - initial_cost if comparable else None
            linked.append({
                **row, "job_root": root, "filing_kind": kind, "filing_sequence": match[3] if match else None,
                "duplicate_filing_number": len(copies) > 1, "conflicting_filing_number": conflicting,
                "filing_day": filed, "approval_day": approved,
                "in_observation_window": start <= filed <= selection.cutoff if start and filed else None,
                "baseline_reported_cost": initial_cost, "filing_reported_cost": amount,
                "reported_cost_change": delta, "absolute_reported_cost_difference": abs(delta) if delta is not None else None,
                "reported_cost_change_pct": delta / initial_cost * 100 if delta is not None and initial_cost > 0 else None,
                "cost_field_comparison": ("unchanged" if delta == 0 else "changed") if delta is not None else None,
                "cost_reporting_era": ("since_2026_02_02" if filed >= COST_CHANGE else "before_2026_02_02") if filed else None,
            })

    uncertain = retrieval_uncertain or any(problems[k] for k in (
        "missing_initial", "multiple_initial_numbers", "seed_missing_from_history",
        "conflicting_filing_numbers", "unrecognized_filing_numbers", "paa_date_uncertain",
    ))
    first = min(paa_dates, default=None)
    project = {
        "job_root": root, "initial_filing_number": seed["job_filing_number"],
        "initial_filing_date": start, "initial_approval_date": read_date(seed.get("approved_date")),
        "initial_reported_cost": initial_cost, **{key: seed.get(key) for key in PROJECT_FIELDS},
        **{key: value for key, value in seed.items() if "work_type" in key or key in {"standpipe", "antenna", "sign", "curb_cut", "fence", "scaffold", "shed"}},
        "observed_paa_count": len(paa_dates), "first_observed_paa_date": first,
        "days_to_first_observed_paa": (first - start).days if first and start else None,
        "available_observation_days": (selection.cutoff - start).days if start else None,
        "history_uncertain": uncertain, "retrieval_uncertain": retrieval_uncertain,
    }
    for months in (12, 24):
        end = calendar_months(start, months) if start else None
        complete = bool(end and end <= selection.cutoff)
        observed = bool(end and first and first <= end and not ambiguous_baseline)
        project[f"full_{months}m_followup"] = complete
        project[f"paa_within_{months}m"] = True if observed else (False if complete and not uncertain else None)
    project["selected_followup_months"] = selection.months
    project["paa_within_selected_followup"] = project[f"paa_within_{selection.months}m"]
    diagnostics = {"job_root": root, "history_rows": len(rows), "history_uncertain": uncertain,
                   "retrieval_uncertain": retrieval_uncertain, **problems}
    return linked, project, diagnostics


def collect(selection, client=None):
    client = client or DobClient()
    started = datetime.now(timezone.utc)
    if selection.cutoff > started.date():
        raise ValueError("The observation cutoff cannot be in the future.")
    source = client.get(METADATA)
    schema = {column["fieldName"]: column for column in source["columns"]}
    if missing := REQUIRED - schema.keys():
        raise ValueError(f"Required fields missing from live DOB schema: {', '.join(sorted(missing))}")
    seeds, raw, failures = {}, {}, set()
    issues, queries = [], []
    where = initial_filter(selection)
    order = "filing_date ASC, job_filing_number ASC, :id ASC"
    queries.append({"phase": "selection", "where": where, "order": order})
    capped = False
    for row in client.pages(where, order):
        match = filing_parts(row)
        if not match or match.groups()[1:] != ("I", "1"):
            issues.append({"phase": "selection", "filing_number": row.get("job_filing_number"),
                           "issue": "unrecognized_initial_identifier"})
            raw[row[":id"]] = row
            continue
        root = match[1]
        if root not in seeds and len(seeds) == selection.maximum:
            capped = True
            break
        seeds.setdefault(root, row)
        raw[row[":id"]] = row

    histories = defaultdict(list)
    roots = list(seeds)
    for offset in range(0, len(roots), 30):
        batch = roots[offset:offset + 30]
        where = history_filter(batch)
        order = "job_filing_number ASC, :id ASC"
        queries.append({"phase": "history", "where": where, "order": order})
        try:
            for row in client.pages(where, order):
                raw[row[":id"]] = row
                root = str(row.get("job_filing_number", "")).strip().upper().split("-", 1)[0]
                if root not in batch:
                    raise ValueError("History query returned a filing outside the requested roots.")
                histories[root].append(row)
        except (URLError, TimeoutError, ValueError, RuntimeError) as exc:
            failures.update(batch)
            issues.append({"phase": "history", "roots": ",".join(batch), "issue": str(exc)})
    try:
        end_source = client.get(METADATA)
        stable = source.get("rowsUpdatedAt") is not None and source["rowsUpdatedAt"] == end_source.get("rowsUpdatedAt")
    except (URLError, TimeoutError, ValueError, RuntimeError) as exc:
        stable = False
        issues.append({"phase": "metadata", "issue": str(exc)})
    if not stable:
        issues.append({"phase": "metadata", "issue": "Source timestamp changed or could not be verified."})

    linked, projects, diagnostics = [], [], []
    for root, seed in seeds.items():
        history, project, quality = characterize(seed, histories[root], root in failures or not stable, selection)
        linked.extend(history)
        projects.append(project)
        diagnostics.append(quality)

    metadata = {
        **asdict(selection), "dataset": "w9ak-ipjd", "endpoint": API, "extractor_version": "0.3",
        "metadata_endpoint": METADATA, "time_origin": "initial filing date",
        "event_date": "PAA filing date", "cutoff_inclusive": True,
        "collection_started_utc": started.isoformat(), "collection_finished_utc": datetime.now(timezone.utc).isoformat(),
        "source_rows_updated_at": source.get("rowsUpdatedAt"), "source_version_stable": stable,
        "cohort_capped": capped, "history_batch_size": 30, "page_size": 1000,
        "api_requests": client.requests, "api_retries": client.retries, "api_error_entries": sum(
            row["phase"] in ("history", "metadata") for row in issues),
        "query_log": json.dumps(queries), "cost_reporting_change_date": COST_CHANGE,
    }
    return {"raw": list(raw.values()), "history": linked, "projects": projects,
            "quality": diagnostics, "issues": issues, "metadata": metadata, "schema": schema}
