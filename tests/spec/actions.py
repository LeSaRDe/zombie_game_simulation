"""Executable, implementation-independent examples for all 29 action contracts.

Fixtures supply concrete starting states and independently stated observations.
They never execute game logic. The adapter must exercise the real admission,
scheduler, completion, and history paths of the future implementation.
"""
from copy import deepcopy
from decimal import Decimal

from .dsl import agent, world, intent, submit, advance, snapshot, check, case


def _number(path, value):
    return check(path, str(value), op="numeric_eq")


def _inventory(**items):
    return {"FOOD": 0, "MEDICAL_SUPPLY": 0, "MATERIAL": 0, **items}


def _gate(mode="CLOSED", integrity=200):
    return {"id": "g", "kind": "Gate", "rect": ["12", "9", "13", "11"],
            "mode": mode, "integrity": integrity, "max_integrity": 200}


def _path(x0, x1, duration, y="10"):
    return [{"x": str(x0), "y": str(y), "offset": "0"},
            {"x": str(x1), "y": str(y), "offset": str(duration)}]


def _draw(channel="hit", value="0", action="a"):
    return {"intent": action, "channel": channel, "value": value}


def _base_cases():
    """One success oracle per action; registry values are literal source facts."""
    rows = []

    def add(name, setup, command, duration, stamina, cost, cooldown="0", checks=(), draws=(), section="9",
            requirements=("V09", "V10", "V24")):
        checks = [check("/intents/a/status", "ADMITTED"),
                  check("/occurrences/a/result", "SUCCEEDED"),
                  _number("/occurrences/a/start_at", "0"),
                  _number("/occurrences/a/planned_end", duration),
                  _number("/occurrences/a/resolved_at", duration),
                  _number("/snapshots/end/agents/a/stamina", stamina),
                  check("/snapshots/end/agents/a/active_action", None), *checks]
        if Decimal(cooldown):
            checks.append(_number("/snapshots/end/agents/a/cooldowns/" + name,
                                  Decimal(duration) + Decimal(cooldown)))
        # The action must not silently mutate the actor's identity or unrelated
        # state. These are literal fixture comparisons, not a second simulator.
        actor = setup["agents"][0]
        checks.extend([check("/snapshots/end/agents/a/type", actor["type"]),
                       check("/snapshots/end/agents/a/role", actor["role"])])
        if name != "feed":
            checks.append(check("/snapshots/end/agents/a/life", actor["life"]))
        if name not in {"move", "dash"}:
            checks.extend([_number("/snapshots/end/agents/a/x", actor["x"]),
                           _number("/snapshots/end/agents/a/y", actor["y"])])
        rows.append({"name": name, "setup": setup, "command": command, "duration": duration,
                     "cost": cost, "cooldown": cooldown, "draws": list(draws), "section": section,
                     "case": case("ACT_" + name + "_success", requirements, setup,
                                  [command, snapshot("admitted"), advance(duration), snapshot()], checks,
                                  actions=[name], source=["ontology §" + section], draws=draws,
                                  description="Admit and resolve " + name + " with exact effects and frame conditions.")})

    add("move", world(agent("a")), submit("a", "a", "move", duration="2", path=_path(10, 14, 2)),
        "2", "99.6", "0", checks=[_number("/snapshots/end/agents/a/x", "14"),
        _number("/snapshots/end/agents/a/y", "10"), _number("/snapshots/admitted/agents/a/stamina", "100"),
        check("/snapshots/end/agents/a/life", 100)], section="10", requirements=("V09", "V11", "V14"))
    add("wait", world(agent("a", stamina="50")), submit("a", "a", "wait", duration="2"),
        "2", "50", "0", checks=[_number("/snapshots/end/agents/a/hunger", "20.1"),
        _number("/snapshots/end/agents/a/x", "10"), check("/snapshots/end/agents/a/life", 100)], section="10")
    add("rest", world(agent("a", stamina="50", life=70)), submit("a", "a", "rest", duration="2"),
        "2", "58", "0", checks=[_number("/snapshots/end/agents/a/hunger", "20.1"),
        _number("/snapshots/end/agents/a/x", "10"), check("/snapshots/end/agents/a/life", 70)], section="10")
    add("signal", world(agent("a")), submit("a", "a", "signal", kind="WARNING",
        payload={"position": ["10", "10"], "observed_at": "0"}), "0.5", "99", "1", "2",
        checks=[check("/snapshots/end/signals/*", 1, op="count"),
        _number("/snapshots/end/signals/*/radius", "40"),
        _number("/snapshots/end/signals/*/emitted_at", "0.5"),
        _number("/snapshots/end/signals/*/expires_at", "8.5"),
        check("/snapshots/end/signals/*/kind", "WARNING"),
        _number("/snapshots/end/agents/a/x", "10")], section="10")
    add("melee", world(agent("a"), agent("t", "Zombie", x="11")), submit("a", "a", "melee", "t"),
        "1", "94", "6", "1", checks=[check("/snapshots/end/agents/t/life", 84),
        check("/snapshots/end/agents/t/status", "ACTIVE"),
        check("/random_draws/*", 1, op="count"), _number("/random_draws/0/probability", "0.6575")],
        draws=[_draw()], section="11", requirements=("V09", "V16", "V17"))
    add("pickup", world(agent("a"), stockpiles=[{"id": "s", "x": "11", "y": "10",
        "stock": _inventory(FOOD=3)}]), submit("a", "a", "pickup", "s", resource_type="FOOD", quantity=2),
        "1", "99", "1", checks=[check("/snapshots/end/agents/a/inventory/FOOD", 2),
        check("/snapshots/end/stockpiles/s/stock/FOOD", 1),
        check("/snapshots/admitted/stockpiles/s/stock/FOOD", 3),
        check("/snapshots/admitted/stockpiles/s/reserved/FOOD", 2),
        check("/snapshots/end/stockpiles/s/reserved/FOOD", 0)], section="11",
        requirements=("V09", "V12", "V13"))
    add("drop", world(agent("a", inventory=_inventory(FOOD=3))),
        submit("a", "a", "drop", resource_type="FOOD", quantity=2), "0.5", "100", "0",
        checks=[check("/snapshots/end/agents/a/inventory/FOOD", 1),
        check("/snapshots/admitted/agents/a/inventory/FOOD", 3),
        check("/snapshots/admitted/agents/a/reserved/FOOD", 2),
        check("/snapshots/end/agents/a/reserved/FOOD", 0),
        check("/snapshots/end/stockpiles/*", 1, op="count"),
        check("/snapshots/end/stockpiles/*/stock/FOOD", 2),
        _number("/snapshots/end/stockpiles/*/x", "10")], section="11", requirements=("V09", "V12", "V13"))
    add("transfer", world(agent("a", inventory=_inventory(FOOD=2)), agent("t", x="11")),
        submit("a", "a", "transfer", "t", resource_type="FOOD", quantity=1), "1", "99", "1",
        checks=[check("/snapshots/end/agents/a/inventory/FOOD", 1),
        check("/snapshots/end/agents/t/inventory/FOOD", 1),
        check("/snapshots/admitted/agents/a/reserved/FOOD", 1),
        check("/snapshots/end/agents/a/reserved/FOOD", 0),
        check("/snapshots/end/agents/t/active_action", None)], section="11", requirements=("V09", "V12", "V13"))
    add("eat", world(agent("a", hunger="60", inventory=_inventory(FOOD=1))),
        submit("a", "a", "eat"), "2", "100", "0", checks=[
        _number("/snapshots/end/agents/a/hunger", "20.1"), check("/snapshots/end/agents/a/inventory/FOOD", 0),
        check("/snapshots/admitted/agents/a/inventory/FOOD", 1), check("/snapshots/admitted/agents/a/reserved/FOOD", 1),
        check("/snapshots/end/agents/a/reserved/FOOD", 0), check("/snapshots/end/agents/a/life", 100)], section="11")
    add("first_aid", world(agent("a", inventory=_inventory(MEDICAL_SUPPLY=1)), agent("t", x="11", life=60)),
        submit("a", "a", "first_aid", "t"), "3", "96", "4", "2", checks=[
        check("/snapshots/end/agents/t/life", 74), check("/snapshots/end/agents/t/status", "HEALTHY"),
        check("/snapshots/end/agents/a/inventory/MEDICAL_SUPPLY", 0),
        check("/snapshots/admitted/agents/a/reserved/MEDICAL_SUPPLY", 1),
        check("/snapshots/end/agents/a/reserved/MEDICAL_SUPPLY", 0),
        _number("/snapshots/end/agents/t/hunger", "20.15")], section="11")
    for name, initial, final in [("open_gate", "CLOSED", "OPEN"), ("close_gate", "OPEN", "CLOSED")]:
        add(name, world(agent("a"), barriers=[_gate(initial)]), submit("a", "a", name, "g"),
            "1", "99", "1", checks=[check("/snapshots/end/barriers/g/mode", final),
            check("/snapshots/end/barriers/g/integrity", 200), _number("/snapshots/end/agents/a/x", "10")],
            section="11", requirements=("V09", "V20"))
    add("claw", world(agent("a", "Zombie"), agent("t", x="11")), submit("a", "a", "claw", "t"),
        "1", "94", "6", "1", checks=[check("/snapshots/end/agents/t/life", 86),
        check("/snapshots/end/agents/t/status", "HEALTHY"), check("/random_draws/*", 1, op="count"),
        _number("/random_draws/0/probability", "0.72")], draws=[_draw()], section="12",
        requirements=("V09", "V16", "V17", "V18"))
    add("bite", world(agent("a", "Zombie"), agent("t", x="11")), submit("a", "a", "bite", "t"),
        "1.5", "90", "10", "2", checks=[check("/snapshots/end/agents/t/life", 94),
        check("/snapshots/end/agents/t/status", "INFECTED"), check("/snapshots/end/episodes/*", 1, op="count"),
        _number("/snapshots/end/episodes/*/onset_at", "1.5"),
        _number("/snapshots/end/episodes/*/conversion_due_at", "301.5"),
        check("/random_draws/*", 2, op="count"), _number("/random_draws/1/probability", "0.36")],
        draws=[_draw(), _draw("infection")], section="12", requirements=("V05", "V06", "V16", "V18"))
    add("feed", world(agent("a", "Zombie", life=90, stamina="90"),
        agent("body", x="11", life=0, death_at="0", death_cause="initial_condition"),
        remains=[{"id": "r", "source_agent": "body", "x": "11", "y": "10", "biomass": 4}]),
        submit("a", "a", "feed", "r"), "3", "100", "0", "1", checks=[
        check("/snapshots/end/agents/a/life", 98), check("/snapshots/end/remains/r/biomass", 3),
        check("/snapshots/admitted/remains/r/biomass", 4), check("/snapshots/admitted/remains/r/reserved_biomass", 1),
        check("/snapshots/end/remains/r/reserved_biomass", 0), check("/snapshots/end/agents/body/life", 0),
        check("/snapshots/end/agents/body/status", "DEAD")], section="12", requirements=("V04", "V13", "V17", "V21"))
    add("smash", world(agent("a", "Zombie"), barriers=[_gate()]), submit("a", "a", "smash", "g"),
        "2", "90", "10", "1", checks=[check("/snapshots/end/barriers/g/integrity", 180),
        check("/snapshots/end/barriers/g/mode", "CLOSED"), check("/random_draws/*", 0, op="count")], section="12")
    add("treat_infection", world(agent("a", role="DOCTOR", inventory=_inventory(MEDICAL_SUPPLY=1)),
        agent("t", x="11", life=60, infection={"onset_at": "0", "incubation_duration": "300"})),
        submit("a", "a", "treat_infection", "t"), "4", "94", "6", "2", checks=[
        check("/snapshots/end/agents/t/status", "HEALTHY"), check("/snapshots/end/agents/t/life", 60),
        _number("/snapshots/end/agents/t/stamina", "100"), _number("/snapshots/end/agents/t/hunger", "20.2"),
        check("/snapshots/end/agents/t/infection_episode", None),
        check("/snapshots/end/episodes/*/outcome", "CURED"),
        check("/snapshots/end/agents/a/inventory/MEDICAL_SUPPLY", 0),
        check("/snapshots/admitted/agents/a/inventory/MEDICAL_SUPPLY", 1),
        check("/snapshots/admitted/agents/a/reserved/MEDICAL_SUPPLY", 1),
        check("/snapshots/end/agents/a/reserved/MEDICAL_SUPPLY", 0)], section="13.1", requirements=("V05", "V06", "V12", "V13"))
    add("prophylaxis", world(agent("a", role="DOCTOR", inventory=_inventory(MEDICAL_SUPPLY=1)), agent("t", x="11")),
        submit("a", "a", "prophylaxis", "t"), "4", "94", "6", "2", checks=[
        check("/snapshots/end/agents/t/status", "HEALTHY"), check("/snapshots/end/agents/t/life", 100),
        _number("/snapshots/end/agents/t/infection_resistance_effective", "0.8"),
        _number("/snapshots/end/agents/t/effects/prophylaxis/end_at", "124"),
        check("/snapshots/end/agents/a/inventory/MEDICAL_SUPPLY", 0),
        check("/snapshots/admitted/agents/a/reserved/MEDICAL_SUPPLY", 1),
        check("/snapshots/end/agents/a/reserved/MEDICAL_SUPPLY", 0)], section="13.1")
    add("power_strike", world(agent("a", role="WARRIOR"), agent("t", "Zombie", x="11")),
        submit("a", "a", "power_strike", "t"), "1.5", "85", "15", "6", checks=[
        check("/snapshots/end/agents/t/life", 66), _number("/random_draws/0/probability", "0.8825"),
        _number("/snapshots/end/agents/a/damage_resistance", "0.2")], draws=[_draw()], section="13.2")
    add("guard", world(agent("a", role="WARRIOR")), submit("a", "a", "guard"),
        "1", "92", "8", "8", checks=[_number("/snapshots/end/agents/a/damage_resistance", "0.6"),
        _number("/snapshots/end/agents/a/effects/guard/end_at", "5"), check("/snapshots/end/agents/a/life", 100)], section="13.2")
    add("recon", world(agent("a", role="SCOUT")), submit("a", "a", "recon"),
        "2", "94", "6", "20", checks=[_number("/snapshots/end/agents/a/sense_r", "85"),
        _number("/snapshots/end/agents/a/effects/recon/end_at", "14"),
        _number("/snapshots/end/agents/a/speed", "2.6")], section="13.3")
    add("mark_target", world(agent("a", role="SCOUT"), agent("t", "Zombie", x="50")),
        submit("a", "a", "mark_target", "t"), "0.5", "99", "1", "3", checks=[
        check("/snapshots/end/signals/*", 1, op="count"), _number("/snapshots/end/signals/*/radius", "90"),
        _number("/snapshots/end/signals/*/expires_at", "10.5"), check("/snapshots/end/agents/t/life", 100)], section="13.3")
    add("build_barricade", world(agent("a", role="ENGINEER", inventory=_inventory(MATERIAL=2))),
        submit("a", "a", "build_barricade", center=["11.5", "10"], orientation="y", length="2"),
        "8", "88", "12", "2", checks=[check("/snapshots/end/barriers/*", 1, op="count"),
        check("/snapshots/end/barriers/*/kind", "Barricade"), check("/snapshots/end/barriers/*/integrity", 100),
        check("/snapshots/end/barriers/*/max_integrity", 100), check("/snapshots/end/agents/a/inventory/MATERIAL", 0),
        check("/snapshots/admitted/agents/a/inventory/MATERIAL", 2), check("/snapshots/admitted/agents/a/reserved/MATERIAL", 2),
        check("/snapshots/end/agents/a/reserved/MATERIAL", 0), _number("/snapshots/end/agents/a/x", "10")], section="13.4")
    add("repair_barrier", world(agent("a", role="ENGINEER", inventory=_inventory(MATERIAL=1)), barriers=[_gate(integrity=100)]),
        submit("a", "a", "repair_barrier", "g"), "5", "92", "8", "1", checks=[
        check("/snapshots/end/barriers/g/integrity", 160), check("/snapshots/end/barriers/g/mode", "CLOSED"),
        check("/snapshots/end/agents/a/inventory/MATERIAL", 0), check("/snapshots/admitted/agents/a/reserved/MATERIAL", 1),
        check("/snapshots/end/agents/a/reserved/MATERIAL", 0)], section="13.4")
    add("rally", world(agent("a", "Zombie", role="TYRANT"), agent("t", "Zombie", x="11"), agent("h", x="12")),
        submit("a", "a", "rally"), "2", "85", "15", "20", checks=[
        _number("/snapshots/end/agents/t/effects/rallied/magnitude", "0.1"),
        _number("/snapshots/end/agents/t/effects/rallied/end_at", "12"),
        check("/snapshots/end/agents/a/effects/rallied", op="absent"),
        check("/snapshots/end/agents/h/effects/rallied", op="absent"),
        check("/snapshots/end/agents/t/active_action", None), _number("/snapshots/end/signals/*/radius", "30")], section="13.5")
    add("demolish", world(agent("a", "Zombie", role="TYRANT"), barriers=[_gate()]),
        submit("a", "a", "demolish", "g"), "3", "82", "18", "6", checks=[
        check("/snapshots/end/barriers/g/integrity", 140), check("/snapshots/end/barriers/g/mode", "CLOSED"),
        check("/random_draws/*", 0, op="count")], section="13.5")
    add("dash", world(agent("a", "Zombie", role="RUNNER")),
        submit("a", "a", "dash", duration="1", path=_path(10, "14.8", 1)), "1", "87.616", "12", "8",
        checks=[_number("/snapshots/admitted/agents/a/stamina", "88"),
        _number("/snapshots/admitted/agents/a/speed", "4.8"), _number("/snapshots/end/agents/a/x", "14.8"),
        _number("/snapshots/end/agents/a/speed", "3.2"), check("/snapshots/end/agents/a/life", 100)], section="13.6")
    add("spit", world(agent("a", "Zombie", role="SPITTER"), agent("t", x="11")),
        submit("a", "a", "spit", "t"), "1", "92", "8", "8", checks=[
        check("/snapshots/end/agents/t/life", 96), check("/snapshots/end/agents/t/status", "INFECTED"),
        check("/snapshots/end/agents/a/spit_charges", 2), _number("/snapshots/end/agents/a/next_charge_at", "31"),
        check("/random_draws/*", 2, op="count"), _number("/random_draws/1/probability", "0.24")],
        draws=[_draw(), _draw("infection")], section="13.7", requirements=("V09", "V13", "V16", "V18"))
    add("scream", world(agent("a", "Zombie", role="SCREAMER")), submit("a", "a", "scream"),
        "2", "85", "15", "30", checks=[check("/snapshots/end/signals/*", 1, op="count"),
        check("/snapshots/end/signals/*/kind", "HUNT_CUE"), _number("/snapshots/end/signals/*/radius", "120"),
        _number("/snapshots/end/signals/*/expires_at", "14"), check("/snapshots/end/agents/a/life", 100)], section="13.8")
    return rows


def _shared_rejections(rows):
    out = []
    common = {"move", "wait", "rest", "signal"}
    for row in rows:
        name, original, cmd = row["name"], row["setup"], row["command"]
        source = ["ontology §9.2", "ontology §" + row["section"]]

        def rejected(suffix, setup, steps=None, extras=(), requirements=("V09", "V10"), draws=()):
            out.append(case("ACT_" + name + "_reject_" + suffix, requirements, setup,
                            steps or [cmd, snapshot()], [check("/intents/a/status", "REJECTED"),
                            check("/occurrences/a", op="absent"), *extras],
                            actions=[name], source=source, draws=draws,
                            description=name + " must reject " + suffix + " without creating an occurrence."))

        setup = deepcopy(original)
        rejected("busy_actor", setup, [submit("busy", "a", "wait", duration="5"), cmd, snapshot()],
                 extras=[check("/snapshots/end/agents/a/active_action", "busy"),
                         _number("/snapshots/end/agents/a/stamina", setup["agents"][0]["stamina"])])
        if Decimal(row["cost"]) > 0:
            setup = deepcopy(original)
            low = str(Decimal(row["cost"]) - Decimal("0.01"))
            setup["agents"][0]["stamina"] = low
            rejected("insufficient_stamina", setup, extras=[_number("/snapshots/end/agents/a/stamina", low)])
        if Decimal(row["cooldown"]) > 0:
            setup = deepcopy(original)
            setup["agents"][0]["cooldowns"] = {name: "10"}
            rejected("cooldown", setup, extras=[_number("/snapshots/end/agents/a/cooldowns/" + name, "10"),
                     _number("/snapshots/end/agents/a/stamina", setup["agents"][0]["stamina"])])
        if name not in common:
            setup = deepcopy(original)
            actor = setup["agents"][0]
            if actor["role"]:
                actor["role"] = None
            else:
                replacement = "Zombie" if actor["type"] == "Human" else "Human"
                setup["agents"][0] = agent("a", replacement)
            rejected("missing_capability", setup, extras=[_number("/snapshots/end/agents/a/stamina", "100")],
                     requirements=("V08", "V09"))
        # Kill a fully valid role-bearing actor first; never arrange a dead state
        # with an illegal active role merely to force an admission rejection.
        setup = deepcopy(original)
        setup["agents"][0]["life"] = 1
        killer_type = "Zombie" if setup["agents"][0]["type"] == "Human" else "Human"
        kill_action = "claw" if killer_type == "Zombie" else "melee"
        setup["agents"].append(agent("killer", killer_type, x="9"))
        rejected("dead_actor", setup,
                 [submit("kill", "killer", kill_action, "a"), advance("1"), cmd, snapshot()],
                 extras=[check("/snapshots/end/agents/a/life", 0), check("/snapshots/end/agents/a/status", "DEAD"),
                         check("/snapshots/end/agents/a/active_action", None)],
                 requirements=("V04", "V09"), draws=[_draw(action="kill")])
    return out


def _edge_cases(rows):
    out = []
    by_name = {r["name"]: r for r in rows}

    def variant(name, suffix, *, setup=None, steps=None, checks=(), draws=(), requirements=("V09",), config=None):
        row = by_name[name]
        out.append(case("ACT_" + name + "_" + suffix, requirements,
                        setup if setup is not None else row["setup"],
                        steps if steps is not None else [row["command"], advance(row["duration"]), snapshot()],
                        list(checks), actions=[name], draws=draws, config=config,
                        source=["ontology §9", "ontology §" + row["section"]],
                        description=name + ": " + suffix.replace("_", " ")))

    for name in ["melee", "claw", "bite", "power_strike", "spit"]:
        row = by_name[name]
        checks = [check("/occurrences/a/result", "MISSED"), check("/snapshots/end/agents/t/life", 100),
                  check("/random_draws/*", 1, op="count"), check("/snapshots/end/episodes/*", 0, op="count"),
                  _number("/snapshots/end/agents/a/stamina", str(100 - Decimal(row["cost"]))),
                  _number("/snapshots/end/agents/a/cooldowns/" + name,
                          Decimal(row["duration"]) + Decimal(row["cooldown"]))]
        if name == "spit":
            checks += [check("/snapshots/end/agents/a/spit_charges", 2),
                       _number("/snapshots/end/agents/a/next_charge_at", "31")]
        variant(name, "miss_has_no_target_effects", draws=[_draw(value="0.999999")], checks=checks,
                requirements=("V09", "V16", "V17", "V18"))
        self_cmd = submit("a", "a", name, "a")
        variant(name, "self_attack_rejected", steps=[self_cmd, snapshot()],
                checks=[check("/intents/a/status", "REJECTED"), check("/occurrences/a", op="absent"),
                        check("/snapshots/end/agents/a/life", 100), _number("/snapshots/end/agents/a/stamina", "100")],
                config={"allow_intraspecies_combat": True})

        same_type = deepcopy(row["setup"])
        same_type["agents"][1] = agent("t", same_type["agents"][0]["type"], x="11")
        variant(name, "same_type_opponent_disabled", setup=same_type,
                steps=[row["command"], snapshot()], checks=[
                    check("/intents/a/status", "REJECTED"), check("/occurrences/a", op="absent"),
                    check("/snapshots/end/agents/t/life", 100),
                    _number("/snapshots/end/agents/a/stamina", "100"),
                    check("/random_draws/*", 0, op="count")],
                config={"allow_intraspecies_combat": False})
        remaining = {"melee": 84, "claw": 86, "bite": 94, "power_strike": 66, "spit": 96}[name]
        variant(name, "same_type_opponent_enabled", setup=same_type, draws=[_draw()], checks=[
                    check("/occurrences/a/result", "SUCCEEDED"),
                    check("/snapshots/end/agents/t/life", remaining),
                    check("/random_draws/*", 1, op="count"),
                    check("/snapshots/end/episodes/*", 0, op="count")],
                config={"allow_intraspecies_combat": True}, requirements=("V09", "V16", "V18"))

    for name, remaining in [("bite", 94), ("spit", 96)]:
        row = by_name[name]
        variant(name, "hit_with_failed_infection_draw", draws=[_draw(), _draw("infection", "0.99")],
                checks=[check("/occurrences/a/result", "SUCCEEDED"),
                        check("/snapshots/end/agents/t/life", remaining),
                        check("/snapshots/end/agents/t/status", "HEALTHY"),
                        check("/snapshots/end/episodes/*", 0, op="count"),
                        check("/random_draws/*", 2, op="count"),
                        check("/random_draws/1/outcome", False)], requirements=("V05", "V16", "V18"))
        setup = deepcopy(row["setup"])
        setup["agents"][1]["infection"] = {"onset_at": "0", "incubation_duration": "300"}
        variant(name, "existing_infection_is_not_restarted", setup=setup, draws=[_draw()], checks=[
            check("/snapshots/end/agents/t/life", remaining), check("/snapshots/end/agents/t/status", "INFECTED"),
            check("/snapshots/end/episodes/*", 1, op="count"),
            _number("/snapshots/end/episodes/*/onset_at", "0"),
            _number("/snapshots/end/episodes/*/conversion_due_at", "300"),
            check("/random_draws/*", 1, op="count")], requirements=("V05", "V06", "V18"))
        setup = deepcopy(row["setup"])
        setup["agents"][1]["life"] = 4
        variant(name, "lethal_hit_has_no_infection_draw", setup=setup, draws=[_draw()], checks=[
            check("/snapshots/end/agents/t/life", 0), check("/snapshots/end/agents/t/status", "DEAD"),
            check("/snapshots/end/episodes/*", 0, op="count"),
            check("/random_draws/*", 1, op="count"),
            check("/snapshots/end/remains/*", 1, op="count")], requirements=("V04", "V17", "V18", "V21"))

    for name in ["move", "wait", "rest", "dash"]:
        row = by_name[name]
        for label, duration in [("zero", "0"), ("below_minimum", "0.249" if name in ["move", "wait"] else "0.999"),
                                ("above_maximum", "5.001" if name != "dash" else "1.001")]:
            cmd = deepcopy(row["command"])
            cmd["parameters"]["duration"] = duration
            if name in ["move", "dash"]:
                cmd["parameters"]["path"] = _path(10, 10, duration)
            variant(name, "reject_duration_" + label, steps=[cmd, snapshot()],
                    checks=[check("/intents/a/status", "REJECTED"), check("/occurrences/a", op="absent")],
                    requirements=("V09", "V10", "V14"))
    variant("move", "continuous_midpoint", steps=[by_name["move"]["command"], advance("1"), snapshot()], checks=[
        _number("/snapshots/end/agents/a/x", "12"), _number("/snapshots/end/agents/a/stamina", "99.8"),
        check("/occurrences/a/result", "IN_PROGRESS"), check("/snapshots/end/agents/a/active_action", "a")], requirements=("V11", "V14", "V22"))
    variant("move", "insufficient_total_path_stamina", setup=world(agent("a", stamina="0.399")),
        steps=[by_name["move"]["command"], snapshot()], checks=[check("/intents/a/status", "REJECTED"),
        _number("/snapshots/end/agents/a/x", "10"), _number("/snapshots/end/agents/a/stamina", "0.399")], requirements=("V11", "V14"))
    variant("move", "instantaneous_speed_not_just_average", setup=world(agent("a")), steps=[
        submit("a", "a", "move", duration="2", path=[{"x": "10", "y": "10", "offset": "0"},
        {"x": "13", "y": "10", "offset": "0.5"}, {"x": "14", "y": "10", "offset": "2"}]), snapshot()],
        checks=[check("/intents/a/status", "REJECTED"), _number("/snapshots/end/agents/a/x", "10")], requirements=("V14",))
    variant("rest", "caps_energy_without_healing", setup=world(agent("a", stamina="99", life=30)),
        checks=[_number("/snapshots/end/agents/a/stamina", "100"), check("/snapshots/end/agents/a/life", 30)], requirements=("V11", "V17"))
    variant("rest", "zombie_rest_rate", setup=world(agent("a", "Zombie", stamina="50")),
        checks=[_number("/snapshots/end/agents/a/stamina", "56"), check("/snapshots/end/agents/a/life", 100)], requirements=("V11",))
    variant("wait", "zero_energy_is_legal", setup=world(agent("a", stamina="0")),
        checks=[check("/occurrences/a/result", "SUCCEEDED"), _number("/snapshots/end/agents/a/stamina", "0")], requirements=("V11",))
    variant("signal", "unknown_kind_rejected", steps=[submit("a", "a", "signal", kind="MIND_CONTROL", payload={}), snapshot()],
        checks=[check("/intents/a/status", "REJECTED"), check("/snapshots/end/signals/*", 0, op="count"),
                _number("/snapshots/end/agents/a/stamina", "100")], requirements=("V09", "V15"))

    for name in ["pickup", "drop", "transfer"]:
        for label, quantity in [("zero", 0), ("negative", -1), ("fractional", "0.5"), ("bool", True)]:
            cmd = deepcopy(by_name[name]["command"])
            cmd["parameters"]["quantity"] = quantity
            variant(name, "reject_quantity_" + label, steps=[cmd, snapshot()], checks=[
                check("/intents/a/status", "REJECTED"), check("/occurrences/a", op="absent")], requirements=("V09", "V12"))
        cmd = deepcopy(by_name[name]["command"])
        cmd["parameters"]["resource_type"] = "BIOMASS"
        variant(name, "biomass_is_not_portable", steps=[cmd, snapshot()], checks=[
            check("/intents/a/status", "REJECTED"), check("/occurrences/a", op="absent")], requirements=("V09", "V12"))
    setup = deepcopy(by_name["pickup"]["setup"])
    setup["agents"][0]["inventory"] = _inventory(FOOD=9)
    variant("pickup", "no_partial_fill_for_capacity", setup=setup, steps=[by_name["pickup"]["command"], snapshot()],
        checks=[check("/intents/a/status", "REJECTED"), check("/snapshots/end/stockpiles/s/stock/FOOD", 3),
        check("/snapshots/end/agents/a/inventory/FOOD", 9), check("/snapshots/end/stockpiles/s/reserved/FOOD", 0)], requirements=("V12", "V13"))
    setup = deepcopy(by_name["pickup"]["setup"])
    setup["stockpiles"][0]["stock"]["FOOD"] = 1
    variant("pickup", "no_partial_fill_for_stock", setup=setup, steps=[by_name["pickup"]["command"], snapshot()],
        checks=[check("/intents/a/status", "REJECTED"), check("/snapshots/end/stockpiles/s/stock/FOOD", 1),
        check("/snapshots/end/agents/a/inventory/FOOD", 0)], requirements=("V12", "V13"))
    setup = deepcopy(by_name["drop"]["setup"])
    setup["agents"][0]["inventory"]["FOOD"] = 1
    variant("drop", "cannot_drop_unheld_quantity", setup=setup, steps=[by_name["drop"]["command"], snapshot()],
        checks=[check("/intents/a/status", "REJECTED"), check("/snapshots/end/agents/a/inventory/FOOD", 1),
        check("/snapshots/end/stockpiles/*", 0, op="count")], requirements=("V12",))
    variant("transfer", "cannot_transfer_to_zombie", setup=world(agent("a", inventory=_inventory(FOOD=2)), agent("t", "Zombie", x="11")),
        steps=[by_name["transfer"]["command"], snapshot()], checks=[check("/intents/a/status", "REJECTED"),
        check("/snapshots/end/agents/a/inventory/FOOD", 2)], requirements=("V09", "V12"))
    variant("eat", "satiated_at_admission", setup=world(agent("a", hunger="0", inventory=_inventory(FOOD=1))),
        steps=[by_name["eat"]["command"], snapshot()], checks=[check("/intents/a/status", "REJECTED"),
        check("/snapshots/end/agents/a/inventory/FOOD", 1), _number("/snapshots/end/agents/a/hunger", "0")], requirements=("V09", "V11"))
    variant("eat", "hunger_floor", setup=world(agent("a", hunger="1", inventory=_inventory(FOOD=1))), checks=[
        check("/occurrences/a/result", "SUCCEEDED"), _number("/snapshots/end/agents/a/hunger", "0"),
        check("/snapshots/end/agents/a/inventory/FOOD", 0)], requirements=("V11",))
    variant("first_aid", "doctor_heals_twenty_eight", setup=world(agent("a", role="DOCTOR", inventory=_inventory(MEDICAL_SUPPLY=1)),
        agent("t", x="11", life=60, infection={"onset_at": "0", "incubation_duration": "300"})), checks=[
        check("/snapshots/end/agents/t/life", 88), check("/snapshots/end/agents/t/status", "INFECTED"),
        _number("/snapshots/end/episodes/*/conversion_due_at", "300")], requirements=("V05", "V17"))
    variant("first_aid", "self_heal_capped", setup=world(agent("a", life=95, inventory=_inventory(MEDICAL_SUPPLY=1))),
        steps=[submit("a", "a", "first_aid", "a"), advance("3"), snapshot()], checks=[
        check("/occurrences/a/result", "SUCCEEDED"), check("/snapshots/end/agents/a/life", 100),
        check("/snapshots/end/agents/a/inventory/MEDICAL_SUPPLY", 0)], requirements=("V17",))
    variant("first_aid", "healthy_target_rejected", setup=world(agent("a", inventory=_inventory(MEDICAL_SUPPLY=1)), agent("t", x="11")),
        steps=[by_name["first_aid"]["command"], snapshot()], checks=[check("/intents/a/status", "REJECTED"),
        check("/snapshots/end/agents/a/inventory/MEDICAL_SUPPLY", 1), _number("/snapshots/end/agents/a/stamina", "100")], requirements=("V09", "V17"))

    for name, mode in [("open_gate", "OPEN"), ("close_gate", "BREACHED")]:
        setup = world(agent("a"), barriers=[_gate(mode, 0 if mode == "BREACHED" else 200)])
        variant(name, "wrong_gate_mode", setup=setup, steps=[by_name[name]["command"], snapshot()], checks=[
            check("/intents/a/status", "REJECTED"), check("/snapshots/end/barriers/g/mode", mode)], requirements=("V20",))
    variant("close_gate", "living_occupant_blocks_closure", setup=world(agent("a"), agent("t", "Zombie", x="12.5"), barriers=[_gate("OPEN")]),
        steps=[by_name["close_gate"]["command"], snapshot()], checks=[check("/intents/a/status", "REJECTED"),
        check("/snapshots/end/barriers/g/mode", "OPEN"), _number("/snapshots/end/agents/t/x", "12.5")], requirements=("V02", "V20"))
    for name, damage in [("smash", 20), ("demolish", 60)]:
        setup = deepcopy(by_name[name]["setup"])
        setup["barriers"][0]["integrity"] = 10
        variant(name, "breach_clamps_integrity", setup=setup, checks=[
            check("/snapshots/end/barriers/g/integrity", 0), check("/snapshots/end/barriers/g/mode", "BREACHED"),
            check("/random_draws/*", 0, op="count")], requirements=("V20",))
        setup["barriers"][0] = {"id": "g", "kind": "Obstacle", "rect": ["12", "9", "13", "11"]}
        variant(name, "permanent_wall_rejected", setup=setup, steps=[by_name[name]["command"], snapshot()], checks=[
            check("/intents/a/status", "REJECTED"), check("/snapshots/end/barriers/g/kind", "Obstacle")], requirements=("V09", "V20"))
    setup = deepcopy(by_name["feed"]["setup"])
    setup["agents"][0].update(life=100, stamina="100")
    variant("feed", "no_need_to_feed", setup=setup, steps=[by_name["feed"]["command"], snapshot()], checks=[
        check("/intents/a/status", "REJECTED"), check("/snapshots/end/remains/r/biomass", 4)], requirements=("V09", "V21"))
    setup = deepcopy(by_name["feed"]["setup"])
    setup["remains"][0]["biomass"] = 0
    variant("feed", "exhausted_remains", setup=setup, steps=[by_name["feed"]["command"], snapshot()], checks=[
        check("/intents/a/status", "REJECTED"), check("/snapshots/end/remains/r/biomass", 0),
        check("/snapshots/end/agents/a/life", 90)], requirements=("V09", "V21"))

    for name in ["first_aid", "treat_infection", "prophylaxis", "build_barricade", "repair_barrier", "eat"]:
        setup = deepcopy(by_name[name]["setup"])
        resource = "FOOD" if name == "eat" else "MATERIAL" if name in ["build_barricade", "repair_barrier"] else "MEDICAL_SUPPLY"
        setup["agents"][0]["inventory"][resource] = 0
        variant(name, "missing_consumable", setup=setup, steps=[by_name[name]["command"], snapshot()], checks=[
            check("/intents/a/status", "REJECTED"), check("/occurrences/a", op="absent"),
            check("/snapshots/end/agents/a/inventory/" + resource, 0)], requirements=("V09", "V12", "V13"))
    variant("treat_infection", "self_cure_preserves_current_life", setup=world(agent("a", role="DOCTOR", life=60,
        inventory=_inventory(MEDICAL_SUPPLY=1), infection={"onset_at": "0", "incubation_duration": "300"})),
        steps=[submit("a", "a", "treat_infection", "a"), advance("4"), snapshot()], checks=[
        check("/occurrences/a/result", "SUCCEEDED"), check("/snapshots/end/agents/a/status", "HEALTHY"),
        check("/snapshots/end/agents/a/life", 60), _number("/snapshots/end/agents/a/stamina", "94"),
        check("/snapshots/end/agents/a/role", "DOCTOR")], requirements=("V05", "V06", "V17"))
    setup = deepcopy(by_name["prophylaxis"]["setup"])
    setup["agents"][1]["infection"] = {"onset_at": "0", "incubation_duration": "300"}
    variant("prophylaxis", "cannot_cure_infected_target", setup=setup, steps=[by_name["prophylaxis"]["command"], snapshot()], checks=[
        check("/intents/a/status", "REJECTED"), check("/snapshots/end/agents/t/status", "INFECTED"),
        check("/snapshots/end/agents/a/inventory/MEDICAL_SUPPLY", 1)], requirements=("V05", "V09"))
    for name, end, field, value in [("guard", "5", "damage_resistance", "0.2"),
                                    ("recon", "14", "sense_r", "55")]:
        variant(name, "effect_exclusive_expiry", steps=[by_name[name]["command"], advance(end), snapshot()], checks=[
            _number("/snapshots/end/agents/a/" + field, value),
            check("/snapshots/end/agents/a/effects/" + name, op="absent")], requirements=("V22", "V25"))
    variant("recon", "subsequent_observation_expands", setup=world(agent("a", role="SCOUT"), agent("t", "Zombie", x="70")), steps=[
        {"op": "observe", "actor": "a", "label": "before"}, by_name["recon"]["command"], advance("2"),
        {"op": "observe", "actor": "a", "label": "after"}], checks=[
        check("/observations/before/local_agents/t", op="absent"),
        check("/observations/after/local_agents/t/id", "t")], requirements=("V15", "V25"))
    variant("recon", "does_not_see_through_wall", setup=world(agent("a", role="SCOUT"), agent("t", "Zombie", x="70"),
        barriers=[{"id": "wall", "kind": "Obstacle", "rect": ["39", "0", "40", "100"]}]), steps=[
        by_name["recon"]["command"], advance("2"), {"op": "observe", "actor": "a", "label": "after"}],
        checks=[check("/observations/after/local_agents/t", op="absent")], requirements=("V15",))
    setup = deepcopy(by_name["mark_target"]["setup"])
    setup["agents"][1]["x"] = "65.001"
    variant("mark_target", "outside_sensing_rejected", setup=setup, steps=[by_name["mark_target"]["command"], snapshot()], checks=[
        check("/intents/a/status", "REJECTED"), check("/snapshots/end/signals/*", 0, op="count")], requirements=("V15",))
    setup = deepcopy(by_name["build_barricade"]["setup"])
    setup["stockpiles"] = [{"id": "s", "x": "11.5", "y": "10", "stock": _inventory(FOOD=1)}]
    variant("build_barricade", "cannot_enclose_nonempty_stockpile", setup=setup, steps=[by_name["build_barricade"]["command"], snapshot()],
        checks=[check("/intents/a/status", "REJECTED"), check("/snapshots/end/barriers/*", 0, op="count"),
                check("/snapshots/end/agents/a/inventory/MATERIAL", 2)], requirements=("V02", "V20"))
    for length in ["1.999", "8.001"]:
        cmd = deepcopy(by_name["build_barricade"]["command"])
        cmd["parameters"]["length"] = length
        variant("build_barricade", "invalid_length_" + length.replace(".", "_"), steps=[cmd, snapshot()], checks=[
            check("/intents/a/status", "REJECTED"), check("/snapshots/end/barriers/*", 0, op="count")], requirements=("V09", "V20"))
    setup = deepcopy(by_name["repair_barrier"]["setup"])
    setup["barriers"] = [_gate("BREACHED", 0)]
    variant("repair_barrier", "breached_gate_becomes_open", setup=setup, checks=[
        check("/snapshots/end/barriers/g/integrity", 60), check("/snapshots/end/barriers/g/mode", "OPEN"),
        check("/snapshots/end/agents/a/inventory/MATERIAL", 0)], requirements=("V20",))
    setup["barriers"] = [{"id": "g", "kind": "Barricade", "rect": ["12", "9", "13", "11"],
                          "integrity": 0, "max_integrity": 100, "creator_id": "a"}]
    variant("repair_barrier", "destroyed_barricade_cannot_repair", setup=setup,
        steps=[by_name["repair_barrier"]["command"], snapshot()], checks=[check("/intents/a/status", "REJECTED"),
        check("/snapshots/end/barriers/g/integrity", 0), check("/snapshots/end/agents/a/inventory/MATERIAL", 1)], requirements=("V20",))
    variant("rally", "broadcast_across_barrier_excludes_self", setup=world(agent("a", "Zombie", role="TYRANT"),
        agent("t", "Zombie", x="20"), barriers=[{"id": "wall", "kind": "Obstacle", "rect": ["14", "0", "15", "100"]}]),
        checks=[_number("/snapshots/end/agents/t/effects/rallied/magnitude", "0.1"),
                check("/snapshots/end/agents/a/effects/rallied", op="absent"),
                check("/snapshots/end/agents/t/active_action", None)], requirements=("V15", "V25"))
    variant("dash", "must_afford_flat_and_distance_cost", setup=world(agent("a", "Zombie", role="RUNNER", stamina="12.383")),
        steps=[by_name["dash"]["command"], snapshot()], checks=[check("/intents/a/status", "REJECTED"),
        _number("/snapshots/end/agents/a/stamina", "12.383"), _number("/snapshots/end/agents/a/x", "10")], requirements=("V11", "V14"))
    variant("spit", "miss_recharge_and_no_postponement", steps=[submit("first", "a", "spit", "t"), advance("9"),
        submit("second", "a", "spit", "t"), advance("10"), snapshot("spent"), advance("31"), snapshot("recharge"),
        advance("61"), snapshot()], draws=[_draw(value="0.99", action="first"), _draw(value="0.99", action="second")],
        checks=[check("/snapshots/spent/agents/a/spit_charges", 1), _number("/snapshots/spent/agents/a/next_charge_at", "31"),
        check("/snapshots/recharge/agents/a/spit_charges", 2), _number("/snapshots/recharge/agents/a/next_charge_at", "61"),
        check("/snapshots/end/agents/a/spit_charges", 3), check("/snapshots/end/agents/a/next_charge_at", None),
        check("/snapshots/end/agents/t/life", 100), check("/random_draws/*", 2, op="count")], requirements=("V13", "V16", "V22"))
    setup = deepcopy(by_name["spit"]["setup"])
    setup["agents"][0].update(spit_charges=0, next_charge_at="30")
    variant("spit", "empty_reservoir_rejected_without_cost", setup=setup,
        steps=[by_name["spit"]["command"], snapshot()], checks=[
        check("/intents/a/status", "REJECTED"), check("/occurrences/a", op="absent"),
        check("/snapshots/end/agents/a/spit_charges", 0),
        _number("/snapshots/end/agents/a/next_charge_at", "30"),
        _number("/snapshots/end/agents/a/stamina", "100"), check("/random_draws/*", 0, op="count")],
        requirements=("V09", "V13"))
    variant("scream", "cannot_claim_unknown_target", steps=[submit("a", "a", "scream",
        payload={"entity_id": "never_observed", "position": ["90", "90"], "observed_at": "0"}), snapshot()],
        checks=[check("/intents/a/status", "REJECTED"), check("/snapshots/end/signals/*", 0, op="count"),
                _number("/snapshots/end/agents/a/stamina", "100")], requirements=("V09", "V15"))

    # Revalidation is exercised by real movement rather than out-of-band state mutation.
    for name in ["melee", "claw", "bite", "power_strike", "spit", "first_aid", "treat_infection", "prophylaxis", "transfer"]:
        row = by_name[name]
        setup = deepcopy(row["setup"])
        duration = Decimal(row["duration"])
        target = setup["agents"][1]
        speed = Decimal("1.6") if target["type"] == "Zombie" else Decimal("2")
        if name == "spit":
            target["x"] = "21.5"
        start = Decimal(target["x"])
        end = start + speed * duration
        steps = [{"op": "submit_batch", "intents": [
            {k: v for k, v in row["command"].items() if k != "op"},
            intent("escape", "t", "move", duration=str(duration), path=_path(start, end, duration))]},
            advance(str(duration)), snapshot()]
        checks = [check("/occurrences/a/result", "FAILED_PRECONDITION"),
                  check("/snapshots/end/agents/t/life", target["life"]),
                  check("/random_draws/*", 0, op="count"),
                  _number("/snapshots/end/agents/a/stamina", 100 - Decimal(row["cost"]))]
        if name in ["first_aid", "treat_infection", "prophylaxis"]:
            checks += [check("/snapshots/end/agents/a/inventory/MEDICAL_SUPPLY", 1),
                       check("/snapshots/end/agents/a/reserved/MEDICAL_SUPPLY", 0)]
        if name == "transfer":
            checks += [check("/snapshots/end/agents/a/inventory/FOOD", 2),
                       check("/snapshots/end/agents/t/inventory/FOOD", 0),
                       check("/snapshots/end/agents/a/reserved/FOOD", 0)]
        if name == "spit":
            checks += [check("/snapshots/end/agents/a/spit_charges", 3),
                       check("/snapshots/end/agents/a/next_charge_at", None)]
        if Decimal(row["cooldown"]):
            checks += [_number("/snapshots/end/agents/a/cooldowns/" + name,
                               duration + Decimal(row["cooldown"]))]
        variant(name, "target_moves_out_before_resolution", setup=setup, steps=steps, checks=checks,
                requirements=("V09", "V13", "V16"))
    return out


def cases():
    rows = _base_cases()
    return [row["case"] for row in rows] + _shared_rejections(rows) + _edge_cases(rows)
