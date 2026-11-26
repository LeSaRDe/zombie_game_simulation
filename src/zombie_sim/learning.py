"""Semi-Markov environment adapters, recurrent candidate PPO, and portable artifacts.

Optional dependencies are imported only when the corresponding facility is used.
Reward readers may inspect ledger events; actor encoders receive local observations.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any

from .policies import (ACTION_NAMES, DEFAULT_PARAMETERS, ROLES, Candidate, available, attr,
                       create_model, generate_candidates, identifier, initialize_memory, commit_action_memory, select_utility_index,
                       number, position, records, update_memory)

ENCODER_VERSION = "candidate_v1"
REWARD_VERSIONS = ("human_survival_v1", "zombie_pressure_v1")
FEATURE_NAMES = tuple(DEFAULT_PARAMETERS["weights"])
OBSERVATION_SIZE = 32
CANDIDATE_SIZE = len(ACTION_NAMES) + len(FEATURE_NAMES) + 10


def discounted_interval_reward(terms: list[dict], elapsed: float, gamma: float = .99) -> float:
    """Terms carry offset seconds; continuous rates are integrated, not step-counted."""
    total=0.0
    for term in terms:
        offset=max(0.0,number(term.get("offset",0)))
        if "rate" in term:
            duration=max(0.0,number(term.get("duration",elapsed-offset)))
            integral=duration if gamma==1 else math.expm1(math.log(gamma)*duration)/math.log(gamma)
            total+=number(term["rate"])*gamma**offset*integral
        else:
            total+=number(term.get("value",0))*gamma**offset
    return total


def semi_markov_gae(rewards, values, next_values, elapsed, terminated, truncated=None, gamma=.99, lam=.95):
    """Bootstrap cutoffs; stop recurrent GAE across either episode boundary."""
    truncated=truncated if truncated is not None else [False]*len(rewards)
    advantages=[0.0]*len(rewards); carry=0.0
    for i in reversed(range(len(rewards))):
        discount=gamma**elapsed[i]; decay=lam**elapsed[i]
        delta=rewards[i]+discount*(0 if terminated[i] else next_values[i])-values[i]
        carry=delta+(0 if terminated[i] or truncated[i] else discount*decay*carry)
        advantages[i]=carry
    return advantages,[a+v for a,v in zip(advantages,values)]


def encode_observation(observation: dict, memory: dict | None = None) -> list[float]:
    """Permutation-invariant mean/min pooling; all inputs are visible or remembered."""
    a=observation["self_state"]; x,y=position(a)
    world=observation.get("world",{}); length=max(1,number(world.get("length",1000))); width=max(1,number(world.get("width",1000)))
    now=number(observation.get("time",0)); horizon=number(observation.get("task_horizon",observation.get("horizon",now)))
    values=[number(a.get("life",100))/100,number(a.get("stamina",100))/100,number(attr(a,"hunger",0))/100,
            float(a.get("type")=="Human"),float(a.get("status")=="INFECTED"),x/length,y/width,
            number(attr(a,"speed",2))/5,number(attr(a,"sense_r",40))/100,
            available(a,"FOOD")/16,available(a,"MEDICAL_SUPPLY")/16,available(a,"MATERIAL")/16,
            number(attr(a,"infection_progress",0)),max(0,min(1,(horizon-now)/1800))]
    values.extend(float(a.get("role")==role) for role in ROLES)
    neighbors=records(observation.get("local_agents",{}))
    for kind in ("Human","Zombie"):
        group=[b for b in neighbors if b.get("type")==kind]
        distances=[math.dist((x,y),position(b)) for b in group]
        values.extend([min(1,len(group)/20),min(distances,default=100)/100,
                       sum(number(b.get("life",100)) for b in group)/max(1,len(group))/100])
    m=memory or {}
    values.extend([min(1,len(m.get("sightings",{}))/30),min(1,len(m.get("geometry",{}))/30),
                   min(1,len(observation.get("received_signals",[]))/10),min(1,len(m.get("visits",{}))/100)])
    assert len(values)==OBSERVATION_SIZE
    return values


def encode_candidate(candidate: Candidate, observation: dict) -> list[float]:
    a=observation["self_state"]; intent=candidate.intent
    onehot=[float(intent["action"]==name) for name in ACTION_NAMES]
    fs=[candidate.features.get(k,0.0) for k in FEATURE_NAMES]
    targets=records(observation.get("local_agents",{}))
    for values in observation.get("local_environment",{}).values():
        if isinstance(values,(dict,list)):
            targets.extend(records(values))
    target=next((b for b in targets if str(identifier(b))==str(intent.get("target"))),a)
    x,y=position(a); tx,ty=position(target)
    path=intent.get("parameters",{}).get("path",[])
    if path:
        tx,ty=position(path[-1])
    extra=[candidate.duration/8,candidate.stamina_cost/20,candidate.score/8,
           max(-1,min(1,(tx-x)/100)),max(-1,min(1,(ty-y)/100)),min(1,math.hypot(tx-x,ty-y)/100),
           number(target.get("life",100))/100,float(target.get("status")=="INFECTED"),
           number(intent.get("parameters",{}).get("quantity",0))/16,
           number(intent.get("parameters",{}).get("length",0))/8]
    return onehot+fs+extra


class CandidateCodec:
    """Lossless typed action table paired with neural features and a padding mask.

    Neural features intentionally pool and normalize values. Decoding uses the
    immutable typed table, so quantities, IDs, payloads and path offsets retain
    their original precision instead of being reconstructed from lossy tensors.
    """
    version = ENCODER_VERSION

    def __init__(self, observation, candidates, *, padding=0):
        if not isinstance(padding, int) or isinstance(padding, bool) or padding < 0:
            raise ValueError("padding must be a nonnegative integer")
        self.intents=[];self.features=[]
        for candidate in candidates:
            if isinstance(candidate,Candidate):row=candidate
            else:
                intent=deepcopy(candidate)
                if not isinstance(intent,dict) or intent.get("action") not in ACTION_NAMES or "actor" not in intent:
                    raise ValueError("Invalid typed candidate")
                from .policies import COST,DURATION
                action=intent["action"]
                row=Candidate(intent,{},"Explicit typed candidate",number(intent.get("parameters",{}).get("duration",DURATION[action])),COST[action])
            self.intents.append(deepcopy(row.intent));self.features.append(encode_candidate(row,observation))
        self.mask=[True]*len(self.intents)+[False]*padding
        self.features.extend([[0.]*CANDIDATE_SIZE for _ in range(padding)])
        self.context=encode_observation(observation)

    def decode(self,index):
        if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(self.intents):
            raise ValueError("INVALID_CANDIDATE: padded or out-of-range candidate")
        return deepcopy(self.intents[index])


def build_network(hidden_size: int = 128):
    import torch
    from torch import nn
    class CandidateActorCritic(nn.Module):
        def __init__(self):
            super().__init__()
            self.context=nn.Sequential(nn.Linear(OBSERVATION_SIZE,hidden_size),nn.Tanh(),nn.Linear(hidden_size,hidden_size),nn.Tanh())
            self.recurrent=nn.GRUCell(hidden_size,hidden_size)
            self.candidates=nn.Sequential(nn.Linear(CANDIDATE_SIZE,hidden_size),nn.Tanh(),nn.Linear(hidden_size,hidden_size))
            self.value=nn.Linear(hidden_size,1)
        def forward(self, observation, candidates, hidden):
            next_hidden=self.recurrent(self.context(observation),hidden)
            logits=(self.candidates(candidates)*next_hidden.unsqueeze(-2)).sum(-1)/math.sqrt(hidden_size)
            return logits,self.value(next_hidden).squeeze(-1),next_hidden
    return CandidateActorCritic()


class LearnedModel:
    model_id="ppo/candidate_v1"
    version="1.0.0"
    def __init__(self, network, *, hidden_size=128, parameters=None, metadata=None, candidate_limit=128):
        self.network=network.eval(); self.hidden_size=hidden_size
        if not isinstance(candidate_limit,int) or isinstance(candidate_limit,bool) or candidate_limit<=0:raise ValueError("candidate_limit must be positive")
        self.candidate_limit=candidate_limit
        self.parameters=deepcopy(DEFAULT_PARAMETERS)
        if parameters: self.parameters.update(parameters)
        self.metadata=metadata or {}
        family=self.metadata.get("settings",{}).get("family")
        self.applicable_types=(family,) if family else ("Human","Zombie")
    def initialize_memory(self, agent):
        m=initialize_memory(agent);m["hidden"]=[0.0]*self.hidden_size
        return m
    def decide(self,observation,memory,rng):
        import torch
        if observation["self_state"].get("type") not in self.applicable_types:
            raise ValueError("Learned model is incompatible with the current biological type")
        m=update_memory(observation,memory,self.parameters)
        candidates=generate_candidates(observation,m,self.parameters)[:self.candidate_limit]
        obs=torch.tensor(encode_observation(observation,m),dtype=torch.float32)
        encoded=torch.tensor([encode_candidate(c,observation) for c in candidates],dtype=torch.float32)
        hidden=torch.tensor(m.get("hidden",[0.0]*self.hidden_size),dtype=torch.float32)
        with torch.no_grad():
            logits,value,h=self.network(obs,encoded,hidden)
            probs=torch.softmax(logits,-1).tolist()
        # Use the engine-provided domain-keyed RNG instead of global torch RNG.
        draw=rng.random(); total=0.; chosen=len(candidates)-1
        for i,p in enumerate(probs):
            total+=p
            if draw<total:
                chosen=i;break
        m["hidden"]=h.tolist();m=commit_action_memory(observation,m,candidates[chosen].intent,candidates[chosen].reason)
        return deepcopy(candidates[chosen].intent),m,{"model_id":self.model_id,"encoder":ENCODER_VERSION,
                "candidate_index":chosen,"log_probability":math.log(max(probs[chosen],1e-30)),"value":float(value),
                "candidate_count":len(candidates),"reason":candidates[chosen].reason}
    def decide_batch(self,observations,memories,rngs):
        return [self.decide(o,m,r) for o,m,r in zip(observations,memories,rngs,strict=True)]
    def save(self,path, *, optimizer=None, metadata=None):
        import torch
        path=Path(path);path.mkdir(parents=True,exist_ok=True)
        # Tensor-only weights are loaded with weights_only=True. Metadata/memory are JSON.
        torch.save(self.network.state_dict(),path/"weights.pt")
        if optimizer is not None: torch.save(optimizer.state_dict(),path/"optimizer.pt")
        manifest={"model_id":self.model_id,"model_version":self.version,"encoder_version":ENCODER_VERSION,
                  "observation_version":"local_v0.1","action_vocabulary":"ontology_v0.1","hidden_size":self.hidden_size,
                  "observation_size":OBSERVATION_SIZE,"candidate_size":CANDIDATE_SIZE,"candidate_limit":self.candidate_limit,"parameters":self.parameters,
                  "applicable_types":([(metadata or self.metadata)["settings"]["family"]] if (metadata or self.metadata).get("settings",{}).get("family") else list(self.applicable_types)),
                  "parameter_checksum":hashlib.sha256(json.dumps(self.parameters,sort_keys=True).encode()).hexdigest(),
                  "deterministic":True,"restartable":True,"dependencies":{"torch":torch.__version__},
                  "weights_sha256":hashlib.sha256((path/"weights.pt").read_bytes()).hexdigest(),
                  "training":metadata or self.metadata}
        (path/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
        return manifest
    @classmethod
    def load(cls,path,parameters=None):
        import torch
        path=Path(path);m=json.loads((path/"manifest.json").read_text())
        if m["encoder_version"]!=ENCODER_VERSION or m["candidate_size"]!=CANDIDATE_SIZE or m.get("observation_size")!=OBSERVATION_SIZE:
            raise ValueError("Unsupported learned-policy encoder")
        if m.get("observation_version")!="local_v0.1" or m.get("action_vocabulary")!="ontology_v0.1":
            raise ValueError("Unsupported learned-policy observation or action contract")
        if m.get("parameter_checksum") and hashlib.sha256(json.dumps(m["parameters"],sort_keys=True).encode()).hexdigest()!=m["parameter_checksum"]:
            raise ValueError("Learned-policy parameter checksum mismatch")
        if hashlib.sha256((path/"weights.pt").read_bytes()).hexdigest()!=m["weights_sha256"]:
            raise ValueError("Learned-policy checksum mismatch")
        net=build_network(m["hidden_size"])
        net.load_state_dict(torch.load(path/"weights.pt",map_location="cpu",weights_only=True))
        result=cls(net,hidden_size=m["hidden_size"],parameters=parameters or m["parameters"],metadata=m.get("training",{}),candidate_limit=m.get("candidate_limit",128))
        result.applicable_types=tuple(m.get("applicable_types",result.applicable_types))
        return result


def reward_terms(events, actor_id, family, start, end, before, after, occurrences=None):
    """Versioned term accounting from actual event effects, never attempted damage."""
    terms=[]; start=number(start);end=number(end); actor_id=str(actor_id)
    dead_before=number(before.get("life",0))<=0
    dead_after=number(after.get("life",0))<=0
    converted=family=="Human" and after.get("type")!="Human"
    terminal_at=end
    for e in events:
        if str(e.get("actor",e.get("agent_id","")))==actor_id and e.get("kind",e.get("type")) in ("death","conversion","DEATH","CONVERSION"):
            terminal_at=min(terminal_at,number(e.get("time",end)))
    if family=="Human" and not dead_before:
        duration=max(0,terminal_at-start)
        terms.append({"name":"human_alive_time","rate":.01,"duration":duration,"offset":0,"value":duration*.01})
        if dead_after or converted:
            terms.append({"name":"human_episode_end","value":-10,"offset":terminal_at-start})
    elif family=="Zombie" and dead_after and not dead_before:
        terms.append({"name":"zombie_death","value":-5,"offset":terminal_at-start})
    for event in events:
        when=number(event.get("time",end));offset=max(0,when-start)
        if str(event.get("actor",event.get("source_agent_id","")))!=actor_id:
            continue
        kind=str(event.get("kind",event.get("type",""))).lower()
        payload=event.get("details",event.get("payload",{}))
        target=str(event.get("target",payload.get("target","")))
        if family=="Human":
            resolved=(occurrences or {}).get(str(event.get("occurrence")),{})
            if kind=="action_completed" and event.get("outcome")=="SUCCEEDED" and target!=actor_id:
                if event.get("action")=="first_aid" and number(resolved.get("healing",0))>0:
                    terms.append({"name":"heal_other","value":.01*number(resolved["healing"]),"offset":offset})
            if kind in ("cure","infection_cured") and target!=actor_id:
                terms.append({"name":"cure_other","value":2,"offset":offset})
            healed=number(payload.get("actual_healing",event.get("actual_healing",0)))
            if healed>0 and target!=actor_id:
                terms.append({"name":"heal_other","value":.01*healed,"offset":offset})
        else:
            if kind in ("infection","infected","infection_created") and not payload.get("initial",False):
                terms.append({"name":"new_infection","value":1,"offset":offset})
            damage=number(payload.get("actual_damage",event.get("actual_damage",0)))
            if damage>0 and payload.get("target_type",event.get("target_type"))=="Human":
                terms.append({"name":"damage_human","value":.02*damage,"offset":offset})
    return terms


try:
    import gymnasium as gym
    _GymBase=gym.Env
except ImportError:
    gym=None
    _GymBase=object


class ControlledAgentEnv(_GymBase):
    """Gymnasium candidate-index environment; opponents use frozen default models.

    `terminated` includes the task horizon and human conversion. `truncated` is
    reserved for an external decision budget; its final observation bootstraps.
    The fixed candidate padding size is a declared encoder restriction.
    """
    metadata={"render_modes":[]}
    def __init__(self,config,actor_id=None,*,family="Human",max_candidates=128,decision_limit=None,gamma=.99):
        if gym is None:
            raise ImportError("Install zombie-sim[learning] (gymnasium, numpy, torch, pettingzoo)")
        import numpy as np
        from .config import resolve_config
        self.config=resolve_config(config);self.requested_actor=actor_id;self.family=family;self._initial_family=family
        self.max_candidates=max_candidates;self.decision_limit=decision_limit;self.gamma=gamma
        self.action_space=gym.spaces.Discrete(max_candidates)
        self.observation_space=gym.spaces.Dict({
            "context":gym.spaces.Box(-np.inf,np.inf,(OBSERVATION_SIZE,),dtype=np.float32),
            "candidates":gym.spaces.Box(-np.inf,np.inf,(max_candidates,CANDIDATE_SIZE),dtype=np.float32),
            "action_mask":gym.spaces.MultiBinary(max_candidates)})
        self.sim=None;self.memories={};self.current_candidates=[];self.batch=[];self.decisions=0
    def _agents(self):
        return self.sim.state["agents"]
    def _actor(self):
        return self._agents()[str(self.actor_id)]
    def _terminal(self):
        actor=self._actor()
        return number(actor.get("life",0))<=0 or actor.get("type")!=self.family or number(self.sim.time)>=number(self.config.get("horizon",1800))
    def _next_batch(self):
        batch=self.sim.next_decision_batch()
        if isinstance(batch,dict):
            batch=list(batch.values())
        if getattr(self,"scripted_others",False):
            batch=[o for o in batch if str(identifier(o["self_state"]))==str(self.actor_id)]
        return batch
    def _opponent_intent(self,obs):
        aid=str(identifier(obs["self_state"]));a=obs["self_state"]
        rng=random.Random(f"{self.seed_value}:{aid}:{self.opponent_steps.get(aid,0)}")
        assignment=a.get("model_assignment",{})
        model=create_model(assignment.get("model_id",a["type"]+"DefaultModel"),assignment.get("parameters"))
        intent,memory,_=model.decide(obs,self.memories.get(aid),rng)
        self.memories[aid]=memory;self.opponent_steps[aid]=self.opponent_steps.get(aid,0)+1
        return intent
    def _submit_batch(self, intents):
        results=self.sim.submit_intents(intents)
        if isinstance(results,list):
            waits=[{"actor":r["actor"],"action":"wait","parameters":{"duration":1}} for r in results if isinstance(r,dict) and r.get("status")=="REJECTED"]
            if waits: self.sim.submit_intents(waits)
        return results
    def _advance_event(self):
        cutoff=getattr(self,"rollout_cutoff_at",None)
        if cutoff is not None and number(self.sim.next_event_time())>cutoff:
            self.sim.advance_until(cutoff,return_snapshot=False)
            return
        old=(self.sim.time,self.sim.revision)
        self.sim.step(timestamp=True,return_snapshot=False)
        if old==(self.sim.time,self.sim.revision):
            self.sim.advance_until(self.config.get("horizon",1800),return_snapshot=False)
    def _seek_actor(self):
        while not self._terminal():
            if getattr(self,"rollout_cutoff_at",None) is not None and number(self.sim.time)>=self.rollout_cutoff_at:
                return
            self.batch=self._next_batch()
            if not self.batch:
                self._advance_event()
                continue
            if any(str(identifier(o["self_state"]))==str(self.actor_id) for o in self.batch):
                return
            self._submit_batch([self._opponent_intent(o) for o in self.batch])
    def _observation(self):
        import numpy as np
        obs=self.sim.observe(self.actor_id)
        obs["task_horizon"]=self.config.get("horizon",1800)
        terminal=self._terminal()
        prior=self.memories.get(str(self.actor_id))
        m=deepcopy(prior) if terminal and prior is not None else update_memory(obs,prior,DEFAULT_PARAMETERS)
        self.memories[str(self.actor_id)]=m;self.raw_observation=obs
        self.current_candidates=generate_candidates(obs,m)[:self.max_candidates] if not terminal else []
        self.candidate_codec=CandidateCodec(obs,self.current_candidates,padding=self.max_candidates-len(self.current_candidates))
        matrix=np.asarray(self.candidate_codec.features,dtype=np.float32)
        mask=np.asarray(self.candidate_codec.mask,dtype=np.int8)
        return {"context":np.array(encode_observation(obs,m),dtype=np.float32),"candidates":matrix,"action_mask":mask}
    def reset(self,*,seed=None,options=None):
        super().reset(seed=seed)
        if options and options.get("continue_identity") is not None:
            if seed is not None:
                raise ValueError("Continuing an identity cannot reseed an existing simulation")
            return self.begin_controller_episode(options["continue_identity"],family=options.get("family"))
        from .engine import Simulation
        self.family=self._initial_family
        self.seed_value=int(seed if seed is not None else self.config.get("seed",0))
        cfg=deepcopy(self.config);cfg["seed"]=self.seed_value
        if self.sim: self.sim.close()
        self.sim=Simulation(cfg,decision_mode="scripted")
        candidates=[a for a in self._agents().values() if a.get("type")==self.family and a.get("life",0)>0]
        if not candidates: raise ValueError(f"No living {self.family} controller available")
        self.actor_id=str(self.requested_actor if self.requested_actor is not None else sorted(candidates,key=lambda a:str(identifier(a)))[0]["id"])
        if self.actor_id not in self._agents() or self._actor().get("type")!=self.family or self._actor().get("life",0)<=0:
            raise ValueError("Requested actor is not a living member of the controlled policy family")
        self.memories={};self.opponent_steps={};self.decisions=0;self.controller_generation=0;self.retired_controller_memories=[]
        self.episode_id=f"{self.sim.state.get('run_id',self.seed_value)}:{self.actor_id}:{self.family}:0"
        self._seek_actor()
        return self._observation(),{"controller_episode_id":self.episode_id,"actor_id":self.actor_id,"elapsed":0.0}
    def attach(self,simulation,actor_id,*,scripted_others=True,rollout_cutoff=None):
        """Attach an existing coordinator without resetting its world or RNG."""
        if self.sim is not None and self.sim is not simulation:raise RuntimeError("Environment already owns a simulation")
        self.sim=simulation;self.actor_id=str(actor_id)
        if self.actor_id not in self._agents() or self._actor()["life"]<=0 or self._actor()["type"]!=self.family:
            raise ValueError("Controlled identity is not a living member of the policy family")
        self.seed_value=simulation.seed;self.scripted_others=scripted_others
        self.rollout_cutoff_at=number(simulation.time)+number(rollout_cutoff) if rollout_cutoff is not None else None
        self.memories={};self.opponent_steps={};self.decisions=0;self.controller_generation=0;self.retired_controller_memories=[]
        self.episode_id=f"{simulation.state['run_id']}:{self.actor_id}:{self.family}:0"
        self._seek_actor()
        return self._observation(),{"controller_episode_id":self.episode_id,"actor_id":self.actor_id,"elapsed":0.0}
    def begin_controller_episode(self,actor_id,family=None):
        """Start a fresh controller under an existing living simulation identity.

        This is useful after human conversion: the world/time and persistent ID
        continue, while controller memory and the recurrent episode reset.
        """
        if self.sim is None:raise RuntimeError("Initialize a simulation before continuing an identity")
        actor_id=str(actor_id)
        if actor_id!=str(self.actor_id):
            raise ValueError("continue_identity must preserve the current persistent identity")
        agent=self._agents().get(actor_id)
        family=family or (agent.get("type") if agent else None)
        if agent is None or agent.get("life",0)<=0 or agent.get("type")!=family:
            raise ValueError("A controller requires a living identity of its applicable type")
        if number(self.sim.time)>=number(self.config["horizon"]):
            raise ValueError("The finite task horizon has ended; start a new simulation")
        old=self.memories.pop(actor_id,{})
        self.retired_controller_memories.append({"episode_id":self.episode_id,"agent_id":actor_id,"time":str(self.sim.time),"memory":deepcopy(old)})
        self.actor_id=actor_id;self.family=family;self.decisions=0;self.controller_generation+=1
        self.episode_id=f"{self.sim.state.get('run_id',self.seed_value)}:{actor_id}:{family}:{self.controller_generation}"
        self._seek_actor()
        return self._observation(),{"controller_episode_id":self.episode_id,"actor_id":actor_id,"elapsed":0.0,"continued_simulation":True}
    def step(self,action):
        if self._terminal(): raise RuntimeError("Reset a terminated controller before stepping")
        if not self.action_space.contains(action) or int(action)>=len(self.current_candidates):
            raise ValueError("Padded or masked candidate cannot be executed")
        chosen=self.current_candidates[int(action)]
        return self.step_intent(self.candidate_codec.decode(int(action)),reason=chosen.reason)
    def step_intent(self,intent,*,reason=None):
        """Execute an observation-derived typed intent, without encoder pruning.

        Used for the full utility/random baselines. Gym's indexed `step` retains
        its explicit fixed candidate-space restriction for learning algorithms.
        """
        if self._terminal():raise RuntimeError("Reset a terminated controller before stepping")
        if str(intent.get("actor"))!=str(self.actor_id):raise ValueError("Intent actor differs from controlled identity")
        before=deepcopy(self._actor());start=number(self.sim.time);event_start=len(self.sim.events)
        intent=deepcopy(intent)
        self.memories[str(self.actor_id)]=commit_action_memory(self.raw_observation,self.memories[str(self.actor_id)],intent,reason)
        submissions=[intent if str(identifier(o["self_state"]))==self.actor_id else self._opponent_intent(o) for o in self.batch]
        self._submit_batch(submissions);self.decisions+=1
        self._seek_actor();end=number(self.sim.time)
        terms=reward_terms(self.sim.events[event_start:],self.actor_id,self.family,start,end,before,self._actor(),self.sim.occurrences)
        terminal=self._terminal();truncated=bool(not terminal and ((self.decision_limit is not None and self.decisions>=self.decision_limit) or
            (getattr(self,"rollout_cutoff_at",None) is not None and end>=self.rollout_cutoff_at)))
        obs=self._observation()
        info={"elapsed":end-start,"reward_terms":terms,"undiscounted_reward":sum(t.get("value",0) for t in terms),
              "intent":intent,"controller_episode_id":self.episode_id,"time":end,"actor_id":self.actor_id,
              "termination_reason":"death" if self._actor()["life"]<=0 else "conversion" if self._actor()["type"]!=self.family else "task_horizon" if terminal else "rollout_cutoff" if truncated else None}
        return obs,discounted_interval_reward(terms,end-start,self.gamma),terminal,truncated,info
    def close(self):
        if self.sim: self.sim.close();self.sim=None


try:
    from pettingzoo import AECEnv as _AECBase
except ImportError:
    _AECBase=object


class DecisionBatchAEC(_AECBase):
    """AEC collection of frozen simultaneous decision observations.

    The entire current batch is collected before any admission; this adapter does
    not advertise Parallel conversion. Nonlearning agents use default policies.
    """
    metadata={"name":"zombie_sim_aec_v1","is_parallelizable":False,"render_modes":[]}
    def __init__(self,config,controlled_ids=None,*,family=None,max_candidates=128):
        if _AECBase is object: raise ImportError("Install pettingzoo for the AEC adapter")
        from .config import resolve_config
        self.config=resolve_config(config);self.controlled_ids=controlled_ids;self.family=family;self.max_candidates=max_candidates
        pop=self.config["population"]
        specs=self.config.get("agents") or [{"id":str(i+1),"type":"Human" if i<pop["humans"] else "Zombie"} for i in range(pop["humans"]+pop["zombies"])]
        self.possible_agents=[str(i) for i in controlled_ids] if controlled_ids is not None else [str(a["id"]) for a in specs if family is None or a.get("type","Human")==family]
        self.agents=[];self.agent_selection=None
        self._env=ControlledAgentEnv(self.config,family=family or ("Human" if pop["humans"] else "Zombie"),max_candidates=max_candidates)
    def observation_space(self,agent): return self._env.observation_space
    def action_space(self,agent): return self._env.action_space
    def reset(self,seed=None,options=None):
        self._env.reset(seed=seed)
        self._initialize_batch_state()
    def attach(self,simulation):
        first=str(self.controlled_ids[0]) if self.controlled_ids else next(iter(simulation.state["agents"]))
        self._env.family=simulation.state["agents"][first]["type"]
        self._env.attach(simulation,first,scripted_others=False)
        self._initialize_batch_state()
        return self
    def _initialize_batch_state(self):
        all_ids=list(self._env._agents())
        self.possible_agents=[str(x) for x in self.controlled_ids] if self.controlled_ids is not None else [i for i in all_ids if self.family is None or self._env._agents()[i]["type"]==self.family]
        self.agents=list(self.possible_agents);self.initial_types={i:self._env._agents()[i]["type"] for i in self.agents}
        self.rewards={i:0. for i in self.agents};self._cumulative_rewards=self.rewards.copy()
        self.terminations={i:False for i in self.agents};self.truncations={i:False for i in self.agents};self.infos={i:{} for i in self.agents}
        self._pending={};self._frozen={};self._raw_frozen={};self._candidates={};self._batch=[];self._queue=[]
        self._interval_start={i:number(self._env.sim.time) for i in self.agents}
        self._interval_terms={i:[] for i in self.agents}
        self._episode_ids={i:f"{self._env.sim.state.get('run_id')}:{i}:{self.initial_types[i]}:0" for i in self.agents}
        self._freeze_next()
    def set_batch_order(self,order):
        """Choose a collection order without changing the frozen observations."""
        if set(order)!=set(self._queue) or len(order)!=len(self._queue) or any(i in self._pending for i in order):
            raise ValueError("Order must cover exactly the unsubmitted frozen controllers")
        self._queue=list(order);self.agent_selection=self._queue[0]
    def raw_observation(self,agent):
        return deepcopy(self._raw_frozen[agent])
    def _freeze_next(self):
        import numpy as np
        while self.agents:
            batch=self._env._next_batch()
            self._batch=batch;self._queue=[];self._frozen={};self._raw_frozen={};self._pending={}
            for obs in batch:
                aid=str(identifier(obs["self_state"]))
                if aid not in self.agents:
                    self._pending[aid]=self._env._opponent_intent(obs);continue
                m=update_memory(obs,self._env.memories.get(aid),DEFAULT_PARAMETERS);self._env.memories[aid]=m
                candidates=generate_candidates(obs,m)[:self.max_candidates];self._candidates[aid]=candidates
                matrix=np.zeros((self.max_candidates,CANDIDATE_SIZE),dtype=np.float32);mask=np.zeros(self.max_candidates,dtype=np.int8)
                for i,c in enumerate(candidates): matrix[i]=encode_candidate(c,obs);mask[i]=1
                self._frozen[aid]={"context":np.array(encode_observation(obs,m),dtype=np.float32),"candidates":matrix,"action_mask":mask}
                self._raw_frozen[aid]=deepcopy(obs)
                self._queue.append(aid)
            if self._queue:
                self.agent_selection=self._queue[0];return
            if not batch:
                if number(self._env.sim.time)>=number(self.config.get("horizon",1800)) or not any(a["life"]>0 for a in self._env._agents().values()):
                    for aid in self.agents: self.terminations[aid]=True
                    self.agent_selection=self.agents[0];return
                self._env._advance_event()
                # Offer dead/type-ended controllers their mandatory dead step.
                ended=[i for i in self.agents if self._env._agents()[i]["life"]<=0 or self._env._agents()[i]["type"]!=self.initial_types[i]]
                if ended:
                    for i in ended:self.terminations[i]=True
                    self.agent_selection=ended[0];return
                continue
            self._env._submit_batch(list(self._pending.values()))
    def observe(self,agent):
        import numpy as np
        if agent in self._frozen: return deepcopy(self._frozen[agent])
        return {"context":np.zeros(OBSERVATION_SIZE,dtype=np.float32),"candidates":np.zeros((self.max_candidates,CANDIDATE_SIZE),dtype=np.float32),"action_mask":np.zeros(self.max_candidates,dtype=np.int8)}
    def _account_interval(self,start,event_start,before):
        """Account every world advance relative to each controller's own origin."""
        end=number(self._env.sim.time)
        self._clear_rewards()
        for i in self.agents:
            after=self._env._agents()[i]
            was_active=before[i]["life"]>0 and before[i]["type"]==self.initial_types[i]
            terms=reward_terms(self._env.sim.events[event_start:],i,self.initial_types[i],start,end,before[i],after,self._env.sim.occurrences) if was_active else []
            offset=max(0.0,start-self._interval_start[i])
            shifted=[dict(term,offset=number(term.get("offset",0))+offset) for term in terms]
            self._interval_terms[i].extend(shifted)
            self.rewards[i]=discounted_interval_reward(shifted,end-self._interval_start[i],self._env.gamma)
            self.terminations[i]=after["life"]<=0 or after["type"]!=self.initial_types[i] or end>=number(self.config["horizon"])
            self.infos[i]={"elapsed":end-self._interval_start[i],"reward_terms":deepcopy(self._interval_terms[i]),"controller_episode_id":self._episode_ids[i]}
        self._accumulate_rewards()
        self._deads_step_first()
    def step(self,action):
        aid=self.agent_selection
        if self.terminations[aid] or self.truncations[aid]:
            if action is not None: raise ValueError("Dead agents require a None action")
            self._clear_rewards()
            self.agents.remove(aid)
            for mapping in (self.rewards,self._cumulative_rewards,self.terminations,self.truncations,self.infos,self._frozen,self._raw_frozen,self._candidates,self._interval_start,self._interval_terms,self._episode_ids):
                mapping.pop(aid,None)
            self._queue=[i for i in self._queue if i!=aid]
            if not self.agents:
                self.agent_selection=None;return
            start=number(self._env.sim.time);event_start=len(self._env.sim.events)
            before={i:deepcopy(self._env._agents()[i]) for i in self.agents}
            ended=[i for i in self.agents if self.terminations[i] or self.truncations[i]]
            if ended:self.agent_selection=ended[0]
            elif self._queue:self.agent_selection=self._queue[0]
            else:self._freeze_next()
            self._account_interval(start,event_start,before)
            return
        if action is None or not 0<=int(action)<len(self._candidates[aid]): raise ValueError("Masked candidate")
        self._cumulative_rewards[aid]=0;self._clear_rewards()
        self._interval_start[aid]=number(self._env.sim.time);self._interval_terms[aid]=[]
        chosen=self._candidates[aid][int(action)]
        self._step_typed(chosen.intent,chosen.reason)
    def step_intent(self,intent,*,reason=None):
        aid=self.agent_selection
        if self.terminations[aid] or self.truncations[aid]:raise ValueError("Dead controller cannot submit an intent")
        if str(intent.get("actor"))!=aid:raise ValueError("Intent actor differs from AEC selection")
        self._cumulative_rewards[aid]=0;self._clear_rewards()
        self._interval_start[aid]=number(self._env.sim.time);self._interval_terms[aid]=[]
        self._step_typed(intent,reason)
    def _step_typed(self,intent,reason):
        aid=self.agent_selection
        self._env.memories[aid]=commit_action_memory(self._raw_frozen[aid],self._env.memories[aid],intent,reason)
        self._pending[aid]=deepcopy(intent);self._queue.pop(0)
        if self._queue:
            self.agent_selection=self._queue[0];return
        start=number(self._env.sim.time);event_start=len(self._env.sim.events)
        before={i:deepcopy(self._env._agents()[i]) for i in self.agents}
        self._env._submit_batch(list(self._pending.values()))
        self._freeze_next()
        self._account_interval(start,event_start,before)
    def close(self):
        if self._env: self._env.close()


@dataclass
class TrainingConfig:
    decisions: int = 4096
    rollout: int = 1024
    epochs: int = 4
    sequence_length: int = 32
    minibatch: int = 256
    hidden_size: int = 128
    learning_rate: float = 3e-4
    clip: float = .2
    gamma: float = .99
    lam: float = .95
    entropy: float = .01
    seed: int = 20261106
    family: str = "Human"
    device: str = "cpu"
    train_seeds: tuple[int,...] = tuple(range(100,110))
    validation_seeds: tuple[int,...] = tuple(range(1000,1005))
    evaluation_seeds: tuple[int,...] = tuple(range(2000,2030))

    def __post_init__(self):
        for field in ("decisions","rollout","epochs","sequence_length","minibatch","hidden_size"):
            value=getattr(self,field)
            if isinstance(value,bool) or not isinstance(value,int) or value<=0:
                raise ValueError(f"training.{field} must be a positive integer")
        for field in ("learning_rate","gamma","lam","clip","entropy"):
            value=getattr(self,field)
            if not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError(f"training.{field} must be finite")
        if self.learning_rate<=0 or not 0<self.gamma<=1 or not 0<=self.lam<=1 or not 0<self.clip<1 or self.entropy<0:
            raise ValueError("Invalid learning rate, discount, advantage decay, clipping, or entropy coefficient")
        if self.family not in ("Human","Zombie"):
            raise ValueError("training.family must be Human or Zombie")
        for field in ("train_seeds","validation_seeds","evaluation_seeds"):
            values=getattr(self,field)
            if not values or any(isinstance(v,bool) or not isinstance(v,int) or v<0 for v in values):
                raise ValueError(f"training.{field} must contain nonnegative integer seeds")
            if len(set(values))!=len(values):
                raise ValueError(f"training.{field} cannot repeat seeds")
            setattr(self,field,tuple(values))
        if set(self.train_seeds)&set(self.validation_seeds) or set(self.train_seeds)&set(self.evaluation_seeds) or set(self.validation_seeds)&set(self.evaluation_seeds):
            raise ValueError("Training, validation, and held-out seed sets must be disjoint")


def _tensor_state(obs,torch,device=None):
    valid=int(obs["action_mask"].sum())
    return torch.tensor(obs["context"],dtype=torch.float32,device=device),torch.tensor(obs["candidates"][:valid],dtype=torch.float32,device=device)


def evaluate(config,artifact=None,seeds=range(2000,2030),*,family="Human",policy="default",max_decisions=10000,access_log=None,split=None,phase=None):
    import torch
    model=LearnedModel.load(artifact) if artifact else None
    if model and family not in model.applicable_types:
        raise ValueError("Evaluation family is incompatible with the learned artifact")
    seeds=tuple(seeds)
    rows=[]
    for seed in seeds:
        env=ControlledAgentEnv(config,family=family,decision_limit=max_decisions,max_candidates=model.candidate_limit if model else 128)
        obs,_=env.reset(seed=int(seed));reward_total=0.;steps=0;done=False;terms={};hidden=torch.zeros(model.hidden_size) if model else None
        if access_log is not None:access_log.append({"split":split,"phase":phase,"seed":int(seed),"operation":"evaluate","policy":policy})
        rng=random.Random(int(seed))
        while not done:
            if model:
                with torch.no_grad():
                    context,candidates=_tensor_state(obs,torch);logits,_,hidden=model.network(context,candidates,hidden)
                probs=torch.softmax(logits,-1).tolist();u=rng.random();acc=0;action=len(probs)-1
                for i,p in enumerate(probs):
                    acc+=p
                    if u<acc:action=i;break
                transition=env.step(action)
            else:
                full_candidates=generate_candidates(env.raw_observation,env.memories[str(env.actor_id)])
                index=rng.randrange(len(full_candidates)) if policy=="random" else select_utility_index(full_candidates,rng)
                chosen=full_candidates[index]
                transition=env.step_intent(chosen.intent,reason=chosen.reason)
            obs,reward,terminated,truncated,info=transition;reward_total+=info["undiscounted_reward"];steps+=1;done=terminated or truncated
            for term in info["reward_terms"]: terms[term["name"]]=terms.get(term["name"],0)+term.get("value",0)
        rows.append({"seed":int(seed),"reward":reward_total,"decisions":steps,"survival_seconds":info["time"],"reason":info["termination_reason"],"terms":terms})
        env.close()
    mean=lambda key:sum(row[key] for row in rows)/max(1,len(rows))
    reward_mean=mean("reward");sd=math.sqrt(sum((r["reward"]-reward_mean)**2 for r in rows)/max(1,len(rows)-1))
    return {"policy":str(artifact) if artifact else policy,"family":family,"candidate_limit":model.candidate_limit if model else None,"seeds":list(map(int,seeds)),"runs":rows,
            "mean_reward":reward_mean,"mean_survival_seconds":mean("survival_seconds"),
            "reward_mean_95_normal_interval":[reward_mean-1.96*sd/math.sqrt(max(1,len(rows))),reward_mean+1.96*sd/math.sqrt(max(1,len(rows)))]}


def train(config,output,settings:TrainingConfig|None=None):
    """Actual recurrent PPO with event-time rewards, sequence replay, and reload evaluation."""
    import torch
    s=settings or TrainingConfig();torch.manual_seed(s.seed);torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    if set(s.train_seeds)&set(s.validation_seeds) or set(s.train_seeds)&set(s.evaluation_seeds) or set(s.validation_seeds)&set(s.evaluation_seeds):
        raise ValueError("Training, validation, and held-out seed sets must be disjoint")
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    network=build_network(s.hidden_size).to(s.device);optimizer=torch.optim.Adam(network.parameters(),lr=s.learning_rate)
    env=ControlledAgentEnv(config,family=s.family,gamma=s.gamma)
    episode=0;obs,_=env.reset(seed=s.train_seeds[0]);hidden=torch.zeros(s.hidden_size,device=s.device)
    split_accesses=[{"split":"train","phase":"optimization","seed":s.train_seeds[0],"operation":"reset"}]
    steps=0;losses=[];rollout_log=[];episode_returns=[];episode_return=0.
    initial_checksum=hashlib.sha256(b"".join(t.detach().cpu().numpy().tobytes() for t in network.state_dict().values())).hexdigest()
    # An imitation checkpoint supplies a reproducible pipeline baseline.
    imitation_optimizer=torch.optim.Adam(network.parameters(),lr=s.learning_rate)
    imitation_rows=[]
    imitation_env=ControlledAgentEnv(config,family=s.family,decision_limit=128)
    io,_=imitation_env.reset(seed=s.train_seeds[0]);ih=torch.zeros(s.hidden_size,device=s.device)
    split_accesses.append({"split":"train","phase":"imitation","seed":s.train_seeds[0],"operation":"reset"})
    imitation_rng=random.Random(s.train_seeds[0])
    for _ in range(min(128,s.decisions)):
        context,candidate_tensor=_tensor_state(io,torch,s.device);label=select_utility_index(imitation_env.current_candidates,imitation_rng)
        imitation_rows.append((context,candidate_tensor,label));io,_,term,trunc,_=imitation_env.step(label)
        if term or trunc:break
    for _ in range(2):
        ih=torch.zeros(s.hidden_size,device=s.device)
        for context,candidate_tensor,label in imitation_rows:
            logits,_,ih=network(context,candidate_tensor,ih.detach())
            loss=torch.nn.functional.cross_entropy(logits.unsqueeze(0),torch.tensor([label],device=s.device))
            imitation_optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(network.parameters(),.5);imitation_optimizer.step()
    LearnedModel(network,hidden_size=s.hidden_size).save(output/"imitation",metadata={"method":"behavior_cloning","examples":len(imitation_rows),"seed":s.train_seeds[0],"settings":{"family":s.family}})
    imitation_env.close()
    # PPO starts from the imitation baseline; this is recorded explicitly.
    ppo_initial_checksum=hashlib.sha256(b"".join(t.detach().cpu().numpy().tobytes() for t in network.state_dict().values())).hexdigest()
    while steps<s.decisions:
        rollout=[]
        for _ in range(min(s.rollout,s.decisions-steps)):
            context,candidate_tensor=_tensor_state(obs,torch,s.device)
            with torch.no_grad():
                logits,value,next_hidden=network(context,candidate_tensor,hidden)
                distribution=torch.distributions.Categorical(logits=logits);action=distribution.sample();logp=distribution.log_prob(action)
            intents=[deepcopy(c.intent) for c in env.current_candidates]
            next_obs,reward,terminated,truncated,info=env.step(int(action));episode_return+=info["undiscounted_reward"]
            with torch.no_grad():
                if terminated: next_value=0.0
                else:
                    nc,ncand=_tensor_state(next_obs,torch,s.device);_,nv,_=network(nc,ncand,next_hidden);next_value=float(nv)
            row={"context":context,"candidates":candidate_tensor,"hidden":hidden.detach().clone(),"action":int(action),
                 "log_probability":float(logp),"value":float(value),"next_value":next_value,"reward":reward,"elapsed":info["elapsed"],
                 "terminated":terminated,"truncated":truncated,"episode":episode,"candidate_intents":intents,
                 "reward_terms":info["reward_terms"],"candidate_mask":obs["action_mask"].tolist()}
            rollout.append(row);steps+=1;hidden=next_hidden.detach();obs=next_obs
            if terminated or truncated:
                episode_returns.append(episode_return);episode_return=0.;episode+=1
                obs,_=env.reset(seed=s.train_seeds[episode%len(s.train_seeds)]);hidden=torch.zeros(s.hidden_size,device=s.device)
                split_accesses.append({"split":"train","phase":"optimization","seed":s.train_seeds[episode%len(s.train_seeds)],"operation":"reset"})
        advantages,returns=semi_markov_gae([r["reward"] for r in rollout],[r["value"] for r in rollout],[r["next_value"] for r in rollout],
            [r["elapsed"] for r in rollout],[r["terminated"] for r in rollout],[r["truncated"] for r in rollout],s.gamma,s.lam)
        av=torch.tensor(advantages,device=s.device);av=(av-av.mean())/(av.std(unbiased=False)+1e-8)
        for i,r in enumerate(rollout):r["advantage"]=av[i];r["return"]=returns[i]
        # Contiguous sequence chunks preserve recurrence; rollout boundaries are
        # truncated BPTT boundaries, not fabricated environment terminations.
        sequences=[];sequence=[]
        for r in rollout:
            if sequence and (len(sequence)>=s.sequence_length or r["episode"]!=sequence[-1]["episode"]):sequences.append(sequence);sequence=[]
            sequence.append(r)
        if sequence:sequences.append(sequence)
        for _ in range(s.epochs):
            random.Random(s.seed+steps+_).shuffle(sequences)
            for offset in range(0,len(sequences),max(1,s.minibatch//s.sequence_length)):
                loss_terms=[]
                for seq in sequences[offset:offset+max(1,s.minibatch//s.sequence_length)]:
                    h=seq[0]["hidden"]
                    for r in seq:
                        logits,value,h=network(r["context"],r["candidates"],h)
                        dist=torch.distributions.Categorical(logits=logits);logp=dist.log_prob(torch.tensor(r["action"],device=s.device))
                        ratio=torch.exp(logp-r["log_probability"])
                        surrogate=torch.minimum(ratio*r["advantage"],torch.clamp(ratio,1-s.clip,1+s.clip)*r["advantage"])
                        loss_terms.append(-surrogate+.5*(value-r["return"])**2-s.entropy*dist.entropy())
                loss=torch.stack(loss_terms).mean();optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(network.parameters(),.5);optimizer.step();losses.append(float(loss.detach()))
        rollout_log.extend({k:v.tolist() if hasattr(v,"tolist") else v for k,v in r.items()} for r in rollout)
        LearnedModel(network,hidden_size=s.hidden_size).save(output/"latest",optimizer=optimizer,metadata={"decisions":steps,"settings":asdict(s)})
    env.close()
    final_checksum=hashlib.sha256(b"".join(t.detach().cpu().numpy().tobytes() for t in network.state_dict().values())).hexdigest()
    validation=evaluate(config,output/"latest",s.validation_seeds,family=s.family,access_log=split_accesses,split="validation",phase="selection")
    # Only one PPO checkpoint is selected here; broader search may use validation only.
    model=LearnedModel.load(output/"latest")
    manifest=model.save(output/"selected",metadata={"method":"recurrent_candidate_ppo","initialization":"imitation", "decisions":steps,"settings":asdict(s),"validation":validation})
    comparisons={name:evaluate(config,artifact,seeds=s.evaluation_seeds,family=s.family,policy=name,access_log=split_accesses,split="test",phase="after_selection") for name,artifact in (("default",None),("random",None),("imitation",output/"imitation"),("ppo",output/"selected"))}
    report={"settings":asdict(s),"config":config,"source_config_sha256":hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
            "decisions":steps,"weights_changed":initial_checksum!=final_checksum,"ppo_weights_changed":ppo_initial_checksum!=final_checksum,
            "optimization_steps":len(losses),"imitation_examples":len(imitation_rows),"ppo_initial_weights_sha256":ppo_initial_checksum,"initial_weights_sha256":initial_checksum,
            "final_weights_sha256":final_checksum,"mean_loss":sum(losses)/max(1,len(losses)),"episode_returns":episode_returns,
            "validation":validation,"comparisons":comparisons,"artifact":str(output/"selected"),"reload_verified":True,"split_accesses":split_accesses}
    (output/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    with (output/"rollouts.jsonl").open("w") as handle:
        for row in rollout_log:handle.write(json.dumps(row,separators=(",",":"))+"\n")
    return report
