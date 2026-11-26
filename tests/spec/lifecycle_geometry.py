"""Independent lifecycle, concurrency, geometry, and observation examples.

Worlds here are controlled semantic fixtures, not samples from baseline placement.
Expected quantities are literal worked examples from the ontology; this module
contains no simulation engine. Empty optional state is normalized as null, while
inapplicable type fields and expired effects are omitted by the adapter.
"""
from copy import deepcopy

from .dsl import agent, world, intent, submit, advance, snapshot, check, case
from .enclosures import with_gate_enclosures


def infection(duration="300", onset="0"):
    return {"onset_at": onset, "incubation_duration": duration}


def inventory(food=0, medical=0, material=0):
    return {"FOOD": food, "MEDICAL_SUPPLY": medical, "MATERIAL": material}


def stock(id="s", x="10", y="10", food=0, medical=0, material=0):
    return {"id": id, "x": x, "y": y, "stock": inventory(food, medical, material)}


def barrier(id="g", kind="Gate", rect=None, mode="CLOSED", integrity=200):
    value = {"id": id, "kind": kind, "rect": rect or ["10", "9", "10.2", "11"]}
    if kind != "Obstacle":
        value.update(integrity=integrity, max_integrity=200 if kind == "Gate" else 100)
    if kind == "Gate":
        value["mode"] = mode
    if kind == "Barricade":
        value["creator_id"] = "e"
    return value


def path(*points):
    return [{"x": str(x), "y": str(y), "offset": str(t)} for x, y, t in points]


def observe(actor, label):
    return {"op": "observe", "actor": actor, "label": label}


def draw(intent_id, channel="hit", value="0"):
    return {"intent": intent_id, "channel": channel, "value": value}


def state(label, id, field):
    return f"/snapshots/{label}/agents/{id}/{field}"


def num(label, id, field, value):
    return check(state(label, id, field), value, "numeric_eq")


def result(id, value):
    return check(f"/occurrences/{id}/result", value)


def lifecycle_cases():
    out = []
    out.append(case(
        "LIF_transmission_and_reexposure", ["V05", "V06", "V16", "V18"],
        world(agent("h", life=80), agent("z", "Zombie", x="11")),
        [advance("38.5"), submit("bite1", "z", "bite", "h"), advance("40"), snapshot("first"),
         advance("68.5"), submit("bite2", "z", "bite", "h"), advance("70"), snapshot()],
        [num("first", "h", "life", 74), num("end", "h", "life", 68),
         check(state("end", "h", "status"), "INFECTED"),
         check("/snapshots/end/episodes/*", 1, "count"),
         check("/snapshots/end/episodes/*/onset_at", "40", "numeric_eq"),
         check("/snapshots/end/episodes/*/conversion_due_at", "340", "numeric_eq"),
         check("/random_draws/*", 1, "count", where={"channel": "infection"}),
         check("/random_draws/*", "0.36", "numeric_eq", where={"channel": "infection"}, field="probability")],
        actions=["bite"], source=["ontology §§6.2,12,17.2 case A"],
        draws=[draw("bite1"), draw("bite1", "infection"), draw("bite2")]))
    out.append(case(
        "LIF_cure_then_new_episode", ["V05", "V06", "V18"],
        world(agent("d", role="DOCTOR", inventory=inventory(medical=1)),
              agent("h", x="10.5", life=60, infection=infection()), agent("z", "Zombie", x="11")),
        [submit("cure", "d", "treat_infection", "h"), advance("4"), snapshot("cured"),
         submit("bite", "z", "bite", "h"), advance("5.5"), snapshot(), advance("300"), snapshot("old_deadline")],
        [check(state("cured", "h", "status"), "HEALTHY"), num("cured", "h", "life", 60),
         check(state("cured", "h", "infection_episode"), None), num("end", "h", "life", 54),
         check(state("end", "h", "status"), "INFECTED"),
         check("/snapshots/end/episodes/*", 2, "count"),
         check("/snapshots/end/episodes/*/outcome", ["CURED", "ONGOING"], "set_eq"),
         check("/snapshots/end/episodes/*", "305.5", "numeric_eq", where={"outcome": "ONGOING"}, field="conversion_due_at"),
         check(state("end", "d", "inventory/MEDICAL_SUPPLY"), 0),
         check(state("old_deadline", "h", "type"), "Human"),
         check(state("old_deadline", "h", "status"), "INFECTED"), num("old_deadline", "h", "life", 54)],
        actions=["treat_infection", "bite"], source=["ontology §§6.2–6.4,13.1,17.2 case B"],
        draws=[draw("bite"), draw("bite", "infection")]))
    for duration, expected, status, medicine in [
        ("4", "FAILED_PRECONDITION", "ACTIVE", 1),
        ("4.000000001", "SUCCEEDED", "HEALTHY", 0),
    ]:
        out.append(case(
            "LIF_cure_deadline_" + duration.replace(".", "_"), ["V06", "V07", "V13", "V22"],
            world(agent("d", role="DOCTOR", inventory=inventory(medical=1)),
                  agent("h", x="11", life=64, stamina="32", infection=infection(duration))),
            [submit("cure", "d", "treat_infection", "h"), advance("4"), snapshot()],
            [result("cure", expected), check(state("end", "h", "status"), status),
             num("end", "h", "life", 64), num("end", "h", "stamina", "32"),
             num("end", "d", "stamina", "94"),
             check(state("end", "d", "inventory/MEDICAL_SUPPLY"), medicine),
             check(state("end", "d", "reserved/MEDICAL_SUPPLY"), 0)],
            actions=["treat_infection"], source=["ontology §§6.4,13.1,14.1,17.2 case C"]))
    out.append(case(
        "LIF_conversion_atomic_cleanup", ["V01", "V07", "V08", "V10", "V12", "V22", "V25"],
        world(agent("h", role="DOCTOR", life=64, stamina="32", infection=infection("3"),
                    inventory=inventory(food=2, medical=1), model_memory={"human_secret": 77})),
        [submit("rest", "h", "rest", duration="5"), advance("3"), snapshot(), advance("30"), snapshot("later")],
        [result("rest", "CANCELLED_BY_CONVERSION"), check(state("end", "h", "type"), "Zombie"),
         check(state("end", "h", "role"), None), num("end", "h", "life", 64),
         num("end", "h", "stamina", "44"), num("end", "h", "x", "10"),
         check(state("end", "h", "inventory"), op="absent"),
         check(state("end", "h", "hunger"), op="absent"),
         check(state("end", "h", "model_memory/human_secret"), op="absent"),
         check(state("end", "h", "model_assignment/model_id"), "ZombieDefaultModel"),
         check(state("end", "h", "active_action"), None),
         check("/snapshots/end/stockpiles/*/stock/FOOD", 2, "sum_eq"),
         check("/snapshots/end/stockpiles/*/stock/MEDICAL_SUPPLY", 1, "sum_eq"),
         check("/snapshots/later/stockpiles/*", 1, "count"),
         check("/snapshots/end/episodes/*/outcome", "CONVERTED"),
         num("later", "h", "stamina", "44")],
        actions=["rest"], source=["ontology §§6.4,8.2,14.1"]))
    out.append(case(
        "LIF_conversion_releases_foreign_reservation", ["V07", "V12", "V13"],
        world(agent("h", infection=infection("0.5"), inventory=inventory(food=2)),
              stockpiles=[stock(medical=1)]),
        [submit("pick", "h", "pickup", "s", resource_type="MEDICAL_SUPPLY", quantity=1),
         snapshot("reserved"), advance("1"), snapshot()],
        [check("/snapshots/reserved/stockpiles/s/reserved/MEDICAL_SUPPLY", 1),
         result("pick", "CANCELLED_BY_CONVERSION"),
         check("/snapshots/end/stockpiles/s/stock/MEDICAL_SUPPLY", 1),
         check("/snapshots/end/stockpiles/s/reserved/MEDICAL_SUPPLY", 0),
         check("/snapshots/end/stockpiles/*/stock/MEDICAL_SUPPLY", 1, "sum_eq"),
         check("/snapshots/end/stockpiles/*/stock/FOOD", 2, "sum_eq"),
         num("end", "h", "stamina", "99")], actions=["pickup"],
        source=["ontology §§6.4,9.2,17.2 case F"]))
    for infected in [False, True]:
        h = agent("h", life=5, inventory=inventory(food=2), **({"infection": infection("2")} if infected else {}))
        out.append(case(
            "LIF_lethal_bite_" + ("infected" if infected else "healthy"),
            ["V04", "V06", "V12", "V13", "V17", "V18", "V21"],
            world(h, agent("z", "Zombie", x="11")),
            [{"op": "submit_batch", "intents": [intent("eat", "h", "eat"), intent("bite", "z", "bite", "h")]},
             advance("1.5"), snapshot("death"), advance("301"), snapshot()],
            [check(state("death", "h", "status"), "DEAD"), check(state("end", "h", "type"), "Human"),
             num("end", "h", "life", 0), num("end", "h", "x", "10"),
             check(state("end", "h", "active_action"), None), check(state("end", "h", "role"), None),
             check(state("end", "h", "model_assignment"), None), check(state("end", "h", "infection_episode"), None),
             check(state("end", "h", "inventory/FOOD"), 0),
             check("/snapshots/end/stockpiles/*/stock/FOOD", 2, "sum_eq"),
             check("/snapshots/end/remains/*", 1, "count"), check("/snapshots/end/remains/*/biomass", 4),
             check("/random_draws/*", 0, "count", where={"channel": "infection"}),
             result("eat", "CANCELLED_BY_DEATH"),
             check("/snapshots/end/episodes/*", 1 if infected else 0, "count")]
            + ([check("/snapshots/end/episodes/*/outcome", "HOST_DIED")] if infected else []),
            actions=["eat", "bite"], source=["ontology §§6.5,9.2,17.2 case D"], draws=[draw("bite")]))
    out.append(case(
        "LIF_dead_identity_never_acts_or_heals", ["V04", "V09", "V21"],
        world(agent("h", life=5), agent("z", "Zombie", x="11"),
              agent("d", role="DOCTOR", x="10.5", inventory=inventory(medical=1))),
        [submit("claw", "z", "claw", "h"), advance("1"),
         submit("wait", "h", "wait", duration="1"), submit("aid", "d", "first_aid", "h"),
         advance("5"), snapshot()],
        [check("/intents/wait/status", "REJECTED"), check("/intents/aid/status", "REJECTED"),
         num("end", "h", "life", 0), num("end", "d", "stamina", "100"),
         check(state("end", "d", "inventory/MEDICAL_SUPPLY"), 1), check("/snapshots/end/remains/*", 1, "count")],
        actions=["claw", "wait", "first_aid"], source=["ontology §§6.5,9.2"], draws=[draw("claw")]))
    out.append(case(
        "LIF_nonlethal_damage_does_not_interrupt_rest", ["V10", "V11", "V22"],
        world(agent("h", stamina="10"), agent("z", "Zombie", x="11")),
        [{"op": "submit_batch", "intents": [intent("rest", "h", "rest", duration="5"), intent("claw", "z", "claw", "h")]},
         advance("1"), snapshot("hit"), advance("5"), snapshot()],
        [num("hit", "h", "life", 86), num("hit", "h", "stamina", "14"),
         check(state("hit", "h", "active_action"), "rest"), num("end", "h", "stamina", "30"),
         result("rest", "SUCCEEDED")], actions=["rest", "claw"],
        source=["ontology §§9.2,10"], draws=[draw("claw")]))
    out.append(case(
        "LIF_hunger_saturation_and_recurrence", ["V11", "V22", "V25"], world(agent()),
        [advance("1599"), snapshot("before"), advance("1600"), snapshot("saturated"),
         advance("1610"), snapshot("tick1"), advance("1620"), snapshot()],
        [num("before", "h", "hunger", "99.95"), num("before", "h", "life", 100),
         num("saturated", "h", "hunger", "100"), num("saturated", "h", "starvation_started_at", "1600"),
         num("saturated", "h", "next_starvation_damage_at", "1610"),
         num("tick1", "h", "life", 99), num("end", "h", "life", 98),
         num("end", "h", "next_starvation_damage_at", "1630")], source=["ontology §§5.1,14.1,17.2 case J"]))
    out.append(case(
        "LIF_starvation_bypasses_armor_and_rest", ["V11", "V17", "V22"],
        world(agent("h", role="WARRIOR", hunger="100", life=2, stamina="0")),
        [submit("rest", "h", "rest", duration="5"), advance("10"), snapshot()],
        [num("end", "h", "life", 1), num("end", "h", "stamina", "20"),
         num("end", "h", "hunger", "100"), result("rest", "SUCCEEDED")],
        actions=["rest"], source=["ontology §§5.1,6.5,10"]))
    for start, dead in [("7", False), ("8", True)]:
        out.append(case(
            "LIF_food_before_or_at_lethal_tick_" + start, ["V04", "V11", "V13", "V22"],
            world(agent("h", hunger="100", life=1, inventory=inventory(food=1))),
            [advance(start), submit("eat", "h", "eat"), advance("10"), snapshot()],
            [result("eat", "CANCELLED_BY_DEATH" if dead else "SUCCEEDED"),
             num("end", "h", "life", 0 if dead else 1),
             check(state("end", "h", "status"), "DEAD" if dead else "HEALTHY")]
            + ([check("/snapshots/end/stockpiles/*/stock/FOOD", 1, "sum_eq")] if dead else
               [num("end", "h", "hunger", "60.05"), check(state("end", "h", "next_starvation_damage_at"), None)]),
            actions=["eat"], source=["ontology §§5.1,11,14.1,17.2 case J"]))
    for start, damage in [("3.9", 6), ("4", 11)]:
        out.append(case(
            "LIF_guard_expiry_" + start.replace(".", "_"), ["V17", "V22", "V25"],
            world(agent("h", role="WARRIOR"), agent("z", "Zombie", x="11")),
            [submit("guard", "h", "guard"), advance(start), submit("claw", "z", "claw", "h"),
             advance("4.9" if start == "3.9" else "5"), snapshot()],
            [num("end", "h", "life", 100 - damage), result("claw", "SUCCEEDED")],
            actions=["guard", "claw"], source=["ontology §§4.1,6.5,13.2,14.1"], draws=[draw("claw")]))
    for start, probability, infected in [("122", "0.09", False), ("122.5", "0.36", True)]:
        out.append(case(
            "LIF_prophylaxis_expiry_" + start.replace(".", "_"), ["V05", "V16", "V22", "V25"],
            world(agent("d", role="DOCTOR", x="10.5", inventory=inventory(medical=1)),
                  agent("h"), agent("z", "Zombie", x="11")),
            [submit("protect", "d", "prophylaxis", "h"), advance(start),
             submit("bite", "z", "bite", "h"), advance("123.5" if start == "122" else "124"), snapshot()],
            [num("end", "h", "life", 94), check(state("end", "h", "status"), "INFECTED" if infected else "HEALTHY"),
             check("/random_draws/*", probability, "approx", where={"channel": "infection"}, field="probability")],
            actions=["prophylaxis", "bite"], source=["ontology §§4.1,6.2,13.1,14.1"],
            draws=[draw("bite"), draw("bite", "infection", "0.2")]))
    out.append(case(
        "LIF_prophylaxis_refresh_not_sum", ["V22", "V25"],
        world(agent("d1", role="DOCTOR", inventory=inventory(medical=1)),
              agent("d2", role="DOCTOR", x="10.5", inventory=inventory(medical=1)), agent("h", x="11")),
        [submit("p1", "d1", "prophylaxis", "h"), advance("6"), submit("p2", "d2", "prophylaxis", "h"),
         advance("125"), snapshot("active"), advance("130"), snapshot()],
        [num("active", "h", "infection_resistance_effective", "0.8"),
         check(state("active", "h", "effects/prophylaxis/end_at"), "130", "numeric_eq"),
         check(state("end", "h", "effects/prophylaxis"), op="absent"),
         num("end", "h", "infection_resistance_effective", "0.2")],
        actions=["prophylaxis"], source=["ontology §§4.1,13.1"]))
    out.append(case(
        "LIF_rally_survives_emitter_death", ["V04", "V21", "V22", "V25"],
        world(agent("t", "Zombie", "TYRANT", life=1), agent("z", "Zombie", x="11"), agent("h", x="9")),
        [submit("rally", "t", "rally"), advance("2"), submit("kill", "h", "melee", "t"),
         advance("3"), snapshot("after_death"), advance("12"), snapshot()],
        [check(state("after_death", "t", "status"), "DEAD"),
         check(state("after_death", "z", "effects/rallied/magnitude"), "0.1", "numeric_eq"),
         check(state("after_death", "z", "effects/rallied/end_at"), "12", "numeric_eq"),
         check(state("end", "z", "effects/rallied"), op="absent")],
        actions=["rally", "melee"], source=["ontology §§4.1,13.5"], draws=[draw("kill")]))
    out.append(case(
        "LIF_role_retirement_cancels_role_action", ["V08", "V10", "V13", "V25"],
        world(agent("h", role="WARRIOR", life=70), agent("z", "Zombie", x="11")),
        [submit("strike", "h", "power_strike", "z"),
         {"op": "intervene", "id": "retire", "at": "1", "change": {"kind": "replace_role", "agent": "h", "role": None}},
         advance("2"), snapshot()],
        [result("strike", "CANCELLED_BY_INTERVENTION"), check(state("end", "h", "role"), None),
         num("end", "h", "life", 70), num("end", "h", "stamina", "85"),
         num("end", "h", "combat_skill", "0.35"), num("end", "h", "damage_resistance", "0"),
         num("end", "z", "life", 100)],
        actions=["power_strike"], source=["ontology §§7.1,16.3"], config={"interventions_enabled": True}))
    out.append(case(
        "LIF_capacity_role_loss_drops_exact_excess", ["V08", "V12", "V25"],
        world(agent("e", role="ENGINEER", life=70, stamina="30", inventory=inventory(food=10, material=6))),
        [{"op": "intervene", "id": "retire", "at": "1", "change": {
            "kind": "replace_role", "agent": "e", "role": None,
            "drop_order": ["MATERIAL", "FOOD", "MEDICAL_SUPPLY"]}}, advance("1"), snapshot()],
        [num("end", "e", "carry_capacity", 10), check(state("end", "e", "inventory/FOOD"), 10),
         check(state("end", "e", "inventory/MATERIAL"), 0),
         check("/snapshots/end/stockpiles/*/stock/MATERIAL", 6, "sum_eq"),
         num("end", "e", "life", 70), num("end", "e", "stamina", "30")],
        source=["ontology §§7.1,16.3"], config={"interventions_enabled": True}))
    out.append(case(
        "LIF_starvation_death_precedes_same_time_conversion", ["V04", "V06", "V18", "V22"],
        world(agent("h", life=1, hunger="100", infection=infection("10"))),
        [advance("10"), snapshot(), advance("20"), snapshot("later")],
        [check(state("end", "h", "type"), "Human"), check(state("end", "h", "status"), "DEAD"),
         check("/snapshots/end/episodes/*/outcome", "HOST_DIED"),
         check("/snapshots/end/episodes/*/ended_at", "10", "numeric_eq"),
         check(state("later", "h", "type"), "Human"), check("/snapshots/later/remains/*", 1, "count")],
        source=["ontology §§6.5,14.1"]))
    out.append(case(
        "LIF_role_retirement_ends_incompatible_effect", ["V08", "V22", "V25"], world(agent("h", role="WARRIOR")),
        [submit("guard", "h", "guard"),
         {"op": "intervene", "id": "retire", "at": "2", "change": {"kind": "replace_role", "agent": "h", "role": None}},
         advance("2"), snapshot()],
        [check(state("end", "h", "role"), None), check(state("end", "h", "effects/guard"), op="absent"),
         num("end", "h", "damage_resistance", "0"), num("end", "h", "stamina", "92")],
        actions=["guard"], source=["ontology §§4.1,7.1,16.3"], config={"interventions_enabled": True}))
    out.append(case(
        "LIF_model_replacement_explicit_memory_reset", ["V08", "V24"],
        world(agent("h", role="ENGINEER", life=77, stamina="31", model_memory={"private_token": 777})),
        [{"op": "intervene", "id": "replace", "at": "1", "change": {
            "kind": "replace_model", "agent": "h", "model_id": "HumanDefaultModel", "model_version": "1", "memory_policy": "reset"}},
         advance("1"), snapshot()],
        [check(state("end", "h", "model_memory/private_token"), op="absent"),
         check(state("end", "h", "model_assignment/model_id"), "HumanDefaultModel"),
         check(state("end", "h", "role"), "ENGINEER"), num("end", "h", "life", 77), num("end", "h", "stamina", "31")],
        source=["ontology §§8.2,16.3", "TASK 2 plan §11"], config={"interventions_enabled": True}))
    population = [agent(f"healthy{i}") for i in range(777)]
    population += [agent(f"starving{i}", hunger="100", life=1) for i in range(3)]
    population += [agent(f"infected{i}", infection=infection("10" if i < 5 else "300")) for i in range(20)]
    population += [agent(f"zombie{i}", "Zombie") for i in range(200)]
    out.append(case(
        "LIF_worked_population_accounting_K", ["V01", "V03", "V04", "V05", "V07", "V21"], world(*population),
        [snapshot("initial"), advance("10"), snapshot()],
        [check("/snapshots/initial/agents/*", 1000, "count"),
         check("/snapshots/initial/agents/*", 780, "count", where={"status": "HEALTHY"}),
         check("/snapshots/initial/agents/*", 20, "count", where={"status": "INFECTED"}),
         check("/snapshots/initial/agents/*", 200, "count", where={"status": "ACTIVE"}),
         check("/snapshots/end/agents/*", 1000, "count"),
         check("/snapshots/end/agents/*", 777, "count", where={"status": "HEALTHY"}),
         check("/snapshots/end/agents/*", 15, "count", where={"status": "INFECTED"}),
         check("/snapshots/end/agents/*", 205, "count", where={"status": "ACTIVE"}),
         check("/snapshots/end/agents/*", 3, "count", where={"status": "DEAD"}),
         check("/snapshots/end/remains/*", 3, "count"), check("/snapshots/end/remains/*/biomass", 12, "sum_eq"),
         check("/snapshots/end/episodes/*", 5, "count", where={"outcome": "CONVERTED"})],
        source=["ontology §§6,17.2 case K"], tier="integration",
        description="Controlled coincident positions are legal; this checks population identity accounting, not baseline placement."))
    return out


def conflict_resource_cases():
    out = []
    out.append(case(
        "CON_first_valid_winner_miss_cancels_other", ["V10", "V16", "V19"],
        world(agent("h"), agent("z", "Zombie", x="11")),
        [{"op": "submit_batch", "intents": [intent("melee", "h", "melee", "z"), intent("bite", "z", "bite", "h")]},
         advance("1.5"), snapshot()],
        [result("melee", "MISSED"), result("bite", "CANCELLED_BY_CONFLICT"),
         num("end", "h", "life", 100), num("end", "z", "life", 100),
         num("end", "h", "stamina", "94"), num("end", "z", "stamina", "90"),
         check(state("end", "z", "cooldowns/bite"), "3", "numeric_eq"),
         check("/random_draws/*", 0, "count", where={"intent": "bite"})],
        actions=["melee", "bite"], source=["ontology §§14.2,17.2 case E"], draws=[draw("melee", value="0.99")]))
    out.append(case(
        "CON_equal_time_reciprocal_only_one_kills", ["V04", "V17", "V19", "V21"],
        world(agent("h", life=10), agent("z", "Zombie", x="11", life=10)),
        [{"op": "submit_batch", "intents": [intent("melee", "h", "melee", "z"), intent("claw", "z", "claw", "h")]},
         advance("1"), snapshot()],
        [check("/occurrences/*/result", ["SUCCEEDED", "CANCELLED_BY_DEATH"], "set_eq"),
         check("/snapshots/end/agents/*/life", 10, "sum_eq"),
         check("/snapshots/end/agents/*", 1, "count", where={"status": "DEAD"}),
         check("/snapshots/end/remains/*", 1, "count"),
         check("/random_draws/*", 1, "count", where={"channel": "hit"})],
        actions=["melee", "claw"], source=["ontology §§14.2,17.2 case E"], draws=[draw("melee"), draw("claw")]))
    out.append(case(
        "CON_invalid_first_attempt_does_not_win", ["V19", "V20", "V22"],
        world(agent("h", x="9.5"), agent("z", "Zombie", x="10.5"), agent("opener", x="9"),
              agent("t", "Zombie", "TYRANT", x="9"),
              barriers=[barrier(integrity=60)]),
        [{"op": "submit_batch", "intents": [intent("open", "opener", "open_gate", "g"), intent("break", "t", "demolish", "g")]},
         advance("1"), submit("close", "opener", "close_gate", "g"), advance("1.6"),
         {"op": "submit_batch", "intents": [intent("melee", "h", "melee", "z"), intent("bite", "z", "bite", "h")]},
         advance("2.6"), snapshot("blocked"), advance("3.1"), snapshot()],
        [result("melee", "FAILED_PRECONDITION"), result("bite", "SUCCEEDED"),
         check(state("blocked", "z", "active_action"), "bite"),
         check("/snapshots/end/barriers/g/mode", "BREACHED"), num("end", "h", "life", 94),
         num("end", "z", "life", 100), check("/random_draws/*", 0, "count", where={"intent": "melee"})],
        actions=["open_gate", "close_gate", "demolish", "melee", "bite"],
        source=["ontology §§14.2–14.3"], draws=[draw("bite"), draw("bite", "infection", "0.99")]))
    out.append(case(
        "CON_touching_attack_intervals_are_sequential", ["V10", "V19"],
        world(agent("h"), agent("z", "Zombie", x="11")),
        [submit("melee", "h", "melee", "z"), advance("1"), submit("claw", "z", "claw", "h"), advance("2"), snapshot()],
        [result("melee", "SUCCEEDED"), result("claw", "SUCCEEDED"),
         num("end", "h", "life", 86), num("end", "z", "life", 84)],
        actions=["melee", "claw"], source=["ontology §14.2"], draws=[draw("melee"), draw("claw")]))
    out.append(case(
        "CON_busy_actor_cannot_admit_second_action", ["V10", "V11"], world(agent("h", stamina="50")),
        [submit("rest", "h", "rest", duration="2"), advance("1"),
         submit("move", "h", "move", duration="1", path=path((10, 10, 0), (12, 10, 1))), advance("2"), snapshot()],
        [check("/intents/move/status", "REJECTED"), result("rest", "SUCCEEDED"),
         num("end", "h", "stamina", "58"), num("end", "h", "x", "10")],
        actions=["rest", "move"], source=["ontology §9.2"]))
    out.append(case(
        "RES_simultaneous_single_item_claim", ["V12", "V13", "V24"],
        world(agent("a"), agent("b", x="11"), stockpiles=[stock(x="10.5", food=1)]),
        [{"op": "submit_batch", "intents": [intent("a", "a", "pickup", "s", resource_type="FOOD", quantity=1),
                                               intent("b", "b", "pickup", "s", resource_type="FOOD", quantity=1)]},
         snapshot("reserved"), advance("1"), snapshot()],
        [check("/intents/*/status", ["ADMITTED", "REJECTED"], "set_eq"),
         check("/snapshots/reserved/stockpiles/s/stock/FOOD", 1), check("/snapshots/reserved/stockpiles/s/reserved/FOOD", 1),
         check("/snapshots/end/agents/*/stamina", "199", "sum_eq"),
         check("/snapshots/end/agents/*/inventory/FOOD", 1, "sum_eq"),
         check("/snapshots/end/stockpiles/s/stock/FOOD", 0), check("/snapshots/end/stockpiles/s/reserved/FOOD", 0)],
        actions=["pickup"], source=["ontology §§14.3,17.2 case F"]))
    out.append(case(
        "RES_two_transfers_one_capacity_slot", ["V12", "V13"],
        world(agent("a", inventory=inventory(food=1)), agent("b", inventory=inventory(food=1)),
              agent("r", x="11", inventory=inventory(food=9))),
        [{"op": "submit_batch", "intents": [intent("a", "a", "transfer", "r", resource_type="FOOD", quantity=1),
                                               intent("b", "b", "transfer", "r", resource_type="FOOD", quantity=1)]}, advance("1"), snapshot()],
        [check("/occurrences/*/result", ["SUCCEEDED", "FAILED_PRECONDITION"], "set_eq"),
         check(state("end", "r", "inventory/FOOD"), 10),
         check("/snapshots/end/agents/*/inventory/FOOD", 11, "sum_eq"),
         check("/snapshots/end/agents/*/reserved/FOOD", 0, "sum_eq")],
        actions=["transfer"], source=["ontology §§9.2,14.3"]))
    for action, duration, health, infected in [("treat_infection", "4", 60, True), ("first_aid", "3", 99, False)]:
        out.append(case(
            "RES_competing_" + action, ["V06", "V12", "V13", "V17"],
            world(agent("d1", role="DOCTOR", inventory=inventory(medical=1)),
                  agent("d2", role="DOCTOR", inventory=inventory(medical=1)),
                  agent("h", x="11", life=health, **({"infection": infection()} if infected else {}))),
            [{"op": "submit_batch", "intents": [intent("one", "d1", action, "h"), intent("two", "d2", action, "h")]},
             advance(duration), snapshot()],
            [check("/occurrences/*/result", ["SUCCEEDED", "FAILED_PRECONDITION"], "set_eq"),
             check("/snapshots/end/agents/*/inventory/MEDICAL_SUPPLY", 1, "sum_eq"),
             check("/snapshots/end/agents/*/reserved/MEDICAL_SUPPLY", 0, "sum_eq"),
             num("end", "h", "life", health if infected else 100),
             check(state("end", "h", "status"), "HEALTHY")],
            actions=[action], source=["ontology §§11,13.1,14.3"]))
    out.append(case(
        "RES_first_aid_does_not_cure", ["V05", "V06", "V17"],
        world(agent("d", role="DOCTOR", inventory=inventory(medical=1)), agent("h", x="11", life=50, infection=infection())),
        [submit("aid", "d", "first_aid", "h"), advance("3"), snapshot()],
        [num("end", "h", "life", 78), check(state("end", "h", "status"), "INFECTED"),
         check("/snapshots/end/episodes/*/outcome", "ONGOING"),
         check("/snapshots/end/episodes/*/conversion_due_at", "300", "numeric_eq")],
        actions=["first_aid"], source=["ontology §§11,17.2 case I"]))
    out.append(case(
        "RES_feeders_compete_for_one_biomass", ["V04", "V13", "V21"],
        world(agent("dead", life=0, death_at="0", death_cause="initial_condition"),
              agent("a", "Zombie", x="10.5", life=50), agent("b", "Zombie", x="11", life=50),
              remains=[{"id": "r", "source_agent": "dead", "x": "10", "y": "10", "biomass": 1}]),
        [{"op": "submit_batch", "intents": [intent("one", "a", "feed", "r"), intent("two", "b", "feed", "r")]},
         advance("3"), snapshot()],
        [check("/intents/*/status", ["ADMITTED", "REJECTED"], "set_eq"),
         check("/snapshots/end/agents/*/life", 108, "sum_eq"),
         check("/snapshots/end/remains/r/biomass", 0), num("end", "dead", "life", 0)],
        actions=["feed"], source=["ontology §§12,14.3"]))
    out.append(case(
        "RES_cooldown_boundary_is_inclusive", ["V10", "V16"],
        world(agent("h"), agent("z", "Zombie", x="11")),
        [submit("first", "h", "melee", "z"), advance("1.999999999"),
         submit("early", "h", "melee", "z"), advance("2"), submit("second", "h", "melee", "z"), advance("3"), snapshot()],
        [check("/intents/early/status", "REJECTED"), result("second", "SUCCEEDED"),
         num("end", "h", "stamina", "88"), num("end", "z", "life", 68)],
        actions=["melee"], source=["ontology §9.2"], draws=[draw("first"), draw("second")]))
    return out


def geometry_cases():
    out = []
    for name, points in [
        ("wall_crossing", path((9, 10, 0), (11, 10, 1))),
        ("wall_boundary_tangent", path((9, 9, 0), (11, 9, 1))),
    ]:
        out.append(case(
            "GEO_" + name, ["V02", "V14"],
            world(agent("h", x=points[0]["x"], y=points[0]["y"]),
                  barriers=[barrier(kind="Obstacle", rect=["9.8", "9", "10.2", "11"])]),
            [submit("move", "h", "move", duration="1", path=points), advance("1"), snapshot()],
            [check("/intents/move/status", "REJECTED"), num("end", "h", "x", "9"),
             num("end", "h", "stamina", "100")], actions=["move"],
            source=["ontology §§3.1,10,17.2 case G"]))
    out.append(case(
        "GEO_per_segment_speed_not_average", ["V14"], world(agent()),
        [submit("move", "h", "move", duration="1", path=path((10, 10, 0), (12, 10, ".25"), (12, 10, 1))),
         advance("1"), snapshot()],
        [check("/intents/move/status", "REJECTED"), num("end", "h", "stamina", "100")],
        actions=["move"], source=["ontology §§3.1,10,14.1"]))
    out.append(case(
        "GEO_outer_boundary_and_overlapping_agents_are_legal", ["V02", "V14"],
        world(agent("h", x="0", y="0"), agent("other", x="1", y="0")),
        [submit("move", "h", "move", duration="1", path=path((0, 0, 0), (2, 0, 1))),
         advance(".5"), snapshot("overlap"), advance("1"), snapshot()],
        [num("overlap", "h", "x", "1"), num("overlap", "other", "x", "1"),
         num("end", "h", "x", "2"), num("end", "h", "stamina", "99.8"), result("move", "SUCCEEDED")],
        actions=["move"], source=["ontology §§3.1,10"]))
    out.append(case(
        "GEO_continuous_position_and_energy", ["V11", "V14", "V22"], world(agent()),
        [submit("move", "h", "move", duration="2", path=path((10, 10, 0), (14, 10, 2))),
         advance("1"), snapshot("middle"), advance("2"), snapshot()],
        [num("middle", "h", "x", "12"), num("middle", "h", "stamina", "99.8"),
         num("end", "h", "x", "14"), num("end", "h", "stamina", "99.6"), result("move", "SUCCEEDED")],
        actions=["move"], source=["ontology §§10,14.1"]))
    out.append(case(
        "GEO_newly_closed_gate_stops_before_contact", ["V02", "V11", "V14", "V20", "V22"],
        world(agent("h"), agent("closer", x="14.5"),
              barriers=[barrier(rect=["13", "9", "14", "11"], mode="OPEN")]),
        [{"op": "submit_batch", "intents": [intent("move", "h", "move", duration="4",
             path=path((10, 10, 0), (18, 10, 4))), intent("close", "closer", "close_gate", "g")]},
         advance("4"), snapshot()],
        [result("close", "SUCCEEDED"), result("move", "PARTIAL_BLOCKED"),
         num("end", "h", "x", "12.99"), num("end", "h", "stamina", "99.701"),
         check("/snapshots/end/barriers/g/mode", "CLOSED")],
        actions=["move", "close_gate"], source=["ontology §§3.2,10,14.1"]))
    out.append(case(
        "GEO_moving_occupant_prevents_gate_closure", ["V02", "V14", "V20", "V22"],
        world(agent("h", x="8"), agent("closer", x="9", y="11.5"),
              barriers=[barrier(rect=["9.9", "9", "10.1", "11"], mode="OPEN")]),
        [{"op": "submit_batch", "intents": [intent("move", "h", "move", duration="1",
             path=path((8, 10, 0), (10, 10, 1))), intent("close", "closer", "close_gate", "g")]},
         advance("1"), snapshot()],
        [result("move", "SUCCEEDED"), result("close", "FAILED_PRECONDITION"),
         num("end", "h", "x", "10"), num("end", "closer", "stamina", "99"),
         check("/snapshots/end/barriers/g/mode", "OPEN")],
        actions=["move", "close_gate"], source=["ontology §§3.2,10,14.1"]))
    out.append(case(
        "GEO_death_freezes_interpolated_trajectory", ["V04", "V11", "V14", "V21", "V22"],
        world(agent("h", life=1), agent("z", "Zombie", x="11")),
        [{"op": "submit_batch", "intents": [intent("move", "h", "move", duration="2",
             path=path((10, 10, 0), (14, 10, 2))), intent("claw", "z", "claw", "h")]},
         advance("5"), snapshot()],
        [result("move", "CANCELLED_BY_DEATH"), num("end", "h", "x", "12"),
         num("end", "h", "stamina", "99.8"), check(state("end", "h", "status"), "DEAD"),
         check("/snapshots/end/remains/*/x", "12", "numeric_eq"),
         check("/snapshots/end/remains/*/biomass", 4)],
        actions=["move", "claw"], source=["ontology §§6.5,10,12,14.1"], draws=[draw("claw")]))
    for resource, amount in [("stock", 1), ("stock", 0), ("remains", 1), ("remains", 0)]:
        setup = world(agent("e", role="ENGINEER", inventory=inventory(material=2)))
        if resource == "stock":
            setup["stockpiles"] = [stock(x="11.5", food=amount)]
        else:
            setup["agents"].append(agent("dead", life=0, x="11.5", death_at="0", death_cause="initial_condition"))
            setup["remains"] = [{"id": "r", "source_agent": "dead", "x": "11.5", "y": "10", "biomass": amount}]
        out.append(case(
            f"GEO_build_{resource}_quantity_{amount}", ["V12", "V13", "V20", "V21"], setup,
            [submit("build", "e", "build_barricade", center=["11.5", "10"], orientation="y", length="2"),
             advance("8"), snapshot()],
            [check("/intents/build/status", "REJECTED" if amount else "ADMITTED"),
             check("/snapshots/end/barriers/*", 0 if amount else 1, "count"),
             check(state("end", "e", "inventory/MATERIAL"), 2 if amount else 0),
             num("end", "e", "stamina", "100" if amount else "88")],
            actions=["build_barricade"], source=["ontology §§3.2,13.4"]))
    out.append(case(
        "GEO_build_allows_shared_wall_edge", ["V02", "V20"],
        world(agent("e", role="ENGINEER", inventory=inventory(material=2)),
              barriers=[barrier("wall", "Obstacle", rect=["12", "9", "13", "11"])]),
        [submit("build", "e", "build_barricade", center=["11.5", "10"], orientation="y", length="2"),
         advance("8"), snapshot()],
        [result("build", "SUCCEEDED"), check("/snapshots/end/barriers/*", 2, "count"),
         check(state("end", "e", "inventory/MATERIAL"), 0)],
        actions=["build_barricade"], source=["ontology §§3.2,13.4"]))
    for mode in ["OPEN", "BREACHED", "CLOSED"]:
        out.append(case(
            "GEO_barricade_over_gate_" + mode.lower(), ["V02", "V20"],
            world(agent("e", role="ENGINEER", inventory=inventory(material=2)),
                  barriers=[barrier(rect=["11", "9", "12", "11"], mode=mode, integrity=0 if mode == "BREACHED" else 200)]),
            [submit("build", "e", "build_barricade", center=["11.5", "10"], orientation="y", length="2"),
             advance("8"), snapshot()],
            [check("/intents/build/status", "REJECTED" if mode == "CLOSED" else "ADMITTED"),
             check("/snapshots/end/barriers/*", 4 if mode == "CLOSED" else 5, "count")],
            actions=["build_barricade"], source=["ontology §§3.2,13.4"]))
    out.append(case(
        "GEO_repair_breached_gate_with_living_occupant_rejected", ["V20"],
        world(agent("e", role="ENGINEER", inventory=inventory(material=1)), agent("z", "Zombie", x="11.5"),
              barriers=[barrier(rect=["11", "9", "12", "11"], mode="BREACHED", integrity=0)]),
        [submit("repair", "e", "repair_barrier", "g"), advance("5"), snapshot()],
        [check("/intents/repair/status", "REJECTED"), check("/snapshots/end/barriers/g/integrity", 0),
         check(state("end", "e", "inventory/MATERIAL"), 1)],
        actions=["repair_barrier"], source=["ontology §§3.2,13.4"]))
    out.append(case(
        "GEO_intact_barricade_prevents_gate_closure", ["V20"],
        world(agent("e", role="ENGINEER"), barriers=[
            barrier(rect=["11", "9", "12", "11"], mode="OPEN"),
            barrier("b", "Barricade", rect=["11", "9", "12", "11"], integrity=100)]),
        [submit("close", "e", "close_gate", "g"), advance("1"), snapshot()],
        [check("/intents/close/status", "REJECTED"), check("/snapshots/end/barriers/g/mode", "OPEN")],
        actions=["close_gate"], source=["ontology §§3.2,11"]))
    out.append(case(
        "GEO_shelter_entry_does_not_grant_immunity", ["V02", "V14", "V15", "V18", "V20"],
        world(agent("h", x="11.5"), agent("z", "Zombie", x="8.5"),
              barriers=[barrier(rect=["10", "9", "10.2", "11"])]),
        [submit("open", "h", "open_gate", "g"), advance("1"),
         submit("enter", "z", "move", duration="2", path=path((8.5, 10, 0), (11, 10, 2))), advance("3"),
         submit("close", "h", "close_gate", "g"), advance("4"), observe("h", "inside"),
         submit("bite", "z", "bite", "h"), advance("5.5"), snapshot()],
        [result("enter", "SUCCEEDED"), result("close", "SUCCEEDED"),
         check("/observations/inside/local_agents/z/type", "Zombie"),
         check("/snapshots/end/barriers/g/mode", "CLOSED"), num("end", "h", "life", 94),
         check(state("end", "h", "status"), "INFECTED")],
        actions=["open_gate", "move", "close_gate", "bite"],
        source=["ontology §§3.1–3.2,11–12,17.2 case H"], draws=[draw("bite"), draw("bite", "infection")]))
    return out


def observation_cases():
    out = []
    for type_, boundary in [("Human", "50"), ("Zombie", "45")]:
        out.append(case(
            "OBS_sensing_boundary_" + type_.lower(), ["V15", "V25"],
            world(agent("viewer", type_), agent("at", x=boundary), agent("outside", x=str(int(boundary) + 1))),
            [observe("viewer", "view")],
            [check("/observations/view/local_agents/at/life", 100),
             check("/observations/view/local_agents/outside", op="absent")],
            source=["ontology §§3.4,4,8.1"]))
    for kind, mode, integrity, visible in [
        ("Obstacle", "CLOSED", 200, False), ("Gate", "CLOSED", 200, False),
        ("Gate", "OPEN", 200, True), ("Gate", "BREACHED", 0, True),
        ("Barricade", "CLOSED", 100, False), ("Barricade", "CLOSED", 0, True),
    ]:
        out.append(case(
            f"OBS_occlusion_{kind.lower()}_{mode.lower()}_{integrity}", ["V02", "V15", "V20"],
            world(agent("e", role="ENGINEER"), agent("target", "Zombie", x="11"),
                  barriers=[barrier("b", kind, rect=["10.4", "9.9", "10.6", "10.1"], mode=mode, integrity=integrity)]),
            [observe("e", "view")],
            [check("/observations/view/local_agents/target/type", "Zombie") if visible else
             check("/observations/view/local_agents/target", op="absent")],
            source=["ontology §§3.2,3.4,8.1"]))
    out.append(case(
        "OBS_bodies_resources_and_remains_do_not_occlude", ["V15", "V21"],
        world(agent("viewer"), agent("middle", x="11"), agent("target", "Zombie", x="12"),
              agent("dead", life=0, x="11", death_at="0", death_cause="initial_condition"),
              stockpiles=[stock(x="11", food=1)],
              remains=[{"id": "r", "source_agent": "dead", "x": "11", "y": "10", "biomass": 4}]),
        [observe("viewer", "view")],
        [check("/observations/view/local_agents/target/type", "Zombie"),
         check("/observations/view/local_agents/middle/type", "Human"),
         check("/observations/view/local_agents/dead", op="absent")],
        source=["ontology §§3.4,8.1"]))
    out.append(case(
        "OBS_signal_crosses_wall_with_opponent_redaction", ["V15"],
        world(agent("sender"), agent("ally", x="11"), agent("enemy", "Zombie", x="12"),
              barriers=[barrier("wall", "Obstacle", rect=["10.4", "9", "10.6", "11"])]),
        [submit("signal", "sender", "signal", kind="WARNING", payload={"position": ["10", "10"], "observed_at": "0"}),
         advance(".5"), observe("ally", "allied"), observe("enemy", "opposed"), snapshot()],
        [check("/observations/allied/local_agents/sender", op="absent"),
         check("/observations/allied/received_signals/*", 1, "count"),
         check("/observations/allied/received_signals/*/kind", "WARNING"),
         check("/observations/allied/received_signals/*/payload/observed_at", "0", "numeric_eq"),
         check("/observations/opposed/received_signals/*", 1, "count"),
         check("/observations/opposed/received_signals/*/kind", "NOISE"),
         check("/observations/opposed/received_signals/*/payload", op="absent"),
         check("/snapshots/end/signals/*/radius", "40", "numeric_eq")],
        actions=["signal"], source=["ontology §§3.4,8.1,10"]))
    out.append(case(
        "OBS_signal_expiry_and_delivery_once", ["V15", "V22"], world(agent("sender"), agent("ally", x="11")),
        [submit("signal", "sender", "signal", kind="WARNING", payload={"position": ["10", "10"], "observed_at": "0"}),
         advance(".5"), observe("ally", "first"), observe("ally", "repeat"),
         advance("8.499999999"), observe("ally", "before"), advance("8.5"), observe("ally", "expired")],
        [check("/observations/first/received_signals/*", 1, "count"),
         check("/observations/repeat/received_signals/*", 1, "count"),
         check("/observations/before/received_signals/*", 1, "count"),
         check("/observations/expired/received_signals/*", 0, "count")],
        actions=["signal"], source=["ontology §§3.4,8.1,10,14.1"]))
    out.append(case(
        "OBS_signal_late_entrant_gets_no_delivery", ["V15"], world(agent("sender"), agent("late", x="51")),
        [submit("signal", "sender", "signal", kind="WARNING", payload={"position": ["10", "10"], "observed_at": "0"}),
         advance(".5"), submit("enter", "late", "move", duration="1", path=path((51, 10, 0), (49, 10, 1))),
         advance("1.5"), observe("late", "inside")],
        [check("/observations/inside/received_signals/*", 0, "count"), result("enter", "SUCCEEDED")],
        actions=["signal", "move"], source=["ontology §§3.4,10"]))
    out.append(case(
        "OBS_emission_position_is_frozen", ["V15"], world(agent("sender"), agent("ally", x="11")),
        [submit("signal", "sender", "signal", kind="WARNING", payload={"position": ["10", "10"], "observed_at": "0"}),
         advance(".5"), submit("move", "sender", "move", duration="1", path=path((10, 10, 0), (12, 10, 1))),
         advance("1.5"), observe("ally", "later"), snapshot()],
        [num("end", "sender", "x", "12"),
         check("/observations/later/received_signals/*/position_at_emission/0", "10", "numeric_eq"),
         check("/observations/later/received_signals/*/emitted_at", ".5", "numeric_eq"),
         check("/observations/later/received_signals/*/payload/observed_at", "0", "numeric_eq")],
        actions=["signal", "move"], source=["ontology §§3.4,10"]))
    out.append(case(
        "OBS_sender_conversion_preserves_emission_type", ["V07", "V15"],
        world(agent("sender", infection=infection("1")), agent("ally", x="11")),
        [submit("signal", "sender", "signal", kind="WARNING", payload={"position": ["10", "10"], "observed_at": "0"}),
         advance("1"), observe("ally", "later"), snapshot()],
        [check(state("end", "sender", "type"), "Zombie"),
         check("/observations/later/received_signals/*/kind", "WARNING"),
         check("/observations/later/received_signals/*/sender_type_at_emission", "Human")],
        actions=["signal"], source=["ontology §§3.4,6.4,10"]))
    out.append(case(
        "OBS_mark_is_report_not_attack_authority", ["V09", "V15"],
        world(agent("h"), agent("s", role="SCOUT", x="10.5", y="11"), agent("z", "Zombie", x="11"),
              barriers=[barrier("wall", "Obstacle", rect=["10.4", "9.9", "10.6", "10.1"])]),
        [submit("mark", "s", "mark_target", "z"), advance(".5"), observe("h", "reported"),
         submit("attack", "h", "melee", "z"), advance("1.5"), snapshot()],
        [result("mark", "SUCCEEDED"), check("/observations/reported/local_agents/z", op="absent"),
         check("/observations/reported/received_signals/*", 1, "count"),
         check("/intents/attack/status", "REJECTED"), num("end", "h", "stamina", "100"),
         num("end", "z", "life", 100)],
        actions=["mark_target", "melee"], source=["ontology §§3.4,8.1,13.3"]))
    return out


def validation_cases():
    """Adapter diagnostics group errors; these names are not ontology classes."""
    out = []

    def invalid(name, setup, code, requirements, section, config=None):
        out.append(case(
            "VAL_" + name, requirements, setup, [],
            [check("/validation/valid", False), check("/validation/issues/*/code", code, "contains")],
            source=["ontology §" + section], kind="validation", config=config,
            description="Reject initialization; normalized diagnostic category " + code + "."))

    for axis in ["length", "width"]:
        for label, value in [("zero", "0"), ("negative", "-1"), ("nan", "NaN"), ("infinite", "Infinity")]:
            invalid(axis + "_" + label, world(agent(), **{axis: value}), "INVALID_DOMAIN", ["V02"], "3.1")
    for field, values in [
        ("life", [-1, 101, 1.5]), ("stamina", ["-0.01", "100.01", "NaN"]),
        ("hunger", ["-0.01", "100.01", "Infinity"]),
    ]:
        for index, value in enumerate(values):
            invalid(f"{field}_domain_{index}", world(agent(**{field: value})), "INVALID_DOMAIN", ["V03", "V11"], "4–5")
    for axis, value in [("x", "-0.01"), ("x", "100.01"), ("y", "-0.01"), ("y", "100.01")]:
        invalid(axis + "_outside_" + ("lower" if value.startswith("-") else "upper"), world(agent(**{axis: value})),
                "INVALID_GEOMETRY", ["V02"], "3.1")
    invalid("duplicate_agent_id", world(agent("same"), agent("same", "Zombie")), "DUPLICATE_ID", ["V01"], "2.2")
    invalid("incompatible_human_role", world(agent("h", role="TYRANT")), "INCOMPATIBLE_ROLE", ["V08"], "7")
    invalid("incompatible_zombie_role", world(agent("z", "Zombie", role="DOCTOR")), "INCOMPATIBLE_ROLE", ["V08"], "7")
    invalid("unknown_type", world(agent(type="Ghost")), "INVALID_TYPE_STATUS", ["V03"], "6.1")
    for type_, status in [("Human", "ACTIVE"), ("Zombie", "HEALTHY"), ("Zombie", "INFECTED")]:
        invalid(type_.lower() + "_status_" + status.lower(), world(agent(type=type_, status=status)),
                "INVALID_TYPE_STATUS", ["V03"], "6.1")
    invalid("living_status_zero_life", world(agent(life=0, status="HEALTHY")), "INVALID_TYPE_STATUS", ["V03", "V04"], "6.1")
    invalid("dead_status_positive_life", world(agent(life=1, status="DEAD")), "INVALID_TYPE_STATUS", ["V03", "V04"], "6.1")
    invalid("infected_without_episode", world(agent(status="INFECTED")), "INVALID_EPISODE", ["V05"], "6.2")
    invalid("healthy_with_episode", world(agent(status="HEALTHY", infection=infection())), "INVALID_EPISODE", ["V05"], "6.2")
    invalid("zombie_with_episode", world(agent(type="Zombie", infection=infection())), "INVALID_EPISODE", ["V05"], "6.2")
    for duration in ["0", "-1"]:
        invalid("incubation_" + ("zero" if duration == "0" else "negative"), world(agent(infection=infection(duration))),
                "INVALID_EPISODE", ["V06"], "6.2")
    for label, items, code in [
        ("negative_stock", inventory(food=-1), "INVALID_DOMAIN"),
        ("fractional_stock", inventory(food=.5), "INVALID_DOMAIN"),
        ("over_capacity", inventory(food=11), "INVENTORY_CAPACITY"),
        ("portable_biomass", {**inventory(), "BIOMASS": 1}, "INVALID_DOMAIN"),
    ]:
        invalid(label, world(agent(inventory=items)), code, ["V12"], "3.3,5.1")
    for mode, integrity in [("OPEN", 0), ("CLOSED", 0), ("BREACHED", 1)]:
        invalid("gate_" + mode.lower() + "_integrity_mismatch",
                world(agent(x="9"), barriers=[barrier(mode=mode, integrity=integrity)]),
                "INVALID_GATE_STATE", ["V20"], "3.2")
    invalid("gate_integrity_over_max", world(agent(x="9"), barriers=[barrier(integrity=201)]),
            "INVALID_DOMAIN", ["V20"], "3.2")
    for label, rect in [("degenerate", ["11", "9", "11", "11"]), ("outside", ["99", "9", "101", "11"])]:
        invalid("barrier_" + label, world(agent(), barriers=[barrier(rect=rect)]), "INVALID_GEOMETRY", ["V02"], "3.1–3.2")
    invalid("living_on_closed_barrier_boundary", world(agent(x="10"), barriers=[barrier()]),
            "INVALID_GEOMETRY", ["V02"], "3.1")
    invalid("remains_unknown_source", world(agent(), remains=[
        {"id": "r", "source_agent": "missing", "x": "10", "y": "10", "biomass": 4}]),
        "INVALID_REFERENCE", ["V01", "V21"], "2.2,3.2")
    invalid("reservation_exceeds_inventory", world(agent(inventory=inventory(food=1), reserved=inventory(food=2))),
            "INVALID_RESERVATION", ["V13"], "9.2")
    out.append(case(
        "VAL_shared_coordinates_and_outer_boundary_valid", ["V02"],
        world(agent("a", x="0", y="0"), agent("b", x="0", y="0")), [],
        [check("/validation/valid", True)], kind="validation", source=["ontology §3.1"]))
    return out


def cases():
    result=lifecycle_cases() + conflict_resource_cases() + geometry_cases() + observation_cases() + validation_cases()
    for item in result:
        item["request"]["setup"]=with_gate_enclosures(item["request"]["setup"])
    return result
