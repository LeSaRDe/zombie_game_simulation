/* Readable guide screenshots and the actual small-run workflow. No production hooks. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const [base,output,images]=process.argv.slice(2);fs.mkdirSync(images,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome'});
 const report={passed:false,browser:browser.version(),steps:[],screenshots:[],errors:[]};let page;
 const progress=()=>fs.writeFileSync(path.join(output,'progress.json'),JSON.stringify(report,null,2));
 try{
  page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100},locale:'en-US'});page.on('pageerror',e=>report.errors.push(String(e)));
  const until=async(fn,label,timeout=60000)=>{const end=Date.now()+timeout;while(Date.now()<end){const value=await fn();if(value)return value;await page.waitForTimeout(40);}throw Error('Timed out: '+label);};
  const app=()=>page.evaluate(()=>window.__zombieInspection.app);
  const call=async(route)=>{const response=await page.request.get(route);assert(response.ok());return response.json();};
  const row=async id=>(await call('/api/runs')).find(x=>x.id===id);
  const seconds=value=>{const [n,d=1]=String(value).split('/').map(Number);return n/d;};
  const screenshot=async(name,caption,locator)=>{
   await page.evaluate(()=>{window.scrollTo(0,0);document.querySelector('.config-body')?.scrollTo(0,0);});
   const target=locator||page;await target.screenshot({path:path.join(images,name+'.png')});
   report.screenshots.push({file:'docs/images/user-guide/'+name+'.png',caption});progress();
  };
  const open=async()=>{await page.getByRole('button',{name:/New experiment/}).click();await page.waitForFunction(()=>window.__zombieInspection.configuration.load_state?.phase==='ready');};
  const field=(key)=>page.getByTestId('config-'+key);
  const blur=()=>page.locator('#config-title').click();
  const submit=async(id,route)=>{const wait=page.waitForResponse(r=>new URL(r.url()).pathname===route&&r.request().method()==='POST');await page.getByTestId(id).click();const r=await wait;const data=await r.json();assert(r.ok(),JSON.stringify(data));if(id!=='config-launch')await until(async()=>!await page.getByTestId('config-validate').isDisabled(),'configuration idle',180000);return data;};
  const create=async({seed,infected=0,incubation=300,preview=false})=>{
   await open();await page.getByTestId('config-preset').selectOption('small');
   await field('seed').fill(String(seed));await blur();await field('horizon').fill('60');await blur();assert.equal(await field('human_model').inputValue(),'defaultHuman/v1');assert.equal(await field('zombie_model').inputValue(),'defaultZombie/v1');
   await page.getByLabel('Worker selection',{exact:true}).selectOption('manual');await field('execution.workers').fill('1');await blur();
   if(infected){await field('population.infected').fill(String(infected));await blur();await field('incubation_duration').fill(String(incubation));await blur();}
   const valid=await submit('config-validate','/api/config/validate');assert(!Object.hasOwn(valid.resolved,'human_model'));assert(!Object.hasOwn(valid.resolved,'zombie_model'));assert.equal(valid.resolved.population.humans,16);assert.equal(valid.resolved.population.zombies,4);
   if(preview){const data=await submit('config-preview','/api/config/preview');assert.equal(Object.keys(data.view.state.agents).length,20);report.preview={population:20,sampler:data.resolved.placement.sampler};await screenshot('02-small-preview','Small 20 agents, seed 123, horizon 60 s, one worker; valid isolated placement preview.',page.getByRole('dialog',{name:'Configure your world'}));}
   const created=await submit('config-launch','/api/runs');const id=created.run_id;
   await until(async()=>{const a=await app();return a?.run_id===id&&a.view?.state&&a.view.metrics.populations.total===20;},'readable world');
   await until(async()=>await page.getByTestId('run-pause').isEnabled(),'initial start acknowledgement');
   await page.getByTestId('run-pause').click();await until(async()=>(await row(id)).status==='paused','pause');
   report.steps.push({action:'GUI validate, optional preview, launch, readable world, Pause run',run_id:id,seed,infected,incubation,horizon:60,workers:1,human_model:'Inherited HumanDefaultModel; configuration key omitted'});progress();return id;
  };
  const advance=async(id,target)=>{await page.getByTestId('run-pacing').selectOption('1');await until(async()=>(await row(id)).frontier.pacing===1,'pace applied');await page.getByTestId('run-start').click();await until(async()=>seconds((await row(id)).frontier.time)>=target,'continued simulation time');await page.getByTestId('run-pause').click();await until(async()=>(await row(id)).status==='paused','paused again');await until(async()=>{const a=await app(),r=await row(id);return a.view?.revision===String(r.frontier.revision);},'paused world display');};
  const select=async id=>{await page.locator(`.run-card[data-run-id="${id}"]`).click();await until(async()=>{const a=await app();return a.run_id===id&&a.view?.state;},'selected readable run');};
  const seek=async time=>{await page.getByTestId('replay-exact-time').fill(String(time));await page.getByTestId('replay-seek').click();await until(async()=>{const a=await app();return a.mode==='replay'&&seconds(a.view?.time)===Number(time);},'replay time');};
  await page.goto(base);await page.getByTestId('run-chooser').waitFor();await screenshot('01-home','A clean workspace opens on the chooser; opening the service has not created a simulation.');
  const first=await create({seed:123,preview:true});await advance(first,6);
  await page.getByTestId('run-step-transition').click();await until(async()=>await page.getByTestId('run-step-transition').isEnabled(),'transition step applied');
  await page.getByTestId('tab-world').click();await page.getByTestId('agent-search-select').first().click();await screenshot('03-world-paused','Paused Small20 run with a selected identity and execution controls.');
  report.first=await row(first);report.steps.push({action:'GUI 1× pace, Continue, Pause, Step transition, select identity',run_id:first,time:report.first.frontier.time});progress();
  await page.getByTestId('tab-statistics').click();await until(async()=>{const a=await app();return a.metrics_state?.phase==='ready'&&a.samples.length>1;},'statistics data');
  await until(async()=>await page.getByTestId('population-chart').evaluate(n=>Boolean(n.data?.length)),'statistics chart');
  await screenshot('04-statistics','Statistics curves for the first paused run; source time and revision identify the measurements.',page.locator('.main-panel'));
  const second=await create({seed:321,infected:2,incubation:3});await advance(second,6);
  await seek(0);await page.getByTestId('tab-cohorts').click();await until(async()=>(await app()).cohorts_state?.phase==='ready','cohorts ready');
  for(const [name,mode]of [['Humans at the reference','fixed'],['Humans at each time','dynamic']]){
   await page.getByTestId('cohort-example-humans').click();await page.getByTestId('cohort-name').fill(name);await page.getByTestId('cohort-mode').selectOption(mode);await page.getByTestId('cohort-save').click();await until(async()=>(await app()).cohorts.some(c=>c.definition.name===name),'saved '+name);
  }
  await page.getByTestId('replay-return-live').click();await until(async()=>{const a=await app();return a.mode==='live'&&a.cohorts_state?.phase==='ready'&&seconds(a.cohorts_state.data?.cursor.time)>=6;},'current cohort measurements');
  report.cohorts=(await app()).cohorts;assert.equal(report.cohorts.find(c=>c.definition.mode==='fixed').denominator,16);assert.equal(report.cohorts.find(c=>c.definition.mode==='dynamic').denominator,14);
  const form=page.locator('details').filter({has:page.getByTestId('cohort-name')});if(await form.count()&&await form.evaluate(n=>n.open))await form.locator('summary').first().click();
  await screenshot('05-cohorts','Second run: two initially infected humans converted. The fixed group retains 16 identities; the dynamic Human group has 14.',page.locator('.cohort-grid'));report.steps.push({action:'GUI replay time zero; create fixed and dynamic Human cohorts; return live',run_id:second});progress();
  await page.getByTestId('tab-events').click();await until(async()=>await page.getByTestId('timeline-first-event').count()>0,'events displayed');
  await page.getByTestId('timeline-filter').fill('conversion');await until(async()=>await page.getByTestId('timeline-first-event').count()>0,'conversion search matches');await page.getByTestId('timeline-first-event').filter({has:page.getByText('conversion',{exact:true})}).first().click();await page.getByTestId('event-after').waitFor();await until(async()=>{const a=await app();return a.mode==='replay'&&a.viewer_load.phase==='ready'&&a.events_state.phase==='ready'&&a.events_cursor?.time===a.view.time&&a.events_cursor?.revision===a.view.revision;},'selected conversion view and Events source settle');await screenshot('06-events','Second run: search the loaded Events page for conversion; select a record to inspect its exact causal boundaries.',page.locator('.workspace'));
  report.events={matches:await page.getByTestId('timeline-first-event').count(),detail:await page.locator('.event-detail pre').innerText()};
  await page.getByTestId('event-before').click();await until(async()=>(await app()).mode==='replay','before event replay');await page.getByTestId('replay-return-live').click();await page.getByTestId('tab-comparison').click();await page.locator(`[data-testid="comparison-choice"][data-run-id="${first}"]`).check();
  await until(async()=>{const c=await page.evaluate(()=>window.__zombieInspection.comparison);return c.phase==='ready'&&!c.stale&&c.data?.status==='ready'&&c.data.runs.length===2;},'comparison data');
  await page.getByTestId('comparison-metric').selectOption('zombies');await until(async()=>await page.getByTestId('comparison-chart').evaluate(n=>n.data?.length===2),'comparison chart');await screenshot('07-comparison','Two runs compared as living zombie counts over the common recorded interval.',page.locator('.main-panel'));report.comparison=await page.evaluate(()=>window.__zombieInspection.comparison.data);report.steps.push({action:'GUI loaded-page Events search, select causal record, Before transition, return live, compare two runs',runs:[first,second]});progress();
  const downloadWait=page.waitForEvent('download');await page.getByTestId('comparison-export').click();const download=await downloadWait;await download.saveAs(path.join(output,'comparison.csv'));
  await page.getByTestId('run-stop').click();await until(async()=>{const r=await row(second);return r.status==='stopped'&&r.resource_status.cleanup_complete;},'Stop & save releases worker');report.second=await row(second);
  await select(first);await page.getByTestId('run-stop').click();await until(async()=>{const r=await row(first);return r.status==='stopped'&&r.resource_status.cleanup_complete;},'first Stop & save releases worker');await until(async()=>{const a=await app();return !a.pending&&a.run?.status==='stopped'&&a.run?.resource_status?.cleanup_complete&&await page.getByTestId('run-group-saved').locator('.run-card').count()===2;},'saved status and sidebar acknowledged');await page.getByTestId('tab-world').click();await screenshot('08-saved','Stop & save releases the worker and lists the resumable run under Saved / Completed.');report.steps.push({action:'GUI Stop & save both runs; worker cleanup complete'});
  await open();await page.getByTestId('config-preset').selectOption('baseline');const baseline=await submit('config-validate','/api/config/validate');assert.equal(baseline.resolved.population.humans,800);assert.equal(baseline.resolved.population.zombies,200);
  const baselineStart=Date.now();const preview=await submit('config-preview','/api/config/preview');assert.equal(Object.keys(preview.view.state.agents).length,1000);const state=preview.view.state,agents=Object.values(state.agents),rect=f=>Array.isArray(f)?f:[f.xmin,f.ymin,f.xmax,f.ymax];
  const inside=(p,f,strict=false)=>{const [x0,y0,x1,y1]=rect(f);return strict?p.x>x0&&p.x<x1&&p.y>y0&&p.y<y1:p.x>=x0&&p.x<=x1&&p.y>=y0&&p.y<=y1;};
  for(const a of agents){assert(a.x>=0&&a.x<=state.world.length&&a.y>=0&&a.y<=state.world.width);for(const b of Object.values(state.barriers)){if(b.type==='Gate'&&b.mode==='OPEN')continue;assert(!inside(a,b.footprint));}if(a.type==='Zombie')for(const shelter of Object.values(state.shelters))assert(!inside(a,shelter.interior,true));}
  let pairChecks=0;for(let i=0;i<agents.length;i++)for(let j=i+1;j<agents.length;j++){const a=agents[i],b=agents[j],minimum=a.type===b.type?preview.resolved.placement.minimum_separation:preview.resolved.placement.cross_type_separation;assert(Math.hypot(a.x-b.x,a.y-b.y)>=minimum);pairChecks++;}
  report.baseline={preview_seconds:(Date.now()-baselineStart)/1000,population:1000,placement:preview.resolved.placement,initialization:state.initialization,strict_position_checks:1000,strict_pair_separation_checks:pairChecks};await screenshot('09-baseline-preview','Ontology baseline preview: 1,000 identities with the approved approximate sampler; no baseline simulation was launched.',page.getByRole('dialog',{name:'Configure your world'}));await page.getByRole('button',{name:'Close configuration',exact:true}).click();
  assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(e){report.error=String(e.stack||e);if(page)await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});throw e;}
 finally{fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));progress();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
