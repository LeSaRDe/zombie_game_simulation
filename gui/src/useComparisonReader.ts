import {useEffect, useRef, useState} from 'react';

type Obj=Record<string,any>;
export type ComparisonSource={run_id:string;time:string;revision:string};
export type ComparisonMetadata=Record<string,{scenario:string;seed:string}>;
export type ComparisonData={status:'ready'|'no_overlap';sources:ComparisonSource[];origins:{run_id:string;time:string}[];
  common_interval:{start:string;end:string};sample_interval:string;sample_times:string[];sample_limit:number;
  definition:string;version:string;runs:{run_id:string;origin:string;requested_cursor:{time:string;revision:string};cursor:{time:string;revision:string};samples:Obj[]}[]};
export type ComparisonRead={phase:'idle'|'loading'|'refreshing'|'ready'|'failed';context?:string;data?:ComparisonData;
  metadata?:ComparisonMetadata;source_key?:string;error?:string;failures?:{run_id:string;message:string}[]};

export function comparisonTime(value:string):[bigint,bigint] {
  if(typeof value!=='string')throw Error('Comparison times must be exact strings.');
  const fraction=/^(-?\d+)\/(\d+)$/.exec(value);
  if(fraction&&BigInt(fraction[2])>0n)return [BigInt(fraction[1]),BigInt(fraction[2])];
  const decimal=/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if(!decimal)throw Error('Invalid comparison time.');
  const exponent=Number(decimal[4]||0)-(decimal[3]||'').length;
  if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000)throw Error('Invalid comparison time.');
  const numerator=BigInt((decimal[1]==='-'?'-':'')+decimal[2]+(decimal[3]||''));
  return exponent>=0?[numerator*10n**BigInt(exponent),1n]:[numerator,10n**BigInt(-exponent)];
}
export function compareComparisonTime(left:string,right:string):bigint {
  const [a,b]=comparisonTime(left),[c,d]=comparisonTime(right);return a*d-c*b;
}
export function comparisonSeconds(value:string):number {
  let [a,b]=comparisonTime(value);let x=a<0n?-a:a,y=b;
  while(y){const remainder=x%y;x=y;y=remainder;}if(x){a/=x;b/=x;}
  return Number(a)/Number(b);
}
const exactEqual=(left:string,right:string)=>compareComparisonTime(left,right)===0n;
const integer=(value:any)=>typeof value==='string'&&/^\d+$/.test(value);
const object=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
export const comparisonSourceKey=(sources:ComparisonSource[])=>JSON.stringify(sources);
const sameSource=(a:ComparisonSource,b:ComparisonSource)=>a?.run_id===b.run_id&&a.revision===b.revision&&exactEqual(a.time,b.time);

function validate(data:Obj,requested:ComparisonSource[]):ComparisonData {
  if(!object(data)||!Array.isArray(data.sources)||data.sources.length!==requested.length
    ||data.sources.some((source:ComparisonSource,index:number)=>!sameSource(source,requested[index])))throw Error('Comparison returned a different selection or source cursor. Retry to load the requested histories.');
  if(data.status==='failed'){
    if(!Array.isArray(data.errors)||!data.errors.length||data.errors.some((error:Obj)=>!requested.some(source=>source.run_id===error.run_id)||typeof error.message!=='string'))throw Error('The service returned an incomplete comparison failure.');
    throw Object.assign(Error(data.errors.map((error:Obj)=>`Run ${error.run_id}: ${error.message}`).join(' ')),{failures:data.errors});
  }
  if(!['ready','no_overlap'].includes(data.status)||!object(data.common_interval)||!Array.isArray(data.origins)
    ||data.origins.length!==requested.length||!Array.isArray(data.sample_times)||!Array.isArray(data.runs)
    ||data.sample_limit!==2000||typeof data.definition!=='string'||typeof data.version!=='string'
    ||compareComparisonTime(data.sample_interval,'1')<0n)throw Error('The service returned an incomplete comparison.');
  let start='0',end=requested[0].time;
  for(let index=0;index<requested.length;index++){
    const origin=data.origins[index],source=requested[index];
    if(!origin||origin.run_id!==source.run_id||compareComparisonTime(origin.time,'0')<0n||compareComparisonTime(origin.time,source.time)>0n)throw Error('Comparison returned an invalid history origin.');
    if(compareComparisonTime(origin.time,start)>0n)start=origin.time;
    if(compareComparisonTime(source.time,end)<0n)end=source.time;
  }
  if(!exactEqual(data.common_interval.start,start)||!exactEqual(data.common_interval.end,end))throw Error('Comparison returned a different common interval.');
  if(data.status==='no_overlap'){
    if(compareComparisonTime(start,end)<=0n||data.sample_times.length||data.runs.length)throw Error('The service incorrectly reported no common interval.');
    return data as ComparisonData;
  }
  if(compareComparisonTime(start,end)>0n||data.sample_times.length<1||data.sample_times.length>2000
    ||!exactEqual(data.sample_times[0],start)||!exactEqual(data.sample_times.at(-1),end)||data.runs.length!==requested.length)throw Error('Comparison is missing its shared endpoints or selected runs.');
  const [spacingN,spacingD]=comparisonTime(data.sample_interval);
  for(let index=0;index<data.sample_times.length;index++){
    const time=data.sample_times[index];
    if(compareComparisonTime(time,start)<0n||compareComparisonTime(time,end)>0n)throw Error('Comparison sample lies outside the shared interval.');
    if(index){
      const [a,b]=comparisonTime(time),[c,d]=comparisonTime(data.sample_times[index-1]);
      const delta=a*d-c*b,grid=spacingN*b*d;
      if(delta<=0n||delta*spacingD>grid||(index<data.sample_times.length-1&&delta*spacingD!==grid))throw Error('Comparison sample times are not a common ordered grid.');
    }
  }
  for(let index=0;index<requested.length;index++){
    const run=data.runs[index],source=requested[index];
    if(!object(run)||run.run_id!==source.run_id||!sameSource({run_id:run.run_id,...run.requested_cursor},source)
      ||!exactEqual(run.origin,data.origins[index].time)||!object(run.cursor)||!integer(run.cursor.revision)
      ||!exactEqual(run.cursor.time,end)||BigInt(run.cursor.revision)>BigInt(source.revision)
      ||!Array.isArray(run.samples)||run.samples.length!==data.sample_times.length)throw Error('Comparison returned mismatched run sources.');
    let previousRevision=-1n;
    for(let point=0;point<run.samples.length;point++){
      const sample=run.samples[point],time=data.sample_times[point];
      if(!object(sample)||!exactEqual(sample.time,time)||!integer(sample.revision)||!Number.isFinite(sample.seconds)
        ||Math.abs(sample.seconds-comparisonSeconds(time))>Number.EPSILON*Math.max(1,Math.abs(sample.seconds))*4
        ||['healthy','infected','zombies','dead','total'].some(name=>!Number.isSafeInteger(sample[name])||sample[name]<0)
        ||sample.healthy+sample.infected+sample.zombies+sample.dead!==sample.total
        ||BigInt(sample.revision)<previousRevision||BigInt(sample.revision)>BigInt(run.cursor.revision))throw Error(`Run ${source.run_id} returned an invalid population sample.`);
      previousRevision=BigInt(sample.revision);
    }
    if(run.samples.at(-1).revision!==run.cursor.revision)throw Error('Comparison is missing a run endpoint revision.');
  }
  return data as ComparisonData;
}

/** One bounded batch at a time; a moving frontier coalesces into the next read. */
export default function useComparisonReader({currentRun,perspective,visible,chosen,runs,fetchComparison}:{
  currentRun:string;perspective:string;visible:boolean;chosen:string[];runs:Obj[];
  fetchComparison:(sources:ComparisonSource[],signal:AbortSignal)=>Promise<Obj>;
}) {
  const [read,setRead]=useState<ComparisonRead>({phase:'idle'});
  const [attempt,setAttempt]=useState(0);
  const sources:ComparisonSource[]=[];const metadata:ComparisonMetadata={};const unavailable:{run_id:string;message:string}[]=[];
  for(const identity of chosen){
    const run=runs.find(row=>row.id===identity);
    let message=!run?'This run is no longer available.':run.status==='initializing'?'Still initializing; its history is not ready.':'';
    try{if(!message&&(!integer(String(run?.frontier?.revision??''))||compareComparisonTime(String(run?.frontier?.time),'0')<0n))message='No readable committed history is available.';}catch{message='No readable committed history is available.';}
    if(message||!run){unavailable.push({run_id:identity,message:message||'This run is no longer available.'});continue;}
    sources.push({run_id:identity,time:String(run.frontier.time),revision:String(run.frontier.revision)});
    metadata[identity]={scenario:String(run.config?.scenario||'Untitled scenario'),seed:String(run.config?.seed??'')};
  }
  const context=JSON.stringify([currentRun,perspective,chosen]);
  const contextRef=useRef(context);contextRef.current=context;
  const enabled=Boolean(currentRun&&perspective==='researcher'&&visible&&chosen.length>=2&&chosen.length<=4&&!unavailable.length);
  const sourceKey=comparisonSourceKey(sources);
  const latest=useRef({sources,sourceKey,metadata,fetchComparison});latest.current={sources,sourceKey,metadata,fetchComparison};
  const currentRead=useRef(read);currentRead.current=read;
  const lastStarted=useRef(-Infinity);
  const visibleRead:ComparisonRead=perspective==='researcher'&&read.context===context&&!unavailable.length?read:{phase:'idle'};
  useEffect(()=>{
    if(!enabled){
      if(perspective!=='researcher'||chosen.length<2||unavailable.length)setRead({phase:'idle',context});
      return;
    }
    let disposed=false,inflight=false,last=attempt?'':currentRead.current.context===context?currentRead.current.source_key||'':'',failed='';
    const controller=new AbortController();
    const update=async()=>{
      if(disposed||inflight||contextRef.current!==context||performance.now()-lastStarted.current<500)return;
      const request=latest.current,key=request.sourceKey;
      if(key===last||key===failed)return;
      inflight=true;lastStarted.current=performance.now();
      setRead(previous=>previous.context===context?{...previous,phase:previous.data?'refreshing':'loading',error:undefined,failures:undefined}:{phase:'loading',context});
      try{
        const result=await request.fetchComparison(request.sources,controller.signal);
        if(disposed||contextRef.current!==context)return;
        const data=validate(result,request.sources);
        setRead({phase:'ready',context,data,metadata:request.metadata,source_key:key});last=key;failed='';
      }catch(error:any){
        if(disposed||controller.signal.aborted||contextRef.current!==context)return;
        failed=key;setRead(previous=>({...previous,context,phase:'failed',error:error.message||'The comparison could not be loaded.',failures:error.failures}));
      }finally{inflight=false;}
    };
    void update();const timer=setInterval(()=>void update(),500);
    return()=>{disposed=true;controller.abort();clearInterval(timer);};
  },[context,enabled,attempt]);
  return {read:visibleRead,context,requested_sources:sources,requested_key:sourceKey,unavailable,
    stale:Boolean(visibleRead.data&&visibleRead.source_key!==sourceKey),retry:()=>setAttempt(value=>value+1)};
}
