/* Diagnose unformatted exact times; no production behavior is changed. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const[base,output,engine='chromium']=process.argv.slice(2);
 const fixture=JSON.parse(fs.readFileSync(path.join(output,'fixture.json'),'utf8'));
 const[runId,otherId]=fixture.run_ids,exact=fixture.exact_time;
 const report={passed:false,engine,surfaces:[],requests:[],errors:[]};
 const browser=await(engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});let page;
 try{
  page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('request',r=>{if(r.url().includes('/api/'))report.requests.push({method:r.method(),url:new URL(r.url()).pathname+new URL(r.url()).search,body:r.postData()});});
  const app=()=>page.evaluate(()=>window.__zombieInspection.app);
  const until=async(fn,label)=>{const limit=Date.now()+30000;while(Date.now()<limit){if(await fn())return;await page.waitForTimeout(40);}throw Error('Timed out: '+label);};
  const capture=async(id,label=id)=>{const element=page.getByTestId(id);await element.waitFor();const text=await element.innerText();assert(text.includes(exact),label+' should reproduce exact fraction');report.surfaces.push({label,test_id:id,text});};
  await page.goto(base);await page.getByTestId('run-chooser').waitFor();
  report.assets=await page.locator('script[src]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('src')));
  await page.locator(`.sidebar button.run-card[data-run-id="${runId}"]`).click();
  await until(async()=>{const a=await app();return a.view?.run_id===runId&&!a.view_pending&&a.viewer_load.phase==='ready'&&a.view.time===exact;},'exact live-follow view');
  assert.equal((await app()).mode,'live');
  await capture('simulation-status','Execution clock');await capture('viewer-status','Live-follow clock');
  assert.equal(await page.getByTestId('simulation-status').getAttribute('data-time'),exact);
  assert.equal(await page.getByTestId('viewer-status').getAttribute('data-time'),exact);
  report.exact_editor=await page.getByTestId('replay-exact-time').inputValue();assert.equal(report.exact_editor,exact);
  await page.screenshot({path:path.join(output,'raw-live-clocks.png'),fullPage:true});
  await page.getByTestId('tab-statistics').click();
  await until(async()=>((await page.getByTestId('statistics-source').innerText().catch(()=>''))).includes(exact),'statistics source');
  await capture('statistics-source');await capture('statistics-resource-cursor');await capture('chart-source');
  await page.getByTestId('population-table-toggle').click();
  const endpoint=page.getByTestId('population-table').locator('tbody tr').last().getByRole('button');
  assert.equal(await endpoint.innerText(),exact);report.surfaces.push({label:'Population endpoint table button',text:await endpoint.innerText(),accessible_name:await endpoint.getAttribute('aria-label')});
  await page.screenshot({path:path.join(output,'raw-statistics.png'),fullPage:true});
  await endpoint.click();
  await until(async()=>{const a=await app();return a.mode==='replay'&&a.view.time===exact&&!a.view_pending;},'exact sample selection');
  report.exact_sample_navigation={time:(await app()).view.time,revision:(await app()).view.revision};
  await page.getByTestId('replay-return-live').click();
  await until(async()=>(await app()).mode==='live','return live');
  await page.getByTestId('tab-events').click();
  await until(async()=>((await page.getByTestId('events-cursor').innerText().catch(()=>''))).includes(exact),'events source');
  await capture('events-cursor');await capture('events-status');
  report.event_labels=await page.getByTestId('event-time-label').allTextContents();
  assert(report.event_labels.length>0);assert(report.event_labels.every(v=>!v.includes('/')));
  await page.getByTestId('tab-cohorts').click();
  await until(async()=>((await page.getByTestId('cohorts-cursor').innerText().catch(()=>''))).includes(exact),'cohorts source');
  await capture('cohorts-cursor');await capture('cohort-create-reference');
  const card=page.getByTestId('cohort-card');await card.waitFor();assert((await card.innerText()).includes(exact));report.surfaces.push({label:'Saved cohort reference',text:await card.innerText()});
  await page.getByTestId('tab-comparison').click();
  for(const id of [runId,otherId])await page.locator(`[data-testid="comparison-choice"][data-run-id="${id}"]`).check();
  await until(async()=>((await page.getByTestId('comparison-source').innerText().catch(()=>''))).includes(exact),'comparison source');
  await capture('comparison-source');await capture('comparison-sources');
  assert((await page.getByTestId('comparison-samples').innerText()).includes(exact));
  report.surfaces.push({label:'Comparison endpoint time cells',text:await page.getByTestId('comparison-samples').locator(`tr[data-time="${exact}"]`).allTextContents()});
  await page.getByTestId('comparison-source').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'raw-comparison.png'),fullPage:true});
  report.execution_commands=report.requests.filter(r=>r.method==='POST'&&r.url.endsWith('/commands'));
  assert.deepEqual(report.execution_commands,[]);assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(error){report.error=String(error.stack||error).slice(0,5000);if(page)try{await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}catch{}throw error;}
 finally{fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
