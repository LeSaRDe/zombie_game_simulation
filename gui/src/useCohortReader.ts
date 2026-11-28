import {CohortReader} from './core/AnalysisReaders';
import {useEffect, useRef, useState} from 'react';
import {MetricCursor, sameCursor} from './useStatisticsReader';

type Obj=Record<string,any>;
export type CohortData={run_id:string;cursor:{time:string;revision:string};cohorts:Obj[]};
export type CohortRead={phase:'idle'|'loading'|'refreshing'|'ready'|'failed';cursor?:MetricCursor;data?:CohortData;error?:string};
const map=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const count=(value:any)=>Number.isInteger(value)&&value>=0;

/** Cohorts read the selected committed cursor independently of other panels. */
export default function useCohortReader({runId,mode,perspective,selectionVersion,getCursor,fetchCohorts}:{
  runId:string;mode:string;perspective:string;selectionVersion:number;
  getCursor:()=>MetricCursor|undefined;
  fetchCohorts:(cursor:MetricCursor,signal:AbortSignal)=>Promise<CohortData>;
}) {
  const [read,setRead]=useState<CohortRead>({phase:'idle'});
  const [attempt,setAttempt]=useState(0);
  const latest=useRef({getCursor,fetchCohorts});latest.current={getCursor,fetchCohorts};
  const context=`${runId}:${mode}:${perspective}:${selectionVersion}`;
  const contextRef=useRef(context);contextRef.current=context;
  useEffect(()=>{
    if(!runId||perspective!=='researcher'){setRead({phase:'idle'});return;}
    setRead(previous=>previous.cursor?.run_id===runId
      ? {...previous,phase:previous.data?'refreshing':'loading',error:undefined}
      : {phase:'loading'});
    const reader=new CohortReader({current:()=>contextRef.current===context,read:async(signal)=>{
      const requested=latest.current.getCursor();
      if(!requested||requested.run_id!==runId)return;
      const key=`${requested.time}:${requested.revision}`;
      if(!reader.accepts(key))return;
      setRead(previous=>({...previous,phase:previous.data?'refreshing':'loading',error:undefined}));
      try{
        const data=await latest.current.fetchCohorts(requested,signal);
        if(!reader.current)return;
        const cursor=reader.validate(data,requested);
        const selected=latest.current.getCursor();
        if(!selected||selected.run_id!==runId)return;
        if(mode==='replay'&&!sameCursor(cursor,selected))return;
        setRead({phase:'ready',cursor,data});reader.succeeded(key);
      }catch(error:any){
        if(!reader.current)return;
        reader.failed(key);setRead(previous=>({...previous,phase:'failed',error:error.message||'Cohorts could not be loaded.'}));
      }
    }});
    reader.start();return()=>reader.dispose();
  },[context,attempt]);
  return {read,retry:()=>setAttempt(value=>value+1)};
}
