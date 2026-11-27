/* Reproduce the reported symptom against unchanged production assets. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const [base,output,runId,engine='chromium']=process.argv.slice(2);
 const report={passed:false,engine,steps:[],requests:[],errors:[]};
 const browser=await(engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});
 let page;
 try{
  page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
  page.on('pageerror',error=>report.errors.push(String(error)));
  page.on('request',request=>{if(request.url().includes('/api/'))report.requests.push({method:request.method(),url:new URL(request.url()).pathname+new URL(request.url()).search,body:request.postData()});});
  const app=()=>page.evaluate(()=>window.__zombieInspection.app);
  const head=async()=>{const response=await page.request.get('/api/runs');assert(response.ok());return(await response.json()).find(row=>row.id===runId);};
  const numeric=value=>{const[n,d]=String(value).split('/').map(Number);return n/(d??1);};
  const until=async(fn,label)=>{const limit=Date.now()+30000;while(Date.now()<limit){if(await fn())return;await page.waitForTimeout(40);}throw Error('Timed out: '+label);};
  const ready=()=>until(async()=>{const a=await app();return a.view?.run_id===runId&&!a.view_pending&&a.viewer_load.phase==='ready';},'ready view');
  const capture=async(label)=>{await ready();const a=await app(),r=await head();report.steps.push({label,mode:a.mode,display_time:a.view.time,display_revision:a.view.revision,execution_status:r.status,execution_time:r.frontier.time,execution_revision:r.frontier.revision,chart_time:await page.getByTestId('chart-time').inputValue().catch(()=>null),cursor_text:await page.locator('.cursor-bar').innerText()});return report.steps.at(-1);};
  const live=async()=>{if((await app()).mode==='replay')await page.getByTestId('replay-return-live').click();await until(async()=>{const a=await app();return a.mode==='live'&&a.view?.mode==='live'&&!a.view_pending;},'live view');};
  const provesRunningAtZero=async(label)=>{
   await until(async()=>{const a=await app();return a.mode==='replay'&&numeric(a.view?.time)===0&&!a.view_pending;},'zero-time replay');
   const before=await capture(label+' selected'),firstRevision=before.display_revision;
   await until(async()=>numeric((await head()).frontier.time)>numeric(before.execution_time)+.5,'authoritative execution continues');
   const after=await capture(label+' while execution advances');
   assert.equal(after.execution_status,'running');assert.equal(numeric(after.display_time),0);assert.equal(after.display_revision,firstRevision);
   assert(numeric(after.execution_time)>numeric(before.execution_time));
   await page.screenshot({path:path.join(output,label+'.png'),fullPage:true});
  };
  await page.goto(base);await page.getByTestId('run-chooser').waitFor();
  report.assets=await page.locator('script[src]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('src')));
  await page.locator(`.sidebar button.run-card[data-run-id="${runId}"]`).click();await ready();
  await capture('Initial live view');
  for(const tab of ['statistics','cohorts','events']){
   await page.getByTestId('tab-'+tab).click();await ready();const state=await capture('Open '+tab+' tab');assert.equal(state.mode,'live');assert.equal(state.execution_status,'running');
  }
  await page.getByTestId('tab-cohorts').click();await page.getByTestId('cohort-card').waitFor();
  await page.getByTestId('cohort-card').locator('summary').click();const cohort=await capture('Expand cohort membership');assert.equal(cohort.mode,'live');
  await page.getByTestId('tab-statistics').click();
  await until(async()=>(await app()).samples.length>1,'Statistics samples');
  assert.equal(await page.getByTestId('chart-time').inputValue(),'0');
  await page.getByTestId('chart-select').click();await provesRunningAtZero('untouched-chart-time');
  await live();await capture('Return to live after chart inspection');
  await page.getByTestId('population-table-toggle').click();
  const first=page.getByTestId('population-table').locator('tbody tr').first().getByRole('button');assert.equal(await first.innerText(),'0');
  await first.click();await provesRunningAtZero('first-statistics-sample');
  await live();await page.getByTestId('tab-events').click();
  await until(async()=>{const a=await app();return a.events_state.phase==='ready'&&a.shownEvents.length>0;},'Events page');
  const event=page.getByTestId('timeline-first-event').first();
  const eventTime=await event.locator('[data-exact-time]').getAttribute('data-exact-time');assert.equal(numeric(eventTime),0);
  await event.click();await provesRunningAtZero('first-event');
  await page.getByTestId('event-before').click();await ready();await capture('Before initial event');
  await page.getByTestId('event-after').click();await ready();await capture('After initial event');
  await live();await capture('Final return to live');
  report.execution_commands=report.requests.filter(item=>item.method==='POST'&&item.url.endsWith('/commands'));
  assert.deepEqual(report.execution_commands,[]);assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(error){report.error=String(error.stack||error);if(page)try{report.failure=await page.evaluate(()=>window.__zombieInspection.app);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}catch{}throw error;}
 finally{fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
