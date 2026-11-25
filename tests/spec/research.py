"""Fixed-seed sequences, replicated stochastic checks, and full baseline run."""
from random import Random
from .dsl import agent, world, intent, submit, advance, snapshot, check, case


def cases():
    out = []
    for seed in range(8):
        rng = Random(seed)
        steps = [snapshot("initial")]
        now, x, holder = 0, 10, "a"
        actions = set()
        for i in range(20):
            action = rng.choice(["move", "wait", "rest", "transfer"])
            actions.add(action)
            id = f"step_{i}"
            if action == "move":
                # Oscillate a inside transfer reach of b, with a real segment.
                end = 10 if x == 11 else 11
                step = submit(id, "a", action, duration="1", path=[
                    {"x": str(x), "y": "10", "offset": "0"},
                    {"x": str(end), "y": "10", "offset": "1"}])
                x = end
            elif action == "transfer":
                other = "b" if holder == "a" else "a"
                step = submit(id, holder, action, other, resource_type="FOOD", quantity=1)
                holder = other
            else:
                step = submit(id, "a", action, duration="1")
            steps.extend([step, snapshot(f"admitted_{i}"), advance(str(now+1)), snapshot(f"after_{i}")])
            now += 1
        steps.append(snapshot())
        out.append(case(f"SEQ_resources_and_continuity_{seed}", ["V02", "V09", "V10", "V11", "V12", "V13", "V14", "V22", "V24"],
            world(agent("a", stamina="40", inventory={"FOOD": 1, "MEDICAL_SUPPLY": 0, "MATERIAL": 0}),
                  agent("b", x="10.5", stamina="40")), steps,
            [check("/occurrences/*", 20, "count"), check("/occurrences/*/result", "SUCCEEDED", "all_eq", min_count=20),
             check("/snapshots/end/agents/*/inventory/FOOD", 1, "sum_eq"),
             check(f"/snapshots/end/agents/{holder}/inventory/FOOD", 1),
             check("/snapshots/end/agents/a/x", str(x), "numeric_eq"),
             check("/snapshots/end/agents/a/hunger", "21", "numeric_eq"),
             check("/snapshots/end/agents/b/hunger", "21", "numeric_eq"),
             check("/snapshots/end/reservations/*", 0, "count")],
            actions=sorted(actions), source=["ontology §§9–11,14", "plan:14.1"],
            description="Seeded mixed sequence: check each admission/completion snapshot and final conservation."))
    for kind, probability in (("hit", "0.72"), ("claim", "0.5")):
        seeds = list(range(1024))
        if kind == "hit":
            setup = world(agent("z", "Zombie"), agent("h", x="11"))
            steps = [submit("attack", "z", "claw", "h"), advance("1"), snapshot()]
            actions = ["claw"]
        else:
            setup = world(agent("a"), agent("b", x="12"),
                          stockpiles=[{"id": "s", "x": "11", "y": "10", "stock": {"FOOD": 1}}])
            steps = [{"op": "submit_batch", "intents": [intent("a_claim", "a", "pickup", "s", resource_type="FOOD", quantity=1),
                                                               intent("b_claim", "b", "pickup", "s", resource_type="FOOD", quantity=1)]},
                     advance("1"), snapshot()]
            actions = ["pickup"]
        c = case(f"STAT_{kind}_fixed_seed_trials", ["V12", "V13", "V16"], {},
                 [{"op": "trials.execute", "seeds": seeds, "world": setup, "steps": steps, "label": "trials"}],
                 [check("/captures/trials/*", len(seeds), "count")],
                 source=["ontology §§9.4,14.3", "plan:14.1"], actions=actions,
                 kind="workflow", tier="statistical", description="Predeclared five-sigma diagnostic on independent raw trials.")
        c["trial_checks"] = [{"path": "/captures/trials", "kind": kind, "probability": probability, "seeds": seeds}]
        out.append(c)
    c = case("BASELINE_full_default_model_run", ["V01", "V02", "V03", "V05", "V08", "V12", "V20", "V21", "V23", "V24"],
             {"runs": {"baseline": {"world": {"preset": "baseline_v0.1"},
                                    "config": {"seed": 20261106, "decision_mode": "model", "horizon": "1800"}}}},
             [{"op": "run.create", "run": "baseline"},
              {"op": "run.capture", "run": "baseline", "what": "initial_snapshot", "label": "initial"},
              {"op": "run.script", "run": "baseline", "steps": [advance("1800")]},
              {"op": "run.capture", "run": "baseline", "what": "semantic_snapshot", "label": "end"},
              {"op": "run.capture", "run": "baseline", "what": "status", "label": "status"}],
             [check("/captures/end/agents/*", 1000, "count"),
              check("/captures/end/time", ["0", "1800"], "between"),
              check("/captures/status/state", "COMPLETED")], kind="workflow", tier="integration",
             source=["ontology:15", "plan:15"], decisions=["D5", "D7"],
             description="Full 1,000-agent / 1,800-second baseline with real default policies.")
    c["baseline_paths"] = ["/captures/initial"]
    c["snapshot_paths"] = ["/captures/end"]
    c["baseline_end"] = {"snapshot": "/captures/end", "status": "/captures/status"}
    out.append(c)
    return out
