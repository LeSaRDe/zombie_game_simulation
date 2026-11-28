"""Keep scheduler preparation reversible until its rule transaction publishes."""
from copy import copy


class ScheduledBoundary:
    """Own a small speculative runtime shell around one scheduled transaction.

    The scheduler edits its heap and decision set in place. Other preparation
    fields are replaced; policy memories are copied before invoking a model,
    and game rules already own a fully isolated RuntimeSnapshot workspace.
    Copying just these scheduler containers avoids copying every private model
    memory at every completion while retaining the previous runtime owner.
    """

    def __init__(self, simulation):
        self.simulation = simulation

    def __enter__(self):
        sim = self.simulation
        self.previous = sim._runtime_state
        self.queue_delta = sim._runtime_queue_delta
        self.prepared_agents = getattr(sim, '_runtime_prepared_agents', {})
        staged = copy(self.previous)
        staged.queue = list(self.previous.queue)
        staged._decision_due = set(self.previous._decision_due)
        staged._present = set(self.previous._present)
        sim._runtime_state = staged
        sim._runtime_queue_delta = list(self.queue_delta)
        return self

    def __exit__(self, error_type, error, traceback):
        sim = self.simulation
        # An uncertain receipt can resolve to a successful durable commit. The
        # coordinator's published revision, not an exception alone, decides.
        if error_type is not None and sim.state_coordinator.current_world.revision == self.previous.revision:
            status, reason = sim.run_status, sim.termination_reason
            sim._runtime_state = self.previous
            sim._runtime_queue_delta = self.queue_delta
            sim._runtime_prepared_agents = self.prepared_agents
            sim.__dict__.pop('_runtime_projection', None)
            if status == 'FAILED':
                sim.run_status, sim.termination_reason = status, reason
        return False
