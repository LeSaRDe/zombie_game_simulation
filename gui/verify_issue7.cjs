const {fillExact}=require('./verification_time_helpers.cjs');
/* I07: real cohort creation and history inspection, checked against full snapshots. */
const {chromium, firefox} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');

(async () => {
  const [base, output, encodedRuns, engine = 'chromium'] = process.argv.slice(2);
  const runs = JSON.parse(encodedRuns);
  const browser = await (engine === 'firefox' ? firefox : chromium).launch({headless:true, ...(engine === 'firefox' ? {} : {executablePath:'/usr/bin/google-chrome'})});
  const report = {passed:false, engine, browser:browser.version(), checks:[], captures:[], commands:[], read_only_windows:[], errors:[]};
  let page;
  const cleanup = [];
  try {
    page = await browser.newPage({baseURL:base, viewport:{width:1440,height:1100}, locale:'en-US'});
    page.on('pageerror', error => report.errors.push(String(error)));
    const seconds = value => { const [n,d=1] = String(value).split('/').map(Number); return n/d; };
    const until = async (fn,label,timeout=40000) => {
      const end = Date.now()+timeout;
      while (Date.now()<end) { if (await fn()) return; await page.waitForTimeout(30); }
      throw Error(`Timed out: ${label}`);
    };
    const call = async (url,body) => {
      const response = body === undefined ? await page.request.get(url) : await page.request.post(url,{data:body});
      assert(response.ok(),`${url}: ${response.status()} ${await response.text()}`);
      return response.json();
    };
    const app = () => page.evaluate(() => window.__zombieInspection.app);
    const audit = async run => (await call('/__issue7/audit')).find(row => row.id === run);
    const command = async (run,operation,extra={}) => {
      const current = (await call('/api/runs')).find(row => row.id === run);
      let reply = await call(`/api/runs/${run}/commands`,{operation,command_id:randomUUID(),expected_generation:current.generation,...extra});
      await until(async () => { if (reply.status === 'pending') reply = await call('/api/commands/'+reply.command_id); return reply.status !== 'pending'; },operation,90000);
      report.commands.push({run,operation,status:reply.status,time:reply.time,revision:reply.revision});
      assert.equal(reply.status,'applied',JSON.stringify(reply));
      return reply;
    };
    const aligned = async (run,time,revision) => until(async () => {
      const state = await app(), cursor = state.cohorts_cursor;
      return state.run_id === run && state.cohorts_state?.phase === 'ready' && cursor?.revision === state.view?.revision
        && seconds(cursor?.time) === seconds(state.view?.time) && (time === undefined || seconds(state.view.time) === seconds(time))
        && (revision === undefined || String(state.view.revision) === String(revision));
    },`cohorts aligned ${run}/${time ?? 'current'}`);
    const select = async (run,wait=true) => {
      await page.locator(`.sidebar button.run-card[data-run-id="${run}"]`).click();
      await page.getByTestId('tab-cohorts').click();
      if (wait) await aligned(run);
    };
    const seek = async time => {
      await fillExact(page,'replay-exact-time',time);
      await page.getByTestId('replay-seek').click();
    };
    const capture = async (label,run) => {
      await aligned(run);
      const state = await app(), data = state.cohorts_state.data;
      const oracle = await call('/__issue7/oracle',{run_id:run,data});
      assert(oracle.passed);
      assert.equal(await page.getByTestId('cohort-card').count(),data.cohorts.length);
      for (const row of data.cohorts) {
        const card = page.locator(`[data-cohort-id="${row.definition.id}"]`);
        assert.equal(await card.getByTestId('cohort-count').innerText(),String(row.denominator));
        assert.deepEqual((await card.getByTestId('cohort-members').locator('code').allTextContents()).sort(),[...row.members].sort());
        assert.equal(await card.getByTestId('cohort-reference').locator('.time-value').getAttribute('data-exact-time'),String(row.definition.reference_time));
        assert((await card.getByTestId('cohort-reference').innerText()).endsWith(` · revision ${row.definition.reference_revision}`));
        assert.equal(await card.getByTestId('cohort-measurement').locator('.time-value').getAttribute('data-exact-time'),String(data.cursor.time));
        assert((await card.getByTestId('cohort-measurement').innerText()).endsWith(` · revision ${data.cursor.revision}`));
        assert.equal(await card.getByTestId('cohort-populations').innerText(),`${row.populations.healthy} healthy · ${row.populations.infected} infected · ${row.populations.zombies} zombies · ${row.populations.dead} dead`);
        for (const metric of ['life','stamina']) {
          const value = card.getByTestId(`cohort-mean-${metric}`);
          assert.equal(await value.getAttribute('data-denominator'),String(row[`mean_${metric}_denominator`]));
          assert.equal(await value.locator('strong').innerText(),row[`mean_${metric}`] === null ? '—' : row[`mean_${metric}`].toLocaleString('en-US',{maximumFractionDigits:2}));
        }
      }
      const captured = {label,run_id:run,time:data.cursor.time,revision:data.cursor.revision,cohort_count:data.cohorts.length,oracle};
      report.captures.push(captured);
      return captured;
    };
    const setFilters = async ({name,mode='fixed',type='Human',status='',includeDead=true,region='',role='',model=''}) => {
      await page.getByTestId('cohort-example-humans').click();
      await page.getByTestId('cohort-name').fill(name);
      await page.getByTestId('cohort-mode').selectOption(mode);
      await page.getByTestId('cohort-type').selectOption(type);
      await page.getByTestId('cohort-status').selectOption(status);
      await page.getByTestId('cohort-include-dead').setChecked(includeDead);
      if (region || role || model) {
        if(!await page.getByTestId('cohort-region').isVisible())await page.getByText('Optional role, model or region filters',{exact:true}).click();
        await page.getByTestId('cohort-region').fill(region);
        await page.getByTestId('cohort-role').selectOption(role);
        await page.getByTestId('cohort-model').fill(model);
      }
    };
    const create = async (definition,run) => {
      await setFilters(definition);
      await page.getByTestId('cohort-save').click();
      await until(async () => (await app()).cohorts.some(row => row.definition.name === definition.name),`created ${definition.name}`);
      await aligned(run);
      const row = (await app()).cohorts.find(row => row.definition.name === definition.name);
      assert.match(await page.getByTestId('cohort-created').innerText(),new RegExp(definition.name));
      assert((await page.locator(`[data-cohort-id="${row.definition.id}"]`).getAttribute('class')).includes('cohort-card-created'));
      return row;
    };
    const cohortPattern = '**/api/runs/*/cohorts?*';
    const postPattern = '**/api/runs/*/cohorts';

    let releaseInitial, initialHit=false;
    const initialHold = new Promise(resolve => releaseInitial=resolve); cleanup.push(() => releaseInitial());
    await page.route(cohortPattern,async route => {initialHit=true;await initialHold;try {await route.continue();} catch {}});
    await page.goto(base); await select(runs.small,false);
    await until(async () => initialHit && (await app()).cohorts_state.phase === 'loading','initial cohort loading');
    assert.match(await page.getByTestId('cohorts-status').innerText(),/Loading Cohorts/);
    assert.equal(await page.getByTestId('cohort-card').count(),0);
    releaseInitial(); await page.unroute(cohortPattern); await aligned(runs.small,'0');
    assert.match(await page.getByTestId('cohorts-status').innerText(),/No cohorts have been created/);
    assert.equal(await page.getByTestId('cohort-name').inputValue(),'All humans');
    assert.equal(await page.getByTestId('cohort-type').inputValue(),'Human');
    assert.equal(await page.getByTestId('cohort-status').inputValue(),'');
    assert.equal(await page.getByTestId('cohort-include-dead').isChecked(),true);
    await capture('small-no-cohort-definitions',runs.small);
    await page.screenshot({path:path.join(output,'initial-cohorts.png'),fullPage:true});
    const beforeCreate = await audit(runs.small);

    await page.getByTestId('cohort-name').fill(''); await page.getByTestId('cohort-save').click();
    assert.match(await page.getByTestId('cohort-form-error').innerText(),/highlighted fields/);
    assert.equal(await page.getByTestId('cohort-name').inputValue(),'');
    assert.equal(await page.getByTestId('cohort-name').getAttribute('aria-invalid'),'true');
    await setFilters({name:'Region invalid',region:'5, 2, 1, 4'}); await page.getByTestId('cohort-save').click();
    assert.equal(await page.getByTestId('cohort-region').inputValue(),'5, 2, 1, 4');
    assert.equal(await page.getByTestId('cohort-region').getAttribute('aria-invalid'),'true');
    assert.equal((await app()).cohorts.length,0);
    await setFilters({name:'All humans fixed'});
    let postCount=0, releaseCreate;
    const createHold=new Promise(resolve=>releaseCreate=resolve); cleanup.push(()=>releaseCreate());
    await page.route(postPattern,async route=>{postCount++;await createHold;try{await route.continue();}catch{}});
    await page.getByTestId('cohort-save').click();await until(async()=>postCount===1,'one pending create');
    assert.equal(await page.getByTestId('cohort-save').isDisabled(),true);
    await page.getByTestId('cohort-save').evaluate(button=>{button.click();button.click();});
    await page.waitForTimeout(100);assert.equal(postCount,1);
    releaseCreate();await page.unroute(postPattern);
    await until(async()=>(await app()).cohorts.some(row=>row.definition.name==='All humans fixed'),'fixed cohort created');await aligned(runs.small);
    assert.match(await page.getByTestId('cohort-created').innerText(),/All humans fixed/);
    assert.equal((await app()).cohorts[0].denominator,16);
    await create({name:'All humans dynamic',mode:'dynamic'},runs.small);
    const empty=await create({name:'Initially infected',status:'INFECTED'},runs.small);assert.equal(empty.denominator,0);
    assert.match(await page.locator(`[data-cohort-id="${empty.definition.id}"]`).getByTestId('cohort-empty').innerText(),/valid result/);
    await page.getByTestId('cohort-clear-filters').click();
    assert.equal(await page.getByTestId('cohort-type').inputValue(),'');assert.equal(await page.getByTestId('cohort-status').inputValue(),'');
    await page.getByTestId('cohort-name').fill('Everyone');await page.getByTestId('cohort-save').click();
    await until(async()=>(await app()).cohorts.some(row=>row.definition.name==='Everyone'),'unfiltered cohort');await aligned(runs.small);
    assert.equal((await app()).cohorts.find(row=>row.definition.name==='Everyone').denominator,20);
    await capture('small-created-overlapping-and-empty-cohorts',runs.small);
    assert.match(await page.locator('.cohort-panel').innerText(),/Cohorts may overlap/);
    const afterCreate=await audit(runs.small);assert.deepEqual(afterCreate,beforeCreate);report.read_only_windows.push({label:'create-and-invalid-drafts',before:beforeCreate,after:afterCreate});
    report.checks.push('Loading, no definitions and valid zero membership are distinct; guided defaults, field errors, retained drafts, duplicate-submit guard and created-card feedback work without changing simulation history');
    await page.screenshot({path:path.join(output,'created-cohorts.png'),fullPage:true});

    const zero=(await app()).cohorts_cursor;const step=await command(runs.small,'step');await aligned(runs.small,step.time,step.revision);
    assert.equal(seconds(step.time),0);assert(BigInt(step.revision)>BigInt(zero.revision));await capture('same-time-new-revision',runs.small);
    const oldCollection=(await app()).cohorts_state.data;
    await page.route(cohortPattern,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Controlled cohort read failure'})}));
    const half=await command(runs.small,'advance',{time:'0.5'});
    await until(async()=>{const s=await app();return s.view?.revision===half.revision&&s.cohorts_state.phase==='failed';},'cohort failed while world advances');
    assert.deepEqual((await app()).cohorts_state.data,oldCollection);assert.match(await page.getByTestId('cohorts-cursor').innerText(),/0 s.*selected view differs/);
    assert.match(await page.getByTestId('cohorts-status').innerText(),/last verified/);await page.screenshot({path:path.join(output,'stale-cohorts-retry.png'),fullPage:true});
    await page.unroute(cohortPattern);await page.getByTestId('cohorts-retry').click();await aligned(runs.small,'0.5',half.revision);await capture('cohort-retry-fractional-frontier',runs.small);
    let timelineHits=0,metricHits=0;
    await page.route('**/api/runs/*/timeline?*',route=>{timelineHits++;return route.fulfill({status:503,contentType:'application/json',body:'{"error":"Controlled Events failure"}'});});
    await page.route('**/api/runs/*/metrics?*',route=>{metricHits++;return route.fulfill({status:503,contentType:'application/json',body:'{"error":"Controlled Statistics failure"}'});});
    const one=await command(runs.small,'advance',{time:'1'});await aligned(runs.small,'1',one.revision);await until(async()=>timelineHits>0&&metricHits>0,'unrelated endpoints failed');await capture('events-and-statistics-failures-isolated',runs.small);
    await page.unroute('**/api/runs/*/timeline?*');await page.unroute('**/api/runs/*/metrics?*');
    report.checks.push('Repeated-time and fractional cursors are exact; failed Cohorts retain labelled source data and Retry recovers independently of Events and Statistics');

    let slowActive=0,slowMaximum=0,slowCalls=0;
    await page.route(cohortPattern,async route=>{slowCalls++;slowActive++;slowMaximum=Math.max(slowMaximum,slowActive);const response=await route.fetch();await new Promise(resolve=>setTimeout(resolve,900));slowActive--;try{await route.fulfill({response});}catch{}});
    await command(runs.small,'advance',{time:'2'});await until(async()=>slowCalls>0,'slow cohort read');await command(runs.small,'advance',{time:'3'});
    await until(async()=>seconds((await app()).view?.time)===3,'view advances during slow read');assert.notEqual(seconds((await app()).cohorts_cursor.time),3);
    assert.match(await page.getByTestId('cohorts-status').innerText(),/Refreshing|verified/);await aligned(runs.small,'3');assert.equal(slowMaximum,1);assert(slowCalls<=3);
    await page.unroute(cohortPattern);report.slow_refresh={maximum_inflight:slowMaximum,requests:slowCalls};await capture('single-flight-coalesced-cohort-refresh',runs.small);
    await page.route(cohortPattern,async route=>{const response=await route.fetch(),data=await response.json();data.cursor.revision=String(BigInt(data.cursor.revision)-1n);await route.fulfill({response,json:data});});
    await command(runs.small,'advance',{time:'4'});await until(async()=>(await app()).cohorts_state.phase==='failed','mismatched source rejected');assert.match(await page.getByTestId('cohorts-status').innerText(),/different source/);
    await page.unroute(cohortPattern);await page.getByTestId('cohorts-retry').click();await aligned(runs.small,'4');await capture('wrong-cursor-rejected-and-recovered',runs.small);
    report.checks.push('Slow reads remain single-flight and coalesce later frontiers; mismatched source cursors are rejected rather than relabelled');

    const replayBefore=await audit(runs.small);let releaseReplay,replayReady=false;
    const replayHold=new Promise(resolve=>releaseReplay=resolve);cleanup.push(()=>releaseReplay());
    await page.route(cohortPattern,async route=>{if(seconds(new URL(route.request().url()).searchParams.get('time'))!==.5)return route.continue();const response=await route.fetch();replayReady=true;await replayHold;try{await route.fulfill({response});}catch{}});
    await seek(.5);await until(async()=>replayReady,'held replay response');await seek(2.5);await aligned(runs.small,'2.5');releaseReplay();await page.waitForTimeout(200);assert.equal(seconds((await app()).cohorts_cursor.time),2.5);await page.unroute(cohortPattern);
    await capture('obsolete-replay-response-rejected',runs.small);const replayAfter=await audit(runs.small);assert.deepEqual(replayAfter,replayBefore);report.read_only_windows.push({label:'replay-response-ordering',before:replayBefore,after:replayAfter});
    report.checks.push('A delayed replay response cannot overwrite the newer selection; definition references remain fixed while measurement cursors change');

    let releaseRun,oldRunReady=false;const runHold=new Promise(resolve=>releaseRun=resolve);cleanup.push(()=>releaseRun());
    await page.route(cohortPattern,async route=>{if(!route.request().url().includes(runs.small))return route.continue();const response=await route.fetch();oldRunReady=true;await runHold;try{await route.fulfill({response});}catch{}});
    await seek(3.5);await until(async()=>oldRunReady,'held old-run response');await select(runs.baseline);releaseRun();await page.waitForTimeout(200);await page.unroute(cohortPattern);
    assert.equal((await app()).cohorts_cursor.run_id,runs.baseline);assert.equal((await app()).cohorts.length,0);await capture('old-run-response-rejected',runs.baseline);
    const baselineBefore=await audit(runs.baseline);
    const baselineHumans=await create({name:'Baseline humans'},runs.baseline);assert.equal(baselineHumans.denominator,800);
    const baselineInfected=await create({name:'Baseline infected',mode:'dynamic',status:'INFECTED'},runs.baseline);assert.equal(baselineInfected.denominator,20);
    await capture('baseline-thousand-cohort-members',runs.baseline);const baselineAfter=await audit(runs.baseline);assert.deepEqual(baselineAfter,baselineBefore);report.read_only_windows.push({label:'baseline-cohort-creation',before:baselineBefore,after:baselineAfter});
    const baselineHalf=await command(runs.baseline,'advance',{time:'0.5'});await aligned(runs.baseline,'0.5',baselineHalf.revision);await capture('baseline-thousand-fractional-cohorts',runs.baseline);await page.screenshot({path:path.join(output,'baseline-cohorts.png'),fullPage:true});
    report.checks.push('Run changes discard obsolete collections; real 1,000-agent baseline groups have independently verified member IDs, counts, means and fractional source cursors');

    await select(runs.lifecycle);const lifecycleBefore=await audit(runs.lifecycle);await seek(0);await aligned(runs.lifecycle,'0');
    const fixed=await create({name:'Lifecycle fixed humans'},runs.lifecycle);assert.equal(fixed.denominator,6);
    await create({name:'Lifecycle dynamic humans',mode:'dynamic'},runs.lifecycle);
    await create({name:'Lifecycle dynamic living',mode:'dynamic',includeDead:false},runs.lifecycle);
    await create({name:'Lifecycle fixed living',includeDead:false},runs.lifecycle);
    await create({name:'Lifecycle fixed infected',status:'INFECTED'},runs.lifecycle);
    await create({name:'Lifecycle dynamic infected',mode:'dynamic',status:'INFECTED'},runs.lifecycle);
    await capture('lifecycle-reference-before-transitions',runs.lifecycle);
    await seek(.5);await aligned(runs.lifecycle,'0.5');
    const regionFixed=await create({name:'Fractional fixed region',region:'50.9,49,51.1,51'},runs.lifecycle);assert.deepEqual(regionFixed.members,['mover']);assert.equal(regionFixed.definition.reference_time,'1/2');
    await create({name:'Fractional dynamic region',mode:'dynamic',region:'50.9,49,51.1,51'},runs.lifecycle);
    for(const time of [.5,1,1.5,2,3.5,4]){await seek(time);await aligned(runs.lifecycle,String(time));await capture(`lifecycle-time-${time}`,runs.lifecycle);}
    const finalRows=(await app()).cohorts,byName=name=>finalRows.find(row=>row.definition.name===name);
    assert.equal(byName('Lifecycle fixed humans').denominator,6);assert.equal(byName('Lifecycle fixed humans').populations.dead,1);assert.equal(byName('Lifecycle fixed humans').populations.zombies,2);
    assert.equal(byName('Lifecycle dynamic humans').denominator,4);assert.equal(byName('Lifecycle dynamic living').denominator,3);assert.equal(byName('Lifecycle fixed living').denominator,6);
    assert.deepEqual(byName('Lifecycle fixed infected').members.sort(),['converter','patient']);assert.equal(byName('Lifecycle dynamic infected').denominator,0);
    assert.deepEqual(byName('Fractional fixed region').members,['mover']);assert.equal(byName('Fractional dynamic region').denominator,0);
    await page.screenshot({path:path.join(output,'fixed-dynamic-lifecycle.png'),fullPage:true});
    const lifecycleAfter=await audit(runs.lifecycle);assert.deepEqual(lifecycleAfter,lifecycleBefore);report.read_only_windows.push({label:'lifecycle-creation-and-replay',before:lifecycleBefore,after:lifecycleAfter});
    report.checks.push('Real cure, infection, death and conversion preserve fixed identities and reevaluate dynamic predicates; dead-selection semantics, fractional region references, empty means and overlap match full snapshots without changing runtime/RNG history');

    await select(runs.small);const perspectiveBefore=await audit(runs.small);await page.getByTestId('tab-world').click();await page.getByTestId('agent-search-select').first().click();await page.getByTestId('tab-cohorts').click();
    let releasePerspective,perspectiveReady=false;const perspectiveHold=new Promise(resolve=>releasePerspective=resolve);cleanup.push(()=>releasePerspective());
    await page.route(cohortPattern,async route=>{const response=await route.fetch();perspectiveReady=true;await perspectiveHold;try{await route.fulfill({response});}catch{}});
    await seek(3.25);await until(async()=>perspectiveReady,'cohort pending before restricted perspective');await page.getByTestId('perspective').selectOption('agent');releasePerspective();
    await until(async()=>{const state=await app();return state.perspective==='agent'&&state.cohorts_state.phase==='idle';},'cohort privilege cleanup');await page.waitForTimeout(200);
    const restricted=await app();assert.equal(restricted.cohorts_cursor,undefined);assert.deepEqual(restricted.cohorts,[]);assert.deepEqual(restricted.privileged_cache_keys,[]);assert.equal(await page.getByTestId('cohort-card').count(),0);
    await page.unroute(cohortPattern);await page.getByTestId('perspective').selectOption('researcher');await aligned(runs.small,'3.25');await capture('researcher-cohorts-restored-after-perspective-change',runs.small);
    await page.getByTestId('replay-return-live').click();await aligned(runs.small,'4');const perspectiveAfter=await audit(runs.small);assert.deepEqual(perspectiveAfter,perspectiveBefore);report.read_only_windows.push({label:'perspective-request-race',before:perspectiveBefore,after:perspectiveAfter});
    report.checks.push('Agent perspective cancels pending privileged reads and removes cohort cards/caches; returning restores the selected researcher cursor without history changes');

    for(const run of [runs.small,runs.baseline]){await command(run,'terminate');await until(async()=>(await call('/api/runs')).find(row=>row.id===run).resource_status.cleanup_complete,'worker termination cleanup');}
    await aligned(runs.small);await capture('terminated-final-cohorts',runs.small);
    const idleBefore=await call('/__issue7/diagnostics');await page.waitForTimeout(1300);const idleAfter=await call('/__issue7/diagnostics');
    const matching=rows=>rows.filter(row=>row.path===`/api/runs/${runs.small}/cohorts`&&row.method==='GET').length;
    report.terminal_idle_cohort_requests=matching(idleAfter.requests)-matching(idleBefore.requests);assert.equal(report.terminal_idle_cohort_requests,0);
    report.checks.push('Terminated runs retain readable cohort summaries, finish worker cleanup and issue no redundant unchanged-cursor cohort requests');
    assert.deepEqual(report.errors,[]);report.passed=true;
  } catch(error) {
    report.error=String(error.stack||error);
    if(page)await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});
    throw error;
  } finally {
    for(const release of cleanup)release();
    fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
