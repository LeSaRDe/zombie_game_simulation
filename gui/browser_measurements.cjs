const {openExactEditor}=require('./browser_exact_time.cjs');
/* Browser-only interaction and measurement helpers; no business API calls. */
async function installInputLog(page){
 await page.evaluate(()=>{
  window.__acceptanceInputLog=[];
  if(!window.__acceptanceInputHandlers){
   for(const type of ['keydown','pointerdown'])document.addEventListener(type,e=>{
    if(e.isTrusted)window.__acceptanceInputLog.push({method:type==='keydown'?'keyboard':'pointer',key:e.key||null,testid:e.target.getAttribute?.('data-testid'),at:performance.now()});
   },true);
   window.__acceptanceInputHandlers=true;
  }
 });
}
async function tabTo(page,testid){
 const target=page.getByTestId(testid).first();await target.waitFor({state:'visible'});
 const backwards=await target.evaluate(e=>{const current=document.activeElement;return current&&current!==document.body&&!!(current.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_PRECEDING);});
 for(let index=0;index<350;index++){
  if(await target.evaluate(e=>document.activeElement===e))return;
  await page.keyboard.press(backwards?'Shift+Tab':'Tab');
 }
 throw Error('Keyboard focus cannot reach '+testid);
}
async function activate(page,testid){await tabTo(page,testid);await page.keyboard.press('Enter');}
async function keyboardWorkflow(page,m,log){
 await installInputLog(page);
 for(const action of m.actions){
  if(action==='choose_baseline'){
   await activate(page,'config-edit-new');await tabTo(page,'config-preset');
   await page.keyboard.press('Home');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
   await page.waitForFunction(()=>document.querySelector('[data-testid="config-preset"]')?.value==='baseline');
  }else if(action==='validate'){
   await activate(page,'config-validate');await page.getByRole('dialog').getByRole('status').filter({hasText:'Valid configuration'}).waitFor();
  }else if(action==='preview'){
   await activate(page,'config-preview');await page.getByRole('dialog').locator('canvas').waitFor();
   await page.waitForFunction(()=>!document.querySelector('[data-testid="config-preview"]')?.disabled);
  }else if(action==='start'){
   await activate(page,'config-launch');await page.waitForFunction(()=>window.__zombieInspection?.app?.view&&window.__zombieInspection.app.run?.status==='running');
  }else if(action==='pause'){
   await activate(page,'run-pause');await page.waitForFunction(()=>!window.__zombieInspection.app.pending&&window.__zombieInspection.app.run?.status==='paused');
  }else if(action==='select_agent'){
   const aid=await page.evaluate(()=>{const values=Object.values(window.__zombieInspection.app.view.state.agents);return String((values.find(a=>a.status==='INFECTED')||values[0]).id);});
   await activate(page,'tab-world');await tabTo(page,'agent-search');await page.keyboard.press('ControlOrMeta+A');await page.keyboard.type(aid);
   await activate(page,'agent-search-select');await page.waitForFunction(id=>window.__zombieInspection.app.selected===id,aid);
  }else if(action==='show_table'){
   await activate(page,'tab-statistics');
   const toggle=page.getByTestId('population-table-toggle');
   if(!await toggle.evaluate(e=>e.parentElement.open))await activate(page,'population-table-toggle');
   await tabTo(page,'population-table');
  }else throw Error('Unbound keyboard workflow action '+action);
  log.push({action:'keyboard_workflow',step:action,focused:await page.evaluate(()=>document.activeElement?.getAttribute('data-testid'))});
 }
 const events=await page.evaluate(()=>window.__acceptanceInputLog);
 return {input_methods:[...new Set(events.map(e=>e.method))],events,focused_testid:await page.evaluate(()=>document.activeElement?.getAttribute('data-testid'))};
}
async function accessibility(page){
 const controls={};
 for(const testid of ['run-pause','run-step-transition']){
  const target=page.getByTestId(testid);controls[testid]={accessible_name:await target.getAttribute('aria-label')||await target.innerText(),disabled:await target.isDisabled()};
 }
 const table=page.getByTestId('population-table');
 return {controls,population_table:{role:await table.getAttribute('role')||((await table.evaluate(e=>e.tagName))==='TABLE'?'table':null),headers:await table.locator('thead th').allTextContents()},
  status_tokens:await page.locator('[data-status-token]').evaluateAll(elements=>elements.map(e=>e.getAttribute('data-status-token'))),
  animation_mode:await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches?'reduced':'normal'),
  focused_testid:await page.evaluate(()=>document.activeElement?.getAttribute('data-testid'))};
}
async function benchmark(page,m,log){
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
 const count=m.population,columns=Math.ceil(Math.sqrt(count));
 const config={scenario:'render-benchmark-'+count,seed:20261106,horizon:1800,decision_mode:'scripted',
  world:{length:1000,width:1000},placement:{minimum_separation:0,cross_type_separation:0},
  execution:{workers:1},agents:Array.from({length:count},(_,i)=>({id:String(i+1),type:i%5===0?'Zombie':'Human',
   x:(i%columns+.5)*1000/columns,y:(Math.floor(i/columns)+.5)*1000/columns}))};
 const directory=m.artifacts||fs.mkdtempSync(path.join(os.tmpdir(),'zombie-render-'));
 const file=path.join(directory,'benchmark-config.json');fs.writeFileSync(file,JSON.stringify(config));
 await page.getByTestId('config-edit-new').first().click();
 await page.getByText('Advanced configuration · JSON',{exact:true}).click();
 await page.waitForFunction(()=>{const input=document.querySelector('[data-testid="config-import"]');return input&&!input.matches(':disabled');});
 await page.getByRole('dialog').locator('input[type=file]').setInputFiles(file);
 await page.waitForFunction(n=>window.__zombieInspection?.configuration?.draft?.agents?.length===n,count);
 await page.getByTestId('config-launch').click();
 await page.waitForFunction(n=>Object.keys(window.__zombieInspection?.app?.view?.state?.agents||{}).length===n,count,{timeout:60000});
 await page.getByTestId('run-pause').click();await page.waitForFunction(()=>!window.__zombieInspection.app.pending&&window.__zombieInspection.app.run.status==='paused');
 await page.getByTestId('tab-world').click();
 const actualCount=await page.evaluate(()=>Object.keys(window.__zombieInspection.app.view.state.agents).length);
 await page.evaluate(({duration,warmup})=>{
  window.__browserBenchmark={frames:[],inputs:[],done:false,phase:'warmup',duration,started:performance.now(),receiptStart:window.__zombieMeasurements.transport.receipt_latencies_ms.length};
  const b=window.__browserBenchmark;
  const input=e=>{if(e.isTrusted&&b.phase==='measure')b.lastInput={at:performance.now(),type:e.type,target:e.target.getAttribute?.('data-testid')};};
  for(const type of ['pointerdown','pointermove','change','input','keydown'])document.addEventListener(type,input,true);
  b.remove=()=>{for(const type of ['pointerdown','pointermove','change','input','keydown'])document.removeEventListener(type,input,true);};
  function frame(t){
   if(t-b.started>=warmup){
    if(b.phase==='warmup'){b.phase='measure';b.measureStart=t;}
    if(b.previous!==undefined)b.frames.push(t-b.previous);
    b.previous=t;
    if(t-b.measureStart>=duration){b.done=true;b.phase='done';return;}
   }
   requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
 },{duration:m.duration_seconds*1000,warmup:m.warmup_seconds*1000});
 await page.waitForFunction(()=>window.__browserBenchmark.phase==='measure');
 async function input(label,operation,render='world_frame'){
  await page.evaluate(()=>{window.__browserBenchmark.lastInput=null;});
  await operation();
  await page.waitForFunction(key=>{const b=window.__browserBenchmark,i=window.__zombieMeasurements;return b.lastInput&&i[key]&&i[key].at>=b.lastInput.at;},render);
  const sample=await page.evaluate(({key,label})=>{const b=window.__browserBenchmark,i=window.__zombieMeasurements;
   const s={label,event:b.lastInput.type,event_at:b.lastInput.at,render_at:i[key].at,latency:i[key].at-b.lastInput.at};b.inputs.push(s);return s;},{key:render,label});
  log.push({action:'measured_input',...sample});
 }
 let iteration=0;
 while(!await page.evaluate(()=>window.__browserBenchmark.done)){
  const remaining=await page.evaluate(()=>window.__browserBenchmark.duration-(performance.now()-window.__browserBenchmark.measureStart));
  if(remaining<1000){await page.waitForTimeout(Math.max(10,remaining+50));break;}
  if(iteration===5){
   await input('cohort-tab',()=>page.getByTestId('tab-cohorts').click(),'react_commit');
   await page.getByTestId('cohort-name').fill('Render benchmark');
   await page.getByTestId('cohort-save').click();
   await input('world-tab',()=>page.getByTestId('tab-world').click());
  }else if(iteration===12){
   await openExactEditor(page,'replay-exact-time',log);await page.getByTestId('replay-exact-time').fill('0');
   await input('scrub',()=>page.getByTestId('replay-seek').click());
   await input('return-live',()=>page.getByTestId('replay-return-live').click());
  }else if(iteration%2===0){
   await input('zoom',()=>page.getByRole('button',{name:iteration%4===0?'Zoom in':'Zoom out',exact:true}).click());
  }else{
   const canvas=page.locator('.world-frame canvas').first(),box=await canvas.boundingBox();
   await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
   await input('pan',()=>page.mouse.move(box.x+box.width/2+(iteration%4===1?5:-5),box.y+box.height/2+2));
   await page.mouse.up();
  }
  if(iteration<5){
   await input('pause',()=>page.getByTestId('run-pause').click(),'react_commit');
   await page.waitForFunction(()=>!document.querySelector('[data-testid="run-pause"]')?.disabled);
  }
  if(iteration===8){
   await page.getByTestId('agent-search').fill('1');
   await input('select',()=>page.getByTestId('agent-search-select').first().click());
  }
  iteration++;await page.waitForTimeout(150);
 }
 await page.waitForFunction(()=>window.__browserBenchmark.done);
 const raw=await page.evaluate(()=>{const b=window.__browserBenchmark,t=window.__zombieMeasurements.transport;b.remove();
  return {frame_times_ms:b.frames,input_samples:b.inputs,receipt_ack_latencies_ms:t.receipt_latencies_ms.slice(b.receiptStart),transport:t};});
 const inputs=raw.input_samples.map(s=>s.latency),p95=a=>[...a].sort((a,b)=>a-b)[Math.ceil(.95*a.length)-1];
 fs.writeFileSync(path.join(directory,'benchmark-raw.json'),JSON.stringify(raw));
 if(inputs.length<20||raw.receipt_ack_latencies_ms.length<5)throw Error(`Insufficient actual benchmark inputs (${inputs.length}) or command receipts (${raw.receipt_ack_latencies_ms.length})`);
 return {population:actualCount,frame_times_ms:raw.frame_times_ms,measured_frames:raw.frame_times_ms.length,
  input_latencies_ms:inputs,input_samples:raw.input_samples,receipt_ack_latencies_ms:raw.receipt_ack_latencies_ms,
  fps:1000*raw.frame_times_ms.length/raw.frame_times_ms.reduce((a,b)=>a+b,0),input_latency_p95_ms:p95(inputs),
  receipt_ack_p95_ms:p95(raw.receipt_ack_latencies_ms),
  subscriber_max_queue_depth:raw.transport.max_queue_depth,
  aggregation_label:m.aggregation?await page.getByTestId('aggregation-label').innerText():null,
  transport:raw.transport,config_path:file};
}
module.exports={keyboardWorkflow,accessibility,benchmark,tabTo,activate};
