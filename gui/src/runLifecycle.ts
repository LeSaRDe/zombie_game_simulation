type Run = Record<string, any>;

const inactiveStatuses = new Set(['stopped', 'completed', 'terminated', 'failed', 'interrupted']);

export function isInactiveRun(run?: Run): boolean {
  return inactiveStatuses.has(run?.status);
}

export function cleanupConfirmed(run?: Run): boolean {
  return run?.resource_status?.cleanup_complete === true && run.resource_status.worker_active === false;
}

export function lifecycleLabel(run?: Run, terminationRequested = false): string {
  if (!run) return 'Ready';
  if (terminationRequested || run.resource_status?.phase === 'termination_requested') return 'Termination requested';
  if (run.resource_status?.phase === 'stopping' || (isInactiveRun(run) && run.resource_status?.worker_active === true)) return 'Stopping / cleanup';
  if (isInactiveRun(run) && !cleanupConfirmed(run)) {
    return `${run.status === 'terminated' ? 'Termination acknowledged' : run.status} · cleanup unverified`;
  }
  return run.status;
}

export function runGroup(run: Run, terminationRequested = false): 'active' | 'saved' | 'terminated' {
  if (terminationRequested || ['termination_requested', 'stopping'].includes(run.resource_status?.phase) || run.resource_status?.worker_active === true) return 'active';
  if (run.status === 'terminated') return 'terminated';
  return isInactiveRun(run) ? 'saved' : 'active';
}

export function terminationNotice(run?: Run, terminationRequested = false): string {
  const label = lifecycleLabel(run, terminationRequested);
  if (label === 'Termination requested') return 'Termination requested. Waiting for the next committed boundary; an already-running checkpoint may finish before termination takes effect.';
  if (run?.status !== 'terminated') return '';
  if (cleanupConfirmed(run)) return 'Worker cleanup complete. Terminated without a new checkpoint. Existing checkpoints and committed audit history are retained for replay and inspection.';
  if (label === 'Stopping / cleanup') return 'Simulation stopped at a committed boundary. Worker cleanup is still pending. Existing audit history is retained.';
  return 'Termination acknowledged. Cleanup is not yet confirmed. Existing audit history is retained.';
}
