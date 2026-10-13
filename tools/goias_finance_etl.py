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
from collections import defaultdict
try:
    from tools.goias_identity import document, resolve
except ModuleNotFoundError:
    from goias_identity import document, resolve

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
    private_candidates = {}
    campaign_owners = defaultdict(lambda: defaultdict(set))
    for row, _ in read_csv_zip(candidates_zip, lambda n: "consulta_cand_2026" in n):
        if not go_candidate(row):
            continue
        candidate_id = field(row, "SQ_CANDIDATO")
        if not candidate_id:
            raise ValueError("Missing SQ_CANDIDATO")
        facts = private_candidates.setdefault(candidate_id, {"cpfs": set(), "civil_name": field(row, "NM_CANDIDATO")})
        facts["cpfs"].add(field(row, "NR_CPF_CANDIDATO"))
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
    duplicate_rows = 0
    empty_revenue_declarations = 0
    source_rows = defaultdict(int)
    for row, filename in read_csv_zip(finance_zip, lambda n: n.endswith(("receitas_candidatos_2026_go.csv", "despesas_contratadas_candidatos_2026_go.csv"))):
        source_rows[filename] += 1
        low = filename.lower()
        kind = "revenue" if "receita" in low else "expense"
        cid = field(row, "SQ_CANDIDATO")
        if cid not in candidates:
            continue
        own_cpf = document(field(row, "NR_CPF_CANDIDATO"), 11)
        if own_cpf:
            private_candidates[cid]["cpfs"].add(own_cpf)
        campaign_cnpj = document(field(row, "NR_CNPJ_PRESTADOR_CONTA", "NR_CNPJ_PRESTADOR_CONTAS"), 14)
        if campaign_cnpj:
            campaign_owners[campaign_cnpj][cid].add(field(row, "SQ_PRESTADOR_CONTAS") or cid)
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
        # TSE emits zero-valued account declarations without a receipt, donor
        # or date. These prove account availability, not a financial transfer.
        if kind == "revenue" and amount == 0 and all(field(row, column) is None for column in
                ("SQ_RECEITA", "NR_CPF_CNPJ_DOADOR", "NM_DOADOR", "NM_DOADOR_RFB", "DT_RECEITA", "DS_ORIGEM_RECEITA")):
            empty_revenue_declarations += 1
            incomes.setdefault(cid, Decimal(0))
            continue
        if kind == "revenue" and field(row, "SQ_RECEITA") is None:
            raise ValueError("Revenue transaction lacks its official receipt sequence")
        # Each TSE file type represents an accounting stage. Never sum multiple
        # files of the same type without a distinct transaction identifier.
        record_id = field(row, "SQ_RECEITA" if kind == "revenue" else "SQ_DESPESA",
                          "SQ_PRESTADOR_CONTAS", "NR_DOCUMENTO")
        if not record_id:
            raise ValueError(f"Cannot deduplicate {kind} transactions: missing identifier")
        key = (kind, cid, record_id, str(amount))
        if key in seen:
            duplicate_rows += 1
            continue
        seen.add(key)
        (incomes if kind == "revenue" else expenses)[cid] = (
            (incomes if kind == "revenue" else expenses).get(cid, Decimal(0)) + amount
        )
        matched[kind] += 1
        if kind == "revenue":
            # Direct counterparty only. Original donor is not the sender of this accounting row.
            origin = field(row, "NR_CPF_CNPJ_DOADOR")
            origin_name = field(row, "NM_DOADOR", "NM_DOADOR_RFB") or "Doador não informado"
            transfers.append({
                "id": f"{cid}:{record_id}:{len(transfers)}",
                "from_name": origin_name, "to_name": candidates[cid]["name"],
                "amount": float(amount), "date": field(row, "DT_RECEITA"),
                "type": field(row, "DS_ORIGEM_RECEITA", "DS_ESPECIE_RECEITA") or "Receita declarada",
                "source_url": TSE_DATA, "source_record_id": record_id,
                "source_file": filename, "source_row": source_rows[filename] + 1,
                "candidate_id": cid, "donor_document": origin,
                "recipient_campaign_document": campaign_cnpj,
                "donor_candidate_id": field(row, "SQ_CANDIDATO_DOADOR"),
            })
    if matched["revenue"] == 0 or matched["expense"] == 0:
        raise ValueError("Finance CSV columns not mapped or GO transactions missing; refusing incomplete export")
    for cid, entry in candidates.items():
        entry["revenue"] = float(incomes[cid]) if cid in incomes else 0
        entry["expenses"] = float(expenses[cid]) if cid in expenses else 0
    entities, transfers, audit = resolve(candidates, private_candidates, transfers, campaign_owners)
    audit["empty_revenue_declarations_excluded_from_graph"] = empty_revenue_declarations
    audit["existing_accounting_duplicates_skipped"] = duplicate_rows
    audit["revenue_records_preserved"] = matched["revenue"]
    audit["expense_records_preserved"] = matched["expense"]
    audit["revenue_total"] = str(sum(incomes.values(), Decimal(0)))
    audit["expense_total"] = str(sum(expenses.values(), Decimal(0)))
    import hashlib
    return {
        "identity_schema": 1, "entities": entities, "identity_audit": audit,
        "scope": "GO", "year": 2026,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": sorted(candidates.values(), key=lambda x: (x["office"], x["name"])),
        "transfers": transfers,
        "source": {"candidates": TSE_CAND, "finance": TSE_FIN,
                   "candidates_sha256": hashlib.sha256(candidates_zip.read_bytes()).hexdigest(),
                   "finance_sha256": hashlib.sha256(finance_zip.read_bytes()).hexdigest()},
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
