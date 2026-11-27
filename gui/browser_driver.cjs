/* Actual-browser acceptance transport. Every action goes through a visible control. */
const {chromium,firefox}=require('playwright');
const readline=require('node:readline');
const fs=require('node:fs');
const {executeExport}=require('./browser_exports.cjs');
const measurements=require('./browser_measurements.cjs');
const transport=require('./browser_transport.cjs');
const commands=require('./browser_commands.cjs');
let browser,context,page;const pages=new Map(),log=[];
async function sync(){await page.waitForFunction(()=>{const s=window.__zombieInspection?.app;return s&&!s.pending&&!s.view_pending&&(s.perspective==='agent'?!!s.observation:!!s.view);});await page.waitForTimeout(60);}
async function command(m){
 if(['command_prepare','intervention_form'].includes(m.op))return commands.prepare(page,m,log);
 if(m.op==='click'&&['command-submit','command-retry'].includes(m.testid))return commands.click(page,m,log);
 if(['transport','release_transport','projection_fixture','observer_load'].includes(m.op))return transport.executeTransport(page,m);
 if(['export_form','await_export','export_job'].includes(m.op))return executeExport(page,m);
 if(m.op==='keyboard_workflow')return measurements.keyboardWorkflow(page,m,log);
 if(m.op==='benchmark')return measurements.benchmark(page,m,log);
 if(m.op==='accessibility')return measurements.accessibility(page);
 if(m.op==='open'){
  browser=await (m.engine==='firefox'?firefox:chromium).launch({headless:true,...(m.engine==='firefox'?{}:{executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',args:['--no-sandbox']})});
  context=await browser.newContext({viewport:m.viewport||{width:1440,height:1000},reducedMotion:m.reduced_motion?'reduce':'no-preference',baseURL:m.url,...(fs.existsSync(require('node:os').homedir()+'/.cache/ms-playwright/ffmpeg-1011/ffmpeg-linux')?{recordVideo:{dir:m.artifacts}}:{})});
  await context.tracing.start({screenshots:true,snapshots:true,sources:true});page=await context.newPage();await transport.install(page);pages.set('main',page);await page.goto(m.url);await page.waitForFunction(()=>!!window.__zombieInspection?.app);
  if(m.run_id){await page.locator(`.sidebar button.run-card[data-run-id="${m.run_id}"]`).click();await sync();}
  return {version:browser.version(),engine:m.engine||'chromium',viewport:page.viewportSize(),device_scale:await page.evaluate(()=>devicePixelRatio),application_assets:await page.locator('script[src]').evaluateAll(elements=>elements.map(element=>element.src))};
 }
 if(m.op==='open_tab'){
  const identity=await page.evaluate(()=>window.__zombieInspection?.app?.run_id);
  const p=await context.newPage();pages.set(m.name,p);await p.goto(page.url());
  await p.waitForFunction(()=>!!window.__zombieInspection?.app);
  // Each new browser tab opens on the chooser. Reproduce the user's explicit
  // selection for multi-tab control checks instead of relying on auto-loading.
  if(identity){await p.locator(`.sidebar button.run-card[data-run-id="${identity}"]`).click();await p.waitForFunction(()=>!!window.__zombieInspection?.app?.view);}
  return {};
 }
 if(m.op==='select_tab'){page=pages.get(m.name);await page.bringToFront();return {};}
 if(m.op==='select_run'){await page.locator(`.sidebar button.run-card[data-run-id="${m.run_id}"]`).click();await sync();return {};}
 if(m.op==='close'){if(context){await context.tracing.stop({path:m.trace_path});await context.close();}if(browser)await browser.close();return {};}
 if(m.op==='peek')return page.evaluate(()=>({run_id:window.__zombieInspection.app.run_id,mode:window.__zombieInspection.app.mode,perspective:window.__zombieInspection.app.perspective}));
 if(m.op==='capture'){if(await page.getByTestId('config-launch').count())await page.waitForFunction(()=>!window.__zombieInspection.configuration.start_disabled||window.__zombieInspection.configuration.issues.length>0);else{await sync();if(m.expected_revision)await page.waitForFunction(revision=>BigInt(window.__zombieInspection.app.view?.revision??-1)>=BigInt(revision),m.expected_revision);if(['timeline','cohorts'].includes(m.what))await page.waitForFunction(what=>{const a=window.__zombieInspection.app,cursor=what==='cohorts'?a.cohorts_cursor:a.auxiliary_cursor;return cursor?.revision===a.view?.revision&&cursor?.time===a.view?.time;},m.what);}await page.screenshot({path:m.path,fullPage:true});return await page.evaluate(()=>({...window.__zombieInspection,export_job:window.__zombieExportInspection,recovery_command:window.__zombieCommandInspection,legend_tokens:[...document.querySelectorAll('[data-status-token]')].map(e=>e.dataset.statusToken),glyph_semantics:document.querySelector('[data-glyph-semantics]')?.dataset.glyphSemantics,statistics_watermark_label:document.querySelector('.statistics .tag')?.textContent,cohort_overlap_label:document.querySelector('.cohort-panel')?.textContent?.match(/Cohorts may overlap/)?.[0]}));}
 if(m.op==='sync'||m.op==='await_view'){await sync();if(await page.evaluate(()=>window.__zombieInspection.app.mode==='replay')){await page.waitForFunction(()=>window.__zombieInspection.app.view.time===window.__zombieInspection.app.seek&&window.__zombieInspection.app.metrics_cursor?.time===window.__zombieInspection.app.view.time&&window.__zombieInspection.app.metrics_cursor?.revision===window.__zombieInspection.app.view.revision);return {};}if(m.revision)try{await page.waitForFunction(revision=>BigInt(window.__zombieInspection.app.view?.revision??-1)>=BigInt(revision),m.revision);}catch(error){throw Error(error.message+' expected '+m.revision+' actual '+JSON.stringify(await page.evaluate(()=>window.__zombieInspection.app)));}return {};}
 if(m.op==='click'){
  let testid=m.testid;if(testid==='run-start'&&await page.getByTestId('config-launch').count())testid='config-launch';if(testid==='run-checkpoint')page.once('dialog',dialog=>dialog.accept(m.name||''));if(testid.startsWith('layer-')&&!await page.getByTestId(testid).isVisible())await page.locator('.layers summary').click();const target=page.getByTestId(testid).first();await target.waitFor();log.push({action:'click',testid:m.testid,text:await target.innerText()});await target.click();
  if(testid==='config-launch')await page.waitForFunction(()=>!!window.__zombieInspection.app.view&&!document.querySelector('[data-testid="config-launch"]'));else if(m.testid.startsWith('run-'))await page.waitForFunction(()=>!window.__zombieInspection.app.pending);
  return await page.evaluate(()=>window.__zombieInspection);
 }
 if(m.op==='fill'){
  const aliases={'config-human_count':'config-population.humans'};let testid=aliases[m.testid]||m.testid;
  if(!await page.getByTestId(testid).count()&&testid.startsWith('config-')){
   const control=page.getByLabel('Advanced configuration JSON');const draft=JSON.parse(await control.inputValue());const path=testid.slice(7).replace(/^human_roles\./,'population.human_roles.').split('.');let node=draft;for(const key of path.slice(0,-1))node=node[key]??={};node[path.at(-1)]=Number.isFinite(Number(m.value))?Number(m.value):m.value;
   await control.fill(JSON.stringify(draft,null,2));log.push({action:'fill',testid,actual_control:'Advanced configuration JSON',value:m.value});return {};
  }
  const target=page.getByTestId(testid);log.push({action:'fill',testid,value:String(m.value)});
  if(await target.evaluate(e=>e.tagName==='SELECT')){
   const value=String(m.value);
   if(['config-human_model','config-zombie_model'].includes(testid)&&!(await target.locator('option').evaluateAll(options=>options.map(option=>option.value))).includes(value)){
    // A requested registry ID, alias or artifact is still an exact text entry;
    // the guided selector exposes it through its explicit advanced control.
    await target.selectOption('__advanced__');await page.getByTestId(testid+'-advanced').fill(value);
   }else await target.selectOption(value);
  }else await target.fill(String(m.value));return {};
 }
 if(m.op==='import_config'){await page.getByTestId('config-edit-new').click();await page.getByText('Advanced configuration · JSON',{exact:true}).click();const file=m.path;await page.waitForFunction(()=>{const input=document.querySelector('[data-testid="config-import"]');return input&&!input.matches(':disabled');});await page.getByTestId('config-import').setInputFiles(file);await page.waitForFunction(()=>window.__zombieInspection.configuration.draft.preset!==undefined);return {};}
 if(m.op==='export_import_config'){await page.getByTestId('config-export-format').selectOption(m.format);const pending=page.waitForEvent('download');await page.getByTestId('config-export').click();const downloaded=await pending;const saved=m.path;await downloaded.saveAs(saved);await page.getByTestId('config-import').setInputFiles(saved);await page.waitForTimeout(100);return {path:saved};}
 if(m.op==='cohort_create'){await page.getByTestId('tab-cohorts').click();await page.getByTestId('cohort-name').fill(m.name);await page.getByTestId('cohort-mode').selectOption(m.mode);await page.getByTestId('cohort-status').selectOption(m.predicate.status||'');await page.getByTestId('cohort-type').selectOption(m.predicate.type||'');await page.getByTestId('cohort-include-dead').setChecked(m.include_dead!==false);await page.getByTestId('cohort-save').click();await page.waitForFunction(name=>window.__zombieInspection.app.cohorts.some(c=>c.definition.name===name),m.name);return {};}
 if(m.op==='select_observation'){await page.getByTestId('tab-world').click();await page.getByTestId('agent-search').fill(m.agent);await page.getByTestId('agent-search-select').first().click();await page.getByTestId('perspective').selectOption('agent');await sync();return {};}
 if(m.op==='chart_select'){await page.getByTestId('tab-statistics').click();await page.getByTestId('chart-time').fill(String(m.time));await page.getByTestId('chart-select').click();await sync();return {};}
 if(m.op==='timeline_filter'){if(m.agent){await page.getByTestId('tab-world').click();await page.getByTestId('agent-search').fill(m.agent);await page.getByTestId('agent-search-select').first().click();}await page.getByTestId('tab-events').click();await page.getByTestId('timeline-filter').fill(m.event_type||'');return {};}
 if(m.op==='timeline_select'){await page.getByTestId('tab-events').click();await page.getByTestId('timeline-filter').fill(m.event_type||'');const facts=await page.evaluate(()=>window.__zombieInspection.app);const occurrence=Object.values(facts.timeline_occurrences).find(o=>o.intent_id===m.intent);const records=facts.shownEvents;const index=records.findIndex(e=>(e.occurrence||e.action_id)===occurrence.id);if(index<0)throw Error('Recorded timeline occurrence not visible');await page.getByTestId('timeline-first-event').nth(index).click();return {};}
 if(m.op==='elapse_wall_time'){await page.waitForTimeout(m.milliseconds);return {};}
 if(m.op==='disconnect'){await context.setOffline(true);return {};}
 if(m.op==='reconnect'){await context.setOffline(false);await sync();return {};}
 if(m.op==='capture_transport')return await page.evaluate(()=>window.__zombieInspection.transport);
 throw Error(`Browser operation not yet bound: ${m.op}`);
}
process.on('SIGTERM',async()=>{if(browser)await browser.close();process.exit();});
const lines=readline.createInterface({input:process.stdin});(async()=>{for await(const line of lines){try{const m=JSON.parse(line),result=await command(m);process.stdout.write(JSON.stringify({ok:true,result,log})+'\n');}catch(e){process.stdout.write(JSON.stringify({ok:false,error:e.stack})+'\n');}}if(browser)await browser.close();})();
