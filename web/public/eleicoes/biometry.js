/* Aggregate identification counts. Fixed to President/2026/round two. */
(function(root) {
    'use strict';
    const BASE = '/biometria-2026/presidente/turno-2/';
    const UFS = 'ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz'.split(' ');
    const ELECTION = {year:2026,round:2,code:6258,pleito:3221,office:1};
    const FIELDS = ['expected','processed','failures','attendance','biometric','biographic','no_registration','unknown'];
    const eqElection = value => value && Object.keys(ELECTION).every(key=>value[key]===ELECTION[key]);
    const validId = value => typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
    const sum = rows => Object.fromEntries(FIELDS.map(key=>[key,rows.reduce((total,row)=>total+row[key],0)]));
    const norm = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');
    const identified = row => row.processed>0 && (row.attendance===0 || row.unknown<row.attendance);
    function validate(value) {
        if(value?.schema!==1 || value.environment!=='oficial' || !eqElection(value.election)
            || !Array.isArray(value.states) || !Array.isArray(value.municipalities)
            || value.states.length!==28 || new Set(value.states.map(row=>row.uf)).size!==28
            || value.states.some(row=>!UFS.includes(row.uf))) throw new Error('biometry_wrong_dataset');
        const ids=new Set();
        for(const row of value.municipalities) {
            const id=row.uf+':'+row.municipality;
            if(!UFS.includes(row.uf)||!/^\d{5}$/.test(row.municipality)||ids.has(id)) throw new Error('biometry_duplicate_municipality');
            ids.add(id);
        }
        for(const row of [value.totals,...value.states,...value.municipalities]) {
            if(!row || FIELDS.some(key=>!Number.isSafeInteger(row[key])||row[key]<0)
                || row.processed>row.expected || row.attendance!==row.biometric+row.biographic+row.no_registration+row.unknown)
                throw new Error('biometry_invalid_balance');
        }
        for(const state of value.states) {
            const total=sum(value.municipalities.filter(row=>row.uf===state.uf));
            if(FIELDS.some(key=>total[key]!==state[key])) throw new Error('biometry_state_mismatch');
        }
        const total=sum(value.states);
        if(FIELDS.some(key=>total[key]!==value.totals[key])
            || typeof value.complete!=='boolean' || value.complete!==(total.expected===total.processed)
            || total.expected!==value.national_reference?.sections
            || !Number.isSafeInteger(value.national_reference?.attendance)
            || total.attendance>value.national_reference.attendance
            || value.complete && total.attendance!==value.national_reference.attendance)
            throw new Error('biometry_national_mismatch');
        return value;
    }
    async function read(fetcher=root.fetch.bind(root), reload=false) {
        const response=await fetcher(BASE+'version.json',{cache:'no-store',redirect:'error'});
        if(response.status===404) return null;
        if(!response.ok) throw new Error('biometry_marker_unavailable');
        const marker=await response.json();
        if(marker.schema!==1||!eqElection(marker.election)||!validId(marker.snapshot_id)
            || marker.sha256!==marker.snapshot_id||!Number.isSafeInteger(marker.size)||marker.size<1||marker.size>16*1024*1024)
            throw new Error('biometry_invalid_marker');
        const file=await fetcher(BASE+'releases/'+marker.snapshot_id+'/panel.json',{cache:reload?'reload':'force-cache',redirect:'error'});
        if(!file.ok) throw new Error('biometry_payload_unavailable');
        const bytes=await file.arrayBuffer();
        const hash=Array.from(new Uint8Array(await root.crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
        if(bytes.byteLength!==marker.size||hash!==marker.sha256) throw new Error('biometry_integrity_error');
        return {marker,data:validate(JSON.parse(new TextDecoder().decode(bytes)))};
    }
    function csv(rows) {
        const quote=value=>{let text=String(value??'');if(/^[=+@-]/.test(text))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';};
        const header=['UF','Localidade','BUs esperados','BUs processados','Comparecimento nos BUs lidos','Biometria reconhecida','Identificação biográfica','Sem cadastro biométrico','Forma não informada'];
        return '\ufeff'+[header,...rows.map(row=>[row.uf.toUpperCase(),row.name,row.expected,row.processed,
            row.processed?row.attendance:'',identified(row)?row.biometric:'',identified(row)?row.biographic:'',
            identified(row)?row.no_registration:'',row.processed?row.unknown:''])].map(row=>row.map(quote).join(';')).join('\r\n');
    }
    const api={validate,read,sum,csv};
    if(typeof module!=='undefined'&&module.exports){module.exports=api;return;}
    root.ElectionBiometry=api;
    const doc=root.document,mount=doc?.getElementById('biometria');if(!mount)return;
    const find=id=>doc.getElementById('bio-'+id),number=value=>new Intl.NumberFormat('pt-BR').format(value);
    const percent=(count,total)=>total?new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(count/total*100)+'%':'—';
    const date=value=>value?new Date(value).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'Ainda não registrada';
    const el=(tag,text,cls)=>{const node=doc.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
    let publication=null,busy=false,page=0,view='states',lastError=false;
    function visibleRows() {
        if(!publication)return [];
        const uf=find('uf').value,query=norm(find('search').value.trim());
        const source=view==='states'?publication.data.states:publication.data.municipalities;
        return source.filter(row=>(!uf||row.uf===uf)&&(!query||norm(row.name+' '+row.uf).includes(query)));
    }
    function render() {
        if(!publication)return;
        const {data}=publication,uf=find('uf').value;
        const total=uf?data.states.find(row=>row.uf===uf):data.totals;
        const available=total.processed>0,known=identified(total),without=total.biographic+total.no_registration;
        const pending=available?'Forma de identificação não informada nos BUs lidos':'Aguardando BUs desta localidade';
        find('scope').textContent=uf?(data.states.find(row=>row.uf===uf).name+' · '+uf.toUpperCase()):'Brasil e exterior';
        find('biometric').textContent=known?number(total.biometric):'—';
        find('biometric-share').textContent=known?percent(total.biometric,total.attendance)+' do comparecimento lido':pending;
        find('without').textContent=known?number(without):'—';
        find('without-share').textContent=known?percent(without,total.attendance)+' do comparecimento lido':pending;
        find('biographic').textContent=known?number(total.biographic):'—';
        find('no-registration').textContent=known?number(total.no_registration):'—';
        find('attendance').textContent=available?number(total.attendance):'—';
        find('coverage').textContent=percent(total.processed,total.expected);
        find('coverage-count').textContent=number(total.processed)+' de '+number(total.expected)+' seções com BU processado';
        find('coverage-progress').max=Math.max(1,total.expected);find('coverage-progress').value=total.processed;
        find('unknown').hidden=!total.unknown;
        find('unknown').textContent=number(total.unknown)+' votantes têm a forma de identificação não informada no BU. Eles estão no comparecimento lido e fora das duas contagens de identificação.';
        find('reference').textContent='Referência oficial nacional: '+number(data.national_reference.attendance)+' votantes · '+number(data.national_reference.sections)+' seções.';
        find('updated').textContent='Última coleta: '+date(data.last_source_success_at)+' · Horário de Brasília';
        if(!lastError) find('status').textContent=data.complete?'Todos os BUs do inventário foram processados.':'Coleta nacional em andamento. Os números de identificação são parciais e correspondem somente aos BUs processados.';
        find('segments').replaceChildren();
        const segments=[['Biometria reconhecida',total.biometric,'bio-segment-biometric'],['Sem uso da biometria',without,'bio-segment-without'],['Forma não informada',total.unknown,'bio-segment-unknown']];
        const legend=find('legend');legend.replaceChildren();
        for(const [label,value,cls] of segments) {
            if(value) {const node=el('span',undefined,cls);node.style.width=(value/total.attendance*100)+'%';node.title=label+': '+number(value);find('segments').append(node);}
            legend.append(el('span',label+' · '+((known||label==='Forma não informada'&&available)?percent(value,total.attendance):'—'),cls+'-label'));
        }
        const rows=visibleRows(),limit=view==='states'?28:25,pages=Math.max(1,Math.ceil(rows.length/limit));page=Math.min(page,pages-1);
        find('body').replaceChildren();
        for(const row of rows.slice(page*limit,(page+1)*limit)) {
            const tr=el('tr'),label=el('th');label.scope='row';
            if(view==='states') {const button=el('button',row.name,'bio-row-button');button.type='button';button.onclick=()=>{find('uf').value=row.uf;page=0;render();};label.append(button);}
            else label.textContent=row.name+' · '+row.uf.toUpperCase();
            tr.append(label);
            const values=[number(row.processed)+' / '+number(row.expected),row.processed?number(row.attendance):'—',
                identified(row)?number(row.biometric):'—',identified(row)?number(row.biographic+row.no_registration):'—',
                identified(row)?percent(row.biometric,row.attendance):'—',row.processed?number(row.unknown):'—'];
            for(const value of values)tr.append(el('td',value));find('body').append(tr);
        }
        if(!rows.length){const tr=el('tr'),td=el('td','Nenhuma localidade encontrada.');td.colSpan=7;tr.append(td);find('body').append(tr);}
        find('page').textContent=number(rows.length)+' localidades · página '+(page+1)+' de '+pages;
        find('previous').disabled=page===0;find('next').disabled=page>=pages-1;
        find('csv').disabled=!rows.length;
        find('states').setAttribute('aria-pressed',String(view==='states'));find('municipalities').setAttribute('aria-pressed',String(view==='municipalities'));
    }
    async function load() {
        if(busy||mount.hidden)return;busy=true;find('refresh').disabled=true;
        try {
            const next=await read(undefined,lastError);
            if(!next){if(publication)throw new Error('biometry_marker_missing');find('status').textContent='Aguardando a primeira publicação da coleta nacional de BUs do segundo turno.';return;}
            if(next.marker.snapshot_id!==publication?.marker.snapshot_id){
                const current=find('uf').value;publication=next;
                find('uf').replaceChildren(el('option','Brasil e exterior'));find('uf').firstChild.value='';
                for(const state of publication.data.states){const option=el('option',state.name);option.value=state.uf;find('uf').append(option);}
                find('uf').value=UFS.includes(current)?current:'';
            }
            lastError=false;render();
        } catch(error) {
            lastError=true;
            find('status').textContent=publication?'Não foi possível verificar uma atualização. Os últimos dados validados continuam visíveis.':'Os dados de biometria ainda não puderam ser validados. Tente atualizar novamente.';
        } finally {busy=false;find('refresh').disabled=false;}
    }
    let linked=false;
    function context(){
        const round=Number(root.ElectionPortal?.getContext()?.round||new URL(root.location.href).searchParams.get('turno')||2);
        mount.hidden=round!==2;if(!mount.hidden&&!publication)load();
        if(!mount.hidden&&!linked&&root.location.hash==='#biometria'){linked=true;root.requestAnimationFrame(()=>mount.scrollIntoView());}
    }
    find('uf').onchange=()=>{page=0;render();};find('search').oninput=()=>{view='municipalities';page=0;render();};
    for(const [id,value] of [['states','states'],['municipalities','municipalities']])find(id).onclick=()=>{view=value;page=0;render();};
    find('previous').onclick=()=>{page=Math.max(0,page-1);render();};find('next').onclick=()=>{page++;render();};
    find('refresh').onclick=load;
    find('csv').onclick=()=>{const blob=new Blob([csv(visibleRows())],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download='biometria-presidente-2-turno-2026.csv';link.click();root.setTimeout(()=>URL.revokeObjectURL(url),1000);};
    doc.addEventListener('election:context',context);doc.addEventListener('visibilitychange',()=>{if(!doc.hidden)load();});
    root.setInterval(()=>{if(!doc.hidden)load();},120000);context();
})(typeof window!=='undefined'?window:globalThis);
