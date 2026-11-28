import {useEffect, useRef, useState} from 'react';

type Obj=Record<string,any>;
export type ComparisonSource={run_id:string;time:string;revision:string};
export type ComparisonMetadata=Record<string,{scenario:string;seed:string}>;
export type ComparisonData={status:'ready'|'no_overlap';sources:ComparisonSource[];origins:{run_id:string;time:string}[];
  common_interval:{start:string;end:string};sample_interval:string;sample_times:string[];sample_limit:number;
  definition:string;version:string;runs:{run_id:string;origin:string;requested_cursor:{time:string;revision:string};cursor:{time:string;revision:string};samples:Obj[]}[]};
export type ComparisonRead={phase:'idle'|'loading'|'refreshing'|'ready'|'failed';context?:string;data?:ComparisonData;
  metadata?:ComparisonMetadata;source_key?:string;error?:string;failures?:{run_id:string;message:string}[]};

export {comparisonTime,compareComparisonTime,comparisonSeconds,comparisonSourceKey} from './core/AnalysisReaders';
import {ComparisonReader,compareComparisonTime,comparisonSourceKey} from './core/AnalysisReaders';
const integer=(value:any)=>typeof value==='string'&&/^\d+$/.test(value);

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
    const reader=new ComparisonReader({current:()=>contextRef.current===context,read:async(signal)=>{
      if(performance.now()-lastStarted.current<500)return;
      const request=latest.current,key=request.sourceKey;
      if(!reader.accepts(key))return;
      lastStarted.current=performance.now();
      setRead(previous=>previous.context===context?{...previous,phase:previous.data?'refreshing':'loading',error:undefined,failures:undefined}:{phase:'loading',context});
      try{
        const result=await request.fetchComparison(request.sources,signal);
        if(!reader.current)return;
        const data=reader.validate(result,request.sources);
        setRead({phase:'ready',context,data,metadata:request.metadata,source_key:key});reader.succeeded(key);
      }catch(error:any){
        if(!reader.current)return;
        reader.failed(key);setRead(previous=>({...previous,context,phase:'failed',error:error.message||'The comparison could not be loaded.',failures:error.failures}));
      }
    }});
    reader.seed(attempt?'':currentRead.current.context===context?currentRead.current.source_key||'':'');
    reader.start();return()=>reader.dispose();
  },[context,enabled,attempt]);
  return {read:visibleRead,context,requested_sources:sources,requested_key:sourceKey,unavailable,
    stale:Boolean(visibleRead.data&&visibleRead.source_key!==sourceKey),retry:()=>setAttempt(value=>value+1)};
}
