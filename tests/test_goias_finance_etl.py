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
