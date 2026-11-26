"""Relocate one registered immutable checkpoint, preserving its original paths.

This operator tool never edits the live ledger or checkpoint content. It is not
part of simulation execution. A verified coordinator is briefly stopped only
for final generation checks and atomic symlink publication, then always resumed.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import time
import uuid


def digest(path):
    checksum=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(8*1024**2),b""):checksum.update(block)
    return checksum.hexdigest()


def signature(path):
    value=Path(path).stat()
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)


def registered(ledger,checkpoint):
    connection=sqlite3.connect(f"file:{ledger}?mode=ro",uri=True,timeout=2)
    try:
        return connection.execute("SELECT revision,path,checksum FROM checkpoints WHERE path=?",(str(checkpoint),)).fetchone()
    finally:connection.close()


def sidecar_revision(path):
    connection=sqlite3.connect(f"file:{path}?mode=ro&immutable=1",uri=True,timeout=2)
    try:return connection.execute("SELECT MAX(revision) FROM commits").fetchone()[0]
    finally:connection.close()


def check_files(ledger,checkpoint,revision):
    row=registered(ledger,checkpoint)
    if row is None or row[0]!=revision:raise ValueError("Requested revision is not the registered checkpoint")
    sidecar=checkpoint.with_suffix(".history.sqlite")
    if sidecar.resolve()==ledger.resolve():raise ValueError("Checkpoint sidecar cannot be the live ledger")
    if checkpoint.with_suffix(checkpoint.suffix+".partial").exists() or list(sidecar.parent.glob(sidecar.name+".*.partial")):
        raise ValueError("Checkpoint publication is in progress; partial files are never relocated")
    with checkpoint.open("rb") as stream:prefix=stream.read(160)
    match=re.match(rb'\{"checksum":"([0-9a-f]{64})","document":',prefix)
    if match is None or match[1].decode()!=row[2]:raise ValueError("Checkpoint envelope and registered checksum disagree")
    if sidecar_revision(sidecar)!=revision:raise ValueError("Sidecar and registered checkpoint revisions disagree")
    return row,[checkpoint,sidecar]


def checkpoint_pins(checkpoint):
    """Read the canonical envelope's leading pin object, not its large state."""
    prefix=b"";marker=b'"artifact_pins":'
    with Path(checkpoint).open("rb") as stream:
        while True:
            block=stream.read(64*1024)
            if not block:raise ValueError("Checkpoint artifact pin object is missing or incomplete")
            prefix+=block
            position=prefix.find(marker)
            if position<0:
                if len(prefix)>64*1024:raise ValueError("Checkpoint does not have the canonical leading artifact pins")
                continue
            try:return json.JSONDecoder().raw_decode(prefix[position+len(marker):].decode())[0]
            except (json.JSONDecodeError,UnicodeDecodeError):continue


def copy_pins(checkpoint,destination):
    results=[]
    for pin in checkpoint_pins(checkpoint).get("models",[]):
        relative=Path(pin["path"])
        if relative.is_absolute() or ".." in relative.parts:raise ValueError("Model pin must use a relative checkpoint path")
        source=checkpoint.parent/relative;target=destination/relative
        if checkpoint.parent.resolve() not in source.resolve().parents:raise ValueError("Model pin escapes checkpoint directory")
        target.parent.mkdir(parents=True,exist_ok=True)
        item=copy_verified(source,target)
        if item["sha256"]!=pin["sha256"]:raise ValueError("Model pin checksum differs from checkpoint metadata")
        results.append(item)
    sync_directory(destination)
    return results


def process_identity(pid,ledger):
    if pid<=1 or pid==os.getpid():raise ValueError("A distinct coordinator PID is required")
    process=Path(f"/proc/{pid}")
    if process.stat().st_uid!=os.getuid():raise ValueError("Coordinator belongs to a different operating-system user")
    fields=(process/"stat").read_text().rsplit(")",1)[1].split()
    wanted=signature(ledger)[:2];owns=False
    for descriptor in (process/"fd").iterdir():
        try:
            value=descriptor.stat()
            if (value.st_dev,value.st_ino)==wanted:
                flags=next(line.split()[1] for line in (process/"fdinfo"/descriptor.name).read_text().splitlines()
                           if line.startswith("flags:"))
                if int(flags,8)&os.O_ACCMODE==os.O_RDWR:owns=True;break
        except OSError:continue
    if not owns:raise ValueError("PID does not hold a writable handle to the explicitly named live ledger")
    return {"start_ticks":fields[19],"state":fields[0],"ledger_device_inode":wanted}


def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def copy_verified(source,target):
    before=signature(source)
    if target.exists():
        source_hash=digest(source)
        if digest(target)!=source_hash:raise FileExistsError(f"Existing archive differs: {target}")
    else:
        temporary=target.with_name(target.name+"."+uuid.uuid4().hex+".partial")
        checksum=hashlib.sha256()
        with source.open("rb") as reader,temporary.open("xb") as writer:
            for block in iter(lambda:reader.read(8*1024**2),b""):
                writer.write(block);checksum.update(block)
            writer.flush();os.fsync(writer.fileno())
        source_hash=checksum.hexdigest()
        if digest(temporary)!=source_hash:raise ValueError("Copied checkpoint checksum mismatch")
        # Link publication refuses to replace an existing immutable archive.
        os.link(temporary,target);temporary.unlink()
        target.chmod(0o444)
        with target.open("rb") as stream:os.fsync(stream.fileno())
        sync_directory(target.parent)
    if signature(source)!=before:raise ValueError("Source checkpoint changed during archival copy")
    return {"source":str(source),"target":str(target),"sha256":source_hash,"bytes":before[2],"source_signature":list(before)}


@contextmanager
def stopped_coordinator(pid,ledger,expected,record):
    current=process_identity(pid,ledger)
    if current["start_ticks"]!=expected["start_ticks"]:raise ValueError("Coordinator PID was reused")
    if current["state"] in {"T","t","Z","X"}:raise ValueError("Coordinator is already stopped or exited")
    started=time.monotonic();sent=False
    try:
        os.kill(pid,signal.SIGSTOP);sent=True
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if process_identity(pid,ledger)["state"] in {"T","t"}:break
            time.sleep(.005)
        else:raise TimeoutError("Coordinator did not acknowledge SIGSTOP")
        yield
    finally:
        if sent:
            try:os.kill(pid,signal.SIGCONT)
            except ProcessLookupError:pass
        record["coordinator_stop_seconds"]=time.monotonic()-started


def archive(ledger,checkpoint,revision,destination,pid):
    ledger=Path(ledger).absolute();checkpoint=Path(checkpoint).absolute()
    if ledger.is_symlink():raise ValueError("The live ledger must not be relocated or redirected")
    destination=Path(destination).absolute()/f"revision-{revision}"
    if destination==ledger.parent or ledger.parent in destination.parents:raise ValueError("Archive must be outside the run directory")
    destination.mkdir(parents=True,exist_ok=True)
    with (destination/"archive.lock").open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        expected=process_identity(pid,ledger);row,sources=check_files(ledger,checkpoint,revision)
        manifest=destination/"relocation.json"
        if all(source.is_symlink() and source.resolve()==(destination/source.name).resolve() for source in sources):
            return json.loads(manifest.read_text())
        began=time.time();files=[copy_verified(source,destination/source.name) for source in sources]
        pins=copy_pins(checkpoint,destination)
        result={"schema":"zombie-sim/checkpoint-relocation-v1","status":"COPIED","revision":revision,
                "live_ledger":str(ledger),"coordinator_pid":pid,"started_at_unix":began,
                "registered_checksum":row[2],"files":files,"model_pins":pins,"coordinator_stop_seconds":0.0,
                "hashes_verified_before_stop":True}
        try:
            with stopped_coordinator(pid,ledger,expected,result):
                if registered(ledger,checkpoint)!=row:raise ValueError("Checkpoint registration changed before publication")
                check_files(ledger,checkpoint,revision)
                # Registered checkpoints are immutable and future publication
                # uses os.replace. Unchanged inode/ctime/mtime/size therefore
                # validates the already-verified hashes without hashing many
                # gigabytes again while the coordinator is stopped.
                for item in files+pins:
                    if signature(item["source"])!=tuple(item["source_signature"]):raise ValueError("Checkpoint generation changed before publication")
                for item in files:
                    source=Path(item["source"])
                    link=source.with_name(source.name+"."+uuid.uuid4().hex+".archive-link")
                    link.symlink_to(item["target"]);os.replace(link,source)
                sync_directory(checkpoint.parent)
                result["status"]="APPLIED"
        finally:
            result["finished_at_unix"]=time.time()
            temporary=manifest.with_suffix(".partial")
            with temporary.open("w") as stream:
                json.dump(result,stream,indent=2);stream.write("\n");stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,manifest);sync_directory(destination)
        return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("ledger");parser.add_argument("checkpoint");parser.add_argument("revision",type=int)
    parser.add_argument("destination");parser.add_argument("--coordinator",required=True,type=int)
    arguments=parser.parse_args()
    print(json.dumps(archive(arguments.ledger,arguments.checkpoint,arguments.revision,arguments.destination,arguments.coordinator)),flush=True)
