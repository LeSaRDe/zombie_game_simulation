"""Transactional live stores and an append-only, exact-time SQLite ledger.

Payloads use canonical JSON, never pickle.  Connections belong to a single run;
an RLock serializes writes and permits detached reads from application threads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import zlib
from fractions import Fraction
from typing import Any


def json_default(value):
    if isinstance(value, Fraction):
        return {"numerator": value.numerator, "denominator": value.denominator}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=json_default)


def exact_time(value=0):
    if isinstance(value, dict):
        return Fraction(int(value.get("numerator", value.get("n", 0))),
                        int(value.get("denominator", value.get("d", 1))))
    return Fraction(str(value)) if not isinstance(value, Fraction) else value


def _pack(value):
    return zlib.compress(canonical(value).encode(), 3)


def _unpack(value):
    return json.loads(zlib.decompress(value))


def state_diff(before, after, path=()):
    """JSON object patch; arrays are values, preserving order and exact contents."""
    if isinstance(before, dict) and isinstance(after, dict):
        result = [["remove", list(path + (key,))] for key in sorted(before.keys() - after.keys())]
        for key in sorted(after):
            if key not in before:
                result.append(["set", list(path + (key,)), after[key]])
            elif before[key] != after[key]:
                result.extend(state_diff(before[key], after[key], path + (key,)))
        return result
    return [["set", list(path), after]] if before != after else []


def apply_patch(state, patch):
    for op in patch:
        path = op[1]
        if not path:
            state = copy.deepcopy(op[2])
            continue
        parent = state
        for key in path[:-1]:
            parent = parent.setdefault(key, {})
        if op[0] == "remove":
            parent.pop(path[-1], None)
        else:
            parent[path[-1]] = copy.deepcopy(op[2])
    return state


def stage_patch(state, patch):
    """Copy only branches touched by a transaction; published values stay detached."""
    result = dict(state)
    for op in patch:
        path = op[1]
        if not path:
            result = copy.deepcopy(op[2])
            continue
        parent = result
        for key in path[:-1]:
            parent[key] = dict(parent.get(key, {}))
            parent = parent[key]
        if op[0] == "remove":
            parent.pop(path[-1], None)
        else:
            parent[path[-1]] = copy.deepcopy(op[2])
    return result


def _rollback_patch(undo):
    for parent,key,present,value in reversed(undo):
        if present:parent[key]=value
        else:parent.pop(key,None)


def _stage_locked(state,patch):
    """Stage under the store lock, recording exact undo without copying maps.

    Store read APIs return detached copies. Consequently the private cache can
    be staged in place while the same lock excludes readers. No version is
    published until the durable transaction succeeds; any failure restores the
    old references. This keeps transaction cost proportional to changed records.
    """
    undo=[];result=state
    try:
        for op in patch:
            path=op[1]
            if not path:
                result=copy.deepcopy(op[2]);continue
            parent=result
            for key in path[:-1]:
                if key not in parent:
                    undo.append((parent,key,False,None));parent[key]={}
                parent=parent[key]
            key=path[-1];undo.append((parent,key,key in parent,parent.get(key)))
            if op[0]=="remove":parent.pop(key,None)
            else:parent[key]=copy.deepcopy(op[2])
        return result,undo
    except BaseException:
        _rollback_patch(undo)
        raise


def _request_checksum(kind, payload, records, runtime_delta, command_result):
    return hashlib.sha256(canonical([kind,payload,list(records),runtime_delta,command_result]).encode()).hexdigest()


def _existing_transaction(store, transaction_id, checksum):
    from .persistence.contracts import TransactionMismatch
    if not transaction_id:return None
    if store.history is not None:
        return store.history.transaction_revision(transaction_id, checksum)
    previous=store._transactions.get(transaction_id)
    if previous:
        if previous[0]!=checksum:raise TransactionMismatch("Transaction identity reused with different content")
        return previous[1]
    return None


class VersionConflict(RuntimeError):
    """A stale writer cannot commit over a newer published revision."""


from .persistence.sqlite_queries import SQLiteHistoryQueries


class History(SQLiteHistoryQueries):
    """Lossless event/delta journal with periodic full-state anchors.

    ``state_at`` returns the last committed state at/before a time.  Continuous
    projections are evaluated by the visualization/engine layer from its anchors.
    A revision selects a precise causal boundary, including within one timestamp.
    """
    def __init__(self, path, initial=None, *, connection=None, anchor_interval=1000, read_only=False):
        self.path = Path(path) if str(path) != ":memory:" else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only
        self.connection = connection or (sqlite3.connect(f"file:{Path(path).absolute()}?mode=ro", uri=True, check_same_thread=False)
                                         if read_only else sqlite3.connect(str(path), check_same_thread=False))
        self._owns_connection = connection is None
        self.lock = threading.RLock()
        self.anchor_interval = max(1, int(anchor_interval))
        if read_only:
            self._state = {}
            self._runtime_state = None
            return
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript("""
          CREATE TABLE IF NOT EXISTS commits (
            revision INTEGER PRIMARY KEY, transaction_id TEXT NOT NULL UNIQUE,
            time_n TEXT NOT NULL, time_d TEXT NOT NULL, seconds REAL NOT NULL,
            patch BLOB NOT NULL, anchor BLOB, checksum TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS commit_time ON commits(seconds,revision);
          CREATE INDEX IF NOT EXISTS commit_anchor ON commits(revision) WHERE anchor IS NOT NULL;
          CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, revision INTEGER NOT NULL,
            kind TEXT, actor TEXT, payload BLOB NOT NULL,
            FOREIGN KEY(revision) REFERENCES commits(revision));
          CREATE INDEX IF NOT EXISTS event_revision ON events(revision,sequence);
          CREATE INDEX IF NOT EXISTS event_kind ON events(kind,revision);
          CREATE INDEX IF NOT EXISTS event_actor ON events(actor,revision);
          CREATE TABLE IF NOT EXISTS participants (
            agent_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            PRIMARY KEY(agent_id,sequence));
          CREATE TABLE IF NOT EXISTS checkpoints (
            revision INTEGER NOT NULL, path TEXT PRIMARY KEY, checksum TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, payload BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS live_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL,
            payload BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS live_entities (
            collection TEXT NOT NULL, entity_key TEXT NOT NULL, payload BLOB NOT NULL,
            PRIMARY KEY(collection,entity_key));
          CREATE TABLE IF NOT EXISTS runtime_commits (
            revision INTEGER PRIMARY KEY, patch BLOB NOT NULL, anchor BLOB,
            checksum TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS transaction_requests (transaction_id TEXT PRIMARY KEY, checksum TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS transaction_receipts (
            transaction_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
            first_sequence INTEGER, last_sequence INTEGER, command_result BLOB);
          CREATE TABLE IF NOT EXISTS control_commands (
            command_id TEXT PRIMARY KEY, status TEXT NOT NULL,
            revision INTEGER NOT NULL, payload BLOB NOT NULL);
        """)
        self.connection.commit()
        self._state = self.state_at()
        self._runtime_state = self.runtime_at()
        if initial is not None and not self.connection.execute("SELECT 1 FROM commits LIMIT 1").fetchone():
            self.append(initial.get("time", 0), snapshot=initial, transaction_id="initialize")

    @property
    def revision(self):
        return self.connection.execute("SELECT COALESCE(MAX(revision),-1) FROM commits").fetchone()[0]

    def append(self, time=0, event=None, delta=None, snapshot=None, transaction_id=None,
               *, records=(), revision=None, in_transaction=False, runtime_delta=None, command_result=None, request_checksum=None):
        from .faults import hit
        with self.lock:
            if self.read_only:
                raise RuntimeError("Cannot append to a read-only history view")
            txid = transaction_id or f"revision:{self.revision + 1}"
            records=list(records)
            request_checksum=request_checksum or _request_checksum("append",[str(exact_time(time)),event,delta,snapshot],records,runtime_delta,command_result)
            previous=self.transaction_revision(txid,request_checksum)
            if previous is not None:
                return previous
            rev = self.revision + 1 if revision is None else int(revision)
            if rev != self.revision + 1:
                raise VersionConflict(f"Expected revision {self.revision + 1}, got {rev}")
            t = exact_time(time)
            last_time = self.connection.execute("SELECT time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
            if last_time and t < Fraction(int(last_time[0]), int(last_time[1])):
                raise ValueError("History commit times must be nondecreasing")
            rows = list(records)
            if event is not None:
                rows.append(event)
            undo=[];runtime_undo=[]
            try:
                if snapshot is not None:
                    state=copy.deepcopy(snapshot)
                elif in_transaction:
                    # An outer SQLiteStore transaction owns rollback/publication.
                    state=stage_patch(self._state,delta or [])
                else:
                    state,undo=_stage_locked(self._state,delta or [])
                patch=state_diff(self._state,state) if delta is None else delta
                payload=_pack(patch)
                previous_anchor=self.connection.execute("SELECT revision,length(anchor) FROM commits WHERE anchor IS NOT NULL ORDER BY revision DESC LIMIT 1").fetchone()
                # Keep large histories from rewriting all old occurrences every
                # 1000 transitions. Every delta remains durable; only redundant
                # recovery accelerators become less frequent, up to 10000 rows.
                stride=self.anchor_interval
                if previous_anchor:
                    scale=max(1,(previous_anchor[1]+8*1024**2-1)//(8*1024**2))
                    stride=min(max(self.anchor_interval,10000),self.anchor_interval*scale)
                write_anchor=previous_anchor is None or rev-previous_anchor[0]>=stride
                anchor=_pack({"anchor_schema":1,"state":state,
                              "checksum":hashlib.sha256(canonical(state).encode()).hexdigest()}) if write_anchor else None
                hit("history_write",revision=rev)
                if not in_transaction:
                    self.connection.execute("BEGIN IMMEDIATE")
                    existing=self.transaction_revision(txid,request_checksum)
                    if existing is not None:
                        self.connection.rollback()
                        _rollback_patch(undo)
                        return existing
                    actual = self.revision
                    if rev != actual + 1:
                        raise VersionConflict(f"Expected revision {actual + 1}, got {rev}")
                self.connection.execute("INSERT INTO commits VALUES(?,?,?,?,?,?,?,?)", (
                    rev, txid, str(t.numerator), str(t.denominator), float(t), payload, anchor,
                    hashlib.sha256(payload).hexdigest()))
                self.connection.execute("INSERT INTO transaction_requests VALUES(?,?)",(txid,request_checksum))
                runtime_state = self._runtime_state
                if runtime_delta is not None:
                    if in_transaction:runtime_state=stage_patch(self._runtime_state or {},runtime_delta)
                    else:runtime_state,runtime_undo=_stage_locked(self._runtime_state or {},runtime_delta)
                    runtime_blob = _pack(runtime_delta)
                    runtime_anchor = _pack({"state": runtime_state, "checksum": hashlib.sha256(canonical(runtime_state).encode()).hexdigest()}) if write_anchor or self._runtime_state is None else None
                    self.connection.execute("INSERT INTO runtime_commits VALUES(?,?,?,?)", (rev, runtime_blob, runtime_anchor, hashlib.sha256(runtime_blob).hexdigest()))
                if command_result is not None:
                    self._write_control(command_result, command_result.get("control", {}), rev)
                first_sequence=last_sequence=None
                for record in rows:
                    actor = record.get("actor", record.get("agent_id", record.get("agent")))
                    cursor = self.connection.execute("INSERT INTO events(revision,kind,actor,payload) VALUES(?,?,?,?)", (
                        rev, str(record.get("kind", record.get("type", "event"))), str(actor) if actor is not None else None,
                        _pack(record)))
                    if first_sequence is None:first_sequence=cursor.lastrowid
                    last_sequence=cursor.lastrowid
                    ids = {str(actor)} if actor is not None else set()
                    for key in ("target", "target_id"):
                        if record.get(key) is not None:
                            ids.add(str(record[key]))
                    ids.update(str(x) for x in record.get("targets", []))
                    self.connection.executemany("INSERT OR IGNORE INTO participants VALUES(?,?)",
                                                [(x, cursor.lastrowid) for x in ids])
                self.connection.execute("INSERT INTO transaction_receipts VALUES(?,?,?,?,?)",
                    (txid,rev,first_sequence,last_sequence,_pack(command_result) if command_result is not None else None))
                if not in_transaction:
                    hit("before_history_commit",revision=rev)
                    self.connection.commit()
                    hit("after_history_commit_before_publish",revision=rev)
            except BaseException:
                if not in_transaction:
                    self.connection.rollback()
                _rollback_patch(runtime_undo)
                _rollback_patch(undo)
                raise
            self._state = state
            self._runtime_state = runtime_state
            return rev

    def initialize_runtime(self, document, revision=0):
        with self.lock, self.connection:
            previous = self.connection.execute("SELECT 1 FROM runtime_commits WHERE revision=?", (int(revision),)).fetchone()
            if previous:
                self._runtime_state = self.runtime_at()
                return
            patch = _pack([["set", [], document]])
            anchor = _pack({"state": document, "checksum": hashlib.sha256(canonical(document).encode()).hexdigest()})
            self.connection.execute("INSERT INTO runtime_commits VALUES(?,?,?,?)", (int(revision), patch, anchor, hashlib.sha256(patch).hexdigest()))
            self._runtime_state = copy.deepcopy(document)

    def runtime_at(self, revision=None):
        with self.lock:
            exists = self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_commits'").fetchone()
            if not exists:
                return None
            frontier = self.revision if revision is None else int(revision)
            row = self.connection.execute("SELECT revision,anchor FROM runtime_commits WHERE revision<=? AND anchor IS NOT NULL ORDER BY revision DESC LIMIT 1", (frontier,)).fetchone()
            if row is None:
                return None
            start, envelope = row[0], _unpack(row[1])
            state = envelope["state"]
            if hashlib.sha256(canonical(state).encode()).hexdigest() != envelope["checksum"]:
                raise ValueError("Runtime anchor checksum mismatch")
            last = start
            for current, payload, checksum in self.connection.execute("SELECT revision,patch,checksum FROM runtime_commits WHERE revision>? AND revision<=? ORDER BY revision", (start, frontier)):
                if current != last + 1:
                    raise ValueError(f"Runtime journal is missing revision {last + 1}")
                if hashlib.sha256(payload).hexdigest() != checksum:
                    raise ValueError("Runtime delta checksum mismatch")
                state = apply_patch(state, _unpack(payload))
                last = current
            if last != frontier:
                raise ValueError(f"Runtime journal ends at revision {last}, requested {frontier}")
            return state

    def _write_control(self, result, control, revision):
        self.connection.execute("INSERT OR REPLACE INTO control_commands VALUES(?,?,?,?)", (result["command_id"], result["status"], int(revision), _pack(result)))
        self.connection.execute("INSERT OR REPLACE INTO metadata VALUES('control_state',?)", (_pack(control),))
        self.connection.execute("INSERT OR REPLACE INTO metadata VALUES('active_control_command',?)", (_pack(None),))

    def begin_command(self, command):
        with self.lock, self.connection:
            old = self.connection.execute("SELECT status,payload FROM control_commands WHERE command_id=?", (command["id"],)).fetchone()
            if old and old[0] in {"applied", "rejected"}:
                return _unpack(old[1])
            self.connection.execute("INSERT OR REPLACE INTO control_commands VALUES(?,?,?,?)", (command["id"], "pending", self.revision, _pack(command)))
            self.connection.execute("INSERT OR REPLACE INTO metadata VALUES('active_control_command',?)", (_pack(command),))
            return None

    def finish_command(self, result, control):
        with self.lock, self.connection:
            self._write_control(result, control, self.revision)

    def command_results(self):
        return [_unpack(row[0]) for row in self.connection.execute("SELECT payload FROM control_commands WHERE status IN ('applied','rejected') ORDER BY rowid")]

    def command_result(self, command_id):
        row = self.connection.execute("SELECT payload FROM control_commands WHERE command_id=? AND status IN ('applied','rejected')", (command_id,)).fetchone()
        return _unpack(row[0]) if row else None

    def state_at(self, time=None, revision=None, *, check_cancelled=None):
        with self.lock:
            if check_cancelled:
                check_cancelled()
            frontier = self.revision if revision is None else int(revision)
            if time is not None:
                requested = exact_time(time)
                # The float index is a candidate filter only; exact comparison decides.
                rows = self.connection.execute("SELECT revision,time_n,time_d FROM commits WHERE revision<=? AND seconds<=? ORDER BY revision DESC",
                                               (frontier, float(requested) + max(1, abs(float(requested))) * 1e-14))
                frontier = next((r for r, n, d in rows if Fraction(int(n), int(d)) <= requested), -1)
            anchor = self.connection.execute("SELECT revision,anchor FROM commits WHERE revision<=? AND anchor IS NOT NULL ORDER BY revision DESC LIMIT 1", (frontier,)).fetchone()
            start, state = -1, {}
            if anchor:
                start, envelope = anchor[0], _unpack(anchor[1])
                if check_cancelled:
                    check_cancelled()
                if envelope.get("anchor_schema") == 1:
                    state = envelope["state"]
                    if hashlib.sha256(canonical(state).encode()).hexdigest() != envelope["checksum"]:
                        raise ValueError("History anchor checksum mismatch; replay halted")
                else:
                    # Initial development ledgers had bare anchors. Verify them
                    # against their checked patch chain rather than trust them.
                    for payload, checksum in self.connection.execute("SELECT patch,checksum FROM commits WHERE revision<=? ORDER BY revision", (start,)):
                        if check_cancelled:
                            check_cancelled()
                        if hashlib.sha256(payload).hexdigest() != checksum:
                            raise ValueError("History checksum mismatch; replay halted")
                        state = apply_patch(state, _unpack(payload))
                    if state != envelope:
                        raise ValueError("Legacy anchor disagrees with the durable patch chain")
            for _, payload, checksum in self.connection.execute("SELECT revision,patch,checksum FROM commits WHERE revision>? AND revision<=? ORDER BY revision", (start, frontier)):
                if check_cancelled:
                    check_cancelled()
                if hashlib.sha256(payload).hexdigest() != checksum:
                    raise ValueError("History checksum mismatch; replay halted")
                state = apply_patch(state, _unpack(payload))
            if check_cancelled:
                check_cancelled()
            return state

    def events(self, start=0, end=None, kind=None, agent_id=None, limit=None, latest=False):
        with self.lock:
            sql = "SELECT e.sequence,e.revision,e.payload FROM events e WHERE e.revision>=?"
            args = [int(start)]
            if end is not None:
                sql += " AND e.revision<=?"; args.append(int(end))
            if kind:
                sql += " AND e.kind=?"; args.append(kind)
            if agent_id is not None:
                sql += " AND EXISTS(SELECT 1 FROM participants p WHERE p.sequence=e.sequence AND p.agent_id=?)"; args.append(str(agent_id))
            sql += " ORDER BY e.sequence DESC" if latest else " ORDER BY e.sequence"
            if limit is not None:
                sql += " LIMIT ?"; args.append(max(1, int(limit)))
            result = [dict(_unpack(payload), ledger_sequence=str(seq), ledger_revision=str(rev))
                      for seq, rev, payload in self.connection.execute(sql, args)]
            return list(reversed(result)) if latest else result

    def set_metadata(self, key, value):
        with self.lock, self.connection:
            self.connection.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, _pack(value)))

    def get_metadata(self, key, default=None):
        row = self.connection.execute("SELECT payload FROM metadata WHERE key=?", (key,)).fetchone()
        return _unpack(row[0]) if row else default

    def save_checkpoint(self, payload, path=None):
        if path is None:
            if not self.path:
                raise ValueError("A checkpoint path is required for an in-memory ledger")
            path = self.path.parent / "checkpoints" / f"revision-{self.revision}.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = canonical({"schema": "zombie-sim/checkpoint-v1", "ledger_revision": self.revision, "payload": payload})
        checksum = hashlib.sha256(body.encode()).hexdigest()
        envelope = canonical({"checksum": checksum, "document": json.loads(body)})
        temporary = path.with_suffix(path.suffix + ".partial")
        with temporary.open("w") as handle:
            handle.write(envelope)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        from .faults import hit
        hit("after_checkpoint_rename_before_register",revision=self.revision,path=str(path))
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        with self.lock, self.connection:
            self.connection.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", (self.revision, str(path.absolute()), checksum))
        return str(path)

    def load_checkpoint(self, path=None):
        if path is None:
            row = self.connection.execute("SELECT path FROM checkpoints ORDER BY revision DESC LIMIT 1").fetchone()
            if not row:
                raise FileNotFoundError("No registered checkpoint")
            path = row[0]
        envelope = json.loads(Path(path).read_text())
        digest = hashlib.sha256(canonical(envelope["document"]).encode()).hexdigest()
        if digest != envelope["checksum"]:
            raise ValueError("Checkpoint checksum mismatch")
        return envelope["document"]["payload"]

    def close(self):
        if self._owns_connection:
            self.connection.close()


class MemoryStore:
    def __init__(self, initial=None, *, history=None):
        self.history = history
        self.lock = threading.RLock()
        self._state = copy.deepcopy(initial or {})
        self.version = history.revision if history is not None else 0
        if history is not None and self.version < 0:
            self.version = history.append(self._state.get("time", 0), snapshot=self._state, transaction_id="initialize")
        elif history is not None and initial is None:
            self._state = history.state_at()
        self._transactions = {}

    def read_view(self, time=None, revision=None):
        with self.lock:
            if (time is not None or revision is not None) and self.history is not None:
                return self.history.state_at(time, revision)
            return copy.deepcopy(self._state)

    def read_many(self, keys):
        view = self.read_view()
        return {key: view.get(key) for key in keys}

    def commit(self, state, expected_version=None, records=(), transaction_id=None, *, runtime_delta=None, command_result=None):
        with self.lock:
            records=list(records)
            checksum=_request_checksum("state",state,records,runtime_delta,command_result)
            previous=_existing_transaction(self,transaction_id,checksum)
            if previous is not None:return previous
            if expected_version is not None and int(expected_version) != self.version:
                raise VersionConflict(f"Expected version {expected_version}, current version is {self.version}")
            staged = copy.deepcopy(state)
            version = self.version + 1
            if self.history is not None:
                version = self.history.append(staged.get("time", 0), snapshot=staged, records=records,
                                              transaction_id=transaction_id, runtime_delta=runtime_delta, command_result=command_result,
                                              revision=version, request_checksum=checksum)
            self._state, self.version = staged, version
            if transaction_id:
                self._transactions[transaction_id] = (checksum,version)
            return version

    export_snapshot = read_view

    def commit_delta(self, delta, expected_version=None, records=(), transaction_id=None, *, runtime_delta=None, command_result=None):
        with self.lock:
            records=list(records)
            checksum=_request_checksum("delta",delta,records,runtime_delta,command_result)
            previous=_existing_transaction(self,transaction_id,checksum)
            if previous is not None:return previous
            if expected_version is not None and int(expected_version) != self.version:
                raise VersionConflict(f"Expected version {expected_version}, current version is {self.version}")
            staged,undo = _stage_locked(self._state, delta)
            revision = self.version + 1
            try:
                if self.history is not None:
                    revision = self.history.append(staged.get("time", 0), delta=delta, records=records,
                                                   transaction_id=transaction_id, runtime_delta=runtime_delta, command_result=command_result,
                                                   revision=revision, request_checksum=checksum)
            except BaseException:
                _rollback_patch(undo)
                raise
            self._state, self.version = staged, revision
            if transaction_id:
                self._transactions[transaction_id] = (checksum,revision)
            return revision

    def close(self):
        if self.history:
            self.history.close()


class SQLiteStore:
    def __init__(self, path, initial=None):
        self.history = History(path)
        self.lock = self.history.lock
        self._transactions = {}
        row = self.history.connection.execute("SELECT revision,payload FROM live_state WHERE singleton=1").fetchone()
        if row:
            self.version, blob = row
            self._state = _unpack(blob)
        else:
            self._state = copy.deepcopy(initial or self.history.state_at())
            self.version = self.history.revision
            if self.version < 0:
                self.version = self.history.append(self._state.get("time", 0), snapshot=self._state, transaction_id="initialize")
            with self.history.connection:
                self.history.connection.execute("INSERT INTO live_state VALUES(1,?,?)", (self.version, _pack(self._state)))
        if not self.history.connection.execute("SELECT 1 FROM live_entities LIMIT 1").fetchone():
            with self.history.connection:
                self._write_entities(self._state)
        else:
            self._state = self.read_view()

    def read_many(self, keys):
        view=self.read_view()
        return {key:view.get(key) for key in keys}

    def close(self):
        self.history.close()

    def export_snapshot(self, time=None, revision=None):
        return self.read_view(time,revision)

    def _write_entities(self, state):
        rows = []
        for key, value in state.items():
            if isinstance(value, dict):
                rows.append((key, "", _pack({"mapping": True})))
                rows.extend((key, str(entity), _pack(payload)) for entity, payload in value.items())
            else:
                rows.append((key, "", _pack({"value": value})))
        self.history.connection.executemany("INSERT OR REPLACE INTO live_entities VALUES(?,?,?)", rows)

    def _begin_commit(self, expected_version, transaction_id=None, request_checksum=None):
        connection = self.history.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            actual = connection.execute("SELECT revision FROM live_state WHERE singleton=1").fetchone()[0]
            if actual != self.version:
                self._state = self.read_view()
                self.history._state = self._state
                self.history._runtime_state = self.history.runtime_at()
                self.version = actual
            if transaction_id:
                existing=self.history.transaction_revision(transaction_id,request_checksum)
                if existing is not None:
                    connection.rollback()
                    return existing
            if expected_version is not None and int(expected_version) != actual:
                raise VersionConflict(f"Expected version {expected_version}, durable version is {actual}")
        except BaseException:
            connection.rollback()
            raise

    def read_view(self, time=None, revision=None):
        with self.lock:
            if time is not None or revision is not None:
                return self.history.state_at(time, revision)
            state = {}
            for collection, key, payload in self.history.connection.execute("SELECT collection,entity_key,payload FROM live_entities ORDER BY collection,entity_key"):
                value = _unpack(payload)
                if key == "":
                    state[collection] = {} if value.get("mapping") else value["value"]
                else:
                    state.setdefault(collection, {})[key] = value
            return state

    def commit(self, state, expected_version=None, records=(), transaction_id=None, *, runtime_delta=None, command_result=None):
        with self.lock:
            connection = self.history.connection
            records=list(records)
            checksum=_request_checksum("state",state,records,runtime_delta,command_result)
            previous=_existing_transaction(self,transaction_id,checksum)
            if previous is not None:return previous
            duplicate = self._begin_commit(expected_version, transaction_id, checksum)
            if duplicate is not None:
                return duplicate
            old_history = self.history._state
            old_runtime = self.history._runtime_state
            try:
                staged = copy.deepcopy(state)
                rev = self.history.append(staged.get("time", 0), snapshot=staged, records=records,
                                          transaction_id=transaction_id, in_transaction=True,
                                          runtime_delta=runtime_delta, command_result=command_result, request_checksum=checksum)
                connection.execute("UPDATE live_state SET revision=?,payload=? WHERE singleton=1", (rev, _pack(staged)))
                connection.execute("DELETE FROM live_entities")
                self._write_entities(staged)
                from .faults import hit
                hit("before_history_commit",revision=rev)
                connection.commit()
                hit("after_history_commit_before_publish",revision=rev)
            except BaseException:
                connection.rollback()
                self.history._state = old_history
                self.history._runtime_state = old_runtime
                raise
            self._state, self.version = staged, rev
            return rev

    def commit_delta(self, delta, expected_version=None, records=(), transaction_id=None, *, runtime_delta=None, command_result=None):
        with self.lock:
            connection = self.history.connection
            records=list(records)
            checksum=_request_checksum("delta",delta,records,runtime_delta,command_result)
            previous=_existing_transaction(self,transaction_id,checksum)
            if previous is not None:return previous
            duplicate = self._begin_commit(expected_version, transaction_id, checksum)
            if duplicate is not None:
                return duplicate
            previous = self.history._state
            old_runtime = self.history._runtime_state
            try:
                staged = stage_patch(self._state, delta)
                revision = self.history.append(staged.get("time", 0), delta=delta, records=records,
                                               transaction_id=transaction_id, in_transaction=True,
                                               runtime_delta=runtime_delta, command_result=command_result, request_checksum=checksum)
                collections = {op[1][0] for op in delta if op[1]}
                if any(not op[1] for op in delta):
                    connection.execute("DELETE FROM live_entities")
                    self._write_entities(staged)
                else:
                    for collection in collections:
                        operations = [op for op in delta if op[1][0] == collection]
                        if any(len(op[1]) == 1 for op in operations):
                            connection.execute("DELETE FROM live_entities WHERE collection=?", (collection,))
                            if collection in staged:
                                self._write_entities({collection: staged[collection]})
                        else:
                            for entity in {op[1][1] for op in operations}:
                                if entity in staged[collection]:
                                    connection.execute("INSERT OR REPLACE INTO live_entities VALUES(?,?,?)", (collection, str(entity), _pack(staged[collection][entity])))
                                else:
                                    connection.execute("DELETE FROM live_entities WHERE collection=? AND entity_key=?", (collection, str(entity)))
                # Snapshot payload is an initialization compatibility record.  The
                # row store and ledger, not this old blob, are authoritative.
                connection.execute("UPDATE live_state SET revision=? WHERE singleton=1", (revision,))
                from .faults import hit
                hit("before_history_commit",revision=revision)
                connection.commit()
                hit("after_history_commit_before_publish",revision=revision)
            except BaseException:
                connection.rollback()
                self.history._state = previous
                self.history._runtime_state = old_runtime
                raise
            self._state, self.version = staged, revision
            return revision


MemoryStateStore = MemoryStore
SQLiteStateStore = SQLiteStore
HistoryStore = History
