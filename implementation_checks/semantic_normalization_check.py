"""Check exact old/new acceptance-normalization equivalence and actual captures."""
from copy import deepcopy
import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest

from zombie_sim.engine import Simulation
from zombie_sim.testing import normalize_snapshot, normalize_trace
from zombie_sim.testing_workflows import _semantic


def previous_semantic(sim, value):
    """Literal prior traversal, retained solely as an independent comparison."""
    ignored={"clock_advanced","scheduler_advanced"}
    events=[event for event in sim.events if event.get("kind") not in ignored]
    event_ids={event["id"]:f"semantic-event-{index+1}" for index,event in enumerate(events)}
    revisions={0:0};index=0
    for event in sim.events:
        revision=int(event.get("revision",0))
        if revision not in revisions:
            if event.get("kind") not in ignored:index+=1
            revisions[revision]=index
    def walk(item,key=None):
        if isinstance(item,dict):
            return {k:walk(v,k) for k,v in item.items() if k not in {"ledger_sequence","normalization"}}
        if isinstance(item,list):return [walk(v,key) for v in item]
        if key in {"revision","onset_revision","end_revision","ledger_revision"} and item is not None:
            return str(revisions.get(int(item),sum(1 for r in revisions if r and r<=int(item))))
        if key=="run_id":return "RUN"
        if isinstance(item,str):return event_ids.get(item,item)
        return item
    return walk(value)


class SemanticNormalizationChecks(unittest.TestCase):
    def compare(self, events, value):
        sim=SimpleNamespace(events=events)
        untouched=deepcopy(value)
        expected=previous_semantic(sim,value)
        self.assertEqual(_semantic(sim,value),expected)
        self.assertEqual(value,untouched)
        return expected

    def test_nested_present_missing_zero_negative_and_order(self):
        events=[{"id":f"event-{i}","revision":revision,"kind":kind}
                for i,(revision,kind) in enumerate([(10,"clock_advanced"),(2,"action_admitted"),
                    (10,"action_completed"),(-3,"action_admitted"),(7,"scheduler_advanced"),
                    (4,"action_completed"),(1,"action_admitted"),(4,"action_completed")])]
        queries=[0,"0",-20,-3,-2,-1,1,"2",3,4,5,6,7,8,10,11,True,False,2.7,None]
        value={"revision":queries,"nested":[{"onset_revision":queries,"end_revision":queries,
            "ledger_revision":queries,"run_id":"arbitrary","ordinary":"event-1"},
            {"keep":["event-2",{"reference":"event-7"}],"ledger_sequence":102,"normalization":{}}],
            "ordinary_negative":-4,"empty":[],"tuple_unchanged":("event-1",)}
        expected=self.compare(events,value)
        self.assertEqual(expected["revision"][:7],["0","0","0","2","1","1","4"])
        self.assertEqual(expected["nested"][0]["ordinary"],"semantic-event-1")
        self.assertEqual(expected["tuple_unchanged"],("event-1",))
        self.compare([],value)

    def test_seeded_arbitrary_order_and_repeated_revisions(self):
        rng=random.Random(2381)
        for example in range(100):
            events=[{"id":f"event-{i}","revision":rng.randrange(-5,31),
                     "kind":rng.choice(["clock_advanced","scheduler_advanced","action_admitted","action_completed"])}
                    for i in range(rng.randrange(40))]
            values=[{"revision":rng.randrange(-10,45),"onset_revision":str(rng.randrange(-10,45)),
                     "nested":[{"end_revision":rng.randrange(-10,45),"ledger_revision":None,
                                "causal_predecessors":[f"event-{rng.randrange(40)}"]}]} for _ in range(30)]
            with self.subTest(example=example): self.compare(events,values)

    def test_real_snapshot_and_complete_history(self):
        with TemporaryDirectory(prefix="zombie-semantic-check-") as directory:
            sim=Simulation({"agents":[{"id":"a","type":"Human","x":10,"y":10}],
                            "decision_mode":"scripted","horizon":5,"execution":{"workers":1}},
                           history_path=Path(directory)/"run.sqlite")
            try:
                sim.submit_intents({"actor":"a","action":"move","parameters":{"duration":2,
                    "path":[{"x":10,"y":10,"offset":0},{"x":14,"y":10,"offset":2}]}})
                for target in ("1/4","3/4",2):sim.advance_until(target,return_snapshot=False)
                for value in (normalize_snapshot(sim),normalize_trace(sim)):
                    self.compare(list(sim.events),value)
            finally:sim.close()

    def test_lookup_scaling_without_output_changes(self):
        events=[{"id":f"event-{i}","revision":2*i,"kind":"action_completed"} for i in range(3000)]
        value=[{"revision":i,"nested":{"end_revision":str(i)}} for i in range(6000)]
        sim=SimpleNamespace(events=events)
        started=time.perf_counter();old=previous_semantic(sim,value);old_seconds=time.perf_counter()-started
        started=time.perf_counter();new=_semantic(sim,value);new_seconds=time.perf_counter()-started
        self.assertEqual(old,new)
        print(json.dumps({"semantic_lookup_benchmark":{"events":len(events),"revision_fields":12000,
            "old_seconds":old_seconds,"new_seconds":new_seconds,"outputs_equal":True}}),flush=True)


if __name__=="__main__":unittest.main(verbosity=2)
