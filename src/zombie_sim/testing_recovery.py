"""Read-only capture evaluation of a completely recorded workflow.

This adapter never creates or continues a simulation. Every requested command
must already have the matching durable identity, payload, and applied receipt.
It imports normalization functions, never acceptance cases or expectations.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from .config import resolve_config
from .runtime import _decode, materialize_snapshot
from .storage import History, _unpack, canonical, exact_time
from .testing import fixture_config, normalize_snapshot, request_numbers
from .testing_workflows import _semantic


class RecoveryEvidenceError(ValueError):
    """The supplied primary ledger cannot prove the requested completed work."""


def require(condition, message):
    if not condition:
        raise RecoveryEvidenceError(message)


class EventHeaders:
    """Stream actual ID/kind/revision fields needed by the common normalizer.

    Full event payloads remain unmodified in the original ledger. Avoid retaining
    every recorded observation just to construct the semantic namespace map.
    """
    def __init__(self, history, revision):
        self.history, self.revision = history, revision

    def __iter__(self):
        rows = self.history.connection.execute(
            "SELECT revision,kind,payload FROM events WHERE revision<=? ORDER BY sequence",
            (self.revision,),
        )
        for revision, kind, payload in rows:
            event = _unpack(payload)
            require(int(event.get("revision", -1)) == revision and event.get("kind") == kind,
                    "Event payload disagrees with its durable index")
            require(isinstance(event.get("id"), str), "Event has no recorded identity")
            yield {"id": event["id"], "kind": kind, "revision": revision}


class CompletedRun:
    def __init__(self, path, spec, declared_commands):
        self.path = Path(path).absolute()
        require(self.path.is_file(), f"Missing primary ledger: {self.path}")
        self.history = History(self.path, read_only=True)
        self.cache = None
        self.initial_cache = None
        try:
            self.history.connection.execute("PRAGMA query_only=ON")
            self.history.connection.execute("BEGIN")
            self.frontier = self.history.revision
            require(self.frontier >= 0, "Ledger has no committed initial boundary")
            self._verify_history()
            initial = self.history.runtime_at(0)
            require(initial is not None, "Missing initial runtime journal")
            recorded = _decode(initial["attributes"])
            expected = resolve_config(fixture_config(spec["world"], spec.get("config", {})))
            require(canonical(recorded.get("config")) == canonical(expected),
                    "Declared resolved configuration differs from the recorded initial configuration")
            self.config = recorded["config"]
            self.receipts = {}
            names = {row[0] for row in self.history.connection.execute(
                "SELECT key FROM metadata WHERE key LIKE 'script_command:%'"
            )}
            require(names == {"script_command:" + identity for identity, _, _ in declared_commands},
                    "Recorded script command identities differ from the declared workflow")
            controls = {row[0] for row in self.history.connection.execute("SELECT command_id FROM control_commands")}
            require(controls == {identity for identity, _, _ in declared_commands},
                    "Ledger contains missing or undeclared control receipts")
            previous = 0
            for identity, operation, payload in declared_commands:
                saved = self.history.get_metadata("script_command:" + identity)
                require(canonical(saved) == canonical({"operation": operation, "payload": payload}),
                        f"Recorded command payload differs: {identity}")
                receipt = self.history.command_result(identity)
                require(receipt is not None and receipt.get("status") == "applied",
                        f"Command is missing, pending, or failed: {identity}")
                require(receipt.get("command_id") == identity, f"Command identity differs: {identity}")
                revision = int(receipt["revision"])
                require(previous < revision <= self.frontier, f"Command revision is invalid: {identity}")
                row = self.history.connection.execute(
                    "SELECT time_n,time_d FROM commits WHERE revision=?", (revision,)
                ).fetchone()
                require(row is not None and exact_time(receipt["time"]) == exact_time(f"{row[0]}/{row[1]}"),
                        f"Command receipt does not match its committed time: {identity}")
                self.receipts[identity] = receipt
                previous = revision
            require(bool(declared_commands) and previous == self.frontier,
                    "The declared workflow does not reach the complete durable frontier")
            require(self.history.get_metadata("active_control_command") is None,
                    "A command is still active in the durable journal")
            last = self.receipts[declared_commands[-1][0]]
            require(last.get("run_status") == "completed" and last.get("control", {}).get("status") == "completed",
                    "The final command has no completed acknowledgement")
            require(self.history.get_metadata("control_state") == last.get("control"),
                    "Durable control state differs from the completed acknowledgement")
            state, kernel, attributes = self.at(self.frontier)
            self.identity = {"run_id": state["run_id"], "history": str(self.path)}
            require(all(receipt.get("run_id") == self.identity["run_id"] for receipt in self.receipts.values()),
                    "A command receipt belongs to another run")
            self.status = self.completed_status(state, kernel, attributes)
            self.cursor = 0
        except BaseException:
            self.close()
            raise

    def _verify_history(self):
        for table in ("commits", "runtime_commits"):
            count, low, high = self.history.connection.execute(
                f"SELECT COUNT(*),MIN(revision),MAX(revision) FROM {table}"
            ).fetchone()
            require(count == self.frontier + 1 and low == 0 and high == self.frontier,
                    f"Incomplete {table} revision sequence")
            for revision, payload, checksum in self.history.connection.execute(
                f"SELECT revision,patch,checksum FROM {table} ORDER BY revision"
            ):
                require(hashlib.sha256(payload).hexdigest() == checksum,
                        f"Corrupt {table} delta at revision {revision}")
        count, low, high, earliest, latest = self.history.connection.execute(
            "SELECT COUNT(*),MIN(sequence),MAX(sequence),MIN(revision),MAX(revision) FROM events"
        ).fetchone()
        require(not count or (low == 1 and high == count and 0 <= earliest <= latest <= self.frontier),
                "Incomplete event sequence or event outside the committed history")
        self.history_counts = {"revisions": self.frontier + 1, "events": count}

    def at(self, revision):
        if revision == 0 and self.initial_cache is not None:
            return self.initial_cache
        if self.cache is not None and self.cache[0] == revision:
            return self.cache[1:]
        state = self.history.state_at(revision=revision)
        kernel = self.history.runtime_at(revision)
        require(kernel is not None and kernel.get("schema") == "zombie-sim/runtime-journal-v1",
                f"Missing runtime boundary {revision}")
        attributes = _decode(kernel["attributes"])
        require(int(state.get("revision", -1)) == revision == int(attributes.get("revision", -1)),
                "World and runtime revisions differ")
        require(exact_time(state["time"]) == exact_time(attributes["time"]),
                "World and runtime times differ")
        require(canonical(attributes.get("config")) == canonical(self.config),
                "Runtime configuration changed within the requested workflow")
        if revision == 0:
            # Initial capture must not evict the already verified final world.
            self.initial_cache = (state, kernel, attributes)
        else:
            self.cache = (revision, state, kernel, attributes)
        return state, kernel, attributes

    @staticmethod
    def completed_status(state, kernel, attributes):
        time, horizon = exact_time(state["time"]), exact_time(attributes["horizon"])
        queue = [_decode(item) for item in kernel.get("queue", {}).values()]
        require(len({entry[3] for entry in queue}) == len(queue), "Duplicate pending scheduler identity")
        if time >= horizon and not any(exact_time(entry[0]) <= horizon for entry in queue):
            reason = "HORIZON"
        elif not any(agent["life"] > 0 for agent in state["agents"].values()):
            reason = "NO_LIVING_AGENTS"
        else:
            raise RecoveryEvidenceError("Completed acknowledgement precedes the actual terminal boundary")
        return {"state": "COMPLETED", "termination_reason": reason, "time": str(time)}

    def capture(self, what):
        require(what in {"initial_snapshot", "semantic_snapshot", "status"},
                f"Unsupported recovered capture: {what}")
        if what == "status":
            require(self.cursor == self.frontier, "Status requested before the completed boundary")
            return deepcopy(self.status)
        current, _, _ = self.at(self.cursor)
        aliases = {key: str(value.get("intent_id", key)) for key, value in current.get("occurrences", {}).items()}
        state, kernel, _ = self.at(0 if what == "initial_snapshot" else self.cursor)
        projected = materialize_snapshot(state)
        for aid, agent in projected["agents"].items():
            agent["model_memory"] = _decode(kernel.get("memories", {}).get(aid, {}))
        normalized = normalize_snapshot(projected, aliases, copy_snapshot=False)
        del projected
        return _semantic(SimpleNamespace(events=EventHeaders(self.history, self.cursor)), normalized)

    def close(self):
        self.cache = None
        self.initial_cache = None
        self.history.close()


class RecoveredWorkflowAdapter:
    def __init__(self, *, workdir, ledgers):
        self.workdir = Path(workdir)
        self.ledgers = {name: Path(path).absolute() for name, path in ledgers.items()}
        self.runs = {}

    def execute(self, request):
        require(request.get("kind") == "workflow", "Recovery supports completed workflows only")
        specs = request.get("setup", {}).get("runs", {})
        require(set(specs) == set(self.ledgers), "Explicit ledger aliases do not match the declared runs")
        declared = {name: [] for name in specs}
        for step in request["steps"]:
            require(step["op"] in {"run.create", "run.script", "run.capture"},
                    f"Unsupported recovery operation: {step['op']}")
            require(step.get("run") in specs, "Unknown declared run alias")
            if step["op"] == "run.script":
                require(not step.get("draws"), "Recovery cannot verify unjournaled random-value injection")
                for substep in step["steps"]:
                    require(substep["op"] in {"submit", "submit_batch", "advance", "intervene"},
                            "Script operation has no durable idempotent receipt")
                    commands = declared[step["run"]]
                    commands.append((f"{step['run']}-script-{len(commands)}", substep["op"],
                                     request_numbers({k: deepcopy(v) for k, v in substep.items() if k != "op"})))
        captures = {}
        positions = {name: 0 for name in specs}
        try:
            for step in request["steps"]:
                name, operation = step["run"], step["op"]
                if operation == "run.create":
                    require(name not in self.runs, "Repeated run creation is not supported")
                    self.runs[name] = CompletedRun(self.ledgers[name], specs[name], declared[name])
                    result = self.runs[name].identity
                else:
                    require(name in self.runs, "Run operation precedes its creation")
                    run = self.runs[name]
                    if operation == "run.script":
                        result = None
                        for _ in step["steps"]:
                            identity = declared[name][positions[name]][0]
                            receipt = run.receipts[identity]
                            run.cursor = int(receipt["revision"])
                            positions[name] += 1
                            result = {"time": receipt["time"], "revision": run.cursor}
                    else:
                        result = run.capture(step["what"])
                if "label" in step:
                    captures[step["label"]] = result
            return {"captures": captures, "diagnostics": {
                "normalization": "ordered-semantic-v1",
                "workers": {name: run.identity for name, run in self.runs.items()},
                "evaluation": "recovered-capture-evaluation",
                "source_mode": "read-only completed primary ledger; no simulation executed",
                "verified_history": {name: run.history_counts for name, run in self.runs.items()},
            }}
        finally:
            self.close()

    def close(self):
        for run in self.runs.values():
            run.close()
        self.runs.clear()


def create_adapter(*, workdir):
    encoded = os.environ.get("ZOMBIE_RECOVERY_LEDGERS")
    require(encoded is not None, "Set ZOMBIE_RECOVERY_LEDGERS to an explicit JSON alias-to-ledger mapping")
    mapping = json.loads(encoded)
    require(isinstance(mapping, dict) and bool(mapping), "Recovery ledger mapping must be a nonempty object")
    return RecoveredWorkflowAdapter(workdir=workdir, ledgers=mapping)
