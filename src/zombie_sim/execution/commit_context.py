"""Staged continuation data supplied to the runtime codec, without a live store."""
from ..state_management import install_runtime_fields

@install_runtime_fields
class CommitContext:
    def __init__(self, simulation, plan, world):
        self._runtime_state = plan.runtime.fork()
        self.world_view = world.read_view()
        self._runtime_queue_delta = list(plan.queue_delta)
        self._runtime_config_marker = getattr(simulation, '_runtime_config_marker', None)
        self._runtime_committed_memories = getattr(simulation, '_runtime_committed_memories', {})
        self._runtime_journal_schema = getattr(simulation, '_runtime_journal_schema', None)
        self._runtime_implementation_manifest = getattr(simulation, '_runtime_implementation_manifest', None)

    @property
    def state(self): return self.world_view
