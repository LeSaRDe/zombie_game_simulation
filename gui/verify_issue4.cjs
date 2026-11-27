/* I04 numeric editing against implementation_checks/issue4_check.py only. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID}=require('node:crypto');

(async()=>{
  const [base,output,sourceId,engine='chromium']=process.argv.slice(2);
  const browser=await (engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});
  const report={passed:false,engine,browser:browser.version(),checks:[],field_edits:[],blank_actions:[],domains:[]};
  const errors=[],requests=[];
  let page;
  try{
    page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('request',request=>{
      if(!request.url().includes('/api/'))return;
      let body;try{body=request.postDataJSON();}catch{}
      requests.push({method:request.method(),path:new URL(request.url()).pathname,body});
    });
    const call=async(route,body)=>{
      const response=body===undefined?await page.request.get(route):await page.request.post(route,{data:body});
      if(!response.ok())throw Error(`${route}: ${response.status()} ${await response.text()}`);
      return response.json();
    };
    const until=async(fn,label,timeout=30000)=>{
      const deadline=Date.now()+timeout;
      while(Date.now()<deadline){const value=await fn();if(value)return value;await page.waitForTimeout(25);}
      throw Error(`Timed out waiting for ${label}`);
    };
    const diagnostic=()=>call('/__issue4/diagnostics');
    const audit=()=>call('/__issue4/audit');
    const at=(value,key)=>key.split('.').reduce((node,part)=>node?.[part],value);
    const field=key=>page.getByTestId(`config-${key}`);
    const draft=()=>page.getByLabel('Advanced configuration JSON');
    const ready=()=>page.waitForFunction(()=>window.__zombieInspection.configuration.load_state?.phase==='ready');
    const open=async()=>{await page.getByRole('button',{name:/New experiment/}).click();await ready();};
    const close=async()=>{await page.getByRole('button',{name:'Close configuration',exact:true}).click();await page.getByRole('dialog',{name:'Configure your world'}).waitFor({state:'detached'});};
    const advanced=async()=>{
      const details=page.locator('details').filter({has:page.getByText('Advanced configuration · JSON',{exact:true})});
      if(!await details.evaluate(node=>node.open))await page.getByText('Advanced configuration · JSON',{exact:true}).click();
    };
    const blur=()=>page.locator('#config-title').click();
    const resetSmall=async()=>{
      // I14 requires an explicit discard before replacing unfinished JSON.
      if(await page.getByTestId('config-discard-json').count())await page.getByTestId('config-discard-json').click();
      await page.getByTestId('config-preset').selectOption('small');
      await page.getByLabel('Worker selection',{exact:true}).selectOption('manual');
      await until(async()=>await field('execution.workers').count(),'manual worker editor');
    };
    const assertNoMutation=async(before,label)=>{
      const after=await diagnostic();
      const posts=after.requests.slice(before.requests.length).filter(item=>item.method==='POST');
      if(posts.length)throw Error(`${label} submitted API work: ${JSON.stringify(posts)}`);
      if(after.runs.length!==before.runs.length)throw Error(`${label} created a run`);
    };
    const invalidInfo=async key=>{
      await until(async()=>await field(key).getAttribute('aria-invalid')==='true',`${key} field error`);
      const info=await field(key).evaluate(node=>({value:node.value,invalid:node.getAttribute('aria-invalid'),
        description:(node.getAttribute('aria-describedby')||'').split(/\s+/).filter(Boolean)
          .map(id=>document.getElementById(id)?.textContent||'').join(' ').trim()}));
      if(!info.description)throw Error(`${key} has no accessible field error`);
      return info;
    };
    const responseFor=(route)=>page.waitForResponse(response=>new URL(response.url()).pathname===route&&response.request().method()==='POST');
    const submit=async(testid,route,focused=false)=>{
      const pending=responseFor(route);
      if(focused)await page.getByTestId(testid).evaluate(node=>node.click());
      else await page.getByTestId(testid).click();
      const response=await pending;
      const body=response.request().postDataJSON(),data=await response.json();
      if(!response.ok())throw Error(`${route}: ${response.status()} ${JSON.stringify(data)}`);
      if(testid!=='config-launch')await until(async()=>!await page.getByTestId('config-validate').isDisabled(),'configuration action completion');
      return {body,data,status:response.status()};
    };
    const validate=(focused=false)=>submit('config-validate','/api/config/validate',focused);
    const setJson=async config=>{await advanced();await draft().fill(JSON.stringify(config,null,2));};
    const command=async(identity,operation)=>{
      const sent=await call(`/api/runs/${identity}/commands`,{operation,command_id:randomUUID()});
      const result=await until(async()=>{const receipt=await call(`/api/commands/${sent.command_id}`);return receipt.status==='pending'?null:receipt;},operation+' receipt');
      if(result.status!=='applied')throw Error(JSON.stringify(result));
      return result;
    };

    await page.goto(base);await page.getByTestId('run-chooser').waitFor();
    await page.waitForFunction(()=>window.__zombieInspection.app.run_list_state.phase==='ready');
    const metadata=await call('/api/config');
    const fields=metadata.fields.filter(item=>item.type!=='text');
    if(fields.length!==9)throw Error(`Expected nine numeric controls, got ${fields.length}`);
    await open();await resetSmall();
    const replacements={seed:['73','84'],horizon:['12.5','13.75'],incubation_duration:['7.25','8.5'],
      'world.length':['95.5','96.25'],'world.width':['85.5','86.25'],
      'population.humans':['18','19'],'population.zombies':['5','6'],'population.infected':['2','3'],
      'execution.workers':['2','3']};
    for(const definition of fields){
      const key=definition.path;await resetSmall();const input=field(key);
      const initial=await input.inputValue();await input.click();await input.press('End');
      for(let index=0;index<initial.length;index++)await input.press('Backspace');
      if(await input.inputValue()!=='')throw Error(`${key} inserted a value after deleting its last digit`);
      await input.pressSequentially(replacements[key][0]);
      if(await input.inputValue()!==replacements[key][0])throw Error(`${key} prefixed replacement input with zero`);
      await blur();
      if(at(JSON.parse(await draft().inputValue()),key)!==Number(replacements[key][0]))throw Error(`${key} did not commit the entered Backspace replacement`);
      await input.click();await input.press('ControlOrMeta+A');await input.press('Delete');
      if(await input.inputValue()!=='')throw Error(`${key} could not be cleared with select-all/Delete`);
      await input.pressSequentially(replacements[key][1]);await blur();
      if(at(JSON.parse(await draft().inputValue()),key)!==Number(replacements[key][1]))throw Error(`${key} did not commit the select-all replacement`);
      report.field_edits.push({path:key,backspace_replacement:replacements[key][0],select_all_replacement:replacements[key][1]});
    }
    report.checks.push('All nine numeric controls support repeated Backspace and select-all/Delete, blank text and replacement without an injected zero');

    await page.evaluate(()=>localStorage.setItem('zombie-draft','issue4 prior saved draft'));
    for(const definition of fields){
      const key=definition.path;await resetSmall();await field(key).fill('');await blur();
      const info=await invalidInfo(key);
      if(info.value!=='')throw Error(`${key} restored a numeric value on blank blur`);
      for(const action of ['config-validate','config-preview','config-launch','config-export','config-save']){
        await resetSmall();await field(key).fill('');
        const before=await diagnostic(),saved=await page.evaluate(()=>localStorage.getItem('zombie-draft'));
        // Native HTMLElement.click invokes the enabled action without causing
        // blur: this catches handlers that accidentally read old committed data.
        if(await page.getByTestId(action).isDisabled())throw Error(`${action} disabled before the new blank is checked`);
        await page.getByTestId(action).evaluate(node=>node.click());
        const error=await invalidInfo(key);
        if(error.value!=='')throw Error(`${key}/${action} overwrote unfinished text`);
        await assertNoMutation(before,`${key}/${action}`);
        if(await page.evaluate(()=>localStorage.getItem('zombie-draft'))!==saved)throw Error(`${key}/${action} saved the previous numeric value`);
        report.blank_actions.push({path:key,action,text_preserved:true,error:error.description,no_api_work:true});
      }
    }
    report.checks.push('Blank blur and 45 focused action attempts expose field errors, preserve blanks, submit no API work and never save stale numeric values');

    await resetSmall();await field('horizon').fill('');
    const beforeMouse=await diagnostic();await page.getByTestId('config-validate').click();
    await invalidInfo('horizon');await assertNoMutation(beforeMouse,'mouse blur/submission');
    await field('horizon').fill('');const beforeKeyboard=await diagnostic();
    await page.getByTestId('config-validate').focus();await page.keyboard.press('Enter');
    await invalidInfo('horizon');await assertNoMutation(beforeKeyboard,'keyboard submission');
    await field('horizon').scrollIntoViewIfNeeded();await page.waitForTimeout(200);
    await page.screenshot({path:path.join(output,'blank-field-error.png'),fullPage:true});
    report.checks.push('Native mouse blur/click and keyboard submission cannot send an empty field as its old value');

    const allowedZero=['seed','population.humans','population.zombies','population.infected'];
    for(const key of allowedZero){
      await resetSmall();await field(key).fill('0');const {body}=await validate();
      if(at(body,key)!==0||await field(key).inputValue()!=='0')throw Error(`${key} confused allowed zero with missing input`);
      report.domains.push({path:key,text:'0',accepted:true});
    }
    const invalidNumbers=[
      ...['horizon','incubation_duration','world.length','world.width','execution.workers'].map(key=>[key,'0']),
      ...['seed','population.humans','population.zombies','population.infected','execution.workers'].map(key=>[key,'1.5']),
      ...['seed','population.humans','horizon'].map(key=>[key,'-1']),
      ...['-','+','.','1e','1e+','NaN','Infinity','1e309','0x10'].map(text=>['horizon',text]),
    ];
    for(const [key,text] of invalidNumbers){
      await resetSmall();await field(key).fill(text);const before=await diagnostic();
      await page.getByTestId('config-validate').evaluate(node=>node.click());await invalidInfo(key);
      if(await field(key).inputValue()!==text)throw Error(`${key} rewrote invalid numeric text ${text}`);
      await assertNoMutation(before,`${key}=${text}`);report.domains.push({path:key,text,accepted:false});
    }
    for(const [key,text,value] of [['horizon','2.',2],['horizon','1e2',100],['seed','1e2',100],['horizon','0.0001',.0001],
      ['incubation_duration','0.0001',.0001],['world.length','0.5',.5],['world.width','0.5',.5]]){
      await resetSmall();await field(key).fill(text);const {body}=await validate();
      if(at(body,key)!==value)throw Error(`${key} narrowed the backend numeric domain for ${text}`);
      report.domains.push({path:key,text,accepted:true,value});
    }
    report.checks.push('Allowed zero, positive domains, integer constraints, decimals, finite values and complete exponent syntax retain backend numeric semantics');

    await resetSmall();await field('seed').fill('');await field('horizon').fill('');await blur();
    await invalidInfo('seed');await invalidInfo('horizon');
    await field('seed').fill('121');await blur();
    if(await field('horizon').inputValue()!=='')throw Error('Editing another number erased the pending blank horizon');
    const beforeMultiple=await diagnostic();await page.getByTestId('config-preview').evaluate(node=>node.click());
    await invalidInfo('horizon');await assertNoMutation(beforeMultiple,'remaining pending number');
    report.checks.push('Multiple unfinished numeric edits survive other edits; fixing one cannot submit another stale value');

    await page.getByTestId('config-preset').selectOption('baseline');
    for(const definition of fields.filter(item=>item.path!=='execution.workers')){
      const key=definition.path;
      if(Number(await field(key).inputValue())!==at(metadata.presets.baseline,key))throw Error(`Baseline did not replace ${key} text`);
      if(await field(key).getAttribute('aria-invalid')==='true')throw Error(`Baseline retained ${key} errors`);
    }
    await resetSmall();
    await field('execution.workers').fill('');await blur();await invalidInfo('execution.workers');
    await page.getByLabel('Worker selection',{exact:true}).selectOption('auto');
    if(await field('execution.workers').count())throw Error('Manual worker field remains in auto mode');
    const automatic=await validate();if(automatic.body.execution.workers!=='auto')throw Error('Auto mode submitted a stale manual worker value');
    await page.getByLabel('Worker selection',{exact:true}).selectOption('manual');
    if(!Number.isInteger(Number(await field('execution.workers').inputValue()))||Number(await field('execution.workers').inputValue())<1)throw Error('Manual mode did not initialize usable worker text');
    if(await field('execution.workers').getAttribute('aria-invalid')==='true')throw Error('Manual mode restored a stale error');
    report.checks.push('Preset switches and auto/manual worker selection reset pending text and stale field errors consistently');

    const imported={...metadata.presets.small,scenario:'issue4_imported',seed:541,horizon:18.75,incubation_duration:9.25,
      world:{...metadata.presets.small.world,length:123.5,width:112.25},execution:{workers:2}};
    const importPath=path.join(output,'imported-config.json');fs.writeFileSync(importPath,JSON.stringify(imported));
    await field('seed').fill('');await blur();await advanced();
    const importResponse=responseFor('/api/config/import');await page.getByTestId('config-import').setInputFiles(importPath);await importResponse;
    await until(async()=>await field('seed').inputValue()==='541','imported numeric buffers');
    for(const definition of fields){
      const key=definition.path;if(Number(await field(key).inputValue())!==at(imported,key))throw Error(`Import did not replace ${key}`);
      if(await field(key).getAttribute('aria-invalid')==='true')throw Error(`Import retained ${key} error`);
    }
    const importedValidation=await validate();
    for(const definition of fields)if(at(importedValidation.body,definition.path)!==at(imported,definition.path))throw Error('Import validation disagreed with visible numeric text');
    report.checks.push('Import replaces every numeric buffer and validates the imported values without preserving old edit errors');

    await field('seed').fill('');await blur();
    const jsonReplacement={...imported,scenario:'issue4_json_replacement',seed:777,horizon:11.5};
    await setJson(jsonReplacement);const replacement=await validate();
    if(replacement.body.seed!==777||replacement.body.horizon!==11.5)throw Error('Stale numeric buffers overwrote new Advanced JSON');
    if(await field('seed').inputValue()!=='777'||Number(await field('horizon').inputValue())!==11.5)throw Error('Successful JSON validation did not refresh visible numeric values');
    await setJson({});const partial=await validate();
    if(Object.keys(partial.body).length)throw Error('Untouched missing fields in a partial JSON object gained stale numeric values');
    for(const text of ['', '{', 'null']){
      await draft().fill(JSON.stringify(jsonReplacement));await draft().fill(text);const before=await diagnostic();
      await page.getByTestId('config-validate').click();
      await until(async()=>/complete JSON|JSON object/.test(await page.getByTestId('config-result').innerText()),'I03 JSON error');
      if(await draft().inputValue()!==text)throw Error('Numeric integration changed invalid Advanced JSON');
      await assertNoMutation(before,'I03 malformed JSON regression');
    }
    report.checks.push('Explicit Advanced JSON replaces pending numeric edits; partial objects preserve defaults and I03 malformed-JSON guards remain intact');

    await resetSmall();
    const expected={seed:907,horizon:25.5,incubation_duration:8.25,'world.length':105.5,'world.width':95.25,
      'population.humans':12,'population.zombies':3,'population.infected':2,'execution.workers':2};
    for(const [key,value] of Object.entries(expected))await field(key).fill(String(value));
    const focusedValidation=await validate(true);
    for(const [key,value] of Object.entries(expected))if(at(focusedValidation.body,key)!==value)throw Error(`Focused submission missed ${key}`);
    await field('horizon').fill('26.5');expected.horizon=26.5;
    const mouseValidation=await validate();
    for(const [key,value] of Object.entries(expected))if(at(mouseValidation.body,key)!==value)throw Error(`Blur/click validation missed ${key}`);
    const beforePreview=await audit();
    const preview=await submit('config-preview','/api/config/preview',true);
    for(const [key,value] of Object.entries(expected))if(at(preview.body,key)!==value)throw Error(`Preview missed ${key}`);
    if(preview.data.view.metrics.populations.total!==15)throw Error('Real preview disagreed with edited counts');
    if(JSON.stringify(await audit())!==JSON.stringify(beforePreview))throw Error('Numeric preview changed managed history');
    const download=page.waitForEvent('download');const exported=await submit('config-export','/api/config/export',true);
    const artifact=await download;const exportPath=path.join(output,'numeric-draft-export.json');await artifact.saveAs(exportPath);
    const exportConfig=JSON.parse(fs.readFileSync(exportPath,'utf8'));
    for(const [key,value] of Object.entries(expected))if(at(exported.body.config,key)!==value||at(exportConfig,key)!==value)throw Error(`Export missed ${key}`);
    await field('horizon').scrollIntoViewIfNeeded();await page.waitForTimeout(200);
    await page.screenshot({path:path.join(output,'corrected-numeric-draft.png'),fullPage:true});
    report.payload_values=expected;
    report.checks.push('Focused and mouse submissions, real preview and JSON export use exactly the displayed values across all nine fields');

    const beforeLaunch=(await diagnostic()).runs.length;
    const pending=responseFor('/api/runs');await page.getByTestId('config-launch').evaluate(node=>node.click());
    const response=await pending,creation=await response.json();
    if(response.status()!==202)throw Error('I02 immediate creation handoff changed');
    const launchBody=response.request().postDataJSON();
    for(const [key,value] of Object.entries(expected))if(at(launchBody.config,key)!==value)throw Error(`Launch missed ${key}`);
    await page.waitForFunction(identity=>{const app=window.__zombieInspection.app;return app.run_id===identity&&app.view?.run_id===identity&&!app.start_pending;},creation.run_id);
    if((await diagnostic()).runs.length!==beforeLaunch+1)throw Error('Valid numeric launch did not create exactly one run');
    await command(creation.run_id,'terminate');
    await until(async()=>(await diagnostic()).runs.find(run=>run.id===creation.run_id).resource_status.cleanup_complete,'numeric launch cleanup');
    report.created_run=creation.run_id;
    report.checks.push('Valid numeric Launch creates exactly one real run through HTTP 202 with the same values and guarded start acknowledgement');

    await page.locator(`button[data-run-id="${sourceId}"]`).click();
    await page.waitForFunction(identity=>window.__zombieInspection.app.view?.run_id===identity,sourceId);
    const source=(await diagnostic()).runs.find(run=>run.id===sourceId);
    await page.getByRole('button',{name:'Edit as new run',exact:true}).click();await ready();
    for(const definition of fields){
      const key=definition.path;if(Number(await field(key).inputValue())!==at(source.config,key))throw Error(`Copy did not restore ${key}`);
    }
    await field('seed').fill('');await blur();await page.getByTestId('config-preset').selectOption('baseline');
    await page.getByTestId('config-preset').selectOption('copy');
    if(await field('seed').inputValue()!=='123'||await field('seed').getAttribute('aria-invalid')==='true')throw Error('Copy preset retained earlier text or error');
    const copied=await validate();
    for(const definition of fields)if(at(copied.body,definition.path)!==at(source.config,definition.path))throw Error('Copy validation disagreed with source values');
    await close();report.checks.push('Edit as new run and the copy preset reset numeric buffers without altering the original run');

    if(errors.length)throw Error(`Browser errors: ${JSON.stringify(errors)}`);
    report.passed=true;report.page_errors=errors;report.requests=requests;
    console.log(`I04 browser workflows PASS (${report.checks.length} checks; ${report.field_edits.length} fields; ${report.blank_actions.length} blank/action combinations; ${report.domains.length} domain cases)`);
  }catch(error){
    report.error=String(error.stack||error);report.page_errors=errors;report.requests=requests;
    if(page)try{report.failure_state=await page.evaluate(()=>window.__zombieInspection);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}catch{}
    throw error;
  }finally{
    fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
