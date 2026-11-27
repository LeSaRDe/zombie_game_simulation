import {useEffect, useRef, useState} from 'react';
import {MetricCursor, sameCursor} from './useStatisticsReader';

type Obj=Record<string,any>;
export type EventRequest={cursor:MetricCursor;agent:string|null;limit:number;before_sequence?:string;after_sequence?:string};
export type EventData={run_id:string;cursor:{time:string;revision:string};agent:string|null;records:Obj[];occurrences:Obj;
  page:{limit:number;loaded_count:number;first_sequence:string|null;last_sequence:string|null;has_older:boolean;has_newer:boolean}};
export type EventRead={phase:'idle'|'loading'|'refreshing'|'ready'|'failed';cursor?:MetricCursor;data?:EventData;request?:EventRequest;queryKey?:string;error?:string};
type PageSelection={context:string;cursor:MetricCursor;before_sequence?:string;after_sequence?:string};
const map=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const integer=(value:any)=>/^\d+$/.test(String(value));

/** Latest reads coalesce; pagination keeps its original causal boundary. */
export default function useEventsReader({runId,mode,perspective,selectionVersion,agent,getCursor,fetchEvents}:{
  runId:string;mode:string;perspective:string;selectionVersion:number;agent:string;
  getCursor:()=>MetricCursor|undefined;
  fetchEvents:(request:EventRequest,signal:AbortSignal)=>Promise<EventData>;
}) {
  const [read,setRead]=useState<EventRead>({phase:'idle'});
  const [attempt,setAttempt]=useState(0);
  const [page,setPage]=useState<PageSelection>();
  const latest=useRef({getCursor,fetchEvents});latest.current={getCursor,fetchEvents};
  const context=JSON.stringify([runId,mode,perspective,selectionVersion,agent]);
  const pinned=page?.context===context?page:undefined;
  const queryKey=JSON.stringify([context,pinned?.cursor,pinned?.before_sequence,pinned?.after_sequence]);
  const queryRef=useRef(queryKey);queryRef.current=queryKey;
  const selectedAgent=agent||null;
  const visibleRead:EventRead=perspective==='researcher'&&(!read.cursor||read.cursor.run_id===runId)
    &&(!read.request||read.request.agent===selectedAgent)?read:{phase:'idle'};
  useEffect(()=>{
    if(!runId||perspective!=='researcher'){setRead({phase:'idle'});return;}
    let disposed=false,inflight=false,last='',failed='';
    const controller=new AbortController();
    setRead(previous=>previous.cursor?.run_id===runId&&previous.request?.agent===selectedAgent
      ? {...previous,phase:previous.data?'refreshing':'loading',error:undefined}
      : {phase:'loading'});
    const update=async()=>{
      if(disposed||inflight||queryRef.current!==queryKey)return;
      const selected=latest.current.getCursor();
      if(!selected||selected.run_id!==runId)return;
      const cursor=pinned?.cursor||selected;
      const request:EventRequest={cursor,agent:selectedAgent,limit:500,
        ...(pinned?.before_sequence?{before_sequence:pinned.before_sequence}:{}),
        ...(pinned?.after_sequence?{after_sequence:pinned.after_sequence}:{})};
      const key=JSON.stringify(request);
      if(key===last||key===failed)return;
      inflight=true;
      setRead(previous=>({...previous,phase:previous.data?'refreshing':'loading',error:undefined}));
      try{
        const data=await latest.current.fetchEvents(request,controller.signal);
        if(disposed||queryRef.current!==queryKey)return;
        const source={run_id:data.run_id,time:String(data.cursor?.time),revision:String(data.cursor?.revision)};
        if(!sameCursor(source,cursor)||(data.agent??null)!==selectedAgent)throw Error('Events returned a different source cursor or identity filter. Retry to load the requested page.');
        if(!Array.isArray(data.records)||!map(data.occurrences)||!map(data.page)
          ||data.page.limit!==request.limit||data.page.loaded_count!==data.records.length||data.records.length>request.limit
          ||typeof data.page.has_older!=='boolean'||typeof data.page.has_newer!=='boolean')throw Error('The service returned an incomplete event page.');
        let previous=-1n;const references=new Set<string>();
        for(const record of data.records){
          if(!map(record)||!integer(record.ledger_sequence)||!integer(record.ledger_revision)
            ||!integer(record.revision_before)||!integer(record.revision_after))throw Error('The service returned an invalid event cursor.');
          const sequence=BigInt(record.ledger_sequence),revision=BigInt(record.ledger_revision);
          if(sequence<=0n||sequence<=previous||revision>BigInt(source.revision)
            ||BigInt(record.revision_after)!==revision||BigInt(record.revision_before)!==(revision>0n?revision-1n:0n)
            ||(request.before_sequence&&sequence>=BigInt(request.before_sequence))
            ||(request.after_sequence&&sequence<=BigInt(request.after_sequence)))throw Error('The service returned events outside the requested causal page or order.');
          previous=sequence;
          for(const value of [record.occurrence,record.action_id])if(value!=null)references.add(String(value));
        }
        if(data.page.first_sequence!==(data.records.length?String(data.records[0].ledger_sequence):null)
          ||data.page.last_sequence!==(data.records.length?String(data.records.at(-1)!.ledger_sequence):null)
          ||Object.keys(data.occurrences).some(identity=>!references.has(identity)))throw Error('The service returned inconsistent event page boundaries or unrelated occurrence details.');
        const current=latest.current.getCursor();
        if(!current||current.run_id!==runId)return;
        if(!pinned&&mode==='replay'&&!sameCursor(source,current))return;
        setRead({phase:'ready',cursor:source,data,request,queryKey});last=key;failed='';
      }catch(error:any){
        if(disposed||controller.signal.aborted||queryRef.current!==queryKey)return;
        failed=key;setRead(previous=>({...previous,phase:'failed',error:error.message||'Events could not be loaded.'}));
      }finally{inflight=false;}
    };
    void update();const timer=setInterval(()=>void update(),500);
    return()=>{disposed=true;controller.abort();clearInterval(timer);};
  },[queryKey,attempt]);
  const navigate=(direction:'older'|'newer')=>{
    const result=visibleRead;
    if(!result.cursor||!result.data||result.queryKey!==queryKey||result.phase!=='ready')return;
    const boundary=direction==='older'?result.data.page.first_sequence:result.data.page.last_sequence;
    if(!boundary||!(direction==='older'?result.data.page.has_older:result.data.page.has_newer))return;
    setPage({context,cursor:{...result.cursor},...(direction==='older'?{before_sequence:boundary}:{after_sequence:boundary})});
  };
  return {read:visibleRead,queryKey,following:!pinned,pinnedCursor:pinned?.cursor,
    older:()=>navigate('older'),newer:()=>navigate('newer'),
    latest:()=>{setPage(undefined);setAttempt(value=>value+1);},retry:()=>setAttempt(value=>value+1)};
}
