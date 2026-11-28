"""Executor owns detached worker orchestration and proposal validation."""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import multiprocessing
import random
from ..parallel import conflict_components, materialize_agent, compute_effect, effect_task


class ParallelExecutor:
    def __init__(self, context=None):
        self.context = context

    def ordered_results(self,pool, function, tasks, *, completion_order="native", seed=0):
        """Consume real worker results in any delivery order; publish input order.

        Reversed/shuffled delivery exercises the coordinator's ordering guarantee
        without altering any model RNG stream or delaying work with artificial CPU.
        """
        futures=[pool.submit(function,task) for task in tasks]
        indices={future:index for index,future in enumerate(futures)}
        if completion_order=="native":
            delivery=as_completed(futures)
        elif completion_order=="reverse":
            delivery=reversed(futures)
        elif completion_order in {"seeded_shuffle","shuffle"}:
            delivery=list(futures);random.Random(seed).shuffle(delivery)
        else:
            raise ValueError("Unknown worker completion order")
        results=[None]*len(futures)
        for future in delivery:
            results[indices[future]]=future.result()
        return results


    def materialize_agents(self,tasks,workers=1,pool=None):
        """Evaluate frozen independent actors in order, optionally using real processes.

        A caller-supplied executor is reused and remains owned by that caller. Passing
        no executor creates a bounded spawn pool for this batch. Results have no target
        effects and must be validated/published by the coordinator in canonical order.
        """
        if isinstance(workers,bool) or not isinstance(workers,int) or workers<1:
            raise ValueError("workers must be a positive integer")
        tasks=list(tasks)
        if workers==1 or not tasks:
            return [materialize_agent(task) for task in tasks]
        if pool is not None:
            return list(pool.map(materialize_agent,tasks))
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("spawn")) as executor:
            return list(executor.map(materialize_agent,tasks))


    def prepare_effect_groups(self,entries,workers=1,pool=None):
        """Compute singleton independent effects; coupled/unsupported work stays serial.

        Entries contain `access` and optionally a supported `task`. Worker failure
        yields serial fallback rather than partially published effects.
        """
        groups=conflict_components([entry["access"] for entry in entries])
        eligible=[group[0] for group in groups if len(group)==1 and entries[group[0]].get("task") is not None]
        tasks=[entries[i]["task"] for i in eligible]
        stats={"submitted":len(tasks),"prepared":0,"consumed":0,"fallback":0,
               "unsupported":sum(entry.get("task") is None for entry in entries),
               "conflicted":sum(len(group) for group in groups if len(group)>1),
               "worker_batches":int(workers>1 and len(tasks)>1)}
        try:
            if workers>1 and len(tasks)>1:
                if pool is not None:prepared=list(pool.map(compute_effect,tasks))
                else:
                    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("spawn")) as executor:
                        prepared=list(executor.map(compute_effect,tasks))
            else:prepared=[compute_effect(task) for task in tasks]
        except Exception:
            # No worker proposal has been published. Existing handlers remain the
            # authoritative fallback; do not retry a partially committed action.
            stats["fallback"]+=len(tasks);prepared=[]
        stats["prepared"]=len(prepared)
        return {item["occurrence"]:item for item in prepared},stats


    def consume_prepared_effect(self,simulation,occurrence,actor,actor_profile):
        """Verify the reads immediately after completion validation, before mutation."""
        proposals=getattr(simulation,"_prepared_effects",{})
        proposal=proposals.pop(occurrence["id"],None)
        if proposal is None:return None
        target_id=occurrence.get("target")
        if target_id in simulation.state["agents"]:target=simulation._view_agent(target_id)
        else:target=simulation.state["barriers"].get(target_id)
        current=effect_task(occurrence,actor,target,actor_profile)
        stats=getattr(simulation,"parallel_effect_stats",None)
        if stats is None:
            stats=simulation.parallel_effect_stats={"consumed":0,"fallback":0}
        if current is None or current["fingerprint"]!=proposal["fingerprint"]:
            stats["fallback"]=stats.get("fallback",0)+1
            return None
        stats["consumed"]=stats.get("consumed",0)+1
        return deepcopy(proposal["effect"])

