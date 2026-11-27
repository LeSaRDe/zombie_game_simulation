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
        const data=await latest.current.fetchCohorts(requested,controller.signal);
        if(disposed||contextRef.current!==context)return;
        const cursor={run_id:data.run_id,time:String(data.cursor?.time),revision:String(data.cursor?.revision)};
        if(!sameCursor(cursor,requested))throw Error('Cohorts returned a different source time, revision or run. Retry to load the selected cursor.');
        if(!Array.isArray(data.cohorts))throw Error('The service returned an incomplete cohort collection.');
        const ids=new Set<string>();
        for(const cohort of data.cohorts){
          const definition=cohort?.definition;
          if(!map(cohort)||!map(definition)||typeof definition.id!=='string'||ids.has(definition.id)
            ||!['fixed','dynamic'].includes(definition.mode)||(definition.name!==undefined&&typeof definition.name!=='string')
            ||definition.reference_time===undefined||!/^\d+$/.test(String(definition.reference_revision))
            ||(definition.predicate!==undefined&&!map(definition.predicate))||!Array.isArray(cohort.members)||cohort.members.some((identity:any)=>typeof identity!=='string')
            ||new Set(cohort.members).size!==cohort.members.length||cohort.denominator!==cohort.members.length
            ||!count(cohort.present)||cohort.present>cohort.denominator||!map(cohort.populations)
            ||['healthy','infected','zombies','dead'].some(key=>!count(cohort.populations[key]))
            ||['healthy','infected','zombies','dead'].reduce((sum,key)=>sum+cohort.populations[key],0)!==cohort.present
            ||cohort.populations.total!==cohort.present)throw Error('The service returned an invalid cohort definition or membership summary.');
          for(const metric of ['life','stamina']){
            const denominator=cohort[`mean_${metric}_denominator`],mean=cohort[`mean_${metric}`];
            if(!count(denominator)||denominator!==cohort.present||(denominator===0?mean!==null:!Number.isFinite(mean)))throw Error('The service returned an invalid cohort average or denominator.');
          }
          ids.add(definition.id);
        }
        const selected=latest.current.getCursor();
        if(!selected||selected.run_id!==runId)return;
        if(mode==='replay'&&!sameCursor(cursor,selected))return;
        setRead({phase:'ready',cursor,data});last=key;failed='';
      }catch(error:any){
        if(disposed||controller.signal.aborted||contextRef.current!==context)return;
        failed=key;setRead(previous=>({...previous,phase:'failed',error:error.message||'Cohorts could not be loaded.'}));
      }finally{inflight=false;}
    };
    void update();const timer=setInterval(()=>void update(),500);
    return()=>{disposed=true;controller.abort();clearInterval(timer);};
  },[context,attempt]);
  return {read,retry:()=>setAttempt(value=>value+1)};
}
