"""Durable command receipts and factual inspection of their effects and leases."""
from __future__ import annotations
import json
import os
import time
from .storage import canonical, exact_time


class CommandReceiptService:
    """Recover committed command cursors and inspect factual worker effects."""
    def reply(self, manager,response):
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
                    command=manager.catalog.command(response["command_id"])
                stored=json.loads(command["response"]) if command and command["response"] else {}
                if command and command["operation"]=="create":
                    revision=0
                else:
                    # Branch reservations publish their effective boundary before
                    # launching the child. Prefer that pin to a later live frontier.
                    revision=stored.get("revision",json.loads(row["frontier"]).get("revision"))
                if revision is None:
                    selected=history.head()
                else:
                    selected=history.head(int(revision))
                if selected is None:raise ValueError("Command boundary is not present in committed history")
                # A receipt needs a committed cursor, not world reconstruction.
                # Scene/runtime reads retain their ordinary integrity validation.
                response.update(revision=str(selected[0]),time=str(exact_time({"n":selected[1],"d":selected[2]})))
            finally:history.close()
            with manager.lock,manager.catalog:
                manager.catalog.update_command(response["command_id"],response=response)
        from .faults import hit
        hit("command_after_effect_before_ack",command_id=response.get("command_id"),run_id=response.get("run_id"),durable_revision=response.get("revision"))
        return response


    def inspect(self, manager,command_id):
        response=manager.command_result(command_id)
        with manager.lock:
            row=manager.catalog.command(command_id)
            record=dict(row);record["request"]=json.loads(record["request"]);record["response"]=json.loads(record["response"]) if record["response"] else None
        affected=response.get("run_id",record["run_id"])
        until=time.monotonic()+15
        while True:
            with manager.lock:
                leases=manager.catalog.leases(affected)
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


_default_service = CommandReceiptService()


def reply(manager, response):
    """Compatibility entry point; see :class:`CommandReceiptService`."""
    return _default_service.reply(manager, response)


def inspect_command(manager, command_id):
    """Compatibility entry point; see :class:`CommandReceiptService`."""
    return _default_service.inspect(manager, command_id)
