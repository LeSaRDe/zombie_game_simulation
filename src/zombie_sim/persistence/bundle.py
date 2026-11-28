"""Compatible live, journal, query and checkpoint adapters for one run."""
from __future__ import annotations
from dataclasses import dataclass
from .contracts import CommitBundle, CommitOutcomeUnknown, AtomicCommitPort, HistoryQueryPort, LiveStatePort, CheckpointPort


class AtomicCommitAdapter:
    def __init__(self, store):self.store=store;self.history=store.history
    def commit(self,bundle:CommitBundle,expected_revision:int,transaction_id:str):
        if not isinstance(transaction_id,str) or not transaction_id:raise ValueError('A transaction identity is required')
        try:
            self.store.commit_delta(bundle.world_delta,expected_version=expected_revision,records=bundle.events,
                transaction_id=transaction_id,runtime_delta=bundle.runtime_delta,command_result=bundle.command_result)
        except BaseException as exc:
            # A post-commit publication error cannot be treated as a rollback.
            try:result=self.history.transaction_result(transaction_id)
            except Exception:raise CommitOutcomeUnknown(transaction_id) from exc
            if result is not None:
                from .contracts import TransactionMismatch
                if isinstance(exc,TransactionMismatch):raise
                raise CommitOutcomeUnknown(transaction_id) from exc
            raise
        try:
            result = self.history.transaction_result(transaction_id)
        except Exception as exc:
            raise CommitOutcomeUnknown(transaction_id) from exc
        if result is None:
            raise CommitOutcomeUnknown(transaction_id)
        return result
    def resolve_transaction(self,transaction_id):
        result=self.history.transaction_result(transaction_id)
        if result is not None and self.store.version!=self.history.revision:
            # Repair process-local projection after a durable commit whose
            # publication was interrupted. The ledger remains authoritative.
            from copy import deepcopy
            with self.store.lock:
                state=self.history.state_at()
                self.store._state=deepcopy(state)
                self.store.version=self.history.revision
                self.history._state=state
                self.history._runtime_state=self.history.runtime_at()
        return result


@dataclass
class PersistenceBundle:
    store: LiveStatePort
    history: HistoryQueryPort
    atomic: AtomicCommitPort
    checkpoints: CheckpointPort
    backend: str
    durable: bool=True
    _closed: bool=False
    def close(self):
        if not self._closed:self.store.close();self._closed=True


class PersistenceBundleFactory:
    def create(self,initial,path,backend='memory'):
        from ..storage import History,MemoryStore,SQLiteStore
        from .checkpoint import CheckpointAdapter
        if backend=='contract-memory':
            from .memory import InMemoryHistory
            history=InMemoryHistory(initial);store=MemoryStore(initial,history=history)
        elif backend=='memory':
            history=History(path,initial=initial);store=MemoryStore(initial,history=history)
        elif backend=='sqlite':
            store=SQLiteStore(path,initial=initial);history=store.history
        else:raise ValueError('Unknown persistence backend: '+str(backend))
        return PersistenceBundle(store,history,AtomicCommitAdapter(store),CheckpointAdapter(history),backend,backend!='contract-memory')
    def restore(self,path,backend='memory',initial=None):
        if backend=='contract-memory':raise ValueError('contract-memory cannot recover a discarded nondurable journal')
        return self.create(initial,path,backend)
    def export_prefix(self,source,destination,revision,state):
        """Copy a durable source through this factory's coordinated adapters."""
        from .checkpoint import CheckpointAdapter
        reader=self.open_history(source,read_only=True)
        try:return CheckpointAdapter(reader).export_prefix(destination,revision,state)
        finally:reader.close()
    def open_history(self,path,*,read_only=True):
        from ..storage import History
        if isinstance(path,dict):
            if path.get("schema")!="zombie-sim/history-reference-v1":raise ValueError("Unsupported history reference")
            if path.get("backend")=="contract-memory":
                from .memory import InMemoryHistory
                return InMemoryHistory.from_reference(path,read_only=read_only)
            if path.get("backend")!="sqlite":raise ValueError("Unsupported history backend")
            path=path["path"]
        return History(path,read_only=read_only)


def create_bundle(initial,path,backend='memory'):
    return PersistenceBundleFactory().create(initial,path,backend)
