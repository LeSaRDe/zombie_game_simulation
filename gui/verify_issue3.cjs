/* I03 configuration workflows against implementation_checks/issue3_check.py. */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID}=require('node:crypto');

(async()=>{
  const [base,output,sourceId]=process.argv.slice(2);
  const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true});
  const report={passed:false,browser:browser.version(),checks:[],metadata_failures:[],draft_failures:[]};
  const errors=[],requests=[];
  let page;
  try{
    page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('request',request=>{if(request.url().includes('/api/'))requests.push({method:request.method(),url:request.url()});});
    // Hold a fully received response to test obsolete-result protection even
    // when AbortController cannot retract an already completed network read.
    await page.addInitScript(()=>{
      const original=window.fetch.bind(window);
      window.__issue3Metadata={rules:[],pending:{}};
      window.fetch=async(...args)=>{
        const metadata=String(args[0])==='/api/config'&&(!args[1]?.method||args[1].method==='GET');
        const rule=metadata?window.__issue3Metadata.rules.shift():undefined;
        const response=await original(...args);
        if(!rule)return response;
        const body=await response.text();
        if(rule.kind==='hold')await new Promise(resolve=>{window.__issue3Metadata.pending[rule.name]={resolve,received:true};});
        return new Response(rule.body===undefined?body:rule.body,{status:rule.status||response.status,headers:{'Content-Type':'application/json'}});
      };
    });
    const call=async(route,body)=>{
      const response=body===undefined?await page.request.get(route):await page.request.post(route,{data:body});
      if(!response.ok())throw Error(`${route}: ${response.status()} ${await response.text()}`);
      return response.json();
    };
    const until=async(fn,label,timeout=30000)=>{
      const deadline=Date.now()+timeout;
      while(Date.now()<deadline){const value=await fn();if(value)return value;await page.waitForTimeout(50);}
      throw Error(`Timed out waiting for ${label}`);
    };
    const diagnostic=()=>call('/__issue3/diagnostics');
    const audit=()=>call('/__issue3/audit');
    const addRule=rule=>page.evaluate(rule=>window.__issue3Metadata.rules.push(rule),rule);
    const held=name=>page.waitForFunction(name=>window.__issue3Metadata.pending[name]?.received,name);
    const release=name=>page.evaluate(name=>{window.__issue3Metadata.pending[name].resolve();delete window.__issue3Metadata.pending[name];},name);
    const open=async()=>{await page.getByRole('button',{name:/New experiment/}).click();await page.getByRole('dialog',{name:'Configure your world'}).waitFor();};
    const close=async()=>{await page.getByRole('button',{name:'Close configuration',exact:true}).click();await page.getByRole('dialog',{name:'Configure your world'}).waitFor({state:'detached'});};
    const ready=()=>page.waitForFunction(()=>window.__zombieInspection.configuration.load_state?.phase==='ready');
    const draft=()=>page.getByLabel('Advanced configuration JSON');
    const advanced=async()=>{const details=page.locator('details').filter({has:page.getByText('Advanced configuration · JSON',{exact:true})});if(!await details.evaluate(node=>node.open))await page.getByText('Advanced configuration · JSON',{exact:true}).click();};
    const actions=['config-validate','config-preview','config-launch','config-export','config-save'];
    const blocked=async()=>{
      for(const action of actions)if(!await page.getByTestId(action).isDisabled())throw Error(`${action} available before metadata readiness`);
      if(!await page.getByTestId('config-preset').isDisabled())throw Error('Preset selectable before metadata readiness');
      if(!await page.getByTestId('config-import').isDisabled())throw Error('Import available before metadata readiness');
    };
    const assertNoMutation=async(before,label)=>{
      const after=await diagnostic();
      const mutation=after.requests.slice(before.requests.length).filter(item=>item.method==='POST');
      if(mutation.length)throw Error(`${label} submitted API mutations: ${JSON.stringify(mutation)}`);
      if(after.runs.length!==before.runs.length)throw Error(`${label} created a run`);
    };
    const command=async(identity,operation)=>{
      const sent=await call(`/api/runs/${identity}/commands`,{operation,command_id:randomUUID()});
      const result=await until(async()=>{const receipt=await call(`/api/commands/${sent.command_id}`);return receipt.status==='pending'?null:receipt;},operation+' receipt');
      if(result.status!=='applied')throw Error(JSON.stringify(result));
      return result;
    };
    await page.goto(base);await page.getByTestId('run-chooser').waitFor();
    await page.waitForFunction(()=>window.__zombieInspection.app.run_list_state.phase==='ready');
    const metadata=await call('/api/config');

    await addRule({kind:'hold',name:'initial-load'});const delayedBefore=await diagnostic();
    const savedBefore=await page.evaluate(()=>localStorage.getItem('zombie-draft'));
    await open();await held('initial-load');await page.getByTestId('config-loading').waitFor();await blocked();
    for(const action of ['config-validate','config-preview','config-launch']){
      const bounds=await page.getByTestId(action).boundingBox();
      await page.mouse.click(bounds.x+bounds.width/2,bounds.y+bounds.height/2);
    }
    // Keyboard navigation must not focus disabled actions. Enter on a neutral
    // dialog heading also cannot submit an unfinished configuration.
    await advanced();
    await page.locator('#config-title').evaluate(node=>{node.tabIndex=-1;node.focus();});
    await page.keyboard.press('Enter');await page.keyboard.press('Space');
    const focused=[];
    for(const key of ['Tab','Shift+Tab'])for(let index=0;index<8;index++){
      await page.keyboard.press(key);
      const current=await page.evaluate(()=>({testId:document.activeElement?.getAttribute('data-testid'),
        inside:Boolean(document.activeElement?.closest('[role="dialog"]')),disabled:document.activeElement?.matches(':disabled')}));
      if(!current.inside||current.disabled)throw Error(`${key} escaped the loading dialog or focused a disabled editor control: ${JSON.stringify(current)}`);
      focused.push(current.testId);
    }
    if(focused.some(value=>actions.includes(value)))throw Error('Keyboard focus entered a disabled configuration action');
    await page.getByTestId('config-validate').evaluate(node=>node.click());
    await page.waitForTimeout(250);await assertNoMutation(delayedBefore,'Unloaded configuration');
    if(await page.evaluate(()=>localStorage.getItem('zombie-draft'))!==savedBefore)throw Error('Unloaded draft changed local storage');
    await page.screenshot({path:path.join(output,'metadata-loading.png'),fullPage:true});
    await release('initial-load');await ready();
    if(await page.getByTestId('config-validate').isDisabled())throw Error('Validate did not enable after metadata arrived');
    report.checks.push('Delayed metadata blocks mouse, keyboard and programmatic activation without API mutations or saving an unloaded draft');
    await close();

    const malformed=[
      ['HTTP failure',503,JSON.stringify({error:'Fixture configuration service unavailable'})],
      ['empty body',200,''],['malformed JSON response',200,'{"presets":'],
      ['empty metadata',200,'{}'],['missing fields',200,JSON.stringify({...metadata,fields:undefined})],
      ['unsupported schema',200,JSON.stringify({...metadata,schema_version:'unsupported-fixture-schema'})],
      ['invalid fields container',200,JSON.stringify({...metadata,fields:{}})],
      ['malformed field path',200,JSON.stringify({...metadata,fields:[{path:null,type:'integer',label:'Bad field'}]})],
      ['unsupported field type',200,JSON.stringify({...metadata,fields:[{path:'seed',type:'banana',label:'Bad field'}]})],
      ['missing small preset',200,JSON.stringify({...metadata,presets:{baseline:metadata.presets.baseline}})],
      ['empty small preset',200,JSON.stringify({...metadata,presets:{...metadata.presets,small:{}}})],
      ['array baseline preset',200,JSON.stringify({...metadata,presets:{...metadata.presets,baseline:[]}})],
      ['invalid preset editor structure',200,JSON.stringify({...metadata,presets:{...metadata.presets,small:{...metadata.presets.small,population:[]}}})],
    ];
    for(const [name,status,body] of malformed){
      await addRule({kind:'response',status,body});const before=await diagnostic();await open();
      await page.getByTestId('config-load-error').waitFor();await blocked();
      const message=await page.getByTestId('config-load-error').innerText();
      if(!/configur|metadata|server/i.test(message))throw Error(`${name} did not identify configuration loading failure: ${message}`);
      if(/Unexpected end of JSON input/.test(message))throw Error(`${name} exposed the unhelpful raw parser message`);
      await assertNoMutation(before,name);
      if(name==='HTTP failure'){await page.waitForTimeout(200);await page.screenshot({path:path.join(output,'metadata-error-retry.png'),fullPage:true});}
      await page.getByTestId('config-retry').click();await ready();
      if(await page.getByTestId('config-validate').isDisabled())throw Error(`${name} retry did not restore actions`);
      report.metadata_failures.push({name,message,retry_ready:true});await close();
    }
    report.checks.push('HTTP, empty, malformed and structurally invalid metadata failures keep actions disabled and recover through explicit retry');

    // A completed old response cannot affect a newly opened editor and edits.
    await addRule({kind:'hold',name:'closed-editor'});await open();await held('closed-editor');await close();
    await open();await ready();await advanced();
    const preserved=JSON.stringify({...metadata.presets.small,scenario:'issue3_preserved_after_reopen',seed:777},null,2);
    await draft().fill(preserved);await release('closed-editor');await page.waitForTimeout(250);
    if(await draft().inputValue()!==preserved)throw Error('Late metadata from closed editor overwrote the newer draft');
    if((await page.getByTestId('config-load-error').count())!==0)throw Error('Closed editor metadata failure leaked into newer editor');
    report.checks.push('Late metadata after close/reopen cannot replace text in the new editor');

    const invalidDrafts=[['empty',''],['whitespace',' \n\t '],['incomplete object','{'],['incomplete property','{"seed":'],
      ['array','[]'],['null','null'],['number','42'],['string','"not an object"']];
    for(const [name,text] of invalidDrafts){
      for(const action of ['config-validate','config-preview','config-launch','config-export']){
        await draft().fill(preserved);await draft().fill(text);
        const before=await diagnostic();
        if(await page.getByTestId(action).isDisabled())throw Error(`${action} stayed disabled after editing the previous parse error`);
        await page.getByTestId(action).click();
        await until(async()=>{const value=await page.getByTestId('config-result').innerText();return /complete JSON|JSON object/i.test(value)?value:null;},`${name} ${action} readable error`);
        const message=await page.getByTestId('config-result').innerText();
        const feedback=await page.getByTestId('config-result').evaluate(node=>{
          const rect=node.getBoundingClientRect();
          const target=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
          return {top:rect.top,bottom:rect.bottom,left:rect.left,right:rect.right,
            withinViewport:rect.width>0&&rect.height>0&&rect.top>=0&&rect.left>=0&&rect.bottom<=innerHeight&&rect.right<=innerWidth,
            uncovered:target===node||node.contains(target)};
        });
        if(!feedback.withinViewport||!feedback.uncovered)throw Error(`${name}/${action} error is not visible without scrolling: ${JSON.stringify(feedback)}`);
        if(await draft().inputValue()!==text)throw Error(`${name}/${action} changed the entered JSON`);
        await assertNoMutation(before,`${name}/${action}`);
        report.draft_failures.push({name,action,message,text_preserved:true,feedback_visible_without_scrolling:true});
      }
    }
    await page.waitForTimeout(200);await page.screenshot({path:path.join(output,'draft-json-error.png'),fullPage:true});
    report.checks.push('Empty, whitespace, incomplete, array, null and scalar drafts are safely rejected by Validate, Preview, Launch and Export without changing text or sending API work');

    // I14 protects unfinished JSON until its explicit discard action.
    await page.getByTestId('config-discard-json').click();
    await page.getByTestId('config-preset').selectOption('small');
    await page.getByTestId('config-validate').click();
    await until(async()=>/Valid configuration/.test(await page.getByTestId('config-result').innerText()),'small preset validation');
    const small=await page.evaluate(()=>window.__zombieInspection.configuration.draft);
    if(small.population.humans+small.population.zombies!==20)throw Error('Small preset was not restored');
    await page.getByTestId('config-preset').selectOption('baseline');
    const baseline=JSON.parse(await draft().inputValue());
    if(baseline.population.humans+baseline.population.zombies!==1000)throw Error('Baseline metadata preset changed');
    await page.getByTestId('config-validate').click();
    await until(async()=>/Valid configuration/.test(await page.getByTestId('config-result').innerText()),'baseline validation');
    report.checks.push('Preset switching clears stale parser errors; actual small and ontology-baseline presets validate successfully');

    const launchConfig={...metadata.presets.small,scenario:'issue3_real_launch',seed:321,horizon:30,
      execution:{workers:1},checkpoint_interval:1000};
    await draft().fill(JSON.stringify(launchConfig,null,2));
    await page.getByTestId('config-validate').click();
    await until(async()=>/Valid configuration/.test(await page.getByTestId('config-result').innerText()),'corrected draft validation');
    const beforePreview=await audit();
    await page.getByTestId('config-preview').click();
    await page.waitForFunction(()=>!!window.__zombieInspection.configuration.preview);
    const preview=await page.evaluate(()=>window.__zombieInspection.configuration.preview);
    if(preview.metrics.populations.total!==20)throw Error('Real preview population is incorrect');
    if(JSON.stringify(await audit())!==JSON.stringify(beforePreview))throw Error('Preview mutated managed simulations');
    await page.waitForTimeout(200);await page.screenshot({path:path.join(output,'valid-preview.png'),fullPage:true});
    const download=page.waitForEvent('download');await page.getByTestId('config-export').click();
    const exported=await download;const exportPath=path.join(output,'valid-draft-export.json');await exported.saveAs(exportPath);
    if(JSON.parse(fs.readFileSync(exportPath,'utf8')).scenario!==launchConfig.scenario)throw Error('Valid draft export differs from draft');
    report.checks.push('Corrected draft supports real validation, isolated 20-agent preview and valid JSON export');

    const beforeLaunch=(await diagnostic()).runs.length;
    const creation=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/runs'&&response.request().method()==='POST');
    await page.getByTestId('config-launch').click();const accepted=await creation;
    if(accepted.status()!==202)throw Error('Launch lost the I02 immediate acceptance handoff');
    const created=await accepted.json();
    await page.waitForFunction(identity=>{const app=window.__zombieInspection.app;return app.run_id===identity&&app.view?.run_id===identity&&!app.start_pending;},created.run_id);
    if((await diagnostic()).runs.length!==beforeLaunch+1)throw Error('Valid launch did not create exactly one run');
    await command(created.run_id,'terminate');
    await until(async()=>{const row=(await diagnostic()).runs.find(run=>run.id===created.run_id);return row.resource_status.cleanup_complete;},'launched worker cleanup');
    report.created_run=created.run_id;report.checks.push('Valid Launch creates one real run through HTTP202 and retains the guarded start acknowledgement flow');

    await page.locator(`button[data-run-id="${sourceId}"]`).click();
    await page.waitForFunction(identity=>window.__zombieInspection.app.view?.run_id===identity,sourceId);
    await page.getByRole('button',{name:'Edit as new run',exact:true}).click();await ready();await advanced();
    const copied=JSON.parse(await draft().inputValue());
    if(copied.scenario!=='issue3_source_copy'||copied.seed!==123)throw Error('Copy-as-new was overwritten by default metadata');
    await page.getByTestId('config-validate').click();
    await until(async()=>/Valid configuration/.test(await page.getByTestId('config-result').innerText()),'copied configuration validation');
    await close();report.checks.push('Edit as new run preserves and validates the source configuration without changing the source history');
    if(errors.length)throw Error(`Browser errors: ${JSON.stringify(errors)}`);
    report.passed=true;report.page_errors=errors;report.requests=requests;
    console.log(`I03 browser workflows PASS (${report.checks.length} checks; ${report.metadata_failures.length} metadata faults; ${report.draft_failures.length} draft/action combinations)`);
  }catch(error){
    report.error=String(error.stack||error);report.page_errors=errors;report.requests=requests;
    if(page){
      try{report.failure_state=await page.evaluate(()=>window.__zombieInspection);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}catch{}
    }
    throw error;
  }finally{
    if(page)try{await page.evaluate(()=>{for(const entry of Object.values(window.__issue3Metadata?.pending||{}))entry.resolve();});}catch{}
    fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
