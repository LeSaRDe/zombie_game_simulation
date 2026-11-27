/* I26 independent UI checks. Geometry/spacing assertions do not use implementation helpers. */
const {chromium,firefox}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const [base,output,engine='chromium']=process.argv.slice(2);
 const {source_id:sourceId}=JSON.parse(fs.readFileSync(path.join(output,'fixture.json')));
 const report={passed:false,engine,checks:[],requests:[],errors:[]};
 const browser=await(engine==='firefox'?firefox:chromium).launch({headless:true,...(engine==='firefox'?{}:{executablePath:'/usr/bin/google-chrome'})});
 let page;
 try{
  page=await browser.newPage({baseURL:base,viewport:{width:1440,height:1100}});
  page.on('pageerror',error=>report.errors.push(String(error)));
  page.on('request',request=>{if(request.url().includes('/api/'))report.requests.push({method:request.method(),url:new URL(request.url()).pathname});});
  const clone=value=>structuredClone(value),values=value=>Array.isArray(value)?value:Object.values(value||{});
  const rect=value=>Array.isArray(value)?value:['xmin','ymin','xmax','ymax'].map(key=>value[key]);
  const near=(a,b,label)=>assert(Math.abs(a-b)<=1e-11*Math.max(1,Math.abs(a),Math.abs(b)),`${label}: ${a} != ${b}`);
  const checkGeometry=(original,current,from,to)=>{
   const sx=to[0]/from[0],sy=to[1]/from[1];
   for(const [collection,key] of [['barriers','footprint'],['shelters','interior']]){
    const old=values(original[collection]),next=values(current[collection]);assert.equal(next.length,old.length,collection+' count');
    for(const before of old){const after=next.find(item=>item.id===before.id);assert(after,collection+' identity '+before.id);const a=rect(before[key]),b=rect(after[key]);
     b.forEach((value,i)=>near(value,a[i]*(i%2?sy:sx),`${collection}.${before.id}.${i}`));
     const x=clone(before),y=clone(after);delete x[key];delete y[key];assert.deepEqual(y,x,'non-spatial '+collection+'.'+before.id);}
   }
   for(const collection of ['stockpiles','agents']){
    const old=values(original[collection]),next=values(current[collection]);assert.equal(next.length,old.length,collection+' count');
    for(const before of old){const after=next.find(item=>item.id===before.id);assert(after,collection+' identity '+before.id);near(after.x,before.x*sx,collection+'.x');near(after.y,before.y*sy,collection+'.y');
     const x=clone(before),y=clone(after);delete x.x;delete x.y;delete y.x;delete y.y;assert.deepEqual(y,x,'non-spatial '+collection+'.'+before.id);}
   }
   near(current.world.length,to[0],'world length');near(current.world.width,to[1],'world width');
  };
  const unchangedParameters=(before,after)=>{for(const key of ['population','placement','profiles','seed','horizon','incubation_duration','allow_intraspecies_combat','execution','storage','human_model','zombie_model'])assert.deepEqual(after[key],before[key],'parameter '+key);};
  const until=async(fn,label,timeout=60000)=>{const stop=Date.now()+timeout;while(Date.now()<stop){const value=await fn();if(value)return value;await page.waitForTimeout(40);}throw Error('Timed out: '+label);};
  const call=async(url,data)=>{const r=data===undefined?await page.request.get(url):await page.request.post(url,{data});assert(r.ok(),url+': '+r.status()+' '+await r.text());return r.json();};
  const state=()=>page.evaluate(()=>window.__zombieInspection.configuration);
  const draft=async()=>JSON.parse(await page.getByLabel('Advanced configuration JSON').inputValue());
  const ready=()=>page.waitForFunction(()=>window.__zombieInspection.configuration.load_state?.phase==='ready');
  const open=async()=>{await page.getByRole('button',{name:/New experiment/}).click();await ready();};
  const close=async()=>{await page.getByRole('button',{name:'Close configuration',exact:true}).click();await page.getByRole('dialog',{name:'Configure your world'}).waitFor({state:'detached'});};
  const advanced=async()=>{const summary=page.getByText('Advanced configuration · JSON',{exact:true});if(!await summary.evaluate(node=>node.parentElement.open))await summary.click();};
  const setJSON=async(config)=>{await advanced();await page.getByLabel('Advanced configuration JSON').fill(JSON.stringify(config,null,2));await page.locator('#config-title').click();};
  const baseline=async()=>{await page.getByTestId('config-preset').selectOption('small');await page.getByTestId('config-preset').selectOption('baseline');return draft();};
  const resize=async(length,width)=>{await page.getByTestId('config-world.length').fill(String(length));await page.getByTestId('config-world.length').press('Tab');await page.getByTestId('config-world.width').fill(String(width));await page.getByTestId('config-world.width').press('Tab');return draft();};
  const validate=async(expected=200)=>{const pending=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/config/validate'&&r.request().method()==='POST');await page.getByTestId('config-validate').click();const response=await pending,body=await response.json();assert.equal(response.status(),expected,JSON.stringify(body));await until(async()=>(await state()).issues.length>0||/Valid configuration/.test(await page.getByTestId('config-result').innerText()),'validation feedback');return {body,submitted:response.request().postDataJSON(),feedback:await page.getByTestId('config-result').innerText()};};
  const note=(label,data={})=>report.checks.push({label,...data});
  await page.goto(base);report.assets=await page.locator('script[src]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('src')));await open();
  assert(await page.getByTestId('config-world-resize-help').isVisible());
  const original=await baseline();
  // Each transform is checked against the original coordinates, not the helper's metadata.
  for(const dimensions of [[200,1000],[1000,200],[200,200],[333,777],[2000,1500],[1000,1000],[200,200]]){
   const current=await resize(...dimensions);checkGeometry(original,current,[1000,1000],dimensions);unchangedParameters(original,current);
   const result=await validate();checkGeometry(original,result.submitted,[1000,1000],dimensions);
   note('Baseline dimensions and full geometry',{dimensions,first_barrier:current.barriers[0],feedback:result.feedback});
  }
  assert(await page.getByTestId('config-world-resize-summary').isVisible());assert(await page.getByTestId('config-customized-baseline').isVisible());
  // Incomplete numeric values must neither resize nor issue validation requests.
  for(const invalid of ['', '-', 'Infinity', '0']){
   const before=await draft(),beforeCalls=report.requests.filter(r=>r.method==='POST'&&r.url==='/api/config/validate').length;
   await page.getByTestId('config-world.length').fill(invalid);await page.getByTestId('config-validate').click();
   assert.deepEqual(await draft(),before);assert.equal(report.requests.filter(r=>r.method==='POST'&&r.url==='/api/config/validate').length,beforeCalls);
   assert.match(await page.getByTestId('config-result').innerText(),/World length/i);note('Invalid world text preserved',{invalid,feedback:await page.getByTestId('config-result').innerText()});
   await page.getByTestId('config-world.length').fill('200');await page.getByTestId('config-world.length').press('Tab');
  }
  // An unfinished Advanced JSON document is protected from ordinary form edits.
  await advanced();const validText=await page.getByLabel('Advanced configuration JSON').inputValue();await page.getByLabel('Advanced configuration JSON').fill('{"world":');
  assert(await page.getByTestId('config-world.length').isDisabled());await page.getByTestId('config-validate').click();assert.equal(await page.getByLabel('Advanced configuration JSON').inputValue(),'{"world":');
  await page.getByLabel('Advanced configuration JSON').fill(validText);note('Incomplete Advanced JSON remains protected');
  // Saved editor provenance must survive reopening without applying a second scale.
  const saved=await draft();await page.getByTestId('config-save').click();await resize(800,600);await page.getByTestId('config-load-saved').click();assert.deepEqual(await draft(),saved);
  await resize(1000,1000);checkGeometry(original,await draft(),[1000,1000],[1000,1000]);await resize(200,200);note('Save/load and resize back to original');
  for(const format of ['json','toml']){
   await advanced();await page.getByTestId('config-export-format').selectOption(format);
   const downloadPending=page.waitForEvent('download');await page.getByTestId('config-export').click();const download=await downloadPending,file=path.join(output,'resized-world.'+format);await download.saveAs(file);
   const content=fs.readFileSync(file,'utf8'),parsed=(await call('/api/config/import',{text:content,format})).config;
   checkGeometry(original,parsed,[1000,1000],[200,200]);await resize(600,700);
   const imported=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/config/import'&&r.request().method()==='POST');
   await page.getByTestId('config-import').setInputFiles({name:'resized-world.'+format,mimeType:format==='json'?'application/json':'application/toml',buffer:Buffer.from(content)});await imported;
   await until(async()=>Number(await page.getByTestId('config-world.length').inputValue())===200,'imported world');checkGeometry(original,await draft(),[1000,1000],[200,200]);
   await resize(1000,1000);checkGeometry(original,await draft(),[1000,1000],[1000,1000]);await resize(200,200);note('Export/import retains concrete geometry and reusable reference',{format});
  }
  // Resource-only custom edits must survive an announced resize.
  const resourceCustom=await draft();resourceCustom.stockpiles[0].inventory.FOOD=99;await setJSON(resourceCustom);await resize(400,300);
  assert.equal((await draft()).stockpiles[0].inventory.FOOD,99);checkGeometry(resourceCustom,await draft(),[200,200],[400,300]);await validate();note('Custom resource quantities preserved');
  // Partial presets need effective inherited geometry before adjustment.
  await setJSON({preset:'baseline',seed:20261106,execution:{workers:1},horizon:1});
  assert.equal(await page.getByTestId('config-world.length').inputValue(),'1000');assert.equal(await page.getByTestId('config-world.width').inputValue(),'1000');
  await resize(200,200);const partial=await validate();checkGeometry(original,partial.body.resolved,[1000,1000],[200,200]);assert.equal(partial.body.resolved.population.humans,800);note('Partial baseline materializes inherited layout');
  const explicitJSON=clone(original);explicitJSON.world={...explicitJSON.world,length:200,width:200};await setJSON(explicitJSON);
  assert.deepEqual(await draft(),explicitJSON);const directResult=await validate(422);assert.match(directResult.feedback,/world bounds/);assert.deepEqual((await draft()).barriers,original.barriers);
  const directAPI=await page.request.post('/api/config/validate',{data:explicitJSON});assert.equal(directAPI.status(),422);note('Direct JSON and API values are validated without inferred resizing');
  const custom={scenario:'issue26_custom',seed:26,horizon:1,world:{length:100,width:80},execution:{workers:1},
   barriers:[{id:'block',type:'Obstacle',footprint:{xmin:40,ymin:25,xmax:50,ymax:35}}],shelters:[],stockpiles:[{id:'stock',x:70,y:60,inventory:{FOOD:7}}],
   agents:{h:{id:'h',type:'Human',x:10,y:10},z:{id:'z',type:'Zombie',x:90,y:70}},placement:{minimum_separation:2,cross_type_separation:15}};
  await setJSON(custom);await resize(200,160);checkGeometry(custom,await draft(),[100,80],[200,160]);await validate();note('Custom rectangle objects and agent maps resize together');
  const semantic={scenario:'issue26_semantic',seed:27,horizon:1,world:{length:500,width:500},barriers:[],semantic:{world:custom.world,barriers:custom.barriers,shelters:[],stockpiles:custom.stockpiles,agents:custom.agents},execution:{workers:1}};
  await setJSON(semantic);assert.equal(await page.getByTestId('config-world.length').inputValue(),'100');assert.equal(await page.getByTestId('config-world.width').inputValue(),'80');
  await resize(50,40);const semanticResult=await validate();checkGeometry(custom,semanticResult.body.resolved,[100,80],[50,40]);note('Semantic spatial overrides follow effective form edits');
  const conflict={scenario:'issue26_explicit_conflict',world:{length:100,width:100},agents:[{id:'near-a',type:'Human',x:10,y:10},{id:'near-b',type:'Human',x:14,y:10}],placement:{minimum_separation:2,cross_type_separation:15}};
  await setJSON(conflict);await validate();await resize(20,20);const conflictResult=await validate(422);assert.match(conflictResult.feedback,/near-a|near-b/);assert.match(conflictResult.feedback,/separation|spacing|apart/i);note('Definite explicit-agent spacing conflict rejected by Validate',{feedback:conflictResult.feedback});
  const runtime={scenario:'issue26_history_import',state_import:true,time:'5',world:{length:100,width:100},agents:[{id:'dead',type:'Human',x:10,y:10,life:0,status:'DEAD'}],remains:[{id:'remains',source_agent_id:'dead',x:10,y:10,biomass:4}]};
  await setJSON(runtime);const runtimeBefore=await draft(),beforeRuntimeCalls=report.requests.filter(r=>r.url==='/api/config/validate'&&r.method==='POST').length;
  await page.getByTestId('config-world.length').fill('200');await page.getByTestId('config-validate').click();assert.deepEqual(await draft(),runtimeBefore);assert.equal(report.requests.filter(r=>r.url==='/api/config/validate'&&r.method==='POST').length,beforeRuntimeCalls);
  assert.match(await page.getByTestId('config-result').innerText(),/import|histor|runtime|recorded/i);note('Historical state import preserved without partial scaling',{feedback:await page.getByTestId('config-result').innerText()});
  await setJSON(original);await close();
  // Copy as new changes only the draft, with a durable audit of the source run.
  const sourceBefore=await call('/fixture/audit/'+sourceId);await page.locator(`.sidebar button.run-card[data-run-id="${sourceId}"]`).click();
  await page.waitForFunction(id=>window.__zombieInspection.app.run_id===id&&window.__zombieInspection.app.view?.run_id===id,sourceId);
  await page.getByTestId('config-edit-new').click();await ready();const sourceDraft=await draft();await resize(200,160);checkGeometry(sourceDraft,await draft(),[100,80],[200,160]);await validate();await close();
  assert.deepEqual(await call('/fixture/audit/'+sourceId),sourceBefore);note('Copy-as-new resize leaves source config and ledger unchanged');
  // Finally exercise the actual requested baseline workflow with bounded execution.
  await open();await baseline();await resize(200,200);unchangedParameters(original,await draft());
  await page.getByTestId('config-horizon').fill('0.05');await page.getByTestId('config-horizon').press('Tab');await page.getByLabel('Worker selection',{exact:true}).selectOption('manual');
  await page.getByTestId('config-execution.workers').fill('1');await page.getByTestId('config-execution.workers').press('Tab');
  const launchDraft=await draft(),validated=await validate();checkGeometry(original,validated.submitted,[1000,1000],[200,200]);
  const previewPending=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/config/preview'&&r.request().method()==='POST',{timeout:120000});
  await page.getByTestId('config-preview').click();const previewResponse=await previewPending;assert(previewResponse.ok(),await previewResponse.text());const preview=await previewResponse.json();
  assert.deepEqual(previewResponse.request().postDataJSON(),validated.submitted);await until(async()=>(await state()).preview,'preview rendered');
  const initialOracle=(state,label)=>{
   const agents=values(state.agents),barriers=values(state.barriers),shelters=values(state.shelters),stocks=values(state.stockpiles);assert.equal(agents.length,1000);assert.equal(barriers.length,28);assert.equal(shelters.length,4);assert.equal(stocks.length,10);
   const counts={Human:0,Zombie:0,infected:0},roles={},totals={FOOD:0,MEDICAL_SUPPLY:0,MATERIAL:0};let same=Infinity,cross=Infinity;
   for(const a of agents){counts[a.type]++;if(a.infection_episode)counts.infected++;if(a.role)roles[a.role]=(roles[a.role]||0)+1;
    assert(a.x>=0&&a.x<=200&&a.y>=0&&a.y<=200);
    for(const b of barriers){if(b.type==='Gate'&&b.mode!=='CLOSED')continue;const[x0,y0,x1,y1]=rect(b.footprint);assert(!(a.x>=x0&&a.x<=x1&&a.y>=y0&&a.y<=y1),'agent in closed barrier');}
    if(a.type==='Zombie')for(const s of shelters){const[x0,y0,x1,y1]=rect(s.interior);assert(!(a.x>x0&&a.x<x1&&a.y>y0&&a.y<y1),'Zombie starts inside shelter');}
    for(const resource of Object.keys(totals))totals[resource]+=a.inventory?.[resource]||0;
   }
   for(const stock of stocks)for(const resource of Object.keys(totals))totals[resource]+=stock.inventory?.[resource]||0;
   for(let i=0;i<agents.length;i++)for(let j=i+1;j<agents.length;j++){const d=Math.hypot(agents[i].x-agents[j].x,agents[i].y-agents[j].y);if(agents[i].type===agents[j].type)same=Math.min(same,d);else cross=Math.min(cross,d);}
   assert.deepEqual(counts,{Human:800,Zombie:200,infected:20});assert.deepEqual(roles,{...original.population.human_roles,...original.population.zombie_roles});assert.deepEqual(totals,{FOOD:600,MEDICAL_SUPPLY:280,MATERIAL:400});assert(same>=2&&cross>=15);
   const reference=clone(original);reference.agents=[];
   for(const stock of reference.stockpiles)stock.reserved={FOOD:0,MEDICAL_SUPPLY:0,MATERIAL:0};
   checkGeometry(reference,{...state,agents:[]},[1000,1000],[200,200]);
   return {source:label,counts,roles,totals,minimum_same_type_distance:same,minimum_cross_type_distance:cross};
  };
  note('Independent preview initial-state oracle',initialOracle(preview.view.state,'preview'));
  fs.writeFileSync(path.join(output,'preview.json'),JSON.stringify(preview,null,2)+'\n');
  await page.locator('.config-body').evaluate(node=>node.scrollTop=0);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.screenshot({path:path.join(output,'resized-baseline-preview.png'),fullPage:true});
  await page.setViewportSize({width:390,height:950});await page.locator('.config-body').evaluate(node=>node.scrollTop=0);
  for(const testid of ['config-world-resize-help','config-world-resize-summary']){
   const box=await page.getByTestId(testid).boundingBox();assert(box&&box.x>=0&&box.x+box.width<=391,testid+' fits narrow layout');
  }
  await page.screenshot({path:path.join(output,'narrow-resize-feedback.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1100});note('Resize feedback fits390px layout');
  await resize(210,200);assert.equal((await state()).preview,undefined);await resize(200,200);
  const restored=await draft(),semanticLaunch=clone(launchDraft),semanticRestored=clone(restored);delete semanticLaunch.gui;delete semanticRestored.gui;assert.deepEqual(semanticRestored,semanticLaunch);note('Resize invalidates old preview and stable reference restores launch config');
  const launchPending=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/runs'&&r.request().method()==='POST');await page.getByTestId('config-launch').click();const launchResponse=await launchPending;assert(launchResponse.ok(),await launchResponse.text());
  const launched=await launchResponse.json(),runId=launched.run_id;report.launched_run_id=runId;report.launch_payload=launchResponse.request().postDataJSON();
  await until(async()=>{const run=(await call('/api/runs')).find(item=>item.id===runId);assert(run?.status!=='failed',JSON.stringify(run));return run&&run.status!=='initializing'&&run.frontier?.revision!==undefined;},'baseline initialization',150000);
  const initial=await call(`/api/runs/${runId}/view?time=0&revision=0`);note('Independent launched initial-state oracle',initialOracle(initial.state,'launched'));
  fs.writeFileSync(path.join(output,'launched-initial-view.json'),JSON.stringify(initial,null,2)+'\n');
  // Live views additionally materialize derived profile fields/runtime clocks.
  // Every field actually supplied by the raw preview must remain identical.
  for(const [id,expected] of Object.entries(preview.view.state.agents)){
   const actual=initial.state.agents[id];assert(actual,'Missing launched identity '+id);
   assert.deepEqual(Object.fromEntries(Object.keys(expected).map(key=>[key,actual[key]])),expected,'Preview/launch initialization fields for identity '+id);
  }
  note('All preview-provided initialization fields match launched revision0',{identities:1000});
  checkGeometry(original,report.launch_payload.config,[1000,1000],[200,200]);
  const finalRow=await until(async()=>{const run=(await call('/api/runs')).find(item=>item.id===runId);return run?.status==='completed'&&run.resource_status?.cleanup_complete?run:null;},'short baseline completion and worker cleanup',150000);
  note('Bounded real baseline execution completed',{status:finalRow.status,time:finalRow.frontier.time,revision:finalRow.frontier.revision});
  assert.deepEqual(await call('/fixture/audit/'+sourceId),sourceBefore);assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(error){report.error=String(error.stack||error);if(page)try{report.failure=await page.evaluate(()=>window.__zombieInspection);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});}catch{}throw error;}
 finally{fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
