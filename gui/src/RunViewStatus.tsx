import {TimeValue} from './TimeValue';
import {lifecycleLabel} from './runLifecycle';
import './runViewStatus.css';

type Run = Record<string, any>;
export type StatusFreshness = 'current' | 'last-confirmed' | 'unavailable';

// Age the request from when it began: a delayed response is not a fresh
// observation of execution merely because it has just arrived in the browser.
export function statusFreshness(run: Run | undefined, phase: string, now: number): StatusFreshness {
  if (!run || run.status_read_started_at === undefined) return 'unavailable';
  return phase === 'failed' || now - run.status_read_started_at >= 5000 ? 'last-confirmed' : 'current';
}

export function confirmedStatusLabel(run: Run | undefined, freshness: StatusFreshness, requested = false): string {
  if (!run) return 'Status unavailable';
  const label = lifecycleLabel(run, requested);
  return freshness === 'current' ? label : `Last confirmed: ${label}`;
}

function executionMessage(run: Run | undefined, freshness: StatusFreshness, requested: boolean): string {
  if (freshness !== 'current') {
    return run ? `Current simulation status is unavailable. Last confirmed: ${lifecycleLabel(run, requested)}.`
      : 'Current simulation status is unavailable.';
  }
  const label = lifecycleLabel(run, requested);
  if (label === 'Termination requested') return 'Termination has been requested; waiting for acknowledgement and worker cleanup.';
  if (label === 'Stopping / cleanup') return 'The simulation is stopping; worker cleanup is not yet confirmed.';
  if (label !== run?.status) return `Simulation status: ${label}.`;
  if (run?.status === 'running') return 'The simulation is still running.';
  if (run?.status === 'initializing') return 'The simulation is initializing.';
  return `The simulation is ${run?.status || 'unavailable'}.`;
}

export default function RunViewStatus({run, freshness, requested, mode, cursor, waiting, onLive}: {
  run?: Run; freshness: StatusFreshness; requested: boolean;
  mode: 'live' | 'replay' | 'observation'; cursor?: {time: string; revision: string};
  waiting: boolean; onLive: () => void;
}) {
  const label = confirmedStatusLabel(run, freshness, requested);
  const viewing = mode === 'replay' ? 'Viewing recorded history'
    : mode === 'observation' ? 'Viewing recorded agent observation' : 'Viewing live follow';
  return <section className="execution-view-status" aria-label="Simulation execution and displayed history">
    <div className="status-readouts">
      <div className="status-readout" data-testid="simulation-status" data-status={run?.status || 'unavailable'}
        data-freshness={freshness} data-time={run?.frontier?.time} data-revision={run?.frontier?.revision}>
        <h2>Simulation <span>— {label.charAt(0).toUpperCase() + label.slice(1)}</span></h2>
        {run?.frontier?.time != null ? <p className="status-clock"><strong><TimeValue value={run.frontier.time}/></strong><span>revision {run.frontier.revision}</span></p>
          : <p>Waiting for execution status.</p>}
        <p className="status-caption">{freshness === 'current' ? 'Latest confirmed execution boundary.'
          : 'Status update delayed or unavailable; these are the last confirmed values.'}</p>
      </div>
      <div className={`status-readout displayed-${mode}`} data-testid="viewer-status" data-mode={mode}
        data-time={cursor?.time} data-revision={cursor?.revision}>
        <h2>{viewing}</h2>
        {cursor ? <p className="status-clock"><strong><TimeValue value={cursor.time}/></strong><span>revision {cursor.revision}</span></p>
          : <p>No recorded view loaded yet.</p>}
        <p className="status-caption">{waiting ? 'Loading the requested view; the last loaded cursor is shown.'
          : mode === 'live' ? 'Follows newly committed history; the viewer may lag execution.'
          : 'The displayed time belongs to this recorded state.'}</p>
      </div>
    </div>
    <p className="time-format-help">≈ marks display rounding. Exact time reveals the recorded value; selections keep their exact time and revision.</p>
    {mode === 'replay' && <div className="history-explanation">
      <div><p role="status" data-testid="replay-status-message">You are viewing recorded history. {executionMessage(run, freshness, requested)}</p>
        <p>History selections and replay playback change the view. Use <strong>Pause run</strong> to pause execution.</p></div>
      <button className="primary" data-testid="replay-return-live" onClick={onLive}>Return to live ↗</button>
    </div>}
  </section>;
}
