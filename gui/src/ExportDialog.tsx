import {ExactTimeInput} from './TimeValue';
import React,{useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ExportSession} from './core/ExportSession';
let inspection:Record<string,unknown>={};
Object.defineProperty(window,'__zombieExportInspection',{configurable:true,get:()=>structuredClone(inspection)});
export default function ExportDialog({runId,time,revision,onClose}:{runId:string;time:string;revision:string;onClose?:()=>void}){
  const [session]=useState(()=>new ExportSession(runId,time));useSyncExternalStore(session.subscribe,session.getVersion);
  const {format,setFormat,selected,setSelected,start,setStart,end,setEnd,interval,setInterval,cohort,setCohort,cohorts,job,error,pending,active,begin,cancel}=session;
  const details=useRef<HTMLDetailsElement>(null);
  useEffect(()=>{session.load(runId);return()=>session.dispose();},[session,runId]);
  useEffect(()=>{inspection={run_id:runId,format,time:selected,interval:[start,end],sample_interval:interval,cohort,job,error};},[runId,format,selected,start,end,interval,cohort,job,error]);
  return <details className="export-menu" ref={details}><summary data-testid="export-open">Export ↗</summary>
    <section aria-label="Export recorded data" style={{padding:16,minWidth:300,maxWidth:420,display:'grid',gap:10}}>
      <strong>Export recorded data</strong><small>Capture a committed history revision. The run continues independently.</small>
      <label>Format<select data-testid="export-format" value={format} disabled={active} onChange={e=>setFormat(e.target.value)}>
        <option value="scene_png">World scene · PNG</option><option value="chart_png">Population chart · PNG</option><option value="chart_svg">Population chart · SVG</option>
        <option value="table_csv">Population table · CSV</option><option value="table_parquet">Population table · Parquet</option><option value="replay_animation">Portable replay animation · HTML</option>
      </select></label>
      <ExactTimeInput label="Scene time (s)" data-testid="export-time" value={selected} disabled={active} onChange={e=>setSelected(e.target.value)}/>
      <ExactTimeInput label="Interval start (s)" data-testid="export-interval-start" value={start} disabled={active} onChange={e=>setStart(e.target.value)}/>
      <ExactTimeInput label="Interval end (s)" data-testid="export-interval-end" value={end} disabled={active} onChange={e=>setEnd(e.target.value)}/>
      <ExactTimeInput label="Sample interval (s)" data-testid="export-sample-interval" value={interval} disabled={active} onChange={e=>setInterval(e.target.value)}/>
      <label>Cohort<select data-testid="export-cohort" value={cohort} disabled={active} onChange={e=>setCohort(e.target.value)}><option value="all">All identities</option>{cohorts.map(item=><option key={item.id||item.name} value={item.id||item.name}>{item.name}</option>)}</select></label>
      <small>Current viewer revision: {revision}. Every artifact includes a provenance file.</small>
      {error&&<p role="alert">{error}</p>}
      <div><button data-testid="export-start" disabled={pending||active} onClick={begin}>{pending?'Starting…':'Start export'}</button> <button data-testid="export-cancel" disabled={!active} onClick={cancel}>Cancel export</button></div>
      {job&&<p role="status" data-testid="export-job-status">{job.status} · {job.active_tasks} active tasks</p>}
      {job?.status==='COMPLETED'&&<><a data-testid="export-artifact" href={job.artifact_url} download>Download artifact</a><a data-testid="export-provenance" href={job.provenance_url} download>Download provenance</a></>}
      <button onClick={()=>{if(details.current)details.current.open=false;onClose?.();}}>Close export panel</button>
    </section></details>;
}
