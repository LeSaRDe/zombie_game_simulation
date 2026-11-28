/* I02 browser workflows against implementation_checks/issue2_check.py only. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');

(async () => {
  const [base, output, phase, rawIdentities] = process.argv.slice(2);
  const ids = JSON.parse(rawIdentities || '{}');
  const browser = await chromium.launch({executablePath:'/usr/bin/google-chrome', headless:true});
  const report = {passed:false, phase, browser:browser.version(), checks:[]};
  const errors = [], requests = [], streams = [], abortedRequests = [];
  let releaseSummary;
  let page;
  try {
    page = await browser.newPage({baseURL:base, viewport:{width:1440,height:1100}});
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => {if(request.url().includes('/api/')) requests.push({method:request.method(),url:request.url()});});
    page.on('requestfailed', request => abortedRequests.push({url:request.url(),failure:request.failure()}));
    page.on('websocket', socket => {const item={url:socket.url(),closed:false};streams.push(item);socket.on('close',()=>{item.closed=true;});});
    // Deliberately deliver a fully received response late, even after abort.
    // This tests identity/generation guards independently of network abort.
    await page.addInitScript(({initialSummaryDelay}) => {
      const original = window.fetch.bind(window);
      window.__issue2Holds = {rules:[], pending:{}, released:[], summaryDelay:initialSummaryDelay,
        blockSummaries:false, summaryWaiters:[], summaryResponses:0};
      window.fetch = async (...args) => {
        const url = String(args[0]);
        const summary=url==='/api/runs'&&(!args[1]?.method||args[1].method==='GET');
        const summaryDelay=summary?window.__issue2Holds.summaryDelay:0;
        const index = window.__issue2Holds.rules.findIndex(rule => rule.kind==='start_ack'
          ? /\/commands\/[^/?]+:start$/.test(url) : url.includes(`/runs/${rule.run_id}/view`));
        const rule = index < 0 ? undefined : window.__issue2Holds.rules.splice(index,1)[0];
        const response = await original(...args);
        if(summary&&(summaryDelay||window.__issue2Holds.blockSummaries)){
          const body=await response.text();
          if(summaryDelay)await new Promise(resolve=>setTimeout(resolve,summaryDelay));
          if(window.__issue2Holds.blockSummaries)await new Promise(resolve=>window.__issue2Holds.summaryWaiters.push(resolve));
          window.__issue2Holds.summaryResponses++;
          return new Response(body,{status:response.status,headers:response.headers});
        }
        if (!rule) return response;
        const body = await response.text();
        if(rule.kind==='start_ack'&&JSON.parse(body).status!=='applied'){
          window.__issue2Holds.rules.push(rule);
          return new Response(body,{status:response.status,headers:response.headers});
        }
        await new Promise(resolve => {window.__issue2Holds.pending[rule.name] = {resolve, received:true};});
        return new Response(body, {status:response.status,headers:response.headers});
      };
    },{initialSummaryDelay:phase==='populated'?1500:0});
    const call = async (route, body) => {
      const response = body === undefined ? await page.request.get(route) : await page.request.post(route,{data:body});
      if (!response.ok()) throw Error(`${route}: ${response.status()} ${await response.text()}`);
      return response.json();
    };
    const until = async (fn, label, timeout=30000) => {
      const deadline=Date.now()+timeout;
      while(Date.now()<deadline){const result=await fn();if(result)return result;await page.waitForTimeout(50);}
      throw Error(`Timed out waiting for ${label}`);
    };
    const diagnostic = () => call('/__issue2/diagnostics');
    const audit = () => call('/__issue2/audit');
    const choose = async identity => {await page.locator(`button[data-run-id="${identity}"]`).click();};
    const ready = async identity => {
      await page.waitForFunction(id => {
        const app=window.__zombieInspection?.app;
        return app?.run_id===id && app?.view?.run_id===id && app.viewer_load?.phase==='ready';
      },identity,{timeout:45000});
    };
    const home = async () => {
      await page.getByTestId('run-return-list').click();
      await page.getByTestId('run-chooser').waitFor();
      await page.waitForFunction(()=>!window.__zombieInspection.app.run_id&&!window.__zombieInspection.app.view);
    };
    const arm = (identity,name,kind='delay') => call('/__issue2/gate',{run_id:identity,name,kind});
    const entered = name => until(async()=> (await diagnostic()).gates[name]?.entered,`${name} gate entry`);
    const cancelled = name => until(async()=>{
      const gate=(await diagnostic()).gates[name];return gate?.cancel_observed&&gate.finished;
    },`${name} cooperative reader cancellation`);
    const hold = (identity,name) => page.evaluate(({identity,name})=>window.__issue2Holds.rules.push({run_id:identity,name}),{identity,name});
    const held = name => page.waitForFunction(name=>window.__issue2Holds.pending[name]?.received,name);
    const releaseHeld = name => page.evaluate(name=>{
      window.__issue2Holds.pending[name].resolve();delete window.__issue2Holds.pending[name];window.__issue2Holds.released.push(name);
    },name);
    const command = async (identity,operation) => {
      const result=await call(`/api/runs/${identity}/commands`,{operation,command_id:randomUUID()});
      const receipt=await until(async()=>{const row=await call(`/api/commands/${result.command_id}`);return row.status==='pending'?null:row;},operation+' receipt');
      if(receipt.status!=='applied')throw Error(JSON.stringify(receipt));return receipt;
    };
    const noHistoryWork = (before,after,label) => {
      for(const counter of ['state_at','snapshot_calls','http_views']){
        if(before.counters[counter]!==after.counters[counter])throw Error(`${label} caused ${counter}: ${before.counters[counter]} → ${after.counters[counter]}`);
      }
      const unexpected=after.requests.slice(before.requests.length).filter(row=>/^\/api\/runs\/[^/]+\/(view|metrics|timeline|cohorts)$/.test(row.path));
      if(unexpected.length)throw Error(`${label} loaded run data: ${JSON.stringify(unexpected)}`);
    };

    const initialBefore=await diagnostic(), auditBefore=await audit();
    await page.goto(base);
    await page.getByTestId('run-chooser').waitFor();
    await page.waitForFunction(()=>window.__zombieInspection.app.run_list_state.phase==='ready');
    if(phase==='populated')await page.locator(`button[data-run-id="${ids.baseline}"]`).waitFor();
    await page.waitForTimeout(1300);
    if(phase==='populated')await page.waitForFunction(()=>window.__issue2Holds.summaryResponses>=2);
    const initialAfter=await diagnostic(), auditAfter=await audit();
    noHistoryWork(initialBefore,initialAfter,`${phase} home`);
    if(JSON.stringify(auditBefore)!==JSON.stringify(auditAfter))throw Error('Opening home changed runs/revisions/commands');
    const initialApp=await page.evaluate(()=>window.__zombieInspection.app);
    if(initialApp.run_id||initialApp.view||initialApp.viewer_load.phase!=='idle')throw Error('Home selected or loaded an existing run');
    if(streams.length)throw Error('Home connected a run stream');
    await page.screenshot({path:path.join(output,`${phase}-home.png`),fullPage:true});
    report.checks.push('home performs no history reconstruction, stream connection, run creation, or revision change');
    report.home={before:initialBefore,after:initialAfter,audit_unchanged:true};

    if(phase==='empty'){
      await page.route('**/api/runs',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Fixture workspace service unavailable'})}));
      await page.reload();
      await page.getByTestId('run-list-retry').waitFor();
      if(!(await page.locator('body').innerText()).includes('Fixture workspace service unavailable'))throw Error('Unavailable service did not show actual failure');
      if(await page.getByTestId('viewer-loading').count())throw Error('Unavailable service was mislabeled world initialization');
      await page.screenshot({path:path.join(output,'workspace-error.png'),fullPage:true});
      await page.unroute('**/api/runs');
      await page.getByTestId('run-list-retry').click();
      await page.waitForFunction(()=>window.__zombieInspection.app.run_list_state.phase==='ready');
      await page.getByTestId('run-chooser').waitFor();
      report.checks.push('workspace service failure displays error and retry recovers');
    } else {
      await choose(ids.tiny_a);await ready(ids.tiny_a);
      if((await page.evaluate(()=>window.__zombieInspection.app.view.metrics.populations.total))!==20)throw Error('Tiny history did not load correctly');
      const slowSummaryResponses=await page.evaluate(()=>{window.__issue2Holds.summaryDelay=0;return window.__issue2Holds.summaryResponses;});
      report.slow_summaries={delay_ms:1500,completed_responses:slowSummaryResponses,chooser_and_explicit_selection_ready:true};
      report.checks.push('run summaries slower than the polling interval do not starve the chooser or explicit selection');
      await home();

      const beforeCancel=await audit();
      await arm(ids.baseline,'baseline-cancel');await choose(ids.baseline);await entered('baseline-cancel');
      await page.getByTestId('viewer-loading').waitFor();
      const loading=await page.getByTestId('viewer-loading').innerText();
      if(!loading.includes('Loading recorded history')||loading.includes('Initializing'))throw Error(`Incorrect history loading message: ${loading}`);
      const knownReference=await page.getByTestId('viewer-loading').locator('.viewer-run-reference').innerText();
      const recordedBoundary=beforeCancel.find(row=>row.id===ids.baseline).frontier;
      const exactBoundary=await page.getByTestId('viewer-loading').locator('.viewer-run-reference .time-value').getAttribute('data-exact-time');
      const [shownN,shownD='1']=exactBoundary.split('/');
      const displayedRevision=knownReference.match(/ · revision (\d+)$/);
      if(!displayedRevision||BigInt(shownN)*BigInt(recordedBoundary[2])!==BigInt(recordedBoundary[1])*BigInt(shownD)||Number(displayedRevision[1])!==recordedBoundary[0]){
        throw Error(`History loading panel lost the known committed boundary: ${JSON.stringify({knownReference,recordedBoundary})}`);
      }
      await page.screenshot({path:path.join(output,'history-loading.png'),fullPage:true});
      await page.getByTestId('viewer-cancel').click();await page.getByTestId('run-chooser').waitFor();await cancelled('baseline-cancel');
      if(JSON.stringify(beforeCancel)!==JSON.stringify(await audit()))throw Error('Cancelling history load changed simulation state');
      report.checks.push('1000-agent history load is distinct from initialization; cancel releases server reader without simulation mutation');

      await choose(ids.baseline);await ready(ids.baseline);
      if((await page.evaluate(()=>window.__zombieInspection.app.view.metrics.populations.total))!==1000)throw Error('Full baseline history did not load');
      await page.waitForTimeout(300);await home();

      await arm(ids.tiny_a,'history-failure','error');await choose(ids.tiny_a);
      await page.getByTestId('viewer-error').waitFor();
      if(!(await page.getByTestId('viewer-error').innerText()).includes('history-failure'))throw Error('History error details lost');
      await page.waitForTimeout(200);
      await page.screenshot({path:path.join(output,'history-error.png'),fullPage:true});
      await page.getByTestId('viewer-retry').click();await ready(ids.tiny_a);await home();
      report.checks.push('history failure exposes actual error and explicit retry succeeds');

      const unavailable=`**/api/runs/${ids.tiny_a}/view**`;
      await page.route(unavailable,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Fixture history service unavailable'})}));
      await choose(ids.tiny_a);await page.getByTestId('viewer-error').waitFor();
      if(!(await page.getByTestId('viewer-error').innerText()).includes('Fixture history service unavailable'))throw Error('Unavailable history service was not explained');
      await page.unroute(unavailable);await page.getByTestId('viewer-retry').click();await ready(ids.tiny_a);await home();
      report.checks.push('unavailable history service presents error instead of initialization and retry recovers');

      await arm(ids.tiny_a,'switch-cancel');await choose(ids.tiny_a);await entered('switch-cancel');
      await choose(ids.tiny_b);await ready(ids.tiny_b);await cancelled('switch-cancel');await home();
      report.checks.push('changing selection cancels pending server reader');

      await hold(ids.tiny_a,'late-success');await choose(ids.tiny_a);await held('late-success');
      await choose(ids.tiny_b);await ready(ids.tiny_b);
      let trace=await page.evaluate(()=>window.__zombieInspection.transport.application_trace.length);
      await releaseHeld('late-success');await page.waitForTimeout(250);
      if((await page.evaluate(()=>window.__zombieInspection.app.view.run_id))!==ids.tiny_b)throw Error('Late old selection replaced current view');
      if((await page.evaluate(()=>window.__zombieInspection.transport.application_trace.length))!==trace)throw Error('Late old success was accepted');
      await home();

      await arm(ids.tiny_a,'late-same-run-error','error');await hold(ids.tiny_a,'late-error');await choose(ids.tiny_a);await held('late-error');
      await page.getByTestId('viewer-cancel').click();await page.getByTestId('run-chooser').waitFor();
      await choose(ids.tiny_a);await ready(ids.tiny_a);trace=await page.evaluate(()=>window.__zombieInspection.transport.application_trace.length);
      await releaseHeld('late-error');await page.waitForTimeout(250);
      if(await page.getByTestId('viewer-error').count())throw Error('Late same-run error overwrote successful newer request');
      if((await page.locator('body').innerText()).includes('late-same-run-error'))throw Error('Late same-run failure leaked into the current interface');
      if((await page.evaluate(()=>window.__zombieInspection.transport.application_trace.length))!==trace)throw Error('Late same-run response accepted');
      await home();report.checks.push('fully received late successes/errors cannot overwrite a newer selection or same-run request');

      await choose(ids.failed);await page.getByTestId('viewer-error').waitFor();
      if(!(await page.getByTestId('viewer-error').innerText()).includes('Fixture worker initialization failed'))throw Error('Failed run was not explained');
      if(await page.getByTestId('viewer-loading').count())throw Error('Failed run remains initializing');
      await page.getByTestId('viewer-return-list').click();await page.getByTestId('run-chooser').waitFor();
      report.checks.push('actual failed initialization displays failure and returns to chooser');

      await command(ids.active,'continue');
      await arm(ids.active,'active-cancel');await choose(ids.active);await entered('active-cancel');
      const activeBefore=(await audit()).find(row=>row.id===ids.active);
      await page.getByTestId('viewer-cancel').click();await page.getByTestId('run-chooser').waitFor();await cancelled('active-cancel');
      const activeAfter=(await audit()).find(row=>row.id===ids.active);
      if(activeAfter.status!=='running'||activeAfter.commands!==activeBefore.commands||activeAfter.generation!==activeBefore.generation)throw Error('Viewer cancellation controlled executing simulation');
      await command(ids.active,'pause');report.checks.push('cancelling an active run viewer leaves execution running and submits no run command');

      // Avoid the separately queued configuration-metadata race by explicitly
      // waiting for this dialog's preset response before entering the draft.
      const metadata=page.waitForResponse(response=>response.url().endsWith('/api/config')&&response.ok());
      await page.getByRole('button',{name:/New experiment/}).click();await metadata;
      await page.waitForFunction(()=>!!window.__zombieInspection.configuration.draft?.population);
      await page.getByText('Advanced configuration · JSON',{exact:true}).click();
      await page.getByLabel('Advanced configuration JSON').fill(JSON.stringify({scenario:'issue2_initialization_delay',seed:24,horizon:120,
        population:{humans:16,zombies:4},execution:{workers:1},checkpoint_interval:1000}));
      await page.evaluate(()=>{window.__issue2Holds.blockSummaries=true;});
      releaseSummary=()=>page.evaluate(()=>{
        window.__issue2Holds.blockSummaries=false;
        for(const resolve of window.__issue2Holds.summaryWaiters.splice(0))resolve();
      });
      await page.evaluate(()=>window.__issue2Holds.rules.push({kind:'start_ack',name:'start-ack'}));
      const creation=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
      const launchBefore=await diagnostic();
      await page.getByTestId('config-launch').click();
      const creationResponse=await creation;
      if(creationResponse.status()!==202)throw Error('GUI create did not return accepted identity before initialization');
      const created=await creationResponse.json();
      if(created.status!=='accepted'||created.revision!==undefined||created.time!==undefined)throw Error(`Creation fabricated a finalized boundary: ${JSON.stringify(created)}`);
      const initialization=await until(async()=>{const state=await call(`/__issue2/initialization/${created.run_id}/state`);return state.entered?state:null;},'actual worker initialization barrier');
      if(initialization.status!=='initializing'||initialization.released||initialization.history_exists)throw Error(`Accepted creation did not precede initialization: ${JSON.stringify(initialization)}`);
      await page.waitForFunction(id=>window.__zombieInspection.app.run_id===id&&window.__zombieInspection.app.viewer_load.phase==='loading'&&window.__zombieInspection.app.viewer_load.details,created.run_id);
      if((await page.getByTestId('viewer-loading').innerText()).includes('Initializing'))throw Error('Unknown run summary was falsely called initialization');
      if((await diagnostic()).counters.http_views!==launchBefore.counters.http_views)throw Error('Accepted run queried history before its first fresh summary');
      await page.screenshot({path:path.join(output,'waiting-for-run-summary.png'),fullPage:true});
      await releaseSummary();releaseSummary=undefined;
      await page.waitForFunction(id=>window.__zombieInspection.app.run_id===id&&window.__zombieInspection.app.viewer_load.phase==='initializing',created.run_id);
      await page.getByTestId('viewer-loading').waitFor();
      if(!(await page.getByTestId('viewer-loading').innerText()).includes('Initializing'))throw Error('Actual initialization not distinguished');
      const initializingReference=await page.getByTestId('viewer-loading').locator('.viewer-run-reference').innerText();
      const claimsBoundary=text=>/committed|\brevision\b|\b\d+(?:[,.]\d+)*\s+s\b/i.test(text);
      if(claimsBoundary(initializingReference))throw Error(`Uninitialized run fabricated a committed boundary: ${initializingReference}`);
      await page.screenshot({path:path.join(output,'actual-initialization.png'),fullPage:true});
      await page.waitForTimeout(1100);const afterInit=await diagnostic();
      if(afterInit.counters.http_views!==launchBefore.counters.http_views)throw Error('Initialization requested full history before the world was ready');
      const beforeInitCancel=(await audit()).find(row=>row.id===created.run_id);
      await page.getByTestId('viewer-cancel').click();await page.getByTestId('run-chooser').waitFor();
      const initializingCard=await page.getByTestId('chooser-select-run').filter({hasText:created.run_id}).locator('span').innerText();
      if(claimsBoundary(initializingCard))throw Error(`Uninitialized chooser card fabricated a committed boundary: ${initializingCard}`);
      const afterInitCancel=(await audit()).find(row=>row.id===created.run_id);
      if(JSON.stringify(beforeInitCancel)!==JSON.stringify(afterInitCancel))throw Error('Cancelling the initializing viewer changed the accepted run');
      if(afterInitCancel.frontier!==null||afterInitCancel.history_bytes!==0)throw Error('Initialization boundary assertion did not precede the first committed history');
      report.boundary_display={known_history_reference:knownReference,known_boundary:recordedBoundary,
        initializing_reference:initializingReference,initializing_chooser_status:initializingCard,uninitialized_history_exists:false};
      report.checks.push('initializing viewer and chooser omit unknown committed boundaries while recorded history retains its actual boundary');
      await choose(created.run_id);
      await page.waitForFunction(()=>window.__zombieInspection.app.viewer_load.phase==='initializing');
      if((await diagnostic()).counters.http_views!==launchBefore.counters.http_views)throw Error('Reselecting initialization queried unready history');
      await call(`/__issue2/initialization/${created.run_id}/release`);await held('start-ack');await ready(created.run_id);
      for(const control of ['run-pause','run-stop','run-checkpoint','run-terminate','run-pacing']){
        if(!await page.getByTestId(control).isDisabled())throw Error(`${control} enabled before the new run's start acknowledgement reached the GUI`);
      }
      await home();await choose(created.run_id);await ready(created.run_id);
      if(!await page.getByTestId('run-pause').isDisabled())throw Error('Reselecting a run bypassed its pending start acknowledgement');
      await home();await releaseHeld('start-ack');await page.waitForTimeout(250);
      if(await page.evaluate(()=>Boolean(window.__zombieInspection.app.run_id)))throw Error('Late start acknowledgement navigated away from the run chooser');
      await choose(created.run_id);await ready(created.run_id);
      await until(async()=>!await page.getByTestId('run-pause').isDisabled(),'controls after start acknowledgement');
      report.checks.push('new-run controls wait for start acknowledgement while viewer navigation remains available');
      await command(created.run_id,'terminate');await until(async()=> (await call('/api/runs')).find(row=>row.id===created.run_id).resource_status.cleanup_complete,'created run cleanup');
      report.created_run=created.run_id;report.checks.push('GUI launch selects newly created initializing run, polls lightweight status, then loads its actual world');
      report.checks.push('accepted run waits for a fresh delayed summary; cancelling and reselecting initialization leaves the run unchanged');
      report.creation_acceptance={status:creationResponse.status(),receipt:created,initialization,full_views_during_initialization:0};
      await home();

      const beforeUncertain=await audit(), beforeUncertainRequests=(await diagnostic()).requests.length;
      const secondMetadata=page.waitForResponse(response=>response.url().endsWith('/api/config')&&response.ok());
      await page.getByRole('button',{name:/New experiment/}).click();await secondMetadata;
      await page.waitForFunction(()=>!!window.__zombieInspection.configuration.draft?.population);
      await page.getByText('Advanced configuration · JSON',{exact:true}).click();
      await page.getByLabel('Advanced configuration JSON').fill(JSON.stringify({scenario:'issue2_start_receipt_failure',seed:25,horizon:120,
        population:{humans:16,zombies:4},execution:{workers:1},checkpoint_interval:1000}));
      const startReceipt=/\/api\/commands\/[^/?]+:start$/;
      let failedReceiptRequests=0;
      const failOneReceipt=async route=>{
        failedReceiptRequests++;
        await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Fixture start receipt response unavailable'})});
        await page.unroute(startReceipt,failOneReceipt);
      };
      await page.route(startReceipt,failOneReceipt);
      const secondCreation=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
      await page.getByTestId('config-launch').click();const uncertain=await(await secondCreation).json();
      await ready(uncertain.run_id);
      await page.waitForFunction(id=>{
        const app=window.__zombieInspection.app;
        return app.run_id===id&&!app.start_pending&&!app.start_uncertain&&app.run.generation>0;
      },uncertain.run_id);
      await until(async()=>!await page.getByTestId('run-pause').isDisabled(),'uncertain start recovery');
      await page.getByTestId('run-pause').click();
      await page.waitForFunction(id=>{
        const app=window.__zombieInspection.app;
        return app.run_id===id&&!app.pending&&app.command?.status==='applied'&&app.command?.run_status==='paused';
      },uncertain.run_id);
      const afterUncertain=await audit(), uncertainAudit=afterUncertain.find(row=>row.id===uncertain.run_id);
      const posts=(await diagnostic()).requests.slice(beforeUncertainRequests).filter(row=>row.method==='POST'&&row.path==='/api/runs');
      if(failedReceiptRequests!==1||posts.length!==1||afterUncertain.length!==beforeUncertain.length+1||uncertainAudit.commands!==3){
        throw Error(`Start recovery resubmitted work or lost its control generation: ${JSON.stringify({failedReceiptRequests,posts,uncertainAudit})}`);
      }
      report.uncertain_start={run_id:uncertain.run_id,failed_receipt_requests:failedReceiptRequests,created_runs:1,
        command_count_after_first_pause:uncertainAudit.commands,first_pause_applied:true};
      report.checks.push('failed start receipt reconciles from run summaries; first Pause uses fresh generation without resubmitting create/start');
      await command(uncertain.run_id,'terminate');await home();
      await command(ids.active,'terminate');
      await page.screenshot({path:path.join(output,'final-chooser.png'),fullPage:true});
      report.server_gates=(await diagnostic()).gates;
    }
    if(errors.length)throw Error(`Browser errors: ${JSON.stringify(errors)}`);
    report.passed=true;report.requests=requests;report.streams=streams;report.page_errors=errors;
    console.log(`I02 ${phase} browser workflows PASS (${report.checks.length} checks)`);
  } catch(error) {
    report.error=String(error.stack||error);
    report.requests=requests;report.streams=streams;report.page_errors=errors;
    try {
      report.failure_state=await page.evaluate(()=>{
        const app=window.__zombieInspection.app;
        return {run_id:app.run_id,viewer_load:app.viewer_load,run_list_state:app.run_list_state,
          run_status:app.run?.status,start_pending:app.start_pending,start_uncertain:app.start_uncertain};
      });
      const diagnosticResponse=await page.request.get('/__issue2/diagnostics',{timeout:3000});
      report.failure_diagnostics=await diagnosticResponse.json();
      await page.screenshot({path:path.join(output,`${phase}-failure.png`),fullPage:true});
    } catch(diagnosticError) {report.diagnostic_error=String(diagnosticError);}
    throw error;
  } finally {
    await releaseSummary?.();
    report.aborted_requests=abortedRequests;
    fs.writeFileSync(path.join(output,`browser-${phase}.json`),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
