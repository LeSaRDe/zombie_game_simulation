import {MetricCursor, sameCursor} from './useStatisticsReader';
import {EventRead} from './useEventsReader';

type Obj=Record<string,any>;
const source=(cursor:MetricCursor)=>`${cursor.time} s · revision ${cursor.revision}`;
function rowTime(value:string):string {
  try{
    const fraction=/^(-?\d+)\/(\d+)$/.exec(value);
    let numerator:bigint,denominator:bigint;
    if(fraction){numerator=BigInt(fraction[1]);denominator=BigInt(fraction[2]);}
    else{
      const decimal=/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
      if(!decimal)return value;
      const exponent=Number(decimal[4]||0)-(decimal[3]||'').length;
      if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>10000)return value;
      numerator=BigInt((decimal[1]==='-'?'-':'')+decimal[2]+(decimal[3]||''));
      denominator=exponent<0?10n**BigInt(-exponent):1n;
      if(exponent>0)numerator*=10n**BigInt(exponent);
    }
    if(denominator===0n)return value;
    const magnitude=numerator<0n?-numerator:numerator;
    const scaled=magnitude*1000n;
    const rounded=(scaled*2n+denominator)/(denominator*2n);
    const decimals=String(rounded%1000n).padStart(3,'0').replace(/0+$/,'');
    const label=`${numerator<0n&&rounded>0n?'-':''}${rounded/1000n}${decimals?'.'+decimals:''}`;
    return `${scaled%denominator===0n?'':'≈'}${label}`;
  }catch{return value;}
}
export default function EventsPanel({read,selected,mode,following,queryKey,waitingForView,agent,search,onSearch,onClearAgent,onRetry,onLatest,onOlder,onNewer,onSelect}:{
  read:EventRead;selected:MetricCursor;mode:'live'|'replay';following:boolean;queryKey:string;waitingForView:boolean;agent:string;search:string;
  onSearch:(text:string)=>void;onClearAgent:()=>void;onRetry:()=>void;onLatest:()=>void;onOlder:()=>void;onNewer:()=>void;onSelect:(event:Obj,cursor:MetricCursor)=>void;
}) {
  const records=read.data?.records||[];
  const shown=records.filter(record=>JSON.stringify(record).toLowerCase().includes(search.toLowerCase()));
  const currentPage=read.queryKey===queryKey;
  const stale=waitingForView||!currentPage||(following&&!sameCursor(read.cursor,selected));
  const busy=read.phase==='loading'||read.phase==='refreshing'||waitingForView;
  const measured=read.cursor?source(read.cursor):'not loaded';
  const navigable=read.phase==='ready'&&currentPage&&!waitingForView;
  return <div className="timeline-panel" aria-busy={busy}>
    <h2>Event & causal timeline</h2>
    <p className="events-help">Inspect recorded events in ascending commit sequence. Each page contains at most 500 records. Row times marked ≈ are rounded to three decimal places; hover or select a record for its exact time and causal transition.</p>
    <span data-testid="events-cursor" className={`tag ${stale?'statistics-stale':''}`}>{read.cursor?`Events through ${measured}${stale?' · previous verified results':''}`:'Events not loaded yet'}</span>
    <div className="events-navigation">
      <button data-testid="events-older" disabled={!navigable||!read.data?.page.has_older} onClick={onOlder}>Older</button>
      <button data-testid="events-newer" disabled={!navigable||!read.data?.page.has_newer} onClick={onNewer}>Newer</button>
      <button data-testid="events-latest" disabled={waitingForView} onClick={onLatest}>Show latest events</button>
      <button data-testid="events-refresh" disabled={busy} onClick={onRetry}>Refresh Events</button>
    </div>
    <p className="events-help" data-testid="events-browsing-mode">{following
      ?mode==='live'?'Following the latest verified events in the live view.':'Showing the latest events through the selected replay cursor; later history is excluded.'
      :`Browsing pages pinned to ${measured}. New events do not shift these pages. Show latest events returns to the selected ${mode==='live'?'live':'replay'} cursor.`}</p>
    <div className="event-filters">
      <label>Search the loaded page<input data-testid="timeline-filter" value={search} onChange={event=>onSearch(event.target.value)} placeholder="Action, outcome, actor or event text…"/></label>
      <button data-testid="events-clear-search" disabled={!search} onClick={()=>onSearch('')}>Clear search</button>
      {agent&&<button data-testid="events-clear-agent" onClick={onClearAgent}>Clear identity #{agent} filter</button>}
    </div>
    <p className="events-help" data-testid="events-identity-filter">{agent?`Identity #${agent} is filtered before selecting a page, including actor, target and occurrence-linked records.`:'All identities. Select an agent in World to inspect its related events.'} Text search only filters the loaded page; browse other pages to inspect more history.</p>
    <div className={`statistics-status ${read.phase==='failed'?'statistics-error':''}`} data-testid="events-status" role={read.phase==='failed'?'alert':'status'}>
      {read.phase==='failed'?<><span>Could not refresh Events. {read.error}{read.data&&` Showing the last verified page through ${measured}.`}</span><button data-testid="events-retry" onClick={onRetry}>Retry Events</button></>
        :waitingForView?<span>Waiting for the selected history view. {read.data&&`Last verified page: ${measured}.`}</span>
        :read.phase==='idle'||read.phase==='loading'?<span>Loading Events for the requested cursor and page…</span>
        :read.phase==='refreshing'||stale?<span>Refreshing Events. {read.data&&`Showing the previous verified page through ${measured}.`}</span>
        :!records.length?<span>{agent?`No recorded events match identity #${agent} through this cursor. Clear the identity filter to see all identities.`:'No events were recorded in this page through the selected cursor.'}</span>
        :!shown.length?<span>No records in this loaded page match the search. Clear search or browse another page; this is not a loading failure.</span>
        :<span>Verified events through {measured}. Selecting an event changes the inspection cursor, not simulation execution.</span>}
    </div>
    <p className="events-counts" data-testid="events-counts">{shown.length} matching records · {records.length} loaded{read.data?.page.first_sequence&&` · sequences ${read.data.page.first_sequence}–${read.data.page.last_sequence}`} · ascending durable commit sequence</p>
    <div className="event-list">{shown.map(record=><button data-testid="timeline-first-event" data-event-sequence={record.ledger_sequence} className="event-row" key={record.ledger_sequence} disabled={!read.cursor} onClick={()=>read.cursor&&onSelect(record,read.cursor)}>
      <span className="event-time" data-exact-time={String(record.time??0)} title={`Exact time: ${String(record.time??0)} s`}><span data-testid="event-time-label" aria-hidden="true">{rowTime(String(record.time??0))} s</span><span className="sr-only">Exact time {String(record.time??0)} seconds.</span><small>r{record.ledger_revision} · sequence {record.ledger_sequence} · phase {record.phase??'—'}</small></span>
      <span><strong>{record.kind||record.type||'event'}</strong><small>{(record.actor??record.agent_id??record.agent)!=null&&`Actor #${record.actor??record.agent_id??record.agent}`}{(record.target??record.target_id)!=null&&` → #${record.target??record.target_id}`} {record.action||''}</small><small>Inspect this recorded event</small></span>
      <span className="tag">{record.outcome||record.reason||'recorded'}</span>
    </button>)}</div>
  </div>;
}
