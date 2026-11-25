"""Bounded default-policy demonstrations and complete candidate-codec checks.

Expected actions live in assertions, never in a default-model request. Competing
choices may vary: a real completed occurrence somewhere in the reviewed bank is
required for each action. See POLICY_OPERATIONS.md for the raw capture contract.
"""
from copy import deepcopy

from .actions import _base_cases
from .dsl import agent, world, intent, check, case


def _items(food=0, medical=0, material=0):
    return {"FOOD": food, "MEDICAL_SUPPLY": medical, "MATERIAL": material}


def _stock(id="s", x="11", y="10", **items):
    return {"id": id, "x": x, "y": y, "stock": _items(**items)}


def _door(mode="CLOSED", integrity=200):
    return [
        {"id": "lower", "kind": "Obstacle", "rect": ["12", "0", "13", "9"]},
        {"id": "upper", "kind": "Obstacle", "rect": ["12", "11", "13", "100"]},
        {"id": "g", "kind": "Gate", "rect": ["12", "9", "13", "11"],
         "mode": mode, "integrity": integrity, "max_integrity": 200},
    ]


def witness_bank():
    """Concrete inputs plus separately retained reasons/coverage expectations."""
    inputs, review = [], {}

    def add(id, setup, actions, reason, *, objective=None, background=(), decisions=8, horizon="35"):
        a = setup["agents"][0]
        inputs.append({"id": id, "world": setup, "actor": a["id"],
                       "model": "HumanDefaultModel" if a["type"] == "Human" else "ZombieDefaultModel",
                       "seed": 20261106, "max_decisions": decisions, "horizon": horizon,
                       "memory_seed": {"objective": objective, "recent_reports": []},
                       "background_events": list(background)})
        review[id] = {"actions": list(actions), "reason": reason}

    hold = {"kind": "hold_location", "position": ["10", "10"], "until": "10"}
    route = {"kind": "reach_location", "position": ["20", "10"]}
    defense = {"kind": "protect_region", "rect": ["0", "0", "12", "100"]}
    add("safe_rendezvous", world(agent("a", hunger="0")), ["wait"],
        "Full energy and a short known rendezvous make idle waiting useful.", objective=hold)
    add("depleted_rendezvous", world(agent("a", stamina="0", hunger="0")), ["rest"],
        "Safe zero-energy actor can recover without sacrificing its location.", objective=hold)
    add("distant_supplies", world(agent("a", hunger="85"), stockpiles=[_stock(x="30", food=3)]), ["move", "pickup", "eat"],
        "Visible food is reachable only after travel; high hunger gives it clear value.",
        objective={"kind": "seek_resource", "resource_type": "FOOD"})
    add("fresh_human_warning", world(agent("a", x="50", y="50"), agent("ally", x="20", y="50"),
        agent("enemy", "Zombie", x="85", y="50")), ["signal"],
        "The actor sees a fresh enemy that an ally within ordinary signal range cannot see.")
    add("near_finished_opponent", world(agent("a"), agent("t", "Zombie", x="11", life=10)), ["melee"],
        "Ordinary melee can remove an adjacent low-life threat immediately.")
    add("food_at_hand", world(agent("a", hunger="90"), stockpiles=[_stock(food=3)]), ["pickup", "eat"],
        "An empty hungry actor has nearby food and no threat.")
    add("medicine_needs_space", world(agent("a", life=20, inventory=_items(material=10)),
        stockpiles=[_stock(medical=1)]), ["drop", "pickup", "first_aid"],
        "Full low-value material inventory prevents acquiring medicine for a serious injury.",
        objective={"kind": "seek_resource", "resource_type": "MEDICAL_SUPPLY"})
    add("hungry_ally", world(agent("a", hunger="0", inventory=_items(food=2)), agent("t", x="11", hunger="99")), ["transfer"],
        "A satiated actor can supply its adjacent hungry ally without personal need.",
        objective={"kind": "supply_ally", "target": "t", "resource_type": "FOOD"})
    add("own_urgent_meal", world(agent("a", hunger="99", inventory=_items(food=1))), ["eat"],
        "Food in hand can prevent upcoming starvation in a safe scene.")
    add("own_severe_wound", world(agent("a", life=20, inventory=_items(medical=1))), ["first_aid"],
        "A safe uninfected injured actor can use its own medicine for physical recovery.")
    add("closed_route", world(agent("a"), barriers=_door()), ["open_gate", "move"],
        "An impassable wall makes the closed gate the useful route to the remembered destination.", objective=route)
    add("exposed_refuge", world(agent("a"), agent("ally", x="5"), agent("enemy", "Zombie", x="14"),
        barriers=_door("OPEN")), ["close_gate"],
        "Closing the open door separates a nearby outside threat from the defended side.", objective=defense)
    add("fragile_prey", world(agent("a", "Zombie"), agent("t", x="11", life=10)), ["claw"],
        "Claw kills this nearby prey faster than an insufficient six-damage bite.")
    add("healthy_prey", world(agent("a", "Zombie"), agent("t", x="11")), ["bite"],
        "A healthy high-life human gives a bite meaningful infection value.")
    add("armored_healthy_prey", world(agent("a", "Zombie"), agent("t", role="WARRIOR", x="11")), ["bite"],
        "Armor lowers physical returns while the healthy target remains susceptible to infection.")
    add("remains_for_recovery", world(agent("a", "Zombie", life=20, stamina="20"),
        agent("body", x="11", life=0, death_at="0", death_cause="initial_condition"),
        remains=[{"id": "r", "source_agent": "body", "x": "11", "y": "10", "biomass": 4}]), ["feed"],
        "Feeding nearby remains restores both scarce life and energy.")
    add("weak_blocking_door", world(agent("a", "Zombie"), barriers=_door(integrity=15)), ["smash"],
        "A baseline zombie needs one smash to clear the only known route.", objective=route)
    add("curable_neighbor", world(agent("a", role="DOCTOR", inventory=_items(medical=2)),
        agent("t", x="11", infection={"onset_at": "0", "incubation_duration": "25"})), ["treat_infection"],
        "Nearby infection is curable with ample deadline slack; no physical injury competes.")
    add("susceptible_defender", world(agent("a", role="DOCTOR", inventory=_items(medical=2)),
        agent("t", x="11"), agent("enemy", "Zombie", x="20")), ["prophylaxis"],
        "A healthy adjacent defender faces an observed exposure threat and medicine is available.", objective=defense)
    add("decisive_heavy_hit", world(agent("a", role="WARRIOR"), agent("t", "Zombie", x="11", life=30)), ["power_strike"],
        "One power strike can kill sooner than two ordinary Warrior melee attempts.")
    incoming = [{"at": "0", "intents": [intent("approach", "t", "move", duration="2", path=[
        {"x": "14", "y": "10", "offset": "0"}, {"x": "11", "y": "10", "offset": "2"}])]},
        {"at": "2", "intents": [intent("incoming", "t", "claw", "a")]}]
    add("incoming_defended_contact", world(agent("a", role="WARRIOR"), agent("t", "Zombie", x="14"),
        agent("ally", x="9", life=20)), ["guard"],
        "An observed approach makes temporary resistance useful before holding a defensive position.",
        objective={"kind": "hold_location", "position": ["10", "10"], "until": "4"}, background=incoming)
    add("uncertain_frontier", world(agent("a", role="SCOUT"), agent("t", "Zombie", x="70")), ["recon"],
        "Recon can inspect an uncertain frontier beyond current sensing before committing travel.",
        objective={"kind": "explore_frontier", "position": ["70", "10"]})
    add("wide_scout_report", world(agent("a", role="SCOUT", x="50", y="50"),
        agent("ally", x="1", y="50"), agent("t", "Zombie", x="90", y="50")), ["mark_target"],
        "Scout sees both a threat and an ally beyond ordinary signal range; a mark reaches that ally.")
    add("unprotected_chokepoint", world(agent("a", role="ENGINEER", x="10.5", inventory=_items(material=2)),
        agent("ally", x="5"), agent("enemy", "Zombie", x="40"), barriers=_door()[:2]), ["build_barricade"],
        "The empty two-metre wall gap has no gate to close or repair and a legal defensive footprint.", objective=defense)
    add("damaged_refuge", world(agent("a", role="ENGINEER", inventory=_items(material=1)),
        agent("ally", x="5"), barriers=_door(integrity=100)), ["repair_barrier"],
        "One material can restore a useful closed defense; two-material construction is unavailable.", objective=defense)
    add("ready_zombie_allies", world(agent("a", "Zombie", role="TYRANT"),
        agent("z1", "Zombie", x="13"), agent("z2", "Zombie", x="13", y="10.5"),
        agent("z3", "Zombie", x="13", y="9.5"), agent("t", x="14")), ["rally"],
        "Several visible allies already have contact opportunities while the Tyrant is out of contact.")
    add("strong_blocking_door", world(agent("a", "Zombie", role="TYRANT"), barriers=_door()), ["demolish"],
        "High integrity rewards demolish's greater damage per unit time and stamina.", objective=route)
    add("distant_runner_prey", world(agent("a", "Zombie", role="RUNNER"), agent("t", x="20")), ["dash"],
        "A well-rested Runner can close distance faster while retaining follow-up attack energy.")
    add("ranged_exposure", world(agent("a", "Zombie", role="SPITTER"), agent("t", x="20")), ["spit"],
        "A full charge reservoir offers immediate exposure at ten metres instead of prolonged approach.")
    add("wide_hunt_report", world(agent("a", "Zombie", role="SCREAMER", x="50", y="50"),
        agent("ally", "Zombie", x="1", y="50"), agent("t", x="80", y="50")), ["scream"],
        "Screamer sees an ally outside ordinary signal reach and a fresh human beyond that ally's sight.")
    return inputs, review


def cases():
    rows = _base_cases()
    actions = [r["name"] for r in rows]
    bank, review = witness_bank()
    policy = case("POL_DEFAULT_WITNESS_BANK", ["V09", "V10", "V15", "V16", "V24"],
        {"policy_bank": bank}, [{"op": "policy.run_bank", "bank": "policy_bank", "label": "bank"}],
        [check("/captures/bank/contexts/*", len(bank), "count")], actions=actions,
        source=["plan §8", "plan M3", "ontology §§8–13"], decisions=["D7"], kind="workflow", tier="integration",
        description="Unmodified default models must actually demonstrate all 29 actions across a bounded reviewed bank.")
    policy["policy_checks"] = [{"path": "/captures/bank", "kind": "default_bank", "actions": actions,
                                "contexts": deepcopy(bank), "review": review}]

    # Candidate templates are explicitly allowed here: this is a codec/pipeline
    # test, separate from the model-choice bank above. The existing independently
    # written action oracles verify the decoded action's real consequences.
    fixtures, expected = [], {}
    for row in rows:
        id = "codec_" + row["name"]
        command = {k: deepcopy(v) for k, v in row["command"].items() if k != "op"}
        fixtures.append({"id": id, "world": deepcopy(row["setup"]), "actor": "a", "candidates": [command],
                         "padding": 2, "draws": row["draws"], "duration": row["duration"]})
        expected[id] = {"intent": command, "checks": deepcopy(row["case"]["checks"])}
    encoder = case("POL_ENCODER_ALL_ACTION_ROUNDTRIPS", ["V09", "V13", "V15", "V24"],
        {"encoder_bank": fixtures}, [{"op": "encoder.roundtrip_bank", "bank": "encoder_bank", "label": "codec"}],
        [check("/captures/codec/contexts/*", 29, "count")], actions=actions,
        source=["plan §9.1", "ontology §§9–13"], decisions=["D7"], kind="workflow", tier="integration",
        description="Encode/decode every typed action and execute the decoded intent through the real engine.")
    encoder["policy_checks"] = [{"path": "/captures/codec", "kind": "encoder_bank", "contexts": expected}]
    return [policy, encoder]
