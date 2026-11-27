import {TimeValue, ExactTimeInput} from './TimeValue';
import React,{useEffect,useRef,useState} from 'react';
type Obj=Record<string,any>;
type Saved={path:string;body:Obj;operation:string};
const key='zombie.pending-command';
let inspection:Obj={};
Object.defineProperty(window,'__zombieCommandInspection',{configurable:true,get:()=>structuredClone(inspection)});
async function request(path:string,body?:Obj){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
 let response:Response,text:string;
 try{response=await fetch('/api'+path,{signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});text=await response.text();}
 catch(e){if(controller.signal.aborted)throw Error('No command response was received within 10 seconds.');throw e;}
 finally{clearTimeout(timer);}
 let result:Obj;
 try{result=text?JSON.parse(text):{};}catch{throw Error(`Request returned ${response.status}: ${text.slice(0,160)}`);}
 if(!response.ok)throw Object.assign(Error(result.error||result.detail||'Request failed'),{code:result.code,status:response.status});
 return result;
}
function readSaved():Saved|null{try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}}
export default function CommandDialog({run,view,onApplied}:{run:Obj;view:Obj;onApplied:(result:Obj,operation:string)=>void}){
 const [open,setOpen]=useState(false),[operation,setOperation]=useState('branch'),[commandId,setCommandId]=useState<string>(crypto.randomUUID()),[time,setTime]=useState(view.time);
 const [change,setChange]=useState(JSON.stringify({kind:'add_resource',resource:'FOOD',quantity:1,x:0,y:0},null,2));
 const [pending,setPending]=useState(false),[saved,setSaved]=useState<Saved|null>(readSaved),[receipt,setReceipt]=useState<Obj|null>(null),[error,setError]=useState('');
 const panel=useRef<HTMLDivElement>(null);
 useEffect(()=>{inspection={pending,receipt,error,saved,operation,command_id:commandId};},[pending,receipt,error,saved,operation,commandId]);
 useEffect(()=>{if(open)panel.current?.querySelector<HTMLSelectElement>('select')?.focus();},[open]);
 async function execute(value:Saved,retry=false){
  setPending(true);setError('');setReceipt(null);setSaved(value);localStorage.setItem(key,JSON.stringify(value));
  try{
   // Re-establish the local session and inspect the retained receipt first.
   // Resending the immutable original request also reconciles a reservation
   // whose process died before construction/start finished.
   if(retry){try{await request('/commands/'+encodeURIComponent(value.body.command_id));}catch(e){if((e as Obj).status!==404)throw e;}}
   let result:Obj=await request(value.path,value.body);
   while(result.status==='pending'){await new Promise(resolve=>setTimeout(resolve,150));result=await request('/commands/'+encodeURIComponent(value.body.command_id));}
   setReceipt(result);
   if(result.status==='rejected')setError(result.error||'Command rejected');
   else if(value.operation==='start'){
    let started=await request('/commands/'+encodeURIComponent(value.body.command_id+':start'));
    while(started.status==='pending'){await new Promise(resolve=>setTimeout(resolve,150));started=await request('/commands/'+encodeURIComponent(value.body.command_id+':start'));}
    if(started.status==='rejected')setError(started.error||'The run could not start');
    else onApplied({...result,generation:started.generation},value.operation);
   }else onApplied(result,value.operation);
   localStorage.removeItem(key);setSaved(null);setCommandId(crypto.randomUUID());
  }catch(e){setError((e as Error).message+' Retry checks the original command receipt before sending it again.');}
  finally{setPending(false);}
 }
 function submit(){
  try{
   const body:Obj={command_id:commandId,generation:run.generation};let path='/runs/'+run.id+'/commands';
   if(operation==='start'){path='/runs';body.config=run.config;body.start=true;}
   else if(operation==='branch'){path='/runs/'+run.id+'/branch';body.revision=view.revision;body.seed=run.config.seed;}
   else if(operation==='intervention'){body.operation='intervene';body.change=JSON.parse(change);body.time=time;body.apply_now=time===view.time;}
   else body.operation='stop';
   execute({path,body,operation});
  }catch(e){setError((e as Error).message);}
 }
 return <><button data-testid="command-open" disabled={pending} onClick={()=>{if(!saved)setTime(view.time);setOpen(v=>!v);}}>Run commands</button>{(open||saved)&&<div className="modal-backdrop"><div ref={panel} className="config-modal intervention-modal" role="dialog" aria-modal="true" aria-labelledby="command-title"><header><h2 id="command-title">Run commands</h2><button aria-label="Close run commands" onClick={()=>{setOpen(false);if(saved)setSaved(null);}}>✕</button></header><section className="intervention-body"><label>Operation<select data-testid="command-operation" value={operation} disabled={pending||!!saved} onChange={e=>setOperation(e.target.value)}><option value="start">Start a new run with this configuration</option><option value="branch">Branch from displayed revision</option><option value="intervention" disabled={!run.config.interventions_enabled}>Intervene in this run</option><option value="stop">Stop and save this run</option></select></label><p>Current run {run.id.slice(0,12)} · revision {view.revision} · time <TimeValue value={view.time}/></p>{operation==='intervention'&&<><ExactTimeInput label="Effective simulation time" data-testid="command-time" value={time} onChange={e=>setTime(e.target.value)} disabled={pending||!!saved}/><label>Change specification<textarea data-testid="command-change" rows={9} value={change} onChange={e=>setChange(e.target.value)} disabled={pending||!!saved}/></label><p>A change at the current time is applied before acknowledgement. Future changes are scheduled in the causal timeline.</p></>}<details><summary>Command reference</summary><label>Reference<input data-testid="command-id" value={commandId} onChange={e=>setCommandId(e.target.value)} disabled={pending||!!saved}/></label><small>The same reference is retained if the connection is lost.</small></details>{error&&<p role="alert">{error}</p>}{receipt&&<p role="status">{receipt.status} · revision {receipt.revision} · time <TimeValue value={receipt.time}/></p>}</section><footer><button onClick={()=>setOpen(false)} disabled={pending||!!saved}>Close</button>{saved?<button data-testid="command-retry" className="primary" disabled={pending} onClick={()=>execute(saved,true)}>{pending?'Checking…':'Retry original command'}</button>:<button data-testid="command-submit" className="primary" disabled={pending||!commandId} onClick={submit}>{pending?'Applying…':'Apply command'}</button>}</footer></div></div>}</>;
}
