"""Explicit process-local fault injection for durability verification.

Disabled in ordinary operation. Hooks run at real transaction boundaries; the
driver observes the resulting committed ledger rather than fabricated failures.
"""
from __future__ import annotations
import errno
import json
import os
from pathlib import Path

class FaultInjector:
    """Own one independently armed durability-verification failure.

    Injection is disabled until arm() is called. Storage uses the process-local
    default instance through compatibility functions; isolated instances let
    tests prepare schedules without affecting another experiment.
    """

    def __init__(self):
        self._armed = None

    def arm(self,point, *, occurrence=1, persistent=False, error=None, trace_path=None, crash=False,omit_read_key=None):
        self._armed={"point":point,"remaining":int(occurrence),"persistent":bool(persistent),
                "error":error,"trace_path":str(trace_path) if trace_path else None,"crash":bool(crash),"omit_read_key":omit_read_key}

    def clear(self):
        self._armed=None

    def omit_dependency(self,declarations,**context):
        """Delete one actually declared read, leaving independent read evidence intact."""
        fault=self._armed
        if not fault or fault["point"]!="dependency_validation":return
        key=fault["omit_read_key"]
        if key not in declarations:return
        fault["remaining"]-=1
        if fault["remaining"]>0:return
        if not fault["persistent"]:self._armed=None
        declarations.pop(key)
        if fault["trace_path"]:
            path=Path(fault["trace_path"]);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("a") as stream:
                stream.write(json.dumps({"point":"dependency_validation","pid":os.getpid(),"omitted_read_key":key,**context})+"\n")
                stream.flush();os.fsync(stream.fileno())

    def hit(self,point, **context):
        fault=self._armed
        if not fault or point!=fault["point"]:return
        fault["remaining"]-=1
        if fault["remaining"]>0:return
        if not fault["persistent"]:self._armed=None
        record={"point":point,"pid":os.getpid(),"error":fault["error"],**context}
        if fault["trace_path"]:
            path=Path(fault["trace_path"]);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("a") as stream:
                stream.write(json.dumps(record)+"\n");stream.flush();os.fsync(stream.fileno())
        if fault["crash"]:os._exit(86)
        code=getattr(errno,fault["error"] or "EIO",errno.EIO)
        raise OSError(code,os.strerror(code))

DEFAULT_FAULT_INJECTOR = FaultInjector()


def arm(point, *, occurrence=1, persistent=False, error=None, trace_path=None, crash=False, omit_read_key=None):
    return DEFAULT_FAULT_INJECTOR.arm(point, occurrence=occurrence, persistent=persistent, error=error, trace_path=trace_path, crash=crash, omit_read_key=omit_read_key)


def clear():
    return DEFAULT_FAULT_INJECTOR.clear()


def omit_dependency(declarations, **context):
    return DEFAULT_FAULT_INJECTOR.omit_dependency(declarations, **context)


def hit(point, **context):
    return DEFAULT_FAULT_INJECTOR.hit(point, **context)
