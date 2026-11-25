"""Independent snapshot/trace checks; these do not implement world evolution.

These checks cover structural subsets of V01–V08, V10–V13, V17, V20–V25.
Action, temporal, perception, and stochastic laws also require the scenario cases.
"""
from tests.assertions import ContractFailure, number, equal

ROLES = {"DOCTOR": "Human", "WARRIOR": "Human", "SCOUT": "Human", "ENGINEER": "Human",
         "TYRANT": "Zombie", "RUNNER": "Zombie", "SPITTER": "Zombie", "SCREAMER": "Zombie"}
RESOURCES = {"FOOD", "MEDICAL_SUPPLY", "MATERIAL"}


def require(condition, message):
    if not condition:
        raise ContractFailure(message)


def integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def stocks(total, reserved, context):
    require(isinstance(total, dict) and isinstance(reserved, dict), f"{context}: stock maps required")
    require(set(total) <= RESOURCES and set(reserved) <= RESOURCES, f"{context}: unknown portable resource")
    for resource in RESOURCES:
        quantity, held = total.get(resource, 0), reserved.get(resource, 0)
        require(integer(quantity) and integer(held) and held <= quantity,
                f"{context}: invalid total/reservation for {resource}")


def validate_snapshot(snapshot, label="snapshot"):
    required = {"time", "revision", "world", "agents", "barriers", "stockpiles", "remains",
                "episodes", "reservations", "signals"}
    require(required <= snapshot.keys(), f"{label}: missing snapshot fields {required - snapshot.keys()}")
    now = number(snapshot["time"])
    require(now >= 0 and number(snapshot["revision"]).denominator == 1
            and number(snapshot["revision"]) >= 0, f"{label}: invalid time/revision")
    length, width = (number(snapshot["world"][k]) for k in ("length", "width"))
    require(length > 0 and width > 0, f"{label}: invalid world bounds")
    for name in required - {"time", "revision"}:
        require(isinstance(snapshot[name], dict), f"{label}: {name} must be an object")
    for key, state in snapshot["agents"].items():
        context = f"{label}/agents/{key}"
        fields = {"id", "type", "status", "role", "life", "stamina", "x", "y", "active_action",
                  "cooldowns", "effects", "infection_episode"}
        require(fields <= state.keys(), f"{context}: missing normalized fields {fields - state.keys()}")
        require(state["id"] == key, f"{context}: mismatched identity")
        kind, life, role = state["type"], state["life"], state["role"]
        require(kind in {"Human", "Zombie"} and integer(life, 0, 100), f"{context}: type/life domain")
        require(role is None or ROLES.get(role) == kind, f"{context}: incompatible role")
        require(0 <= number(state["stamina"]) <= 100, f"{context}: stamina domain")
        x, y = number(state["x"]), number(state["y"])
        require(0 <= x <= length and 0 <= y <= width, f"{context}: world bounds")
        expected = ("DEAD" if life == 0 else "ACTIVE" if kind == "Zombie"
                    else "INFECTED" if state["infection_episode"] is not None else "HEALTHY")
        require(state["status"] == expected, f"{context}: inconsistent status")
        if kind == "Zombie" or life == 0:
            require(state["infection_episode"] is None, f"{context}: inapplicable active episode")
        if life == 0:
            require(role is None and state["active_action"] is None
                    and not state["effects"] and not state["cooldowns"], f"{context}: dead cleanup")
        if kind == "Human":
            require({"hunger", "inventory", "reserved", "carry_capacity"} <= state.keys(),
                    f"{context}: missing human fields")
            require(0 <= number(state["hunger"]) <= 100, f"{context}: hunger domain")
            stocks(state["inventory"], state["reserved"], context)
            require(integer(state["carry_capacity"])
                    and sum(state["inventory"].values()) <= state["carry_capacity"],
                    f"{context}: carry capacity")
            if life == 0:
                require(sum(state["inventory"].values()) == 0, f"{context}: dead inventory not dropped")
        else:
            require("hunger" not in state and "inventory" not in state, f"{context}: human fields on zombie")
        episode_id = state["infection_episode"]
        if episode_id is not None:
            require(episode_id in snapshot["episodes"], f"{context}: missing episode")
            ep = snapshot["episodes"][episode_id]
            require(ep["agent"] == key, f"{context}: episode ownership")
            require(ep["outcome"] == "ONGOING" and ep.get("ended_at") is None,
                    f"{context}: active reference to closed episode")
            require(number(ep["incubation_duration"]) > 0
                    and number(ep["conversion_due_at"]) == number(ep["onset_at"]) + number(ep["incubation_duration"]),
                    f"{context}: episode deadline")
            require(number(ep["onset_at"]) <= now <= number(ep["conversion_due_at"]),
                    f"{context}: episode time interval")
        for b_id, barrier in snapshot["barriers"].items():
            blocks = barrier["kind"] == "Obstacle" or (barrier["kind"] == "Gate" and barrier["mode"] == "CLOSED") or (barrier["kind"] == "Barricade" and barrier["integrity"] > 0)
            if life > 0 and blocks:
                a, b, c, d = map(number, barrier["rect"])
                require(not (a <= x <= c and b <= y <= d), f"{context}: inside closed barrier {b_id}")
    for key, barrier in snapshot["barriers"].items():
        require(barrier["kind"] in {"Obstacle", "Gate", "Barricade"}, f"{label}: unknown barrier kind")
        a, b, c, d = map(number, barrier["rect"])
        require(0 <= a < c <= length and 0 <= b < d <= width, f"{label}: invalid rectangle {key}")
        if barrier["kind"] in {"Gate", "Barricade"}:
            require(integer(barrier["max_integrity"], 1) and integer(barrier["integrity"], 0, barrier["max_integrity"]), f"{label}: barrier integrity")
        if barrier["kind"] == "Gate":
            require(barrier["mode"] in {"OPEN", "CLOSED", "BREACHED"}
                    and (barrier["mode"] == "BREACHED") == (barrier["integrity"] == 0), f"{label}: gate mode/integrity")
    for key, stock in snapshot["stockpiles"].items():
        stocks(stock["stock"], stock["reserved"], f"{label}/stockpiles/{key}")
    sources = []
    for key, remains in snapshot["remains"].items():
        require(integer(remains["biomass"]) and integer(remains["reserved_biomass"])
                and remains["reserved_biomass"] <= remains["biomass"], f"{label}: biomass reservation")
        source = remains["source_agent"]
        require(source in snapshot["agents"] and snapshot["agents"][source]["life"] == 0,
                f"{label}: remains does not identify a dead agent")
        sources.append(source)
    require(len(sources) == len(set(sources)), f"{label}: duplicate remains per death")
    ongoing = {}
    for ep_id, ep in snapshot["episodes"].items():
        if ep["outcome"] == "ONGOING":
            owner = ep["agent"]
            require(owner not in ongoing and owner in snapshot["agents"]
                    and snapshot["agents"][owner]["infection_episode"] == ep_id,
                    f"{label}: orphan or duplicate ongoing episode")
            ongoing[owner] = ep_id


def validate_trace(response):
    for key, kind in {"snapshots": dict, "intents": dict, "occurrences": dict, "observations": dict,
                      "events": list, "random_draws": list}.items():
        require(isinstance(response.get(key), kind), f"Missing/wrong response collection {key}")
    frozen = {}
    snapshots = sorted(response["snapshots"].items(), key=lambda item: (number(item[1]["time"]), number(item[1]["revision"])))
    for label, snap in snapshots:
        validate_snapshot(snap, label)
        for key, state in snap["agents"].items():
            active = state["active_action"]
            if active is not None:
                require(active in response["occurrences"]
                        and response["occurrences"][active]["actor"] == key,
                        f"{key}: orphan or wrong-owner active action")
            if key in frozen:
                previous = frozen[key]
                require(state["life"] == 0 and state["type"] == previous["type"]
                        and number(state["x"]) == number(previous["x"])
                        and number(state["y"]) == number(previous["y"]), f"{key}: resurrection or moved dead identity")
            if state["life"] == 0:
                frozen[key] = state
    events = response["events"]
    seen = set()
    for event in events:
        require(event["id"] not in seen, "Duplicate event identity")
        require(set(event.get("causes", [])) <= seen, "Missing, cyclic, or future causal predecessor")
        seen.add(event["id"])
    for draw in response["random_draws"]:
        p, value = number(draw["probability"]), number(draw["value"])
        require(0 <= p <= 1 and 0 <= value < 1, "Invalid Bernoulli probability/draw")
        require(type(draw["outcome"]) is bool and draw["outcome"] == (value < p), "Draw does not match probability/outcome")
