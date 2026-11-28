"""SQLite workspace catalog adapter, separate from each run's semantic ledger."""
from __future__ import annotations
from pathlib import Path
import sqlite3
import threading
import time
from ..storage import canonical


class SQLiteRunCatalog:
    def __init__(self,path,*,read_only=False):
        self.path=Path(path);self.lock=threading.RLock()
        self._connection=sqlite3.connect(self.path.absolute().as_uri()+"?mode=ro",uri=True,timeout=30,check_same_thread=False) if read_only else sqlite3.connect(str(path),timeout=30,check_same_thread=False)
        self._connection.row_factory=sqlite3.Row
        if read_only:return
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.executescript("""
      CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY, directory TEXT NOT NULL, config TEXT NOT NULL,
        status TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
        frontier TEXT NOT NULL DEFAULT '{}', error TEXT, parent TEXT);
      CREATE TABLE IF NOT EXISTS commands (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, operation TEXT NOT NULL,
        request TEXT NOT NULL, status TEXT NOT NULL, response TEXT,
        created REAL NOT NULL);
      CREATE INDEX IF NOT EXISTS pending_commands ON commands(run_id,status,created);
      CREATE TABLE IF NOT EXISTS views (
        run_id TEXT NOT NULL, id TEXT NOT NULL, definition TEXT NOT NULL,
        PRIMARY KEY(run_id,id));
      CREATE TABLE IF NOT EXISTS worker_leases (
        run_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, heartbeat REAL NOT NULL);
    """)
        self._connection.commit()

    def __enter__(self):
        self.lock.acquire();self._connection.__enter__();return self
    def __exit__(self,*args):
        try:return self._connection.__exit__(*args)
        finally:self.lock.release()
    def close(self):self._connection.close()
    def run(self,run_id):
        row=self._connection.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
        return dict(row) if row else None
    def run_by_directory(self,directory):
        row=self._connection.execute("SELECT * FROM runs WHERE directory=?",(str(directory),)).fetchone()
        return dict(row) if row else None
    def run_rows(self):return [dict(r) for r in self._connection.execute("SELECT * FROM runs ORDER BY rowid DESC")]
    def insert_run(self,run_id,directory,config,status,*,generation=0,frontier=None,parent=None,replace=False,ignore=False):
        verb="INSERT OR REPLACE" if replace else "INSERT OR IGNORE" if ignore else "INSERT"
        self._connection.execute(verb+" INTO runs(id,directory,config,status,generation,frontier,parent) VALUES(?,?,?,?,?,?,?)",
            (run_id,str(directory),canonical(config),status,generation,canonical(frontier or {}),canonical(parent) if parent is not None else None))
    def update_run(self,run_id,**fields):
        allowed={'status','generation','frontier','error'}
        if not fields or not fields.keys()<=allowed:raise ValueError('Unsupported run metadata update')
        keys=list(fields);values=[canonical(fields[k]) if k=='frontier' else fields[k] for k in keys]
        self._connection.execute('UPDATE runs SET '+','.join(k+'=?' for k in keys)+' WHERE id=?',(*values,run_id))
    def command(self,command_id):
        row=self._connection.execute('SELECT * FROM commands WHERE id=?',(command_id,)).fetchone()
        return dict(row) if row else None
    def insert_command(self,command_id,run_id,operation,request,status='pending',response=None):
        self._connection.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?)',(command_id,run_id,operation,canonical(request),status,canonical(response) if response is not None else None,time.time()))
    def update_command(self,command_id,*,status=None,response=None):
        if status is None:self._connection.execute('UPDATE commands SET response=? WHERE id=?',(canonical(response),command_id))
        else:self._connection.execute('UPDATE commands SET status=?,response=? WHERE id=?',(status,canonical(response),command_id))
    def pending_commands(self,run_id=None,*,controls_only=False,operation=None):
        sql="SELECT * FROM commands WHERE status='pending'";args=[]
        if run_id is not None:sql+=' AND run_id=?';args.append(run_id)
        if controls_only:sql+=" AND operation NOT IN ('create','branch')"
        if operation is not None:sql+=' AND operation=?';args.append(operation)
        return [dict(r) for r in self._connection.execute(sql+' ORDER BY created,id',args)]
    def controls_waiting(self,run_id,*,operation=None,controls_only=True):
        sql="SELECT 1 FROM commands WHERE run_id=? AND status='pending'";args=[run_id]
        if controls_only:sql+=" AND operation NOT IN ('create','branch')"
        if operation is not None:sql+=' AND operation=?';args.append(operation)
        return self._connection.execute(sql+' LIMIT 1',args).fetchone() is not None
    def unfinished_creations(self):
        return [dict(r) for r in self._connection.execute("SELECT commands.id,commands.request FROM commands JOIN runs ON runs.id=commands.run_id WHERE commands.operation='create' AND runs.status='initializing'")]
    def command_count(self,run_id=None):
        return self._connection.execute('SELECT COUNT(*) FROM commands'+(' WHERE run_id=?' if run_id is not None else ''),(run_id,) if run_id is not None else ()).fetchone()[0]
    def lease(self,run_id):
        row=self._connection.execute('SELECT pid FROM worker_leases WHERE run_id=?',(run_id,)).fetchone()
        return tuple(row) if row else None
    def leases(self,run_id=None):
        return [dict(r) for r in self._connection.execute('SELECT * FROM worker_leases'+(' WHERE run_id=?' if run_id is not None else ''),(run_id,) if run_id is not None else ())]
    def lease_count(self):return self._connection.execute('SELECT COUNT(*) FROM worker_leases').fetchone()[0]
    def set_lease(self,run_id,pid,heartbeat):self._connection.execute('INSERT OR REPLACE INTO worker_leases VALUES(?,?,?)',(run_id,pid,heartbeat))
    def heartbeat(self,run_id,pid,heartbeat):self._connection.execute('UPDATE worker_leases SET heartbeat=? WHERE run_id=? AND pid=?',(heartbeat,run_id,pid))
    def remove_lease(self,run_id,pid):self._connection.execute('DELETE FROM worker_leases WHERE run_id=? AND pid=?',(run_id,pid))
    def save_view(self,run_id,definition):self._connection.execute('INSERT OR REPLACE INTO views VALUES(?,?,?)',(run_id,definition['id'],canonical(definition)))
    def views(self,run_id):
        import json
        return [json.loads(row[0]) for row in self._connection.execute('SELECT definition FROM views WHERE run_id=?',(run_id,))]
    def view_rows(self,run_id=None):
        return [tuple(r) for r in self._connection.execute('SELECT id,definition FROM views'+(' WHERE run_id=?' if run_id is not None else '')+' ORDER BY id',(run_id,) if run_id is not None else ())]
