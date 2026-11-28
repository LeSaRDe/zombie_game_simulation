import {Obj,ViewerLoad} from '../uiRuntime';
import {TimeValue} from '../TimeValue';
export default function ViewerLoadPanel({state,run,hasView,onCancel,onRetry,onReturn}:{state:ViewerLoad;run?:Obj;hasView:boolean;onCancel:()=>void;onRetry:()=>void;onReturn:()=>void}){
  if(state.phase==='idle'||state.phase==='ready')return null;
  const failed=state.phase==='failed';const initializing=state.phase==='initializing';
  const hasBoundary=run?.frontier?.time!=null&&run?.frontier?.revision!=null;
  return <section className={`viewer-load panel ${hasView?'viewer-load-compact':''}`} data-testid={failed?'viewer-error':'viewer-loading'} aria-live="polite" aria-busy={!failed}>
    <span className="eyebrow">{failed?'VIEWER ERROR':initializing?'RUN INITIALIZATION':'HISTORY VIEWER'}</span>
    <h2>{failed?'Could not load this view':initializing?'Initializing the world…':state.details?'Loading run information…':'Loading recorded history…'}</h2>
    {failed?<p role="alert">{state.error||'The requested view is unavailable.'}</p>:initializing?<p>The service is initializing this run, including its geometry and population.</p>:<p>{state.details?'Waiting for the service to report this run.':'Reading the selected run’s recorded state. Large histories can take longer to open.'}</p>}
    <p className="viewer-run-reference">{run?.config.scenario||'Selected run'} · <code>{state.run_id}</code>{hasBoundary&&<> · committed <TimeValue value={run!.frontier.time}/> · revision {run!.frontier.revision}</>}</p>
    {hasView&&<p>The last loaded view remains below until the requested view is ready.</p>}
    <div className="viewer-load-actions">{failed?<><button data-testid="viewer-retry" className="primary" onClick={onRetry}>Retry loading</button><button data-testid="viewer-return-list" onClick={onReturn}>Return to run list</button></>:<button data-testid="viewer-cancel" onClick={onCancel}>Cancel loading and return to runs</button>}</div>
    {!failed&&<p className="viewer-load-note">Cancelling this viewer does not stop the simulation. Atomic reader work already in progress may finish before cancellation takes effect.</p>}
  </section>;
}

