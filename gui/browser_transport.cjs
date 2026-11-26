/* Deterministic faults intercept real viewer transport, preserving every payload. */
const sessions=new WeakMap();
async function install(page){
 const state={behavior:null,held:[],sockets:[],received:[],index:0,slow:false};sessions.set(page,state);
 await page.routeWebSocket('**/api/runs/*/stream',socket=>{
  const server=socket.connectToServer();state.sockets.push(socket);
  socket.onMessage(message=>{if(!state.slow)server.send(message);});
  server.onMessage(message=>{
   state.index++;state.received.push({index:state.index,payload:message});
   if(state.behavior==='scripted_delta_faults')state.held.push({socket,message,index:state.index});
   else socket.send(message);
  });
 });
 return state;
}
async function executeTransport(page,step){
 let state=sessions.get(page);if(!state)state=await install(page);
 if(step.op==='transport'){
  state.behavior=step.behavior;state.index=0;state.parameters=step;
  if(['delay_metrics','hold_seek'].includes(step.behavior)){
   await page.route(step.behavior==='delay_metrics'?'**/api/runs/*/metrics?*':'**/api/runs/*/view?*',async route=>{
    const url=new URL(route.request().url());
    if(step.behavior==='hold_seek'&&url.searchParams.get('time')!==String(step.time)){await route.continue();return;}
    const response=await route.fetch();state.held.push({route,response});
   });
  }
  return {};
 }
 if(step.op==='release_transport'){
  const behavior=state.behavior;state.behavior=null;
  const held=state.held.splice(0);
  if(behavior==='scripted_delta_faults'){
   const params=state.parameters;const messages=held.filter(item=>!params.omit_sequences.includes(item.index));
   const reverse=messages.filter(item=>params.reverse_sequences.includes(item.index)).reverse();let offset=0;
   for(let item of messages){if(params.reverse_sequences.includes(item.index))item=reverse[offset++];item.socket.send(item.message);if(params.duplicate_sequences.includes(item.index))item.socket.send(item.message);}
  }else{for(const item of held)await item.route.fulfill({response:item.response});await page.unroute('**/api/runs/*/metrics?*');await page.unroute('**/api/runs/*/view?*');}
  return {received:state.received};
 }
 if(step.op==='projection_fixture'){
  const app=await page.evaluate(()=>window.__zombieInspection.app);const fixture=step.bundle;
  const body={schema:'zombie-sim/view-v1',run_id:app.run_id,time:fixture.time,revision:fixture.revision,sequence:fixture.revision,mode:'replay',committed_frontier:fixture.revision,
    state:{world:{length:100,width:100},barriers:{},stockpiles:{},remains:{},episodes:{},reservations:{},signals:{},...fixture},metrics:{populations:{healthy:Object.keys(fixture.agents).length,infected:0,zombies:0,dead:0,total:Object.keys(fixture.agents).length},resources:{available_and_reserved:{},reserved_subset:{}}}};
  await page.route('**/api/runs/*/view?*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)}),{times:1});
  await page.getByTestId('replay-seek').click();await page.waitForFunction(revision=>window.__zombieInspection.app.view?.revision===revision,fixture.revision);
  return {};
 }
 if(step.op==='observer_load'){
  state.slow=step.mode==='slow';
  for(const pace of step.pacing){const value=pace==='fastest'?'16':String(pace);await page.getByTestId('view-pacing').selectOption(value);await page.waitForFunction(()=>!window.__zombieInspection.app.pending);}
  if(step.mode==='exports'){
   const {executeExport}=require('./browser_exports.cjs');await executeExport(page,{op:'export_form',format:'scene_png',time:'0',interval:['0','0'],sample_interval:'1',cohort:'all'});await page.getByTestId('export-start').click();
  }
  return {received:state.received};
 }
 throw Error('Unknown transport operation '+step.op);
}
module.exports={install,executeTransport};
