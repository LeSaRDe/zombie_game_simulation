import {useEffect, useRef, useState} from 'react';

export type MetricCursor = {run_id:string; time:string; revision:string};
export type MetricData = {samples:Record<string,any>[]; event_counts:Record<string,number>; [key:string]:any};
export type MetricRead = {phase:'idle'|'loading'|'refreshing'|'ready'|'failed'; cursor?:MetricCursor; data?:MetricData; error?:string};

function timeParts(value:string):[bigint,bigint] {
  const fraction=/^(-?\d+)\/(\d+)$/.exec(value);
  if(fraction&&BigInt(fraction[2])!==0n)return [BigInt(fraction[1]),BigInt(fraction[2])];
  const decimal=/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if(!decimal)throw Error('Invalid metric time.');
  const exponent=Number(decimal[4]||0)-(decimal[3]||'').length;
  if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000)throw Error('Invalid metric time.');
  const numerator=BigInt((decimal[1]==='-'?'-':'')+decimal[2]+(decimal[3]||''));
  return exponent>=0?[numerator*10n**BigInt(exponent),1n]:[numerator,10n**BigInt(-exponent)];
}
export function sameTime(left:string,right:string):boolean {
  if(left===right)return true;
  try{const [a,b]=timeParts(left),[c,d]=timeParts(right);return a*d===c*b;}catch{return false;}
}
function compareTime(left:string,right:string):bigint {
  const [a,b]=timeParts(left),[c,d]=timeParts(right);return a*d-c*b;
}
const plainMap=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
export function sameCursor(left?:MetricCursor,right?:MetricCursor):boolean {
  return Boolean(left&&right&&left.run_id===right.run_id&&left.revision===right.revision&&sameTime(left.time,right.time));
}

/** Coalesce live reads without cancelling every request when the frontier moves. */
export default function useStatisticsReader({runId,mode,perspective,selectionVersion,getCursor,fetchMetrics}:{
  runId:string;mode:string;perspective:string;selectionVersion:number;
  getCursor:()=>MetricCursor|undefined;
  fetchMetrics:(cursor:MetricCursor,signal:AbortSignal)=>Promise<MetricData>;
}) {
  const [read,setRead]=useState<MetricRead>({phase:'idle'});
  const [attempt,setAttempt]=useState(0);
  const latest=useRef({getCursor,fetchMetrics});latest.current={getCursor,fetchMetrics};
  const context=`${runId}:${mode}:${perspective}:${selectionVersion}`;
  const contextRef=useRef(context);contextRef.current=context;
  useEffect(()=>{
    if(!runId||perspective!=='researcher'){setRead({phase:'idle'});return;}
    let disposed=false,inflight=false,last='',failed='';
    const controller=new AbortController();
    setRead(previous=>previous.cursor?.run_id===runId
      ? {...previous,phase:previous.data?'refreshing':'loading',error:undefined}
      : {phase:'loading'});
    const update=async()=>{
      if(disposed||inflight||contextRef.current!==context)return;
      const requested=latest.current.getCursor();
      if(!requested||requested.run_id!==runId)return;
      const key=`${requested.time}:${requested.revision}`;
      if(key===last||key===failed)return;
      inflight=true;
      setRead(previous=>({...previous,phase:previous.data?'refreshing':'loading',error:undefined}));
      try{
        const data=await latest.current.fetchMetrics(requested,controller.signal);
        if(disposed||contextRef.current!==context)return;
        const cursor={run_id:runId,time:String(data.cursor?.time??data.time),revision:String(data.cursor?.revision??data.revision)};
        if(!sameCursor(cursor,requested))throw Error('Statistics returned a different source time or revision. Retry to load the selected cursor.');
        if(!Array.isArray(data.samples)||!plainMap(data.event_counts))throw Error('The service returned incomplete statistics.');
        let previousTime='0';
        for(const sample of data.samples){
          if(!plainMap(sample)||sample.time===undefined||!/^\d+$/.test(String(sample.revision))||!Number.isFinite(sample.seconds)||sample.seconds<0
            ||['healthy','infected','zombies','dead'].some(key=>!Number.isInteger(sample[key])||sample[key]<0)
            ||sample.healthy+sample.infected+sample.zombies+sample.dead!==sample.total
            ||compareTime(String(sample.time),previousTime)<0||compareTime(String(sample.time),cursor.time)>0
            ||BigInt(sample.revision)>BigInt(cursor.revision)
            ||!plainMap(sample.resources?.available_and_reserved)||!plainMap(sample.resources?.reserved_subset))throw Error('The service returned an invalid population or resource sample.');
          previousTime=String(sample.time);
        }
        const endpoint=data.samples.at(-1);
        if(endpoint&&!sameCursor({run_id:runId,time:String(endpoint.time),revision:String(endpoint.revision)},cursor))throw Error('Statistics are missing the selected frontier sample. Retry to load the complete cursor.');
        // Replay requests are tied to the selected cursor. Live requests may
        // finish behind the advancing view, and are explicitly labelled stale.
        const selected=latest.current.getCursor();
        if(!selected||selected.run_id!==runId)return;
        if(mode==='replay'&&!sameCursor(cursor,selected))return;
        setRead({phase:'ready',cursor,data});last=key;failed='';
      }catch(error:any){
        if(disposed||controller.signal.aborted||contextRef.current!==context)return;
        failed=key;setRead(previous=>({...previous,phase:'failed',error:error.message||'Statistics could not be loaded.'}));
      }finally{inflight=false;}
    };
    void update();const timer=setInterval(()=>void update(),500);
    return()=>{disposed=true;controller.abort();clearInterval(timer);};
  },[context,attempt]);
  return {read,retry:()=>setAttempt(value=>value+1)};
}
