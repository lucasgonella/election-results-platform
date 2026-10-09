#!/usr/bin/env python3
"""Strict ETL: TSE 2026 candidacies and declared campaign finance for Goiás.

Only releases validated real records. It fails closed if CSV layout changes.
Receipts and expenses are independently deduplicated using TSE document/row identity.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import io
import json
from pathlib import Path
import re
import zipfile

TSE_CAND = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip"
TSE_FIN = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip"
TSE_DATA = "https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026"
CARGOS = {"6": "deputado federal", "7": "deputado estadual"}


def field(row, *names):
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() not in ("", "#NULO", "#NE", "-1"):
            return str(value).strip()
    return None


def money(raw):
    if raw is None:
        return None
    try:
        amount = Decimal(str(raw).replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid monetary number {raw!r}") from exc
    return amount


def read_csv_zip(path, predicate):
    with zipfile.ZipFile(path) as archive:
        matches = [n for n in archive.namelist()
                   if n.lower().endswith(".csv") and predicate(n.lower())]
        if not matches:
            raise ValueError(f"No matching CSV in {path}; names: {archive.namelist()[:25]}")
        for name in matches:
            with archive.open(name) as stream:
                reader = csv.DictReader(io.TextIOWrapper(stream, encoding="latin-1", newline=""), delimiter=";")
                if not reader.fieldnames or len(reader.fieldnames) < 3:
                    raise ValueError(f"Unrecognized CSV {name}")
                for row in reader:
                    yield row, name


def go_candidate(row):
    return field(row, "SG_UF", "SG_UF_CANDIDATO", "SG_UF_UE") == "GO" and field(row, "CD_CARGO") in CARGOS


def build(candidates_zip: Path, finance_zip: Path):
    candidates = {}
    for row, _ in read_csv_zip(candidates_zip, lambda n: "consulta_cand_2026" in n):
        if not go_candidate(row):
            continue
        candidate_id = field(row, "SQ_CANDIDATO")
        if not candidate_id:
            raise ValueError("Missing SQ_CANDIDATO")
        candidates[candidate_id] = {
            "id": candidate_id,
            "name": field(row, "NM_URNA_CANDIDATO", "NM_CANDIDATO") or "Nome não informado",
            "party": field(row, "SG_PARTIDO"),
            "number": field(row, "NR_CANDIDATO"),
            "office": CARGOS[field(row, "CD_CARGO")],
            "status": field(row, "DS_SIT_TOT_TURNO", "DS_SITUACAO_CANDIDATURA", "DS_SITUACAO_CANDIDATO_URNA") or "Não informado",
            "votes": None,
            "revenue": None,
            "expenses": None,
        }
    if not candidates:
        raise ValueError("No Goiás federal/state deputy candidates found")

    incomes = {}
    expenses = {}
    transfers = []
    seen = set()
    matched = {"revenue": 0, "expense": 0}
    for row, filename in read_csv_zip(finance_zip, lambda n: n.endswith(("receitas_candidatos_2026_go.csv", "despesas_contratadas_candidatos_2026_go.csv"))):
        low = filename.lower()
        kind = "revenue" if "receita" in low else "expense"
        cid = field(row, "SQ_CANDIDATO")
        if cid not in candidates:
            continue
        # Check the columns before trusting totals; do not interpret expenses as income.
        value_column = "VR_RECEITA" if kind == "revenue" else "VR_DESPESA_CONTRATADA"
        raw_amount = field(row, value_column)
        if raw_amount is None and kind == "expense":
            raw_amount = field(row, "VR_DESPESA_PAGA")
        if raw_amount is None:
            continue
        amount = money(raw_amount)
        if amount is None or amount < 0:
            continue
        # Each TSE file type represents an accounting stage. Never sum multiple
        # files of the same type without a distinct transaction identifier.
        record_id = field(row, "SQ_RECEITA" if kind == "revenue" else "SQ_DESPESA",
                          "SQ_PRESTADOR_CONTAS", "NR_DOCUMENTO")
        if not record_id:
            raise ValueError(f"Cannot deduplicate {kind} transactions: missing identifier")
        key = (kind, cid, record_id, str(amount))
        if key in seen:
            continue
        seen.add(key)
        (incomes if kind == "revenue" else expenses)[cid] = (
            (incomes if kind == "revenue" else expenses).get(cid, Decimal(0)) + amount
        )
        matched[kind] += 1
        if kind == "revenue":
            origin = field(row, "NR_CPF_CNPJ_DOADOR_ORIGINARIO", "NR_CPF_CNPJ_DOADOR")
            origin_name = field(row, "NM_DOADOR_ORIGINARIO", "NM_DOADOR")
            if origin_name and origin:
                # Do not publish tax identifiers; public graph nodes are opaque.
                import hashlib
                origin_id = "donor:" + hashlib.sha256(origin.encode()).hexdigest()[:20]
                transfers.append({
                    "id": f"{cid}:{record_id}:{len(transfers)}",
                    "from_id": origin_id, "from_name": origin_name,
                    "to_id": cid, "to_name": candidates[cid]["name"],
                    "amount": float(amount),
                    "date": field(row, "DT_RECEITA"),
                    "type": field(row, "DS_ORIGEM_RECEITA", "DS_ESPECIE_RECEITA") or "Receita declarada",
                    "source_url": TSE_DATA,
                })
    if matched["revenue"] == 0 or matched["expense"] == 0:
        raise ValueError("Finance CSV columns not mapped or GO transactions missing; refusing incomplete export")
    for cid, entry in candidates.items():
        entry["revenue"] = float(incomes[cid]) if cid in incomes else 0
        entry["expenses"] = float(expenses[cid]) if cid in expenses else 0
    return {
        "scope": "GO", "year": 2026,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": sorted(candidates.values(), key=lambda x: (x["office"], x["name"])),
        "transfers": transfers,
        "source": {"candidates": TSE_CAND, "finance": TSE_FIN},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--finance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = build(args.candidates, args.finance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".new")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(args.output)
    print(f"Exported GO candidates={len(data['candidates'])} receipts={len(data['transfers'])}")


if __name__ == "__main__":
    main()
