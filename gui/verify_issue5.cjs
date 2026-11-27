/* I05 role allocation against the disposable issue5_check.py service only. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID}=require('node:crypto');
const assert=require('node:assert/strict');

(async()=>{
  const [base,output,sourceId,engine='chromium']=process.argv.slice(2);
  const browser=await (engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});
    const report={passed:false,engine,browser:browser.version(),checks:[],blank_actions:[],invalid_targets:[],allocation_cases:[]};
  const errors=[],requests=[];let page;
  const roles={Human:['DOCTOR','WARRIOR','SCOUT','ENGINEER'],Zombie:['TYRANT','RUNNER','SPITTER','SCREAMER']};
  const populationKey={Human:'humans',Zombie:'zombies'},rolesKey={Human:'human_roles',Zombie:'zombie_roles'};
  try{
    page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('request',request=>{if(!request.url().includes('/api/'))return;let body;try{body=request.postDataJSON();}catch{}requests.push({method:request.method(),path:new URL(request.url()).pathname,body});});
    const until=async(fn,label,timeout=30000)=>{const deadline=Date.now()+timeout;while(Date.now()<deadline){const value=await fn();if(value)return value;await page.waitForTimeout(25);}throw Error(`Timed out waiting for ${label}`);};
    const call=async(route,body)=>{const response=body===undefined?await page.request.get(route):await page.request.post(route,{data:body});if(!response.ok())throw Error(`${route}: ${response.status()} ${await response.text()}`);return response.json();};
    const diagnostic=()=>call('/__issue5/diagnostics'),audit=()=>call('/__issue5/audit');
    const field=key=>page.getByTestId(`config-${key}`),role=(kind,id)=>page.getByTestId(`role-${kind}-${id}`);
    const draft=()=>page.getByLabel('Advanced configuration JSON');
    const config=async()=>JSON.parse(await draft().inputValue());
    const ready=()=>page.waitForFunction(()=>window.__zombieInspection.configuration.load_state?.phase==='ready');
    const open=async()=>{await page.getByRole('button',{name:/New experiment/}).click();await ready();};
    const close=async()=>{await page.getByRole('button',{name:'Close configuration',exact:true}).click();await page.getByRole('dialog',{name:'Configure your world'}).waitFor({state:'detached'});};
    const advanced=async()=>{const summary=page.getByText('Advanced configuration · JSON',{exact:true});const details=page.locator('details').filter({has:summary});if(!await details.evaluate(node=>node.open))await summary.click();};
    const blur=()=>page.locator('#config-title').click();
    const reset=async(preset='small')=>{await page.getByTestId('config-preset').selectOption(preset);await until(async()=>await role('Human','DOCTOR').count(),'role controls');};
    const responseFor=route=>page.waitForResponse(response=>new URL(response.url()).pathname===route&&response.request().method()==='POST');
    const submit=async(testid,route,focused=false)=>{const pending=responseFor(route);if(focused)await page.getByTestId(testid).evaluate(node=>node.click());else await page.getByTestId(testid).click();const response=await pending;const body=response.request().postDataJSON(),data=await response.json();if(!response.ok())throw Error(`${route}: ${response.status()} ${JSON.stringify(data)}`);if(testid!=='config-launch')await until(async()=>!await page.getByTestId('config-validate').isDisabled(),'action completion');return {body,data,status:response.status()};};
    const validate=(focused=false)=>submit('config-validate','/api/config/validate',focused);
    const noWork=async(before,label)=>{const after=await diagnostic();assert.deepEqual(after.requests.slice(before.requests.length).filter(item=>item.method==='POST'),[],`${label}: unexpected API work`);assert.equal(after.runs.length,before.runs.length,`${label}: created run`);};
    const roleError=async(kind,id)=>{const input=role(kind,id);await until(async()=>await input.getAttribute('aria-invalid')==='true',`${kind}/${id} accessible error`);const description=await input.evaluate(node=>(node.getAttribute('aria-describedby')||'').split(/\s+/).filter(Boolean).map(id=>document.getElementById(id)?.textContent||'').join(' '));assert.ok(description.trim(),`${kind}/${id}: missing error description`);return description;};
    const assertCounts=async(kind,expected,label)=>{
      const current=await config(),total=current.population[populationKey[kind]],actual=current.population[rolesKey[kind]]||{};
      assert.deepEqual(roles[kind].map(id=>actual[id]||0),expected.slice(1),`${label}: role map`);
      assert.equal(total-Object.values(actual).reduce((a,b)=>a+b,0),expected[0],`${label}: no-role remainder`);
      for(const [index,id] of ['unassigned',...roles[kind]].entries())assert.equal(Number(await page.getByTestId(`role-count-${kind}-${id}`).innerText()),expected[index],`${label}: visible ${id} count`);
      assert.equal(expected.reduce((a,b)=>a+b,0),total,`${label}: total`);
      report.allocation_cases.push({label,kind,total,expected,config:current});
      return current;
    };
    const editPopulation=async(kind,value)=>{await field(`population.${populationKey[kind]}`).fill(String(value));await blur();};
    const editRole=async(kind,id,value)=>{await role(kind,id).fill(String(value));await blur();};
    const importConfig=async(value,name='import.json')=>{
      await advanced();const file=path.join(output,name);fs.writeFileSync(file,typeof value==='string'?value:JSON.stringify(value,null,2));
      const pending=responseFor('/api/config/import');await page.getByTestId('config-import').setInputFiles(file);const response=await pending;
      await until(async()=>!await page.getByTestId('config-validate').isDisabled(),'import completion');return {response,file};
    };
    const command=async(id,operation)=>{const sent=await call(`/api/runs/${id}/commands`,{operation,command_id:randomUUID()});const result=await until(async()=>{const receipt=await call(`/api/commands/${sent.command_id}`);return receipt.status==='pending'?null:receipt;},operation);assert.equal(result.status,'applied');};
    await page.goto(base);await page.getByTestId('run-chooser').waitFor();await page.waitForFunction(()=>window.__zombieInspection.app.run_list_state.phase==='ready');
    const metadata=await call('/api/config');await open();await reset('baseline');
    assert.deepEqual((await validate()).data.resolved.population,metadata.presets.baseline.population,'Unedited baseline role counts changed');
    await assertCounts('Human',[400,80,120,80,120],'baseline Human');await assertCounts('Zombie',[120,20,30,20,10],'baseline Zombie');
    await editPopulation('Human',100);await editPopulation('Zombie',10);
    await assertCounts('Human',[50,10,15,10,15],'resized baseline Human');await assertCounts('Zombie',[6,1,2,1,0],'resized baseline Zombie tie');
    const baseline=(await validate()).data.resolved;await field('seed').fill('427');await blur();
    assert.deepEqual((await validate()).data.resolved.population,baseline.population,'Seed changed count allocation');
    report.checks.push('Baseline counts stay unchanged; population edits recalculate both types including deterministic fractional ties, independently of seed');

    for(const partial of [{preset:'baseline'},{scenario:'baseline_v0.1'}]){
      await importConfig(partial,`partial-baseline-${partial.preset?'preset':'scenario'}.json`);
      assert.equal(Number(await field('population.humans').inputValue()),800,'Partial baseline Humans must reflect effective defaults');
      assert.equal(Number(await field('population.zombies').inputValue()),200,'Partial baseline Zombies must reflect effective defaults');
      for(const [kind,targets] of [['Human',[10,15,10,15]],['Zombie',[10,15,10,5]]])for(const [index,id] of roles[kind].entries())assert.equal(Number(await role(kind,id).inputValue()),targets[index],`${kind}/${id}: partial baseline target`);
      assert.deepEqual((await validate()).data.resolved.population,metadata.presets.baseline.population,'Partial baseline effective counts changed');
      await editPopulation('Human',100);await assertCounts('Human',[50,10,15,10,15],'partial baseline resized Human targets');
    }
    report.checks.push('Partial baseline imports show effective ontology population and shares; resizing uses those shares without requiring Launch of a missing-seed draft');

    await reset();await editPopulation('Human',7);await editRole('Human','DOCTOR','10');
    await assertCounts('Human',[6,1,0,0,0],'seven Humans at ten percent Doctor');
    const realized=await page.getByTestId('role-realized-Human-DOCTOR').innerText();assert.match(realized,/≈.*14\.29/,'Rounded realized percentage must be marked and visible');
    assert.equal(Number(await role('Human','DOCTOR').inputValue()),10);
    await role('Human','DOCTOR').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'rounded-target-and-count.png'),fullPage:true});
    await editRole('Human','DOCTOR','50');await editPopulation('Human',1);await assertCounts('Human',[1,0,0,0,0],'no-role wins exact tie');
    await editPopulation('Human',2);await assertCounts('Human',[1,1,0,0,0],'two Humans preserve fifty percent target');
    await reset();await editPopulation('Human',20);await editPopulation('Zombie',20);
    for(const kind of Object.keys(roles))for(const id of roles[kind])await editRole(kind,id,'12.5');
    await assertCounts('Human',[10,3,3,2,2],'all Human roles with ontology-order tie');await assertCounts('Zombie',[10,3,3,2,2],'all Zombie roles with ontology-order tie');
    for(const kind of Object.keys(roles)){
      await editPopulation(kind,0);await assertCounts(kind,[0,0,0,0,0],`${kind} zero population`);
      for(const id of ['unassigned',...roles[kind]])assert.equal((await page.getByTestId(`role-realized-${kind}-${id}`).innerText()).trim(),'—');
      for(const id of roles[kind])assert.equal(Number(await role(kind,id).inputValue()),12.5,'Zero population lost requested target');
      await editPopulation(kind,8);await assertCounts(kind,[4,1,1,1,1],`${kind} restore from zero`);
    }
    report.checks.push('Seven-agent rounding, no-role/role tie ordering, all eight role controls and zero-population target retention stay consistent');

    const repeating=structuredClone(metadata.presets.small);repeating.scenario='issue5_exact_import';repeating.population={humans:3,zombies:0,infected:0,human_roles:{DOCTOR:1},zombie_roles:{}};
    await importConfig(repeating,'repeating-share.json');
    await assertCounts('Human',[2,1,0,0,0],'import one Doctor among three');
    assert.deepEqual((await validate()).body.population,repeating.population,'No-op validation rewrote imported exact counts');
    await field('seed').fill('871');await blur();await assertCounts('Human',[2,1,0,0,0],'unrelated edit preserves repeating import');
    await editPopulation('Human',300);await assertCounts('Human',[200,100,0,0,0],'repeating share uses exact one-third');
    const thirds=await config();assert.deepEqual(thirds.gui.role_allocation.Human.targets.DOCTOR,{numerator:'1',denominator:'3'});
    await editPopulation('Human',3);await assertCounts('Human',[2,1,0,0,0],'return to imported population');
    assert.equal((await config()).gui.role_allocation.Zombie.targets.unassigned.numerator,'1','Imported zero population should start no-role');
    report.checks.push('Unchanged imported integer maps remain exact; one-of-three targets retain rational precision through resizing, and imported zero populations default to no-role');

    for(const kind of Object.keys(roles))for(const id of roles[kind]){
      await reset();const input=role(kind,id);await input.click();await input.press('End');
      for(let i=0,n=(await input.inputValue()).length;i<n;i++)await input.press('Backspace');
      assert.equal(await input.inputValue(),'');await input.pressSequentially('12.5');assert.equal(await input.inputValue(),'12.5');await blur();
      await input.click();await input.press('ControlOrMeta+A');await input.press('Delete');assert.equal(await input.inputValue(),'');await input.pressSequentially('25');assert.equal(await input.inputValue(),'25');await blur();
    }
    report.checks.push('All eight percentage controls support repeated Backspace and select-all/Delete replacement without an injected zero');
    const actions=['config-validate','config-preview','config-launch','config-export','config-save'];
    await page.evaluate(()=>localStorage.setItem('zombie-draft','issue5 saved sentinel'));
    for(const kind of Object.keys(roles))for(const id of roles[kind])for(const action of actions){
      await reset();await role(kind,id).fill('');const before=await diagnostic();const saved=await page.evaluate(()=>localStorage.getItem('zombie-draft'));
      assert.equal(await page.getByTestId(action).isDisabled(),false,`${kind}/${id}/${action} prematurely disabled`);
      await page.getByTestId(action).evaluate(node=>node.click());const description=await roleError(kind,id);
      assert.equal(await role(kind,id).inputValue(),'');await noWork(before,`${kind}/${id}/${action}`);
      assert.equal(await page.evaluate(()=>localStorage.getItem('zombie-draft')),saved,'Invalid target overwrote saved draft');
      report.blank_actions.push({kind,role:id,action,error:description});
    }
    for(const text of ['-1','101','100.0000000000000000000001','NaN','Infinity','1e309','1e','1e+','.','0x10']){
      await reset();await role('Human','DOCTOR').fill(text);const before=await diagnostic();await page.getByTestId('config-validate').evaluate(node=>node.click());
      await roleError('Human','DOCTOR');assert.equal(await role('Human','DOCTOR').inputValue(),text);await noWork(before,`invalid ${text}`);report.invalid_targets.push(text);
    }
    await reset();await editRole('Human','DOCTOR','60');await role('Human','WARRIOR').fill('60');await blur();
    await until(async()=>/100|sum|total/i.test(await page.getByTestId('config-result').innerText()),'total percentage error');
    const overflow=await diagnostic();await page.getByTestId('config-preview').evaluate(node=>node.click());await noWork(overflow,'target overflow');
    assert.equal(await role('Human','WARRIOR').inputValue(),'60');await editRole('Human','WARRIOR','20');await assertCounts('Human',[3,10,3,0,0],'correction after total overflow');
    await reset();await editRole('Human','DOCTOR','1e1');await assertCounts('Human',[14,2,0,0,0],'complete scientific percent syntax');
    await editRole('Human','DOCTOR','100');await assertCounts('Human',[0,16,0,0,0],'one hundred percent role');
    await reset();await editRole('Human','DOCTOR','0.0000000000000001');await assertCounts('Human',[16,0,0,0,0],'tiny positive exact target');
    assert.deepEqual((await config()).gui.role_allocation.Human.targets.DOCTOR,{numerator:'1',denominator:'1000000000000000000'},'Tiny positive target lost decimal precision');
    await reset();for(const [index,id] of roles.Human.entries())await editRole('Human',id,['10.1','20.2','30.3','39.4'][index]);
    await assertCounts('Human',[0,2,3,5,6],'decimal targets sum exactly one hundred');
    report.checks.push('All eight blank target fields block five actions without API work; invalid syntax/ranges and totals above 100% remain editable until corrected');

    await reset();await field('population.humans').fill('');await role('Human','DOCTOR').fill('50');await blur();
    const incomplete=await diagnostic();await page.getByTestId('config-validate').evaluate(node=>node.click());await noWork(incomplete,'blank population with target');
    assert.equal(await field('population.humans').inputValue(),'');assert.equal(await role('Human','DOCTOR').inputValue(),'50');
    await field('population.humans').fill('6');await blur();await assertCounts('Human',[3,3,0,0,0],'atomic population plus role correction');
    await role('Human','DOCTOR').fill('');await role('Zombie','TYRANT').fill('');await blur();await roleError('Human','DOCTOR');await roleError('Zombie','TYRANT');
    await role('Human','DOCTOR').fill('25');await blur();assert.equal(await role('Zombie','TYRANT').inputValue(),'');
    const remaining=await diagnostic();await page.getByTestId('config-save').evaluate(node=>node.click());await noWork(remaining,'second pending role');
    await role('Zombie','TYRANT').fill('25');const keyboardResponse=responseFor('/api/config/validate');await page.getByTestId('config-validate').focus();await page.keyboard.press('Enter');assert.equal((await keyboardResponse).ok(),true,'Keyboard validation failed');await until(async()=>!await page.getByTestId('config-validate').isDisabled(),'keyboard validation completion');
    await assertCounts('Human',[5,1,0,0,0],'corrected Human pending target');await assertCounts('Zombie',[3,1,0,0,0],'corrected Zombie pending target');
    await role('Human','DOCTOR').fill('');await page.getByTestId('config-validate').click();await roleError('Human','DOCTOR');
    await role('Human','DOCTOR').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'invalid-role-target.png'),fullPage:true});
    await reset('baseline');await assertCounts('Human',[400,80,120,80,120],'preset resets pending target');
    await role('Human','DOCTOR').fill('');await blur();await advanced();await draft().fill(JSON.stringify(repeating));
    assert.deepEqual((await validate()).body.population,repeating.population,'Pending role text overrode newer Advanced JSON');
    report.checks.push('Numeric and role edits commit atomically; errors survive other edits; native mouse/keyboard submission and preset replacement use current text');

    await reset();const beforeImport=await config();
    const invalidImports=[['incompatible',{human_roles:{TYRANT:1}}],['overallocated',{human_roles:{DOCTOR:17}}],['negative',{human_roles:{DOCTOR:-1}}],['fractional',{human_roles:{DOCTOR:1.5}}]];
    for(const [label,patch] of invalidImports){const bad=structuredClone(metadata.presets.small);Object.assign(bad.population,patch);await importConfig(bad,`invalid-${label}.json`);await until(async()=>await page.getByTestId('config-result').getAttribute('role')==='alert',`${label} import error`);assert.deepEqual(await config(),beforeImport,`${label} import replaced the usable draft`);}
    const imprecise=structuredClone(metadata.presets.small);imprecise.population.humans=1e20;imprecise.population.human_roles={DOCTOR:1};
    await importConfig(imprecise,'imprecise-role-remainder.json');await until(async()=>/exact|precision|represent/i.test(await page.getByTestId('config-result').innerText()),'unrepresentable integer remainder error');assert.deepEqual(await config(),beforeImport,'Precision-losing import replaced usable draft');
    await field('population.infected').fill('3');await blur();await editPopulation('Human',2);const pendingInfection=responseFor('/api/config/validate');await page.getByTestId('config-validate').click();const infectionResponse=await pendingInfection;assert.equal(infectionResponse.ok(),false);assert.equal((await config()).population.infected,3,'Population reduction silently clamped infection');
    report.checks.push('Incompatible, overallocated, negative and fractional imported role counts are rejected; infected Humans remain an independent constrained subset');

    const explicit={scenario:'issue5_explicit_agents',seed:592,agents:[{id:'explicit-human',type:'Human',role:'DOCTOR',x:10,y:10},{id:'explicit-zombie',type:'Zombie',x:40,y:40}]};
    await importConfig(explicit,'explicit-agents.json');
    assert.equal(Number(await field('population.humans').inputValue()),1,'Explicit Human count must be derived');assert.equal(Number(await field('population.zombies').inputValue()),1,'Explicit Zombie count must be derived');
    assert.equal(Number(await page.getByTestId('role-count-Human-DOCTOR').innerText()),1,'Explicit Doctor count must be derived');
    for(const key of ['population.humans','population.zombies','population.infected'])assert.equal(await field(key).isDisabled(),true,`${key} must not pretend to overwrite explicit agents`);
    for(const kind of Object.keys(roles))for(const id of roles[kind])assert.equal(await role(kind,id).isDisabled(),true,`${kind}/${id} must preserve explicit assignments`);
    assert.match(await page.getByRole('dialog',{name:'Configure your world'}).innerText(),/explicit/i,'Explicit-agent editing restriction must be explained');
    assert.deepEqual((await validate()).body.agents,explicit.agents,'Unedited explicit identities changed');
    report.checks.push('Explicit-agent scenarios explain and disable population/role reallocation while preserving individual identities and assignments');

    const semantic={seed:593,semantic:{population:{humans:3,zombies:0,infected:0,human_roles:{DOCTOR:1},zombie_roles:{}}}};
    await importConfig(semantic,'semantic-population.json');
    assert.equal(Number(await field('population.humans').inputValue()),3,'Semantic Human count must be effective');assert.equal(Number(await field('population.zombies').inputValue()),0,'Semantic Zombie count must be effective');
    assert.equal(Number(await page.getByTestId('role-count-Human-DOCTOR').innerText()),1,'Semantic Doctor count must be effective');
    for(const key of ['population.humans','population.zombies','population.infected'])assert.equal(await field(key).isDisabled(),true,`${key}: semantic overlay must be guarded`);
    for(const kind of Object.keys(roles))for(const id of roles[kind])assert.equal(await role(kind,id).isDisabled(),true,`${kind}/${id}: semantic overlay must be guarded`);
    assert.match(await page.getByRole('dialog',{name:'Configure your world'}).innerText(),/semantic/i,'Semantic editing restriction must be explained');
    const semanticValidation=await validate();assert.deepEqual(semanticValidation.body,semantic,'Guarded semantic import raw payload changed');assert.deepEqual(semanticValidation.data.resolved.population,semantic.semantic.population,'Semantic resolved population changed');
    report.checks.push('Semantic population wrappers show effective counts and explain read-only role/population controls while preserving the raw legacy configuration');

    await reset();await editPopulation('Human',7);await editPopulation('Zombie',5);await field('population.infected').fill('2');await blur();
    await editRole('Human','DOCTOR','10');await editRole('Human','WARRIOR','20');for(const id of roles.Zombie)await editRole('Zombie',id,'20');
    await field('horizon').fill('12');await blur();await page.getByLabel('Worker selection',{exact:true}).selectOption('manual');
    await assertCounts('Human',[5,1,1,0,0],'final Human payload');await assertCounts('Zombie',[1,1,1,1,1],'final Zombie payload');
    const payload=(await validate(true)).body;report.payload=payload;
    await page.getByTestId('config-save').click();const saved=await page.evaluate(()=>localStorage.getItem('zombie-draft'));assert.deepEqual(JSON.parse(saved),payload);
    await close();await open();await page.getByTestId('config-load-saved').click();assert.deepEqual(await config(),payload,'Load saved draft lost exact targets/counts');
    await assertCounts('Human',[5,1,1,0,0],'saved/reopened Human targets');
    for(const format of ['json','toml']){
      await advanced();await page.getByTestId('config-export-format').selectOption(format);const downloading=page.waitForEvent('download');const exported=await submit('config-export','/api/config/export',true);const artifact=await downloading;const exportPath=path.join(output,`role-draft-export.${format}`);await artifact.saveAs(exportPath);
      assert.deepEqual(exported.body.config.population,payload.population);assert.deepEqual(exported.body.config.gui.role_allocation,payload.gui.role_allocation);
      await reset();await importConfig(fs.readFileSync(exportPath,'utf8'),`roundtrip.${format}`);const imported=(await validate()).data.resolved;
      assert.deepEqual(imported.population,payload.population,`${format} role count roundtrip`);assert.deepEqual(imported.gui.role_allocation,payload.gui.role_allocation,`${format} targets roundtrip`);
    }
    const mismatch=structuredClone(payload);mismatch.population.human_roles.DOCTOR=2;const beforeMismatch=await config();await importConfig(mismatch,'inconsistent-provenance.json');await until(async()=>await page.getByTestId('config-result').getAttribute('role')==='alert','provenance mismatch error');assert.deepEqual(await config(),beforeMismatch);
    await page.getByTestId('config-load-saved').click();await validate();
    report.checks.push('Save/reopen and JSON/TOML exchange retain exact targets, tie order and counts; contradictory provenance is rejected');

    const beforePreview=await audit();const preview=await submit('config-preview','/api/config/preview',true);assert.deepEqual(preview.body.population,payload.population);assert.deepEqual(preview.data.resolved.gui.role_allocation,payload.gui.role_allocation);
    const previewAgents=Object.values(preview.data.view.state.agents);assert.equal(previewAgents.length,12);
    for(const kind of Object.keys(roles)){for(const id of roles[kind])assert.equal(previewAgents.filter(a=>a.type===kind&&a.role===id).length,payload.population[rolesKey[kind]][id]);}
    assert.equal(previewAgents.filter(a=>a.type==='Human'&&a.infection_episode).length,2);assert.deepEqual(await audit(),beforePreview,'Preview mutated existing managed history');
    report.preview={resolved:preview.data.resolved,counts:preview.data.view.metrics.populations};
    await page.getByTestId('role-panel-Zombie').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'role-preview.png'),fullPage:true});
    const beforeLaunch=(await diagnostic()).runs.length;const pending=responseFor('/api/runs');await page.getByTestId('config-launch').evaluate(node=>node.click());const response=await pending;const creation=await response.json();assert.equal(response.status(),202);
    assert.deepEqual(response.request().postDataJSON().config.population,payload.population);assert.deepEqual(response.request().postDataJSON().config.gui.role_allocation,payload.gui.role_allocation);
    await page.waitForFunction(id=>{const app=window.__zombieInspection.app;return app.run_id===id&&app.view?.run_id===id&&!app.start_pending;},creation.run_id);
    assert.equal((await diagnostic()).runs.length,beforeLaunch+1);await command(creation.run_id,'terminate');await until(async()=>(await diagnostic()).runs.find(r=>r.id===creation.run_id).resource_status.cleanup_complete,'created run cleanup');report.created_run=creation.run_id;
    report.checks.push('Validate, actual Preview, export and one HTTP 202 Launch use the same role counts and provenance; preview agent roles and infection counts agree');

    await page.locator(`button[data-run-id="${sourceId}"]`).click();await page.waitForFunction(id=>window.__zombieInspection.app.view?.run_id===id,sourceId);
    const source=(await diagnostic()).runs.find(r=>r.id===sourceId);await page.getByRole('button',{name:'Edit as new run',exact:true}).click();await ready();assert.deepEqual((await validate()).body.population,source.config.population);
    await role('Human','DOCTOR').fill('');await blur();await reset('baseline');await reset('copy');assert.deepEqual((await validate()).body.population,source.config.population);await close();
    report.checks.push('Copied run configuration and copy preset preserve exact source role counts and reset unfinished targets without altering source history');
    assert.deepEqual(errors,[],'Browser page errors');report.passed=true;report.page_errors=errors;report.requests=requests;
    console.log(`I05 browser workflows PASS (${report.checks.length} groups, ${report.blank_actions.length} blank/action combinations, ${report.allocation_cases.length} allocation observations)`);
  }catch(error){report.error=String(error.stack||error);report.page_errors=errors;report.requests=requests;if(page)try{report.failure_state=await page.evaluate(()=>window.__zombieInspection);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}catch{}throw error;}
  finally{fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
