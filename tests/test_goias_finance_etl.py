import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "tools/goias_finance_etl.py"
spec = importlib.util.spec_from_file_location("go_finance_etl", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def create_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, contents in files.items():
            z.writestr(name, contents)


class GoFinanceTests(unittest.TestCase):
    def export_values(self, receipts, expenses):
        """All rows and names here are synthetic, without personal documents."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            create_zip(tmp / "c.zip", {"consulta_cand_2026_GO.csv":
                "SG_UF;CD_CARGO;SQ_CANDIDATO;NM_CANDIDATO\n" +
                "\n".join(f"GO;6;{cid};Exemplo {cid}" for cid in ("a", "b", "c", "d")) + "\n"})
            create_zip(tmp / "f.zip", {
                "receitas_candidatos_2026_GO.csv":
                    "SQ_CANDIDATO;SQ_RECEITA;VR_RECEITA;NM_DOADOR;DT_RECEITA\n" + "\n".join(receipts) + "\n",
                "despesas_contratadas_candidatos_2026_GO.csv":
                    "SQ_CANDIDATO;SQ_DESPESA;VR_DESPESA_CONTRATADA\n" + "\n".join(expenses) + "\n",
            })
            return mod.build(tmp / "c.zip", tmp / "f.zip")

    def test_absence_explicit_zero_and_positive_have_distinct_coverage(self):
        data = self.export_values(["a;11;12,50;Origem A;01/10/2026", "b;12;0,00;Origem B;01/10/2026", "c;-1;0,00;;"], ["a;21;5,00", "b;22;0,00"])
        candidates = {row["id"]: row for row in data["candidates"]}
        self.assertEqual(data["financial_schema"], 1)
        self.assertEqual([candidates[c]["revenue"] for c in "abcd"], [12.5, 0, 0, None])
        self.assertEqual([candidates[c]["expenses"] for c in "abcd"], [5, 0, None, None])
        self.assertEqual(candidates["d"]["financial_coverage"]["revenue"]["status"], "missing")
        zero = candidates["c"]["financial_coverage"]["revenue"]
        self.assertEqual(zero["status"], "known")
        self.assertEqual(zero["known_records"], 0)
        self.assertEqual(zero["zero_declarations"], [{"source_file": "receitas_candidatos_2026_GO.csv", "source_row": 4}])
        self.assertEqual(len(data["transfers"]), 2)
        self.assertEqual(data["financial_audit"]["revenue"]["missing"], 1)
        self.assertEqual(data["financial_audit"]["revenue"]["subtotal"], 12.5)

    def test_missing_amounts_keep_official_receipts_and_mark_subtotals(self):
        data = self.export_values(["a;11;12,50;Origem A;01/10/2026", "a;12;#NULO;Origem A;02/10/2026", "b;13;-1;Origem B;03/10/2026"], ["a;21;5,00", "a;22;#NULO", "b;23;"])
        candidates = {row["id"]: row for row in data["candidates"]}
        self.assertIsNone(candidates["a"]["revenue"])
        self.assertIsNone(candidates["a"]["expenses"])
        self.assertEqual(candidates["a"]["financial_coverage"]["revenue"]["known_subtotal"], 12.5)
        self.assertEqual(candidates["a"]["financial_coverage"]["expenses"]["known_subtotal"], 5)
        for field in ("revenue", "expenses"):
            self.assertEqual(candidates["a"]["financial_coverage"][field]["status"], "partial")
            self.assertEqual(candidates["a"]["financial_coverage"][field]["missing_records"], 1)
            self.assertIsNone(candidates["b"][field])
            self.assertEqual(candidates["b"]["financial_coverage"][field]["missing_records"], 1)
        self.assertEqual(len(data["transfers"]), 3)
        self.assertEqual(sum(row["amount"] is None for row in data["transfers"]), 2)
        self.assertEqual({row["source_record_id"] for row in data["transfers"]}, {"11", "12", "13"})
        self.assertEqual(data["identity_audit"]["revenue_total"], "12.50")
        self.assertEqual(data["financial_audit"]["revenue"]["partial"], 1)

    def test_zero_declaration_does_not_hide_missing_source_value(self):
        data = self.export_values(["a;-1;0,00;;", "a;11;#NULO;Origem A;01/10/2026"], ["a;21;0,00"])
        row = next(row for row in data["candidates"] if row["id"] == "a")
        self.assertIsNone(row["revenue"])
        self.assertEqual(row["financial_coverage"]["revenue"]["known_subtotal"], 0)
        self.assertEqual(row["financial_coverage"]["revenue"]["status"], "partial")
        self.assertIsNone(data["transfers"][0]["amount"])

    def test_zero_declarations_and_header_only_files_do_not_fabricate_activity(self):
        data = self.export_values(["a;-1;0,00;;"], ["a;21;0,00"])
        self.assertEqual(data["transfers"], [])
        self.assertEqual(data["candidates"][0]["revenue"], 0)
        empty = self.export_values([], [])
        self.assertTrue(all(c["revenue"] is None and c["expenses"] is None for c in empty["candidates"]))
        self.assertIsNone(empty["financial_audit"]["revenue"]["subtotal"])

    def test_missing_row_without_transaction_only_marks_coverage(self):
        data = self.export_values(["a;-1;#NULO;;"], ["a;-1;#NULO"])
        self.assertEqual(data["transfers"], [])
        self.assertEqual(data["candidates"][0]["financial_coverage"]["revenue"]["missing_records"], 1)

    def test_non_finite_negative_and_invalid_values_fail_closed(self):
        for amount in ("NaN", "Infinity", "-2,00", "not-a-number"):
            with self.subTest(amount=amount), self.assertRaisesRegex(ValueError, "Invalid monetary number"):
                self.export_values([f"a;11;{amount};Origem;01/10/2026"], ["a;21;0,00"])

    def test_unmapped_header_is_not_treated_as_a_missing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            create_zip(tmp / "c.zip", {"consulta_cand_2026_GO.csv":
                "SG_UF;CD_CARGO;SQ_CANDIDATO;NM_CANDIDATO\nGO;6;a;Exemplo\n"})
            create_zip(tmp / "f.zip", {
                "receitas_candidatos_2026_GO.csv": "SQ_CANDIDATO;SQ_RECEITA;WRONG_VALUE_COLUMN\n",
                "despesas_contratadas_candidatos_2026_GO.csv": "SQ_CANDIDATO;SQ_DESPESA;VR_DESPESA_CONTRATADA\na;21;0,00\n",
            })
            with self.assertRaisesRegex(ValueError, "columns not mapped"):
                mod.build(tmp / "c.zip", tmp / "f.zip")

    def test_scoped_candidates_and_finance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cand = tmp / "candidates.zip"
            fin = tmp / "finance.zip"
            create_zip(cand, {
                "consulta_cand_2026_BR.csv":
                    "SG_UF;CD_CARGO;SQ_CANDIDATO;NM_URNA_CANDIDATO;SG_PARTIDO;NR_CANDIDATO\n"
                    "GO;6;123;Candidato Exemplo;AAA;1234\n"
                    "GO;3;125;Governador Exemplo;BBB;12\n"
                    "SP;7;124;Outro Estado;CCC;45678\n",
            })
            create_zip(fin, {
                "receitas_candidatos_2026_GO.csv":
                    "SQ_CANDIDATO;SQ_RECEITA;VR_RECEITA;NR_CPF_CNPJ_DOADOR;NM_DOADOR;DT_RECEITA\n"
                    "123;91;1250,50;12345678909;Pessoa Exemplo;01/10/2026\n",
                "receitas_candidatos_2026_BRASIL.csv":
                    "SQ_CANDIDATO;SQ_RECEITA;VR_RECEITA;NR_CPF_CNPJ_DOADOR;NM_DOADOR;DT_RECEITA\\n"
                    "123;91;1250,50;12345678909;Pessoa Exemplo;01/10/2026\\n",
                "despesas_contratadas_candidatos_2026_GO.csv":
                    "SQ_CANDIDATO;SQ_DESPESA;VR_DESPESA_CONTRATADA\n"
                    "123;33;250,50\n",
            })
            data = mod.build(cand, fin)
            self.assertEqual(len(data["candidates"]), 1)
            self.assertEqual(data["candidates"][0]["office"], "deputado federal")
            self.assertEqual(data["candidates"][0]["revenue"], 1250.50)
            self.assertEqual(data["candidates"][0]["expenses"], 250.50)
            self.assertEqual(len(data["transfers"]), 1)
            self.assertNotIn("12345678909", json.dumps(data))

    def test_fail_closed_when_expenses_unmapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            create_zip(tmp/"c.zip", {
                "consulta_cand_2026_BR.csv":
                    "SG_UF;CD_CARGO;SQ_CANDIDATO;NM_CANDIDATO\nGO;7;1;Exemplo\n"
            })
            create_zip(tmp/"f.zip", {
                "receitas_candidatos_2026_GO.csv":
                    "SQ_CANDIDATO;SQ_RECEITA;VR_RECEITA\n1;1;100,00\n"
            })
            with self.assertRaises(ValueError):
                mod.build(tmp/"c.zip", tmp/"f.zip")


if __name__ == "__main__":
    unittest.main()
