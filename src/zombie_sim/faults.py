"""Explicit process-local fault injection for durability verification.

Disabled in ordinary operation. Hooks run at real transaction boundaries; the
driver observes the resulting committed ledger rather than fabricated failures.
"""
from __future__ import annotations
import errno
import json
import os
from pathlib import Path

_armed=None


def arm(point, *, occurrence=1, persistent=False, error=None, trace_path=None, crash=False,omit_read_key=None):
    global _armed
    _armed={"point":point,"remaining":int(occurrence),"persistent":bool(persistent),
            "error":error,"trace_path":str(trace_path) if trace_path else None,"crash":bool(crash),"omit_read_key":omit_read_key}


def clear():
    global _armed
    _armed=None


def omit_dependency(declarations,**context):
    """Delete one actually declared read, leaving independent read evidence intact."""
    global _armed
    fault=_armed
    if not fault or fault["point"]!="dependency_validation":return
    key=fault["omit_read_key"]
    if key not in declarations:return
    fault["remaining"]-=1
    if fault["remaining"]>0:return
    if not fault["persistent"]:_armed=None
    declarations.pop(key)
    if fault["trace_path"]:
        path=Path(fault["trace_path"]);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("a") as stream:
            stream.write(json.dumps({"point":"dependency_validation","pid":os.getpid(),"omitted_read_key":key,**context})+"\n")
            stream.flush();os.fsync(stream.fileno())


def hit(point, **context):
    global _armed
    fault=_armed
    if not fault or point!=fault["point"]:return
    fault["remaining"]-=1
    if fault["remaining"]>0:return
    if not fault["persistent"]:_armed=None
    record={"point":point,"pid":os.getpid(),"error":fault["error"],**context}
    if fault["trace_path"]:
        path=Path(fault["trace_path"]);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("a") as stream:
            stream.write(json.dumps(record)+"\n");stream.flush();os.fsync(stream.fileno())
    if fault["crash"]:os._exit(86)
    code=getattr(errno,fault["error"] or "EIO",errno.EIO)
    raise OSError(code,os.strerror(code))
