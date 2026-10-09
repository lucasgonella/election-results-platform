#!/usr/bin/env python3
"""Read-only diagnostic for possible repeated TSE 2026 campaign accounting entries."""
import csv
from collections import Counter, defaultdict
from pathlib import Path
import io
import json
import zipfile

DATA = Path("web/public/eleicoes/goias/raio-x/data/go-2026.json")
ZIP = Path("/tmp/tse-go/finance.zip")


def scan():
    data=json.loads(DATA.read_text())
    print("PUBLIC DATA", "candidates",len(data["candidates"]),"edges",len(data["transfers"]))
    ids=[c["id"] for c in data["candidates"]]
    print("DUPLICATE CANDIDATE IDS",len(ids)-len(set(ids)))
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
                    if cid not in ids: continue
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
