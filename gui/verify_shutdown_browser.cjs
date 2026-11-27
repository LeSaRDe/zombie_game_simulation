/* Actual browser tabs, live readers and public service drain; no injected delays. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
(async()=>{
 const [base,output,engine='chromium',tabs='open',mode='terminate']=process.argv.slice(2);
 const browser=await(engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});
 const context=await browser.newContext({baseURL:base,viewport:{width:1440,height:1100}});
 const report={passed:false,engine,browser:browser.version(),tabs,mode,requests:{},socket_closed:0,errors:[]};
 const until=async(fn,label,timeout=90000)=>{const end=Date.now()+timeout;while(Date.now()<end){const x=await fn();if(x)return x;await new Promise(r=>setTimeout(r,40));}throw Error('Timed out '+label);};
 const call=async(route,body)=>{const r=body===undefined?await context.request.get(route):await context.request.post(route,{data:body});assert(r.ok(),route+' '+await r.text());return r.json();};
 const command=async(id,operation)=>{const sent=await call(`/api/runs/${id}/commands`,{operation,command_id:randomUUID()});const result=await until(async()=>{const r=await call('/api/commands/'+sent.command_id);return r.status==='pending'?null:r;},operation);assert.equal(result.status,'applied');};
 try{
  await call('/api/runs');const runs=[];
  for(let n=0;n<2;n++){const made=await call('/api/runs',{config:{scenario:`shutdown_browser_${n}`,seed:800+n,horizon:120,execution:{workers:1}},command_id:randomUUID()});await until(async()=>(await call('/api/runs')).find(r=>r.id===made.run_id)?.status==='paused','initialized');runs.push(made.run_id);}
  const initial=await call(`/api/runs/${runs[0]}/view?time=0`);await call(`/api/runs/${runs[0]}/cohorts`,{name:'Shutdown study',mode:'dynamic',predicate:{type:'Human'},include_dead:true,reference_time:initial.time,reference_revision:initial.revision});
  for(const id of runs)await command(id,'resume');
  const pages=[];
  for(const panel of ['world','statistics','cohorts','events','comparison']){
   const p=await context.newPage();pages.push(p);p.on('pageerror',e=>report.errors.push(String(e)));p.on('websocket',socket=>socket.on('close',()=>report.socket_closed++));p.on('requestfinished',req=>{const route=new URL(req.url()).pathname;if(route.startsWith('/api/'))report.requests[route]=(report.requests[route]||0)+1;});await p.goto(base);await p.locator(`.sidebar button.run-card[data-run-id="${runs[0]}"]`).click();await p.waitForFunction(id=>window.__zombieInspection.app.view?.run_id===id,runs[0]);await p.getByTestId('tab-'+panel).click();
   if(panel==='comparison'){for(const id of runs)await p.locator(`[data-testid="comparison-choice"][data-run-id="${id}"]`).check();await p.waitForFunction(()=>window.__zombieInspection.comparison?.phase==='ready');}
   if(panel==='statistics')await p.waitForFunction(()=>window.__zombieInspection.app.metrics_state.phase==='ready');
   if(panel==='cohorts')await p.waitForFunction(()=>window.__zombieInspection.app.cohorts_state.phase==='ready'&&window.__zombieInspection.app.cohorts.length===1);
   if(panel==='events')await p.waitForFunction(()=>window.__zombieInspection.app.events_state.phase==='ready');
  }
  report.before=await until(async()=>{const s=await call('/api/shutdown');return s.viewers>=4&&s.readers.processes.length?s:null;},'actual active readers and sockets');
  report.panels=pages.length;await pages[0].close();if(tabs==='closed')for(const p of pages.slice(1))await p.close();
  report.after_tab_closure=await call('/api/shutdown');
  if(tabs==='open')assert(report.after_tab_closure.viewers>0);else await until(async()=>(await call('/api/shutdown')).viewers===0,'closed browser tabs');
  report.started=await call('/api/shutdown',{mode,timeout:60});
  const blocked=await context.request.get(`/api/runs/${runs[0]}/view`);assert.equal(blocked.status(),503);assert.equal((await blocked.json()).code,'SERVICE_DRAINING');report.new_expensive_read_rejected=true;
  report.ready=await until(async()=>{const s=await call('/api/shutdown');if(s.phase==='incomplete')throw Error(s.error);return s.complete?s:null;},'service ready',70000);
  assert.equal(report.ready.viewers,0);assert.equal(report.ready.readers.active,0);assert.equal(report.ready.readers.queued,0);assert.deepEqual(report.ready.readers.processes,[]);assert.equal(report.ready.exports.active,0);assert.deepEqual(report.ready.exports.readers.processes,[]);assert(Object.values(report.ready.runs).every(r=>r.cleanup_complete));
  report.final_runs=await call('/api/runs');assert(report.final_runs.every(r=>r.status===(mode==='save'?'stopped':'terminated')));assert(report.final_runs.every(r=>r.resource_status.cleanup_complete));
  if(tabs==='open')assert(report.socket_closed>=4);else assert(pages.every(p=>p.isClosed()));assert(Object.keys(report.requests).some(p=>p.includes('/comparison')));for(const kind of ['/metrics','/cohorts','/timeline'])assert(Object.keys(report.requests).some(p=>p.endsWith(kind)),kind);
  report.exiting=await call('/api/shutdown/exit',{});report.passed=true;
 }catch(e){report.error=String(e.stack||e);throw e;}finally{fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
