"""System, research, learning and browser contracts for the future framework.

The workflow operations are adapter instructions, specified in SYSTEM_OPERATIONS.md.
They must exercise actual services or browser interactions and return captured facts.
Nothing here supplies a simulated implementation or accepts an adapter's pass flag.
"""
from copy import deepcopy

from .dsl import agent, world, intent, submit, advance, snapshot, check, case


def _run(w, **config):
    return {"world": deepcopy(w), "config": {"seed": 20261106, "decision_mode": "scripted",
                                            "horizon": "1800", **config}}


def _op(op, **fields):
    return {"op": op, **fields}


def _capture(run, label, what="semantic_snapshot", **fields):
    return _op("run.capture", run=run, label=label, what=what, **fields)


def _same(path, other):
    return check(path, op="same", other_path=other)


def _workflow(id, requirements, runs, steps, checks, *, source, actions=(), tier="core",
              decisions=(), extra=None, kind="workflow", description=""):
    setup = {"runs": deepcopy(runs), **(extra or {})}
    result = case(id, requirements, setup, steps, checks, source=source, actions=actions,
                  tier=tier, decisions=decisions, kind=kind, description=description)
    result["snapshot_paths"] = ["/captures/" + step["label"] for step in steps
                                if step["op"] == "run.replay" or
                                (step["op"] == "run.capture" and step["what"] in
                                 {"semantic_snapshot", "initial_snapshot", "durable_snapshot"})]
    if id == "GUI_CONFIG_CLI_PARITY":
        result["baseline_paths"] = ["/captures/gui_initial", "/captures/cli_initial"]
    return result


def _movement_world():
    return world(agent("h", stamina="80"), agent("z", "Zombie", x="60", y="60"))


def _moving_script():
    return [submit("walk", "h", "move", duration="4",
                   path=[{"x": "10", "y": "10", "offset": "0"},
                         {"x": "18", "y": "10", "offset": "4"}])]


def _treatment_world():
    return world(agent("doctor", role="DOCTOR", inventory={"FOOD": 0, "MEDICAL_SUPPLY": 2, "MATERIAL": 0}),
                 agent("patient", x="11", life=61, infection={"onset_at": "0", "incubation_duration": "300"}))


def _contention_world():
    return world(agent("a"), agent("b", x="12"),
                 stockpiles=[{"id": "stock", "x": "11", "y": "10", "stock": {"MEDICAL_SUPPLY": 1}}])


def _contention_script():
    return [{"op": "submit_batch", "intents": [intent("take_a", "a", "pickup", "stock", resource_type="MEDICAL_SUPPLY", quantity=1),
                                                 intent("take_b", "b", "pickup", "stock", resource_type="MEDICAL_SUPPLY", quantity=1)]},
            advance("1")]


def _storage_cases():
    out = []
    for backend in ("memory", "sqlite"):
        w = _movement_world()
        out.append(_workflow(f"SYS_RESTART_{backend.upper()}", ["V14", "V22", "V24"],
            {"reference": _run(w, backend=backend), "resumed": _run(w, backend=backend)},
            [_op("run.create", run="reference"), _op("run.create", run="resumed"),
             _op("run.script", run="reference", steps=_moving_script() + [advance("4")]),
             _op("run.script", run="resumed", steps=_moving_script() + [advance("2")]),
             _op("run.checkpoint", run="resumed", name="middle", label="checkpoint"),
             _op("run.restart", run="resumed", checkpoint="middle"),
             _op("run.script", run="resumed", steps=[advance("4")]),
             _capture("reference", "reference"), _capture("resumed", "resumed"),
             _capture("reference", "events_a", "semantic_history"), _capture("resumed", "events_b", "semantic_history")],
            [_same("/captures/reference", "/captures/resumed"), _same("/captures/events_a", "/captures/events_b"),
             check("/captures/resumed/agents/h/x", "18", "numeric_eq"),
             check("/captures/resumed/agents/h/stamina", "79.2", "numeric_eq"),
             check("/captures/resumed/agents/h/hunger", "20.2", "numeric_eq")],
            source=["ontology:16.1", "plan:10.3"], actions=["move"], decisions=["D4", "D6"]))
        out.append(_workflow(f"SYS_REPLAY_NO_EXECUTION_{backend.upper()}", ["V14", "V16", "V24"],
            {"live": _run(w, backend=backend)},
            [_op("run.create", run="live"), _op("run.script", run="live", steps=_moving_script() + [advance("4")]),
             _capture("live", "before", "execution_counters"),
             _op("run.replay", run="live", time="1.25", label="replayed"),
             _capture("live", "after", "execution_counters"), _capture("live", "current")],
            [_same("/captures/before", "/captures/after"),
             check("/captures/replayed/time", "1.25", "numeric_eq"),
             check("/captures/replayed/agents/h/x", "12.5", "numeric_eq"),
             check("/captures/replayed/agents/h/stamina", "79.75", "numeric_eq"),
             check("/captures/current/agents/h/x", "18", "numeric_eq")],
            source=["ontology:16.1", "plan:10.3"], actions=["move"], decisions=["D4"]))
        for fault in ("before_history_commit", "after_history_commit_before_publish", "after_checkpoint_rename_before_register"):
            out.append(_workflow(f"SYS_RECOVERY_{backend.upper()}_{fault.upper()}", ["V12", "V13", "V24"],
                {"reference": _run(_contention_world(), backend=backend), "crashed": _run(_contention_world(), backend=backend)},
                [_op("run.create", run="reference"), _op("run.create", run="crashed"),
                 _op("run.script", run="reference", steps=_contention_script()),
                 _op("fault.arm", run="crashed", point=fault, occurrence=1),
                 _op("run.script", run="crashed", steps=_contention_script(), on_fault="capture", label="fault"),
                 *([_op("run.checkpoint", run="crashed", name="checkpoint", on_fault="capture", label="cp")]
                   if fault == "after_checkpoint_rename_before_register" else []),
                 _op("run.recover", run="crashed", replay_commands=True),
                 _op("run.script", run="crashed", steps=[advance("1")]),
                 _capture("reference", "reference"), _capture("crashed", "recovered"),
                 _capture("reference", "events_a", "semantic_history"), _capture("crashed", "events_b", "semantic_history"),
                 _capture("crashed", "faults", "fault_trace")],
                [_same("/captures/reference", "/captures/recovered"), _same("/captures/events_a", "/captures/events_b"),
                 check("/captures/recovered/agents/*/inventory/MEDICAL_SUPPLY", 1, "sum_eq"),
                 check("/captures/recovered/stockpiles/stock/stock/MEDICAL_SUPPLY", 0),
                 check("/captures/recovered/reservations/*", 0, "count"),
                 check("/captures/faults/*/point", fault, "contains")],
                source=["ontology:9.2", "ontology:16.1", "plan:10.3"], actions=["pickup"], decisions=["D4"]))
    out.append(_workflow("SYS_BACKEND_EQUIVALENCE", ["V12", "V16", "V24"],
        {"memory": _run(_contention_world(), backend="memory"), "sqlite": _run(_contention_world(), backend="sqlite")},
        [_op("run.create", run="memory"), _op("run.create", run="sqlite"),
         _op("run.script", run="memory", steps=_contention_script()), _op("run.script", run="sqlite", steps=_contention_script()),
         _capture("memory", "a"), _capture("sqlite", "b"),
         _capture("memory", "events_a", "semantic_history"), _capture("sqlite", "events_b", "semantic_history")],
        [_same("/captures/a", "/captures/b"), _same("/captures/events_a", "/captures/events_b"),
         check("/captures/a/agents/*/inventory/MEDICAL_SUPPLY", 1, "sum_eq")],
        source=["plan:10.1", "plan:14.1"], actions=["pickup"], decisions=["D4"]))
    out.append(_workflow("SYS_PENDING_HORIZON_CHECKPOINT", ["V10", "V13", "V24"],
        {"run": _run(_treatment_world(), horizon="2")},
        [_op("run.create", run="run"), _op("run.script", run="run", steps=[submit("cure", "doctor", "treat_infection", "patient"), advance("2")]),
         _capture("run", "state"), _capture("run", "occurrences", "occurrences"),
         _capture("run", "status", "status"), _op("run.checkpoint", run="run", name="final", label="checkpoint")],
        [check("/captures/occurrences/cure/result", "IN_PROGRESS"), check("/captures/occurrences/cure/resolved_at", op="absent"),
         check("/captures/state/agents/doctor/reserved/MEDICAL_SUPPLY", 1),
         check("/captures/state/agents/patient/status", "INFECTED"),
         check("/captures/status/termination_reason", "HORIZON"),
         check("/captures/checkpoint/state/agents/doctor/active_action", "cure")],
        source=["ontology:9.1", "ontology:16.1", "plan:4.2"], actions=["treat_infection"]))
    out.append(_workflow("SYS_STORAGE_FAILURE_STOPS_DURABLY", ["V12", "V24"],
        {"run": _run(_contention_world())},
        [_op("run.create", run="run"), _capture("run", "before"),
         _op("fault.arm", run="run", point="history_write", error="ENOSPC", persistent=True),
         _op("run.script", run="run", steps=_contention_script(), on_fault="capture", label="error"),
         _capture("run", "durable", "durable_snapshot"), _capture("run", "status", "status")],
        [check("/captures/status/state", "FAILED"), check("/captures/status/termination_reason", "STORAGE_ERROR"),
         _same("/captures/before", "/captures/durable"), check("/captures/error/code", "ENOSPC")],
        source=["plan:10.3"], actions=["pickup"]))
    for corrupt in ("checkpoint_checksum", "model_artifact_checksum", "ontology_fingerprint"):
        out.append(_workflow(f"SYS_RESTART_REJECTS_{corrupt.upper()}", ["V24"], {"run": _run(_movement_world())},
            [_op("run.create", run="run"), _op("run.checkpoint", run="run", name="c", label="checkpoint"),
             _op("artifact.corrupt", run="run", checkpoint="c", component=corrupt),
             _op("run.restart", run="run", checkpoint="c", on_error="capture", label="error")],
            [check("/captures/error/code", "ARTIFACT_MISMATCH"), check("/captures/error/component", corrupt)],
            source=["ontology:16.1", "plan:10.3"]))
    return out


def _parallel_cases():
    out = []
    for workers in (2, 4):
        for order in ("reverse", "seeded_shuffle"):
            out.append(_workflow(f"SYS_PARALLEL_{workers}_{order.upper()}", ["V12", "V13", "V16", "V24"],
                {"serial": _run(_contention_world(), workers=1), "parallel": _run(_contention_world(), workers=workers)},
                [_op("run.create", run="serial"), _op("run.create", run="parallel"),
                 _op("workers.completion_order", run="parallel", order=order, seed=41),
                 _op("run.script", run="serial", steps=_contention_script()),
                 _op("run.script", run="parallel", steps=_contention_script()),
                 _capture("serial", "serial"), _capture("parallel", "parallel"),
                 _capture("serial", "history_a", "semantic_history"), _capture("parallel", "history_b", "semantic_history"),
                 _capture("serial", "draws_a", "random_draws"), _capture("parallel", "draws_b", "random_draws")],
                [_same("/captures/serial", "/captures/parallel"), _same("/captures/history_a", "/captures/history_b"),
                 _same("/captures/draws_a", "/captures/draws_b"),
                 check("/captures/parallel/agents/*/inventory/MEDICAL_SUPPLY", 1, "sum_eq")],
                source=["ontology:14.3", "plan:5.1", "plan:14.1"], actions=["pickup"], decisions=["D3"]))
    out.append(_workflow("SYS_DEPENDENCY_RETRY_NO_PARTIAL_EFFECT", ["V12", "V13", "V24"],
        {"reference": _run(_contention_world(), workers=1), "retry": _run(_contention_world(), workers=4)},
        [_op("run.create", run="reference"), _op("run.create", run="retry"),
         _op("fault.arm", run="retry", point="dependency_validation", omit_read_key="stock:stock:MEDICAL_SUPPLY", occurrence=1),
         _op("run.script", run="reference", steps=_contention_script()),
         _op("run.script", run="retry", steps=_contention_script()),
         _capture("reference", "reference"), _capture("retry", "retry"), _capture("retry", "diagnostics", "scheduler_diagnostics")],
        [_same("/captures/reference", "/captures/retry"), check("/captures/retry/agents/*/inventory/MEDICAL_SUPPLY", 1, "sum_eq"),
         check("/captures/diagnostics/dependency_retries", [1, 100], "between"),
         check("/captures/retry/reservations/*", 0, "count")],
        source=["plan:5.1"], actions=["pickup"], decisions=["D3"]))
    return out


def _configuration_cases():
    out = []
    for field, value in (("workers", 4), ("checkpoint_interval", "10"), ("backend", "sqlite")):
        out.append(_workflow(f"SYS_CONFIG_EXECUTION_{field.upper()}", ["V23", "V24"], {},
            [_op("config.resolve", draft={"preset": "baseline_v0.1", "execution": {field: value}}, label="changed"),
             _op("config.resolve", draft={"preset": "baseline_v0.1"}, label="base")],
            [_same("/captures/base/semantic_fingerprint", "/captures/changed/semantic_fingerprint"),
             _same("/captures/base/semantic", "/captures/changed/semantic")],
            source=["plan:11.1"], decisions=["D1"]))
    out.append(_workflow("SYS_CONFIG_SEMANTIC_CHANGE_NEW_FINGERPRINT", ["V23", "V24"], {},
        [_op("config.resolve", draft={"preset": "baseline_v0.1"}, label="base"),
         _op("config.resolve", draft={"preset": "baseline_v0.1", "semantic": {"incubation_duration": "301"}}, label="changed")],
        [check("/captures/base/semantic_fingerprint", op="different", other_path="/captures/changed/semantic_fingerprint"),
         check("/captures/base/semantic/incubation_duration", "300", "numeric_eq"),
         check("/captures/changed/semantic/incubation_duration", "301", "numeric_eq")], source=["ontology:15.6", "plan:11.1"]))
    out.append(_workflow("SYS_CONFIG_TOML_ROUNDTRIP", ["V23", "V24"], {},
        [_op("config.resolve", draft={"preset": "baseline_v0.1", "semantic": {"incubation_duration": "300.125"}}, label="original"),
         _op("config.export_import", source="original", format="toml", label="roundtrip")],
        [_same("/captures/original/semantic", "/captures/roundtrip/semantic"),
         _same("/captures/original/semantic_fingerprint", "/captures/roundtrip/semantic_fingerprint")],
        source=["plan:11.1"]))
    out.append(_workflow("SYS_BRANCH_PARENT_IMMUTABLE", ["V01", "V12", "V24"], {"parent": _run(_movement_world(), interventions_enabled=True)},
        [_op("run.create", run="parent"), _op("run.script", run="parent", steps=_moving_script() + [advance("2")]),
         _capture("parent", "before"), _capture("parent", "history_before", "semantic_history"),
         _op("run.branch", run="parent", child="child", time="2", after_all_events=True,
             random_alignment="independent", label="branch"),
         _op("run.intervene", run="child", id="addition", at="2", change={"kind": "add_resource", "stockpile": "gift", "x": "20", "y": "20", "resource": "FOOD", "quantity": 3}),
         _op("run.script", run="child", steps=[advance("4")]),
         _capture("parent", "after"), _capture("parent", "history_after", "semantic_history"), _capture("child", "child")],
        [_same("/captures/before", "/captures/after"), _same("/captures/history_before", "/captures/history_after"),
         check("/captures/child/stockpiles/gift/stock/FOOD", 3), check("/captures/child/agents/h/x", "18", "numeric_eq"),
         check("/captures/after/agents/h/x", "14", "numeric_eq"), check("/captures/branch/parent_alias", "parent"),
         check("/captures/branch/child_alias", "child")], source=["ontology:16.3", "plan:11.3"], actions=["move"]))
    out.append(_workflow("SYS_MEASUREMENTS_POPULATION_ACCOUNTING", ["V03", "V21", "V24"],
        {"run": _run(world(agent("infected", infection={"onset_at": "0", "incubation_duration": "2"}),
                           agent("healthy", x="20"), agent("zombie", "Zombie", x="50")))},
        [_op("run.create", run="run"), _op("run.script", run="run", steps=[advance("2")]),
         _op("measurement.query", run="run", measurement="populations", time="2", label="population"),
         _op("measurement.query", run="run", measurement="infection_episodes", interval=["0", "2"], label="episodes")],
        [check("/captures/population/healthy_humans", 1), check("/captures/population/infected_humans", 0),
         check("/captures/population/active_zombies", 2), check("/captures/population/dead_agents", 0),
         check("/captures/population/total_identities", 3), check("/captures/episodes/initial_episodes", 1),
         check("/captures/episodes/new_incidence", 0), check("/captures/episodes/conversions", 1)],
        source=["ontology:16.2", "plan:12"]))
    return out


def _learning_cases():
    out = []
    for action, life, elapsed, term, credit, total in (
        ("first_aid", 99, "3", "healing_others", "0.01", "0.04"),
        ("treat_infection", 61, "4", "curing_others", "2", "2.04"),
    ):
        fixture = _treatment_world()
        fixture["agents"][1]["life"] = life
        out.append(_workflow("SYS_RL_ACTUAL_REWARD_" + action.upper(), ["V06", "V12", "V17"],
            {"run": _run(fixture)},
            [_op("run.create", run="run"), _op("rl.attach", run="run", controlled="doctor", reward="human_survival_v1", adapter="gymnasium"),
             _op("rl.step", run="run", intent=intent("care", "doctor", action, "patient"), label="transition"), _capture("run", "state")],
            [check("/captures/transition/elapsed", elapsed, "numeric_eq"),
             check("/captures/transition/reward_terms/" + term, credit, "numeric_eq"),
             check("/captures/transition/reward", total, "numeric_eq"),
             check("/captures/state/agents/patient/life", 100 if action == "first_aid" else 61),
             check("/captures/state/agents/patient/status", "INFECTED" if action == "first_aid" else "HEALTHY")],
            source=["plan:9.3", "ontology:13.1"], actions=[action], decisions=["D7"]))
    for infected in (False, True):
        fixture = world(agent("z", "Zombie"), agent("h", x="11", **({"infection": {"onset_at": "0", "incubation_duration": "300"}} if infected else {})))
        draws = [{"intent": "bite", "channel": "hit", "value": "0"}]
        if not infected:
            draws.append({"intent": "bite", "channel": "infection", "value": "0"})
        out.append(_workflow("SYS_RL_ZOMBIE_REWARD_" + ("REEXPOSURE" if infected else "NEW_INFECTION"), ["V05", "V16", "V17", "V18"],
            {"run": _run(fixture)},
            [_op("run.create", run="run"), _op("rl.attach", run="run", controlled="z", reward="zombie_pressure_v1", adapter="gymnasium"),
             _op("rl.step", run="run", intent=intent("bite", "z", "bite", "h"), draws=draws, label="transition"),
             _capture("run", "state"), _capture("run", "draws", "random_draws")],
            [check("/captures/transition/reward_terms/damage_to_humans", "0.12", "numeric_eq"),
             check("/captures/transition/reward_terms/new_infection", "0" if infected else "1", "numeric_eq"),
             check("/captures/transition/reward", "0.12" if infected else "1.12", "numeric_eq"),
             check("/captures/state/agents/h/life", 94), check("/captures/state/episodes/*", 1, "count"),
             check("/captures/draws/*", 0 if infected else 1, "count", where={"channel": "infection"})],
            source=["plan:9.3", "ontology:12"], actions=["bite"], decisions=["D7"]))
    for duration, reward, discount in (("1", "0.01", "0.99"), ("2", "0.02", "0.9801"), ("5", "0.05", "0.9509900499")):
        out.append(_workflow(f"SYS_RL_ELAPSED_{duration}", ["V11", "V22", "V24"], {"run": _run(world(agent("h")))},
            [_op("run.create", run="run"), _op("rl.attach", run="run", controlled="h", reward="human_survival_v1", adapter="gymnasium"),
             _op("rl.step", run="run", intent=intent("wait", "h", "wait", duration=duration), label="transition")],
            [check("/captures/transition/elapsed", duration, "numeric_eq"),
             check("/captures/transition/reward_terms/alive_human", reward, "numeric_eq"),
             check("/captures/transition/reward", reward, "numeric_eq"),
             check("/captures/transition/discount", discount, "approx", abs_tol="0.000000000001"),
             check("/captures/transition/terminated", False), check("/captures/transition/truncated", False)],
            source=["plan:9.2", "plan:9.3"], actions=["wait"], decisions=["D7"]))
    out.append(_workflow("SYS_RL_CONVERSION_TERMINATES_CONTROLLER", ["V07", "V08", "V22"],
        {"run": _run(world(agent("h", infection={"onset_at": "0", "incubation_duration": "1"})))},
        [_op("run.create", run="run"), _op("rl.attach", run="run", controlled="h", reward="human_survival_v1", adapter="gymnasium"),
         _op("rl.step", run="run", intent=intent("wait", "h", "wait", duration="2"), label="transition"), _capture("run", "state")],
        [check("/captures/transition/terminated", True), check("/captures/transition/truncated", False),
         check("/captures/transition/elapsed", "1", "numeric_eq"),
         check("/captures/transition/reward_terms/conversion", "-10", "numeric_eq"),
         check("/captures/state/agents/h/type", "Zombie"), check("/captures/state/agents/h/life", 100),
         check("/captures/transition/controller_episode_id", op="different", other_path="/captures/transition/next_controller_episode_id")],
        source=["ontology:6.4", "plan:9.2"], actions=["wait"], decisions=["D7"]))
    for finite in (False, True):
        out.append(_workflow(f"SYS_RL_{'TASK_HORIZON' if finite else 'ROLLOUT_CUTOFF'}", ["V22", "V24"],
            {"run": _run(world(agent("h")), horizon="2" if finite else "10")},
            [_op("run.create", run="run"), _op("rl.attach", run="run", controlled="h", reward="human_survival_v1", adapter="gymnasium",
                                                      task_horizon="2" if finite else None, rollout_cutoff=None if finite else "2"),
             _op("rl.step", run="run", intent=intent("wait", "h", "wait", duration="5"), label="transition")],
            [check("/captures/transition/terminated", finite), check("/captures/transition/truncated", not finite),
             check("/captures/transition/elapsed", "2", "numeric_eq"),
             check("/captures/transition/bootstrap_allowed", not finite)],
            source=["plan:9.2"], actions=["wait"], decisions=["D7"]))
    out.append(_workflow("SYS_RL_AEC_BATCH_OBSERVATIONS", ["V13", "V15", "V16"],
        {"ab": _run(_contention_world()), "ba": _run(_contention_world())},
        [_op("run.create", run="ab"), _op("run.create", run="ba"),
         _op("rl.attach", run="ab", controlled=["a", "b"], adapter="aec"),
         _op("rl.attach", run="ba", controlled=["a", "b"], adapter="aec"),
         _op("rl.aec_batch", run="ab", order=["a", "b"], intents=_contention_script()[0]["intents"], label="ab"),
         _op("rl.aec_batch", run="ba", order=["b", "a"], intents=list(reversed(_contention_script()[0]["intents"])), label="ba"),
         _op("run.script", run="ab", steps=[advance("1")]), _op("run.script", run="ba", steps=[advance("1")]),
         _capture("ab", "end_ab"), _capture("ba", "end_ba")],
        [_same("/captures/ab/observations", "/captures/ba/observations"), _same("/captures/end_ab", "/captures/end_ba"),
         check("/captures/ab/observations/a/local_environment/stockpiles/stock/available/MEDICAL_SUPPLY", 1),
         check("/captures/ab/observations/b/local_environment/stockpiles/stock/available/MEDICAL_SUPPLY", 1)],
        source=["ontology:8.1", "plan:9.2"], actions=["pickup"], decisions=["D7"]))
    for failure, reason in (("exception", "MODEL_EXCEPTION"), ("missing", "MODEL_UNAVAILABLE"),
                            ("malformed", "INVALID_MODEL_OUTPUT"), ("repeated_invalid", "REJECTION_LIMIT")):
        out.append(_workflow(f"SYS_MODEL_FALLBACK_{failure.upper()}", ["V09", "V10", "V15", "V22"],
            {"run": _run(world(agent("h")), decision_mode="model")},
            [_op("model.install_fixture", run="run", agent="h", fixture=failure), _op("run.create", run="run"),
             _op("run.script", run="run", steps=[advance("0")]), _capture("run", "occurrences", "occurrences"),
             _capture("run", "state"), _capture("run", "decisions", "decisions")],
            [check("/captures/occurrences/*/action", ["wait"], "set_eq"),
             check("/captures/occurrences/*/planned_end", ["1"], "set_eq"),
             check("/captures/state/agents/h/stamina", "100", "numeric_eq"),
             check("/captures/decisions/*", 1, "count"),
             check("/captures/decisions/*/fallback_reason", reason, "all_eq")],
            source=["ontology:8.2", "plan:9.1"], actions=["wait"], decisions=["D7"]))
    out.append(_workflow("SYS_MODEL_PRIVATE_MEMORY_ISOLATION", ["V08", "V15", "V24"],
        {"run": _run(world(agent("a"), agent("b", x="12")), decision_mode="model")},
        [_op("model.install_fixture", run="run", agents=["a", "b"], fixture="private_counter", shared_weights=True),
         _op("run.create", run="run"), _op("run.script", run="run", steps=[advance("0")]),
         _capture("run", "first", "model_memory"), _op("run.script", run="run", steps=[advance("1")]),
         _capture("run", "second", "model_memory")],
        [check("/captures/first/a/count", 1), check("/captures/first/b/count", 1),
         check("/captures/second/a/count", 2), check("/captures/second/b/count", 2)],
        source=["ontology:8.2", "plan:9.1"], actions=["wait"], decisions=["D7"]))
    out.append(_workflow("SYS_MODEL_MEMORY_RESTART", ["V08", "V15", "V24"],
        {"reference": _run(world(agent("h")), decision_mode="model"), "resumed": _run(world(agent("h")), decision_mode="model")},
        [_op("model.install_fixture", run="reference", agent="h", fixture="private_counter"),
         _op("model.install_fixture", run="resumed", agent="h", fixture="private_counter"),
         _op("run.create", run="reference"), _op("run.create", run="resumed"),
         _op("run.script", run="reference", steps=[advance("3")]), _op("run.script", run="resumed", steps=[advance("1")]),
         _op("run.checkpoint", run="resumed", name="model", label="checkpoint"), _op("run.restart", run="resumed", checkpoint="model"),
         _op("run.script", run="resumed", steps=[advance("3")]), _capture("reference", "a", "model_memory"),
         _capture("resumed", "b", "model_memory"), _capture("reference", "da", "decisions"), _capture("resumed", "db", "decisions")],
        [_same("/captures/a", "/captures/b"), _same("/captures/da", "/captures/db"), check("/captures/b/h/count", 4)],
        source=["ontology:16.1", "plan:9.1", "plan:10.3"], actions=["wait"], decisions=["D7"]))
    out.append(_workflow("SYS_MODEL_UNSERIALIZABLE_RESTART_LIMIT", ["V24"], {"run": _run(world(agent("h")), decision_mode="model")},
        [_op("model.install_fixture", run="run", agent="h", fixture="unserializable_memory"),
         _op("run.create", run="run"), _op("run.script", run="run", steps=[advance("0")]),
         _op("run.checkpoint", run="run", name="limited", label="checkpoint"),
         _op("run.restart", run="run", checkpoint="limited", exact=True, on_error="capture", label="error"),
         _op("run.replay", run="run", time="0", label="replay")],
        [check("/captures/checkpoint/restart_capability", "STATE_REPLAY_ONLY"),
         check("/captures/error/code", "MODEL_STATE_UNAVAILABLE"), check("/captures/replay/agents/h/life", 100)],
        source=["ontology:16.1", "plan:10.3"], decisions=["D7"]))
    out.append(_workflow("SYS_ENCODER_PERMUTATION_AND_ROUNDTRIP", ["V09", "V15"], {},
        [_op("encoder.evaluate", observation={"self_state": agent("h"), "local_agents": [agent("a", x="11"), agent("b", x="12")],
                                             "time": "0", "bounds": ["100", "100"]},
             candidates=[intent("wait", "h", "wait", duration="1"), intent("rest", "h", "rest", duration="2")],
             padding=3, label="forward"),
         _op("encoder.evaluate", observation={"self_state": agent("h"), "local_agents": [agent("b", x="12"), agent("a", x="11")],
                                             "time": "0", "bounds": ["100", "100"]},
             candidates=[intent("wait", "h", "wait", duration="1"), intent("rest", "h", "rest", duration="2")],
             padding=3, label="reverse")],
        [_same("/captures/forward/neighborhood_features", "/captures/reverse/neighborhood_features"),
         _same("/captures/forward/decoded_intents", "/captures/reverse/decoded_intents"),
         check("/captures/forward/decoded_intents/0/action", "wait"),
         check("/captures/forward/decoded_intents/1/parameters/duration", "2"),
         check("/captures/forward/candidate_mask", [True, True, False, False, False]),
         check("/captures/forward/padding_decode_errors/*", 3, "count"),
         check("/captures/forward/padding_decode_errors/*/code", "INVALID_CANDIDATE", "all_eq")],
        source=["plan:9.1"], actions=["wait", "rest"], decisions=["D7"]))
    out.append(_workflow("SYS_TRAINING_RELOAD_AND_SPLITS", ["V08", "V15", "V16", "V24"], {},
        [_op("training.run", algorithm="ppo", decision_budget=4096, train_seeds=[11, 12], validation_seeds=[21], test_seeds=[31],
             scenario={"world": _movement_world(), "horizon": "10"}, label="trained"),
         _op("training.evaluate_checkpoint", checkpoint_from="trained", seeds=[31], deterministic=True, label="before"),
         _op("training.reload_checkpoint", checkpoint_from="trained", label="reloaded"),
         _op("training.evaluate_checkpoint", checkpoint_from="reloaded", seeds=[31], deterministic=True, label="after")],
        [check("/captures/trained/decisions_collected", 4096), check("/captures/trained/optimizer_steps", [1, 100000], "between"),
         check("/captures/trained/training_seeds", [11, 12]),
         check("/captures/trained/validation_seeds", [21]), check("/captures/trained/test_seeds_seen_during_selection/*", 0, "count"),
         _same("/captures/before/actions", "/captures/after/actions"),
         _same("/captures/before/reward_terms", "/captures/after/reward_terms"),
         check("/captures/before/action_count", [1, 100000], "between")],
        source=["plan:9.3"], decisions=["D7"], tier="training"))
    return out


def cases():
    result = _storage_cases() + _parallel_cases() + _configuration_cases() + _learning_cases() + _gui_cases()
    for c in result:
        if c["id"].startswith("GUI_RENDER_BENCHMARK_"):
            c["performance_checks"] = [{"path": "/captures/benchmark",
                                        "population": int(c["id"].rsplit("_", 1)[1]),
                                        "duration_seconds": "30"}]
    return result


def _gui_cases():
    """Real-browser interactions; assertions read DOM/projection/service facts."""
    out = []
    def gui(id, requirements, runs, steps, checks, **kwargs):
        kwargs.setdefault("tier", "browser")
        return _workflow(id, requirements, runs, steps, checks,
                         source=["plan:13", "matrix:5"], kind="browser", decisions=["D9"], **kwargs)
    def ui(action, **fields):
        return _op("browser." + action, **fields)
    def click(testid, **fields):
        return ui("click", testid=testid, **fields)
    def capture(label, **fields):
        return ui("capture", label=label, **fields)
    def fill(testid, value):
        return ui("fill", testid=testid, value=value)
    def opened(w, **config):
        return {"run": _run(w, **config)}, [_op("run.create", run="run"), ui("open", run="run")]

    draft = {"preset": "baseline_v0.1", "seed": 20261106, "horizon": "4"}
    out.append(gui("GUI_CONFIG_CLI_PARITY", ["G01", "V23", "V24"], {},
        [ui("open"), ui("import_config", draft=draft), fill("config-horizon", "5"),
         click("config-validate"), click("config-save"), ui("export_import_config", format="toml"),
         click("run-start", bind_run="gui"), _op("cli.run", draft={**draft, "horizon": "5"}, bind_run="cli"),
         _op("run.await", run="gui", state="COMPLETED"), _op("run.await", run="cli", state="COMPLETED"),
         _capture("gui", "gui_config", "resolved_config"), _capture("cli", "cli_config", "resolved_config"),
         _capture("gui", "gui_initial", "initial_snapshot"), _capture("cli", "cli_initial", "initial_snapshot"),
         _capture("gui", "gui_final"), _capture("cli", "cli_final"),
         _capture("gui", "gui_history", "semantic_history"), _capture("cli", "cli_history", "semantic_history"),
         fill("view-pacing", "4"), click("layer-trails"), _capture("gui", "after_view", "resolved_config")],
        [_same("/captures/gui_config/semantic", "/captures/cli_config/semantic"),
         _same("/captures/gui_config/semantic_fingerprint", "/captures/cli_config/semantic_fingerprint"),
         _same("/captures/gui_config/semantic_fingerprint", "/captures/after_view/semantic_fingerprint"),
         _same("/captures/gui_initial", "/captures/cli_initial"), _same("/captures/gui_final", "/captures/cli_final"),
         _same("/captures/gui_history", "/captures/cli_history"), check("/captures/gui_config/seed", 20261106)]))
    for field, value, code in (("human_count", -1, "INVALID_DOMAIN"),
                                ("human_roles.TYRANT", 1, "INCOMPATIBLE_ROLE"),
                                ("incubation_duration", "0", "INVALID_DOMAIN"),
                                ("world.length", "-1", "INVALID_DOMAIN"),
                                ("human_model", "missing:model:999", "MODEL_UNAVAILABLE")):
        out.append(gui("GUI_VALIDATION_" + field.upper().replace(".", "_"), ["G02"], {},
            [ui("open"), ui("import_config", draft=draft), fill("config-" + field, value),
             click("config-validate"), capture("errors", what="validation"), _op("runs.list", label="runs")],
            [check("/captures/errors/fields/" + field + "/code", code),
             check("/captures/errors/summary_codes/*", code, "contains"),
             check("/captures/errors/start_control/disabled", True), check("/captures/runs/*", 0, "count")]))
    out.append(gui("GUI_PREVIEW_RNG_ISOLATION", ["G02", "V16", "V23"], {},
        [ui("open"), ui("import_config", draft=draft), click("config-preview"), capture("preview", what="preview"),
         click("config-preview"), click("run-start", bind_run="previewed"),
         _op("cli.run", draft=draft, bind_run="direct"),
         _capture("previewed", "a", "initial_snapshot"), _capture("direct", "b", "initial_snapshot"),
         _capture("previewed", "draws_a", "initial_random_draws"), _capture("direct", "draws_b", "initial_random_draws"),
         click("config-edit-new"), fill("config-seed", 20261107), click("run-start", bind_run="changed"),
         _capture("changed", "changed", "initialization_provenance")],
        [_same("/captures/a", "/captures/b"), _same("/captures/draws_a", "/captures/draws_b"),
         check("/captures/changed/seed", 20261107),
         check("/captures/changed/reused_preview_id", op="different", other_path="/captures/preview/artifact_id")]))

    runs, steps = opened(world(agent("infected", role="DOCTOR", infection={"onset_at": "0", "incubation_duration": "2"}),
                               agent("starving", x="20", life=1, hunger="100")))
    out.append(gui("GUI_IDENTITY_INSPECTION_CONVERSION_DEATH", ["G03", "V03", "V04", "V07"], runs,
        steps + [fill("agent-search", "infected"), click("agent-search-select"), click("agent-follow"), capture("human"),
                 _op("run.script", run="run", steps=[advance("2")]), ui("sync"), capture("converted"),
                 _capture("run", "state2"), _op("run.script", run="run", steps=[advance("10")]), ui("sync"),
                 fill("agent-search", "starving"), click("agent-search-select"), capture("dead"), _capture("run", "state10")],
        [check("/captures/human/inspector/agent/id", "infected"), check("/captures/human/inspector/agent/status", "INFECTED"),
         check("/captures/converted/selected_agent", "infected"), check("/captures/converted/follow_agent", "infected"),
         _same("/captures/converted/inspector/agent", "/captures/state2/agents/infected"),
         check("/captures/converted/inspector/agent/type", "Zombie"),
         _same("/captures/dead/inspector/agent", "/captures/state10/agents/starving"),
         check("/captures/dead/inspector/agent/status", "DEAD"), check("/captures/dead/scene/living_agents/*", 1, "count"),
         check("/captures/dead/scene/remains/*", 1, "count"), check("/captures/dead/scene/glyph_semantics", "screen_symbol")]))
    out.append(gui("GUI_BASELINE_ENVIRONMENT_LAYERS", ["G03", "V23"], {},
        [ui("open"), ui("import_config", draft=draft), click("config-preview"), capture("scene", what="preview_scene")],
        [check("/captures/scene/shelters/*", 4, "count"), check("/captures/scene/barriers/*", 28, "count"),
         check("/captures/scene/stockpiles/*", 10, "count"), check("/captures/scene/agents/*", 1000, "count"),
         check("/captures/scene/legend/categories/*", "INFECTED", "contains"),
         check("/captures/scene/legend/non_color_tokens/*", "INFECTED", "contains")]))

    cohort_world = world(agent("a", infection={"onset_at": "0", "incubation_duration": "2"}),
                         agent("b", x="20", infection={"onset_at": "0", "incubation_duration": "3"}), agent("c", x="30"))
    runs, steps = opened(cohort_world)
    out.append(gui("GUI_FIXED_DYNAMIC_COHORTS", ["G04", "G05"], runs,
        steps + [ui("cohort_create", name="initial", mode="fixed", predicate={"status": "INFECTED"}),
                 ui("cohort_create", name="current", mode="dynamic", predicate={"status": "INFECTED"}), capture("initial", what="cohorts"),
                 _op("run.script", run="run", steps=[advance("2")]), ui("sync"), capture("two", what="cohorts"),
                 _op("run.script", run="run", steps=[advance("3")]), ui("sync"), capture("three", what="cohorts")],
        [check("/captures/initial/initial/member_ids", ["a", "b"], "set_eq"),
         check("/captures/two/initial/member_ids", ["a", "b"], "set_eq"), check("/captures/two/current/member_ids", ["b"], "set_eq"),
         check("/captures/two/initial/denominator", 2), check("/captures/two/current/denominator", 1),
         check("/captures/two/initial/human_survival/events", 1), check("/captures/two/initial/identity_survival/events", 0),
         check("/captures/three/current/member_ids/*", 0, "count"), check("/captures/three/current/denominator", 0),
         check("/captures/three/initial/conversions", 2), check("/captures/initial/overlap_label", "Cohorts may overlap")]))

    runs, steps = opened(world(agent("patient", life=7, hunger="100", infection={"onset_at": "0", "incubation_duration": "20"}),
                               agent("doctor", x="11", role="DOCTOR", inventory={"FOOD": 0, "MEDICAL_SUPPLY": 1, "MATERIAL": 0}),
                               agent("z", "Zombie", x="10", y="11")))
    out.append(gui("GUI_COHORT_CURE_REINFECTION_DEATH", ["G04", "V05", "V06", "V18"], runs,
        steps + [ui("cohort_create", name="initial", mode="fixed", predicate={"status": "INFECTED"}),
                 ui("cohort_create", name="current", mode="dynamic", predicate={"status": "INFECTED"}),
                 _op("run.script", run="run", steps=[submit("cure", "doctor", "treat_infection", "patient"), advance("4")]),
                 ui("sync"), capture("cured", what="cohorts"),
                 _op("run.script", run="run", steps=[submit("bite", "z", "bite", "patient"), advance("5.5")],
                     draws=[{"intent": "bite", "channel": "hit", "value": "0"}, {"intent": "bite", "channel": "infection", "value": "0"}]),
                 ui("sync"), capture("reinfection", what="cohorts"), _op("run.script", run="run", steps=[advance("10")]),
                 ui("sync"), capture("dead", what="cohorts")],
        [check("/captures/cured/current/member_ids/*", 0, "count"), check("/captures/cured/initial/member_ids", ["patient"]),
         check("/captures/cured/initial/cures", 1), check("/captures/reinfection/current/member_ids", ["patient"]),
         check("/captures/reinfection/initial/new_incidence", 1), check("/captures/dead/current/member_ids/*", 0, "count"),
         check("/captures/dead/initial/member_ids", ["patient"]), check("/captures/dead/initial/denominator", 1),
         check("/captures/dead/initial/human_survival/events", 1), check("/captures/dead/initial/identity_survival/events", 1)]))

    runs, steps = opened(_movement_world())
    out.append(gui("GUI_LINKED_CURSOR_AND_WATERMARK", ["G05"], runs,
        steps + [_op("run.script", run="run", steps=_moving_script() + [advance("4")]),
                 ui("chart_select", chart="population", time="2"), ui("await_view"), capture("linked"),
                 _op("measurement.query", run="run", measurement="populations", time="2", label="expected"),
                 ui("transport", behavior="delay_metrics", until="explicit_release"), click("replay-return-live"), capture("lagged")],
        [_same("/captures/linked/world/cursor", "/captures/linked/inspector/cursor"),
         _same("/captures/linked/world/cursor", "/captures/linked/statistics/cursor"),
         check("/captures/linked/world/cursor/time", "2", "numeric_eq"),
         _same("/captures/linked/statistics/populations", "/captures/expected"),
         check("/captures/lagged/statistics/watermark/time", "2", "numeric_eq"),
         check("/captures/lagged/world/cursor/time", "4", "numeric_eq"), check("/captures/lagged/statistics/lag_label", "Statistics through 2 s")]))

    deadline_world = world(agent("h", life=1, hunger="100", infection={"onset_at": "0", "incubation_duration": "10"}),
                           agent("survivor", x="20", infection={"onset_at": "0", "incubation_duration": "10"}))
    runs, steps = opened(deadline_world)
    out.append(gui("GUI_STEP_TIMESTAMP_AND_RESTART", ["G06", "V04", "V22", "V24"], runs,
        steps + [click("run-pause"), capture("paused", what="control"),
                 ui("elapse_wall_time", milliseconds=50), _capture("run", "still"),
                 click("run-step-transition"), capture("transition"), _capture("run", "after_step"),
                 click("run-checkpoint", name="inside_timestamp"), _op("run.restart", run="run", checkpoint="inside_timestamp"),
                 click("run-step-timestamp"), _capture("run", "final"), _capture("run", "events", "semantic_history")],
        [check("/captures/still/time", "0", "numeric_eq"), check("/captures/after_step/time", "10", "numeric_eq"),
         check("/captures/after_step/agents/h/status", "DEAD"), check("/captures/after_step/agents/h/type", "Human"),
         check("/captures/after_step/agents/h/life", 0), check("/captures/after_step/remains/*", 1, "count"),
         check("/captures/after_step/agents/survivor/type", "Human"),
         check("/captures/final/agents/survivor/type", "Zombie"), check("/captures/final/time", "10", "numeric_eq"),
         check("/captures/final/agents/h/type", "Human"), check("/captures/events/occurrences/*", 0, "count")]))

    runs, steps = opened(_movement_world())
    out.append(gui("GUI_REPLAY_PRESERVES_LIVE", ["G07", "G08", "V14", "V24"], runs,
        steps + [_op("run.script", run="run", steps=_moving_script() + [advance("2")]), _capture("run", "before"),
                 _capture("run", "counters_before", "execution_counters"), fill("replay-exact-time", "1.25"), click("replay-seek"),
                 click("replay-pause"), capture("replay"), _capture("run", "after"),
                 _capture("run", "counters_after", "execution_counters"), ui("disconnect"),
                 _op("run.script", run="run", steps=[advance("4")]), ui("reconnect"), click("replay-return-live"), capture("live")],
        [_same("/captures/before", "/captures/after"), _same("/captures/counters_before", "/captures/counters_after"),
         check("/captures/replay/mode", "REPLAY"), check("/captures/replay/scene/agents/h/x", "12.5", "numeric_eq"),
         check("/captures/live/mode", "LIVE"), check("/captures/live/scene/agents/h/x", "18", "numeric_eq")]))
    for command in ("start", "branch", "intervention", "stop"):
        runs, steps = opened(_movement_world(), interventions_enabled=True)
        out.append(gui("GUI_COMMAND_RECOVERY_" + command.upper(), ["G08", "V01", "V12", "V24"], runs,
            steps + [ui("command_prepare", command=command, command_id="same-command", child_alias="child",
                        at="0", change={"kind": "add_resource", "stockpile": "gift", "x": "20", "y": "20", "resource": "FOOD", "quantity": 3}),
                     _op("fault.arm", run="run", point="command_after_effect_before_ack", occurrence=1),
                     click("command-submit", on_disconnect="capture"), _op("server.recover"), ui("reconnect"),
                     click("command-retry"), capture("command", what="command"),
                     _op("commands.inspect", command_id="same-command", label="journal")],
            [check("/captures/command/status", "APPLIED"), check("/captures/journal/semantic_effects/*", 1, "count"),
             check("/captures/journal/resulting_run_ids/*", 1 if command in ("start", "branch") else 0, "count"),
             check("/captures/journal/active_worker_lease_count", [0, 0 if command == "stop" else 1], "between"),
             _same("/captures/command/effective_revision", "/captures/journal/effective_revision")]))
    runs, steps = opened(_movement_world())
    out.append(gui("GUI_STALE_CONTROL_REJECTED", ["G08"], runs,
        steps + [ui("open_tab", name="other"), ui("select_tab", name="other"), click("run-pause"),
                 ui("select_tab", name="main"), click("run-stop", preserve_stale_generation=True), capture("rejected", what="command"),
                 click("command-refresh"), capture("refreshed", what="control")],
        [check("/captures/rejected/status", "REJECTED"), check("/captures/rejected/code", "STALE_CONTROL_GENERATION"),
         check("/captures/refreshed/run_state", "PAUSED")]))

    runs, steps = opened(_movement_world())
    out.append(gui("GUI_STREAM_GAP_DUPLICATE_REORDER", ["G09"], runs,
        steps + [ui("transport", behavior="scripted_delta_faults", omit_sequences=[2], duplicate_sequences=[3], reverse_sequences=[4, 5]),
                 _op("run.script", run="run", steps=_moving_script() + [advance("1"), advance("2"), advance("3"), advance("4")]),
                 ui("release_transport"), ui("await_view"), capture("view"), _capture("run", "state"),
                 ui("capture_transport", label="transport")],
        [_same("/captures/view/scene/agents", "/captures/state/agents"),
         check("/captures/transport/snapshot_requests", [1, 100], "between"),
         check("/captures/transport/applied_revision_regressions", 0),
         _same("/captures/view/world/cursor", "/captures/view/inspector/cursor")]))
    runs, steps = opened(_movement_world())
    out.append(gui("GUI_STALE_SEEK_AND_EXACT_STRINGS", ["G09"], runs,
        steps + [_op("run.script", run="run", steps=_moving_script() + [advance("4")]),
                 ui("transport", behavior="hold_seek", time="1"), fill("replay-exact-time", "1"), click("replay-seek"),
                 fill("replay-exact-time", "3"), click("replay-seek"), ui("await_view"), ui("release_transport"), capture("latest"),
                 ui("projection_fixture", bundle={"run_id": "9007199254740993", "revision": "9007199254740995", "time": "0.1234567890123456789", "agents": {"9007199254740997": {"id": "9007199254740997", "x": "1", "y": "2"}}}),
                 capture("exact", what="projection")],
        [check("/captures/latest/world/cursor/time", "3", "numeric_eq"), check("/captures/latest/scene/agents/h/x", "16", "numeric_eq"),
         check("/captures/exact/run_id", "9007199254740993"), check("/captures/exact/revision", "9007199254740995"),
         check("/captures/exact/time", "0.1234567890123456789"), check("/captures/exact/agents/9007199254740997/id", "9007199254740997")]))

    runs, steps = opened(cohort_world)
    out.append(gui("GUI_CAUSAL_TIMELINE_ATOMIC_CONVERSION", ["G10", "V07", "V24"], runs,
        steps + [_op("run.script", run="run", steps=[advance("2")]), ui("timeline_filter", agent="a", event_type="CONVERSION"),
                 click("timeline-first-event"), capture("event", what="selected_event"),
                 click("event-before"), capture("before"), click("event-after"), capture("after"),
                 _capture("run", "events", "semantic_history")],
        [check("/captures/event/type", "CONVERSION"), check("/captures/event/time", "2", "numeric_eq"),
         check("/captures/before/scene/agents/a/type", "Human"), check("/captures/after/scene/agents/a/type", "Zombie"),
         check("/captures/after/scene/agents/a/role", None), check("/captures/after/scene/agents/a/infection_episode", None),
         _same("/captures/event/revision_after", "/captures/after/world/cursor/revision")]))
    for life, result in ((100, "CANCELLED_BY_CONFLICT"), (10, "CANCELLED_BY_DEATH")):
        runs, steps = opened(world(agent("h", life=10), agent("z", "Zombie", x="11", life=life)))
        out.append(gui("GUI_RECIPROCAL_TIMELINE_" + str(life), ["G10", "V04", "V19", "V24"], runs,
            steps + [_op("run.script", run="run", steps=[{"op": "submit_batch", "intents": [intent("swing", "h", "melee", "z"), intent("bite", "z", "bite", "h")]}, advance("1.5")],
                         draws=[{"intent": "swing", "channel": "hit", "value": "0"}]),
                     ui("timeline_filter", agent="h"), capture("timeline", what="timeline"),
                     _capture("run", "history", "timeline_records", agent="h"),
                     ui("timeline_select", intent="swing", event_type="ACTION_RESULT"), click("event-before"), capture("before"),
                     click("event-after"), capture("after")],
            [_same("/captures/timeline/records", "/captures/history/records"),
             check("/captures/timeline/occurrences/swing/result", "SUCCEEDED"), check("/captures/timeline/occurrences/bite/result", result),
             check("/captures/timeline/occurrences/bite/resolved_at", "1", "numeric_eq"),
             check("/captures/before/scene/agents/z/life", life), check("/captures/after/scene/agents/z/life", max(0, life - 16)),
             check("/captures/after/scene/agents/h/life", 10), check("/captures/after/scene/remains/*", 1 if life == 10 else 0, "count")]))
    hidden_world = world(agent("observer"), agent("hidden", "Zombie", x="90", y="90"))
    runs, steps = opened(hidden_world, decision_mode="model")
    out.append(gui("GUI_OBSERVATION_CLEARS_PRIVILEGED_CACHES", ["G11", "V15"], runs,
        steps + [_op("run.script", run="run", steps=[advance("0")]), fill("agent-search", "hidden"), click("agent-search-select"),
                 click("layer-global-agents"), _capture("run", "policy_before", "model_memory"),
                 ui("select_observation", agent="observer", decision_index=0), capture("observation"),
                 _op("observation.read", run="run", agent="observer", decision_index=0, label="recorded"),
                 _capture("run", "policy_after", "model_memory")],
        [_same("/captures/observation/observation", "/captures/recorded"),
         check("/captures/observation/scene/agents/hidden", op="absent"), check("/captures/observation/inspector/agent/id", "observer"),
         check("/captures/observation/privileged_cache_keys/*", 0, "count"),
         check("/captures/observation/perspective", "AGENT_OBSERVATION"), _same("/captures/policy_before", "/captures/policy_after")]))
    runs, steps = opened(_movement_world(), interventions_enabled=True)
    out.append(gui("GUI_EDIT_NEW_AND_MODEL_INTERVENTION", ["G12", "V08", "V24"], runs,
        steps + [_capture("run", "original", "resolved_config"), _capture("run", "history", "semantic_history"),
                 click("config-edit-new"), fill("config-incubation_duration", "301"), click("config-save"),
                 click("run-start", bind_run="new"), _capture("run", "unchanged", "resolved_config"),
                 _capture("run", "unchanged_history", "semantic_history"), _capture("new", "new", "resolved_config"),
                 ui("select_run", run="run"), ui("intervention_form", id="replace", at="0",
                    change={"kind": "replace_model", "agent": "h", "model_id": "HumanDefaultModel", "model_version": "1", "memory_policy": "reset"}),
                 click("command-submit"), _capture("run", "intervention", "interventions")],
        [_same("/captures/original", "/captures/unchanged"), _same("/captures/history", "/captures/unchanged_history"),
         check("/captures/new/semantic/incubation_duration", "301", "numeric_eq"),
         check("/captures/intervention/replace/status", "APPLIED"), check("/captures/intervention/replace/change/memory_policy", "reset")]))

    for backend, workers, observer in (("memory", 1, "live"), ("sqlite", 2, "slow"), ("memory", 4, "exports")):
        out.append(gui(f"GUI_OBSERVER_INDEPENDENCE_{backend.upper()}_{workers}_{observer.upper()}", ["G13", "V16", "V24"],
            {"headless": _run(_movement_world(), backend=backend, workers=workers), "viewed": _run(_movement_world(), backend=backend, workers=workers)},
            [_op("run.create", run="headless"), _op("run.create", run="viewed"), ui("open", run="viewed"),
             ui("observer_load", mode=observer, frame_rates=[1, 30], pacing=["0.25", "4", "fastest"], buffer_limit=16),
             _op("run.script", run="headless", steps=_moving_script() + [advance("4")]),
             _op("run.script", run="viewed", steps=_moving_script() + [advance("4")]),
             _capture("headless", "a"), _capture("viewed", "b"), _capture("headless", "ha", "semantic_history"),
             _capture("viewed", "hb", "semantic_history"), ui("capture_transport", label="transport")],
            [_same("/captures/a", "/captures/b"), _same("/captures/ha", "/captures/hb"),
             check("/captures/transport/max_queue_depth", [0, 16], "between")]))
    for size in (1000, 10000):
        out.append(gui(f"GUI_RENDER_BENCHMARK_{size}", ["G14"], {},
            [ui("open"), ui("benchmark", population=size, duration_seconds=30, warmup_seconds=5, aggregation=size > 1000,
                            interactions=["pan", "select", "scrub", "cohort", "pause"], label="benchmark")],
            [check("/captures/benchmark/population", size), check("/captures/benchmark/measured_frames", [1, 100000], "between"),
             check("/captures/benchmark/frame_times_ms/0", [0, 10000], "between"),
             check("/captures/benchmark/subscriber_max_queue_depth", [0, 16], "between"),
             *([check("/captures/benchmark/fps", [30, 10000], "between"),
                check("/captures/benchmark/input_latency_p95_ms", [0, 100], "between"),
                check("/captures/benchmark/receipt_ack_p95_ms", [0, 250], "between")] if size == 1000 else
               [check("/captures/benchmark/aggregation_label", "Spatial aggregation")])], tier="performance"))
    for browser in ("chromium", "firefox"):
        out.append(gui("GUI_ACCESSIBLE_KEYBOARD_" + browser.upper(), ["G15"], {},
            [ui("open", engine=browser, viewport={"width": 720, "height": 900}, reduced_motion=True),
             ui("keyboard_workflow", actions=["choose_baseline", "validate", "preview", "start", "pause", "select_agent", "show_table"], label="keyboard"),
             capture("accessibility", what="accessibility")],
            [check("/captures/keyboard/input_methods", ["keyboard"], "set_eq"),
             check("/captures/accessibility/controls/run-pause/accessible_name", "Pause run"),
             check("/captures/accessibility/controls/run-step-transition/disabled", False),
             check("/captures/accessibility/population_table/role", "table"),
             check("/captures/accessibility/population_table/headers", ["Time (s)", "Healthy humans", "Infected humans", "Zombies", "Dead identities"]),
             check("/captures/accessibility/status_tokens/*", "INFECTED", "contains"),
             check("/captures/accessibility/animation_mode", "reduced"),
             check("/captures/accessibility/focused_testid", "population-table")]))
    for format in ("scene_png", "chart_png", "chart_svg", "table_csv", "table_parquet", "replay_animation"):
        runs, steps = opened(_movement_world())
        out.append(gui("GUI_EXPORT_" + format.upper(), ["G16"], runs,
            steps + [_op("run.script", run="run", steps=_moving_script() + [advance("4")]), _capture("run", "before"),
                     ui("export_form", format=format, interval=["0", "4"], time="2", sample_interval="1", cohort="all", label="job"),
                     click("export-start"), ui("await_export", job="job", label="artifact"),
                     _op("export.read_artifact", artifact_from="artifact", label="decoded"), _capture("run", "after")],
            [_same("/captures/before", "/captures/after"), check("/captures/decoded/provenance/run_alias", "run"),
             check("/captures/decoded/provenance/time", "2", "numeric_eq"), check("/captures/decoded/provenance/interval", ["0", "4"]),
             check("/captures/decoded/provenance/cohort", "all"), check("/captures/decoded/provenance/sample_interval", "1", "numeric_eq"),
             check("/captures/decoded/bytes", [1, 1000000000], "between"),
             check("/captures/decoded/source_scene/agents/h/x", "14", "numeric_eq")]))
    runs, steps = opened(_movement_world())
    out.append(gui("GUI_EXPORT_CANCEL_PRESERVES_HISTORY", ["G16", "G14"], runs,
        steps + [_op("run.script", run="run", steps=_moving_script() + [advance("4")]), _capture("run", "before", "semantic_history"),
                 ui("export_form", format="replay_animation", interval=["0", "4"], label="job"),
                 _op("fault.arm", run="run", point="export_before_encode", behavior="pause"), click("export-start"),
                 click("export-cancel"), ui("release_export"), capture("job", what="export_job"), _capture("run", "after", "semantic_history")],
        [check("/captures/job/status", "CANCELLED"), check("/captures/job/active_tasks", 0), _same("/captures/before", "/captures/after")]))
    return out
