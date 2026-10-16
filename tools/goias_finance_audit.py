#!/usr/bin/env python3
"""Read-only diagnostic for possible repeated TSE 2026 campaign accounting entries."""
import csv
from collections import Counter, defaultdict
from pathlib import Path
import io
import json
import math
import zipfile

DATA = Path("web/public/eleicoes/goias/raio-x/data/go-2026.json")
ZIP = Path("/tmp/tse-go/finance.zip")


def financial_summary(data):
    """Validate additive value coverage, returning only aggregate diagnostics.

    Legacy numbers, including zero, retain their published meaning. Coverage is
    mandatory only when the exporter explicitly opts into financial_schema 1.
    No row names or personal documents are returned by this diagnostic.
    """
    schema = data.get("financial_schema")
    if schema is not None and (type(schema) is not int or schema != 1):
        raise ValueError("Unsupported financial coverage schema")
    summary = {}
    for field in ("revenue", "expenses"):
        totals = {"known": 0, "partial": 0, "missing": 0, "zero": 0, "subtotal": None}
        for candidate in data["candidates"]:
            value = candidate.get(field)
            numeric = type(value) in (int, float) and math.isfinite(value) and value >= 0
            if value is not None and not numeric:
                raise ValueError("Invalid financial value")
            coverage = candidate.get("financial_coverage")
            if schema == 1 and not isinstance(coverage, dict):
                raise ValueError("Missing financial coverage")
            status = "known" if numeric else "missing"
            if coverage is not None:
                metric = coverage.get(field) if isinstance(coverage, dict) else None
                if not isinstance(metric, dict):
                    raise ValueError("Missing financial metric coverage")
                known, missing = metric.get("known_records"), metric.get("missing_records")
                declarations = metric.get("zero_declarations")
                if (type(known) is not int or known < 0 or type(missing) is not int or missing < 0
                        or not isinstance(declarations, list)):
                    raise ValueError("Invalid financial coverage counts")
                for declaration in declarations:
                    if (field != "revenue" or not isinstance(declaration, dict)
                            or not isinstance(declaration.get("source_file"), str)
                            or not declaration["source_file"].lower().endswith("receitas_candidatos_2026_go.csv")
                            or type(declaration.get("source_row")) is not int or declaration["source_row"] < 2):
                        raise ValueError("Invalid explicit zero evidence")
                supported = known > 0 or bool(declarations)
                status = "missing" if not supported else "partial" if missing else "known"
                subtotal = metric.get("known_subtotal")
                subtotal_numeric = type(subtotal) in (int, float) and math.isfinite(subtotal) and subtotal >= 0
                if (metric.get("status") != status or subtotal_numeric != supported
                        or (not supported and subtotal is not None)
                        or (status == "known" and (not numeric or value != subtotal))
                        or (status != "known" and value is not None)
                        or (declarations and not known and subtotal != 0)):
                    raise ValueError("Inconsistent financial coverage")
                value, numeric = subtotal, subtotal_numeric
            totals[status] += 1
            if numeric:
                totals["subtotal"] = (totals["subtotal"] or 0) + value
                totals["zero"] += value == 0 and status == "known"
        summary[field] = totals
    for row in data.get("transfers", []):
        value = row.get("amount")
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError("Invalid transfer value")
    return summary


def scan():
    data=json.loads(DATA.read_text())
    print("PUBLIC DATA", "candidates",len(data["candidates"]),"edges",len(data["transfers"]))
    print("FINANCIAL COVERAGE", json.dumps(financial_summary(data), sort_keys=True))
    ids=[c["id"] for c in data["candidates"]]
    print("DUPLICATE CANDIDATE IDS",len(ids)-len(set(ids)))
    wanted=set(ids)
    edges=data["transfers"]
    edge_ids=[x["id"] for x in edges]
    print("DUPLICATE EDGE IDS",len(edge_ids)-len(set(edge_ids)))
    identical=Counter((x["to_id"],x["from_id"],str(x["amount"]),str(x["date"]),str(x["type"])) for x in edges)
    repeated=[(k,v) for k,v in identical.items() if v>1]
    print("POSSIBLY REPEATED EDGES",len(repeated),"EXTRA ROWS",sum(v-1 for _,v in repeated))
    print("EXAMPLES (IDs and amounts, no donor identities)")
    for k,v in sorted(repeated,key=lambda x:-x[1])[:12]:
        print("repeats",v,"recipient",k[0],"amount",k[2],"date",k[3])
    paths=Counter()
    transaction_keys=defaultdict(set)
    row_fingerprints=Counter()
    with zipfile.ZipFile(ZIP) as z:
        for name in z.namelist():
            low=name.lower()
            if not low.endswith(".csv") or not ("receitas_candidatos_" in low or "despesas_contratadas_candidatos_" in low):
                continue
            with z.open(name) as f:
                reader=csv.DictReader(io.TextIOWrapper(f,encoding="latin-1",newline=""),delimiter=";")
                for row in reader:
                    cid=row.get("SQ_CANDIDATO","").strip()
                    if cid not in wanted: continue
                    kind="receita" if "receitas_candidatos_" in low else "despesa"
                    paths[(name,kind)]+=1
                    rid=(row.get("SQ_RECEITA") if kind=="receita" else row.get("SQ_DESPESA")) or ""
                    value=(row.get("VR_RECEITA") if kind=="receita" else row.get("VR_DESPESA_CONTRATADA")) or ""
                    transaction_keys[(kind,cid,rid,value)].add(name)
                    import hashlib
                    digest=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                    row_fingerprints[(kind,cid,digest)]+=1
    print("FILES MATCHED",paths)
    print("TRANSACTIONS PRESENT IN MULTIPLE CSV FILES",sum(len(f)>1 for f in transaction_keys.values()))
    print("EXACT IDENTICAL ROWS REPEATED",sum(x-1 for x in row_fingerprints.values() if x>1))
    blank=sum(1 for (kind,cid,rid,value) in transaction_keys if not rid)
    print("RECORDS WITHOUT TRANSACTION ID",blank)
    if repeated or blank:
        print("AUDIT WARNING: investigate legitimate installments vs repeated source records before changing published totals")


if __name__=="__main__":
    scan()
