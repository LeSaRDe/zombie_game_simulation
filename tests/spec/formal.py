"""Three actual simulator traces exported through the existing RDF vocabulary."""
from .dsl import agent, world, submit, advance, check, case


def expectations(kind):
    """Literal oracle facts, also used to unit-test the independent RDF reader."""
    common = {"atTime": "300" if kind == "conversion" else "10", "x": "10", "y": "10"}
    if kind == "treatment":
        state = {"atTime": "104", "x": "11", "y": "10", "life": 60, "stamina": "100", "hunger": "25.2", "biologicalType": "Human"}
        return {"path": "/captures/trace", "kind": kind, "subject": "patient", "actor": "doctor",
                "before": {**state, "status": "INFECTED"}, "after": {**state, "status": "HEALTHY"},
                "episode": {"onset_at": "0", "conversion_due_at": "300", "ended_at": "104", "episodeOutcome": "CURED"},
                "action": {"startTime": "100", "plannedEnd": "104", "resolvedAt": "104", "actionResult": "SUCCEEDED"},
                "actor_start": {"life": 100, "stamina": "80", "hunger": "25", "atTime": "100"},
                "actor_after": {"life": 100, "stamina": "74", "hunger": "25.2", "atTime": "104"},
                "medical_before": 2, "medical_after": 1}
    if kind == "conversion":
        common.update(life=64, stamina="32")
        return {"path": "/captures/trace", "kind": kind, "subject": "h",
                "before": {**common, "hunger": "35", "biologicalType": "Human", "status": "INFECTED"},
                "after": {**common, "biologicalType": "Zombie", "status": "ACTIVE"},
                "episode": {"onset_at": "0", "conversion_due_at": "300", "ended_at": "300", "episodeOutcome": "CONVERTED"}}
    return {"path": "/captures/trace", "kind": kind, "subject": "h",
            "before": {**common, "life": 5, "stamina": "100", "hunger": "20.5", "biologicalType": "Human", "status": "HEALTHY"},
            "after": {**common, "life": 0, "stamina": "100", "hunger": "20.5", "biologicalType": "Human", "status": "DEAD"}}


def cases():
    out = []
    for kind in ["treatment", "conversion", "death"]:
        if kind == "treatment":
            setup = world(agent("doctor", role="DOCTOR", stamina="80",
                                inventory={"FOOD": 0, "MEDICAL_SUPPLY": 2, "MATERIAL": 0}),
                          agent("patient", x="11", life=60, infection={"onset_at": "0", "incubation_duration": "300"}))
            script = [advance("100"), submit("treatment", "doctor", "treat_infection", "patient"), advance("104")]
            actions, subject, draws = ["treat_infection"], "patient", []
        elif kind == "conversion":
            setup = world(agent("h", role="DOCTOR", life=64, stamina="32",
                                infection={"onset_at": "0", "incubation_duration": "300"}))
            script, actions, subject, draws = [advance("300")], [], "h", []
        else:
            setup = world(agent("h", life=5), agent("z", "Zombie", x="11"))
            script = [advance("9"), submit("attack", "z", "claw", "h"), advance("10")]
            actions, subject = ["claw"], "h"
            draws = [{"intent": "attack", "channel": "hit", "value": "0"}]
        steps = [{"op": "run.create", "run": "run"}, {"op": "run.script", "run": "run", "steps": script, "draws": draws},
                 {"op": "run.capture", "run": "run", "what": "semantic_snapshot", "label": "end"},
                 {"op": "trace.export_turtle", "run": "run", "kind": kind, "subject": subject, "label": "trace"}]
        c = case("FORMAL_actual_" + kind + "_trace", ["V01", "V03", "V04", "V06", "V07", "V24"],
                 {"runs": {"run": {"world": setup, "config": {"seed": 20261106, "decision_mode": "scripted"}}}},
                 steps, [check("/captures/end/agents/" + subject + "/life", 0 if kind == "death" else 64 if kind == "conversion" else 60)],
                 kind="workflow", tier="integration", actions=actions,
                 source=["ontology/formal_v0.1/shapes.ttl", "ontology/formal_v0.1/examples/valid_" +
                         ("conversion_preserves_identity" if kind == "conversion" else kind) + ".ttl", "plan:2.2,14.1"],
                 description="Export the executed trace; independently validate SHACL and literal RDF transition facts.")
        c["snapshot_paths"] = ["/captures/end"]
        c["formal_checks"] = [expectations(kind)]
        out.append(c)
    return out
