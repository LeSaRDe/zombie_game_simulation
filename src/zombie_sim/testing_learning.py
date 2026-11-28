"""Acceptance bindings to the product's policy, encoder and learning APIs.

Fixtures replace only a model plugin. All admissions, effects, observations,
reward accounting, neural optimization and decoding execute production code.
"""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import random
import tempfile

from .storage import exact_time
from .testing import normalize_intent,normalize_snapshot,normalize_trace,request_numbers,_wire


class FixtureModelError(RuntimeError):pass


class LiveHandle:
    def __init__(self):self.handle=tempfile.TemporaryFile()
    def __deepcopy__(self,memo):return self


class BoundaryProbeModel:
    version="1.0.0"
    applicable_types=("Human","Zombie")
    def __init__(self,parameters=None):self.parameters=deepcopy(parameters or {})
    def manifest(self):
        return {"model_id":"acceptance/boundary-probe-v1","model_version":self.version,
                "applicable_types":list(self.applicable_types),"parameters":self.parameters,
                "deterministic":True,"restartable":self.parameters.get("fixture")!="unserializable_memory"}
    def decide(self,observation,memory,rng):
        fixture=self.parameters["fixture"];aid=observation["self_state"]["id"]
        memory=deepcopy(memory or {})
        if fixture=="exception":raise FixtureModelError("Boundary probe deliberately raised")
        if fixture=="missing":Path(self.parameters["artifact_path"]).read_bytes()
        intent={"actor":aid,"action":"wait","parameters":{"duration":"1"}}
        if fixture=="malformed":intent.pop("action")
        if fixture=="repeated_invalid":
            a=observation["self_state"]
            intent={"actor":aid,"action":"move","parameters":{"duration":"1","path":[
                {"x":a["x"],"y":a["y"],"offset":"0"},{"x":-1,"y":a["y"],"offset":"1"}]}}
        if fixture=="private_counter":memory["count"]=memory.get("count",0)+1
        if fixture=="unserializable_memory" and "handle" not in memory:memory["handle"]=LiveHandle()
        return intent,memory,{"fixture":fixture}


def install_plugins(setup,plugins):
    from .policies import register_model
    for plugin in plugins:
        fixture=plugin["fixture"];name="acceptance/"+fixture
        parameters={"fixture":fixture}
        if fixture=="missing":
            handle=tempfile.NamedTemporaryFile(prefix="zombie-model-probe-",delete=False)
            handle.write(b"available model artifact\n");handle.close();parameters["artifact_path"]=handle.name
        # The registry resolves a real plugin for configuration validation and execution.
        def factory(overrides=None,defaults=deepcopy(parameters)):
            return BoundaryProbeModel({**defaults,**(overrides or {})})
        register_model(name,factory,replace=True)
        aids=plugin.get("agents",[plugin.get("agent")])
        for agent in setup.get("agents",[]):
            if agent["id"] in aids:agent["model_assignment"]={"model_id":name,"model_version":"1.0.0","parameters":deepcopy(parameters)}
    return setup


def activate_plugins(sim,plugins):
    if any(p["fixture"]=="missing" for p in plugins):
        for agent in sim.state["agents"].values():
            parameters=(agent.get("model_assignment") or {}).get("parameters",{})
            if parameters.get("fixture")=="missing":Path(parameters["artifact_path"]).unlink(missing_ok=True)


def _normalized_observation(observation):
    """Expand only the supplied local shorthand using public agent defaults."""
    from .domain import make_agent,profile,status,capabilities
    value=request_numbers(deepcopy(observation))
    def expand(agent):
        agent=deepcopy(agent);aid=agent.pop("id");kind=agent.pop("type","Human");role=agent.pop("role",None)
        result=make_agent(aid,kind,role,**agent)
        result.update(profile(result));result.update(status=status(result),available_actions=capabilities(result))
        return result
    value["self_state"]=expand(value["self_state"])
    neighbors=value.get("local_agents",{})
    value["local_agents"]={a["id"]:expand(a) for a in (neighbors.values() if isinstance(neighbors,dict) else neighbors)}
    if "world" not in value:
        bounds=value.pop("bounds",[1000,1000]);value["world"]={"length":bounds[0],"width":bounds[1]} if isinstance(bounds,list) else bounds
    value.setdefault("local_environment",{});value.setdefault("received_signals",[]);value.setdefault("time","0")
    return value


def _codec(observation,candidates,padding):
    from .learning import CandidateCodec
    codec=CandidateCodec(observation,candidates,padding=padding)
    decoded=[codec.decode(i) for i in range(len(candidates))];errors=[]
    for i in range(len(candidates),len(codec.mask)):
        try:codec.decode(i)
        except ValueError as error:errors.append({"index":i,"code":"INVALID_CANDIDATE","message":str(error)})
        else:raise AssertionError("Production decoder admitted a padded candidate")
    return {"neighborhood_features":codec.context,"decoded_intents":decoded,"candidate_mask":codec.mask,
            "padding_decode_errors":errors,"padding_rejected_indices":[e["index"] for e in errors],
            "index_to_intent":{str(i):v["id"] for i,v in enumerate(decoded) if "id" in v}}


def worker_operation(sim,operation,data):
    from .learning import ControlledAgentEnv,DecisionBatchAEC
    if operation=="attach":
        controlled=data["controlled"]
        if data["adapter"]=="aec":
            env=DecisionBatchAEC(sim.config,controlled_ids=controlled).attach(sim)
        else:
            family=sim.state["agents"][controlled]["type"]
            if data.get("reward",family.lower()+"_survival_v1") not in {"human_survival_v1","zombie_pressure_v1"}:raise ValueError("Unknown reward task")
            env=ControlledAgentEnv(sim.config,actor_id=controlled,family=family)
            env.attach(sim,controlled,scripted_others=sim.decision_mode=="scripted",rollout_cutoff=data.get("rollout_cutoff"))
        sim._runtime_learning_adapter=env
        return {"adapter":data["adapter"],"controlled":controlled}
    env=sim._runtime_learning_adapter
    if operation=="step":
        sim.inject_random_values(data.get("draws", []))
        _,discounted,terminated,truncated,info=env.step_intent(normalize_intent(data["intent"]))
        names={"human_alive_time":"alive_human","heal_other":"healing_others","cure_other":"curing_others",
               "damage_human":"damage_to_humans","human_episode_end":"conversion" if info["termination_reason"]=="conversion" else "death"}
        terms={"new_infection":0.} if env.family=="Zombie" else {}
        for term in info["reward_terms"]:
            name=names.get(term["name"],term["name"]);terms[name]=terms.get(name,0.)+term["value"]
        next_episode=None
        if info["termination_reason"]=="conversion":
            _,next_info=env.begin_controller_episode(env.actor_id,family="Zombie");next_episode=next_info["controller_episode_id"]
        return _wire({"elapsed":info["elapsed"],"reward":info["undiscounted_reward"],"discounted_reward":discounted,
                "reward_terms":terms,"raw_reward_terms":info["reward_terms"],"discount":env.gamma**info["elapsed"],
                "terminated":terminated,"truncated":truncated,"bootstrap_allowed":not terminated,
                "controller_episode_id":info["controller_episode_id"],"next_controller_episode_id":next_episode})
    if operation=="aec_batch":
        env.set_batch_order(data["order"]);intents={i["actor"]:i for i in data["intents"]};observations={}
        for aid in data["order"]:
            if env.agent_selection!=aid:raise RuntimeError("AEC selection differs from requested collection order")
            observations[aid]=env.raw_observation(aid)
            env.step_intent(normalize_intent(intents[aid]))
        # Normalize only namespace/revisions, preserving the raw frozen contents.
        from .testing_workflows import _semantic
        return {"observations":_semantic(sim,_wire(observations))}
    raise NotImplementedError(operation)


def write_toml(value,path):
    """Serialize the JSON-compatible resolved configuration as TOML tables."""
    def scalar(v):
        if v is None:raise ValueError("TOML has no null scalar")
        if isinstance(v,bool):return "true" if v else "false"
        if isinstance(v,(int,float,str)):return json.dumps(v,ensure_ascii=False,allow_nan=False)
        if isinstance(v,list):return "["+", ".join(scalar(x) for x in v)+"]"
        if isinstance(v,dict):return "{ "+", ".join(json.dumps(str(k))+" = "+scalar(x) for k,x in v.items() if x is not None)+" }"
        raise TypeError(type(v).__name__)
    Path(path).write_text("\n".join(json.dumps(str(k))+" = "+scalar(v) for k,v in value.items() if v is not None)+"\n")


def execute_operation(adapter,request,step,captures):
    op=step["op"]
    if op=="encoder.evaluate":return _wire(_codec(_normalized_observation(step["observation"]),step["candidates"],step.get("padding",0)))
    if op=="encoder.roundtrip_bank":
        from .config import ConfigError
        results={}
        for fixture in request["setup"][step["bank"]]:
            try:sim=adapter.new_simulation(fixture["world"],{"decision_mode":"scripted"},fixture.get("draws"))
            except ConfigError as error:
                results[fixture["id"]]={"configuration_error":{"type":type(error).__name__,"message":str(error)}}
                continue
            result=_codec(sim.observe(fixture["actor"]),fixture["candidates"],fixture["padding"])
            trace=adapter.simulation_steps(sim,[{"op":"submit",**result["decoded_intents"][0]},
                {"op":"snapshot","label":"admitted"},{"op":"advance","to":fixture["duration"]},{"op":"snapshot","label":"end"}])
            result["trace"]=trace;results[fixture["id"]]=result
        return _wire({"contexts":results})
    if op=="policy.run_bank":return _policy_bank(adapter,request["setup"][step["bank"]])
    if op.startswith("training."):return _training_operation(adapter,step,captures)
    raise NotImplementedError(op)


def _policy_bank(adapter,bank):
    from .policies import create_model,initialize_memory,set_goal
    from .config import ConfigError
    names=sorted({context["model"] for context in bank})
    defaults={name:{"version":create_model(name).version,"parameters":deepcopy(create_model(name).parameters)} for name in names}
    contexts={}
    for context in bank:
        result={"model":{"id":context["model"],**deepcopy(defaults[context["model"]])},
                "memory_seed":deepcopy(context["memory_seed"]),"decisions":[]}
        contexts[context["id"]]=result
        try:sim=adapter.new_simulation(context["world"],{"seed":context["seed"],"horizon":context["horizon"],"decision_mode":"scripted"})
        except ConfigError as error:
            result["configuration_error"]={"type":type(error).__name__,"message":str(error)}
            continue
        actor=context["actor"];model=create_model(context["model"])
        memory=initialize_memory(sim.observe(actor)["self_state"])
        memory=set_goal(memory,context["memory_seed"].get("objective"))
        memory["last_reports"]={}
        sim.memories[actor]=memory
        snapshots={"initial":normalize_snapshot(sim)};observations={}
        background=sorted(deepcopy(context.get("background_events",[])),key=lambda row:exact_time(row["at"]))
        def advance_to(target):
            while background and exact_time(background[0]["at"])<=target:
                event=background.pop(0);sim.advance_until(event["at"],return_snapshot=False)
                sim.submit_intents([normalize_intent(i) for i in event["intents"]])
            sim.advance_until(target,return_snapshot=False)
        advance_to(exact_time(0))
        for index in range(context["max_decisions"]):
            if sim.time>=sim.horizon or sim.state["agents"][actor]["life"]<=0:break
            if sim.state["agents"][actor].get("active_action"):
                occurrence=sim.occurrences[sim.state["agents"][actor]["active_action"]]
                advance_to(min(exact_time(occurrence["planned_end"]),sim.horizon))
                if sim.state["agents"][actor].get("active_action"):break
            before=f"before-{index}";snapshots[before]=normalize_snapshot(sim)
            sim._decide([actor])
            decision=deepcopy(sim.decisions[-1]);did=decision["id"];intent_id=decision["intent"]["id"]
            observation_id=f"observation-{index}";observations[observation_id]=_wire(decision["observation"])
            candidates=[];selected=None
            for ci,candidate in enumerate(decision["diagnostics"].get("ranked_candidates",[])):
                cid=f"{did}-candidate-{ci}"
                terms=[{"feature":key,"value":value,"weight_path":"/weights/"+key,
                        "contribution":value*model.parameters["weights"][key]} for key,value in candidate["features"].items()]
                candidates.append({"id":cid,"intent":candidate["intent"],"observable_feasible":True,
                                   "reason":candidate["reason"],"terms":terms,"score":candidate["score"]})
                if ci==decision["diagnostics"]["selected_candidate_index"]:selected=cid
            record={"id":did,"time":decision["time"],"observation_id":observation_id,"intent_id":intent_id,
                    "selected_candidate_id":selected,"before_snapshot":before,
                    "reason":decision["diagnostics"].get("reason"),"candidates":candidates}
            result["decisions"].append(record)
            occurrence=next((o for o in sim.occurrences.values() if o["intent_id"]==intent_id),None)
            if occurrence:
                advance_to(min(exact_time(occurrence["planned_end"]),sim.horizon))
                if occurrence.get("result") not in {None,"PENDING"}:
                    after=f"after-{index}";snapshots[after]=normalize_snapshot(sim);record["after_snapshot"]=after
            elif sim.state["agents"][actor].get("active_action"):
                fallback=sim.occurrences[sim.state["agents"][actor]["active_action"]]
                advance_to(min(exact_time(fallback["planned_end"]),sim.horizon))
        result["trace"]={**normalize_trace(sim),"snapshots":snapshots,"observations":observations}
    value=_wire({"default_models":defaults,"contexts":contexts})
    (adapter.workdir/"policy-bank-evidence.json").write_text(json.dumps(value,indent=2))
    return value


def _training_process(connection,operation,config,artifact,settings,seeds):
    try:
        from .learning import train,TrainingConfig,LearnedModel,ControlledAgentEnv,_tensor_state
        import torch
        torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
        if operation=="train":
            report=train(config,artifact,TrainingConfig(**settings))
            result={"artifact":report["artifact"],"config":config,"decisions_collected":report["decisions"],
                    "optimizer_steps":report["optimization_steps"],"training_seeds":report["settings"]["train_seeds"],
                    "validation_seeds":report["validation"]["seeds"],"test_seeds_seen_during_selection":[r["seed"] for r in report["split_accesses"] if r["split"]=="test" and r["phase"]!="after_selection"],
                    "split_accesses":report["split_accesses"],
                    "report_path":str(Path(artifact)/"report.json")}
        elif operation=="reload":
            model=LearnedModel.load(artifact)
            result={"artifact":artifact,"config":config,"encoder_version":model.metadata.get("encoder_version","candidate_v1"),
                    "loaded_weights":len(model.network.state_dict())}
        else:
            model=LearnedModel.load(artifact);actions=[];elapsed=[];terms=[]
            for seed in seeds:
                env=ControlledAgentEnv(config,family="Human",max_candidates=model.candidate_limit)
                try:
                    obs,_=env.reset(seed=seed);hidden=torch.zeros(model.hidden_size)
                    for _ in range(10000):
                        with torch.no_grad():
                            context,candidates=_tensor_state(obs,torch);logits,_,hidden=model.network(context,candidates,hidden)
                            chosen=int(torch.argmax(logits))
                        obs,reward,terminated,truncated,info=env.step(chosen)
                        actions.append(info["intent"]);elapsed.append(info["elapsed"]);terms.append(info["reward_terms"])
                        if terminated or truncated:break
                    else:raise RuntimeError("Held-out evaluation exceeded its explicit decision bound")
                finally:env.close()
            result={"actions":actions,"action_count":len(actions),"elapsed":elapsed,"reward_terms":terms,"seeds":seeds}
        connection.send({"ok":True,"value":_wire(result)})
    except BaseException:
        import traceback
        connection.send({"ok":False,"error":traceback.format_exc()})
    finally:connection.close()


def _training_operation(adapter,step,captures):
    import multiprocessing
    from .testing import fixture_config
    op=step["op"].split(".",1)[1];settings={};seeds=step.get("seeds",[])
    if op=="run":
        if step["algorithm"]!="ppo":raise ValueError("Only PPO is implemented")
        config=fixture_config(step["scenario"]["world"],{"horizon":step["scenario"]["horizon"],"decision_mode":"scripted"})
        artifact=str(adapter.workdir/"ppo-smoke")
        settings={"decisions":step["decision_budget"],"train_seeds":step["train_seeds"],"validation_seeds":step["validation_seeds"],"evaluation_seeds":step["test_seeds"]}
        operation="train"
    else:
        source=captures[step["checkpoint_from"]];config=request_numbers(source["config"]);artifact=source["artifact"]
        operation="reload" if op=="reload_checkpoint" else "evaluate"
    context=multiprocessing.get_context("spawn");connection,child=context.Pipe()
    process=context.Process(target=_training_process,args=(child,operation,config,artifact,settings,seeds));process.start();child.close()
    try:
        if not connection.poll(1800):raise TimeoutError("Real training worker exceeded 1800 seconds")
        result=connection.recv()
        if not result["ok"]:raise RuntimeError(result["error"])
        return result["value"]
    finally:
        process.join(timeout=10)
        if process.is_alive():process.terminate();process.join()
        connection.close()
