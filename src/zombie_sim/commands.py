"""Durable idempotent commands for scripted research runs.

The same command can be retried after a lost caller acknowledgement or a hard
process failure. Admission and its acknowledgement share the engine transaction.
"""
from copy import deepcopy
from .storage import canonical


class ScriptCommandService:
    """Admit scripted commands with identity-checked durable acknowledgements."""
    def execute(self, sim, operation, payload, command_id, *, desired_control=None):
        if operation not in {"submit","submit_batch","advance","intervene"}:
            raise ValueError(f"Unsupported scripted operation: {operation}")
        command_id=str(command_id)
        identity={"operation":operation,"payload":deepcopy(payload)}
        key="script_command:"+command_id
        previous=sim.history.get_metadata(key)
        if previous is not None and canonical(previous)!=canonical(identity):
            raise ValueError("A command ID cannot be reused for different content")
        completed=sim.history.command_result(command_id)
        if completed is not None:return completed
        sim.history.set_metadata(key,identity)
        request=deepcopy(payload)
        active={"id":command_id,"operation":"script_submit" if operation in {"submit","submit_batch"} else operation,
                "request":request,"desired_control":deepcopy(desired_control or {"status":"paused","generation":0,"pacing":0}),
                "script_operation":operation}
        if operation=="advance":active["target"]=str(payload["to"])
        sim.history.set_metadata("active_control_command",active)
        sim._active_control_command=active
        if operation=="submit":sim.submit_intents(payload)
        elif operation=="submit_batch":sim.submit_intents(payload["intents"])
        elif operation=="advance":sim.advance_until(payload["to"],return_snapshot=False)
        elif operation=="intervene":sim.intervene(payload["change"],at=payload.get("at"),id=payload.get("id",command_id))
        result=sim.history.command_result(command_id)
        if result is None:
            raise RuntimeError("Scripted operation completed without its durable acknowledgement")
        return result


_default_service = ScriptCommandService()


def execute_script_command(sim, operation, payload, command_id, *, desired_control=None):
    """Compatibility entry point; see :class:`ScriptCommandService`."""
    return _default_service.execute(sim, operation, payload, command_id, desired_control=desired_control)
