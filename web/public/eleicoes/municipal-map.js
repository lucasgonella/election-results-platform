/* Official municipality releases. A rendered shape is never a result source. */
(function(root){
    'use strict';
    const BASE='/municipal-2026/', UFS='ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to'.split(' ');
    const normalize=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR').replace(/\s+/g,' ').trim();
    const searchRows=(rows,query)=>{const q=normalize(query),score=r=>normalize(r.name)===q?0:normalize(r.name).startsWith(q)?1:2;return rows.filter(r=>normalize(r.name+' '+r.uf).includes(q)).sort((a,b)=>score(a)-score(b)||a.name.localeCompare(b.name,'pt-BR')||a.uf.localeCompare(b.uf));};
    const canonical=v=>JSON.stringify(v,(key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(k=>[k,value[k]])):value);
    const hash=async bytes=>Array.from(new Uint8Array(await root.crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
    const validId=id=>typeof id==='string'&&/^[a-f0-9]{64}$/.test(id);
    const validPath=p=>typeof p==='string'&&/^(?:turnos\/[12]\/(?:version\.json|releases\/[a-f0-9]{64}\/(?:manifest|catalog|overview|coverage|[a-z]{2}\/president)\.json)|geography\/[a-f0-9]{64}\/[a-z]{2}-(?:national|detail)\.json)$/.test(p);
    class Waiting extends Error{}
    class Reader {
        constructor(fetcher=root.fetch.bind(root)){this.fetch=fetcher;this.cache=new Map();}
        async json(path,entry,signal){
            if(!validPath(path))throw new Error('municipal_unsafe_path');
            const key=path+'|'+(entry?.sha256||'');
            if(entry&&this.cache.has(key))return this.cache.get(key);
            const request=(async()=>{
                const response=await this.fetch(BASE+path,{cache:entry?'force-cache':'no-store',redirect:'error',signal});
                if(response.status===404&&!entry)throw new Waiting('Aguardando dados municipais');
                if(!response.ok)throw new Error('municipal_http_error');
                const bytes=await response.arrayBuffer();
                if(bytes.byteLength>16*1024*1024||entry&&(bytes.byteLength!==entry.size||await hash(bytes)!==entry.sha256))throw new Error('municipal_integrity_error');
                return JSON.parse(new TextDecoder().decode(bytes));
            })();
            if(entry){if(this.cache.size>=64)this.cache.delete(this.cache.keys().next().value);this.cache.set(key,request);request.catch(()=>this.cache.delete(key));}
            return request;
        }
        async pin(round,signal){
            if(![1,2].includes(round))throw new Error('municipal_invalid_round');
            const marker=await this.json(`turnos/${round}/version.json`,null,signal);
            if(marker.schema!==1||marker.environment!=='oficial'||marker.year!==2026||marker.round!==round||!marker.coverage_complete||!validId(marker.release_id))throw new Error('municipal_invalid_marker');
            const prefix=`turnos/${round}/releases/${marker.release_id}/`;
            const manifest=await this.json(prefix+'manifest.json',{sha256:marker.manifest_sha256,size:marker.manifest_size},signal);
            if(manifest.schema!==1||manifest.environment!=='oficial'||manifest.release_id!==marker.release_id||manifest.election.round!==round||manifest.election.year!==2026||manifest.election.code!==marker.election_code||!manifest.coverage_complete||manifest.ufs.length!==27||new Set(manifest.ufs).size!==27||manifest.ufs.some(uf=>!UFS.includes(uf))||await hash(new TextEncoder().encode(canonical(manifest.seed)))!==marker.release_id)throw new Error('municipal_invalid_manifest');
            const after=await this.json(`turnos/${round}/version.json`,null,signal);
            if(canonical(after)!==canonical(marker))throw new Error('municipal_activation_changed');
            return {marker,manifest,prefix,round};
        }
        async data(context,name,signal){
            const entry=context.manifest.files[name];
            if(!entry)throw new Error('municipal_missing_partition');
            const value=await this.json(context.prefix+name,entry,signal);
            if(value.release_id!==context.marker.release_id||canonical(value.election)!==canonical(context.manifest.election))throw new Error('municipal_mixed_release');
            return value;
        }
        async geometry(context,uf,level,signal){
            const entry=context.manifest.geometry[uf+'-'+level];
            if(!entry||entry.path!==`geography/${context.manifest.geometry_id}/${uf}-${level}.json`)throw new Error('municipal_invalid_geometry_path');
            const value=await this.json(entry.path,entry,signal);
            if(value.uf!==uf||value.level!==level||value.type!=='FeatureCollection'||!Array.isArray(value.features))throw new Error('municipal_invalid_geometry');
            return value;
        }
    }
    function zoom(camera,point,factor){const scale=Math.min(40,Math.max(.8,camera.scale*factor)),ratio=scale/camera.scale;return {scale,x:point.x-(point.x-camera.x)*ratio,y:point.y-(point.y-camera.y)*ratio};}
    // Mercator for display only. Values always come from the exact IBGE join.
    const mercator=lat=>Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));
    function project(lon,lat){return [(lon+74)*18.65,40+(mercator(6)-mercator(lat))*180/Math.PI*18.65];}
    const api={Reader,Waiting,zoom,project,normalize,searchRows,validPath};
    if(typeof module!=='undefined'&&module.exports){module.exports=api;return;}
    root.MunicipalMap=api;if(!root.document)return;
    const doc=root.document, el=(tag,cls,text)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
    const num=v=>v==null?'Não informado':new Intl.NumberFormat('pt-BR').format(v),pct=v=>v==null?'Não informado':new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(v)+'%',date=v=>v?new Date(v).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'Não informada';
    const status=r=>({final:'Totalização final TSE',partial:'Apuração parcial',waiting:'Aguardando apuração',tie:r?.consolidation==='final'?'Empate · totalização final TSE':'Empate · apuração parcial',inconclusive:'Liderança inconclusiva'}[r?.status]||'Dados indisponíveis');
    class View {
        constructor(parent){
            this.parent=parent;this.reader=new Reader();this.round=0;this.sequence=0;this.camera={scale:1,x:0,y:0};this.paths=new Map();this.details=new Map();this.geometryLoaded=new Set();this.active=false;this.page=0;this.query='';this.mode=['leader','share','margin'].includes(parent.mode)?parent.mode:'leader';this.candidate=parent.candidate||'';
            const url=new URL(root.location.href);this.uf=UFS.includes(url.searchParams.get('muf'))?url.searchParams.get('muf'):'';this.selected=/^\d{7}$/.test(url.searchParams.get('municipio')||'')?url.searchParams.get('municipio'):'';
            this.build();this.bind();
            this.setContext(parent.portal.getContext());
            doc.addEventListener('election:context',event=>this.setContext(event.detail||parent.portal.getContext()));
            if(url.searchParams.get('nivel')==='municipios')this.activate(true);
            root.addEventListener('popstate',()=>{const u=new URL(root.location.href);this.uf=UFS.includes(u.searchParams.get('muf'))?u.searchParams.get('muf'):'';this.selected=u.searchParams.get('municipio')||'';this.activate(u.searchParams.get('nivel')==='municipios',false);this.render();});
            // Pin each new version as a whole; never replace one UF in place.
            this.poll=root.setInterval(async()=>{if(!this.active||this.loading)return;if(!this.context){if(this.waiting)this.load();return;}try{const marker=await this.reader.json(`turnos/${this.round}/version.json`);if(marker.release_id!==this.context.marker.release_id)this.load();}catch(_){/* retain the verified pinned release */}},60000);
        }
        build(){
            const buttons=this.parent.mount.querySelectorAll('.emap-level button');this.stateButton=buttons[0];this.municipalButton=buttons[1];this.municipalButton.disabled=false;this.municipalButton.textContent='Municípios';
            this.mount=el('div','mmap');this.mount.id='municipal-map-root';this.mount.hidden=true;
            this.parent.mount.querySelector('.emap-heading').after(this.mount);
            this.mount.innerHTML=`<details class="emap-filters" open><summary class="emap-filter-toggle">Filtros municipais <span>Presidência · dados próprios</span></summary><div class="emap-toolbar"><label class="emap-search"><span>Buscar município</span><input id="mmap-search" type="search" maxlength="120" autocomplete="off" placeholder="Nome do município" role="combobox" aria-expanded="false" aria-controls="mmap-search-results" aria-autocomplete="list"><div id="mmap-search-results" class="mmap-search-results" role="listbox" aria-label="Municípios encontrados"></div></label><label><span>UF</span><select id="mmap-uf"><option value="">Todo o Brasil</option></select></label><label><span>Leitura do mapa</span><select id="mmap-mode"><option value="leader">Mais votado no município</option><option value="share">Percentual do candidato</option><option value="margin">Diferença entre os líderes</option></select></label><label><span>Candidato</span><select id="mmap-candidate"><option value="">Todos os candidatos</option></select></label><div class="emap-view-switch"><button id="mmap-map-view" type="button" aria-pressed="true">Mapa</button><button id="mmap-table-view" type="button" aria-pressed="false">Tabela</button></div></div></details><div class="emap-status" id="mmap-status" role="status" aria-live="polite">Consultando a publicação municipal…</div><div class="emap-workspace"><div class="emap-visual"><div class="emap-canvas mmap-canvas-wrap" id="mmap-visual"><div class="emap-map-caption"><span id="mmap-caption">BRASIL · MUNICÍPIOS</span><span id="mmap-round-label"></span></div><canvas id="mmap-canvas" width="820" height="740" tabindex="0" role="group" aria-label="Mapa navegável de municípios brasileiros" aria-describedby="mmap-help"></canvas><div class="emap-zoom"><button type="button" id="mmap-zoom-in" aria-label="Ampliar mapa municipal">+</button><button type="button" id="mmap-zoom-out" aria-label="Reduzir mapa municipal">−</button><button type="button" id="mmap-reset">Voltar ao Brasil</button></div><div id="mmap-tooltip" class="emap-tooltip" role="tooltip" hidden></div></div><div id="mmap-table" class="emap-table-wrap" hidden></div><div id="mmap-legend" class="emap-legend" aria-label="Legenda municipal"></div><p class="emap-method" id="mmap-help">Ctrl + rolagem aproxima o ponto sob o cursor. Arraste para mover; dois dedos aproximam em touch. No mapa, setas percorrem municípios; Enter abre os detalhes. A busca e a tabela oferecem navegação por teclado.</p><p class="emap-method" id="mmap-method"></p></div><aside class="emap-detail" id="mmap-detail" aria-label="Detalhes do município selecionado"></aside></div><div class="emap-footnotes"><p>Resultados municipais próprios do TSE. Limites territoriais: IBGE, malha 2025 simplificada. Brasília e Fernando de Noronha seguem o inventário territorial oficial; localidades do exterior não integram este mapa. Quantidade de municípios liderados não é quantidade de votos nem declaração de eleição.</p><p id="mmap-release"></p></div>`;
            this.find=id=>this.mount.querySelector('#'+id);this.canvas=this.find('mmap-canvas');this.ctx=this.canvas.getContext('2d');
            for(const uf of UFS){const option=el('option','',this.parent.states.find(s=>s.scope===uf)?.name||uf.toUpperCase());option.value=uf;this.find('mmap-uf').append(option);}
            this.find('mmap-uf').value=this.uf;this.find('mmap-mode').value=this.mode;
        }
        activate(value,update=true){
            this.active=value;this.mount.hidden=!value;this.stateButton.setAttribute('aria-pressed',String(!value));this.municipalButton.setAttribute('aria-pressed',String(value));
            for(const selector of ['#emap-filters','#emap-status','.emap-workspace','.emap-footnotes']){const node=this.parent.mount.querySelector('.emap-section > '+selector);if(node)node.hidden=value;}
            this.parent.find('emap-title').textContent=value?'O voto em cada município.':'O voto em cada estado.';
            if(update)this.url();if(value){if(!this.context&&!this.loading)this.load();this.render();}
        }
        setContext(value){
            const round=Number(value?.round)||1;
            if(Number(value?.office)===1&&value.candidate!=null){this.candidate=String(value.candidate);this.find('mmap-candidate').value=this.candidate;}
            if(this.round!==round){this.round=round;this.controller?.abort();this.sequence++;this.context=null;this.rows=[];this.byId=new Map();this.fullById=new Map();this.catalog={};this.baseColors=new Map();this.coverage=null;this.paths.clear();this.details.clear();this.geometryLoaded.clear();if(this.active)this.load();else this.loading=false;}
            else if(this.active&&!this.loading&&this.lastScope!==value?.scope&&(UFS.includes(value?.scope)||value?.scope==='br')&&this.uf!==(value.scope==='br'?'':value.scope))this.setUF(value.scope==='br'?'':value.scope,false);
            this.lastScope=value?.scope;
        }
        async load(){
            const sequence=++this.sequence;this.controller?.abort();this.controller=new AbortController();const signal=this.controller.signal;
            this.find('mmap-candidate').replaceChildren(el('option','','Todos os candidatos'));this.find('mmap-candidate').firstChild.value='';this.find('mmap-release').textContent='Sem publicação municipal validada neste turno.';this.find('mmap-tooltip').hidden=true;this.hovered=null;this.find('mmap-search-results').replaceChildren();this.find('mmap-search').setAttribute('aria-expanded','false');
            this.loading=true;this.error=null;this.waiting=false;this.context=null;this.rows=[];this.byId=new Map();this.fullById=new Map();this.catalog={};this.baseColors=new Map();this.coverage=null;this.paths.clear();this.details.clear();this.geometryLoaded.clear();this.render();
            try{
                const context=await this.reader.pin(this.round,signal);
                const [overview,catalog,coverage]=await Promise.all([this.reader.data(context,'overview.json',signal),this.reader.data(context,'catalog.json',signal),this.reader.data(context,'coverage.json',signal)]);
                if(sequence!==this.sequence)return;
                const ids=new Set();for(const row of overview.municipalities){if(!/^\d{7}$/.test(row.ibge_code)||!UFS.includes(row.uf)||ids.has(row.ibge_code)||!['final','partial','tie','waiting','inconclusive'].includes(row.status))throw new Error('municipal_invalid_overview');ids.add(row.ibge_code);}
                if(ids.size!==context.marker.municipalities||coverage.municipalities!==ids.size)throw new Error('municipal_coverage_mismatch');
                this.context=context;this.rows=overview.municipalities;this.catalog=catalog.candidates;this.baseColors=new Map(Object.values(this.catalog).map(c=>[c.id,root.ElectoralMap.candidateColor(c.number)]));this.coverage=coverage;this.byId=new Map(this.rows.map(r=>[r.ibge_code,r]));
                if(!this.byId.has(this.selected))this.selected='';
                if(this.selected){this.uf=this.byId.get(this.selected).uf;this.find('mmap-uf').value=this.uf;}
                const candidate=this.find('mmap-candidate');candidate.replaceChildren(el('option','','Todos os candidatos'));candidate.firstChild.value='';
                for(const c of Object.values(this.catalog)){const o=el('option','',`${c.name} · ${c.party}`);o.value=String(c.number);candidate.append(o);}
                if(!Object.values(this.catalog).some(c=>String(c.number)===this.candidate))this.candidate='';candidate.value=this.candidate;
                this.find('mmap-release').textContent=`Publicação municipal: ${context.marker.release_id.slice(0,12)} · eleição ${context.marker.election_code} · ${this.round}º turno.`;
                const pending=this.uf?[this.uf]:UFS.slice();let done=0;
                const worker=async()=>{while(pending.length){const uf=pending.shift();await this.loadGeometry(uf,'national',sequence);if(sequence!==this.sequence)return;this.find('mmap-status').textContent=`Carregando territórios: ${++done} de ${this.uf?1:27} UFs · ${num(this.rows.length)} municípios no inventário.`;}};
                await Promise.all(Array.from({length:Math.min(4,pending.length)},worker));
                if(sequence!==this.sequence)return;
                this.error=null;
                if(this.uf){await this.loadGeometry(this.uf,'detail',sequence);await this.stateData(this.uf);}
                if(sequence!==this.sequence)return;this.fit();this.loading=false;
                if(this.selected)await this.select(this.selected,false);else this.render();
                if(this.uf)await this.parent.portal.selectScope(this.uf,1);
            }catch(error){if(sequence!==this.sequence||error.name==='AbortError')return;this.loading=false;this.waiting=error instanceof Waiting;this.error=error;this.context=null;this.rows=[];this.paths.clear();this.render();}
        }
        async loadGeometry(uf,level,sequence=this.sequence){
            const key=uf+'-'+level;if(this.geometryLoaded.has(key)||!this.context)return;
            const context=this.context, data=await this.reader.geometry(context,uf,level,this.controller.signal);
            if(sequence!==this.sequence||context!==this.context)return;
            const ids=new Set(data.features.map(f=>f.properties.ibge_code)),expected=new Set(this.rows.filter(r=>r.uf===uf).map(r=>r.ibge_code));
            if(ids.size!==data.features.length||ids.size!==expected.size||[...ids].some(id=>!expected.has(id)))throw new Error('municipal_geometry_join_mismatch');
            let count=0;
            for(const feature of data.features){
                const geometry=feature.geometry;
                if(!['Polygon','MultiPolygon'].includes(geometry.type))throw new Error('municipal_invalid_polygon');
                const path=new Path2D(),bounds=[Infinity,Infinity,-Infinity,-Infinity];
                const polygons=geometry.type==='Polygon'?[geometry.coordinates]:geometry.coordinates;
                for(const polygon of polygons)for(const ring of polygon){
                    ring.forEach((coordinate,i)=>{if(coordinate.length!==2||!coordinate.every(Number.isFinite)||Math.abs(coordinate[0])>180||Math.abs(coordinate[1])>=90)throw new Error('municipal_invalid_coordinate');const [x,y]=project(...coordinate);bounds[0]=Math.min(bounds[0],x);bounds[1]=Math.min(bounds[1],y);bounds[2]=Math.max(bounds[2],x);bounds[3]=Math.max(bounds[3],y);if(i===0)path.moveTo(x,y);else path.lineTo(x,y);});path.closePath();
                }
                this.paths.set(feature.properties.ibge_code,{path,bounds,uf,level});
                if(++count%100===0)await new Promise(resolve=>root.requestAnimationFrame(resolve));
                if(sequence!==this.sequence)return;
            }
            this.geometryLoaded.add(key);this.draw();
        }
        detailVisible(){if(!this.context||this.camera.scale<3)return;const c=this.camera,area=[-c.x/c.scale,-c.y/c.scale,(820-c.x)/c.scale,(740-c.y)/c.scale],scopes=new Set();for(const item of this.paths.values()){const b=item.bounds;if((!this.uf||item.uf===this.uf)&&b[2]>=area[0]&&b[0]<=area[2]&&b[3]>=area[1]&&b[1]<=area[3])scopes.add(item.uf);}for(const uf of [...scopes].slice(0,4))this.loadGeometry(uf,'detail').catch(()=>{this.find('mmap-status').textContent='A malha detalhada não pôde ser carregada. A resolução nacional continua disponível.';});}
        async stateData(uf){
            if(this.details.has(uf))return this.details.get(uf);
            const context=this.context;const data=await this.reader.data(context,uf+'/president.json',this.controller.signal);
            if(context!==this.context)return null;
            if(data.uf!==uf||data.municipalities.length!==this.rows.filter(r=>r.uf===uf).length||data.municipalities.some(r=>r.uf!==uf||r.election.round!==this.round))throw new Error('municipal_invalid_uf_partition');
            this.details.set(uf,data);for(const row of data.municipalities)this.fullById.set(row.ibge_code,row);return data;
        }
        visible(){return (this.rows||[]).filter(r=>(!this.uf||r.uf===this.uf)&&(!this.query||normalize(r.name+' '+r.uf).includes(this.query)));}
        color(row){
            const base=id=>this.baseColors.get(id)||'#d7dfe5';
            if(this.mode!=='share'&&!row.leader||['waiting','inconclusive'].includes(row.status))return '#d7dfe5';
            if(this.mode==='leader')return base(row.leader.id);
            let percent=this.mode==='margin'?row.difference_percentage_points:null,color=base(row.leader.id);
            if(this.mode==='share'){
                const candidate=Object.values(this.catalog).find(c=>String(c.number)===this.candidate);if(!candidate)return '#d7dfe5';
                color=base(candidate.id);const full=this.fullById.get(row.ibge_code),value=full?.candidates.find(c=>c.id===candidate.id);
                percent=value&&full.valid_votes?value.votes/full.valid_votes*100:null;
            }
            if(percent==null)return '#d7dfe5';
            const mix=Math.max(.12,Math.min(1,percent/100));return '#'+[1,3,5].map(i=>Math.round(238+(parseInt(color.slice(i,i+2),16)-238)*mix).toString(16).padStart(2,'0')).join('');
        }
        draw(){if(!this.active||this.frame)return;this.frame=root.requestAnimationFrame(()=>{this.frame=null;this.paint();});}
        paint(){
            const dpr=Math.min(2,root.devicePixelRatio||1);if(this.canvas.width!==820*dpr){this.canvas.width=820*dpr;this.canvas.height=740*dpr;}
            const ctx=this.ctx;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,820,740);
            ctx.setTransform(dpr*this.camera.scale,0,0,dpr*this.camera.scale,dpr*this.camera.x,dpr*this.camera.y);
            const visible=new Set(this.visible().map(r=>r.ibge_code)),style=getComputedStyle(this.mount),surface=style.getPropertyValue('--emap-surface')||'#fff',ink=style.getPropertyValue('--emap-text')||'#102334';
            for(const [id,item] of this.paths){const row=this.byId?.get(id);if(!row||this.uf&&item.uf!==this.uf)continue;
                ctx.globalAlpha=visible.has(id)?(this.candidate&&this.mode==='leader'&&String(this.catalog[row.leader?.id]?.number)!==String(this.candidate)? .28:1):.12;
                ctx.fillStyle=this.color(row);ctx.fill(item.path,'evenodd');ctx.strokeStyle=surface;ctx.lineWidth=.4/this.camera.scale;
                ctx.setLineDash(row.consolidation==='partial'&&['partial','tie'].includes(row.status)?[2/this.camera.scale,2/this.camera.scale]:[]);ctx.stroke(item.path);
                if(id===this.selected||id===this.hovered){ctx.globalAlpha=1;ctx.strokeStyle=ink;ctx.lineWidth=2.5/this.camera.scale;ctx.setLineDash([]);ctx.stroke(item.path);}
            }ctx.globalAlpha=1;ctx.setLineDash([]);
        }
        point(event){const b=this.canvas.getBoundingClientRect();return {x:(event.clientX-b.left)*820/b.width,y:(event.clientY-b.top)*740/b.height};}
        hit(point){const x=(point.x-this.camera.x)/this.camera.scale,y=(point.y-this.camera.y)/this.camera.scale;
            this.ctx.save();this.ctx.setTransform(1,0,0,1,0,0);let match=null;
            for(const [id,item] of this.paths){if(this.uf&&item.uf!==this.uf)continue;const b=item.bounds;if(x>=b[0]&&y>=b[1]&&x<=b[2]&&y<=b[3]&&this.ctx.isPointInPath(item.path,x,y,'evenodd')){match=id;break;}}
            this.ctx.restore();return match;
        }
        fit(){
            const items=[...this.paths.values()].filter(p=>!this.uf||p.uf===this.uf);if(!items.length)return;
            const box=[Math.min(...items.map(p=>p.bounds[0])),Math.min(...items.map(p=>p.bounds[1])),Math.max(...items.map(p=>p.bounds[2])),Math.max(...items.map(p=>p.bounds[3]))];
            const scale=Math.min(35,Math.min(760/(box[2]-box[0]),660/(box[3]-box[1])));this.camera={scale,x:410-(box[0]+box[2])/2*scale,y:370-(box[1]+box[3])/2*scale};this.draw();
        }
        async select(id,update=true){
            const row=this.byId?.get(id);if(!row)return;const sequence=this.sequence;this.selected=id;this.page=0;
            try{const data=await this.stateData(row.uf);if(sequence!==this.sequence||!data)return;this.render();if(update)this.url();}catch(error){if(sequence!==this.sequence||error.name==='AbortError')return;this.find('mmap-status').textContent='Não foi possível carregar os detalhes municipais. Tente novamente.';}
        }
        async setUF(uf,sync=true){this.uf=uf;this.selected='';this.page=0;this.find('mmap-uf').value=uf;const sequence=this.sequence;
            if(!this.context)return;
            try{if(uf){await this.loadGeometry(uf,'detail');if(sequence!==this.sequence)return;await this.stateData(uf);}else{const pending=UFS.filter(u=>!this.geometryLoaded.has(u+'-national'));await Promise.all(Array.from({length:4},async()=>{while(pending.length)await this.loadGeometry(pending.shift(),'national');}));}if(sequence!==this.sequence)return;this.fit();this.render();this.url();if(sync)await this.parent.portal.selectScope(uf||'br',1);}catch(error){if(sequence!==this.sequence||error.name==='AbortError')return;this.find('mmap-status').textContent='Falha ao carregar esta UF. Use Tentar novamente; nenhuma outra UF é substituída.';}
        }
        url(){const u=new URL(root.location.href);for(const k of ['nivel','muf','municipio'])u.searchParams.delete(k);if(this.active){u.searchParams.set('nivel','municipios');if(this.uf)u.searchParams.set('muf',this.uf);if(this.selected)u.searchParams.set('municipio',this.selected);}root.history.replaceState(root.history.state,'',u);}
        render(){
            const statusNode=this.find('mmap-status');this.find('mmap-round-label').textContent=this.round+'º TURNO';this.mount.setAttribute('aria-busy',String(this.loading));
            if(this.error){statusNode.replaceChildren(el('span','',this.waiting?'Aguardando dados municipais oficiais deste turno.':'Não foi possível validar a publicação municipal. A versão anterior e outros turnos não são usados como substitutos.'));const retry=el('button','emap-retry','Tentar novamente');retry.type='button';retry.onclick=()=>this.load();statusNode.append(retry);}
            else if(this.loading)statusNode.textContent='Carregando e verificando a publicação municipal…';
            else if(this.context){const rows=this.visible(),available=rows.filter(r=>['final','partial','tie'].includes(r.status)).length;statusNode.textContent=`${num(available)} de ${num(rows.length)} municípios com dados de votação · ${this.uf?this.uf.toUpperCase():'Brasil'} · limites reais IBGE.`;}
            this.find('mmap-caption').textContent=(this.uf?this.uf.toUpperCase():'BRASIL')+' · MUNICÍPIOS';
            this.draw();this.legend();this.detail();if(this.table)this.renderTable();
            this.find('mmap-method').textContent=this.mode==='margin'?'Diferença: (votos do primeiro − votos do segundo) ÷ votos válidos nominais municipais × 100. Valores em pontos percentuais. Empates ficam neutros.':this.mode==='share'?'Intensidade: votos do candidato ÷ votos válidos nominais do próprio município × 100. Sem denominador válido, o município fica neutro.':'A cor indica o candidato mais votado no município; borda tracejada identifica apuração parcial. Isso não significa candidato eleito.';
        }
        legend(){const node=this.find('mmap-legend');node.replaceChildren();if(this.mode==='share'){const candidate=Object.values(this.catalog).find(c=>String(c.number)===this.candidate);node.append(el('span','',candidate?`Percentual municipal: ${candidate.name} · ${candidate.party}`:'Escolha um candidato para visualizar a intensidade.'));if(candidate){const gradient=el('span','mmap-gradient');gradient.style.background=`linear-gradient(90deg,#eee,${this.baseColors.get(candidate.id)})`;gradient.setAttribute('aria-hidden','true');node.append(gradient,el('span','','0% → 100% dos votos válidos nominais'));}return;}if(this.mode==='margin')node.append(el('span','','Intensidade da diferença: 0–100 p.p.; cor identifica quem lidera.'));const counts=new Map();for(const r of this.visible())if(r.leader)counts.set(r.leader.id,(counts.get(r.leader.id)||0)+1);
            for(const [id,count] of [...counts].sort((a,b)=>b[1]-a[1])){const candidate=this.catalog[id];if(!candidate)continue;const button=el('button','emap-legend-item');button.type='button';const swatch=el('span','emap-swatch');swatch.style.background=root.ElectoralMap.candidateColor(candidate.number);button.append(swatch,el('span','',`${candidate.name} · ${candidate.party} · ${num(count)} municípios`));button.onclick=()=>{this.candidate=this.candidate===String(candidate.number)?'':String(candidate.number);this.find('mmap-candidate').value=this.candidate;this.render();};node.append(button);}
            node.append(el('span','emap-neutral-legend','Neutro: empate, aguardando apuração ou liderança inconclusiva.'));
        }
        detail(){const panel=this.find('mmap-detail');panel.replaceChildren();const row=this.byId?.get(this.selected);
            if(!row){panel.append(el('h3','',this.uf?this.parent.states.find(s=>s.scope===this.uf)?.name:'Visão municipal do Brasil'),el('p','emap-detail-copy','Selecione um município no mapa, na busca ou na tabela para abrir seus votos e a fonte oficial.'));if(this.coverage){const reports=this.uf?[this.coverage.ufs[this.uf]]:Object.values(this.coverage.ufs);panel.append(el('p','',`${num(reports.reduce((s,r)=>s+r.processed,0))} municípios processados. ${num(reports.reduce((s,r)=>s+r.pending,0))} pendentes; ${num(reports.reduce((s,r)=>s+r.failed,0))} falhas.`));}return;}
            const full=this.fullById.get(row.ibge_code)||row;
            panel.append(el('p','emap-eyebrow',`${row.uf.toUpperCase()} · IBGE ${row.ibge_code} · TSE ${row.tse_code}`),el('h3','',row.name+' — '+row.uf.toUpperCase()),el('span','emap-status-badge',status(row)));
            const stat=(label,value)=>{const n=el('div','mmap-stat');n.append(el('small','',label),el('strong','',value));panel.append(n);};
            if(row.leader){const c=this.catalog[row.leader.id];stat('Mais votado',`${c.name} · ${c.party}`);stat('Votos municipais',num(row.leader.votes));stat('Percentual municipal',pct(row.valid_votes?row.leader.votes/row.valid_votes*100:null));}
            if(row.status==='tie')for(const tied of row.ties||[]){const c=this.catalog[tied.id];stat('Empate no primeiro lugar',`${c.name} · ${c.party} · ${num(tied.votes)} votos`);}
            if(row.second&&row.status!=='tie'){const c=this.catalog[row.second.id];stat('Segundo colocado',`${c.name} · ${c.party}`);stat('Votos do segundo',num(row.second.votes));}
            if(row.difference_votes!=null)stat('Diferença em votos',num(row.difference_votes));
            stat('Seções totalizadas',`${num(row.sections.totalized)} / ${num(row.sections.total)} · ${pct(row.sections.percentage)}`);stat('Atualização TSE',date(row.updated_at));
            if(full.source_url){const a=el('a','emap-source','Consultar arquivo municipal no TSE ↗');a.href=full.source_url;a.target='_blank';a.rel='noopener noreferrer';panel.append(a);}
            const state=this.details.get(row.uf)?.state;
            if(state){const compare=el('details','mmap-comparison');compare.append(el('summary','','Comparar com a UF nesta publicação'));const leader=state.leader&&this.catalog[state.leader.id];compare.append(el('p','',leader?`${row.uf.toUpperCase()}: ${leader.name} · ${leader.party}, ${num(state.leader.votes)} votos (${pct(state.valid_votes?state.leader.votes/state.valid_votes*100:null)}). ${status(state)}.`:status(state)),el('p','','A comparação usa o resultado estadual capturado junto desta publicação municipal; não soma exterior nem confunde municípios liderados com votos.'));panel.append(compare);}
        }
        renderTable(){const wrap=this.find('mmap-table');wrap.replaceChildren();const rows=this.visible(),table=el('table'),caption=el('caption','','Resultados presidenciais por município'),head=el('thead'),tr=el('tr');for(const text of ['Município / UF','Mais votado','Votos','Percentual','Segundo','Diferença','Situação']){const th=el('th','',text);th.scope='col';tr.append(th);}head.append(tr);table.append(caption,head);const body=el('tbody');
            this.page=Math.max(0,Math.min(this.page,Math.ceil(rows.length/30)-1));
            for(const row of rows.slice(this.page*30,(this.page+1)*30)){const tr=el('tr');tr.dataset.ibge=row.ibge_code;const td=el('td'),button=el('button','',`${row.name} / ${row.uf.toUpperCase()}`);button.type='button';button.onclick=()=>this.select(row.ibge_code);td.append(button);tr.append(td);for(const value of [this.catalog[row.leader?.id]?.name||'—',row.leader?num(row.leader.votes):'—',row.leader?pct(row.leader.votes/row.valid_votes*100):'—',this.catalog[row.second?.id]?.name||'—',num(row.difference_votes),status(row)])tr.append(el('td','',value));body.append(tr);}table.append(body);wrap.append(table);const pages=el('div','mmap-pagination'),previous=el('button','','← Anterior'),next=el('button','','Próxima →');previous.type=next.type='button';previous.disabled=this.page===0;next.disabled=(this.page+1)*30>=rows.length;previous.onclick=()=>{this.page--;this.renderTable();};next.onclick=()=>{this.page++;this.renderTable();};pages.append(previous,el('span','',`${this.page+1} / ${Math.max(1,Math.ceil(rows.length/30))} · ${num(rows.length)} municípios`),next);wrap.append(pages);
        }
        bind(){
            this.municipalButton.onclick=()=>this.activate(true);this.stateButton.addEventListener('click',()=>this.activate(false));
            this.find('mmap-uf').onchange=()=>this.setUF(this.find('mmap-uf').value);
            this.find('mmap-mode').onchange=async()=>{const sequence=this.sequence;this.mode=this.find('mmap-mode').value;this.parent.mode=this.mode;this.parent.find('emap-mode').value=this.mode;this.parent.updateUrl();if(this.mode==='share'&&this.context){const pending=this.uf?[this.uf]:UFS.slice();this.find('mmap-status').textContent='Carregando percentuais municipais por UF…';try{await Promise.all(Array.from({length:4},async()=>{while(pending.length)await this.stateData(pending.shift());}));}catch(error){if(sequence!==this.sequence||error.name==='AbortError')return;this.find('mmap-status').textContent='Falha ao carregar percentuais. Municípios sem dados completos ficam neutros.';return;}}this.render();};
            this.find('mmap-candidate').onchange=()=>{this.candidate=this.find('mmap-candidate').value;this.parent.candidate=this.candidate;this.parent.find('emap-candidate').value=this.candidate;this.parent.portal.setCandidate(this.candidate);this.parent.updateUrl();this.render();};
            for(const table of [false,true])this.find(table?'mmap-table-view':'mmap-map-view').onclick=()=>{this.table=table;this.find('mmap-visual').hidden=table;this.find('mmap-table').hidden=!table;this.find('mmap-map-view').setAttribute('aria-pressed',String(!table));this.find('mmap-table-view').setAttribute('aria-pressed',String(table));this.render();};
            const search=this.find('mmap-search');search.oninput=()=>{this.query=normalize(search.value.trim());this.page=0;const list=this.find('mmap-search-results');list.replaceChildren();const matches=searchRows(this.rows||[],this.query).slice(0,12);for(const row of this.query?matches:[]){const button=el('button','',`${row.name} — ${row.uf.toUpperCase()}`);button.type='button';button.setAttribute('role','option');button.onclick=async()=>{this.query='';search.value='';list.replaceChildren();search.setAttribute('aria-expanded','false');await this.setUF(row.uf);await this.select(row.ibge_code);};list.append(button);}if(this.query&&!matches.length)list.append(el('p','','Nenhum município encontrado.'));search.setAttribute('aria-expanded',String(!!this.query));this.render();};
            search.onkeydown=event=>{if(event.key==='ArrowDown'){event.preventDefault();this.find('mmap-search-results').querySelector('button')?.focus();}if(event.key==='Enter')this.find('mmap-search-results').querySelector('button')?.click();if(event.key==='Escape'){search.value='';search.dispatchEvent(new Event('input'));}};
            this.find('mmap-search-results').onkeydown=event=>{const list=[...this.find('mmap-search-results').querySelectorAll('button')],i=list.indexOf(doc.activeElement);if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();list[(i+(event.key==='ArrowDown'?1:list.length-1))%list.length]?.focus();}if(event.key==='Escape'){search.focus();search.value='';search.dispatchEvent(new Event('input'));}};
            this.find('mmap-zoom-in').onclick=()=>{this.camera=zoom(this.camera,{x:410,y:370},1.4);this.draw();this.detailVisible();};this.find('mmap-zoom-out').onclick=()=>{this.camera=zoom(this.camera,{x:410,y:370},1/1.4);this.draw();};this.find('mmap-reset').onclick=()=>this.setUF('');
            this.canvas.addEventListener('wheel',event=>{if(event.ctrlKey||event.metaKey){event.preventDefault();this.camera=zoom(this.camera,this.point(event),Math.exp(-event.deltaY*.002));this.draw();this.detailVisible();}}, {passive:false});
            const pointers=new Map();let drag=null,dragged=false,pinch=null;
            this.canvas.onpointerdown=event=>{if(event.button!==0&&event.pointerType!=='touch')return;this.canvas.setPointerCapture(event.pointerId);pointers.set(event.pointerId,this.point(event));drag={point:this.point(event),camera:{...this.camera}};dragged=false;if(pointers.size===2){const [a,b]=[...pointers.values()];pinch={distance:Math.hypot(a.x-b.x,a.y-b.y),camera:{...this.camera},point:{x:(a.x+b.x)/2,y:(a.y+b.y)/2}};dragged=true;}};
            this.canvas.onpointermove=event=>{const point=this.point(event);if(pointers.has(event.pointerId))pointers.set(event.pointerId,point);
                if(pinch&&pointers.size===2){const [a,b]=[...pointers.values()],center={x:(a.x+b.x)/2,y:(a.y+b.y)/2};this.camera=zoom(pinch.camera,pinch.point,Math.hypot(a.x-b.x,a.y-b.y)/pinch.distance);this.camera.x+=center.x-pinch.point.x;this.camera.y+=center.y-pinch.point.y;this.draw();return;}
                if(drag){const dx=point.x-drag.point.x,dy=point.y-drag.point.y;if(Math.hypot(dx,dy)>5)dragged=true;if(dragged){this.camera={...drag.camera,x:drag.camera.x+dx,y:drag.camera.y+dy};this.draw();}return;}
                const id=this.hit(point);this.hovered=id;const tip=this.find('mmap-tooltip');tip.hidden=!id;if(id){const row=this.byId.get(id),c=this.catalog[row.leader?.id];tip.textContent=`${row.name} — ${row.uf.toUpperCase()} · ${c?`${c.name} (${c.party}), ${num(row.leader.votes)} votos, ${pct(row.leader.votes/row.valid_votes*100)}`:status(row)} · ${row.second?`Segundo: ${this.catalog[row.second.id]?.name}, ${num(row.second.votes)} votos. Diferença: ${num(row.difference_votes)} votos.`:''} · ${status(row)} · ${this.round}º turno · ${date(row.updated_at)}`;tip.style.left=Math.min(55,point.x/820*100)+'%';tip.style.top=Math.min(80,point.y/740*100)+'%';}this.draw();};
            this.canvas.onpointerup=event=>{const point=this.point(event);pointers.delete(event.pointerId);if(!dragged&&event.pointerType!=='touch'||!dragged&&pointers.size===0){const id=this.hit(point);if(id)this.select(id);}drag=null;pinch=null;this.detailVisible();};this.canvas.onpointercancel=()=>{pointers.clear();drag=null;pinch=null;};this.canvas.onpointerleave=()=>{this.hovered=null;this.find('mmap-tooltip').hidden=true;this.draw();};
            this.canvas.onkeydown=event=>{const rows=this.visible();if(event.key==='Home'){event.preventDefault();this.fit();}if(event.key==='Escape'){this.selected='';this.render();this.url();}if(['ArrowRight','ArrowLeft','ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();const i=Math.max(0,rows.findIndex(r=>r.ibge_code===this.hovered));this.hovered=rows[(i+(['ArrowRight','ArrowDown'].includes(event.key)?1:rows.length-1))%rows.length]?.ibge_code;const row=this.byId?.get(this.hovered);if(row)this.find('mmap-status').textContent=`${row.name} — ${row.uf.toUpperCase()}. ${status(row)}. Enter abre os detalhes.`;this.draw();}if(event.key==='Enter'||event.key===' '){event.preventDefault();if(this.hovered)this.select(this.hovered);}};
            new MutationObserver(()=>this.draw()).observe(doc.documentElement,{attributes:true,attributeFilter:['data-theme']});
        }
    }
    api.View=View;api.install=parent=>{parent.municipal=new View(parent);};
})(typeof globalThis!=='undefined'?globalThis:this);
