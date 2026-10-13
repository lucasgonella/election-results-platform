"""Entirely invented official-format fixtures. Never used for collection/deploy."""
from pathlib import Path
from collector.src.election_release import canonical,digest
from collector.src.municipal_collection import UF_CODES,result

ELECTION={'code':9001,'round':1,'year':2026,'cycle':'ele2026','pleito':'fixture'}


def ea20(code='00001',round_number=1,partial=False,tie=False,waiting=False):
    votes=[50,50] if tie else [80,20]
    if waiting:votes=[0,0]
    return {'f':'o','ele':'9001','t':str(round_number),'idg':'1','tpabr':'mu','cdabr':code,'dv':'s','tf':'n' if partial or waiting else 's',
            'dg':'04/10/2026','hg':'20:00:00','dt':'04/10/2026','ht':'19:59:00','and':'p' if partial else 'n' if waiting else 'f',
            's':{'ts':'10','st':'0' if waiting else '6' if partial else '10','pstn':'0' if waiting else '60' if partial else '100'},
            'e':{'te':'130','est':'0' if waiting else '120','c':'0' if waiting else '110','a':'0' if waiting else '10'},
            'v':{'tv':'0' if waiting else '110','vvc':str(sum(votes)),'vv':str(sum(votes)),'vb':'0' if waiting else '5','tvn':'0' if waiting else '5'},
            'carg':[{'cd':'1','nmn':'Presidente','nv':'1','agr':[{'nm':'Coligação sintética','tp':'i','par':[{'n':'10','sg':'EX','nm':'Partido sintético','cand':[
                {'sqcand':str(1001+i),'n':str(10+i*10),'nm':'CANDIDATO SINTÉTICO '+str(i),'nmu':'EXEMPLO '+str(i),'dvt':'Válido','vap':str(v),'pvapn':str(v),'e':'n','st':'Não eleito','seq':str(i)} for i,v in enumerate(votes)]}]}]}]}


def make_dataset(round_number=1):
    selected={**ELECTION,'round':round_number};rows=[];coverage={};states={}
    for i,(uf,ibge_prefix) in enumerate(UF_CODES.items()):
        code=f'{i+1:05d}'
        m={'uf':uf,'tse_code':code,'ibge_code':ibge_prefix+'00001','name':'GOIÂNIA SINTÉTICA' if uf=='go' else 'CIDADE SINTÉTICA '+uf.upper()}
        raw=ea20(code,round_number)
        info={'url':f'https://resultados.tse.jus.br/oficial/ele2026/9001/dados/{uf}/{uf}{code}-c0001-e009001-u.json','captured_at':'2026-10-04T23:00:00+00:00','sha256':digest(canonical(raw))}
        rows.append(result(raw,m,selected,info,{'1001':{},'1002':{}}))
        state={**raw,'tpabr':'uf','cdabr':uf}
        states[uf]=result(state,None,selected,{**info,'scope':uf})
        coverage[uf]={'expected':1,'processed':1,'available':1,'waiting':0,'inconclusive':0,'pending':0,'failed':0,'coverage_percentage':100,'reconciliation':'equal','all_final':True}
    return {'schema':1,'environment':'oficial','election':selected,'catalog':{'1001':{'id':'1001','number':10,'name':'EXEMPLO 0','party':'EX'},'1002':{'id':'1002','number':20,'name':'EXEMPLO 1','party':'EX'}},
            'municipalities':rows,'coverage':coverage,'states':states,'sources':{},'exterior_included':False}


def make_geometry(dataset,directory):
    root=Path(directory);root.mkdir();files={}
    for i,municipality in enumerate(dataset['municipalities']):
        uf=municipality['uf'];x=-60+(i%5)*2;y=-20+(i//5)*2
        polygon={'type':'Polygon','coordinates':[[[x,y],[x+1,y],[x+1,y+1],[x,y+1],[x,y]]]}
        for level in ['national','detail']:
            value={'schema':1,'year':2025,'uf':uf,'level':level,'type':'FeatureCollection','features':[{'type':'Feature','properties':{'uf':uf,'name':municipality['name'],'ibge_code':municipality['ibge_code']},'geometry':polygon}]}
            raw=canonical(value);name=uf+'-'+level+'.json';(root/name).write_bytes(raw);files[name]={'size':len(raw),'sha256':digest(raw),'municipalities':1}
    (root/'geometry-report.json').write_bytes(canonical({'year':2025,'source_url':'https://geoftp.ibge.gov.br/fixture','source_sha256':'0'*64,'municipalities':len(dataset['municipalities']),'files':files}))

