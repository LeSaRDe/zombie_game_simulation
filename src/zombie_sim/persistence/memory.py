"""Independent nondurable run journal for contract tests and embedded experiments.

This backend never opens SQLite. It intentionally retains full detached versions;
production `memory` mode continues to use the bounded durable SQLite journal.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from .contracts import CommitResult,TransactionMismatch


class InMemoryHistory:
    def __init__(self, initial=None):
        self.path=None;self.lock=threading.RLock();self.read_only=False
        self._commits=[];self._events=[];self._runtime={};self._metadata={};self._commands={};self._transactions={}
        self._source_token=object();self._checkpoints=[];self._receipts={}
        self._state={};self._runtime_state=None
        if initial is not None:self.append(initial.get('time',0),snapshot=initial,transaction_id='initialize')

    @property
    def revision(self):return len(self._commits)-1

    def append(self,time=0,event=None,delta=None,snapshot=None,transaction_id=None,*,records=(),revision=None,in_transaction=False,runtime_delta=None,command_result=None,request_checksum=None):
        from ..storage import canonical,exact_time,state_diff,stage_patch,_pack,_request_checksum,VersionConflict
        from ..faults import hit
        with self.lock:
            if self.read_only:raise RuntimeError("Cannot append to a read-only history view")
            rows=list(records)+([event] if event is not None else [])
            txid=transaction_id or f'revision:{self.revision+1}'
            checksum=request_checksum or _request_checksum('append',[str(exact_time(time)),event,delta,snapshot],records,runtime_delta,command_result)
            previous=self.transaction_revision(txid,checksum)
            if previous is not None:return previous
            rev=self.revision+1 if revision is None else int(revision)
            if rev!=self.revision+1:raise VersionConflict('History revision conflict')
            at=exact_time(time)
            if self._commits and at<exact_time(self._commits[-1]['time']):raise ValueError('History commit times must be nondecreasing')
            state=deepcopy(snapshot) if snapshot is not None else stage_patch(self._state,delta or [])
            patch=state_diff(self._state,state) if delta is None else deepcopy(delta)
            runtime=stage_patch(self._runtime_state or {},runtime_delta) if runtime_delta is not None else deepcopy(self._runtime_state)
            events=[(len(self._events)+i+1,rev,deepcopy(row)) for i,row in enumerate(rows)]
            commit={'revision':rev,'time':str(at),'state':state,'patch':patch,'checksum':hashlib.sha256(_pack(patch)).hexdigest()}
            hit('history_write',revision=rev);hit('before_history_commit',revision=rev)
            # All publication is protected by the same lock and follows staging.
            self._commits.append(commit);self._events.extend(events);self._state=state;self._runtime_state=runtime
            self._runtime[rev]=deepcopy(runtime);self._transactions[txid]=(checksum,rev)
            self._receipts[txid]=CommitResult(rev,str(at),txid,events[0][0] if events else None,events[-1][0] if events else None,deepcopy(command_result))
            if command_result is not None:self._write_control(command_result,command_result.get('control',{}),rev)
            hit('after_history_commit_before_publish',revision=rev)
            return rev

    def transaction_revision(self,txid,request_checksum=None):
        record=self._transactions.get(txid)
        if record is not None and request_checksum is not None and record[0]!=request_checksum:raise TransactionMismatch('Transaction identity reused with different content')
        return record[1] if record else None

    def transaction_result(self,txid):
        return deepcopy(self._receipts.get(txid))

    def head(self,revision=None):
        from ..storage import exact_time
        selected=self.revision if revision is None else int(revision)
        if not 0<=selected<=self.revision:return None
        at=exact_time(self._commits[selected]['time']);return selected,str(at.numerator),str(at.denominator)

    def origin(self):return self.head(0)
    def boundary(self,revision):
        row=self.head(revision);return row[1:] if row else None
    def cursor_candidates(self,time,revision_cap=None):
        from ..storage import exact_time
        for rev in range(min(self.revision,self.revision if revision_cap is None else int(revision_cap)),-1,-1):
            if exact_time(self._commits[rev]['time'])<=exact_time(time):yield self.head(rev)
    def cursor_at(self,time,revision_cap=None,*,check_cancelled=None):
        if check_cancelled:check_cancelled()
        return next(self.cursor_candidates(time,revision_cap),None)
    def state_at(self,time=None,revision=None,*,check_cancelled=None):
        if check_cancelled:check_cancelled()
        row=self.head(revision) if time is None else self.cursor_at(time,revision,check_cancelled=check_cancelled)
        return deepcopy(self._commits[row[0]]['state']) if row else {}
    def commit_patch(self,revision):
        if not 0<=int(revision)<=self.revision:return None
        row=self._commits[int(revision)];return deepcopy(row['patch']),row['checksum']
    def commit_checksum(self,revision):
        row=self.commit_patch(revision)
        return row[1] if row else None
    def iter_commits(self,after=-1,through=None):
        for rev in range(int(after)+1,min(self.revision,self.revision if through is None else int(through))+1):
            yield (*self.head(rev),*self.commit_patch(rev))
    def verified_anchor(self,revision):return int(revision),self.state_at(revision=revision)
    def source_identity(self):
        from ..storage import exact_time
        if self.revision<0:raise ValueError('History requires a committed initial state')
        return (self._source_token,self._commits[0]['checksum']),exact_time(self._commits[0]['time'])
    def initialize_runtime(self,document,revision=0):
        if self._runtime.get(revision) is None:self._runtime[revision]=deepcopy(document);self._runtime_state=deepcopy(document)
    def runtime_at(self,revision=None):return deepcopy(self._runtime.get(self.revision if revision is None else int(revision)))
    def event_positions(self,kind=None):
        for seq,rev,event in self._events:
            if kind is None or event.get('kind')==kind:yield seq
    def event_range(self,first,last,kind=None):return [deepcopy(event) for seq,rev,event in self._events if first<=seq<=last and (kind is None or event.get('kind')==kind)]
    def last_event_sequence(self):return self._events[-1][0] if self._events else None
    def event_count(self):return len(self._events)
    def event_counts(self,after=-1,through=None):
        from collections import Counter
        end=self.revision if through is None else int(through)
        return dict(Counter(event.get('kind') for seq,rev,event in self._events if after<rev<=end))
    @staticmethod
    def _participants(event):
        result={str(event[k]) for k in ('actor','agent','agent_id','target','target_id') if event.get(k) is not None}
        result.update(map(str,event.get('targets',[])));return result
    def events(self,start=0,end=None,kind=None,agent_id=None,limit=None,latest=False):
        rows=[dict(deepcopy(event),ledger_sequence=str(seq),ledger_revision=str(rev)) for seq,rev,event in self._events if rev>=int(start) and (end is None or rev<=int(end)) and (kind is None or event.get('kind')==kind) and (agent_id is None or str(agent_id) in self._participants(event))]
        return rows[-limit:] if latest and limit is not None else rows[:limit] if limit is not None else rows
    def timeline_records(self,revision,*,agent=None,before=None,after=None,descending=True,limit=None):
        rows=reversed(self._events) if descending else iter(self._events);count=0
        for seq,rev,event in rows:
            if rev>revision or (before is not None and seq>=before) or (after is not None and seq<=after):continue
            yield seq,rev,deepcopy(event),*self.head(rev)[1:],int(agent is not None and str(agent) in self._participants(event))
            count+=1
            if limit is not None and count>=limit:break
    def decision_records_at(self,actor,when):
        from ..storage import exact_time
        return [deepcopy(e) for _,_,e in self._events if e.get('kind')=='decision' and str(e.get('actor'))==str(actor) and exact_time(e.get('observation',{}).get('time',0))==exact_time(when)]
    def set_metadata(self,key,value):self._metadata[key]=deepcopy(value)
    def get_metadata(self,key,default=None):return deepcopy(self._metadata.get(key,default))
    def _write_control(self,result,control,revision):
        self._commands[result['command_id']]=(revision,deepcopy(result));self.set_metadata('control_state',control);self.set_metadata('active_control_command',None)
    def begin_command(self,command):
        existing=self.command_result(command['id'])
        if existing:return existing
        self._commands[command['id']]=(self.revision,deepcopy(command));self.set_metadata('active_control_command',command)
    def finish_command(self,result,control):self._write_control(result,control,self.revision)
    def command_result(self,command_id):
        record=self._commands.get(command_id)
        return deepcopy(record[1]) if record and record[1].get('status') in {'applied','rejected'} else None
    def command_results(self):return [deepcopy(r) for _,r in self._commands.values() if r.get('status') in {'applied','rejected'}]
    def save_checkpoint(self,payload,path=None):
        from .checkpoint import write_checkpoint_document
        if path is None:raise ValueError('A checkpoint path is required for contract-memory')
        result=write_checkpoint_document(payload,self.revision,path);self._checkpoints.append(result);return result
    def load_checkpoint(self,path=None):
        from .checkpoint import read_checkpoint_document
        if path is None:
            if not self._checkpoints:raise FileNotFoundError('No registered checkpoint')
            path=self._checkpoints[-1]
        return read_checkpoint_document(path)
    def set_cancellation(self,cancel_event):self._cancel_event=cancel_event
    def flush(self):pass
    def reader_reference(self):
        # Nondurable test histories travel as values, never process-local handles.
        return {"schema":"zombie-sim/history-reference-v1","backend":"contract-memory",
                "commits":deepcopy(self._commits),"events":deepcopy(self._events),
                "runtime":deepcopy(self._runtime),"metadata":deepcopy(self._metadata),
                "commands":deepcopy(self._commands),"transactions":deepcopy(self._transactions),"receipts":deepcopy(self._receipts)}
    @classmethod
    def from_reference(cls,reference,*,read_only=True):
        history=cls()
        for key in ("commits","events","runtime","metadata","commands","transactions","receipts"):
            setattr(history,"_"+key,deepcopy(reference[key]))
        history._state=history.state_at();history._runtime_state=history.runtime_at();history.read_only=read_only
        return history
    def storage_bytes(self):return 0
    def close(self):pass
