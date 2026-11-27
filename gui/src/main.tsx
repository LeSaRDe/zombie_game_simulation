import React, {useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import ExportDialog from './ExportDialog';
import CommandDialog from './CommandDialog';
import {isInactiveRun, lifecycleLabel, runGroup, terminationNotice} from './runLifecycle';
import {configurationMetadata, parseConfigurationDraft} from './configurationDraft';
import {configurationNumberRules, parseNumericText} from './numericDraft';
import {applyRoleEdits, effectivePopulation, roleEditingBlock, parseRolePercentage, readRoleGroups} from './roleAllocation';
import RoleAllocationPanels from './RoleAllocationPanels';
import ModelSelection from './ModelSelection';
import {ModelField, readModelSetting} from './modelSelection';
import StatisticsPanel from './StatisticsPanel';
import useStatisticsReader, {MetricCursor, MetricRead} from './useStatisticsReader';
import useCohortReader, {CohortRead} from './useCohortReader';
import CohortPanel from './CohortPanel';
import useEventsReader from './useEventsReader';
import EventsPanel from './EventsPanel';
import useComparisonReader from './useComparisonReader';
import ComparisonPanel from './ComparisonPanel';
import RunViewStatus, {confirmedStatusLabel, statusFreshness} from './RunViewStatus';
import {applyWorldResize, effectiveWorld, worldResizeSummary} from './worldLayout';

type Obj = Record<string, any>;
// A late command receipt or summary cannot replace a newer confirmed boundary.
// The request timestamp also orders lifecycle changes at the same revision.
function newestRunStatus(previous: Obj | undefined, incoming: Obj): Obj {
  if (!previous) return incoming;
  if (previous.generation > incoming.generation) return previous;
  if (previous.generation === incoming.generation) {
    const before = BigInt(previous.frontier?.revision ?? 0), after = BigInt(incoming.frontier?.revision ?? 0);
    if (before > after || (before === after && previous.status_read_started_at > incoming.status_read_started_at)) return previous;
  }
  return incoming;
}
type ViewerLoad = {phase:'idle'|'initializing'|'loading'|'ready'|'failed';run_id:string;error?:string;details?:boolean};
type Bundle = {state: Obj; metrics: Obj; time: string; revision: string; sequence: string; mode: string; run_id: string; committed_frontier: string};
const inspection:Obj={transport:{snapshot_requests:0,application_trace:[],max_queue_depth:0,queue_depth:0,receipt_latencies_ms:[]},configuration:{}};
Object.defineProperty(window,'__zombieInspection',{get:()=>structuredClone(inspection)});
Object.defineProperty(window,'__zombieMeasurements',{get:()=>structuredClone({world_frame:inspection.world_frame,react_commit:inspection.react_commit,transport:inspection.transport})});
const colors: Obj = {healthy: '#77d5c5', infected: '#f4bc65', zombies: '#ef8796', dead: '#88919c'};
const values = (v: any): Obj[] => Array.isArray(v) ? v : Object.values(v || {});
const seconds = (v: any): number => { const parts=String(v??0).split('/').map(Number); return parts[0]/(parts[1]||1); };
const fixed = (v: any) => Number(seconds(v)).toLocaleString(undefined,{maximumFractionDigits:2});
const id = () => crypto.randomUUID();
async function api(path: string, body?: Obj, signal?: AbortSignal): Promise<any> {
  if(path.includes('/view'))inspection.transport.snapshot_requests++;
  const sent=performance.now();
  const response = await fetch(`/api${path}`, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal} : {signal});
  if(body&&path.endsWith('/commands'))inspection.transport.receipt_latencies_ms.push(performance.now()-sent);
  const text = await response.text();
  let data: Obj;
  try { data = text ? JSON.parse(text) : {}; }
  catch { throw Object.assign(Error(`The server returned ${response.status} without a valid JSON response. ${text.replace(/<[^>]*>/g,'').slice(0,160)}`),{status:response.status,code:'INVALID_RESPONSE'}); }
  if(!response.ok) throw Object.assign(Error(data.error || data.detail || `Request failed (${response.status})`),{status:response.status,code:data.code,issues:data.issues});
  return data;
}
function download(name: string, content: string, type='application/json') {
  const url=URL.createObjectURL(new Blob([content],{type})); const a=document.createElement('a'); a.href=url; a.download=name; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const agentStatus = (a: Obj) => a.status==='DEAD'||a.life===0?'dead':a.type==='Zombie'?'zombies':a.status==='INFECTED'||a.infection_episode?'infected':'healthy';

function World({state,selected,onSelect,follow=false,layers}: {state:Obj; selected:string; onSelect:(id:string)=>void; follow?:boolean; layers?:Obj}) {
  const canvas=useRef<HTMLCanvasElement>(null); const frame=useRef<HTMLDivElement>(null);
  const [camera,setCamera]=useState({scale:1,x:0,y:0}); const [size,setSize]=useState({width:800,height:560});
  const pointer=useRef({x:0,y:0,down:false,moved:false});
  const world=state.world||{length:100,width:100}; const agents=values(state.agents);const aggregate=agents.length>5000&&camera.scale<2;
  useEffect(()=>{if(!frame.current)return;const observer=new ResizeObserver(([entry])=>setSize({width:entry.contentRect.width,height:entry.contentRect.height})); observer.observe(frame.current); return()=>observer.disconnect();},[]);
  const base=Math.max(.001,Math.min((size.width-48)/world.length,(size.height-48)/world.width));
  const scale=base*camera.scale;
  let x=(size.width-world.length*scale)/2+camera.x, y=(size.height-world.width*scale)/2+camera.y;
  if(follow&&selected&&state.agents?.[selected]) {x=size.width/2-state.agents[selected].x*scale;y=size.height/2-(world.width-state.agents[selected].y)*scale;}
  useEffect(()=>{
    const element=canvas.current;if(!element)return;const context=element.getContext('2d');if(!context)return;
    const dpr=window.devicePixelRatio||1;element.width=size.width*dpr;element.height=size.height*dpr;context.scale(dpr,dpr);
    context.fillStyle='#101a24';context.fillRect(0,0,size.width,size.height);
    context.save();context.translate(x,y+world.width*scale);context.scale(scale,-scale);
    context.fillStyle='#14232d';context.fillRect(0,0,world.length,world.width);
    context.strokeStyle='#233640';context.lineWidth=1/scale;
    const grid=10**Math.floor(Math.log10(world.length/8));
    for(let gx=0;gx<=world.length;gx+=grid){context.beginPath();context.moveTo(gx,0);context.lineTo(gx,world.width);context.stroke();}
    for(let gy=0;gy<=world.width;gy+=grid){context.beginPath();context.moveTo(0,gy);context.lineTo(world.length,gy);context.stroke();}
    for(const shelter of values(state.shelters)){const r=shelter.interior;if(r){context.fillStyle='#36554430';context.fillRect(r[0],r[1],r[2]-r[0],r[3]-r[1]);}}
    for(const b of values(state.barriers)){const r=b.footprint||b.rect;if(!r)continue;context.fillStyle=b.type==='Gate'?(b.mode==='OPEN'?'#78bd8a':b.mode==='BREACHED'?'#685941':'#d2a666'):b.type==='Barricade'?'#aa815d':'#5a727e';context.fillRect(r[0],r[1],r[2]-r[0],r[3]-r[1]);}
    if(layers?.resources!==false)for(const s of values(state.stockpiles)){context.fillStyle='#d9d8b2';context.fillRect(s.x-3/scale,s.y-3/scale,6/scale,6/scale);}
    if(layers?.remains!==false)for(const r of values(state.remains)){context.strokeStyle='#8f7887';context.beginPath();context.arc(r.x,r.y,3/scale,0,Math.PI*2);context.stroke();}
    if(aggregate&&layers?.agents!==false){
      const bins=new Map<string,{x:number,y:number,n:number,color:string}>();
      for(const a of agents){const px=a.x*scale+x,py=(world.width-a.y)*scale+y;if(px<0||py<0||px>size.width||py>size.height)continue;const color=colors[agentStatus(a)];const key=`${Math.floor(px/8)}:${Math.floor(py/8)}:${color}`;const bin=bins.get(key)||{x:0,y:0,n:0,color};bin.x+=a.x;bin.y+=a.y;bin.n++;bins.set(key,bin);}
      for(const bin of bins.values()){context.beginPath();context.fillStyle=bin.color;context.globalAlpha=Math.min(1,.35+Math.log2(bin.n+1)/6);context.arc(bin.x/bin.n,bin.y/bin.n,Math.min(7,2+Math.sqrt(bin.n))/scale,0,2*Math.PI);context.fill();}context.globalAlpha=1;
    }
    for(const a of agents){
      if(layers?.agents===false||aggregate&&String(a.id)!==selected)continue;
      if(a.x*scale+x < -10||(world.width-a.y)*scale+y < -10||a.x*scale+x>size.width+10||(world.width-a.y)*scale+y>size.height+10)continue;
      const status=agentStatus(a);const radius=(String(a.id)===selected?6:Math.max(2.6,Math.min(4,camera.scale*2)))/scale;
      if(layers?.sensing&&String(a.id)===selected){context.beginPath();context.arc(a.x,a.y,a.sense_r||a.sensing_radius||a.effective_sensing||30,0,Math.PI*2);context.fillStyle='#77d5c512';context.fill();context.strokeStyle='#77d5c560';context.stroke();}
      const path=state.occurrences?.[a.active_action]?.parameters?.path;if(layers?.trails&&path){context.beginPath();for(const [i,p]of path.entries())i?context.lineTo(p.x,p.y):context.moveTo(p.x,p.y);context.strokeStyle='#76b6c760';context.stroke();}
      context.fillStyle=colors[status];context.strokeStyle=colors[status];context.lineWidth=1.5/scale;context.beginPath();
      if(status==='dead'){context.moveTo(a.x-radius,a.y-radius);context.lineTo(a.x+radius,a.y+radius);context.moveTo(a.x+radius,a.y-radius);context.lineTo(a.x-radius,a.y+radius);context.stroke();}
      else if(a.type==='Zombie'){context.moveTo(a.x,a.y-radius*1.3);context.lineTo(a.x+radius,a.y+radius);context.lineTo(a.x-radius,a.y+radius);context.closePath();context.fill();}
      else{context.arc(a.x,a.y,radius,0,Math.PI*2);context.fill();if(status==='infected'){context.strokeStyle='#f4bc65';context.beginPath();context.arc(a.x,a.y,radius+2/scale,0,Math.PI*2);context.stroke();}}
      if(String(a.id)===selected){context.strokeStyle='#fff';context.beginPath();context.arc(a.x,a.y,radius+4/scale,0,Math.PI*2);context.stroke();}
      if(layers?.labels&&(camera.scale>2||String(a.id)===selected)){context.fillStyle='#d9e4e7';context.font=`${11/scale}px system-ui`;context.save();context.translate(a.x,a.y);context.scale(1,-1);context.fillText(`${a.id}${a.role?' · '+a.role:''}`,8/scale,-7/scale);context.restore();}
      if(layers?.actions&&a.active_action){context.strokeStyle='#d9e4e7';context.beginPath();context.moveTo(a.x-radius,a.y+radius+4/scale);context.lineTo(a.x+radius,a.y+radius+4/scale);context.stroke();}
    }
    context.strokeStyle='#4a626d';context.strokeRect(0,0,world.length,world.width);context.restore();
    context.fillStyle='#8fa3b0';context.font='11px system-ui';context.fillText(`${world.length} × ${world.width} m · ${agents.length.toLocaleString()} identities`,16,size.height-16);
    inspection.world_frame={at:performance.now(),selected,camera:{...camera},time:state.time,revision:String(state.revision)};
  },[state,selected,camera,size,follow,layers]);
  return <div className="world-frame" data-glyph-semantics="screen_symbol" ref={frame}>{aggregate&&<span data-testid="aggregation-label" className="aggregation-label">Spatial aggregation</span>}<canvas ref={canvas} aria-label="World map. Use the searchable agent table below for keyboard-accessible selection." onWheel={e=>{e.preventDefault();setCamera(c=>({...c,scale:Math.max(.4,Math.min(30,c.scale*(e.deltaY<0?1.14:.88)))}));}} onPointerDown={e=>{pointer.current={x:e.clientX,y:e.clientY,down:true,moved:false};e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{const p=pointer.current;if(!p.down)return;const dx=e.clientX-p.x,dy=e.clientY-p.y;if(Math.abs(dx)+Math.abs(dy)>2)p.moved=true;setCamera(c=>({...c,x:c.x+dx,y:c.y+dy}));p.x=e.clientX;p.y=e.clientY;}} onPointerUp={e=>{if(!pointer.current.moved){const r=e.currentTarget.getBoundingClientRect();const px=e.clientX-r.left,py=e.clientY-r.top;let best:Obj|undefined;let distance=15;for(const a of agents){const d=Math.hypot(a.x*scale+x-px,(world.width-a.y)*scale+y-py);if(d<distance){best=a;distance=d;}}if(best)onSelect(String(best.id));}pointer.current.down=false;}}/>
    <div className="map-tools"><button title="Zoom in" aria-label="Zoom in" onClick={()=>setCamera(c=>({...c,scale:Math.min(30,c.scale*1.5)}))}>＋</button><button title="Zoom out" aria-label="Zoom out" onClick={()=>setCamera(c=>({...c,scale:Math.max(.4,c.scale/1.5)}))}>−</button><button onClick={()=>setCamera({scale:1,x:0,y:0})}>Fit world</button><button onClick={()=>{const a=document.createElement('a');a.download=`world-r${state.revision}.png`;a.href=canvas.current!.toDataURL();a.click();}}>PNG</button></div>
  </div>;
}

function useModalFocus(ref:React.RefObject<HTMLElement|null>,onClose:()=>void){
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;const controls=()=>Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,a[href]')||[]).filter(el=>el.offsetParent!==null);controls()[0]?.focus();const handle=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();onClose();}if(event.key==='Tab'){const items=controls();const first=items[0],last=items.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}};document.addEventListener('keydown',handle);return()=>{document.removeEventListener('keydown',handle);if(previous?.isConnected)previous.focus();};},[]);
}

function Configuration({onClose,onCreated,onStartState,onError,source}:{onClose:()=>void;onCreated:(id:string,generation?:number)=>void;onStartState:(id:string,pending:boolean,generation?:number,uncertain?:boolean)=>void;onError:(text:string)=>void;source?:Obj}){
  const [metadata,setMetadata]=useState<Obj>();const[draft,setDraft]=useState<Obj>({});const[advanced,setAdvanced]=useState('');const[preview,setPreview]=useState<Bundle>();const[result,setResult]=useState('');const[issues,setIssues]=useState<Obj[]>([]);const[artifactId,setArtifactId]=useState('');const[exportFormat,setExportFormat]=useState('json');const[busy,setBusy]=useState(false);const[batchSeeds,setBatchSeeds]=useState('');const modal=useRef<HTMLElement>(null);useModalFocus(modal,onClose);
  const draftRef=useRef(draft);const advancedRef=useRef(advanced);
  const[modelEditorVersion,setModelEditorVersion]=useState(0);
  const[numericText,setNumericText]=useState<Record<string,string>>({});const numericTextRef=useRef(numericText);
  const[numericErrors,setNumericErrors]=useState<Record<string,string>>({});const numericErrorsRef=useRef(numericErrors);
  const[roleText,setRoleText]=useState<Record<string,string>>({});const roleTextRef=useRef(roleText);
  const[roleErrors,setRoleErrors]=useState<Record<string,string>>({});const roleErrorsRef=useRef(roleErrors);
  const[loadState,setLoadState]=useState<{phase:'loading'|'ready'|'failed';error?:string}>({phase:'loading'});
  const[loadAttempt,setLoadAttempt]=useState(0);const loadVersion=useRef(0);const loadStateRef=useRef(loadState);loadStateRef.current=loadState;
  const busyRef=useRef(false);const ready=loadState.phase==='ready';const unavailable=!ready||busy;
  const setLoadingState=(state:typeof loadState)=>{loadStateRef.current=state;setLoadState(state);};
  const clearDraftFeedback=()=>{setPreview(undefined);setArtifactId('');setResult('');setIssues([]);};
  const setDraftValue=(config:Obj)=>{draftRef.current=config;setDraft(config);};
  const setAdvancedValue=(text:string)=>{advancedRef.current=text;setAdvanced(text);};
  const setNumericState=(text:Record<string,string>,errors:Record<string,string>)=>{
    numericTextRef.current=text;setNumericText(text);numericErrorsRef.current=errors;setNumericErrors(errors);
  };
  const setRoleState=(text:Record<string,string>,errors:Record<string,string>)=>{roleTextRef.current=text;setRoleText(text);roleErrorsRef.current=errors;setRoleErrors(errors);};
  const replaceDraft=(config:Obj)=>{setDraftValue(config);setAdvancedValue(JSON.stringify(config,null,2));setNumericState({},{});setRoleState({},{});setModelEditorVersion(value=>value+1);clearDraftFeedback();};
  useEffect(()=>{
    const controller=new AbortController();const version=++loadVersion.current;
    setLoadingState({phase:'loading'});setMetadata(undefined);
    api('/config',undefined,controller.signal).then(configurationMetadata).then(data=>{
      if(controller.signal.aborted||version!==loadVersion.current)return;
      setMetadata(data);replaceDraft(structuredClone(source||data.presets.small));setLoadingState({phase:'ready'});
    }).catch((error:Error)=>{
      if(!controller.signal.aborted&&version===loadVersion.current)setLoadingState({phase:'failed',error:error.message});
    });
    return()=>{controller.abort();loadVersion.current++;};
  },[loadAttempt,source]);
  const reportDraftError=(error:any)=>{setResult(error.message);setIssues(error.issues||[{path:'configuration',code:error.code||'INVALID_REQUEST',message:error.message}]);};
  const requireReady=()=>{
    if(loadStateRef.current.phase!=='ready')throw Error('Wait for configuration to finish loading, or retry if loading failed.');
  };
  const numericFailure=(errors:Record<string,string>)=>Object.assign(new Error(Object.values(errors).join(' ')),{
    code:'INVALID_DOMAIN',issues:Object.entries(errors).map(([key,message])=>{const path=/^(Human|Zombie)\./.test(key)?`gui.role_allocation.${key.replace('.', '.targets.')}`:key==='Human'||key==='Zombie'?`gui.role_allocation.${key}`:key;return {path,code:'INVALID_DOMAIN',message};})});
  const retainNumericFeedback=()=>{const errors={...numericErrorsRef.current,...roleErrorsRef.current};if(Object.keys(errors).length)reportDraftError(numericFailure(errors));};
  const assignPath=(config:Obj,path:string,value:any)=>{
    const keys=path.split('.');let node=config;
    for(const key of keys.slice(0,-1)){
      if(node[key]===undefined)node[key]={};
      if(node[key]===null||typeof node[key]!=='object'||Array.isArray(node[key]))throw Error(`${path}: correct its containing object in Advanced JSON before editing this field.`);
      node=node[key];
    }
    node[keys.at(-1)!]=value;
  };
  const readDraft=()=>{
    requireReady();
    const config=parseConfigurationDraft(advancedRef.current);
    const base=structuredClone(config);
    const pending=numericTextRef.current;const parsed:Record<string,number>={};const errors:Record<string,string>={};
    for(const [path,text] of Object.entries(pending)){
      try{parsed[path]=parseNumericText(text,configurationNumberRules[path]);}
      catch(error){errors[path]=(error as Error).message;}
    }
    const rolePending=roleTextRef.current;const nextRoleErrors:Record<string,string>={};
    for(const [path,text] of Object.entries(rolePending)){
      try{parseRolePercentage(text,`gui.role_allocation.${path.replace('.', '.targets.')}`);}
      catch(error){nextRoleErrors[path]=(error as Error).message;}
    }
    if(Object.keys(errors).length||Object.keys(nextRoleErrors).length){setNumericState(pending,errors);setRoleState(rolePending,nextRoleErrors);throw numericFailure({...errors,...nextRoleErrors});}
    // Commit all pending values together, from current refs rather than a render
    // closure. A pointer click can blur an input before its action handler runs.
    for(const [path,value] of Object.entries(parsed))assignPath(config,path,value);
    applyWorldResize(base,config,parsed,metadata!.presets);
    const populationBlock=roleEditingBlock(base);if(populationBlock&&Object.keys(parsed).some(path=>path.startsWith('population.')))throw Error(populationBlock);
    try{applyRoleEdits(base,config,rolePending,new Set(Object.keys(parsed).filter(path=>path==='population.humans'||path==='population.zombies').map(path=>path.split('.')[1])),metadata!.presets);}
    catch(error:any){
      const path=error.issues?.[0]?.path||'';const kind=path.includes('Human')||path.includes('human')?'Human':path.includes('Zombie')||path.includes('zombie')?'Zombie':'configuration';
      setRoleState(rolePending,{[kind]:error.message});throw error;
    }
    setDraftValue(config);setNumericState({},{});setRoleState({},{});
    if(Object.keys(pending).length||Object.keys(rolePending).length)setAdvancedValue(JSON.stringify(config,null,2));
    return config;
  };
  const editNumber=(path:string,text:string)=>{
    if(loadStateRef.current.phase!=='ready'||busyRef.current)return;
    const errors={...numericErrorsRef.current};delete errors[path];
    setNumericState({...numericTextRef.current,[path]:text},errors);clearDraftFeedback();retainNumericFeedback();
  };
  const editRole=(path:string,text:string)=>{
    if(loadStateRef.current.phase!=='ready'||busyRef.current)return;
    const errors={...roleErrorsRef.current};delete errors[path];delete errors[path.split('.')[0]];
    setRoleState({...roleTextRef.current,[path]:text},errors);clearDraftFeedback();retainNumericFeedback();
  };
  const commitNumbers=()=>{
    if(loadStateRef.current.phase!=='ready'||busyRef.current||(!Object.keys(numericTextRef.current).length&&!Object.keys(roleTextRef.current).length))return;
    try{readDraft();clearDraftFeedback();}catch(error){reportDraftError(error);}
  };
  const change=(path:string,value:any)=>{
    if(loadStateRef.current.phase!=='ready'||busyRef.current)return;
    try{
      const next=parseConfigurationDraft(advancedRef.current);assignPath(next,path,value);
      if(path==='execution.workers'){
        const text={...numericTextRef.current};const errors={...numericErrorsRef.current};delete text[path];delete errors[path];setNumericState(text,errors);
      }
      setDraftValue(next);setAdvancedValue(JSON.stringify(next,null,2));clearDraftFeedback();retainNumericFeedback();
    }
    catch(error){reportDraftError(error);}
  };
  const editAdvanced=(text:string)=>{
    // Complete JSON is the shared configuration immediately. Keep unfinished
    // text separate, so field edits cannot overwrite it with the last valid object.
    setAdvancedValue(text);setNumericState({},{});setRoleState({},{});clearDraftFeedback();
    try{setDraftValue(parseConfigurationDraft(text));}catch{/* Keep the last valid object for explicit discard. */}
  };
  const changeModel=(field:ModelField,value:string)=>{
    if(loadStateRef.current.phase!=='ready'||busyRef.current)return;
    try{
      // Model controls consume the current JSON, preserving imported aliases,
      // per-agent parameters and unrelated Advanced JSON edits until changed.
      const next=parseConfigurationDraft(advancedRef.current);
      const setting=readModelSetting(next,field==='human_model'?'Human':'Zombie',metadata!.models);
      if(setting.blocked)throw Error(setting.blocked);
      next[field]=value;
      setDraftValue(next);setAdvancedValue(JSON.stringify(next,null,2));clearDraftFeedback();retainNumericFeedback();
    }catch(error){reportDraftError(error);}
  };
  const numberInput=(field:Obj)=>{
    const path=field.path;const error=numericErrors[path];const errorId=`numeric-error-${path.replaceAll('.','-')}`;
    const pending=Object.prototype.hasOwnProperty.call(numericText,path);
    let value=pending?numericText[path]:String(path.split('.').reduce((node:any,key:string)=>node?.[key],draft)??'');
    let explicitAgents=false;try{const config=parseConfigurationDraft(advancedRef.current);explicitAgents=Boolean(roleEditingBlock(config));if(!pending&&path.startsWith('population.'))value=String(effectivePopulation(config,metadata!.presets)[path.split('.')[1]]);if(!pending&&path.startsWith('world.'))value=String(effectiveWorld(config,metadata!.presets)[path.split('.')[1]]);}catch{}
    return <label key={path}>{field.label}{field.unit&&<small>{field.unit}</small>}<input data-testid={`config-${path}`} aria-label={field.label} type="text" inputMode={field.type==='integer'?'numeric':'decimal'} value={value} disabled={explicitAgents&&path.startsWith('population.')} aria-invalid={Boolean(error)} aria-describedby={error?errorId:undefined} onChange={event=>editNumber(path,event.target.value)} onBlur={commitNumbers}/>{error&&<span className="config-field-error" id={errorId}>{error}</span>}</label>;
  };
  const action=async(kind:string)=>{
    if(busyRef.current)return;
    let config:Obj;
    try{config=readDraft();}catch(error){reportDraftError(error);return;}
    busyRef.current=true;setBusy(true);let handedOff=false;
    try{
      setDraftValue(config);
      if(kind==='start'){
        const validated=await api('/config/validate',config);
        const seeds=batchSeeds.trim()?batchSeeds.split(',').map(v=>v.trim()?Number(v.trim()):NaN):[validated.resolved.seed];
        if(seeds.length>8||seeds.some(seed=>!Number.isInteger(seed)||seed<0))throw Error('Enter at most eight nonnegative integer seeds.');
        for(const seed of seeds){
          const run=await api('/runs',{config:{...validated.resolved,seed},command_id:id(),start:true,wait_for_initialization:false});
          onStartState(run.run_id,true);
          if(!handedOff){handedOff=true;onCreated(run.run_id);onClose();}
          // Initialization belongs to the selected run screen. A late start
          // acknowledgement updates controls without reselecting that run.
          let ack:Obj;
          try{
            ack=await api(`/commands/${run.command_id}:start`);
            while(ack.status==='pending'){await new Promise(resolve=>setTimeout(resolve,150));ack=await api(`/commands/${run.command_id}:start`);}
          }catch(e){onStartState(run.run_id,true,undefined,true);throw e;}
          onStartState(run.run_id,false,ack.generation);
          if(ack.status!=='applied')throw Error(ack.error||'Run could not be started');
        }
      }else{
        const data=await api(`/config/${kind}`,config);setIssues([]);
        if(data.view){setPreview(data.view);setArtifactId(data.artifact_id);}
        setResult(`Valid configuration · ${data.resolved.fingerprint.slice(0,14)} · ${data.view?'Placement preview is independent of the live run.':'Configuration checks passed. Preview checks connectivity and generated placement before launch.'}`);
      }
    }catch(e:any){
      if(handedOff)onError(e.message);
      else reportDraftError(e);
    }finally{if(!handedOff){busyRef.current=false;setBusy(false);}}
  };
  const exportDraft=async()=>{
    if(busyRef.current)return;
    let config:Obj;
    try{config=readDraft();}catch(error){reportDraftError(error);return;}
    busyRef.current=true;setBusy(true);
    try{const data=await api('/config/export',{config,format:exportFormat});download(`scenario.${exportFormat}`,data.text);setResult('Configuration exported.');setIssues([]);}
    catch(error){reportDraftError(error);}
    finally{busyRef.current=false;setBusy(false);}
  };
  const importDraft=async(file?:File)=>{
    if(!file||busyRef.current)return;
    try{requireReady();}catch(error){reportDraftError(error);return;}
    busyRef.current=true;setBusy(true);
    try{const data=await api('/config/import',{text:await file.text(),format:file.name.endsWith('.toml')?'toml':'json'});const imported=parseConfigurationDraft(JSON.stringify(data.config)??'');readRoleGroups(imported,metadata!.presets);replaceDraft(imported);}
    catch(error){reportDraftError(error);}
    finally{busyRef.current=false;setBusy(false);}
  };
  const saveDraft=()=>{
    if(busyRef.current)return;
    try{requireReady();if(Object.keys(numericTextRef.current).length||Object.keys(roleTextRef.current).length)readDraft();localStorage.setItem('zombie-draft',advancedRef.current);setResult('Draft saved in this workspace. Use Load saved draft to reopen it.');}
    catch(error){reportDraftError(error);}
  };
  const loadSavedDraft=()=>{
    if(busyRef.current)return;
    try{requireReady();const saved=localStorage.getItem('zombie-draft');if(saved===null)throw Error('No saved draft is available in this browser workspace.');editAdvanced(saved);setModelEditorVersion(value=>value+1);try{setDraftValue(parseConfigurationDraft(saved));setResult('Saved draft loaded. Validate it before launching.');}catch(error){reportDraftError(error);}}
    catch(error){reportDraftError(error);}
  };
  let advancedError='';if(ready){try{parseConfigurationDraft(advanced);}catch(error){advancedError=(error as Error).message;}}
  let resizeSummary;try{resizeSummary=worldResizeSummary(parseConfigurationDraft(advanced));}catch{}
  const discardAdvanced=()=>{setAdvancedValue(JSON.stringify(draftRef.current,null,2));clearDraftFeedback();};
  useLayoutEffect(()=>{let allocation;try{allocation=readRoleGroups(parseConfigurationDraft(advanced),metadata?.presets||{});}catch{}inspection.configuration={draft,preview,artifact_id:artifactId,issues,load_state:loadState,numeric_text:numericText,numeric_errors:numericErrors,role_text:roleText,role_errors:roleErrors,role_allocation:allocation,advanced_error:advancedError,start_disabled:unavailable||issues.length>0};});
  return <div className="modal-backdrop"><section role="dialog" aria-modal="true" aria-labelledby="config-title" className="config-modal" ref={modal} aria-busy={loadState.phase==='loading'}><header><div><span className="eyebrow">NEW EXPERIMENT</span><h2 id="config-title">Configure your world</h2></div><button onClick={onClose} aria-label="Close configuration">✕</button></header>{loadState.phase==='loading'&&<div className="config-load-state" data-testid="config-loading" role="status">Loading configuration… Presets and editor fields will be ready shortly.</div>}{loadState.phase==='failed'&&<div className="config-load-state config-load-error" data-testid="config-load-error" role="alert"><p>Could not load configuration. {loadState.error}</p><button data-testid="config-retry" onClick={()=>{setLoadingState({phase:'loading'});setLoadAttempt(value=>value+1);}}>Retry loading configuration</button></div>}<div className="config-body"><fieldset className="config-editor" disabled={unavailable} aria-label="Configuration editor">{advancedError&&<div className="config-json-unapplied" data-testid="config-json-unapplied" role="status"><p>{advancedError} Your unfinished JSON is kept. Complete it below, or discard it to resume field editing, presets, imports and saved-draft loading.</p><button type="button" data-testid="config-discard-json" onClick={discardAdvanced}>Discard unfinished JSON</button></div>}<fieldset className="config-fields" disabled={Boolean(advancedError)} aria-label="Configuration fields"><label>Starting preset<select data-testid="config-preset" defaultValue={source?"copy":"small"} onChange={e=>{if(unavailable||!metadata)return;const p=e.target.value==='copy'?source!:metadata.presets[e.target.value];replaceDraft(structuredClone(p));}}>{source&&<option value="copy">Copy of selected run · new identity</option>}<option value="small">Small · 20 agents</option><option value="baseline">Ontology baseline · 1,000 agents</option></select></label><button type="button" data-testid="config-load-saved" disabled={unavailable} onClick={loadSavedDraft}>Load saved draft</button><section className="world-resize-note" aria-label="World layout resizing"><p data-testid="config-world-resize-help">Changing World length or World width resizes the whole layout, including custom geometry and initial agent positions. Counts, resources, speeds, sensing ranges and initial spacing stay as set.</p>{resizeSummary&&<div data-testid="config-world-resize-summary" role="status">{resizeSummary.customizedBaseline&&<strong data-testid="config-customized-baseline">Customized baseline</strong>}<p>{resizeSummary.text}</p></div>}</section><div className="form-grid">{metadata?.fields.filter((f:Obj)=>!['execution.workers','human_model','zombie_model'].includes(f.path)).map((f:Obj)=>f.type==='text'?<label key={f.path}>{f.label}{f.unit&&<small>{f.unit}</small>}<input data-testid={`config-${f.path}`} type="text" value={f.path.split('.').reduce((o:any,k:string)=>o?.[k],draft)??''} onChange={e=>change(f.path,e.target.value)}/></label>:numberInput(f))}</div>{ready&&<ModelSelection key={modelEditorVersion} advanced={advanced} catalog={metadata!.models} onChange={changeModel}/>} {ready&&<RoleAllocationPanels advanced={advanced} presets={metadata!.presets} text={roleText} errors={roleErrors} populationPending={Object.keys(numericText).some(path=>path==='population.humans'||path==='population.zombies')} onEdit={editRole} onCommit={commitNumbers}/>}<label>Worker selection<select aria-label="Worker selection" value={draft.execution?.workers==='auto'?'auto':'manual'} onChange={e=>change('execution.workers',e.target.value==='auto'?'auto':1)}><option value="auto">Automatic · available CPU resources</option><option value="manual">Manual worker limit</option></select></label>{draft.execution?.workers!=='auto'&&numberInput({path:'execution.workers',label:'Workers',type:'integer'})}<label>Placement sampler<select aria-label="Placement sampler" value={draft.placement?.sampler||'exact'} onChange={e=>change('placement.sampler',e.target.value)}><option value="exact">Exact joint rejection</option><option value="relocation">Conditional relocation (approximate)</option></select></label>{draft.placement?.sampler==='relocation'&&<label className="check"><input type="checkbox" checked={draft.placement.allow_approximate||false} onChange={e=>change('placement.allow_approximate',e.target.checked)}/>Explicitly accept approximate joint placement; all separation constraints remain strict.</label>}<label>Replicate seeds · optional, at most 8<input placeholder="Example: 42, 43, 44" value={batchSeeds} onChange={e=>{setBatchSeeds(e.target.value);clearDraftFeedback();retainNumericFeedback();}}/><small>Blank launches one run using the seed above.</small></label><label>Live storage<select aria-label="Live storage" value={draft.storage?.backend||'memory'} onChange={e=>change('storage.backend',e.target.value)}><option value="memory">Memory + durable SQLite history</option><option value="sqlite">SQLite live state + history</option></select></label><label className="check"><input type="checkbox" checked={draft.interventions_enabled||false} onChange={e=>change('interventions_enabled',e.target.checked)}/>Authorize resource, role, and model interventions for this experiment.</label></fieldset><details><summary>Advanced configuration · JSON</summary><p>All profiles, role allocations, resources, geometry, and execution settings remain available here.</p><textarea aria-label="Advanced configuration JSON" value={advanced} onChange={e=>editAdvanced(e.target.value)} rows={18}/><button data-testid="config-export" disabled={unavailable} onClick={exportDraft}>Export draft</button><label>Export format<select data-testid="config-export-format" value={exportFormat} onChange={e=>setExportFormat(e.target.value)}><option value="json">JSON</option><option value="toml">TOML</option></select></label><label>Import configuration<input data-testid="config-import" disabled={Boolean(advancedError)} type="file" accept=".json,.toml" onChange={e=>{void importDraft(e.target.files?.[0]);}}/></label></details></fieldset><div className="preview-pane"><div className="legend"><span data-status-token="HEALTHY">● Healthy</span><span data-status-token="INFECTED">◉ INFECTED</span><span data-status-token="ACTIVE">▲ Zombie</span><span data-status-token="DEAD">× Dead</span></div>{preview?<World state={preview.state} selected="" onSelect={()=>{}}/>:<div className="empty"><span className="empty-icon">◎</span><h3>Inspect before you launch</h3><p>Validate parameters, then generate an isolated initialization preview with the chosen seed.</p></div>}<p className="notice">The baseline requires an explicit approximate-sampler opt-in for practical placement. Exact sampling never silently falls back.</p></div></div><p className={`config-feedback ${issues.length?'config-feedback-error':''}`} data-testid="config-result" role={issues.length?'alert':'status'} hidden={!result}>{result}</p><footer><button data-testid="config-validate" disabled={unavailable} onClick={()=>action('validate')}>Validate</button><button data-testid="config-save" disabled={unavailable} onClick={saveDraft}>Save draft</button><button data-testid="config-preview" disabled={unavailable} onClick={()=>action('preview')}>{busy?'Working…':'Preview placement'}</button><button data-testid="config-launch" className="primary" disabled={unavailable||issues.length>0} onClick={()=>action('start')}>Launch run ↗</button></footer></section></div>;
}

function InterventionDialog({view,run,onClose,onCommand,onBranch}:{view:Bundle;run:Obj;onClose:()=>void;onCommand:(operation:string,extra:Obj)=>Promise<void>;onBranch:(seed:number)=>Promise<void>}){
  const modal=useRef<HTMLElement>(null);useModalFocus(modal,onClose);const[mode,setMode]=useState('branch');const[kind,setKind]=useState('add_resource');const[agent,setAgent]=useState(values(view.state.agents)[0]?.id||'');const[stock,setStock]=useState(Object.keys(view.state.stockpiles||{})[0]||'');const[resource,setResource]=useState('FOOD');const[quantity,setQuantity]=useState(10);const[x,setX]=useState(0);const[y,setY]=useState(0);const[role,setRole]=useState('');const[model,setModel]=useState('HumanDefaultModel');const[time,setTime]=useState(view.time);const[seed,setSeed]=useState(run.config.seed);const[busy,setBusy]=useState(false);
  const submit=async()=>{setBusy(true);try{if(mode==='branch')await onBranch(seed);else{let change:Obj={kind};if(kind==='add_resource')change={kind,stockpile:stock||undefined,resource,quantity,x,y};else if(kind==='replace_role')change={kind,agent,role:role||null};else change={kind,agent,model_id:model,memory_policy:"reset"};await onCommand('intervene',{change,time,revision:view.revision});}onClose();}finally{setBusy(false);}};
  return <div className="modal-backdrop"><section className="config-modal intervention-modal" ref={modal} role="dialog" aria-modal="true" aria-labelledby="intervention-title"><header><div><span className="eyebrow">EXPLICIT RESEARCH CONTROL</span><h2 id="intervention-title">Branch or intervene</h2></div><button aria-label="Close intervention dialog" onClick={onClose}>✕</button></header><div className="intervention-body"><label>Operation<select value={mode} onChange={e=>setMode(e.target.value)}><option value="branch">Create a child run at this revision</option><option value="intervene" disabled={!run.config.interventions_enabled}>Schedule an authorized intervention</option></select></label>{mode==='branch'?<><p>A new run retains pending actions, reservations, policy memory, and explicit parent lineage. The parent remains unchanged. Pause and select any committed revision in recorded history.</p><p>Parent {run.id.slice(0,12)} · revision {view.revision} · time {view.time} s</p><label>Child seed<input type="number" min={0} value={seed} onChange={e=>setSeed(Number(e.target.value))}/></label><p>Retaining the seed aligns matching random domains; changing it makes subsequent draws independent. Pending queue priorities are inherited.</p></>:<><label>Effective simulation time (s)<input value={time} onChange={e=>setTime(e.target.value)}/></label><label>Change<select value={kind} onChange={e=>setKind(e.target.value)}><option value="add_resource">Add resources</option><option value="replace_role">Replace compatible role</option><option value="replace_model">Replace decision model</option></select></label>{kind==='add_resource'?<><label>Stockpile<select value={stock} onChange={e=>setStock(e.target.value)}><option value="">New ground stock at coordinates</option>{Object.keys(view.state.stockpiles||{}).map(s=><option key={s}>{s}</option>)}</select></label>{!stock&&<div className="form-grid"><label>x (m)<input type="number" min={0} max={view.state.world.length} value={x} onChange={e=>setX(Number(e.target.value))}/></label><label>y (m)<input type="number" min={0} max={view.state.world.width} value={y} onChange={e=>setY(Number(e.target.value))}/></label></div>}<div className="form-grid"><label>Resource<select value={resource} onChange={e=>setResource(e.target.value)}>{['FOOD','MEDICAL_SUPPLY','MATERIAL'].map(r=><option key={r}>{r}</option>)}</select></label><label>Quantity<input type="number" min={1} step={1} value={quantity} onChange={e=>setQuantity(Number(e.target.value))}/></label></div></>:<><label>Agent identity<input value={agent} onChange={e=>setAgent(e.target.value)}/></label>{kind==='replace_role'?<label>Role<select value={role} onChange={e=>setRole(e.target.value)}><option value="">No active role</option>{['DOCTOR','WARRIOR','SCOUT','ENGINEER','TYRANT','RUNNER','SPITTER','SCREAMER'].map(r=><option key={r}>{r}</option>)}</select></label>:<label>Registered model<input value={model} onChange={e=>setModel(e.target.value)}/><small>Replacement explicitly resets this agent’s private model memory.</small></label>}</>}<p>The engine checks compatibility and invariants at the intervention phase. A scheduled change appears in the causal timeline with its actual outcome.</p></>}{!run.config.interventions_enabled&&<p className="notice">This run's frozen configuration does not authorize interventions. Enable them in a new experiment before launch.</p>}</div><footer><button onClick={onClose}>Cancel</button><button className="primary" disabled={busy} onClick={submit}>{busy?'Applying…':mode==='branch'?'Create child run':'Schedule intervention'}</button></footer></section></div>;
}

function ViewerLoadPanel({state,run,hasView,onCancel,onRetry,onReturn}:{state:ViewerLoad;run?:Obj;hasView:boolean;onCancel:()=>void;onRetry:()=>void;onReturn:()=>void}){
  if(state.phase==='idle'||state.phase==='ready')return null;
  const failed=state.phase==='failed';const initializing=state.phase==='initializing';
  const hasBoundary=run?.frontier?.time!=null&&run?.frontier?.revision!=null;
  return <section className={`viewer-load panel ${hasView?'viewer-load-compact':''}`} data-testid={failed?'viewer-error':'viewer-loading'} aria-live="polite" aria-busy={!failed}>
    <span className="eyebrow">{failed?'VIEWER ERROR':initializing?'RUN INITIALIZATION':'HISTORY VIEWER'}</span>
    <h2>{failed?'Could not load this view':initializing?'Initializing the world…':state.details?'Loading run information…':'Loading recorded history…'}</h2>
    {failed?<p role="alert">{state.error||'The requested view is unavailable.'}</p>:initializing?<p>The service is initializing this run, including its geometry and population.</p>:<p>{state.details?'Waiting for the service to report this run.':'Reading the selected run’s recorded state. Large histories can take longer to open.'}</p>}
    <p className="viewer-run-reference">{run?.config.scenario||'Selected run'} · <code>{state.run_id}</code>{hasBoundary&&<> · committed {fixed(run!.frontier.time)} s · revision {run!.frontier.revision}</>}</p>
    {hasView&&<p>The last loaded view remains below until the requested view is ready.</p>}
    <div className="viewer-load-actions">{failed?<><button data-testid="viewer-retry" className="primary" onClick={onRetry}>Retry loading</button><button data-testid="viewer-return-list" onClick={onReturn}>Return to run list</button></>:<button data-testid="viewer-cancel" onClick={onCancel}>Cancel loading and return to runs</button>}</div>
    {!failed&&<p className="viewer-load-note">Cancelling this viewer does not stop the simulation. Atomic reader work already in progress may finish before cancellation takes effect.</p>}
  </section>;
}

function App(){
  const[runs,setRuns]=useState<Obj[]>([]);const[runId,setRunId]=useState('');const[view,setView]=useState<Bundle>();const[mode,setMode]=useState<'live'|'replay'>('live');const[seek,setSeek]=useState('0');const[selected,setSelected]=useState('');const[follow,setFollow]=useState(false);const[tab,setTab]=useState('world');const[configOpen,setConfigOpen]=useState(false);const[configSource,setConfigSource]=useState<Obj>();const[interventionOpen,setInterventionOpen]=useState(false);const[error,setError]=useState('');const[notice,setNotice]=useState('');const[pending,setPending]=useState(false);const[filter,setFilter]=useState('');const[eventFilter,setEventFilter]=useState('');const[eventDetailData,setEventDetail]=useState<Obj>();const[eventDetailSource,setEventDetailSource]=useState<MetricCursor>();const[layers,setLayers]=useState<Obj>({resources:true,remains:true,labels:true,actions:true,trails:false,sensing:false,agents:true});const[perspective,setPerspective]=useState('researcher');const[observation,setObservation]=useState<Obj>();const[playing,setPlaying]=useState(false);const[replaySpeed,setReplaySpeed]=useState(1);const[commandResult,setCommandResult]=useState<Obj>();const[viewPending,setViewPending]=useState(false);
  const[comparisonChosen,setComparisonChosen]=useState<string[]>([]);const[comparisonMetric,setComparisonMetric]=useState('infected');
  const viewRef=useRef(view);viewRef.current=view;
  const[terminationRequest,setTerminationRequest]=useState('');
  const[viewerLoad,setViewerLoad]=useState<ViewerLoad>({phase:'idle',run_id:''});
  const[runListState,setRunListState]=useState<{phase:'loading'|'ready'|'failed';error?:string;version?:number}>({phase:'loading'});
  const[,setStatusTick]=useState(0);
  useEffect(()=>{const timer=setInterval(()=>setStatusTick(value=>value+1),1000);return()=>clearInterval(timer);},[]);
  // The timer refreshes an idle replay, but every render samples the real clock.
  // Reusing the previous tick could briefly mark a late response as fresh.
  const statusNow=Date.now();
  const[viewAttempt,setViewAttempt]=useState(0);
  const[startingRuns,setStartingRuns]=useState<Record<string,boolean>>({});
  const starting=Boolean(startingRuns[runId]);
  const uncertainStarts=useRef(new Set<string>());
  const viewerLoadRef=useRef(viewerLoad);viewerLoadRef.current=viewerLoad;
  const viewAbort=useRef<AbortController|undefined>(undefined);const streamRef=useRef<WebSocket|undefined>(undefined);
  const lastViewRequest=useRef<{time?:string;revision?:string}>({});
  const setViewerState=(state:ViewerLoad)=>{viewerLoadRef.current=state;setViewerLoad(state);};
  const selectionSummaryAfter=useRef(0);
  const requestGeneration=useRef(0);const listRequest=useRef(0);const listInFlight=useRef(false);const runIdRef=useRef(runId);runIdRef.current=runId;
  const controlGenerations=useRef<Record<string,number>>({});const commandBusy=useRef(false);
  const liveRef=useRef(mode);liveRef.current=mode;const perspectiveRef=useRef(perspective);perspectiveRef.current=perspective;
  const run=runs.find(r=>r.id===runId);const finished=['completed','terminated'].includes(run?.status);
  const executionFreshness=statusFreshness(run,runListState.phase,statusNow);
  const runRef=useRef(run);runRef.current=run;
  const unknownSummaryVersion=run?0:(runListState.version??0);
  const terminalCursor=isInactiveRun(run)?`${run?.status}:${run?.frontier?.revision??''}`:'';
  const statistics=useStatisticsReader({runId,mode,perspective,selectionVersion:mode==='replay'?requestGeneration.current:0,
    getCursor:()=>{
      const current=viewRef.current;
      if(!current||current.run_id!==runIdRef.current||perspectiveRef.current!=='researcher'||viewerLoadRef.current.phase!=='ready')return;
      if(isInactiveRun(runRef.current)&&liveRef.current==='live'&&String(current.revision)!==String(runRef.current?.frontier?.revision))return;
      return {run_id:current.run_id,time:String(current.time),revision:String(current.revision)};
    },fetchMetrics:(cursor,signal)=>api(`/runs/${cursor.run_id}/metrics?end=${encodeURIComponent(cursor.time)}&revision=${cursor.revision}`,undefined,signal)});
  const metricsState:MetricRead=perspective==='researcher'&&(!statistics.read.cursor||statistics.read.cursor.run_id===runId)?statistics.read:{phase:'idle'};
  const samples=metricsState.data?.samples||[];const eventCounts=metricsState.data?.event_counts||{};
  const metricsCursor=metricsState.cursor?{...metricsState.cursor,populations:samples.at(-1)}:undefined;
  const cohortReader=useCohortReader({runId,mode,perspective,selectionVersion:mode==='replay'?requestGeneration.current:0,
    getCursor:()=>{
      const current=viewRef.current;
      if(!current||current.run_id!==runIdRef.current||perspectiveRef.current!=='researcher'||viewerLoadRef.current.phase!=='ready')return;
      if(isInactiveRun(runRef.current)&&liveRef.current==='live'&&String(current.revision)!==String(runRef.current?.frontier?.revision))return;
      return {run_id:current.run_id,time:String(current.time),revision:String(current.revision)};
    },fetchCohorts:(cursor,signal)=>api(`/runs/${cursor.run_id}/cohorts?time=${encodeURIComponent(cursor.time)}&revision=${cursor.revision}&with_cursor=true`,undefined,signal)});
  const cohortsState:CohortRead=perspective==='researcher'&&(!cohortReader.read.cursor||cohortReader.read.cursor.run_id===runId)?cohortReader.read:{phase:'idle'};
  const cohorts=cohortsState.data?.cohorts||[];const cohortsCursor=cohortsState.cursor;
  const eventReader=useEventsReader({runId,mode,perspective,selectionVersion:mode==='replay'?requestGeneration.current:0,agent:selected,
    getCursor:()=>{
      const current=viewRef.current;
      if(!current||current.run_id!==runIdRef.current||perspectiveRef.current!=='researcher'||viewerLoadRef.current.phase!=='ready')return;
      if(isInactiveRun(runRef.current)&&liveRef.current==='live'&&String(current.revision)!==String(runRef.current?.frontier?.revision))return;
      return {run_id:current.run_id,time:String(current.time),revision:String(current.revision)};
    },fetchEvents:(request,signal)=>{
      const query=new URLSearchParams({time:request.cursor.time,revision:request.cursor.revision,limit:String(request.limit)});
      if(request.agent!==null)query.set('agent',request.agent);
      if(request.before_sequence)query.set('before_sequence',request.before_sequence);
      if(request.after_sequence)query.set('after_sequence',request.after_sequence);
      return api(`/runs/${request.cursor.run_id}/timeline?${query}`,undefined,signal);
    }});
  const eventsState=eventReader.read;const events=eventsState.data?.records||[];
  const timelineOccurrences=eventsState.data?.occurrences||{};const eventsCursor=eventsState.cursor;const auxiliaryCursor=eventsCursor;
  const eventDetail=perspective==='researcher'&&eventDetailSource?.run_id===runId?eventDetailData:undefined;
  const comparison=useComparisonReader({currentRun:runId,perspective,visible:tab==='comparison'&&Boolean(view),chosen:comparisonChosen,runs,
    fetchComparison:(sources,signal)=>api('/comparison',{sources},signal)});
  const comparisonContextRef=useRef(comparison.context);comparisonContextRef.current=comparison.context;

  const runGroups=[{id:'active',label:'Active'},{id:'saved',label:'Saved / completed'},{id:'terminated',label:'Terminated history'}];
  const frontier=seconds(run?.frontier?.time||view?.time||0);const agent=selected?view?.state.agents?.[selected]:null;
  const cancelViewerRequest=()=>{viewAbort.current?.abort();viewAbort.current=undefined;requestGeneration.current++;streamRef.current?.close();streamRef.current=undefined;};
  const selectRun=(identity:string)=>{
    if(identity!==runIdRef.current)setComparisonChosen(identity?[identity]:[]);
    delete inspection.comparison;delete inspection.comparison_chart;
    cancelViewerRequest();delete inspection.statistics_chart;runIdRef.current=identity;viewRef.current=undefined;setView(undefined);setViewPending(false);
    liveRef.current='live';perspectiveRef.current='researcher';setMode('live');setPerspective('researcher');setPlaying(false);
    setRunId(identity);setError('');setNotice('');
    const next=runs.find(row=>row.id===identity);runRef.current=next;selectionSummaryAfter.current=listRequest.current+1;
    setViewerState({phase:identity?(next?.status==='initializing'?'initializing':'loading'):'idle',run_id:identity,details:!next});
    if(identity===runId)setViewAttempt(value=>value+1);
    if(identity&&!next)refreshRuns();
  };
  const returnToRuns=()=>{
    const loading=['loading','initializing'].includes(viewerLoadRef.current.phase);selectRun('');
    setNotice(loading?'Viewer loading cancelled. Simulation execution is unchanged. Any atomic reader work already in progress may finish before it stops.':'Returned to the run list. Simulation execution is unchanged.');
  };
  const refreshRuns=useCallback(async()=>{
    // A slow summary request must be allowed to finish. Starting a replacement
    // every second would make every response stale when latency exceeds 1 s.
    if(listInFlight.current)return;listInFlight.current=true;
    const token=++listRequest.current;const requestedAt=Date.now();
    try {
      let data=await api('/runs');if(token!==listRequest.current)return;if(perspectiveRef.current==='agent')data=data.map((item:Obj)=>({...item,config:{scenario:item.config.scenario,seed:item.config.seed,horizon:item.config.horizon}}));
      for(const item of data){
        if(controlGenerations.current[item.id]===undefined)controlGenerations.current[item.id]=item.generation;
        // Reconcile only our own accepted start requests whose receipt was
        // lost. Ordinary pending ACKs and unrelated tabs retain their guards.
        if(uncertainStarts.current.has(item.id)&&item.status!=='initializing'&&(Number(item.generation)>0||isInactiveRun(item))){
          controlGenerations.current[item.id]=item.generation;uncertainStarts.current.delete(item.id);
          setStartingRuns(previous=>({...previous,[item.id]:false}));
        }
      }
      setRuns(old=>data.map((item:Obj)=>{
        const previous=old.find(row=>row.id===item.id);
        return newestRunStatus(previous,{...item,status_read_started_at:requestedAt});
      }));
      setRunListState({phase:'ready',version:token});
    } catch(e:any){if(token===listRequest.current)setRunListState({phase:'failed',error:e.message});}
    finally{listInFlight.current=false;}
  },[]);
  useEffect(()=>{refreshRuns();const timer=setInterval(refreshRuns,1000);return()=>clearInterval(timer);},[refreshRuns]);
  useEffect(()=>{setSelected('');setObservation(undefined);setEventDetail(undefined);setEventDetailSource(undefined);setEventFilter('');},[runId]);
  const acceptView=(data:Bundle,identity:string)=>{
    if(runIdRef.current!==identity||data.run_id!==identity||perspectiveRef.current!=='researcher')return;
    const old=viewRef.current;
    if(liveRef.current==='live'&&old?.run_id===identity&&old.mode==='live'&&BigInt(data.revision)<BigInt(old.revision))return;
    inspection.transport.application_trace.push({run_id:identity,revision:data.revision,mode:liveRef.current,at:performance.now()});
    viewRef.current=data;setView(data);setSeek(data.time);setViewerState({phase:'ready',run_id:identity});
  };
  const loadView=async(time?:string,revision?:string)=>{
    const identity=runIdRef.current;if(!identity||perspectiveRef.current!=='researcher')return;
    viewAbort.current?.abort();const controller=new AbortController();viewAbort.current=controller;
    const token=++requestGeneration.current;lastViewRequest.current={time,revision};setViewPending(true);
    setViewerState({phase:'loading',run_id:identity});
    try {
      const query=new URLSearchParams({generation:String(token)});if(time!==undefined)query.set('time',time);if(revision!==undefined)query.set('revision',revision);
      const data=await api(`/runs/${identity}/view?${query}`,undefined,controller.signal);
      if(!data||data.run_id!==identity||!data.state?.world||!data.state?.agents||!data.metrics?.populations||data.revision===undefined||data.time===undefined){
        throw Error('The service returned an incomplete history view. Retry loading or return to the run list.');
      }
      if(!controller.signal.aborted&&token===requestGeneration.current&&identity===runIdRef.current&&perspectiveRef.current==='researcher'){
        acceptView(data,identity);return data;
      }
    } catch(e:any){
      if(!controller.signal.aborted&&token===requestGeneration.current&&identity===runIdRef.current){
        const currentRun=runRef.current;
        if(e.code==='RUN_INITIALIZING'&&currentRun?.status==='initializing')setViewerState({phase:'initializing',run_id:identity});
        else if(e.code==='RUN_INITIALIZING'&&!currentRun)setViewerState({phase:'loading',run_id:identity,details:true});
        else setViewerState({phase:'failed',run_id:identity,error:e.code==='RUN_INITIALIZING'?`Recorded history is unavailable for this ${currentRun?.status} run (${e.code}). Retry loading or return to the run list.`:e.message});
      }
    } finally{
      if(token===requestGeneration.current&&identity===runIdRef.current){setViewPending(false);if(viewAbort.current===controller)viewAbort.current=undefined;}
    }
  };
  const retryView=()=>{if(!runRef.current){selectionSummaryAfter.current=listRequest.current+1;setViewerState({phase:'loading',run_id:runIdRef.current,details:true});}refreshRuns();if(mode==='live')setViewAttempt(value=>value+1);else loadView(lastViewRequest.current.time,lastViewRequest.current.revision);};
  useEffect(()=>{
    if(!runId||mode!=='live'||perspective!=='researcher')return;
    if(runListState.phase==='failed'&&(!viewRef.current||run?.status==='initializing')){
      setViewerState({phase:'failed',run_id:runId,error:runListState.error});return;
    }
    if(run?.status==='initializing'){
      setViewerState({phase:'initializing',run_id:runId});return;
    }
    if(!run){
      // An accepted new identity can precede the next lightweight summary.
      // Never probe its history merely because an older run list was ready.
      const missing=runListState.phase==='ready'&&(runListState.version??0)>=selectionSummaryAfter.current;
      setViewerState(missing?{phase:'failed',run_id:runId,error:'This run is no longer listed by the service. Retry loading or return to the run list.'}:{phase:'loading',run_id:runId,details:true});return;
    }
    let disposed=false;let terminalPacket=false;let socket:WebSocket|undefined;let ownedController:AbortController|undefined;let retry:ReturnType<typeof setTimeout>;
    const current=viewRef.current;
    if(terminalCursor&&current?.run_id===runId&&current.mode==='live'&&String(current.revision)===String(runRef.current?.frontier?.revision)){
      // Cleanup may have invalidated an in-flight refresh's generation. Its
      // finally block then cannot clear pending; this verified reused view can.
      setViewPending(false);setViewerState({phase:'ready',run_id:runId});return;
    }
    const connect=async()=>{
      if(disposed||runIdRef.current!==runId)return;
      const loading=loadView();ownedController=viewAbort.current;const first=await loading;if(disposed||runIdRef.current!==runId)return;
      if(!first){
        // Only genuine, service-confirmed initialization is retried without a
        // click. A loading failure has its own error and explicit retry path.
        if(viewerLoadRef.current.phase==='initializing')retry=setTimeout(connect,1000);
        return;
      }
      if(isInactiveRun(first.control)||isInactiveRun(runRef.current))return;
      socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/runs/${runId}/stream`);streamRef.current=socket;
      socket.onmessage=event=>{
        if(disposed||streamRef.current!==socket||runIdRef.current!==runId||liveRef.current!=='live'||perspectiveRef.current!=='researcher')return;
        try {
          inspection.transport.queue_depth++;inspection.transport.max_queue_depth=Math.max(inspection.transport.max_queue_depth,inspection.transport.queue_depth);
          const data=JSON.parse(event.data);
          if(!disposed&&streamRef.current===socket&&runIdRef.current===runId&&liveRef.current==='live'&&perspectiveRef.current==='researcher')acceptView(data,runId);
          terminalPacket=isInactiveRun(data.control);socket?.send(JSON.stringify({ack:data.sequence}));
        }
        catch(e:any){if(!disposed)setError(`Live update could not be read: ${e.message}`);}
        finally {inspection.transport.queue_depth=Math.max(0,inspection.transport.queue_depth-1);}
      };
      socket.onclose=()=>{if(!disposed&&streamRef.current===socket&&!terminalPacket&&runIdRef.current===runId&&liveRef.current==='live'&&perspectiveRef.current==='researcher'&&!isInactiveRun(runRef.current))retry=setTimeout(connect,1000);};
    };
    connect();return()=>{
      disposed=true;clearTimeout(retry);ownedController?.abort();if(ownedController&&viewAbort.current===ownedController){viewAbort.current=undefined;requestGeneration.current++;}socket?.close();
      if(streamRef.current===socket)streamRef.current=undefined;
    };
  },[runId,mode,perspective,terminalCursor,run?.status==='initializing',Boolean(run),runListState.phase,unknownSummaryVersion,viewAttempt]);
  useEffect(()=>{if(!playing||mode!=='replay')return;const timer=setInterval(()=>{setSeek(old=>{const next=Math.min(frontier,seconds(old)+.5*replaySpeed);loadView(String(next));if(next>=frontier)setPlaying(false);return String(next);});},500);return()=>clearInterval(timer);},[playing,replaySpeed,frontier,mode,runId]);
  const replay=(time:string,revision?:string)=>{cancelViewerRequest();liveRef.current='replay';setMode('replay');setSeek(time);setPerspective('researcher');setObservation(undefined);loadView(time,revision);};
  const returnToLive=()=>{cancelViewerRequest();liveRef.current='live';perspectiveRef.current='researcher';setMode('live');setPlaying(false);setPerspective('researcher');setObservation(undefined);};
  const command=async(operation:string,extra:Obj={})=>{
    const identity=runIdRef.current;if(!identity||commandBusy.current||startingRuns[identity])return;
    const requestedAt=Date.now();
    commandBusy.current=true;setPending(true);setError('');setNotice(`${operation.replaceAll('_',' ')} requested…`);if(operation==='terminate')setTerminationRequest(identity);
    try {
      let result=await api(`/runs/${identity}/commands`,{operation,command_id:id(),generation:controlGenerations.current[identity]??run?.generation,...extra});
      while(result.status==='pending'){await new Promise(r=>setTimeout(r,150));result=await api(`/commands/${result.command_id}`);}
      setCommandResult(result);if(result.status==='rejected')throw Error(result.error);
      // Apply our own acknowledgement immediately. Waiting for the next poll
      // permits a second click to send the previous generation.
      controlGenerations.current[identity]=result.generation;
      setRuns(rows=>rows.map(row=>row.id===identity?newestRunStatus(row,{...row,generation:result.generation,status:result.run_status,status_read_started_at:requestedAt,
        resource_status:operation==='terminate'?{...row.resource_status,phase:'stopping',cleanup_complete:false}:row.resource_status,
        frontier:{...row.frontier,time:result.time,revision:result.revision,generation:result.generation,status:result.run_status,pacing:result.pacing??row.frontier?.pacing}}):row));
      if(identity===runIdRef.current){setNotice(`${operation==='terminate'?'Termination acknowledged; waiting for cleanup':'Applied'} at ${fixed(result.time)} s · revision ${result.revision}`);if(liveRef.current==='live'&&!isInactiveRun({status:result.run_status}))await loadView();}
      await refreshRuns();
    } catch(e:any){if(identity===runIdRef.current)setError(e.message);await refreshRuns();}
    finally{commandBusy.current=false;setPending(false);setTerminationRequest('');}
  };
  const selectPerspective=async(value:string)=>{
    if(value==='agent'&&!selected){setError('Select an agent first.');return;}
    cancelViewerRequest();delete inspection.comparison;delete inspection.comparison_chart;perspectiveRef.current=value;setViewPending(false);setPerspective(value);setObservation(undefined);setEventDetail(undefined);setEventDetailSource(undefined);setPlaying(false);
    if(value==='agent'){
      const cursor=viewRef.current;inspection.configuration={};delete inspection.statistics_chart;setConfigSource(undefined);setConfigOpen(false);setRuns(rows=>rows.map(row=>({...row,config:{scenario:row.config.scenario,seed:row.config.seed,horizon:row.config.horizon}})));
      // The only retained scene is the selected observer's later recorded input.
      viewRef.current=undefined;setView(undefined);
      const identity=runIdRef.current;const token=++requestGeneration.current;const controller=new AbortController();viewAbort.current=controller;
      try{const recorded=await api(`/runs/${identity}/observations/${selected}?revision=${cursor?.revision}`,undefined,controller.signal);
        if(controller.signal.aborted||token!==requestGeneration.current||identity!==runIdRef.current||perspectiveRef.current!=='agent')return;setObservation(recorded);
      }catch(e:any){if(!controller.signal.aborted&&token===requestGeneration.current&&identity===runIdRef.current)setError(e.message);}
      finally{if(viewAbort.current===controller)viewAbort.current=undefined;}
    }else if(mode==='replay'){await loadView(lastViewRequest.current.time,lastViewRequest.current.revision);}
  };
  const exportLink=(format:string)=>`/api/runs/${runId}/export?format=${format}&revision=${view?.revision}${mode==='replay'?`&time=${encodeURIComponent(view?.time||'0')}`:''}`;
  const visibleAgents=values(view?.state.agents).filter(a=>[a.id,a.type,a.role,a.status].join(' ').toLowerCase().includes(filter.toLowerCase()));
  const shownEvents=events.filter(event=>JSON.stringify(event).toLowerCase().includes(eventFilter.toLowerCase()));
  useLayoutEffect(()=>{
    inspection.react_commit={at:performance.now(),count:(inspection.react_commit?.count||0)+1};
    if(inspection.comparison?.context!==comparison.context)delete inspection.comparison_chart;
    inspection.comparison={current_run:runId,chosen:comparisonChosen,metric:comparisonMetric,...comparison.read,context:comparison.context,requested_sources:perspective==='researcher'?comparison.requested_sources:[],requested_key:perspective==='researcher'?comparison.requested_key:undefined,stale:comparison.stale,unavailable:comparison.unavailable};
    inspection.app={run_id:runId,mode,seek,perspective,selected,follow,view,observation,events,shownEvents,cohorts,samples,
      selected_event:eventDetail,selected_event_source:eventDetail?eventDetailSource:undefined,timeline_occurrences:timelineOccurrences,events_state:eventsState,events_cursor:eventsCursor,events_page:eventsState.data?.page,events_following:eventReader.following,events_query_key:eventReader.queryKey,metrics_cursor:metricsCursor,metrics_state:metricsState,cohorts_state:cohortsState,cohorts_cursor:cohortsCursor,auxiliary_cursor:auxiliaryCursor,command:commandResult,run,pending,start_pending:starting,start_uncertain:uncertainStarts.current.has(runId),view_pending:viewPending,viewer_load:viewerLoad,run_list_state:runListState,layers,
      privileged_cache_keys:perspective==='agent'?[...(comparison.read.data?['comparison']:[]),...(inspection.comparison_chart?['comparison_chart']:[]),...(view?['view']:[]),...(events.length?['events']:[]),...(samples.length?['samples']:[]),...(cohorts.length?['cohorts']:[]),...(Object.keys(eventCounts).length?['eventCounts']:[]),...(eventDetail?['eventDetail']:[]),...(Object.keys(timelineOccurrences).length?['timelineOccurrences']:[]),...(configSource?['configSource']:[]),...(Object.keys(inspection.configuration).length?['configurationPreview']:[]),...runs.filter(row=>row.config.agents||row.config.barriers||row.config.stockpiles).map(row=>`run-config:${row.id}`)]:[]};
  });
  return <div className="app"><aside className="sidebar"><a className="brand" href="/" aria-label="Outbreak home"><span className="brand-icon">✳</span><div>OUTBREAK<small>SIMULATION WORKSPACE</small></div></a><button className="primary new-run" onClick={()=>{setConfigSource(undefined);setConfigOpen(true);}}>＋ New experiment</button><div className="run-list">{runGroups.map(group=>{
    const grouped=runs.filter(r=>runGroup(r,terminationRequest===r.id)===group.id);
    return <section key={group.id} className="run-group" data-testid={`run-group-${group.id}`} aria-label={group.label}>
      <h2 className="sidebar-title">{group.label}<span>{grouped.length}</span></h2>
      {grouped.map(r=><button key={r.id} data-run-id={r.id} className={`run-card ${r.id===runId?'active':''}`} onClick={()=>selectRun(r.id)}><span className={`status-dot ${r.status}`}/><div><strong>{r.config.scenario||'Untitled scenario'}</strong><small>{r.id.slice(0,8)} · seed {r.config.seed}</small><span>{confirmedStatusLabel(r,statusFreshness(r,runListState.phase,statusNow),terminationRequest===r.id)} · {fixed(r.frontier.time||0)} s</span></div></button>)}
      {!grouped.length&&<p className="run-group-empty">No runs</p>}
    </section>;
  })}</div><div className="sidebar-footer"><span className="eyebrow">ONTOLOGY v0.1</span><p>Asynchronous events.<br/>Exact clocks. Recorded evolution.</p><span className="connection">● Local workspace</span></div></aside>
  <main><header className="topbar"><div><span className="eyebrow">RESEARCH WORKSPACE</span><h1>{run?.config.scenario||'Explore an evolving world'}<span className="tag" data-testid="run-lifecycle-status">{run?confirmedStatusLabel(run,executionFreshness,terminationRequest===runId):'Ready'}</span></h1></div>{runId&&<button data-testid="run-return-list" onClick={returnToRuns}>← Run list</button>}<button data-testid="config-edit-new" onClick={()=>{setConfigSource(run?.config);setConfigOpen(true);}}>{run?'Edit as new run':'Configure new run'}</button></header>
  {error&&<div className="alert" role="alert"><span>{error}</span>{error.includes('Stale control generation')&&<button data-testid="command-refresh" onClick={()=>{if(run)controlGenerations.current[run.id]=run.generation;refreshRuns();setError('');}}>Refresh controls</button>}<button aria-label="Dismiss error" onClick={()=>setError('')}>✕</button></div>}
  {run?.error&&<div className="alert" role="alert">{run.error}</div>}
  <section className="control-bar" aria-label="Run execution controls"><div className="run-controls"><span className="control-label">EXECUTION</span><button data-testid="run-start" className="primary" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'||run.status==='running'} onClick={()=>command('continue')}>▶ Continue run</button><button data-testid="run-pause" aria-label="Pause run" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} onClick={()=>command('pause')}>Ⅱ Pause run</button><button data-testid="run-step-transition" disabled={!runId||pending||starting||run?.status!=='paused'} onClick={()=>command('step')}>Step transition</button><button data-testid="run-step-timestamp" disabled={!runId||pending||starting||run?.status!=='paused'} onClick={()=>command('step_timestamp')}>Step timestamp</button><button disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} data-testid="run-checkpoint" onClick={()=>{const name=window.prompt('Checkpoint name (optional)',`revision-${view?.revision??0}`);if(name!==null)command('checkpoint',{name});}}>Checkpoint</button><button data-testid="run-stop" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} onClick={()=>command('stop')}>Stop & save</button><button data-testid="run-terminate" className="danger" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} aria-describedby="termination-help" title="End this run permanently without writing a new checkpoint. Existing checkpoints and committed audit history are retained." onClick={()=>command('terminate')}>Terminate without a new checkpoint</button><button disabled={!runId||pending||starting||!['paused','stopped','completed'].includes(run?.status)} onClick={()=>setInterventionOpen(true)}>Branch / intervene</button>{run&&view&&!starting&&<CommandDialog run={run} view={view} onApplied={(result,operation)=>{setCommandResult(result);controlGenerations.current[result.run_id]=result.generation??0;if(operation==='start'||operation==='branch')selectRun(result.run_id);setNotice(`Applied at ${result.time??view.time} s · revision ${result.revision??view.revision}`);refreshRuns();loadView();}}/>}</div><label className="pace">Run pace<select data-testid="run-pacing" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} value={run?.frontier?.pacing??1} onChange={e=>command('pace',{pacing:Number(e.target.value)})}><option value={.25}>0.25×</option><option value={1}>1×</option><option value={4}>4×</option><option value={0}>Fastest</option></select></label><span className="ack" aria-live="polite">{terminationNotice(run,terminationRequest===runId)||(pending?'Pending…':starting?'Waiting for the start acknowledgement…':notice)}</span>{run?.frontier?.workers&&<span className="subtle">{run.frontier.workers} workers</span>}{runs.filter(r=>r.id!==runId&&r.status==='running').length>0&&<span className="subtle">{runs.filter(r=>r.id!==runId&&r.status==='running').length} other run(s) running</span>}</section>
  {run&&<p id="termination-help" className="termination-help">Termination skips a new checkpoint and keeps existing checkpoints and committed audit history. An already-running checkpoint may finish before termination takes effect.</p>}
  {runId&&<RunViewStatus run={run} freshness={executionFreshness} requested={terminationRequest===runId} mode={perspective==='agent'?'observation':mode} cursor={perspective==='agent'?(observation?{time:String(observation.time),revision:String(observation.revision)}:undefined):(view?{time:String(view.time),revision:String(view.revision)}:undefined)} waiting={viewerLoad.phase!=='ready'&&perspective!=='agent'} onLive={returnToLive}/>}
  {!runId?<section className="run-chooser panel" data-testid="run-chooser">
    <span className="eyebrow">YOUR SIMULATION WORKSPACE</span><h2>Choose a run or create an experiment.</h2>
    <p>Open a run from the sidebar or choose one below. History loads only when you select a run.</p>
    {notice&&<p className="chooser-notice" role="status">{notice}</p>}
    {runListState.phase==='loading'&&<p role="status">Loading run summaries…</p>}
    {runListState.phase==='failed'&&<div className="chooser-error"><p role="alert">Could not load run summaries. {runListState.error}</p><button data-testid="run-list-retry" onClick={()=>{setRunListState({phase:'loading'});refreshRuns();}}>Retry run list</button></div>}
    {runListState.phase==='ready'&&!runs.length&&<p>No runs yet. Create an experiment to get started.</p>}
    {runs.length>0&&<><p className="chooser-summary">{runs.length} recorded run{runs.length===1?'':'s'} · {runs.filter(row=>!isInactiveRun(row)).length} active or paused</p><div className="chooser-runs">{runs.slice(0,12).map(row=><button key={row.id} data-testid="chooser-select-run" onClick={()=>selectRun(row.id)}><strong>{row.config.scenario||'Untitled scenario'}</strong><span>{confirmedStatusLabel(row,statusFreshness(row,runListState.phase,statusNow))}{row.frontier?.time!=null&&row.frontier?.revision!=null&&<> · {fixed(row.frontier.time)} s · revision {row.frontier.revision}</>}</span><small>{row.id}</small></button>)}</div>{runs.length>12&&<p>All {runs.length} runs are available in the sidebar.</p>}</>}
    <button className="primary" onClick={()=>{setConfigSource(undefined);setConfigOpen(true);}}>Create an experiment ↗</button>
  </section>:<>
  {perspective!=='agent'&&<ViewerLoadPanel state={viewerLoad} run={run} hasView={Boolean(view)} onCancel={returnToRuns} onRetry={retryView} onReturn={returnToRuns}/>}
  {(view||perspective==='agent')&&<>
  <section className="cursor-bar"><span className={`mode-badge ${mode}`}>{perspective==='agent'?'◷ RECORDED OBSERVATION':mode==='live'?'● LIVE FOLLOW':'◷ RECORDED REPLAY'}</span><label>Perspective<select data-testid="perspective" value={perspective} onChange={e=>selectPerspective(e.target.value)}><option value="researcher">Researcher · global state</option><option value="agent">Recorded agent observation</option></select></label></section>
  {perspective==='agent'?<section className="observation-panel panel"><h2>Recorded agent observation</h2><p>Only the selected decision’s recorded input is displayed. Global map, metrics, inspector, and event overlays are hidden.</p>{observation?<><p>Decision {observation.decision} · {observation.time} s · revision {observation.revision}</p><pre>{JSON.stringify(observation.observation,null,2)}</pre></>:<p>No observation loaded. Select an agent in researcher view and choose this perspective again.</p>}</section>:view&&<>
  <section className="metric-cards" aria-label="Population at the displayed revision">{Object.keys(colors).map(key=><div className="metric-card" data-status-token={{healthy:'HEALTHY',infected:'INFECTED',zombies:'ACTIVE',dead:'DEAD'}[key]} key={key}><span className="metric-symbol" style={{color:colors[key]}}>{key==='zombies'?'▲':key==='dead'?'×':key==='infected'?'◉':'●'}</span><div><span>{key==='healthy'?'Healthy humans':key==='infected'?'Infected humans':key==='zombies'?'Living zombies':'Dead identities'}</span><strong>{view.metrics.populations[key]}</strong></div></div>)}</section>
  <div className="workspace"><section className="main-panel panel"><nav className="tabs" aria-label="Workspace views">{['world','statistics','cohorts','events','comparison'].map(t=><button data-testid={`tab-${t}`} key={t} className={tab===t?'active':''} onClick={()=>setTab(t)}>{t[0].toUpperCase()+t.slice(1)}</button>)}<span className="panel-caption">{view.metrics.populations.total} identities · {view.state.world.length} × {view.state.world.width} m</span></nav>
  {tab==='world'&&<><div className="world-toolbar"><div className="legend"><span data-status-token="HEALTHY" style={{color:colors.healthy}}>● Human</span><span data-status-token="INFECTED" style={{color:colors.infected}}>◉ INFECTED</span><span data-status-token="ACTIVE" style={{color:colors.zombies}}>▲ Zombie</span><span data-status-token="DEAD" style={{color:colors.dead}}>× Dead</span></div><details className="layers"><summary>Layers</summary>{Object.keys(layers).map(key=><label className="check" key={key}><input data-testid={`layer-${key==='agents'?'global-agents':key}`} type="checkbox" checked={layers[key]} onChange={e=>setLayers(l=>({...l,[key]:e.target.checked}))}/>{key}</label>)}</details></div><World state={view.state} selected={selected} onSelect={setSelected} follow={follow} layers={layers}/><div className="agent-search"><label>Find an agent<input data-testid="agent-search" placeholder="ID, role, type or status…" value={filter} onChange={e=>setFilter(e.target.value)}/></label><label className="check"><input data-testid="agent-follow" type="checkbox" checked={follow} disabled={!selected} onChange={e=>setFollow(e.target.checked)}/>Follow selected identity</label><span>{visibleAgents.length} matching</span></div><div className="table-scroll"><table><caption className="sr-only">Searchable agents at revision {view.revision}</caption><thead><tr><th>Identity</th><th>Type / role</th><th>Status</th><th>Life</th><th>Stamina</th><th>Action</th></tr></thead><tbody>{visibleAgents.slice(0,100).map(a=><tr key={a.id} className={String(a.id)===selected?'selected':''}><td><button data-testid="agent-search-select" className="link" onClick={()=>setSelected(String(a.id))}>#{a.id}</button></td><td>{a.type}{a.role&&` · ${a.role}`}</td><td>{a.status||agentStatus(a)}</td><td>{a.life}</td><td>{fixed(a.stamina)}</td><td>{a.active_action||'idle'}</td></tr>)}</tbody></table></div>{visibleAgents.length>100&&<p className="subtle">Showing the first 100 matches. Narrow the search to inspect any identity.</p>}</>}
  <div hidden={tab!=='statistics'}><StatisticsPanel read={metricsState} selected={{run_id:runId,time:String(view.time),revision:String(view.revision)}} mode={mode} visible={tab==='statistics'} waitingForView={viewerLoad.phase!=='ready'} onRetry={statistics.retry} onSeek={replay} colors={colors} onChartState={state=>{if(perspectiveRef.current==='researcher'&&state.run_id===runIdRef.current)inspection.statistics_chart=state;}}/></div>
  <div hidden={tab!=='comparison'}><ComparisonPanel runs={runs} chosen={comparisonChosen} onChoose={setComparisonChosen} metric={comparisonMetric} onMetric={setComparisonMetric} read={comparison.read} context={comparison.context} requestedSources={comparison.requested_sources} stale={comparison.stale} unavailable={comparison.unavailable} visible={tab==='comparison'} onRetry={comparison.retry} onExport={download} onChartState={state=>{if(perspectiveRef.current==='researcher'&&state.context===comparisonContextRef.current)inspection.comparison_chart=state;}}/></div>
  <div hidden={tab!=='cohorts'}><CohortPanel key={runId} read={cohortsState} selected={{run_id:runId,time:String(view.time),revision:String(view.revision)}} waitingForView={viewerLoad.phase!=='ready'} onRetry={cohortReader.retry} onCreate={(definition,signal)=>api(`/runs/${runId}/cohorts`,definition,signal)} onExport={(cohort,cursor)=>download(`cohort-${cohort.definition.id}.json`,JSON.stringify({...cohort,...cursor},null,2))} colors={colors}/></div>
  {tab==='events'&&<EventsPanel read={eventsState} selected={{run_id:runId,time:String(view.time),revision:String(view.revision)}} mode={mode} following={eventReader.following} queryKey={eventReader.queryKey} waitingForView={viewerLoad.phase!=='ready'} agent={selected} search={eventFilter} onSearch={setEventFilter} onClearAgent={()=>setSelected('')} onRetry={eventReader.retry} onLatest={eventReader.latest} onOlder={eventReader.older} onNewer={eventReader.newer} onSelect={(event,cursor)=>{setEventDetail(event);setEventDetailSource({...cursor});replay(String(event.time??0),String(event.revision_after));}}/>}
  </section><aside className="inspector panel"><header><span className="eyebrow">IDENTITY INSPECTOR</span>{selected&&<button aria-label="Clear agent selection" onClick={()=>setSelected('')}>✕</button>}</header>{agent?<><div className="identity-heading"><span className="identity-icon" style={{color:colors[agentStatus(agent)]}}>{agent.type==='Zombie'?'▲':'●'}</span><div><h2>Agent #{agent.id}</h2><p>{agent.type} · {agent.role||'No active role'}</p></div></div><span data-status-token={agent.status||agentStatus(agent)} className="tag">{agent.status||agentStatus(agent)}</span>{['life','stamina','hunger'].filter(k=>agent[k]!==undefined).map(k=><div className="gauge" key={k}><div><span>{k}</span><strong>{fixed(agent[k])} / 100</strong></div><meter min={0} max={100} value={agent[k]} aria-label={k}/></div>)}<dl><dt>Position</dt><dd>{fixed(agent.x)}, {fixed(agent.y)} m</dd><dt>Model</dt><dd>{typeof agent.model_assignment==='object'?JSON.stringify(agent.model_assignment):agent.model_assignment||'Default utility'}</dd><dt>Action</dt><dd>{agent.active_action||'Idle'}</dd><dt>Inventory</dt><dd>{JSON.stringify(agent.inventory||{})}</dd><dt>Reserved subset</dt><dd>{JSON.stringify(agent.reserved||{})}</dd></dl>{agent.infection_episode&&<section className="infection-card"><h3>Active infection episode</h3><pre>{JSON.stringify(view.state.episodes?.[agent.infection_episode]||agent.infection_episode,null,2)}</pre></section>}<button onClick={()=>{setTab('events');setEventFilter('');}}>Inspect identity history ↗</button><details open><summary>Attributes, effects & cooldowns</summary><pre>{JSON.stringify(agent,null,2)}</pre></details></>:<div className="empty"><span className="empty-icon">⌖</span><h3>Follow an identity</h3><p>Select an agent on the map or use the searchable table. Identity persists through conversion and death.</p></div>}{eventDetail&&<section className="event-detail"><h3>Selected event</h3><p data-testid="event-detail-source">Loaded from {eventDetailSource?.time} s · revision {eventDetailSource?.revision}. Event sequence {eventDetail.ledger_sequence}.</p><button data-testid="event-before" onClick={()=>replay(String(eventDetail.time??0),String(eventDetail.revision_before))}>Before recorded transition</button><button data-testid="event-after" onClick={()=>replay(String(eventDetail.time??0),String(eventDetail.revision_after))}>After recorded transition</button><pre>{JSON.stringify(eventDetail,null,2)}</pre></section>}</aside></div></>}
  {view&&<><section className="replay-bar" aria-label="Viewer playback controls"><div><span className="control-label">VIEWER</span><button data-testid="replay-pause" disabled={mode==='live'} onClick={()=>setPlaying(v=>!v)}>{playing?'Ⅱ':'▶'} Replay</button><select data-testid="view-pacing" aria-label="Replay speed" value={replaySpeed} onChange={e=>setReplaySpeed(Number(e.target.value))}><option value={.25}>0.25×</option><option value={1}>1×</option><option value={4}>4×</option><option value={16}>16×</option></select></div><label className="scrubber"><span>Scrub to inspect recorded history. Use execution controls to pause or stop the simulation.</span><input aria-label="Replay time" type="range" min={0} max={Math.max(.01,frontier)} step="any" value={Math.min(frontier,seconds(seek))} onChange={e=>replay(e.target.value)}/></label><label className="exact-time">Exact time<input data-testid="replay-exact-time" value={seek} onChange={e=>setSeek(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')replay(seek);}}/></label><button data-testid="replay-seek" onClick={()=>replay(seek)}>Inspect recorded time</button><ExportDialog runId={runId} time={view.time} revision={view.revision}/></section><footer className="status-footer"><span>Run {runId.slice(0,12)} · displayed r{view.revision} · frontier when view was read r{view.committed_frontier}</span><span>Researcher views never feed information to agent policies.</span></footer></>}</>}</>}
  </main>{interventionOpen&&view&&run&&<InterventionDialog view={view} run={run} onClose={()=>setInterventionOpen(false)} onCommand={command} onBranch={async seed=>{try{const result=await api(`/runs/${runId}/branch`,{command_id:id(),revision:view.revision,generation:run.generation,seed});selectRun(result.run_id);refreshRuns();}catch(e:any){setError(e.message);throw e;}}}/>}{configOpen&&<Configuration source={configSource} onClose={()=>setConfigOpen(false)} onCreated={(identity,generation)=>{if(generation!==undefined)controlGenerations.current[identity]=generation;selectRun(identity);refreshRuns();}} onStartState={(identity,pending,generation,uncertain)=>{if(uncertain)uncertainStarts.current.add(identity);else uncertainStarts.current.delete(identity);setStartingRuns(rows=>({...rows,[identity]:pending}));if(generation!==undefined)controlGenerations.current[identity]=generation;refreshRuns();}} onError={setError}/>}</div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
