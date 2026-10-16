"""Synthetic value-coverage validation; no source downloads or private data."""
import copy
import unittest

from tools.goias_finance_audit import financial_summary


def metric(status="missing", known=0, missing=0, declarations=None, subtotal=None):
    return {"status": status, "known_records": known, "missing_records": missing,
            "zero_declarations": declarations or [],
            "known_subtotal": subtotal if subtotal is not None else 0 if known or declarations else None}


class FinancialContractTests(unittest.TestCase):
    def data(self):
        return {"financial_schema": 1, "candidates": [
            {"revenue": None, "expenses": None, "financial_coverage": {
                "revenue": metric("partial", 1, 1, subtotal=12.5), "expenses": metric()}},
            {"revenue": 0, "expenses": 0, "financial_coverage": {
                "revenue": metric("known", declarations=[{"source_file": "receitas_candidatos_2026_GO.csv", "source_row": 2}]),
                "expenses": metric("known", 1)}},
            {"revenue": None, "expenses": None, "financial_coverage": {
                "revenue": metric("missing", 0, 1), "expenses": metric()}},
        ], "transfers": [{"amount": None}, {"amount": 0}, {"amount": 12.5}]}

    def test_audit_counts_partial_missing_positive_and_explicit_zero(self):
        summary = financial_summary(self.data())
        self.assertEqual(summary["revenue"], {"known": 1, "partial": 1, "missing": 1, "zero": 1, "subtotal": 12.5})
        self.assertEqual(summary["expenses"]["subtotal"], 0)

    def test_legacy_zero_is_preserved_without_reclassifying_history(self):
        data = {"candidates": [{"revenue": 0, "expenses": 5}, {"revenue": None}]}
        original = copy.deepcopy(data)
        summary = financial_summary(data)
        self.assertEqual(summary["revenue"]["zero"], 1)
        self.assertEqual(summary["revenue"]["subtotal"], 0)
        self.assertEqual(data, original)

    def test_all_missing_is_not_zero(self):
        summary = financial_summary({"candidates": [{"revenue": None, "expenses": None}]})
        self.assertIsNone(summary["revenue"]["subtotal"])
        self.assertEqual(summary["revenue"]["zero"], 0)

    def test_partial_zero_is_not_counted_as_a_complete_zero(self):
        data = self.data()
        data["candidates"][0]["financial_coverage"]["revenue"]["known_subtotal"] = 0
        self.assertEqual(financial_summary(data)["revenue"]["zero"], 1)

    def test_inconsistent_financial_metadata_fails_closed(self):
        for replacement in [metric("known", 0), metric("known", 1, 1), metric("missing", 1),
                            metric("known", -1), metric("known", 1.5),
                            metric("known", declarations=[{"source_file": "wrong.csv", "source_row": 2}])]:
            data = self.data()
            data["candidates"][0]["financial_coverage"]["revenue"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                financial_summary(data)
        data = self.data()
        del data["candidates"][0]["financial_coverage"]
        with self.assertRaises(ValueError):
            financial_summary(data)

    def test_invalid_numeric_values_and_schema_fail_closed(self):
        for value in (float("nan"), float("inf"), -2, "0", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                financial_summary({"candidates": [{"revenue": value}]})
            with self.subTest(transfer=value), self.assertRaises(ValueError):
                financial_summary({"candidates": [], "transfers": [{"amount": value}]})
        for schema in (True, 2, "1"):
            with self.assertRaises(ValueError):
                financial_summary({"financial_schema": schema, "candidates": []})


if __name__ == "__main__":
    unittest.main()
