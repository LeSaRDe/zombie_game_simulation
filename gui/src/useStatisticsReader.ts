import {StatisticsReader} from './core/AnalysisReaders';
import {useEffect, useRef, useState} from 'react';

export type MetricCursor = {run_id:string; time:string; revision:string};
export type MetricData = {samples:Record<string,any>[]; event_counts:Record<string,number>; [key:string]:any};
export type MetricRead = {phase:'idle'|'loading'|'refreshing'|'ready'|'failed'; cursor?:MetricCursor; data?:MetricData; error?:string};

export {sameTime,sameMetricCursor as sameCursor} from './core/AnalysisReaders';
import {sameMetricCursor as sameCursor} from './core/AnalysisReaders';

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
    setRead(previous=>previous.cursor?.run_id===runId
      ? {...previous,phase:previous.data?'refreshing':'loading',error:undefined}
      : {phase:'loading'});
    const reader=new StatisticsReader({current:()=>contextRef.current===context,read:async(signal)=>{
      const requested=latest.current.getCursor();
      if(!requested||requested.run_id!==runId)return;
      const key=`${requested.time}:${requested.revision}`;
      if(!reader.accepts(key))return;
      setRead(previous=>({...previous,phase:previous.data?'refreshing':'loading',error:undefined}));
      try{
        const data=await latest.current.fetchMetrics(requested,signal);
        if(!reader.current)return;
        const cursor=reader.validate(data,requested);
        // Replay requests are tied to the selected cursor. Live requests may
        // finish behind the advancing view, and are explicitly labelled stale.
        const selected=latest.current.getCursor();
        if(!selected||selected.run_id!==runId)return;
        if(mode==='replay'&&!sameCursor(cursor,selected))return;
        setRead({phase:'ready',cursor,data});reader.succeeded(key);
      }catch(error:any){
        if(!reader.current)return;
        reader.failed(key);setRead(previous=>({...previous,phase:'failed',error:error.message||'Statistics could not be loaded.'}));
      }
    }});
    reader.start();return()=>reader.dispose();
  },[context,attempt]);
  return {read,retry:()=>setAttempt(value=>value+1)};
}
