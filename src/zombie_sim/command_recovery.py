"""Durable command receipts and factual inspection of their effects and leases."""
from __future__ import annotations
import json
import os
import time
from .storage import canonical


def reply(manager,response):
    """Pin creation/branch receipts to their actual durable initial boundary."""
    if response.get("status")!="applied":return response
    response=dict(response)
    if response.get("revision") is None and response.get("run_id"):
        until=time.monotonic()+30
        while True:
            row=manager._row(response["run_id"])
            if row["status"]!="initializing":break
            if time.monotonic()>until:raise TimeoutError("Run initialization did not publish its command boundary")
            time.sleep(.01)
        if row["status"] == "failed":
            raise ValueError(row["error"] or "Run initialization failed")
        history=manager.history(response["run_id"])
        try:
            with manager.lock:
                command=manager.connection.execute("SELECT operation FROM commands WHERE id=?",(response["command_id"],)).fetchone()
            selected=history.state_at(revision=0 if command and command["operation"]=="create" else None)
            response.update(revision=str(selected["revision"]),time=str(selected["time"]))
        finally:history.close()
        with manager.lock,manager.connection:
            manager.connection.execute("UPDATE commands SET response=? WHERE id=?",(canonical(response),response["command_id"]))
    from .faults import hit
    hit("command_after_effect_before_ack",command_id=response.get("command_id"),run_id=response.get("run_id"),durable_revision=response.get("revision"))
    return response


def inspect_command(manager,command_id):
    response=manager.command_result(command_id)
    with manager.lock:
        row=manager.connection.execute("SELECT * FROM commands WHERE id=?",(command_id,)).fetchone()
        record=dict(row);record["request"]=json.loads(record["request"]);record["response"]=json.loads(record["response"]) if record["response"] else None
    affected=response.get("run_id",record["run_id"])
    until=time.monotonic()+15
    while True:
        with manager.lock:
            leases=[dict(row) for row in manager.connection.execute("SELECT * FROM worker_leases WHERE run_id=?",(affected,))]
        active=[]
        for lease in leases:
            try:os.kill(lease["pid"],0);active.append(lease)
            except ProcessLookupError:pass
        if record["operation"]!="stop" or not active or time.monotonic()>until:break
        time.sleep(.02)
    effects=[]
    if response["status"]=="applied":
        if record["operation"] in {"create", "branch"}:
            effects=[dict(manager._row(affected))]
        else:
            history=manager.history(affected)
            try:
                if record["operation"]=="intervene":
                    effects=[event for event in history.events(kind="intervention") if event.get("intervention")==command_id]
                else:
                    durable=history.command_result(command_id)
                    effects=[durable] if durable else []
            finally:history.close()
    return {"command_id":command_id,"status":response["status"],"semantic_effects":effects,
            "resulting_run_ids":[affected] if record["operation"] in {"create","branch"} and response["status"]=="applied" else [],
            "active_worker_leases":active,"active_worker_lease_count":len(active),
            "effective_revision":response.get("revision"),"effective_time":response.get("time")}
