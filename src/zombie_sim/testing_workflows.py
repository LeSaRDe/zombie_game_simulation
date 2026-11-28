"""Acceptance workflow bindings to real isolated simulation processes.

No case expectations enter this module. Run operations cross an RPC boundary to
an actual coordinator; crash probes terminate that process at persistence hooks.
"""
from __future__ import annotations
from bisect import bisect_right
from copy import deepcopy
import errno
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
import traceback

from .storage import History,canonical,exact_time


def _semantic(sim,value):
    """Normalize namespaces and execution-only clock publications, in order.

    Intermediate observation/checkpoint calls may publish clock-only revisions.
    They do not change the game: retain every game event and its causal ordering,
    and map revisions/IDs to that semantic sequence for equivalent-run comparison.
    The untouched ledger remains available in each run's diagnostic directory.
    """
    ignored={"clock_advanced","scheduler_advanced"}
    events=[event for event in sim.events if event.get("kind") not in ignored]
    event_ids={event["id"]:f"semantic-event-{index+1}" for index,event in enumerate(events)}
    revisions={0:0};index=0
    for event in sim.events:
        revision=int(event.get("revision",0))
        if revision not in revisions:
            if event.get("kind") not in ignored:index+=1
            revisions[revision]=index
    ordered_revisions=sorted(revision for revision in revisions if revision)
    def walk(item,key=None):
        if isinstance(item,dict):
            return {k:walk(v,k) for k,v in item.items() if k not in {"ledger_sequence","normalization"}}
        if isinstance(item,list):return [walk(v,key) for v in item]
        if key in {"revision","onset_revision","end_revision","ledger_revision"} and item is not None:
            revision=int(item)
            return str(revisions[revision] if revision in revisions else bisect_right(ordered_revisions,revision))
        if key=="run_id":return "RUN"
        if isinstance(item,str):return event_ids.get(item,item)
        return item
    return walk(value)


def _capture(sim,what,initial=None):
    from .testing import normalize_snapshot,normalize_trace,occurrence_aliases,_wire
    aliases=occurrence_aliases(sim)
    if what in {"semantic_snapshot","initial_snapshot","durable_snapshot"}:
        if what=="initial_snapshot":raw=sim.history.state_at(revision=0)
        elif what=="durable_snapshot":raw=sim.history.state_at()
        else:return _semantic(sim,normalize_snapshot(sim))
        from .runtime import materialize_snapshot,_decode
        projected=materialize_snapshot(raw)
        journal=sim.history.runtime_at(int(raw["revision"]))
        memories=(journal or {}).get("memories",{})
        for aid,agent in projected["agents"].items():agent["model_memory"]=_decode(memories.get(aid,{}))
        return _semantic(sim,normalize_snapshot(projected,aliases))
    if what=="semantic_history":
        trace=normalize_trace(sim)
        trace["events"]=[event for event in trace["events"] if event.get("kind") not in {"clock_advanced","scheduler_advanced"}]
        trace["decisions"]=_wire(list(sim.decisions),aliases)
        trace["model_memory"]=_wire(sim.memories,aliases)
        return _semantic(sim,trace)
    if what in {"occurrences","random_draws","interventions"}:
        return _semantic(sim,normalize_trace(sim)[what])
    if what=="decisions":return _semantic(sim,_wire(list(sim.decisions),aliases))
    if what=="model_memory":return _wire(sim.memories,aliases)
    if what=="execution_counters":
        return deepcopy(sim.execution_counters)
    if what=="status":return {"state":sim.run_status,"termination_reason":sim.termination_reason,"time":str(sim.time)}
    if what=="resolved_config":return resolved_config(sim.config)
    if what=="initialization_provenance":return {"seed":sim.seed,**deepcopy(sim.state.get("initialization",{})),"reused_preview_id":None}
    if what=="scheduler_diagnostics":return sim.execution_diagnostics()
    raise NotImplementedError(f"Unknown run capture {what}")


def resolved_config(draft):
    from .testing import request_numbers
    from .config import resolve_config,semantic_config
    draft=deepcopy(draft);values={**draft,**draft.pop("semantic",{})}
    execution=values.get("execution",{})
    if "backend" in execution:values.setdefault("storage",{})["backend"]=execution["backend"]
    if "checkpoint_interval" in execution:values["checkpoint_interval"]=execution["checkpoint_interval"]
    values.pop("semantic",None)
    values=request_numbers(values)
    for key in ("incubation_duration",):
        if key in values:values[key]=float(exact_time(values[key]))
    resolved=resolve_config(values)
    return {"semantic":semantic_config(resolved),"semantic_fingerprint":resolved["fingerprint"],
            "seed":resolved["seed"],"execution":resolved.get("execution",{}),"resolved":resolved}


def _worker(connection,directory,setup,config,mode,checkpoint,plugins):
    from .testing import FrameworkTestAdapter,ControlledSimulation,normalize_snapshot,normalize_trace,occurrence_aliases,request_numbers
    from .commands import execute_script_command
    from .runtime import restore_revision,materialize_snapshot
    from .faults import arm,clear
    adapter=FrameworkTestAdapter(workdir=directory);sim=None
    try:
        if plugins:
            from .testing_learning import install_plugins
            setup=install_plugins(deepcopy(setup),plugins)
        if mode=="checkpoint":sim=ControlledSimulation.restore(checkpoint,history_path=Path(directory)/"run-0.sqlite")
        elif mode=="latest":sim=restore_revision(ControlledSimulation,Path(directory)/"run-0.sqlite",output_history_path=Path(directory)/"run-0.sqlite")
        else:sim=adapter.new_simulation(setup,config)
        if plugins:
            from .testing_learning import activate_plugins
            activate_plugins(sim,plugins)
        adapter.simulations=[sim]
        connection.send({"ok":True,"value":{"run_id":sim.state["run_id"],"history":sim.history_path}})
        while True:
            command=connection.recv();operation=command["operation"];data=command.get("data",{})
            try:
                if operation=="close":
                    connection.send({"ok":True,"value":None});break
                if operation=="script":
                    step=deepcopy(data["step"])
                    if data.get("draws"):
                        sim.inject_random_values(data["draws"])
                    if step["op"] in {"submit","submit_batch","advance","intervene"}:
                        execute_script_command(sim,step["op"],request_numbers({k:v for k,v in step.items() if k!="op"}),data["command_id"])
                        result={"time":str(sim.time),"revision":sim.revision}
                    else:result=adapter.simulation_steps(sim,[step])
                elif operation=="capture":result=_capture(sim,data["what"])
                elif operation=="trace":result=normalize_trace(sim)
                elif operation=="checkpoint":
                    path=sim.checkpoint(Path(directory)/(data["name"]+".checkpoint.json"))
                    capability=json.loads(Path(path).read_text())["document"]["payload"]["restart_capability"]
                    result={"state":_capture(sim,"durable_snapshot" if capability=="STATE_REPLAY_ONLY" else "semantic_snapshot"),"path":path,
                            "sha256":hashlib.sha256(Path(path).read_bytes()).hexdigest(),"restart_capability":capability}
                elif operation=="replay":
                    state=sim.history.state_at(time=data["time"])
                    result=_semantic(sim,normalize_snapshot(materialize_snapshot(state,data["time"]),occurrence_aliases(sim)))
                elif operation=="fault":
                    arm(data["point"],occurrence=data.get("occurrence",1),persistent=data.get("persistent",False),
                        error=data.get("error"),trace_path=Path(directory)/"faults.jsonl",crash=data["point"] not in {"history_write","dependency_validation"},omit_read_key=data.get("omit_read_key"))
                    result={"armed":data["point"]}
                elif operation=="completion_order":
                    sim.config.setdefault("execution",{}).update(completion_order=data["order"],completion_order_seed=data.get("seed",41))
                    result={"order":sim.config["execution"]["completion_order"]}
                elif operation=="branch":
                    selected=sim.history.state_at(time=data["time"]) if data.get("time") is not None else sim.state
                    source=restore_revision(ControlledSimulation,sim.history_path,revision=int(selected["revision"]))
                    try:
                        child=source.branch(data["directory"],seed=sim.seed+1 if data.get("random_alignment")=="independent" else None)
                        try:
                            child.history.flush()
                            result={"parent_run_id":sim.state["run_id"],"child_run_id":child.state["run_id"],"lineage":child.state.get("lineage")}
                        finally:child.close()
                    finally:source.close()
                elif operation=="measurement":
                    from .visualization import populations
                    at=data.get("time",str(sim.time));state=materialize_snapshot(sim.history.state_at(time=at),at)
                    if data["measurement"]=="populations":
                        counts=populations(state)
                        result={"healthy_humans":counts["healthy"],"infected_humans":counts["infected"],
                                "active_zombies":counts["zombies"],"dead_agents":counts["dead"],"total_identities":counts["total"]}
                    elif data["measurement"]=="infection_episodes":
                        lower,upper=map(exact_time,data["interval"]);episodes=state["episodes"].values()
                        result={"initial_episodes":sum(e.get("source_kind","").upper()=="INITIAL_CONDITION" for e in episodes),
                                "new_incidence":sum(e.get("source_kind","").upper()!="INITIAL_CONDITION" and lower<=exact_time(e["onset_at"])<=upper for e in episodes),
                                "conversions":sum(e.get("outcome")=="CONVERTED" and lower<=exact_time(e["ended_at"])<=upper for e in episodes)}
                    else:raise NotImplementedError(data["measurement"])
                elif operation=="formal":
                    from .ontology_export import export_snapshot
                    from rdflib import Graph,Namespace,RDF
                    turtle=export_snapshot(sim.snapshot(),events=sim.events)
                    graph=Graph().parse(data=turtle,format="turtle");zg=Namespace("urn:zombie-game:v0.1:")
                    kind={"treatment":zg.CureTransition,"death":zg.DeathTransition,"conversion":zg.ConversionTransition}[data["kind"]]
                    transitions=list(graph.subjects(RDF.type,kind))
                    if len(transitions)!=1:raise ValueError(f"Expected one actual focused {data['kind']} transition, got {len(transitions)}")
                    # Agent URIs are emitted by the real exporter; bind by its ID map.
                    from urllib.parse import unquote
                    agents={unquote(str(s).rsplit(":",1)[-1]):str(s) for s in graph.subjects(RDF.type,zg.Agent)}
                    bindings={"agents":{aid:agents[aid] for aid in sim.state["agents"] if aid in agents},"transition":str(transitions[0])}
                    occurrence=next(graph.objects(transitions[0],zg.triggeredBy),None)
                    if occurrence:bindings["occurrence"]=str(occurrence)
                    result={"turtle":turtle,"bindings":bindings}
                elif operation.startswith("learning."):
                    from .testing_learning import worker_operation
                    result=worker_operation(sim,operation.removeprefix("learning."),data)
                else:raise NotImplementedError(operation)
                connection.send({"ok":True,"value":result})
            except Exception as error:
                code=errno.errorcode.get(error.errno,"ERROR") if isinstance(error,OSError) else type(error).__name__
                connection.send({"ok":False,"error":{"code":getattr(error,"code",code),"component":getattr(error,"component",None),"type":type(error).__name__,"message":str(error),"traceback":traceback.format_exc()}})
    except BaseException as error:
        try:connection.send({"ok":False,"error":{"code":getattr(error,"code",type(error).__name__),"component":getattr(error,"component",None),"message":str(error),"traceback":traceback.format_exc()}})
        except (OSError,EOFError):pass
    finally:
        clear();adapter.close();connection.close()


class WorkerError(RuntimeError):
    def __init__(self,details):super().__init__(details.get("message",str(details)));self.details=details


class Peer:
    def __init__(self,directory,setup,config,plugins=(),mode="create",checkpoint=None):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.setup,self.config,self.plugins=setup,config,plugins
        context=multiprocessing.get_context("spawn");self.connection,child=context.Pipe()
        self.process=context.Process(target=_worker,args=(child,str(directory),setup,config,mode,checkpoint,plugins))
        self.process.start();child.close();self.identity=self.receive()
    def receive(self):
        try:
            timeout=float(os.environ.get("ZOMBIE_ACCEPTANCE_RPC_TIMEOUT", "1800"))
            if timeout <= 0:raise ValueError("ZOMBIE_ACCEPTANCE_RPC_TIMEOUT must be positive")
            if not self.connection.poll(timeout):raise TimeoutError(f"Simulation worker did not answer within {timeout:g} seconds")
            result=self.connection.recv()
        except (EOFError,OSError):
            self.process.join(timeout=2)
            raise WorkerError({"code":"PROCESS_EXIT","exitcode":self.process.exitcode,"message":"Coordinator process exited at a real fault boundary"}) from None
        if not result["ok"]:raise WorkerError(result["error"])
        return result["value"]
    def call(self,operation,**data):
        if not self.process.is_alive():raise WorkerError({"code":"PROCESS_EXIT","message":"Coordinator is no longer running"})
        self.connection.send({"operation":operation,"data":data});return self.receive()
    def close(self):
        if self.process.is_alive():
            try:self.call("close")
            except (OSError,WorkerError):pass
        self.process.join(timeout=5)
        if self.process.is_alive():self.process.terminate();self.process.join(timeout=5)
        self.connection.close()


def execute_workflow(adapter,request):
    if request["kind"]=="browser":
        from .testing_browser import execute_browser
        return execute_browser(adapter,request)
    captures={};runs={};specs=deepcopy(request.get("setup",{}).get("runs",{}));plugins={};commands={};checkpoints={}
    def create(name,mode="create",checkpoint=None):
        spec=specs[name]
        runs[name]=Peer(adapter.workdir/name,spec["world"],spec.get("config",{}),plugins.get(name,()),mode,checkpoint)
        commands.setdefault(name,[])
        return runs[name].identity
    try:
        for step in request["steps"]:
            operation=step["op"];name=step.get("run");result=None
            try:
                if operation=="run.create":result=create(name)
                elif operation=="model.install_fixture":plugins.setdefault(name,[]).append(deepcopy(step))
                elif operation=="run.script":
                    for substep in step["steps"]:
                        command={"step":deepcopy(substep),"command_id":f"{name}-script-{len(commands[name])}","draws":step.get("draws",[])}
                        commands[name].append(command)
                        result=runs[name].call("script",**command)
                elif operation=="run.capture":
                    if step["what"]=="fault_trace":
                        path=runs[name].directory/"faults.jsonl"
                        result=[json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
                    else:result=runs[name].call("capture",what=step["what"])
                elif operation=="run.checkpoint":
                    result=runs[name].call("checkpoint",name=step["name"]);checkpoints[(name,step["name"])]=result["path"]
                elif operation=="artifact.corrupt":
                    path=Path(checkpoints[(name,step["checkpoint"])]);envelope=json.loads(path.read_text())
                    component=step["component"]
                    if component=="checkpoint_checksum":
                        envelope["checksum"]="0"*64
                    elif component=="ontology_fingerprint":
                        envelope["document"]["payload"]["artifact_pins"]["ontology"]["ontology.ttl"]="0"*64
                        envelope["checksum"]=hashlib.sha256(canonical(envelope["document"]).encode()).hexdigest()
                    elif component=="model_artifact_checksum":
                        record=envelope["document"]["payload"]["artifact_pins"]["models"][0]
                        with (path.parent/record["path"]).open("ab") as stream:stream.write(b"\nmodified artifact\n")
                    else:raise NotImplementedError(component)
                    path.write_text(canonical(envelope));result={"path":str(path),"component":component}
                elif operation in {"run.restart","run.recover"}:
                    path=checkpoints.get((name,step.get("checkpoint")))
                    if path:
                        from .runtime import assert_exact_restart
                        assert_exact_restart(json.loads(Path(path).read_text())["document"]["payload"])
                    old=runs[name];old.close()
                    result=create(name,"checkpoint" if operation=="run.restart" else "latest",path)
                    if step.get("replay_commands"):
                        for command in commands[name]:runs[name].call("script",**command)
                elif operation=="run.replay":result=runs[name].call("replay",time=step["time"])
                elif operation=="run.intervene":
                    payload={"op":"intervene",**{k:v for k,v in step.items() if k not in {"op","run","label"}}}
                    result=runs[name].call("script",step=payload,command_id=f"intervene-{step['id']}")
                elif operation=="run.branch":
                    child=step["child"];directory=adapter.workdir/child
                    result=runs[name].call("branch",directory=str(directory),time=step.get("time"),random_alignment=step.get("random_alignment"))
                    # The production branch names its own ledger run.sqlite.
                    (directory/"run.sqlite").rename(directory/"run-0.sqlite")
                    specs[child]=deepcopy(specs[name]);create(child,"latest")
                    result.update(parent_alias=name,child_alias=child)
                elif operation=="fault.arm":result=runs[name].call("fault",**{k:v for k,v in step.items() if k not in {"op","run"}})
                elif operation=="workers.completion_order":result=runs[name].call("completion_order",**{k:v for k,v in step.items() if k not in {"op","run"}})
                elif operation=="measurement.query":result=runs[name].call("measurement",**{k:v for k,v in step.items() if k not in {"op","run","label"}})
                elif operation=="trace.export_turtle":result=runs[name].call("formal",**{k:v for k,v in step.items() if k not in {"op","run","label"}})
                elif operation=="config.resolve":result=resolved_config(step["draft"])
                elif operation=="config.export_import":
                    from .config import resolve_config
                    from .testing_learning import write_toml
                    path=adapter.workdir/(step["label"]+".toml")
                    write_toml(captures[step["source"]]["resolved"],path)
                    result=resolved_config(resolve_config(path))
                elif operation=="trials.execute":
                    result=[]
                    for seed in step["seeds"]:
                        sim=adapter.new_simulation(step["world"],{"seed":seed,"decision_mode":"scripted"})
                        try:trace=adapter.simulation_steps(sim,step["steps"])
                        finally:sim.close()
                        result.append({"seed":seed,"trace":trace})
                elif operation.startswith("rl."):result=runs[name].call("learning."+operation.removeprefix("rl."),**{k:v for k,v in step.items() if k not in {"op","run","label"}})
                elif operation.startswith(("encoder.","policy.","training.")):
                    from .testing_learning import execute_operation
                    result=execute_operation(adapter,request,step,captures)
                else:raise NotImplementedError(f"Unbound workflow operation {operation}")
            except (WorkerError,ValueError) as error:
                if step.get("on_fault")!="capture" and step.get("on_error")!="capture":raise
                result=error.details if isinstance(error,WorkerError) else {"code":getattr(error,"code",type(error).__name__),"message":str(error)}
            if "label" in step:captures[step["label"]]=result
        return {"captures":captures,"diagnostics":{"normalization":"ordered-semantic-v1","workers":{k:v.identity for k,v in runs.items()}}}
    finally:
        for peer in runs.values():peer.close()
