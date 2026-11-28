import ViewerLoadPanel from './ViewerLoadPanel';
import {TimeValue, ExactTimeInput} from '../TimeValue';
import {formatTime} from '../timeFormat';
import React, {useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore} from 'react';
import ExportDialog from '../ExportDialog';
import CommandDialog from '../CommandDialog';
import {isInactiveRun, lifecycleLabel, runGroup, terminationNotice} from '../runLifecycle';
import {configurationMetadata, parseConfigurationDraft} from '../configurationDraft';
import {configurationNumberRules, parseNumericText} from '../numericDraft';
import {applyRoleEdits, effectivePopulation, roleEditingBlock, parseRolePercentage, readRoleGroups} from '../roleAllocation';
import RoleAllocationPanels from '../RoleAllocationPanels';
import ModelSelection from '../ModelSelection';
import {ModelField, readModelSetting} from '../modelSelection';
import StatisticsPanel from '../StatisticsPanel';
import useStatisticsReader, {MetricCursor, MetricRead} from '../useStatisticsReader';
import useCohortReader, {CohortRead} from '../useCohortReader';
import CohortPanel from '../CohortPanel';
import useEventsReader from '../useEventsReader';
import EventsPanel from '../EventsPanel';
import useComparisonReader from '../useComparisonReader';
import ComparisonPanel from '../ComparisonPanel';
import RunViewStatus, {confirmedStatusLabel, statusFreshness} from '../RunViewStatus';
import {applyWorldResize, effectiveWorld, worldResizeSummary} from '../worldLayout';

import {Obj,Bundle,ViewerLoad,inspection,colors,values,seconds,fixed,id,api,download,agentStatus} from '../uiRuntime';
import World from './World';
import {RunCatalog} from '../core/RunCatalog';
import {ViewSession} from '../core/ViewSession';
import {ExecutionSession} from '../core/ExecutionSession';
import Configuration from './Configuration';
import InterventionDialog from './InterventionDialog';

export default function Workspace(){
  const[catalog]=useState(()=>new RunCatalog(api));useSyncExternalStore(catalog.subscribe,catalog.getVersion);
  const runs=catalog.rows,setRuns=catalog.setRows,runListState=catalog.state,setRunListState=catalog.setState;
  const[runId,setRunId]=useState('');const[view,setView]=useState<Bundle>();const[mode,setMode]=useState<'live'|'replay'>('live');const[seek,setSeek]=useState('0');const[selected,setSelected]=useState('');const[follow,setFollow]=useState(false);const[tab,setTab]=useState('world');const[configOpen,setConfigOpen]=useState(false);const[configSource,setConfigSource]=useState<Obj>();const[interventionOpen,setInterventionOpen]=useState(false);const[error,setError]=useState('');const[notice,setNotice]=useState<React.ReactNode>('');const[filter,setFilter]=useState('');const[eventFilter,setEventFilter]=useState('');const[eventDetailData,setEventDetail]=useState<Obj>();const[eventDetailSource,setEventDetailSource]=useState<MetricCursor>();const[layers,setLayers]=useState<Obj>({resources:true,remains:true,labels:true,actions:true,trails:false,sensing:false,agents:true});const[perspective,setPerspective]=useState('researcher');const[observation,setObservation]=useState<Obj>();const[playing,setPlaying]=useState(false);const[replaySpeed,setReplaySpeed]=useState(1);const[viewPending,setViewPending]=useState(false);
  const[comparisonChosen,setComparisonChosen]=useState<string[]>([]);const[comparisonMetric,setComparisonMetric]=useState('infected');
  const viewRef=useRef(view);viewRef.current=view;
  const[replayDraft,setReplayDraft]=useState<{runId:string;text:string}>();
  const[replayTimeError,setReplayTimeError]=useState('');
  const replayEdited=replayDraft?.runId===runId;
  const replayInput=replayEdited?replayDraft!.text:String(view?.time??seek);
  const[viewerLoad,setViewerLoad]=useState<ViewerLoad>({phase:'idle',run_id:''});
  const[,setStatusTick]=useState(0);
  useEffect(()=>{const timer=setInterval(()=>setStatusTick(value=>value+1),1000);return()=>clearInterval(timer);},[]);
  // The timer refreshes an idle replay, but every render samples the real clock.
  // Reusing the previous tick could briefly mark a late response as fresh.
  const statusNow=Date.now();
  const[viewAttempt,setViewAttempt]=useState(0);
  const[startingRuns,setStartingRuns]=useState<Record<string,boolean>>({});
  const starting=Boolean(startingRuns[runId]);
  const uncertainStarts=useRef(new Set<string>());
  const viewerLoadRef=useRef(viewerLoad);viewerLoadRef.current=viewerLoad;
  const setViewerState=(state:ViewerLoad)=>{viewerLoadRef.current=state;setViewerLoad(state);};
  const selectionSummaryAfter=useRef(0);
  const listRequest=catalog.request;const runIdRef=useRef(runId);runIdRef.current=runId;
  const liveRef=useRef(mode);liveRef.current=mode;const perspectiveRef=useRef(perspective);perspectiveRef.current=perspective;
  const run=runs.find(r=>r.id===runId);const finished=['completed','terminated'].includes(run?.status);
  const executionFreshness=statusFreshness(run,runListState.phase,statusNow);
  const runRef=useRef(run);runRef.current=run;
  const sessionOptions={runIdRef,perspectiveRef,liveRef,viewRef,viewerLoadRef,runRef,setView,setSeek,setViewerState,setViewPending,setError};
  const [session]=useState(()=>new ViewSession(sessionOptions,api));session.options=sessionOptions;
  const {requestGeneration,viewAbort,streamRef,lastViewRequest}=session;
  useEffect(()=>()=>session.dispose(),[session]);
  const executionContext={identity:()=>runIdRef.current,run:()=>runRef.current,starting:(identity:string)=>Boolean(startingRuns[identity]),live:()=>liveRef.current==='live',loadView:session.loadView,
    requested:(operation:string)=>setNotice(`${operation.replaceAll('_',' ')} requested…`),
    applied:(operation:string,result:Obj)=>setNotice(<>{operation==='terminate'?'Termination acknowledged; waiting for cleanup':'Applied'} at <TimeValue value={result.time}/> · revision {result.revision}</>),error:setError};
  const[execution]=useState(()=>new ExecutionSession(executionContext,catalog,api));execution.context=executionContext;useSyncExternalStore(execution.subscribe,execution.getVersion);
  const {pending,terminationRequest,result:commandResult,setResult:setCommandResult,generations:controlGenerations}=execution;

  const unknownSummaryVersion=run?0:(runListState.version??0);
  const terminalCursor=isInactiveRun(run)?`${run?.status}:${run?.frontier?.revision??''}`:'';
  const statistics=useStatisticsReader({runId,mode,perspective,selectionVersion:mode==='replay'?requestGeneration.current:0,
    getCursor:()=>{
      const current=viewRef.current;
      if(!current||current.run_id!==runIdRef.current||perspectiveRef.current!=='researcher'||viewerLoadRef.current.phase!=='ready')return;
      if(isInactiveRun(runRef.current)&&liveRef.current==='live'&&String(current.revision)!==String(runRef.current?.frontier?.revision))return;
      return {run_id:current.run_id,time:String(current.time),revision:String(current.revision)};
    },fetchMetrics:(cursor,signal)=>api(`/runs/${cursor.run_id}/metrics?end=${encodeURIComponent(cursor.time)}&revision=${cursor.revision}`,undefined,signal)});
  const metricsState:MetricRead=perspective==='researcher'&&(!statistics.read.cursor||statistics.read.cursor.run_id===runId)?statistics.read:{phase:'idle'};
  const samples=metricsState.data?.samples||[];const eventCounts=metricsState.data?.event_counts||{};
  const metricsCursor=metricsState.cursor?{...metricsState.cursor,populations:samples.at(-1)}:undefined;
  const cohortReader=useCohortReader({runId,mode,perspective,selectionVersion:mode==='replay'?requestGeneration.current:0,
    getCursor:()=>{
      const current=viewRef.current;
      if(!current||current.run_id!==runIdRef.current||perspectiveRef.current!=='researcher'||viewerLoadRef.current.phase!=='ready')return;
      if(isInactiveRun(runRef.current)&&liveRef.current==='live'&&String(current.revision)!==String(runRef.current?.frontier?.revision))return;
      return {run_id:current.run_id,time:String(current.time),revision:String(current.revision)};
    },fetchCohorts:(cursor,signal)=>api(`/runs/${cursor.run_id}/cohorts?time=${encodeURIComponent(cursor.time)}&revision=${cursor.revision}&with_cursor=true`,undefined,signal)});
  const cohortsState:CohortRead=perspective==='researcher'&&(!cohortReader.read.cursor||cohortReader.read.cursor.run_id===runId)?cohortReader.read:{phase:'idle'};
  const cohorts=cohortsState.data?.cohorts||[];const cohortsCursor=cohortsState.cursor;
  const eventReader=useEventsReader({runId,mode,perspective,selectionVersion:mode==='replay'?requestGeneration.current:0,agent:selected,
    getCursor:()=>{
      const current=viewRef.current;
      if(!current||current.run_id!==runIdRef.current||perspectiveRef.current!=='researcher'||viewerLoadRef.current.phase!=='ready')return;
      if(isInactiveRun(runRef.current)&&liveRef.current==='live'&&String(current.revision)!==String(runRef.current?.frontier?.revision))return;
      return {run_id:current.run_id,time:String(current.time),revision:String(current.revision)};
    },fetchEvents:(request,signal)=>{
      const query=new URLSearchParams({time:request.cursor.time,revision:request.cursor.revision,limit:String(request.limit)});
      if(request.agent!==null)query.set('agent',request.agent);
      if(request.before_sequence)query.set('before_sequence',request.before_sequence);
      if(request.after_sequence)query.set('after_sequence',request.after_sequence);
      return api(`/runs/${request.cursor.run_id}/timeline?${query}`,undefined,signal);
    }});
  const eventsState=eventReader.read;const events=eventsState.data?.records||[];
  const timelineOccurrences=eventsState.data?.occurrences||{};const eventsCursor=eventsState.cursor;const auxiliaryCursor=eventsCursor;
  const eventDetail=perspective==='researcher'&&eventDetailSource?.run_id===runId?eventDetailData:undefined;
  const comparison=useComparisonReader({currentRun:runId,perspective,visible:tab==='comparison'&&Boolean(view),chosen:comparisonChosen,runs,
    fetchComparison:(sources,signal)=>api('/comparison',{sources},signal)});
  const comparisonContextRef=useRef(comparison.context);comparisonContextRef.current=comparison.context;

  const runGroups=[{id:'active',label:'Active'},{id:'saved',label:'Saved / completed'},{id:'terminated',label:'Terminated history'}];
  const frontier=seconds(run?.frontier?.time||view?.time||0);const agent=selected?view?.state.agents?.[selected]:null;
  const cancelViewerRequest=session.cancel;
  const selectRun=(identity:string)=>{
    if(identity!==runIdRef.current)setComparisonChosen(identity?[identity]:[]);
    delete inspection.comparison;delete inspection.comparison_chart;
    cancelViewerRequest();delete inspection.statistics_chart;runIdRef.current=identity;viewRef.current=undefined;setView(undefined);setViewPending(false);
    liveRef.current='live';perspectiveRef.current='researcher';setMode('live');setPerspective('researcher');setPlaying(false);
    setRunId(identity);setReplayDraft(undefined);setReplayTimeError('');setError('');setNotice('');
    const next=runs.find(row=>row.id===identity);runRef.current=next;selectionSummaryAfter.current=listRequest.current+1;
    setViewerState({phase:identity?(next?.status==='initializing'?'initializing':'loading'):'idle',run_id:identity,details:!next});
    if(identity===runId)setViewAttempt(value=>value+1);
    if(identity&&!next)refreshRuns();
  };
  const returnToRuns=()=>{
    const loading=['loading','initializing'].includes(viewerLoadRef.current.phase);selectRun('');
    setNotice(loading?'Viewer loading cancelled. Simulation execution is unchanged. Any atomic reader work already in progress may finish before it stops.':'Returned to the run list. Simulation execution is unchanged.');
  };
  catalog.perspective=()=>perspectiveRef.current;
  catalog.onSummary=item=>{
    if(controlGenerations.current[item.id]===undefined)controlGenerations.current[item.id]=item.generation;
    if(uncertainStarts.current.has(item.id)&&item.status!=='initializing'&&(Number(item.generation)>0||isInactiveRun(item))){
      controlGenerations.current[item.id]=item.generation;uncertainStarts.current.delete(item.id);setStartingRuns(previous=>({...previous,[item.id]:false}));
    }
  };
  const refreshRuns=catalog.refresh;
  useEffect(()=>{catalog.start();return()=>catalog.dispose();},[catalog]);
  useEffect(()=>{setSelected('');setObservation(undefined);setEventDetail(undefined);setEventDetailSource(undefined);setEventFilter('');},[runId]);
  const loadView=session.loadView;
  const retryView=()=>{if(!runRef.current){selectionSummaryAfter.current=listRequest.current+1;setViewerState({phase:'loading',run_id:runIdRef.current,details:true});}refreshRuns();if(mode==='live')setViewAttempt(value=>value+1);else loadView(lastViewRequest.current.time,lastViewRequest.current.revision);};
  useEffect(()=>{
    if(!runId||mode!=='live'||perspective!=='researcher')return;
    if(runListState.phase==='failed'&&(!viewRef.current||run?.status==='initializing')){
      setViewerState({phase:'failed',run_id:runId,error:runListState.error});return;
    }
    if(run?.status==='initializing'){
      setViewerState({phase:'initializing',run_id:runId});return;
    }
    if(!run){
      // An accepted new identity can precede the next lightweight summary.
      // Never probe its history merely because an older run list was ready.
      const missing=runListState.phase==='ready'&&(runListState.version??0)>=selectionSummaryAfter.current;
      setViewerState(missing?{phase:'failed',run_id:runId,error:'This run is no longer listed by the service. Retry loading or return to the run list.'}:{phase:'loading',run_id:runId,details:true});return;
    }
    return session.follow(runId,terminalCursor);
  },[runId,mode,perspective,terminalCursor,run?.status==='initializing',Boolean(run),runListState.phase,unknownSummaryVersion,viewAttempt]);
  useEffect(()=>{if(!playing||mode!=='replay')return;const timer=setInterval(()=>{setSeek(old=>{const next=Math.min(frontier,seconds(old)+.5*replaySpeed);loadView(String(next));if(next>=frontier)setPlaying(false);return String(next);});},500);return()=>clearInterval(timer);},[playing,replaySpeed,frontier,mode,runId]);
  const replay=(time:string,revision?:string)=>{setReplayDraft(undefined);setReplayTimeError('');cancelViewerRequest();liveRef.current='replay';setMode('replay');setSeek(time);setPerspective('researcher');setObservation(undefined);loadView(time,revision);};
  const inspectReplayTime=()=>{
    if(!formatTime(replayInput).valid){setReplayTimeError('Enter a complete, nonnegative time in seconds, such as 2.5 or 5/2.');return;}
    replay(replayInput.trim(),replayEdited?undefined:view?.revision);
  };
  const returnToLive=()=>{setReplayDraft(undefined);setReplayTimeError('');cancelViewerRequest();liveRef.current='live';perspectiveRef.current='researcher';setMode('live');setPlaying(false);setPerspective('researcher');setObservation(undefined);};
  const command=execution.execute;
  const selectPerspective=async(value:string)=>{
    if(value==='agent'&&!selected){setError('Select an agent first.');return;}
    cancelViewerRequest();delete inspection.comparison;delete inspection.comparison_chart;perspectiveRef.current=value;setViewPending(false);setPerspective(value);setObservation(undefined);setEventDetail(undefined);setEventDetailSource(undefined);setPlaying(false);
    if(value==='agent'){
      const cursor=viewRef.current;inspection.configuration={};delete inspection.statistics_chart;setConfigSource(undefined);setConfigOpen(false);setRuns(rows=>rows.map(row=>({...row,config:{scenario:row.config.scenario,seed:row.config.seed,horizon:row.config.horizon}})));
      // The only retained scene is the selected observer's later recorded input.
      viewRef.current=undefined;setView(undefined);
      const identity=runIdRef.current;const token=++requestGeneration.current;const controller=new AbortController();viewAbort.current=controller;
      try{const recorded=await api(`/runs/${identity}/observations/${selected}?revision=${cursor?.revision}`,undefined,controller.signal);
        if(controller.signal.aborted||token!==requestGeneration.current||identity!==runIdRef.current||perspectiveRef.current!=='agent')return;setObservation(recorded);
      }catch(e:any){if(!controller.signal.aborted&&token===requestGeneration.current&&identity===runIdRef.current)setError(e.message);}
      finally{if(viewAbort.current===controller)viewAbort.current=undefined;}
    }else if(mode==='replay'){await loadView(lastViewRequest.current.time,lastViewRequest.current.revision);}
  };
  const exportLink=(format:string)=>`/api/runs/${runId}/export?format=${format}&revision=${view?.revision}${mode==='replay'?`&time=${encodeURIComponent(view?.time||'0')}`:''}`;
  const visibleAgents=values(view?.state.agents).filter(a=>[a.id,a.type,a.role,a.status].join(' ').toLowerCase().includes(filter.toLowerCase()));
  const shownEvents=events.filter(event=>JSON.stringify(event).toLowerCase().includes(eventFilter.toLowerCase()));
  useLayoutEffect(()=>{
    inspection.react_commit={at:performance.now(),count:(inspection.react_commit?.count||0)+1};
    if(inspection.comparison?.context!==comparison.context)delete inspection.comparison_chart;
    inspection.comparison={current_run:runId,chosen:comparisonChosen,metric:comparisonMetric,...comparison.read,context:comparison.context,requested_sources:perspective==='researcher'?comparison.requested_sources:[],requested_key:perspective==='researcher'?comparison.requested_key:undefined,stale:comparison.stale,unavailable:comparison.unavailable};
    inspection.app={run_id:runId,mode,seek,perspective,selected,follow,view,observation,events,shownEvents,cohorts,samples,
      selected_event:eventDetail,selected_event_source:eventDetail?eventDetailSource:undefined,timeline_occurrences:timelineOccurrences,events_state:eventsState,events_cursor:eventsCursor,events_page:eventsState.data?.page,events_following:eventReader.following,events_query_key:eventReader.queryKey,metrics_cursor:metricsCursor,metrics_state:metricsState,cohorts_state:cohortsState,cohorts_cursor:cohortsCursor,auxiliary_cursor:auxiliaryCursor,command:commandResult,run,pending,start_pending:starting,start_uncertain:uncertainStarts.current.has(runId),view_pending:viewPending,viewer_load:viewerLoad,run_list_state:runListState,layers,
      privileged_cache_keys:perspective==='agent'?[...(comparison.read.data?['comparison']:[]),...(inspection.comparison_chart?['comparison_chart']:[]),...(view?['view']:[]),...(events.length?['events']:[]),...(samples.length?['samples']:[]),...(cohorts.length?['cohorts']:[]),...(Object.keys(eventCounts).length?['eventCounts']:[]),...(eventDetail?['eventDetail']:[]),...(Object.keys(timelineOccurrences).length?['timelineOccurrences']:[]),...(configSource?['configSource']:[]),...(Object.keys(inspection.configuration).length?['configurationPreview']:[]),...runs.filter(row=>row.config.agents||row.config.barriers||row.config.stockpiles).map(row=>`run-config:${row.id}`)]:[]};
  });
  return <div className="app"><aside className="sidebar"><a className="brand" href="/" aria-label="Outbreak home"><span className="brand-icon">✳</span><div>OUTBREAK<small>SIMULATION WORKSPACE</small></div></a><button className="primary new-run" onClick={()=>{setConfigSource(undefined);setConfigOpen(true);}}>＋ New experiment</button><div className="run-list">{runGroups.map(group=>{
    const grouped=runs.filter(r=>runGroup(r,terminationRequest===r.id)===group.id);
    return <section key={group.id} className="run-group" data-testid={`run-group-${group.id}`} aria-label={group.label}>
      <h2 className="sidebar-title">{group.label}<span>{grouped.length}</span></h2>
      {grouped.map(r=><button key={r.id} data-run-id={r.id} className={`run-card ${r.id===runId?'active':''}`} onClick={()=>selectRun(r.id)}><span className={`status-dot ${r.status}`}/><div><strong>{r.config.scenario||'Untitled scenario'}</strong><small>{r.id.slice(0,8)} · seed {r.config.seed}</small><span>{confirmedStatusLabel(r,statusFreshness(r,runListState.phase,statusNow),terminationRequest===r.id)} · <TimeValue value={r.frontier.time} details={false}/></span></div></button>)}
      {!grouped.length&&<p className="run-group-empty">No runs</p>}
    </section>;
  })}</div><div className="sidebar-footer"><span className="eyebrow">ONTOLOGY v0.1</span><p>Asynchronous events.<br/>Exact clocks. Recorded evolution.</p><span className="connection">● Local workspace</span></div></aside>
  <main><header className="topbar"><div><span className="eyebrow">RESEARCH WORKSPACE</span><h1>{run?.config.scenario||'Explore an evolving world'}<span className="tag" data-testid="run-lifecycle-status">{run?confirmedStatusLabel(run,executionFreshness,terminationRequest===runId):'Ready'}</span></h1></div>{runId&&<button data-testid="run-return-list" onClick={returnToRuns}>← Run list</button>}<button data-testid="config-edit-new" onClick={()=>{setConfigSource(run?.config);setConfigOpen(true);}}>{run?'Edit as new run':'Configure new run'}</button></header>
  {error&&<div className="alert" role="alert"><span>{error}</span>{error.includes('Stale control generation')&&<button data-testid="command-refresh" onClick={()=>{if(run)controlGenerations.current[run.id]=run.generation;refreshRuns();setError('');}}>Refresh controls</button>}<button aria-label="Dismiss error" onClick={()=>setError('')}>✕</button></div>}
  {run?.error&&<div className="alert" role="alert">{run.error}</div>}
  <section className="control-bar" aria-label="Run execution controls"><div className="run-controls"><span className="control-label">EXECUTION</span><button data-testid="run-start" className="primary" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'||run.status==='running'} onClick={()=>command('continue')}>▶ Continue run</button><button data-testid="run-pause" aria-label="Pause run" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} onClick={()=>command('pause')}>Ⅱ Pause run</button><button data-testid="run-step-transition" disabled={!runId||pending||starting||run?.status!=='paused'} onClick={()=>command('step')}>Step transition</button><button data-testid="run-step-timestamp" disabled={!runId||pending||starting||run?.status!=='paused'} onClick={()=>command('step_timestamp')}>Step timestamp</button><button disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} data-testid="run-checkpoint" onClick={()=>{const name=window.prompt('Checkpoint name (optional)',`revision-${view?.revision??0}`);if(name!==null)command('checkpoint',{name});}}>Checkpoint</button><button data-testid="run-stop" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} onClick={()=>command('stop')}>Stop & save</button><button data-testid="run-terminate" className="danger" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} aria-describedby="termination-help" title="End this run permanently without writing a new checkpoint. Existing checkpoints and committed audit history are retained." onClick={()=>command('terminate')}>Terminate without a new checkpoint</button><button disabled={!runId||pending||starting||!['paused','stopped','completed'].includes(run?.status)} onClick={()=>setInterventionOpen(true)}>Branch / intervene</button>{run&&view&&!starting&&<CommandDialog run={run} view={view} onApplied={(result,operation)=>{setCommandResult(result);controlGenerations.current[result.run_id]=result.generation??0;if(operation==='start'||operation==='branch')selectRun(result.run_id);setNotice(<>Applied at <TimeValue value={result.time??view.time}/> · revision {result.revision??view.revision}</>);refreshRuns();loadView();}}/>}</div><label className="pace">Run pace<select data-testid="run-pacing" disabled={!runId||!run||pending||starting||finished||run.status==='initializing'} value={run?.frontier?.pacing??1} onChange={e=>command('pace',{pacing:Number(e.target.value)})}><option value={.25}>0.25×</option><option value={1}>1×</option><option value={4}>4×</option><option value={0}>Fastest</option></select></label><span className="ack" aria-live="polite">{terminationNotice(run,terminationRequest===runId)||(pending?'Pending…':starting?'Waiting for the start acknowledgement…':notice)}</span>{run?.frontier?.workers&&<span className="subtle">{run.frontier.workers} workers</span>}{runs.filter(r=>r.id!==runId&&r.status==='running').length>0&&<span className="subtle">{runs.filter(r=>r.id!==runId&&r.status==='running').length} other run(s) running</span>}</section>
  {run&&<p id="termination-help" className="termination-help">Termination skips a new checkpoint and keeps existing checkpoints and committed audit history. An already-running checkpoint may finish before termination takes effect.</p>}
  {runId&&<RunViewStatus run={run} freshness={executionFreshness} requested={terminationRequest===runId} mode={perspective==='agent'?'observation':mode} cursor={perspective==='agent'?(observation?{time:String(observation.time),revision:String(observation.revision)}:undefined):(view?{time:String(view.time),revision:String(view.revision)}:undefined)} waiting={viewerLoad.phase!=='ready'&&perspective!=='agent'} onLive={returnToLive}/>}
  {!runId?<section className="run-chooser panel" data-testid="run-chooser">
    <span className="eyebrow">YOUR SIMULATION WORKSPACE</span><h2>Choose a run or create an experiment.</h2>
    <p>Open a run from the sidebar or choose one below. History loads only when you select a run.</p>
    {notice&&<p className="chooser-notice" role="status">{notice}</p>}
    {runListState.phase==='loading'&&<p role="status">Loading run summaries…</p>}
    {runListState.phase==='failed'&&<div className="chooser-error"><p role="alert">Could not load run summaries. {runListState.error}</p><button data-testid="run-list-retry" onClick={()=>{setRunListState({phase:'loading'});refreshRuns();}}>Retry run list</button></div>}
    {runListState.phase==='ready'&&!runs.length&&<p>No runs yet. Create an experiment to get started.</p>}
    {runs.length>0&&<><p className="chooser-summary">{runs.length} recorded run{runs.length===1?'':'s'} · {runs.filter(row=>!isInactiveRun(row)).length} active or paused</p><div className="chooser-runs">{runs.slice(0,12).map(row=><button key={row.id} data-testid="chooser-select-run" onClick={()=>selectRun(row.id)}><strong>{row.config.scenario||'Untitled scenario'}</strong><span>{confirmedStatusLabel(row,statusFreshness(row,runListState.phase,statusNow))}{row.frontier?.time!=null&&row.frontier?.revision!=null&&<> · <TimeValue value={row.frontier.time} details={false}/> · revision {row.frontier.revision}</>}</span><small>{row.id}</small></button>)}</div>{runs.length>12&&<p>All {runs.length} runs are available in the sidebar.</p>}</>}
    <button className="primary" onClick={()=>{setConfigSource(undefined);setConfigOpen(true);}}>Create an experiment ↗</button>
  </section>:<>
  {perspective!=='agent'&&<ViewerLoadPanel state={viewerLoad} run={run} hasView={Boolean(view)} onCancel={returnToRuns} onRetry={retryView} onReturn={returnToRuns}/>}
  {(view||perspective==='agent')&&<>
  <section className="cursor-bar"><span className={`mode-badge ${mode}`}>{perspective==='agent'?'◷ RECORDED OBSERVATION':mode==='live'?'● LIVE FOLLOW':'◷ RECORDED REPLAY'}</span><label>Perspective<select data-testid="perspective" value={perspective} onChange={e=>selectPerspective(e.target.value)}><option value="researcher">Researcher · global state</option><option value="agent">Recorded agent observation</option></select></label></section>
  {perspective==='agent'?<section className="observation-panel panel"><h2>Recorded agent observation</h2><p>Only the selected decision’s recorded input is displayed. Global map, metrics, inspector, and event overlays are hidden.</p>{observation?<><p>Decision {observation.decision} · <TimeValue value={observation.time}/> · revision {observation.revision}</p><pre>{JSON.stringify(observation.observation,null,2)}</pre></>:<p>No observation loaded. Select an agent in researcher view and choose this perspective again.</p>}</section>:view&&<>
  <section className="metric-cards" aria-label="Population at the displayed revision">{Object.keys(colors).map(key=><div className="metric-card" data-status-token={{healthy:'HEALTHY',infected:'INFECTED',zombies:'ACTIVE',dead:'DEAD'}[key]} key={key}><span className="metric-symbol" style={{color:colors[key]}}>{key==='zombies'?'▲':key==='dead'?'×':key==='infected'?'◉':'●'}</span><div><span>{key==='healthy'?'Healthy humans':key==='infected'?'Infected humans':key==='zombies'?'Living zombies':'Dead identities'}</span><strong>{view.metrics.populations[key]}</strong></div></div>)}</section>
  <div className="workspace"><section className="main-panel panel"><nav className="tabs" aria-label="Workspace views">{['world','statistics','cohorts','events','comparison'].map(t=><button data-testid={`tab-${t}`} key={t} className={tab===t?'active':''} onClick={()=>setTab(t)}>{t[0].toUpperCase()+t.slice(1)}</button>)}<span className="panel-caption">{view.metrics.populations.total} identities · {view.state.world.length} × {view.state.world.width} m</span></nav>
  {tab==='world'&&<><div className="world-toolbar"><div className="legend"><span data-status-token="HEALTHY" style={{color:colors.healthy}}>● Human</span><span data-status-token="INFECTED" style={{color:colors.infected}}>◉ INFECTED</span><span data-status-token="ACTIVE" style={{color:colors.zombies}}>▲ Zombie</span><span data-status-token="DEAD" style={{color:colors.dead}}>× Dead</span></div><details className="layers"><summary>Layers</summary>{Object.keys(layers).map(key=><label className="check" key={key}><input data-testid={`layer-${key==='agents'?'global-agents':key}`} type="checkbox" checked={layers[key]} onChange={e=>setLayers(l=>({...l,[key]:e.target.checked}))}/>{key}</label>)}</details></div><World state={view.state} selected={selected} onSelect={setSelected} follow={follow} layers={layers}/><div className="agent-search"><label>Find an agent<input data-testid="agent-search" placeholder="ID, role, type or status…" value={filter} onChange={e=>setFilter(e.target.value)}/></label><label className="check"><input data-testid="agent-follow" type="checkbox" checked={follow} disabled={!selected} onChange={e=>setFollow(e.target.checked)}/>Follow selected identity</label><span>{visibleAgents.length} matching</span></div><div className="table-scroll"><table><caption className="sr-only">Searchable agents at revision {view.revision}</caption><thead><tr><th>Identity</th><th>Type / role</th><th>Status</th><th>Life</th><th>Stamina</th><th>Action</th></tr></thead><tbody>{visibleAgents.slice(0,100).map(a=><tr key={a.id} className={String(a.id)===selected?'selected':''}><td><button data-testid="agent-search-select" className="link" onClick={()=>setSelected(String(a.id))}>#{a.id}</button></td><td>{a.type}{a.role&&` · ${a.role}`}</td><td>{a.status||agentStatus(a)}</td><td>{a.life}</td><td>{fixed(a.stamina)}</td><td>{a.active_action||'idle'}</td></tr>)}</tbody></table></div>{visibleAgents.length>100&&<p className="subtle">Showing the first 100 matches. Narrow the search to inspect any identity.</p>}</>}
  <div hidden={tab!=='statistics'}><StatisticsPanel read={metricsState} selected={{run_id:runId,time:String(view.time),revision:String(view.revision)}} mode={mode} visible={tab==='statistics'} waitingForView={viewerLoad.phase!=='ready'} onRetry={statistics.retry} onSeek={replay} colors={colors} onChartState={state=>{if(perspectiveRef.current==='researcher'&&state.run_id===runIdRef.current)inspection.statistics_chart=state;}}/></div>
  <div hidden={tab!=='comparison'}><ComparisonPanel runs={runs} chosen={comparisonChosen} onChoose={setComparisonChosen} metric={comparisonMetric} onMetric={setComparisonMetric} read={comparison.read} context={comparison.context} requestedSources={comparison.requested_sources} stale={comparison.stale} unavailable={comparison.unavailable} visible={tab==='comparison'} onRetry={comparison.retry} onExport={download} onChartState={state=>{if(perspectiveRef.current==='researcher'&&state.context===comparisonContextRef.current)inspection.comparison_chart=state;}}/></div>
  <div hidden={tab!=='cohorts'}><CohortPanel key={runId} read={cohortsState} selected={{run_id:runId,time:String(view.time),revision:String(view.revision)}} waitingForView={viewerLoad.phase!=='ready'} onRetry={cohortReader.retry} onCreate={(definition,signal)=>api(`/runs/${runId}/cohorts`,definition,signal)} onExport={(cohort,cursor)=>download(`cohort-${cohort.definition.id}.json`,JSON.stringify({...cohort,...cursor},null,2))} colors={colors}/></div>
  {tab==='events'&&<EventsPanel read={eventsState} selected={{run_id:runId,time:String(view.time),revision:String(view.revision)}} mode={mode} following={eventReader.following} queryKey={eventReader.queryKey} waitingForView={viewerLoad.phase!=='ready'} agent={selected} search={eventFilter} onSearch={setEventFilter} onClearAgent={()=>setSelected('')} onRetry={eventReader.retry} onLatest={eventReader.latest} onOlder={eventReader.older} onNewer={eventReader.newer} onSelect={(event,cursor)=>{setEventDetail(event);setEventDetailSource({...cursor});replay(String(event.time??0),String(event.revision_after));}}/>}
  </section><aside className="inspector panel"><header><span className="eyebrow">IDENTITY INSPECTOR</span>{selected&&<button aria-label="Clear agent selection" onClick={()=>setSelected('')}>✕</button>}</header>{agent?<><div className="identity-heading"><span className="identity-icon" style={{color:colors[agentStatus(agent)]}}>{agent.type==='Zombie'?'▲':'●'}</span><div><h2>Agent #{agent.id}</h2><p>{agent.type} · {agent.role||'No active role'}</p></div></div><span data-status-token={agent.status||agentStatus(agent)} className="tag">{agent.status||agentStatus(agent)}</span>{['life','stamina','hunger'].filter(k=>agent[k]!==undefined).map(k=><div className="gauge" key={k}><div><span>{k}</span><strong>{fixed(agent[k])} / 100</strong></div><meter min={0} max={100} value={agent[k]} aria-label={k}/></div>)}<dl><dt>Position</dt><dd>{fixed(agent.x)}, {fixed(agent.y)} m</dd><dt>Model</dt><dd>{typeof agent.model_assignment==='object'?JSON.stringify(agent.model_assignment):agent.model_assignment||'Default utility'}</dd><dt>Action</dt><dd>{agent.active_action||'Idle'}</dd><dt>Inventory</dt><dd>{JSON.stringify(agent.inventory||{})}</dd><dt>Reserved subset</dt><dd>{JSON.stringify(agent.reserved||{})}</dd></dl>{agent.infection_episode&&<section className="infection-card"><h3>Active infection episode</h3><pre>{JSON.stringify(view.state.episodes?.[agent.infection_episode]||agent.infection_episode,null,2)}</pre></section>}<button onClick={()=>{setTab('events');setEventFilter('');}}>Inspect identity history ↗</button><details open><summary>Attributes, effects & cooldowns</summary><pre>{JSON.stringify(agent,null,2)}</pre></details></>:<div className="empty"><span className="empty-icon">⌖</span><h3>Follow an identity</h3><p>Select an agent on the map or use the searchable table. Identity persists through conversion and death.</p></div>}{eventDetail&&<section className="event-detail"><h3>Selected event</h3><p>Event time <TimeValue value={eventDetail.time}/> · revisions {eventDetail.revision_before} → {eventDetail.revision_after}</p><p data-testid="event-detail-source">Loaded from <TimeValue value={eventDetailSource?.time}/> · revision {eventDetailSource?.revision}. Event sequence {eventDetail.ledger_sequence}.</p><button data-testid="event-before" onClick={()=>replay(String(eventDetail.time??0),String(eventDetail.revision_before))}>Before recorded transition</button><button data-testid="event-after" onClick={()=>replay(String(eventDetail.time??0),String(eventDetail.revision_after))}>After recorded transition</button><pre>{JSON.stringify(eventDetail,null,2)}</pre></section>}</aside></div></>}
  {view&&<><section className="replay-bar" aria-label="Viewer playback controls"><div><span className="control-label">VIEWER</span><button data-testid="replay-pause" disabled={mode==='live'} onClick={()=>setPlaying(v=>!v)}>{playing?'Ⅱ':'▶'} Replay</button><select data-testid="view-pacing" aria-label="Replay speed" value={replaySpeed} onChange={e=>setReplaySpeed(Number(e.target.value))}><option value={.25}>0.25×</option><option value={1}>1×</option><option value={4}>4×</option><option value={16}>16×</option></select></div><label className="scrubber"><span>Scrub to inspect recorded history. Use execution controls to pause or stop the simulation.</span><input aria-label="Replay time" type="range" min={0} max={Math.max(.01,frontier)} step="any" value={Math.min(frontier,seconds(seek))} onChange={e=>replay(e.target.value)}/></label><ExactTimeInput key={runId} label="Recorded time" data-testid="replay-exact-time" value={replayInput} aria-invalid={Boolean(replayTimeError)} aria-describedby={replayTimeError?'replay-time-error':undefined} onChange={e=>{setReplayDraft({runId,text:e.target.value});setReplayTimeError('');}} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();inspectReplayTime();}}}/><button data-testid="replay-seek" onClick={inspectReplayTime}>Inspect recorded time</button>{replayEdited&&<button data-testid="replay-time-reset" onClick={()=>{setReplayDraft(undefined);setReplayTimeError('');}}>Use selected view time</button>}{replayTimeError&&<p role="alert" id="replay-time-error" data-testid="replay-time-error">{replayTimeError}</p>}<ExportDialog runId={runId} time={view.time} revision={view.revision}/></section><footer className="status-footer"><span>Run {runId.slice(0,12)} · displayed r{view.revision} · frontier when view was read r{view.committed_frontier}</span><span>Researcher views never feed information to agent policies.</span></footer></>}</>}</>}
  </main>{interventionOpen&&view&&run&&<InterventionDialog view={view} run={run} onClose={()=>setInterventionOpen(false)} onCommand={command} onBranch={async seed=>{try{const result=await api(`/runs/${runId}/branch`,{command_id:id(),revision:view.revision,generation:run.generation,seed});selectRun(result.run_id);refreshRuns();}catch(e:any){setError(e.message);throw e;}}}/>}{configOpen&&<Configuration source={configSource} onClose={()=>setConfigOpen(false)} onCreated={(identity,generation)=>{if(generation!==undefined)controlGenerations.current[identity]=generation;selectRun(identity);refreshRuns();}} onStartState={(identity,pending,generation,uncertain)=>{if(uncertain)uncertainStarts.current.add(identity);else uncertainStarts.current.delete(identity);setStartingRuns(rows=>({...rows,[identity]:pending}));if(generation!==undefined)controlGenerations.current[identity]=generation;refreshRuns();}} onError={setError}/>}</div>;
}


