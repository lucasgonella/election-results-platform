"""Standard-library synthetic dataset shared by pytest and standalone unittest."""
from collector.src.ftp_delivery import canonical
from collector.src.ftp_recovery import parse, targets


def bundle(root, generation, changed=None):
    root.mkdir()
    rows=[]
    for name,(scope,office) in targets().items():
        source=generation if changed is None or name in changed else 1
        time=f'2026-10-09T12:00:0{source}+00:00'
        candidate={'tse_candidate_seq':100+office,'votes':source,'vote_percentage':100.0,
                   'result_status':'Não eleito','elected':False,'name':'Fixture','ballot_name':'Fixture'}
        payload={'schema_version':1,'environment':'fixture','scope':{'code':scope,'type':'uf','uf':scope.upper()},
                 'office':{'code':office,'name':'Fixture'},'election':{'code':1,'round':1},
                 'snapshot':{'generated_at':time,'captured_at':time,'tse_idg':source,'totalization_final':True},
                 'candidate_count':1,'candidates':[candidate]}
        row={'path':name,'scope':scope,'office':office,'election_code':1,'round':1,
             'tse_idg':source,'captured_at':time,'candidate_count':1}
        rows.append(row)
        if changed is None or name in changed:
            path=root/name;path.parent.mkdir(exist_ok=True);path.write_bytes(canonical(payload))
    meta={'schema_version':1,'environment':'fixture','generated_at':f'2026-10-09T13:00:0{generation}+00:00'}
    (root/'version.json').write_bytes(canonical(meta))
    (root/'manifest.json').write_bytes(canonical(meta|{'result_count':137,'candidate_count':137,'results':rows}))
    (root/'alerts.json').write_bytes(canonical(meta|{'alerts':[]}))


def change(path, function):
    value=parse(path.read_bytes());function(value);path.write_bytes(canonical(value))
