"""Independent oracles for captured default decisions and candidate round trips.

This module validates observations and committed records. It never chooses an
action, fabricates a policy response, or implements simulator evolution.
"""
from fractions import Fraction

from tests.assertions import ContractFailure, assert_checks, equal, number, select
from tests.invariants import validate_trace


def _require(ok, message):
    if not ok:
        raise ContractFailure(message)


def _close(actual, expected, message):
    _require(abs(number(actual) - number(expected)) <= Fraction(1, 10**9), message)


def _signature(intent):
    return {key: intent[key] for key in ("actor", "action", "target", "parameters") if key in intent}


def _quantity(state, resource):
    return state.get("inventory", {}).get(resource, 0)


def validate_utility_decision(decision, parameters):
    """Recalculate utility contributions and verify the actual chosen maximum."""
    candidates = decision["candidates"]
    _require(isinstance(candidates, list) and candidates, "Decision omitted its actual candidate set")
    identifiers, scores, chosen = set(), {}, None
    for candidate in candidates:
        id = candidate["id"]
        _require(id not in identifiers, "Duplicate candidate identity")
        identifiers.add(id)
        _require(type(candidate["observable_feasible"]) is bool, "Candidate feasibility must be a boolean")
        _require(isinstance(candidate["reason"], str) and candidate["reason"].strip(), "Candidate lacks a reason")
        terms = candidate["terms"]
        _require(isinstance(terms, list) and terms, "Utility components are required")
        total = Fraction(0)
        seen_terms = set()
        for term in terms:
            _require(term["feature"] not in seen_terms, "Duplicate utility feature")
            seen_terms.add(term["feature"])
            value = number(term["value"])
            _require(0 <= value <= 1, "Utility input is not normalized")
            weights = select(parameters, term["weight_path"])
            _require(len(weights) == 1, "Utility weight does not resolve in the default model parameters")
            contribution = value * number(weights[0])
            _close(term["contribution"], contribution, "Utility contribution differs from feature × configured weight")
            total += contribution
        _close(candidate["score"], total, "Candidate score differs from independently summed utility terms")
        if candidate["observable_feasible"]:
            scores[id] = number(candidate["score"])
        if id == decision["selected_candidate_id"]:
            chosen = candidate
    _require(chosen is not None and chosen["id"] in scores, "Chosen candidate is absent or masked")
    _require(scores[chosen["id"]] + Fraction(1, 10**9) >= max(scores.values()),
             "Default utility policy chose a lower-scoring candidate")
    _require(isinstance(decision["reason"], str) and decision["reason"].strip(), "Chosen decision lacks an explanation")
    return chosen


def _check_effect(action, intent, occurrence, before, after):
    """Check concrete consequences; a claimed 'executable' flag cannot pass."""
    actor_id = intent["actor"]
    a, b = before["agents"][actor_id], after["agents"][actor_id]
    params, target_id = intent.get("parameters", {}), intent.get("target", actor_id)
    start, end = number(occurrence["start_at"]), number(occurrence["resolved_at"])
    duration = end - start
    _require(duration > 0, "A policy witness requires positive elapsed action time")
    _close(before["time"], start, "Witness before snapshot is not at admission")
    _close(after["time"], end, "Witness after snapshot is not at resolution")
    _require(a["type"] == b["type"] and a["role"] == b["role"], "A successful witness changed actor type/role")
    if action not in {"move", "dash"}:
        _close(b["x"], a["x"], "Stationary action moved its actor")
        _close(b["y"], a["y"], "Stationary action moved its actor")
    costs = {"signal": 1, "melee": 6, "pickup": 1, "drop": 0, "transfer": 1, "eat": 0,
             "first_aid": 4, "open_gate": 1, "close_gate": 1, "claw": 6, "bite": 10,
             "smash": 10, "treat_infection": 6, "prophylaxis": 6, "power_strike": 15,
             "guard": 8, "recon": 6, "mark_target": 1, "build_barricade": 12,
             "repair_barrier": 8, "rally": 15, "demolish": 18, "spit": 8, "scream": 15}
    if action in costs:
        _close(b["stamina"], number(a["stamina"]) - costs[action], "Action did not spend its ordinary flat stamina cost")
    if action in {"move", "dash"}:
        _require((number(a["x"]), number(a["y"])) != (number(b["x"]), number(b["y"])),
                 "A motion witness must actually move")
        _require(number(b["stamina"]) < number(a["stamina"]), "Movement did not expend energy")
        if action == "dash":
            _require(number(b["stamina"]) < number(a["stamina"]) - 12, "Dash omitted its flat or distance cost")
    elif action == "wait":
        _close(b["stamina"], a["stamina"], "Wait regenerated stamina")
    elif action == "rest":
        rate = 4 if a["type"] == "Human" else 3
        _close(b["stamina"], min(100, number(a["stamina"]) + rate * duration), "Wrong rest energy recovery")
        _require(number(b["stamina"]) > number(a["stamina"]), "Rest witness did not recover energy")
    elif action in {"melee", "claw", "bite", "power_strike", "spit"}:
        target_before, target_after = before["agents"][target_id], after["agents"][target_id]
        raw = {"melee": 22 if a["role"] == "WARRIOR" else 16,
               "claw": 24 if a["role"] == "TYRANT" else 10 if a["role"] in {"RUNNER", "SCREAMER"} else 14,
               "bite": 6, "power_strike": 34, "spit": 4}[action]
        # Bank worlds use baseline profiles. Do not let a wrong derived armor
        # value become its own oracle for the resulting damage.
        base_resistance = {"WARRIOR": Fraction("0.2"), "TYRANT": Fraction("0.3")}.get(target_before["role"], Fraction(0))
        guard = target_before["effects"].get("guard")
        initial_resistance = base_resistance
        resistance = base_resistance
        if guard is not None:
            _require(target_before["role"] == "WARRIOR", "Guard applied to an incompatible target")
            _close(guard["magnitude"], "0.6", "Baseline guard strength changed")
            if number(guard["end_at"]) > start:
                initial_resistance = max(initial_resistance, Fraction("0.6"))
            if number(guard["end_at"]) > end:
                resistance = max(resistance, Fraction("0.6"))
        _close(target_before["damage_resistance"], initial_resistance, "Derived armor disagrees with independent baseline role/effect facts")
        damage = int(raw * (1 - resistance) + Fraction(1, 2)) if occurrence["result"] == "SUCCEEDED" else 0
        _require(target_after["life"] == max(0, target_before["life"] - damage), "Attack witness has incorrect physical consequence")
        if action == "spit":
            _require(b["spit_charges"] == a["spit_charges"] - 1, "Spit did not spend a charge")
    elif action == "pickup":
        resource, quantity = params["resource_type"], params["quantity"]
        _require(_quantity(b, resource) - _quantity(a, resource) == quantity, "Pickup did not acquire requested items")
        _require(before["stockpiles"][target_id]["stock"].get(resource, 0) -
                 after["stockpiles"][target_id]["stock"].get(resource, 0) == quantity, "Pickup did not conserve ground stock")
    elif action == "drop":
        resource, quantity = params["resource_type"], params["quantity"]
        _require(_quantity(a, resource) - _quantity(b, resource) == quantity, "Drop did not remove requested items")
        def ground(snap):
            return sum(s["stock"].get(resource, 0) for s in snap["stockpiles"].values()
                       if number(s["x"]) == number(a["x"]) and number(s["y"]) == number(a["y"]))
        _require(ground(after) - ground(before) == quantity, "Drop did not deposit items at actor location")
    elif action == "transfer":
        resource, quantity = params["resource_type"], params["quantity"]
        _require(_quantity(a, resource) - _quantity(b, resource) == quantity and
                 _quantity(after["agents"][target_id], resource) - _quantity(before["agents"][target_id], resource) == quantity,
                 "Transfer did not atomically conserve the requested quantity")
    elif action == "eat":
        _require(_quantity(a, "FOOD") - _quantity(b, "FOOD") == 1, "Eat did not consume one food")
        _close(b["hunger"], max(0, min(100, number(a["hunger"]) + Fraction("0.05") * duration) - 40), "Eat has incorrect hunger effect")
    elif action in {"first_aid", "treat_infection", "prophylaxis"}:
        _require(_quantity(a, "MEDICAL_SUPPLY") - _quantity(b, "MEDICAL_SUPPLY") == 1, "Medical action did not consume one supply")
        old, new = before["agents"][target_id], after["agents"][target_id]
        if action == "first_aid":
            _require(new["life"] == min(100, old["life"] + (28 if a["role"] == "DOCTOR" else 14)), "Wrong first-aid healing")
        elif action == "treat_infection":
            _require(old["status"] == "INFECTED" and new["status"] == "HEALTHY" and new["infection_episode"] is None,
                     "Treatment witness did not cure an infection")
            _require(old["life"] == new["life"], "Treatment improperly healed life")
        else:
            _require(number(new["infection_resistance_effective"]) >= Fraction("0.8"), "Prophylaxis resistance missing")
            _close(new["effects"]["prophylaxis"]["end_at"], end + 120, "Prophylaxis duration wrong")
    elif action in {"open_gate", "close_gate"}:
        old, new = before["barriers"][target_id], after["barriers"][target_id]
        _require(new["mode"] == ("OPEN" if action == "open_gate" else "CLOSED") and old["mode"] != new["mode"]
                 and old["integrity"] == new["integrity"], "Gate witness did not change only its mode")
    elif action == "feed":
        _require(before["remains"][target_id]["biomass"] - after["remains"][target_id]["biomass"] == 1, "Feed did not consume one biomass")
        _require(b["life"] == min(100, a["life"] + 8), "Feed healing wrong")
        _close(b["stamina"], min(100, number(a["stamina"]) + 12), "Feed energy wrong")
    elif action in {"smash", "demolish", "repair_barrier"}:
        old, new = before["barriers"][target_id], after["barriers"][target_id]
        if action == "repair_barrier":
            _require(new["integrity"] == min(old["max_integrity"], old["integrity"] + 60), "Repair amount wrong")
            _require(_quantity(a, "MATERIAL") - _quantity(b, "MATERIAL") == 1, "Repair material missing")
        else:
            _require(new["integrity"] == max(0, old["integrity"] - (60 if action == "demolish" else 20)), "Barrier damage wrong")
    elif action in {"guard", "recon"}:
        field, minimum, ttl = ("damage_resistance", "0.6", 4) if action == "guard" else ("sense_r", "85", 12)
        _require(number(b[field]) >= number(minimum), "Temporary role effect missing")
        _close(b["effects"][action]["end_at"], end + ttl, "Temporary role effect expires at wrong time")
    elif action == "build_barricade":
        new = [v for k, v in after["barriers"].items() if k not in before["barriers"] and v["kind"] == "Barricade"]
        _require(len(new) == 1 and new[0]["integrity"] == new[0]["max_integrity"] == 100, "Build did not create one intact barricade")
        _require(_quantity(a, "MATERIAL") - _quantity(b, "MATERIAL") == 2, "Build did not consume two materials")
    elif action == "rally":
        allies = [v for k, v in after["agents"].items() if k != actor_id and v["type"] == "Zombie" and v["life"] > 0
                  and (number(v["x"]) - number(b["x"]))**2 + (number(v["y"]) - number(b["y"]))**2 <= 30**2]
        _require(allies, "Rally demonstration had no actual eligible recipients")
        for ally in allies:
            _close(ally["effects"]["rallied"]["magnitude"], "0.1", "Rally bonus missing")
            _close(ally["effects"]["rallied"]["end_at"], end + 10, "Rally duration wrong")
        _require("rallied" not in b["effects"], "Tyrant rallied itself")
    elif action not in {"signal", "mark_target", "scream"}:
        raise ContractFailure("Unknown policy witness action " + action)
    if action in {"signal", "mark_target", "scream", "rally"}:
        added = [v for k, v in after["signals"].items() if k not in before["signals"] and v["sender_id"] == actor_id]
        _require(len(added) == 1, "Communication witness emitted no unique signal")
        radius, ttl = {"signal": (40, 8), "mark_target": (90, 10), "scream": (120, 12), "rally": (30, 10)}[action]
        _close(added[0]["radius"], radius, "Communication radius wrong")
        _close(added[0]["expires_at"], end + ttl, "Communication expiry wrong")


def _validate_initial(snapshot, context):
    expected = context["world"]
    _close(snapshot["time"], 0, "Policy context did not start at time zero")
    for field in ("length", "width"):
        _close(snapshot["world"][field], expected[field], "Policy world geometry was changed")
    _require(set(snapshot["agents"]) == {a["id"] for a in expected["agents"]}, "Policy world agent identities were changed")
    for given in expected["agents"]:
        actual = snapshot["agents"][given["id"]]
        for field in ("type", "role", "life"):
            _require(equal(actual[field], given[field]), "Policy initial agent state was changed")
        for field in ("x", "y", "stamina"):
            _close(actual[field], given[field], "Policy initial agent numeric state was changed")
        if given["type"] == "Human":
            _close(actual["hunger"], given["hunger"], "Policy initial hunger was changed")
            for resource in ("FOOD", "MEDICAL_SUPPLY", "MATERIAL"):
                _require(_quantity(actual, resource) == given["inventory"].get(resource, 0), "Policy initial inventory was changed")
        if given.get("infection"):
            _require(actual["status"] == "INFECTED", "Policy initial infection was removed")
            episode = snapshot["episodes"][actual["infection_episode"]]
            _close(episode["onset_at"], given["infection"]["onset_at"], "Policy initial infection onset changed")
            _close(episode["incubation_duration"], given["infection"]["incubation_duration"], "Policy initial incubation changed")
    for collection in ("barriers", "stockpiles", "remains"):
        _require(set(snapshot[collection]) == {v["id"] for v in expected[collection]}, "Policy initial environment identities changed")
        for given in expected[collection]:
            actual = snapshot[collection][given["id"]]
            if collection == "barriers":
                for key in ("kind", "mode", "integrity", "max_integrity"):
                    if key in given:
                        _require(equal(actual[key], given[key]), "Policy initial barrier state changed")
                for observed, required in zip(actual["rect"], given["rect"]):
                    _close(observed, required, "Policy initial barrier geometry changed")
            else:
                _close(actual["x"], given["x"], "Policy initial environment position changed")
                _close(actual["y"], given["y"], "Policy initial environment position changed")
                if collection == "stockpiles":
                    for resource in ("FOOD", "MEDICAL_SUPPLY", "MATERIAL"):
                        _require(actual["stock"].get(resource, 0) == given["stock"].get(resource, 0), "Policy initial ground stocks changed")
                else:
                    _require(actual["biomass"] == given["biomass"] and actual["source_agent"] == given["source_agent"],
                             "Policy initial remains changed")


def validate_policy_result(value, spec):
    """Dispatcher called by the runner for each case's policy_checks metadata."""
    if spec["kind"] == "encoder_bank":
        _require(set(value["contexts"]) == set(spec["contexts"]), "Encoder bank omitted/added a fixture")
        for id, expected in spec["contexts"].items():
            actual = value["contexts"][id]
            _require(equal(actual["decoded_intents"], [expected["intent"]]), "Encoder failed exact typed intent round trip: " + id)
            _require(equal(actual["candidate_mask"], [True, False, False]), "Codec padding mask wrong: " + id)
            _require(actual["padding_rejected_indices"] == [1, 2], "Padding decoded to executable intents: " + id)
            _require(actual["index_to_intent"]["0"] == expected["intent"]["id"], "Candidate index mapping lost identity: " + id)
            validate_trace(actual["trace"])
            assert_checks(actual["trace"], expected["checks"])
        return
    _require(spec["kind"] == "default_bank", "Unknown policy postcheck kind")
    contexts = {c["id"]: c for c in spec["contexts"]}
    _require(set(value["contexts"]) == set(contexts), "Policy bank omitted/added a context")
    witnesses = set()
    for id, context in contexts.items():
        actual = value["contexts"][id]
        model = actual["model"]
        default = value["default_models"][context["model"]]
        _require(model["id"] == context["model"] and model["version"] == default["version"], "Wrong default model/version")
        _require(equal(model["parameters"], default["parameters"]), "Default model weights/thresholds were overridden for a focus scenario")
        _require(equal(actual["memory_seed"], context["memory_seed"]), "Policy memory seed was replaced")
        trace = actual["trace"]
        validate_trace(trace)
        _validate_initial(trace["snapshots"]["initial"], context)
        decisions = actual["decisions"]
        _require(0 < len(decisions) <= context["max_decisions"], "Missing or unbounded policy decisions")
        seen_decisions = set()
        for decision in decisions:
            _require(decision["id"] not in seen_decisions, "Duplicate decision identity")
            seen_decisions.add(decision["id"])
            _require(0 <= number(decision["time"]) <= number(context["horizon"]), "Policy decision exceeded context horizon")
            observation = trace["observations"][decision["observation_id"]]
            _require(observation["self_state"]["id"] == context["actor"], "Decision used another agent's observation")
            _close(observation["time"], decision["time"], "Decision observation was captured at the wrong time")
            chosen = validate_utility_decision(decision, model["parameters"])
            actual_intent = trace["intents"][decision["intent_id"]]
            _require(actual_intent["decision_id"] == decision["id"], "Chosen intent lacks a decision origin")
            _require(equal(_signature(actual_intent), _signature(chosen["intent"])), "Engine received a different intent from the chosen candidate")
            _require(actual_intent["actor"] == context["actor"], "Default policy controlled a different actor")
            if actual_intent["status"] != "ADMITTED":
                _require(actual_intent["status"] == "REJECTED", "Unrecognized chosen-intent state")
                continue
            occurrence = trace["occurrences"][decision["intent_id"]]
            _require(occurrence["action"] == actual_intent["action"] and occurrence["actor"] == context["actor"],
                     "Chosen action does not match its real occurrence")
            if occurrence["result"] not in {"SUCCEEDED", "MISSED"}:
                continue
            action = actual_intent["action"]
            if action not in spec["review"][id]["actions"]:
                continue
            if action in {"melee", "claw", "bite", "power_strike", "spit"}:
                hits = [d for d in trace["random_draws"]
                        if d["intent"] == decision["intent_id"] and d["channel"] == "hit"]
                _require(len(hits) == 1 and hits[0]["outcome"] == (occurrence["result"] == "SUCCEEDED"),
                         "Combat witness lacks its actual corresponding hit outcome")
            before = trace["snapshots"][decision["before_snapshot"]]
            after = trace["snapshots"][decision["after_snapshot"]]
            _check_effect(action, actual_intent, occurrence, before, after)
            witnesses.add(action)
    missing = set(spec["actions"]) - witnesses
    _require(not missing, "Default-policy bank lacks real selected/executed witnesses: " + ", ".join(sorted(missing)))
