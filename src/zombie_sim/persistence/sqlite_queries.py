"""Named SQLite queries shared by the compatibility ledger and persistence bundle.

Callers receive detached records or bounded iterators. SQL and compressed archive
formats do not escape this adapter; exact rational checks refine indexed searches.
"""
from __future__ import annotations
import hashlib


class SQLiteHistoryQueries:
    def head(self, revision=None):
        with self.lock:
            if revision is None:
                return self.connection.execute('SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1').fetchone()
            return self.connection.execute('SELECT revision,time_n,time_d FROM commits WHERE revision=?',(int(revision),)).fetchone()

    def boundary(self, revision):
        row=self.head(revision)
        return row[1:] if row else None

    def origin(self):
        with self.lock:
            return self.connection.execute('SELECT revision,time_n,time_d FROM commits ORDER BY revision LIMIT 1').fetchone()

    def cursor_candidates(self, time, revision_cap=None):
        from ..storage import exact_time
        at=exact_time(time)
        cursor=self.connection.execute('SELECT revision,time_n,time_d FROM commits WHERE revision<=? AND seconds<=? ORDER BY revision DESC',
            (self.revision if revision_cap is None else int(revision_cap),float(at)+max(1,abs(float(at)))*1e-14))
        try:
            yield from cursor
        finally:
            cursor.close()

    def cursor_at(self, time, revision_cap=None, *, check_cancelled=None):
        from ..storage import exact_time
        rows=self.cursor_candidates(time,revision_cap)
        try:
            for row in rows:
                if check_cancelled:check_cancelled()
                if exact_time({'n':row[1],'d':row[2]})<=exact_time(time):return row
        finally:rows.close()
        return None

    @staticmethod
    def _verified_patch(payload, checksum):
        from ..storage import _unpack
        if hashlib.sha256(payload).hexdigest()!=checksum:
            raise ValueError('History checksum mismatch; query halted')
        return _unpack(payload)

    def commit_patch(self, revision):
        row=self.connection.execute('SELECT patch,checksum FROM commits WHERE revision=?',(int(revision),)).fetchone()
        return (self._verified_patch(*row),row[1]) if row else None

    def commit_checksum(self, revision):
        """Verify stored bytes without decoding a potentially large anchor."""
        row=self.connection.execute('SELECT patch,checksum FROM commits WHERE revision=?',(int(revision),)).fetchone()
        if row is None:return None
        if hashlib.sha256(row[0]).hexdigest()!=row[1]:
            raise ValueError('History checksum mismatch; query halted')
        return row[1]

    def iter_commits(self, after=-1, through=None):
        cursor=self.connection.execute('SELECT revision,time_n,time_d,patch,checksum FROM commits WHERE revision>? AND revision<=? ORDER BY revision',
            (int(after),self.revision if through is None else int(through)))
        try:
            for revision,n,d,payload,checksum in cursor:
                yield revision,n,d,self._verified_patch(payload,checksum),checksum
        finally:cursor.close()

    def verified_anchor(self, revision):
        from ..storage import _unpack, canonical
        row=self.connection.execute('SELECT revision,anchor FROM commits WHERE revision<=? AND anchor IS NOT NULL ORDER BY revision DESC LIMIT 1',(int(revision),)).fetchone()
        if row:
            envelope=_unpack(row[1])
            if envelope.get('anchor_schema')==1:
                if hashlib.sha256(canonical(envelope['state']).encode()).hexdigest()!=envelope['checksum']:
                    raise ValueError('History anchor checksum mismatch; query halted')
                return row[0],envelope['state']
        return None

    def source_identity(self):
        from ..storage import exact_time
        row=self.origin()
        if row is None:raise ValueError('History requires a committed initial state')
        checksum=self.commit_checksum(row[0])
        if self.path is None:
            if not hasattr(self,'_source_token'):self._source_token=object()
            identity=(self._source_token,checksum)
        else:
            stat=self.path.stat()
            identity=(str(self.path.resolve()),stat.st_dev,stat.st_ino,checksum)
        return identity,exact_time({'n':row[1],'d':row[2]})

    def event_positions(self, kind=None):
        sql='SELECT sequence FROM events'+(' WHERE kind=?' if kind else '')+' ORDER BY sequence'
        cursor=self.connection.execute(sql,(kind,) if kind else ())
        try:
            for row in cursor:yield row[0]
        finally:cursor.close()

    def event_range(self, first, last, kind=None):
        from ..storage import _unpack
        sql='SELECT payload FROM events WHERE sequence>=? AND sequence<=?';args=[first,last]
        if kind:sql+=' AND kind=?';args.append(kind)
        with self.lock:
            return [_unpack(row[0]) for row in self.connection.execute(sql+' ORDER BY sequence',args)]

    def last_event_sequence(self):
        return self.connection.execute('SELECT MAX(sequence) FROM events').fetchone()[0]

    def event_counts(self, after=-1, through=None):
        return dict(self.connection.execute('SELECT kind,COUNT(*) FROM events WHERE revision>? AND revision<=? GROUP BY kind',
            (int(after),self.revision if through is None else int(through))))

    def event_count(self):
        return self.connection.execute('SELECT COUNT(*) FROM events').fetchone()[0]

    def decision_records_at(self, actor, when):
        from ..storage import _unpack,exact_time
        at=exact_time(when);seconds=float(at);epsilon=max(1,abs(seconds))*1e-14
        with self.lock:
            records=[_unpack(row[0]) for row in self.connection.execute("SELECT e.payload FROM events e JOIN commits c ON c.revision=e.revision WHERE e.kind='decision' AND e.actor=? AND c.seconds>=? AND c.seconds<=? ORDER BY e.sequence",(str(actor),seconds-epsilon,seconds+epsilon))]
        return [r for r in records if exact_time(r.get('observation',{}).get('time',0))==at]

    def timeline_records(self, revision, *, agent=None, before=None, after=None, descending=True, limit=None):
        from ..storage import _unpack
        direct='0' if agent is None else 'EXISTS(SELECT 1 FROM participants p WHERE p.sequence=e.sequence AND p.agent_id=?)'
        sql=f'SELECT e.sequence,e.revision,e.payload,c.time_n,c.time_d,{direct} FROM events e JOIN commits c ON c.revision=e.revision WHERE e.revision<=?'
        args=[] if agent is None else [str(agent)];args.append(int(revision))
        if before is not None:sql+=' AND e.sequence<?';args.append(before)
        if after is not None:sql+=' AND e.sequence>?';args.append(after)
        sql+=' ORDER BY e.sequence DESC' if descending else ' ORDER BY e.sequence'
        if limit is not None:sql+=' LIMIT ?';args.append(int(limit))
        cursor=self.connection.execute(sql,args)
        try:
            for seq,rev,payload,n,d,matched in cursor:yield seq,rev,_unpack(payload),n,d,matched
        finally:cursor.close()

    def set_cancellation(self, cancel_event):
        self.connection.set_progress_handler((lambda:int(cancel_event.is_set())) if cancel_event else None,1000)

    def flush(self):
        self.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def reader_reference(self):
        if self.path is None:raise ValueError("An anonymous SQLite ledger cannot be reopened in another process")
        return str(self.path.absolute())  # Preserve the existing opaque local reference format.

    def storage_bytes(self):
        return self.path.stat().st_size if self.path else 0

    def transaction_revision(self, transaction_id, request_checksum=None):
        from .contracts import TransactionMismatch
        row=self.connection.execute('SELECT revision FROM commits WHERE transaction_id=?',(transaction_id,)).fetchone()
        if row and request_checksum is not None:
            stored=self.connection.execute('SELECT checksum FROM transaction_requests WHERE transaction_id=?',(transaction_id,)).fetchone()
            if stored is None:
                raise TransactionMismatch('Historical transaction has no request fingerprint; cannot prove an idempotent retry')
            if stored[0]!=request_checksum:raise TransactionMismatch('Transaction identity reused with different content')
        return row[0] if row else None

    def transaction_result(self, transaction_id):
        from .contracts import CommitResult
        from ..storage import exact_time,_unpack
        row=self.connection.execute('SELECT revision,time_n,time_d FROM commits WHERE transaction_id=?',(transaction_id,)).fetchone()
        if row is None:return None
        table=self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transaction_receipts'").fetchone()
        receipt=self.connection.execute('SELECT first_sequence,last_sequence,command_result FROM transaction_receipts WHERE transaction_id=?',(transaction_id,)).fetchone() if table else None
        if receipt:
            first,last,command=receipt
        else:
            first,last=self.connection.execute('SELECT MIN(sequence),MAX(sequence) FROM events WHERE revision=?',(row[0],)).fetchone()
            command=None  # Legacy ledgers did not retain a per-transaction receipt.
        return CommitResult(row[0],str(exact_time({'n':row[1],'d':row[2]})),transaction_id,first,last,_unpack(command) if command is not None else None)
