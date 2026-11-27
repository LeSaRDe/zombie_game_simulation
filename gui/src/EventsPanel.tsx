import {MetricCursor, sameCursor} from './useStatisticsReader';
import {EventRead} from './useEventsReader';
import {TimeValue} from './TimeValue';
import {timeLabel} from './timeFormat';

type Obj=Record<string,any>;
const source=(cursor:MetricCursor)=>`${timeLabel(cursor.time)} s · revision ${cursor.revision}`;
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
    <p className="events-help">Inspect recorded events in ascending commit sequence. Each page contains at most 500 records. Times marked ≈ are rounded for display. Ordinary times use up to three decimal places; very small or large times use scientific notation. Select a record for its exact time and causal transition.</p>
    <span data-testid="events-cursor" data-exact-time={read.cursor?.time} data-revision={read.cursor?.revision} className={`tag ${stale?'statistics-stale':''}`}>{read.cursor?<>Events through <TimeValue value={read.cursor.time}/> · revision {read.cursor.revision}{stale?' · previous verified results':''}</>:'Events not loaded yet'}</span>
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
      <span className="event-time" data-exact-time={String(record.time??0)} title={`Exact time: ${String(record.time??0)} s`}><span data-testid="event-time-label" aria-hidden="true">{timeLabel(record.time)} s</span><span className="sr-only">Time {timeLabel(record.time).replace("≈","approximately ")} seconds. Select for the exact time.</span><small>r{record.ledger_revision} · sequence {record.ledger_sequence} · phase {record.phase??'—'}</small></span>
      <span><strong>{record.kind||record.type||'event'}</strong><small>{(record.actor??record.agent_id??record.agent)!=null&&`Actor #${record.actor??record.agent_id??record.agent}`}{(record.target??record.target_id)!=null&&` → #${record.target??record.target_id}`} {record.action||''}</small><small>Inspect this recorded event</small></span>
      <span className="tag">{record.outcome||record.reason||'recorded'}</span>
    </button>)}</div>
  </div>;
}
