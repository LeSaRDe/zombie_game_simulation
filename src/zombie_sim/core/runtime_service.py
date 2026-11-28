"""Runtime lifecycle owns exact continuation and atomic journal publication."""
from __future__ import annotations
from copy import deepcopy
import heapq
import json
import os
from pathlib import Path
import tempfile
import uuid
from ..storage import canonical, exact_time
from ..persistence import PersistenceBundleFactory
from ..persistence.checkpoint import (previous_publication, sync_directory,
                                     envelope_owns_generation, resolve_checkpoint_history, owned_generation)
from ..persistence.versioning import implementation_manifest, validate_implementation
from ..runtime import SCHEMA, _EPHEMERAL, JOURNAL_SCHEMA, _memory_encode, _contains_unavailable, _stamp, _encode, _decode, _digest, _file_digest, _validated_payload, _copy_history, _recorded_histories, _journal_attributes
from .composition import SimulationServiceFactory


class RuntimeService:
    """Persistence boundary used by coordinator transactions and restore APIs."""

    def __init__(self, context=None):
        self.context = context

    def serialize(self,sim):
        """Encode explicitly owned state at one committed causal boundary."""
        from ..execution.rule_bindings import validate_rule_restart
        validate_rule_restart(sim._runtime_state.attributes(detach=False).get('rule_bindings'), sim._runtime_rules)
        if getattr(sim,"_dirty",None):
            raise ValueError("Runtime snapshots require a committed boundary; pending state writes exist")
        if sim.revision!=sim.history.revision:
            raise ValueError("Runtime revision differs from durable history; cannot checkpoint an uncommitted boundary")
        state=sim.state_coordinator.current_world.to_record()
        values=sim._runtime_state.attributes(detach=False)
        attributes={key:_encode(value) for key,value in values.items() if key!="memories"}
        attributes["state"]=_encode(state)
        attributes["memories"]={str(key):_memory_encode(sim,key,value) for key,value in sim.memories.items()}
        payload={"schema":SCHEMA,"attributes":attributes,"history_path":str(Path(sim.history_path).absolute()),
                 "history_revision":int(sim.revision),"state_sha256":_digest(state),"attributes_sha256":_digest(attributes),
                 "event_history":"ledger","implementation_manifest":deepcopy(sim._runtime_implementation_manifest)}
        payload["restart_capability"]="STATE_REPLAY_ONLY" if _contains_unavailable(attributes["memories"]) else "EXACT"
        return json.loads(canonical(payload))


    def from_serialized(self,SimulationClass,payload,history_path=None,backend=None,workers=None,service_factory=None,persistence_factory=None,rule_set=None):
        attributes=_validated_payload(payload)
        if payload.get("schema")=="zombie-sim/runtime-v2":
            validate_implementation(payload.get("implementation_manifest"))
        from ..execution.rule_bindings import validate_rule_restart
        validate_rule_restart(attributes.get("rule_bindings"), rule_set)
        factory=service_factory or SimulationServiceFactory()
        factory.validate_restart(attributes.get("service_bindings"))
        persistence_factory=persistence_factory or PersistenceBundleFactory()
        temporary=tempfile.TemporaryDirectory(prefix="zombie-sim-restored-") if history_path is None else None
        target=Path(history_path) if history_path is not None else Path(temporary.name)/"history.sqlite"
        source=Path(payload["history_path"])
        sim=None
        try:
            if not target.exists() or target.stat().st_size==0:
                persistence_factory.export_prefix(source,target,attributes["revision"],attributes["state"])
            else:
                reader=persistence_factory.open_history(target,read_only=True)
                try:
                    if reader.revision!=attributes["revision"]:
                        raise ValueError(f"Continuation ledger is at revision {reader.revision}, checkpoint is at {attributes['revision']}. Restore to a fresh destination or choose the matching checkpoint; newer durable history is never overwritten.")
                    if _digest(reader.state_at())!=payload["state_sha256"]:
                        raise ValueError("Continuation ledger state differs from checkpoint")
                finally:reader.close()
            # A normal reconstruction constructor wires all owners. It never
            # initializes/resamples the population or runs an unrecorded policy.
            sim=SimulationClass._from_runtime_attributes(attributes,history_path=str(target.absolute()),
                backend=backend,workers=workers,service_factory=factory,persistence_factory=persistence_factory,rule_set=rule_set)
            sim._temporary=temporary
            sim._source_history_path=str(source.absolute())
            if sim.store.version!=sim.revision:
                raise ValueError("Restored store revision does not match coordinator")
            kernel=sim.history.runtime_at()
            if kernel is None:self.initialize_history(sim)
            else:
                sim._runtime_journal_schema=kernel.get("schema")
                sim._runtime_implementation_manifest=implementation_manifest()
                self.mark_committed(sim)
            return sim
        except BaseException:
            if sim is not None:sim.store.close()
            if temporary:temporary.cleanup()
            raise


    def restore_revision(self,SimulationClass,history_path,revision=None,output_history_path=None,backend=None,workers=None,service_factory=None,persistence_factory=None,rule_set=None):
        """Restore a committed runtime journal boundary without initialization.

        The default is an independent verified prefix. A caller can continue the
        latest source ledger by explicitly passing it as output_history_path;
        restoring an earlier revision never truncates an existing destination.
        """
        source=Path(history_path).absolute()
        persistence_factory=persistence_factory or PersistenceBundleFactory()
        history=persistence_factory.open_history(source,read_only=True)
        try:
            selected=history.revision if revision is None else revision
            if isinstance(selected,bool) or not isinstance(selected,int) or not 0<=selected<=history.revision:
                raise ValueError(f"Runtime revision must be an integer between 0 and {history.revision}")
            kernel=history.runtime_at(selected)
            if not kernel or kernel.get("schema") not in {"zombie-sim/runtime-journal-v1",JOURNAL_SCHEMA}:
                raise ValueError("This ledger has no complete runtime journal at the selected revision; restore its matching explicit checkpoint instead")
            if kernel.get("schema")=="zombie-sim/runtime-journal-v2":
                validate_implementation(kernel.get("implementation_manifest"))
            attributes=_decode(kernel["attributes"])
            if int(attributes.get("revision",-1))!=selected:
                raise ValueError("Runtime journal revision does not match the requested state revision")
            state=history.state_at(revision=selected)
            if int(state.get("revision",-1))!=selected:
                raise ValueError("World journal revision does not match the selected runtime boundary")
            queue=[_decode(value) for value in kernel.get("queue",{}).values()]
            serials=[entry[3] for entry in queue]
            if len(serials)!=len(set(serials)):
                raise ValueError("Runtime journal contains duplicate pending event serials")
            attributes.update(state=state,queue=queue,memories={key:_decode(value) for key,value in kernel.get("memories",{}).items()},
                              _dirty=set(),_effects_buffer=[],_deferred_events=[],_batching=False,
                              _decision_due={(str(entry[4]["agent"]),_stamp(entry[0])) for entry in queue if entry[4].get("kind")=="decision"})
            encoded={key:_encode(value) for key,value in attributes.items()}
            payload={"schema":"zombie-sim/runtime-v1" if kernel.get("schema")=="zombie-sim/runtime-journal-v1" else SCHEMA,
                     "attributes":encoded,"history_path":str(source),"history_revision":selected,
                     "state_sha256":_digest(state),"attributes_sha256":_digest(encoded),"event_history":"ledger"}
            if kernel.get("implementation_manifest") is not None:
                payload["implementation_manifest"]=kernel["implementation_manifest"]
        finally:
            history.close()
        sim=self.from_serialized(SimulationClass,payload,history_path=output_history_path,backend=backend,workers=workers,service_factory=service_factory,persistence_factory=persistence_factory,rule_set=rule_set)
        if not any(agent["life"]>0 for agent in sim.world_view["agents"].values()):
            sim.run_status,sim.termination_reason="COMPLETED","NO_LIVING_AGENTS"
        elif sim.time>=sim.horizon and not any(exact_time(entry[0])<=sim.horizon for entry in sim.queue):
            sim.run_status,sim.termination_reason="COMPLETED","HORIZON"
        else:
            sim.run_status,sim.termination_reason="PAUSED",None
        return sim


    def checkpoint(self,sim,path=None):
        """Durably save runtime and a portable history prefix; return the JSON path."""
        if path is None:
            path=Path(sim.history_path).parent/"checkpoints"/f"revision-{sim.revision}.json"
        path=Path(path).absolute();path.parent.mkdir(parents=True,exist_ok=True)
        previous_markers=sim._last_checkpoint,sim._since_checkpoint
        temporary=None
        generation=None
        try:
            previous_checksum,previous_generation=previous_publication(path,_file_digest)
            sim._last_checkpoint=exact_time(sim.time);sim._since_checkpoint=0
            payload=self.serialize(sim)
            sidecar=path.with_suffix(".history.sqlite")
            if sidecar.resolve()==Path(sim.history_path).resolve():
                raise ValueError("Checkpoint sidecar would replace the live ledger; choose another checkpoint path")
            identity=uuid.uuid4().hex
            candidate=sidecar.with_name(sidecar.name+"."+identity+".partial")
            # Reserve ownership exclusively; a collision must never delete another
            # generation's files during failure cleanup. _copy_history accepts empty files.
            with candidate.open("xb"):
                temporary=candidate
            sim.state_coordinator.persistence.checkpoints.export_prefix(temporary,sim.revision,sim.state_coordinator.current_world.to_record())
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            staged=sidecar.with_name(sidecar.name+"."+identity+".generation.history.sqlite")
            # An exclusive link publishes the durable generation without
            # replacing the sidecar used by the preceding checkpoint envelope.
            os.link(temporary,staged)
            generation=staged
            temporary.unlink()
            temporary=None
            sync_directory(path.parent)
            payload["history_path"]=str(sidecar)
            payload["history_sha256"]=_file_digest(generation)
            payload["history_publication"]={"schema":"zombie-sim/checkpoint-publication-v1",
                "generation":generation.name,"previous_sha256":previous_checksum}
            from ..artifact_pins import write_pins
            payload["artifact_pins"]=write_pins(sim,path)
            # History.save_checkpoint provides atomic replacement, file/directory fsync,
            # and a verified envelope. The runtime digest separately checks typed values.
            result=sim.state_coordinator.persistence.checkpoints.save(payload,path)
            from ..faults import hit
            hit("after_checkpoint_envelope_before_sidecar_promotion",revision=sim.revision,path=str(path))
            os.replace(generation,sidecar)
            generation=None
            sync_directory(path.parent)
            # Only a specifically recorded publisher-owned interrupted
            # generation is eligible. User-named checkpoints and archives are
            # never searched or removed. Successful rolling publication leaves
            # one canonical sidecar, independent of the checkpoint count.
            if previous_generation is not None and previous_generation.exists():
                previous_generation.unlink()
                sync_directory(path.parent)
            return result
        except BaseException:
            sim._last_checkpoint,sim._since_checkpoint=previous_markers
            if generation is not None and not envelope_owns_generation(path,generation):
                try:generation.unlink(missing_ok=True)
                except OSError:pass
            if temporary is not None:
                for suffix in ("","-wal","-shm","-journal"):
                    try:Path(str(temporary)+suffix).unlink(missing_ok=True)
                    except OSError:pass  # Preserve the original checkpoint failure.
            raise


    def restore(self,SimulationClass,path,history_path=None,backend=None,workers=None,service_factory=None,persistence_factory=None,rule_set=None):
        from ..artifact_pins import ArtifactMismatch,validate_pins
        path=Path(path)
        envelope=json.loads(path.read_text())
        if "document" not in envelope or _digest(envelope["document"])!=envelope.get("checksum"):
            raise ArtifactMismatch("checkpoint_checksum","Checkpoint envelope checksum mismatch")
        payload=envelope["document"]["payload"]
        if "artifact_pins" in payload:validate_pins(payload["artifact_pins"],path)
        # A portable bundle owns its adjacent history, even if the original rolling
        # checkpoint still exists. Never hide a damaged local sidecar by falling back.
        sidecar=resolve_checkpoint_history(path,payload,_file_digest)
        payload["history_path"]=str(sidecar)
        try:
            return self.from_serialized(SimulationClass,payload,history_path=history_path,backend=backend,workers=workers,service_factory=service_factory,persistence_factory=persistence_factory,rule_set=rule_set)
        except Exception:
            # Adapter-specific open errors differ (e.g. SQLite OperationalError
            # versus FileNotFoundError). Retry only the demonstrable publication
            # race: the selected owned generation disappeared and the canonical
            # sibling now contains precisely this envelope's expected bytes.
            if sidecar!=owned_generation(path,payload.get('history_publication')) or sidecar.exists():raise
            promoted=path.with_suffix('.history.sqlite')
            if _file_digest(promoted)!=payload.get('history_sha256'):raise
            payload['history_path']=str(promoted)
            return self.from_serialized(SimulationClass,payload,history_path=history_path,backend=backend,workers=workers,service_factory=service_factory,persistence_factory=persistence_factory,rule_set=rule_set)


    def branch(self,sim,output,seed=None,run_id=None):
        """Copy a verified prefix, then commit the new child's lineage once."""
        if seed is not None and (isinstance(seed,bool) or not isinstance(seed,int) or seed<0):
            raise ValueError("Branch seed must be a nonnegative integer")
        output=Path(output)
        if output.exists():raise ValueError("Branch destination must be new; existing runs are never replaced")
        output.mkdir(parents=True)
        payload=self.serialize(sim)
        child=self.from_serialized(type(sim),payload,history_path=output/"run.sqlite",
            service_factory=getattr(sim,"_runtime_service_factory",None),
            persistence_factory=getattr(sim,"_runtime_persistence_factory",None),
            rule_set=sim._runtime_rules)
        parent={"run_id":sim.world_view.get("run_id"),"history_path":str(Path(getattr(sim,"_source_history_path",sim.history_path)).absolute()),
                "time":_stamp(sim.time),"revision":sim.revision,"state_sha256":payload["state_sha256"],
                "seed":sim.seed,"counterfactual_seed":sim.seed if seed is None else int(seed),
                "pending_priorities":"inherited from parent; subsequent random draws use the child's seed"}
        try:
            config=deepcopy(child.config)
            if seed is not None:
                config["seed"]=int(seed)
                from ..config import resolve_config
                config=resolve_config(config)
            metadata={"run_id":run_id or uuid.uuid4().hex,"lineage":parent,
                      "scenario_fingerprint":config.get("fingerprint")}
            event={"kind":"branch_created","time":_stamp(child.time),"parent":parent}
            # Runtime replacement and world metadata must join the same plan.
            child._commit_metadata(metadata,event,config=config,seed=child.seed if seed is None else seed)
            child.history.set_metadata("lineage",parent)
            child._source_history_path=child.history_path
            (output/"manifest.json").write_text(canonical({"run_id":metadata["run_id"],"parent":parent,"config":child.config,"status":"paused"}))
            return child
        except BaseException:
            child.close()
            raise


    def close(self,sim):
        if getattr(sim,"_closed",False):
            return
        if getattr(sim,"_pool",None) is not None:
            sim._pool.shutdown(wait=True,cancel_futures=True)
            sim._pool=None
        if getattr(sim,"state_coordinator",None) is not None:
            sim.state_coordinator.persistence.close()
        elif getattr(sim,"store",None) is not None:
            sim.store.close()
        if getattr(sim,"_temporary",None) is not None:
            sim._temporary.cleanup()
        sim._closed=True


    def initialize_history(self,sim):
        manifest=implementation_manifest()
        document = {"schema": JOURNAL_SCHEMA, "implementation_manifest":manifest,
                    "attributes": _journal_attributes(sim, include_config=True),
                    "queue": {str(row[3]): _encode(row) for row in sim.queue},
                    "memories": {str(key): _memory_encode(sim,key,value) for key, value in sim.memories.items()}}
        sim.history.initialize_runtime(document, revision=sim.revision)
        sim._runtime_journal_schema=JOURNAL_SCHEMA
        sim._runtime_implementation_manifest=manifest
        self.mark_committed(sim)


    def capture_delta(self,sim, next_revision, records):
        """Prepare continuation changes for the very same world commit transaction."""
        attributes = _journal_attributes(sim, include_config=getattr(sim, "_runtime_config_marker", None) is not sim._runtime_state.config_token())
        attributes["revision"] = int(next_revision)
        attributes["time"] = _encode(sim.time)
        attributes["_batching"] = False
        attributes["_since_checkpoint"] = int(sim._since_checkpoint) + 1
        patch = [["set", ["attributes", key], value] for key, value in attributes.items()]
        if getattr(sim,"_runtime_journal_schema",None)!=JOURNAL_SCHEMA:
            manifest=getattr(sim,"_runtime_implementation_manifest",None) or implementation_manifest()
            patch[:0]=[["set",["schema"],JOURNAL_SCHEMA],["set",["implementation_manifest"],manifest]]
            sim._runtime_pending_journal_schema=JOURNAL_SCHEMA
        patch.extend(deepcopy(getattr(sim, "_runtime_queue_delta", [])))
        # Agent movement, hunger and effects do not change private model memory.
        # Keep immutable cell identities from the durable boundary so frequent
        # state writes neither copy nor encode an unchanged private memory map.
        # Every actual policy invocation is forced through the codec, including a
        # plugin which mutates its memory in place. Cell references also prevent
        # allocator reuse from hiding a replaced memory object.
        committed_memories = getattr(sim, "_runtime_committed_memories", {})
        current_memories = sim._runtime_state.memory_tokens()
        memory_ids = {str(key) for key, value in current_memories.items()
                      if key not in committed_memories or committed_memories[key] is not value}
        memory_ids.update(str(key) for key in committed_memories if key not in current_memories)
        memory_ids.update(str(record["actor"]) for record in records if record.get("kind") == "decision" and record.get("actor") is not None)
        for key in sorted(memory_ids):
            patch.append(["set", ["memories", key], _memory_encode(sim,key,sim.memories[key])] if key in sim.memories else ["remove", ["memories", key]])
        command_result = None
        command = getattr(sim, "_active_control_command", None)
        if command:
            operation = command["operation"]
            kinds = {record.get("kind") for record in records}
            intervention_boundary = "intervention" if command.get("request", {}).get("apply_now") else "intervention_scheduled"
            intervention_id = command.get("request", {}).get("id", command["id"])
            completed = operation == "step" or (operation == "intervene" and any(
                record.get("kind") == intervention_boundary and record.get("intervention") == intervention_id
                for record in records))
            completed = completed or (operation == "script_submit" and "admission_batch" in kinds)
            if operation in {"advance", "step_timestamp"}:
                target = min(exact_time(command["target"]), sim.horizon)
                completed = ("clock_advanced" in kinds and sim.time >= target) or not any(a["life"] > 0 for a in sim.world_view["agents"].values())
            if completed:
                control = deepcopy(command["desired_control"])
                if (not any(a["life"] > 0 for a in sim.world_view["agents"].values())
                        or (sim.time >= sim.horizon and (not sim.queue or sim.queue[0][0] > sim.horizon))):
                    control["status"] = "completed"
                command_result = {"command_id": command["id"], "run_id": sim.world_view.get("run_id"), "status": "applied",
                                  "time": _stamp(sim.time), "revision": str(next_revision), "generation": control["generation"],
                                  "run_status": control["status"], "pacing": control["pacing"], "control": control}
                patch.append(["set", ["attributes", "_active_control_command"], None])
        sim._runtime_command_result = command_result
        return patch, command_result


    def mark_committed(self,sim):
        if getattr(sim,"_runtime_pending_journal_schema",None) is not None:
            sim._runtime_journal_schema=sim._runtime_pending_journal_schema
            sim._runtime_pending_journal_schema=None
        sim._runtime_queue_delta = []
        sim._runtime_config_marker = sim._runtime_state.config_token()
        # This marker moves only after the enclosing world/runtime transaction is
        # durable. A failed publication must retry the same memory changes.
        sim._runtime_committed_memories = sim._runtime_state.memory_tokens()
        if getattr(sim, "_runtime_command_result", None) is not None:
            sim._active_control_command = None
        sim._runtime_command_result = None

