import {FormEvent, useEffect, useRef, useState} from 'react';
import {MetricCursor, sameCursor} from './useStatisticsReader';
import {CohortRead} from './useCohortReader';
import {TimeValue} from './TimeValue';
import {timeLabel} from './timeFormat';

type Obj=Record<string,any>;
type Draft={name:string;mode:string;type:string;status:string;role:string;model:string;region:string;includeDead:boolean};
const example:Draft={name:'All humans',mode:'fixed',type:'Human',status:'',role:'',model:'',region:'',includeDead:true};
const source=(cursor:{time:string;revision:string})=>`${timeLabel(cursor.time)} s · revision ${cursor.revision}`;
const sourceView=(cursor:{time:string;revision:string})=><><TimeValue value={cursor.time}/> · revision {cursor.revision}</>;
const reference=(definition:Obj)=>definition.reference_time==null?`Time unavailable · revision ${definition.reference_revision}`:sourceView({time:String(definition.reference_time),revision:String(definition.reference_revision)});
const number=(value:number)=>value.toLocaleString(undefined,{maximumFractionDigits:2});
function parsedDraft(draft:Draft){
  const errors:Record<string,string>={};
  const predicate:Obj={};
  if(!draft.name.trim())errors.name='Enter a name for this cohort.';
  if(draft.type)predicate.type=draft.type;
  if(draft.status)predicate.status=draft.status;
  if(draft.role)predicate.role=draft.role==='NONE'?null:draft.role;
  if(draft.model.trim())predicate.model_assignment=draft.model.trim();
  if(draft.region.trim()){
    const parts=draft.region.split(',').map(part=>part.trim());
    const region=parts.map(Number);
    if(parts.length!==4||parts.some(part=>!part)||region.some(value=>!Number.isFinite(value)))errors.region='Enter four finite coordinates: xmin, ymin, xmax, ymax.';
    else if(region[0]>region[2]||region[1]>region[3])errors.region='The minimum coordinates must not exceed the maximum coordinates.';
    else predicate.region=region;
  }
  return {errors,predicate};
}
function filters(definition:Obj){
  const predicate=definition.predicate||{};
  return [predicate.type||'Any type',predicate.status||'Any status',
    Object.hasOwn(predicate,'role')?(predicate.role===null?'No active role':predicate.role):'Any role',
    predicate.model_assignment?`Model ${predicate.model_assignment}`:'Any model',
    predicate.region?`Region [${predicate.region.join(', ')}]`:'Whole world'].join(' · ');
}

export default function CohortPanel({read,selected,waitingForView,onRetry,onCreate,onExport,colors}:{
  read:CohortRead;selected:MetricCursor;waitingForView:boolean;onRetry:()=>void;
  onCreate:(definition:Obj,signal:AbortSignal)=>Promise<Obj>;onExport:(cohort:Obj,cursor:MetricCursor)=>void;colors:Record<string,string>;
}) {
  const [draft,setDraft]=useState<Draft>({...example});
  const [fieldErrors,setFieldErrors]=useState<Record<string,string>>({});
  const [error,setError]=useState('');
  const [pending,setPending]=useState(false);
  const [filtersOpen,setFiltersOpen]=useState(false);
  const [created,setCreated]=useState<Obj>();
  const active=useRef(true),busy=useRef(false),creation=useRef<AbortController|undefined>(undefined);
  useEffect(()=>{active.current=true;return()=>{active.current=false;creation.current?.abort();};},[]);
  const edit=<K extends keyof Draft>(key:K,value:Draft[K])=>{setDraft(old=>({...old,[key]:value}));setFieldErrors(old=>({...old,[key]:''}));setError('');};
  const reset=(allHumans:boolean)=>{setDraft(old=>allHumans?{...example}:{...old,type:'',status:'',role:'',model:'',region:'',includeDead:true});setFieldErrors({});setError('');setCreated(undefined);};
  const submit=async(event:FormEvent)=>{
    event.preventDefault();if(busy.current||waitingForView)return;
    const {errors,predicate}=parsedDraft(draft);setFieldErrors(errors);setError('');
    if(Object.keys(errors).length){if(errors.region)setFiltersOpen(true);setError('Check the highlighted fields. Your entries have been kept.');return;}
    const reference={...selected};const controller=new AbortController();creation.current=controller;
    busy.current=true;setPending(true);setCreated(undefined);
    try{
      const saved=await onCreate({name:draft.name.trim(),mode:draft.mode,predicate,include_dead:draft.includeDead,
        reference_time:reference.time,reference_revision:reference.revision},controller.signal);
      if(!active.current||controller.signal.aborted)return;
      setCreated(saved);onRetry();
    }catch(error:any){if(active.current&&!controller.signal.aborted)setError(error.message||'The cohort could not be created. Your entries have been kept.');}
    finally{if(active.current){busy.current=false;setPending(false);}if(creation.current===controller)creation.current=undefined;}
  };
  const data=read.data;
  const cohorts=data?.cohorts||[];
  // Export the cursor delivered with these measurements, even while a newer
  // viewer cursor is loading or has failed. Never borrow the selected cursor.
  const exportCursor=data?{run_id:data.run_id,time:String(data.cursor.time),revision:String(data.cursor.revision)}:undefined;
  const stale=waitingForView||!sameCursor(read.cursor,selected);
  const measured=read.cursor?source(read.cursor):'not loaded';
  return <div className="cohort-panel" aria-busy={pending||read.phase==='loading'||read.phase==='refreshing'}>
    <h2>Study groups of agents</h2>
    <p>A cohort is a named group you can follow through recorded history. Fixed cohorts keep the chosen identities; dynamic cohorts reapply their filters at each displayed cursor. Cohorts may overlap.</p>
    <span className={`tag ${stale?'statistics-stale':''}`} data-testid="cohorts-cursor" data-exact-time={read.cursor?.time} data-revision={read.cursor?.revision}>{read.cursor?<>Cohorts through {sourceView(read.cursor)}{stale?' · selected view differs':''}</>:'Cohorts not loaded yet'}</span>
    <button className="cohort-refresh" data-testid="cohorts-refresh" disabled={read.phase==='loading'||read.phase==='refreshing'||waitingForView} onClick={onRetry} title="Read saved definitions, including changes made in another browser.">Refresh Cohorts</button>
    <div className={`statistics-status ${read.phase==='failed'?'statistics-error':''}`} data-testid="cohorts-status" role={read.phase==='failed'?'alert':'status'}>
      {read.phase==='failed'?<><span>Could not refresh Cohorts. {read.error}{read.data&&` Showing the last verified collection through ${measured}.`}</span><button data-testid="cohorts-retry" onClick={onRetry}>Retry Cohorts</button></>
        :waitingForView?<span>Waiting for the selected history view. {read.data&&`Last verified collection: ${measured}.`}</span>
        :read.phase==='idle'||read.phase==='loading'?<span>Loading Cohorts for the selected time and revision…</span>
        :read.phase==='refreshing'||stale?<span>Refreshing Cohorts. {read.data&&`Showing the last verified collection through ${measured}.`}</span>
        :!cohorts.length?<span>No cohorts have been created for this run. Start with the All humans example below.</span>
        :<span>{cohorts.length} cohort{cohorts.length===1?'':'s'} measured through {measured}.</span>}
    </div>
    <form className="cohort-create" onSubmit={submit} noValidate>
      <fieldset disabled={pending||waitingForView}>
        <legend>Create a cohort</legend>
        <p className="cohort-help">1. Choose a reference time with the main replay controls, or keep the live view. 2. Name and filter the group. 3. Create it and inspect its members below.</p>
        <p data-testid="cohort-create-reference">Reference for this submission: <strong>{sourceView(selected)}</strong>. The displayed cursor is captured when you choose Create cohort.</p>
        <div className="cohort-presets"><button type="button" data-testid="cohort-example-humans" onClick={()=>reset(true)}>Use All humans example</button><button type="button" data-testid="cohort-clear-filters" onClick={()=>reset(false)}>Clear all filters</button></div>
        <div className="cohort-form">
          <label>Name<input data-testid="cohort-name" value={draft.name} aria-invalid={Boolean(fieldErrors.name)} aria-describedby={fieldErrors.name?'cohort-name-error':undefined} onChange={event=>edit('name',event.target.value)}/>{fieldErrors.name&&<span className="config-field-error" id="cohort-name-error">{fieldErrors.name}</span>}</label>
          <label>Membership<select data-testid="cohort-mode" value={draft.mode} onChange={event=>edit('mode',event.target.value)}><option value="fixed">Fixed identities</option><option value="dynamic">Dynamic filters</option></select></label>
          <label>Type<select data-testid="cohort-type" value={draft.type} onChange={event=>edit('type',event.target.value)}><option value="">Any type</option><option>Human</option><option>Zombie</option></select></label>
          <label>Status predicate<select data-testid="cohort-status" value={draft.status} onChange={event=>edit('status',event.target.value)}><option value="">Any status</option>{['INFECTED','HEALTHY','ACTIVE','DEAD'].map(status=><option key={status}>{status}</option>)}</select></label>
        </div>
        <label className="check cohort-dead-option"><input type="checkbox" data-testid="cohort-include-dead" checked={draft.includeDead} onChange={event=>edit('includeDead',event.target.checked)}/>{draft.mode==='fixed'?'Include already-dead identities when choosing the initial members':'Include dead identities when evaluating the filters'}</label>
        <p className="cohort-help">{draft.mode==='fixed'?'Fixed membership is captured once at the reference cursor. Those IDs remain members after conversion or death, regardless of their later type or status.':'Dynamic membership is recomputed at the measurement cursor. A Human-filtered identity leaves after conversion; dead identities can be excluded by this checkbox or by a status filter.'}</p>
        <details open={filtersOpen} onToggle={event=>setFiltersOpen(event.currentTarget.open)}><summary>Optional role, model or region filters</summary><div className="cohort-form">
          <label>Role<select data-testid="cohort-role" value={draft.role} onChange={event=>edit('role',event.target.value)}><option value="">Any role</option><option value="NONE">No active role</option>{['DOCTOR','WARRIOR','SCOUT','ENGINEER','TYRANT','RUNNER','SPITTER','SCREAMER'].map(role=><option key={role}>{role}</option>)}</select></label>
          <label>Model ID<input data-testid="cohort-model" value={draft.model} onChange={event=>edit('model',event.target.value)} placeholder="Any model"/></label>
          <label>Region · xmin, ymin, xmax, ymax (m)<input data-testid="cohort-region" value={draft.region} onChange={event=>edit('region',event.target.value)} placeholder="Whole world" aria-invalid={Boolean(fieldErrors.region)} aria-describedby={fieldErrors.region?'cohort-region-error':undefined}/>{fieldErrors.region&&<span className="config-field-error" id="cohort-region-error">{fieldErrors.region}</span>}</label>
        </div></details>
        <p className="cohort-help">The small preset starts with no infected humans. An INFECTED filter can therefore produce a valid cohort with 0 members. Clear filters or use All humans to try a populated group.</p>
        <button type="submit" data-testid="cohort-save" className="primary">{pending?'Creating cohort…':'Create cohort'}</button>
      </fieldset>
      {error&&<p role="alert" className="cohort-form-error" data-testid="cohort-form-error">{error}</p>}
      {created&&<p role="status" className="cohort-created" data-testid="cohort-created">Created “{created.name}” at {reference(created)}. {cohorts.some(cohort=>cohort.definition.id===created.id)?'Its card is highlighted below.':'Its card will appear when the collection refresh succeeds.'}</p>}
    </form>
    <div className="cohort-grid">{cohorts.map(cohort=>{
      const definition=cohort.definition;
      return <article className={`cohort-card ${definition.id===created?.id?'cohort-card-created':''}`} key={definition.id} data-testid="cohort-card" data-cohort-id={definition.id}>
        <span className="tag">{definition.mode==='fixed'?'Fixed identities':'Dynamic filters'}</span><h3>{definition.name||'Unnamed cohort'}</h3>
        <p data-testid="cohort-reference">Reference: {reference(definition)}</p>
        <p data-testid="cohort-measurement">Measured through {read.cursor?sourceView(read.cursor):'not loaded'}{stale?' · stale for the selected view':''}</p>
        <p className="cohort-predicate">{filters(definition)}</p>
        <p>{definition.mode==='fixed'?(definition.include_dead===false?'Initially excluded already-dead identities; later deaths stay in this fixed group.':'Included matching dead identities at the reference cursor; later deaths stay in this fixed group.'):(definition.include_dead===false?'Dead identities excluded from current membership.':'Matching dead identities included in current membership.')}</p>
        <strong className="cohort-number" data-testid="cohort-count">{cohort.denominator}</strong><p>member identities{cohort.present!==cohort.denominator&&` · ${cohort.present} present at this cursor`}</p>
        {cohort.denominator===0&&<p className="cohort-empty" data-testid="cohort-empty">0 members is a valid result. No identities match this group's membership rule at its selection cursor. Review the filters above; this is not a loading failure.</p>}
        <div className="cohort-bars">{Object.keys(colors).map(key=><span key={key} style={{background:colors[key],width:`${100*cohort.populations[key]/Math.max(1,cohort.denominator)}%`}} title={`${key}: ${cohort.populations[key]}`}/>)}</div>
        <p data-testid="cohort-populations">{cohort.populations.healthy} healthy · {cohort.populations.infected} infected · {cohort.populations.zombies} zombies · {cohort.populations.dead} dead</p>
        <p data-testid="cohort-mean-life" data-denominator={cohort.mean_life_denominator}>Mean life <strong>{cohort.mean_life_denominator?number(cohort.mean_life):'—'}</strong> · denominator {cohort.mean_life_denominator}</p>
        <p data-testid="cohort-mean-stamina" data-denominator={cohort.mean_stamina_denominator}>Mean stamina <strong>{cohort.mean_stamina_denominator?number(cohort.mean_stamina):'—'}</strong> · denominator {cohort.mean_stamina_denominator}</p>
        {cohort.human_survival&&<div className="cohort-survival" data-testid="cohort-human-survival"><h4>Human survival</h4><p>{cohort.human_survival.eligible} eligible at entry · {cohort.human_survival.events} events · {cohort.human_survival.censored} right-censored</p><p>{cohort.human_survival.excluded_non_human} initially non-Human identities excluded · {cohort.human_survival.excluded_unknown_entry} without a known entry state · {cohort.human_survival.excluded_dead_at_entry} dead at entry excluded</p><p data-testid="cohort-human-entry">Entry source run <code>{cohort.human_survival.entry_run_id}</code> · <TimeValue value={cohort.human_survival.entry_time}/> · revision {cohort.human_survival.entry_revision}</p><small>Death or conversion ends Human survival; surviving Humans are right-censored at this measurement cursor.</small></div>}
        {cohort.identity_survival&&<div className="cohort-survival" data-testid="cohort-identity-survival"><h4>Identity survival</h4><p>{cohort.identity_survival.eligible} eligible at entry · {cohort.identity_survival.events} deaths · {cohort.identity_survival.censored} right-censored</p><p>{cohort.identity_survival.excluded_dead_at_entry} dead at entry excluded · {cohort.identity_survival.excluded_unknown_entry} without a known entry state</p><p data-testid="cohort-identity-entry">Entry source run <code>{cohort.identity_survival.entry_run_id}</code> · <TimeValue value={cohort.identity_survival.entry_time}/> · revision {cohort.identity_survival.entry_revision}</p><small>Conversion preserves an identity.</small></div>}
        <details><summary>Member IDs ({cohort.members.length}) and definition</summary><div className="cohort-member-list" data-testid="cohort-members">{cohort.members.length?cohort.members.map((identity:string)=><code key={identity}>{identity}</code>):<span>No member IDs.</span>}</div><pre>{JSON.stringify(definition,null,2)}</pre></details>
        <button disabled={!exportCursor} onClick={()=>{if(exportCursor)onExport(cohort,exportCursor);}}>Export cohort</button><p className="cohort-help" data-testid="cohort-export-source">Exports the displayed measurements through {exportCursor?sourceView(exportCursor):'not loaded'}{stale?', including this older source cursor':''}.</p>
      </article>;
    })}</div>
    <p className="cohort-help">Creating a cohort saves an analysis definition. It does not change the simulation or its decisions. Averages use the number of member identities present at the measurement cursor; an empty denominator has no defined mean.</p>
  </div>;
}
