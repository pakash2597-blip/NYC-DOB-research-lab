import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.error import URLError

from cohort import METADATA, REQUIRED, DobClient, Selection, characterize, collect


def filing(suffix, filed, cost="100", row_id=None):
    return {"job_filing_number": f"B00244768-{suffix}", ":id": row_id or suffix,
            "filing_date": filed, "initial_cost": cost}


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.initial = filing("I1", "2020-02-29")
        self.selection = Selection(date(2020, 2, 1), date(2020, 2, 29), date(2021, 2, 28), 12, 1)

    def test_boundary_and_cost_comparisons(self):
        paa = filing("P1", "2021-02-28", "90")
        history, project, quality = characterize(self.initial, [self.initial, paa], False, self.selection)
        self.assertTrue(project["paa_within_12m"])
        self.assertTrue(project["paa_within_24m"])
        self.assertFalse(project["full_24m_followup"])
        self.assertEqual(project["days_to_first_observed_paa"], 365)
        self.assertEqual(history[1]["reported_cost_change"], Decimal("-10"))
        self.assertEqual(history[1]["absolute_reported_cost_difference"], Decimal("10"))
        self.assertEqual(history[1]["reported_cost_change_pct"], Decimal("-10"))
        self.assertFalse(quality["history_uncertain"])

    def test_future_record_is_preserved_without_counting_it(self):
        paa = filing("P1", "2021-03-01")
        history, project, _ = characterize(self.initial, [self.initial, paa], False, self.selection)
        self.assertFalse(history[1]["in_observation_window"])
        self.assertEqual(project["observed_paa_count"], 0)
        self.assertIs(project["paa_within_12m"], False)
        self.assertIsNone(project["paa_within_24m"])

    def test_unknown_negative_when_retrieval_fails_or_paa_date_is_missing(self):
        for rows, failed in (([self.initial], True), ([self.initial, filing("P1", None)], False)):
            with self.subTest(failed=failed):
                _, project, _ = characterize(self.initial, rows, failed, self.selection)
                self.assertIsNone(project["paa_within_12m"])
                self.assertTrue(project["history_uncertain"])

    def test_duplicate_is_counted_once_and_conflicting_paa_is_uncertain(self):
        first = filing("P1", "2020-05-01")
        copy = dict(first, **{":id": "copy"})
        _, project, quality = characterize(self.initial, [self.initial, first, copy], False, self.selection)
        self.assertEqual(project["observed_paa_count"], 1)
        self.assertEqual(quality["duplicate_filing_rows"], 1)
        copy["filing_date"] = "2020-05-02"
        _, project, quality = characterize(self.initial, [self.initial, first, copy], False, self.selection)
        self.assertIsNone(project["paa_within_12m"])
        self.assertEqual(quality["conflicting_filing_numbers"], 1)

    def test_pagination_rejects_repeat_rows(self):
        client = DobClient()
        with patch.object(client, "get", side_effect=[[self.initial], [self.initial]]):
            with self.assertRaisesRegex(ValueError, "repeated row ID"):
                list(client.pages("where", ":id", page_size=1))

    def test_partial_collection_marks_outcomes_and_reports_cap(self):
        source = {"columns": [{"fieldName": field} for field in REQUIRED], "rowsUpdatedAt": 1}
        other = dict(self.initial, job_filing_number="B00244769-I1", **{":id": "other"})
        client = DobClient()
        def pages(where, order):
            yield self.initial
            if where.startswith("job_filing_number like '%"):
                yield other
            else:
                raise URLError("test batch failure")

        with patch.object(client, "get", return_value=source) as request, patch.object(client, "pages", side_effect=pages):
            result = collect(self.selection, client)
        self.assertEqual(request.call_count, 2)
        request.assert_called_with(METADATA)
        self.assertTrue(result["metadata"]["cohort_capped"])
        self.assertEqual(result["metadata"]["api_error_entries"], 1)
        self.assertEqual(len(result["raw"]), 1)
        self.assertIsNone(result["projects"][0]["paa_within_12m"])


if __name__ == "__main__":
    unittest.main()
