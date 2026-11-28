"""Additional semantic sequences guarding the approved domain/state redesign.

These use the original adapter operations and independent literal expectations.
Object ownership and port replacement are tested directly in tests/architecture.
"""
from .dsl import agent, world, submit, advance, snapshot, check, case
from .systems import _workflow, _run, _op, _capture, _same


SOURCE = ["docs/DEEP_OOP_REFACTOR_PROPOSAL.md:2,3,4,5,7", "ontology:6.4,7.3,14,16.1"]


def cases():
    result = []
    converting = world(agent("h", role="DOCTOR", life=64, stamina="32",
        infection={"onset_at": "0", "incubation_duration": "3"},
        inventory={"FOOD": 2, "MEDICAL_SUPPLY": 1, "MATERIAL": 0}))
    result.append(case("OOP_IDENTITY_historical_human_survives_converted_projection", ["V01", "V07", "V08", "V24"],
        converting, [snapshot("before"), submit("rest", "h", "rest", duration="5"),
                     advance("3"), snapshot("converted"), advance("31"), snapshot()],
        [check("/snapshots/before/agents/h/type", "Human"), check("/snapshots/before/agents/h/role", "DOCTOR"),
         check("/snapshots/before/agents/h/inventory/FOOD", 2), check("/snapshots/before/agents/h/life", 64),
         check("/snapshots/converted/agents/h/type", "Zombie"), check("/snapshots/converted/agents/h/role", None),
         check("/snapshots/end/agents/*", 1, "count"), check("/snapshots/end/agents/h/id", "h"),
         check("/snapshots/end/agents/h/life", 64), check("/snapshots/end/agents/h/stamina", "44", "numeric_eq"),
         check("/occurrences/rest/result", "CANCELLED_BY_CONVERSION"),
         check("/snapshots/end/stockpiles/*", 1, "count"),
         check("/snapshots/end/stockpiles/*/stock/FOOD", 2, "sum_eq"),
         check("/snapshots/end/stockpiles/*/stock/MEDICAL_SUPPLY", 1, "sum_eq"),
         check("/snapshots/end/episodes/*/outcome", "CONVERTED", "all_eq", min_count=1)],
        actions=["rest"], source=SOURCE))
    result.append(case("OOP_ROLES_spitter_reservoirs_and_recharge_are_per_agent", ["V08", "V12", "V13", "V22"],
        world(agent("s1", "Zombie", role="SPITTER"), agent("s2", "Zombie", role="SPITTER", y="11"),
              agent("target", x="18")),
        [submit("spit", "s1", "spit", "target"), advance("1"), snapshot("spent"),
         advance("30.999999999"), snapshot("before_recharge"), advance("31"), snapshot()],
        [check("/occurrences/spit/result", "MISSED"),
         check("/snapshots/spent/agents/s1/spit_charges", 2), check("/snapshots/spent/agents/s1/next_charge_at", "31", "numeric_eq"),
         check("/snapshots/spent/agents/s2/spit_charges", 3), check("/snapshots/spent/agents/s2/next_charge_at", None),
         check("/snapshots/before_recharge/agents/s1/spit_charges", 2),
         check("/snapshots/end/agents/s1/spit_charges", 3), check("/snapshots/end/agents/s1/next_charge_at", None),
         check("/snapshots/end/agents/s2/spit_charges", 3), check("/snapshots/end/agents/target/life", 100)],
        actions=["spit"], source=SOURCE, draws=[{"intent": "spit", "channel": "hit", "value": "0.999999"}]))
    result.append(case("OOP_STATE_TYPES_dead_infected_human_never_becomes_zombie", ["V01", "V04", "V07", "V18", "V22"],
        world(agent("h", life=1, hunger="100", infection={"onset_at": "0", "incubation_duration": "10"})),
        [snapshot("initial"), advance("10"), snapshot("dead"), advance("300"), snapshot()],
        [check("/snapshots/initial/agents/h/type", "Human"), check("/snapshots/initial/agents/h/life", 1),
         check("/snapshots/dead/agents/h/status", "DEAD"), check("/snapshots/end/agents/h/status", "DEAD"),
         check("/snapshots/end/agents/h/type", "Human"), check("/snapshots/end/agents/h/life", 0),
         check("/snapshots/end/agents/*", 1, "count"), check("/snapshots/end/remains/*", 1, "count"),
         check("/snapshots/end/agents/h/infection_episode", None),
         check("/snapshots/end/episodes/*/outcome", "HOST_DIED", "all_eq", min_count=1)], source=SOURCE))
    for backend in ("memory", "sqlite"):
        result.append(_workflow(f"OOP_CONTINUATION_conversion_cleanup_{backend}", ["V01", "V07", "V12", "V13", "V24"],
            {"reference": _run(converting, backend=backend), "resumed": _run(converting, backend=backend)},
            [_op("run.create", run="reference"), _op("run.create", run="resumed"),
             _op("run.script", run="reference", steps=[submit("rest", "h", "rest", duration="5"), advance("31")]),
             _op("run.script", run="resumed", steps=[submit("rest", "h", "rest", duration="5"), advance("1/3")]),
             _op("run.checkpoint", run="resumed", name="pending", label="checkpoint"),
             _op("run.restart", run="resumed", checkpoint="pending"),
             _op("run.script", run="resumed", steps=[advance("31")]),
             _capture("reference", "reference"), _capture("resumed", "resumed"),
             _capture("reference", "events_reference", "semantic_history"), _capture("resumed", "events_resumed", "semantic_history")],
            [_same("/captures/reference", "/captures/resumed"), _same("/captures/events_reference", "/captures/events_resumed"),
             check("/captures/resumed/agents/h/type", "Zombie"), check("/captures/resumed/agents/h/life", 64),
             check("/captures/resumed/stockpiles/*", 1, "count"), check("/captures/resumed/episodes/*/outcome", "CONVERTED", "all_eq", min_count=1),
             check("/captures/resumed/reservations/*", 0, "count")], source=SOURCE, actions=["rest"]))
    return result
