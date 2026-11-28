"""DecisionService owns decisions behavior behind an explicit context port."""
from __future__ import annotations
from copy import deepcopy
import math
import multiprocessing
import time as wall_clock
from ..domain import profile
from ..interrupts import BoundaryProcessPool as ProcessPoolExecutor, ignore_worker_sigint
from ..engine import stamp, _policy_call, _observe_policy_chunk
from .ports import DecisionContext


class DecisionService:
    def __init__(self, context: DecisionContext):
        self.context = context

    def _decide(self, aids):
        context = self.context
        rows = self._infer(aids)
        return context._run_rule('decision_batch', {'rows':rows, 'agents':list(aids)})

    def _infer(self, aids):
        context = self.context
        aids = sorted(set(aids))
        controllers=[]
        for aid in aids:
            a = context.world_view["agents"][aid]
            if a["life"] == 0 or a.get("active_action"):
                continue
            assignment = a.get("model_assignment") or {}
            model = assignment.get("model_id", "HumanDefaultModel" if a["type"] == "Human" else "ZombieDefaultModel")
            seed = int(context._random("policy",f"{aid}:{stamp(context.time)}")*2**64)
            controllers.append((aid,deepcopy(context.memories.get(aid,{})),seed,model,assignment.get("parameters")))
        started=wall_clock.perf_counter()
        execution=context.config.get("execution",{})
        if context.workers > 1 and len(controllers) >= execution.get("parallel_min_agents",32):
            if context._pool is None:
                context._pool = ProcessPoolExecutor(context.workers,mp_context=multiprocessing.get_context("spawn"),initializer=ignore_worker_sigint)
            tasks=context._observation_tasks(controllers)
            chunks=context.services.parallel.ordered_results(context._pool,_observe_policy_chunk,tasks,
                completion_order=execution.get("completion_order","native"),seed=execution.get("completion_order_seed",0))
            rows=[row for chunk in chunks for row in chunk["rows"]]
            metrics=getattr(context,"_runtime_performance",{})
            worker_cpu=metrics.setdefault("worker_cpu_seconds",{})
            for chunk in chunks:
                key=str(chunk["pid"]);worker_cpu[key]=worker_cpu.get(key,0.)+chunk["cpu_seconds"]
            metrics["parallel_decisions"]=metrics.get("parallel_decisions",0)+len(rows)
            metrics["parallel_batches"]=metrics.get("parallel_batches",0)+1
            context._runtime_performance=metrics
        else:
            rows=[]
            for aid,memory,seed,model,parameters in controllers:
                observation=context.observe(aid)
                rows.append((observation,_policy_call((observation,memory,seed,model,parameters))))
        metrics=getattr(context,"_runtime_performance",{})
        metrics["observation_policy_wall_seconds"]=metrics.get("observation_policy_wall_seconds",0.)+wall_clock.perf_counter()-started
        metrics["decisions"]=metrics.get("decisions",0)+len(rows)
        context._runtime_performance=metrics
        return rows

    def _decide_inner(self, aids):
        return self._decide(aids)

    def _observation_tasks(self,controllers):
        """Freeze only neighborhood records needed by each observer chunk.

        Workers receive no store or coordinator, and policies receive only the
        usual visibility-filtered observation produced inside that worker.
        """
        context = self.context
        context._nearby((0.,0.),0.)  # Build the exact-time broad-phase once.
        ordering={aid:index for index,aid in enumerate(context.world_view["agents"])}
        size=max(1,math.ceil(len(controllers)/(context.workers*4)))
        tasks=[]
        for start in range(0,len(controllers),size):
            chunk=controllers[start:start+size];nearby=set()
            for aid,*_ in chunk:
                radius=float(profile(context.world_view["agents"][aid],stamp(context.time))["sense_r"])
                nearby.update(context._nearby(context._position_at(aid),radius));nearby.add(aid)
            agents={aid:context.world_view["agents"][aid] for aid in sorted(nearby,key=ordering.get)}
            occurrence_ids={a.get("active_action") for a in agents.values()}
            episode_ids={a.get("infection_episode") for a in agents.values()}
            state={name:deepcopy(context.world_view[name]) for name in ("world","barriers","stockpiles","remains","signals")}
            state.update(agents=agents,occurrences={key:context.occurrences[key] for key in occurrence_ids if key in context.occurrences},
                         episodes={key:context.world_view["episodes"][key] for key in episode_ids if key in context.world_view["episodes"]})
            tasks.append({"state":state,"controllers":chunk,"time":context.time,"horizon":context.horizon,"revision":context.revision})
        return tasks

    def next_decision_batch(self):
        context = self.context
        return [context.observe(aid) for aid,a in context.world_view["agents"].items() if a["life"] > 0 and not a.get("active_action")]

    def execution_diagnostics(self):
        """Measured execution metadata, deliberately outside semantic history."""
        context = self.context
        return {"workers":context.workers,"hardware":deepcopy(getattr(context,"_runtime_worker_budget",{})),
                "performance":deepcopy(getattr(context,"_runtime_performance",{})),
                "dependency_retries":getattr(context,"_runtime_dependency_retries",0),
                "effects":deepcopy(getattr(context,"parallel_effect_stats",{}))}

    def _prepare_completions(self,current):
        """Parallelize the independent continuous phase, then commit canonically.

        Conservative action conflicts are still resolved by the coordinator;
        only single-agent anchor calculations have disjoint write sets here.
        """
        context = self.context
        if context._prepared_boundary==context.time:
            return
        aids=set()
        for event in [current,*[entry[4] for entry in context.queue if entry[0]==context.time and entry[1]==5]]:
            occurrence=context.occurrences.get(event.get("occurrence"))
            if occurrence and occurrence["result"]=="IN_PROGRESS":
                aids.add(occurrence["actor"])
        tasks=[]
        for aid in sorted(aids):
            a=context.world_view["agents"][aid]
            tasks.append({"agent":deepcopy(a),"occurrence":deepcopy(context.occurrences.get(a.get("active_action"))),
                          "episode":deepcopy(context.world_view["episodes"].get(a.get("infection_episode"))),"time":stamp(context.time)})
        use_workers=context.workers if len(tasks)>=8 else 1
        if use_workers>1 and context._pool is None:
            context._pool=ProcessPoolExecutor(use_workers,mp_context=multiprocessing.get_context("spawn"),initializer=ignore_worker_sigint)
        context._runtime_prepared_agents = {}
        for result in context.services.parallel.materialize_agents(tasks,workers=use_workers,pool=context._pool if use_workers>1 else None):
            context._runtime_prepared_agents[result["id"]]=result["agent"]
        # Compute bounded deterministic action effects for genuinely disjoint
        # components. Completion validation and all publication remain serial.
        from ..parallel import PREPARABLE_ACTIONS, completion_access, effect_task
        entries=[]
        for event in [current,*[entry[4] for entry in context.queue if entry[0]==context.time and entry[1]==5]]:
            occurrence=context.occurrences.get(event.get("occurrence"))
            if not occurrence or occurrence["result"]!="IN_PROGRESS":
                continue
            task=None
            if occurrence["action"] in PREPARABLE_ACTIONS:
                actor=context._view_agent(occurrence["actor"])
                target_id=occurrence.get("target")
                target=context._view_agent(target_id) if target_id in context.world_view["agents"] else context.world_view["barriers"].get(target_id)
                try:
                    task=effect_task(occurrence,actor,target,profile(actor,stamp(context.time)))
                except (KeyError,TypeError,ValueError):
                    pass  # The ordinary completion validator supplies the outcome.
            entries.append({"access":completion_access(occurrence),"task":task})
        effect_workers=context.workers if len(entries)>1 else 1
        if effect_workers>1 and context._pool is None:
            context._pool=ProcessPoolExecutor(effect_workers,mp_context=multiprocessing.get_context("spawn"),initializer=ignore_worker_sigint)
        context._prepared_effects,statistics=context.services.parallel.prepare_effect_groups(entries,workers=effect_workers,pool=context._pool if effect_workers>1 else None)
        # A declared default exists even before the field was explicitly
        # published. Assign through the runtime owner so the next snapshot
        # retains these cumulative diagnostics when adopting its successor.
        statistics_total = dict(context.parallel_effect_stats)
        for key,value in statistics.items():
            statistics_total[key]=statistics_total.get(key,0)+value
        context.parallel_effect_stats = statistics_total
        context._prepared_boundary=context.time
