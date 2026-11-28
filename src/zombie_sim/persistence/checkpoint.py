"""Portable prefix and checkpoint file operations owned by persistence adapters."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from ..storage import History,canonical,_pack


def _digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def copy_history_prefix(source,destination,revision,state):
    """Copy a verified prefix to a new database without changing its revisions."""
    source,destination=Path(source),Path(destination)
    if source.resolve()==destination.resolve():
        raise ValueError("History prefix copy requires a different destination")
    if not source.is_file():
        raise FileNotFoundError(f"Checkpoint history is unavailable: {source}; retain the checkpoint's .history.sqlite sidecar")
    if destination.exists() and destination.stat().st_size:
        raise ValueError(f"History destination already exists: {destination}")
    read=History(source,read_only=True)
    try:
        if read.revision<revision:
            raise ValueError("Checkpoint revision is beyond the source history")
        prefix_state=read.state_at(revision=revision)
        if _digest(prefix_state)!=_digest(state):
            raise ValueError("Checkpoint state does not match its source ledger revision")
        destination.parent.mkdir(parents=True,exist_ok=True)
        target=sqlite3.connect(destination)
        try:
            read.connection.backup(target)
            with target:
                tables={row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                target.execute("DELETE FROM participants WHERE sequence IN (SELECT sequence FROM events WHERE revision>?)",(revision,))
                target.execute("DELETE FROM events WHERE revision>?",(revision,))
                if "transaction_requests" in tables:
                    target.execute("DELETE FROM transaction_requests WHERE transaction_id IN (SELECT transaction_id FROM commits WHERE revision>?)",(revision,))
                target.execute("DELETE FROM commits WHERE revision>?",(revision,))
                if "transaction_receipts" in tables:
                    target.execute("DELETE FROM transaction_receipts WHERE revision>?",(revision,))
                if "runtime_commits" in tables:
                    target.execute("DELETE FROM runtime_commits WHERE revision>?",(revision,))
                if "control_commands" in tables:
                    target.execute("DELETE FROM control_commands WHERE revision>? OR revision IS NULL OR status='pending'",(revision,))
                target.execute("DELETE FROM metadata WHERE key IN ('active_control_command','control_state')")
                # Checkpoint paths belong to the source run and cannot be reused.
                target.execute("DELETE FROM checkpoints")
                target.execute("DELETE FROM live_entities")
                target.execute("DELETE FROM live_state")
                target.execute("INSERT INTO live_state VALUES(1,?,?)",(revision,_pack(state)))
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            target.close()
    finally:
        read.close()


def write_checkpoint_document(payload,revision,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    document={"schema":"zombie-sim/checkpoint-v1","ledger_revision":revision,"payload":payload}
    envelope={"checksum":_digest(document),"document":document}
    temporary=path.with_suffix(path.suffix+".partial")
    with temporary.open("w") as stream:
        stream.write(canonical(envelope));stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    descriptor=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return str(path)


def read_checkpoint_document(path):
    envelope=json.loads(Path(path).read_text())
    if _digest(envelope["document"])!=envelope.get("checksum"):raise ValueError("Checkpoint checksum mismatch")
    return envelope["document"]["payload"]


def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def owned_generation(checkpoint,publication):
    """Recognize only a publisher-owned sibling named in its own envelope."""
    if not isinstance(publication,dict) or publication.get('schema')!='zombie-sim/checkpoint-publication-v1':return None
    sidecar=Path(checkpoint).with_suffix('.history.sqlite')
    name=publication.get('generation')
    if not isinstance(name,str) or Path(name).name!=name or not re.fullmatch(r'.+\.history\.sqlite\.[0-9a-f]{32}\.generation\.history\.sqlite',name):
        raise ValueError('Invalid owned checkpoint generation name')
    # A successfully published portable pair may be renamed. Its canonical
    # sidecar remains authoritative, but it does not own the original name's
    # pending generation for recovery or cleanup.
    if not re.fullmatch(re.escape(sidecar.name)+r'\.[0-9a-f]{32}\.generation\.history\.sqlite',name):return None
    return sidecar.parent/name


def previous_publication(checkpoint,file_digest):
    """Read prior ownership before constructing the potentially large new payload."""
    path=Path(checkpoint)
    if not path.exists() and not path.is_symlink():return None,None
    payload=read_checkpoint_document(path)
    publication=payload.get('history_publication')
    generation=owned_generation(path,publication)
    # An existing generation means its envelope was published before canonical
    # promotion. The canonical still belongs to the preceding envelope.
    checksum=publication.get('previous_sha256') if generation is not None and generation.exists() else payload.get('history_sha256')
    adjacent=path.with_suffix('.history.sqlite')
    if checksum is None and (adjacent.exists() or adjacent.is_symlink()):
        checksum=file_digest(adjacent)
    return checksum,generation


def resolve_checkpoint_history(checkpoint,payload,file_digest):
    """Resolve portable adjacency, including an interrupted two-file promotion.

    Arbitrary corruption never triggers fallback. A canonical sidecar may be
    superseded by the local pending generation only if its bytes are exactly
    the previous checksum explicitly recorded by the newly published envelope.
    """
    path=Path(checkpoint);adjacent=path.with_suffix('.history.sqlite')
    publication=payload.get('history_publication')
    generation=owned_generation(path,publication)
    expected=payload.get('history_sha256')
    if adjacent.exists() or adjacent.is_symlink():
        actual=file_digest(adjacent) if expected else None
        if not expected or actual==expected:return adjacent
        if generation is None or actual!=publication.get('previous_sha256'):
            raise ValueError('Checkpoint history sidecar checksum mismatch')
        candidate=generation
    elif generation is not None and generation.exists():candidate=generation
    else:candidate=Path(payload['history_path'])
    try:
        if expected and file_digest(candidate)!=expected:
            raise ValueError('Checkpoint history sidecar checksum mismatch')
    except FileNotFoundError:
        # The publisher may promote this exact generation between selection
        # and opening it. Only the expected checksum can authorize that race.
        if candidate==generation and not generation.exists() and file_digest(adjacent)==expected:
            return adjacent
        raise
    return candidate


def envelope_owns_generation(checkpoint,generation):
    try:
        payload=read_checkpoint_document(checkpoint)
        return owned_generation(checkpoint,payload.get('history_publication'))==generation
    except (OSError,ValueError,KeyError,TypeError):return False


class CheckpointAdapter:
    def __init__(self,history):self.history=history
    def save(self,payload,path=None):return self.history.save_checkpoint(payload,path)
    def load(self,path=None):return self.history.load_checkpoint(path)
    def export_prefix(self,destination,revision,state):
        if self.history.path is None:raise ValueError("This nondurable journal has no portable SQLite prefix")
        copy_history_prefix(self.history.path,destination,revision,state)
        return str(destination)
