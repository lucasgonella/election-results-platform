/* Actual LiveData reader with independent simulated users. Loopback only. */
'use strict';
const {create}=require('../web/public/eleicoes/live-data.js');
const fs=require('node:fs');
const [origin,countArg,durationArg,output]=process.argv.slice(2);
const endpoint=new URL(origin);
if(!['127.0.0.1','localhost'].includes(endpoint.hostname))throw Error('Loopback only');
const users=Number(countArg),duration=Number(durationArg);
if(!Number.isInteger(users)||users<1||users>1000||duration<1||duration>1800)throw Error('Invalid rehearsal limits');
const started=Date.now(),stats=[],errors=[],requests=[],detections=[];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function session(id){
 const reader=create(async(path,options)=>{
  const before=Date.now();
  try{
   const response=await fetch(origin+path,{...options,headers:{...options.headers,'X-Rehearsal-Session':String(id)}});
   requests.push({session:id,path,status:response.status,duration_ms:Date.now()-before,at:before});
   return response;
  }catch(error){requests.push({session:id,path,error:error.name,duration_ms:Date.now()-before,at:before});throw error;}
 });
 let previous=null;
 await sleep(id*15); // spread initial arrivals; this is not a connection flood
 while(Date.now()-started<duration*1000){
  try{
   const response=await reader.fetch('/data/turnos/2/version.json');
   if(!response.ok)throw Error('marker_'+response.status);
   const marker=await response.json();
   if(marker.snapshot_id!==previous){
    const base='/data/turnos/2/releases/'+marker.snapshot_id;
    const manifest=await(await reader.fetch(base+'/manifest.json')).json();
    const row=manifest.results.find(x=>x.scope==='br'&&x.office===1)||manifest.results[0];
    const result=await(await reader.fetch(base+'/'+row.path)).json();
    if(result.election.round!==2)throw Error('mixed_round');
    detections.push({session:id,snapshot_id:marker.snapshot_id,detected_at:Date.now()});
    previous=marker.snapshot_id;
   }
  }catch(error){errors.push({session:id,error:error.message,at:Date.now()});}
  await sleep(5000+Math.random()*250);
 }
 stats.push({session:id,...reader.stats});
}
(async()=>{
 await Promise.all(Array.from({length:users},(_,i)=>session(i)));
 fs.writeFileSync(output,JSON.stringify({users,duration_seconds:(Date.now()-started)/1000,stats,requests,detections,errors},null,2));
 console.log(JSON.stringify({users,requests:requests.length,errors:errors.length,detections:detections.length}));
})().catch(error=>{console.error(error);process.exitCode=1;});
