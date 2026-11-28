import {EventsReader} from './core/AnalysisReaders';
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
    setRead(previous=>previous.cursor?.run_id===runId&&previous.request?.agent===selectedAgent
      ? {...previous,phase:previous.data?'refreshing':'loading',error:undefined}
      : {phase:'loading'});
    const reader=new EventsReader({current:()=>queryRef.current===queryKey,read:async(signal)=>{
      const selected=latest.current.getCursor();
      if(!selected||selected.run_id!==runId)return;
      const cursor=pinned?.cursor||selected;
      const request:EventRequest={cursor,agent:selectedAgent,limit:500,
        ...(pinned?.before_sequence?{before_sequence:pinned.before_sequence}:{}),
        ...(pinned?.after_sequence?{after_sequence:pinned.after_sequence}:{})};
      const key=JSON.stringify(request);
      if(!reader.accepts(key))return;
      setRead(previous=>({...previous,phase:previous.data?'refreshing':'loading',error:undefined}));
      try{
        const data=await latest.current.fetchEvents(request,signal);
        if(!reader.current)return;
        const source=reader.validate(data,request);
        const current=latest.current.getCursor();
        if(!current||current.run_id!==runId)return;
        if(!pinned&&mode==='replay'&&!sameCursor(source,current))return;
        setRead({phase:'ready',cursor:source,data,request,queryKey});reader.succeeded(key);
      }catch(error:any){
        if(!reader.current)return;
        reader.failed(key);setRead(previous=>({...previous,phase:'failed',error:error.message||'Events could not be loaded.'}));
      }
    }});
    reader.start();return()=>reader.dispose();
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
