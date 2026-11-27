/* Independent I25 checks: real UI actions, DOM labels, command journal and ledger. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const [base,output,engine='chromium']=process.argv.slice(2);
 const ids=JSON.parse(fs.readFileSync(path.join(output,'fixture.json')));
 const report={passed:false,engine,steps:[],requests:[],errors:[]};
 const browser=await(engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});
 let page;const releases=[];
 try{
  page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
  page.on('pageerror',error=>report.errors.push(String(error)));
  page.on('request',request=>{if(request.url().includes('/api/'))report.requests.push({method:request.method(),url:new URL(request.url()).pathname+new URL(request.url()).search,body:request.postData()});});
  const app=()=>page.evaluate(()=>window.__zombieInspection?.app);
  const numeric=value=>{const[n,d]=String(value).split('/').map(Number);return n/(d??1);};
  const until=async(fn,label,timeout=30000)=>{const limit=Date.now()+timeout;while(Date.now()<limit){if(await fn())return;await page.waitForTimeout(40);}throw Error('Timed out: '+label);};
  const ready=(identity=ids.primary)=>until(async()=>{const a=await app();return a?.view?.run_id===identity&&!a.view_pending&&a.viewer_load.phase==='ready';},'ready view '+identity);
  const getJSON=async(url)=>{const response=await page.request.get(url);assert(response.ok(),url);return response.json();};
  const audit=(identity=ids.primary,through)=>getJSON(`/fixture/audit?run_id=${identity}${through===undefined?'':'&through='+through}`);
  const head=async(identity=ids.primary)=>(await getJSON('/api/runs')).find(row=>row.id===identity);
  const attrs=async(id)=>page.getByTestId(id).evaluate(node=>({text:node.textContent,status:node.dataset.status,freshness:node.dataset.freshness,mode:node.dataset.mode,time:node.dataset.time,revision:node.dataset.revision}));
  const capture=async(label,identity=ids.primary)=>{
   await ready(identity);const {a,execution,viewer}=await page.evaluate(()=>{
    const read=id=>{const node=document.querySelector(`[data-testid="${id}"]`);return {text:node.textContent,status:node.dataset.status,freshness:node.dataset.freshness,mode:node.dataset.mode,time:node.dataset.time,revision:node.dataset.revision};};
    return {a:window.__zombieInspection.app,execution:read('simulation-status'),viewer:read('viewer-status')};
   });
   assert.equal(viewer.mode,a.mode);assert.equal(viewer.time,String(a.view.time));assert.equal(viewer.revision,String(a.view.revision));
   assert.equal(execution.status,a.run.status);assert.equal(execution.time,String(a.run.frontier.time));assert.equal(execution.revision,String(a.run.frontier.revision));
   const value={label,run_id:identity,execution,viewer,banner:await page.getByTestId('replay-status-message').count()?await page.getByTestId('replay-status-message').textContent():null,populations:a.view.metrics.populations};report.steps.push(value);console.log(label);return value;
  };
  const select=async(identity)=>{await page.locator(`.sidebar button.run-card[data-run-id="${identity}"]`).click();await ready(identity);};
  const live=async(identity=ids.primary)=>{if((await app()).mode==='replay')await page.getByTestId('replay-return-live').click();await until(async()=>{const a=await app();return a.mode==='live'&&a.view?.mode==='live'&&!a.view_pending;},'live view');await ready(identity);};
  const seek=async(time)=>{await page.getByTestId('replay-exact-time').fill(time);await page.getByTestId('replay-seek').click();await ready();};
  const current=()=>until(async()=>(await attrs('simulation-status')).freshness==='current','fresh run summary');
  const historyZero=async(label)=>{
   await until(async()=>{const a=await app();return a.mode==='replay'&&numeric(a.view?.time)===0&&!a.view_pending;},'zero-time replay');await current();
   const before=await capture(label+' selected'),ledger=await audit();
   assert.match(before.viewer.text,/Viewing recorded history/i);assert.match(before.banner,/You are viewing recorded history\. The simulation is still running\./);
   await until(async()=>(await audit()).head.seconds>ledger.head.seconds+.5,'durable ledger advances during replay');
   const later=await audit(ids.primary,ledger.through),after=await capture(label+' while execution advances');
   assert.equal(after.execution.status,'running');assert.equal(after.viewer.time,before.viewer.time);assert.equal(after.viewer.revision,before.viewer.revision);assert.deepEqual(after.populations,before.populations);
   assert.equal(ledger.prefix_sha256,later.prefix_sha256);assert(later.head.seconds>ledger.head.seconds);
   report.steps.push({label:label+' ledger evidence',before:ledger,after:later});
  };
  await page.goto(base);await page.getByTestId('run-chooser').waitFor();
  report.assets=await page.locator('script[src]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('src')));
  await select(ids.primary);await current();const initialAudit=await audit();await capture('Initial live view');
  for(const tab of ['statistics','cohorts','events']){
   await page.getByTestId('tab-'+tab).click();const state=await capture('Open '+tab+' tab');assert.equal(state.viewer.mode,'live');assert.equal(state.execution.status,'running');
  }
  await page.getByTestId('tab-cohorts').click();await page.getByTestId('cohort-card').waitFor();await page.getByTestId('cohort-card').locator('summary').click();assert.equal((await capture('Expand cohort details')).viewer.mode,'live');
  await page.getByTestId('tab-statistics').click();
  await until(async()=>{const a=await app();return a.samples.length>1&&(await page.getByTestId('chart-time').inputValue())===String(a.view.time);},'untouched field follows selected cursor');
  const inputBefore=await page.getByTestId('chart-time').inputValue();assert(numeric(inputBefore)>0);
  await until(async()=>numeric(await page.getByTestId('chart-time').inputValue())>numeric(inputBefore),'untouched field advances');
  await page.getByTestId('chart-select').click();await ready();
  const untouched=await capture('Untouched Statistics field inspects current cursor');assert.equal(untouched.viewer.mode,'replay');assert(numeric(untouched.viewer.time)>0);assert.match(await page.getByTestId('chart-select').innerText(),/recorded/i);
  await live();await page.getByTestId('chart-time').fill('1/2');const editedHead=(await head()).frontier.time;
  await until(async()=>numeric((await head()).frontier.time)>numeric(editedHead)+.5,'run advances with edited draft');assert.equal(await page.getByTestId('chart-time').inputValue(),'1/2');
  await page.getByTestId('chart-time').press('Enter');await ready();assert.equal(numeric((await app()).view.time),.5);await capture('Intentional fraction survives live updates and Enter selects it');
  await live();
  for(const draft of ['', 'banana','1/0','-1']){
   await page.getByTestId('chart-time').fill(draft);await page.getByTestId('chart-select').click();await page.getByTestId('chart-time-error').waitFor();
   assert.equal(await page.getByTestId('chart-time').getAttribute('aria-invalid'),'true');assert.equal((await app()).mode,'live');report.steps.push({label:'Rejected invalid chart draft',draft,error:await page.getByTestId('chart-time-error').innerText()});
  }
  await page.getByTestId('chart-time').fill('0');await page.getByTestId('chart-time').press('Enter');await historyZero('Deliberately inspect zero');
  await page.getByTestId('chart-time-reset').click();assert.equal(await page.getByTestId('chart-time').inputValue(),String((await app()).view.time));
  await live();await page.getByTestId('population-table-toggle').click();const first=page.getByTestId('population-table').locator('tbody tr').first().getByRole('button');assert.equal(await first.innerText(),'0');await first.click();await historyZero('First Statistics sample');
  await live();await until(async()=>await page.getByTestId('population-chart').locator('.scatterlayer .trace .points .point').count()>1,'drawn Plotly markers');
  await page.getByTestId('population-chart').locator('.scatterlayer .trace .points .point').first().click({force:true});await historyZero('Actual Plotly sample click');
  await live();await page.getByTestId('tab-events').click();await until(async()=>{const a=await app();return a.events_state.phase==='ready'&&a.shownEvents.length>0;},'Events page');
  const event=page.getByTestId('timeline-first-event').first();assert.equal(numeric(await event.locator('[data-exact-time]').getAttribute('data-exact-time')),0);await event.click();await historyZero('First recorded event');await page.screenshot({path:path.join(output,'running-history.png'),fullPage:true});
  await page.getByTestId('event-before').click();await ready();const beforeEvent=await capture('Before recorded transition');
  await page.getByTestId('event-after').click();await ready();const afterEvent=await capture('After recorded transition');assert(BigInt(afterEvent.viewer.revision)>BigInt(beforeEvent.viewer.revision));
  await page.getByTestId('replay-pause').click();await until(async()=>numeric((await app()).view.time)>0,'replay playback advances viewer');await page.getByTestId('replay-pause').click();await ready();await capture('Pause replay playback leaves execution running');
  await seek('0');await ready();
  // Fail only the browser's status request; API audit reads remain real and available.
  const runsPattern='**/api/runs';
  await page.route(runsPattern,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'I25 isolated status outage'})}));
  await until(async()=>(await attrs('simulation-status')).freshness==='last-confirmed','failed status is last confirmed');
  const failedStatus=await capture('Failed status fetch');assert.match(failedStatus.execution.text,/Last confirmed/i);assert.match(failedStatus.banner,/last confirmed/i);assert.doesNotMatch(failedStatus.banner,/simulation is still running/i);
  await page.unroute(runsPattern);await current();
  let delayedEntered=false,releaseDelay;const delayedGate=new Promise(resolve=>releaseDelay=resolve);releases.push(releaseDelay);let firstDelay=true;
  await page.route(runsPattern,async route=>{if(!firstDelay)return route.fulfill({status:503,contentType:'application/json',body:'{"detail":"hold recovery for stale response assertion"}'});firstDelay=false;const response=await route.fetch();delayedEntered=true;await delayedGate;await route.fulfill({response});});
  await until(()=>delayedEntered,'captured delayed run summary');await page.waitForTimeout(5600);
  const stalePending=await capture('Pending summary exceeds freshness limit');assert.equal(stalePending.execution.freshness,'last-confirmed');assert.doesNotMatch(stalePending.banner,/simulation is still running/i);
  releaseDelay();await page.waitForTimeout(250);const staleArrival=await capture('Late response stays last confirmed');assert.equal(staleArrival.execution.freshness,'last-confirmed');
  await page.unroute(runsPattern);await current();
  // Hold a history response while switching runs; stale content must not return.
  await live();await page.getByTestId('tab-statistics').click();await page.getByTestId('chart-time').fill('11/4');
  let viewEntered=false,releaseView;const viewGate=new Promise(resolve=>releaseView=resolve);releases.push(releaseView);
  const viewPattern=`**/api/runs/${ids.primary}/view?*`;
  await page.route(viewPattern,async route=>{const response=await route.fetch();viewEntered=true;await viewGate;try{await route.fulfill({response});}catch{}});
  await page.getByTestId('replay-exact-time').fill('0');await page.getByTestId('replay-seek').click();await until(()=>viewEntered,'held historical view');
  await select(ids.alternate);assert.equal(await page.getByTestId('chart-time').inputValue(),'2');releaseView();await page.unroute(viewPattern);await page.waitForTimeout(300);await capture('Switch run discards edited input and late historical response',ids.alternate);
  assert.equal((await app()).view.run_id,ids.alternate);assert.equal((await app()).mode,'live');assert.equal(await page.getByTestId('chart-time').inputValue(),'2');
  await select(ids.primary);await until(async()=>await page.getByTestId('chart-time').inputValue()===String((await app()).view.time),'switch back resets input to selected view');
  await seek('0');await ready();
  await page.setViewportSize({width:390,height:900});
  for(const testid of ['simulation-status','viewer-status','replay-status-message']){
   const node=page.getByTestId(testid);assert(await node.isVisible());const box=await node.boundingBox();assert(box&&box.width<=390&&box.x>=0&&box.x+box.width<=391,`${testid} fits narrow screen: ${JSON.stringify(box)}`);
  }
  await page.getByTestId('replay-return-live').focus();await page.keyboard.press('Enter');await live();
  await page.getByTestId('tab-statistics').focus();await page.keyboard.press('Enter');await page.getByTestId('chart-time').fill('0');await page.getByTestId('chart-time').press('Enter');await ready();await capture('Keyboard history inspection at narrow width');
  await page.screenshot({path:path.join(output,'narrow-history.png'),fullPage:true});await page.setViewportSize({width:1440,height:1100});
  const analysisAudit=await audit(ids.primary,initialAudit.through);
  assert.deepEqual(analysisAudit.commands,initialAudit.commands);assert.equal(analysisAudit.prefix_sha256,initialAudit.prefix_sha256);assert(analysisAudit.head.seconds>initialAudit.head.seconds);
  report.analysis_audit={before:initialAudit,after:analysisAudit};report.analysis_execution_commands=report.requests.filter(r=>r.method==='POST'&&r.url.endsWith('/commands'));assert.deepEqual(report.analysis_execution_commands,[]);
  // Now explicit execution buttons are intentionally exercised while history stays selected.
  const historical=await capture('History before explicit execution controls');
  const expectedHistory=()=>({time:historical.viewer.time,revision:historical.viewer.revision,populations:historical.populations});
  const status=async(expected,label,identity=ids.primary)=>{
   await until(async()=>{const a=await app();return a.run?.status===expected&&!a.pending&&(await attrs('simulation-status')).freshness==='current';},label);
   if(['stopped','terminated','completed'].includes(expected))await until(async()=>{const a=await app();return a.run.resource_status?.cleanup_complete===true;},label+' cleanup');
   const result=await capture(label,identity);assert.match(result.banner,new RegExp(`simulation (?:is|has) ${expected}|simulation.*${expected}`,'i'));
   if(identity===ids.primary)assert.deepEqual({time:result.viewer.time,revision:result.viewer.revision,populations:result.populations},expectedHistory());
  };
  let oldEntered=false,releaseOld;const oldGate=new Promise(resolve=>releaseOld=resolve);releases.push(releaseOld);let oldOnce=true;
  await page.route(runsPattern,async route=>{if(!oldOnce)return route.continue();oldOnce=false;const response=await route.fetch();oldEntered=true;await oldGate;await route.fulfill({response});});
  await until(()=>oldEntered,'captured pre-pause summary');await page.getByTestId('run-pause').click();await status('paused','Explicit Pause run while viewing history');releaseOld();await page.waitForTimeout(300);assert.equal((await attrs('simulation-status')).status,'paused');await page.unroute(runsPattern);await current();
  await page.getByTestId('run-start').click();await status('running','Explicit Continue run while viewing history');
  await page.getByTestId('run-stop').click();await status('stopped','Explicit Stop and save while viewing history');
  await page.getByTestId('run-start').click();await status('running','Continue a stopped run while viewing history');
  await page.getByTestId('run-terminate').click();await status('terminated','Explicit Terminate while viewing history');
  await page.screenshot({path:path.join(output,'terminated-history.png'),fullPage:true});
  await select(ids.completion);await page.getByTestId('replay-exact-time').fill('0');await page.getByTestId('replay-seek').click();await ready(ids.completion);const completedHistory=await capture('Short run before completion',ids.completion);
  // Delay the applied Continue receipt until normal polling has observed completion.
  // A historical acknowledgement must not turn that completed summary back to running.
  let ackEntered=false,releaseAck,releaseSummaries,holdSummaries=false;
  const ackGate=new Promise(resolve=>releaseAck=resolve),summariesGate=new Promise(resolve=>releaseSummaries=resolve);
  releases.push(releaseAck,releaseSummaries);let ackBody;
  const ackPattern='**/api/**';
  await page.route(ackPattern,async route=>{
   const pathname=new URL(route.request().url()).pathname;
   if(pathname==='/api/runs'&&holdSummaries){await summariesGate;return route.continue();}
   if(pathname===`/api/runs/${ids.completion}/commands`||pathname.startsWith('/api/commands/')){
    const response=await route.fetch(),body=await response.json();
    if(body.status==='applied'&&!ackEntered){ackEntered=true;ackBody=body;await ackGate;await route.fulfill({response});return;}
    await route.fulfill({response});return;
   }
   await route.continue();
  });
  await page.getByTestId('run-start').click();await until(()=>ackEntered,'captured delayed applied Continue acknowledgement');
  await until(async()=>(await app()).run?.status==='completed','poll observes completion before old Continue acknowledgement');
  const summaryBeforeAck=(await app()).run;holdSummaries=true;releaseAck();
  await until(async()=>(await app()).command?.command_id===ackBody.command_id,'late acknowledgement applied');
  const summaryAfterAck=(await app()).run;
  assert.equal(summaryAfterAck.status,'completed');assert(BigInt(summaryAfterAck.frontier.revision)>=BigInt(summaryBeforeAck.frontier.revision));
  report.steps.push({label:'Delayed Continue acknowledgement cannot overwrite newer completed summary',acknowledgement:ackBody,before:summaryBeforeAck,after:summaryAfterAck});
  releaseSummaries();await page.unrouteAll({behavior:'wait'});await status('completed','Natural completion while viewing history',ids.completion);
  const completed=await capture('Completed history cursor retained',ids.completion);assert.equal(completed.viewer.time,completedHistory.viewer.time);assert.equal(completed.viewer.revision,completedHistory.viewer.revision);assert.deepEqual(completed.populations,completedHistory.populations);
  report.explicit_execution_commands=report.requests.filter(r=>r.method==='POST'&&r.url.endsWith('/commands')).map(r=>JSON.parse(r.body).operation);
  assert.deepEqual(report.explicit_execution_commands,['pause','continue','stop','continue','terminate','continue']);assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(error){report.error=String(error.stack||error);if(page)try{report.failure=await page.evaluate(()=>window.__zombieInspection.app);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}catch{}throw error;}
 finally{for(const release of releases)release();fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
