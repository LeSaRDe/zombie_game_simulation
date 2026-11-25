"""Independent baseline and predeclared statistical oracles over raw observations."""
from collections import Counter, defaultdict
from fractions import Fraction

from tests.assertions import number
from tests.invariants import validate_snapshot, validate_trace, require, RESOURCES


def baseline_geometry():
    """Literal geometry from ontology §15.3, independent of the RDF importer."""
    rectangles = []
    stocks = {}
    for u, v in ((150, 150), (750, 150), (150, 750), (750, 750)):
        for a, b, c, d in ((0, 98, 100, 100), (0, 2, 2, 98), (98, 2, 100, 98),
                           (0, 0, 47, 2), (53, 0, 100, 2)):
            rectangles.append(("Obstacle", u+a, v+b, u+c, v+d))
        rectangles.append(("Gate", u+47, v, u+53, v+2))
        stocks[(u+50, v+50)] = {"FOOD": 60, "MEDICAL_SUPPLY": 20, "MATERIAL": 40}
    for rect in ((420, 180, 460, 340), (540, 660, 580, 820),
                 (180, 540, 340, 580), (660, 420, 820, 460)):
        rectangles.append(("Obstacle", *rect))
    for point in ((100, 500), (300, 500), (500, 100), (500, 300), (700, 500), (900, 500)):
        stocks[point] = {"FOOD": 60, "MEDICAL_SUPPLY": 20, "MATERIAL": 20}
    return rectangles, stocks


def validate_baseline(snapshot):
    validate_snapshot(snapshot)
    require(number(snapshot["time"]) == 0, "Baseline is an initial snapshot")
    require(number(snapshot["world"]["length"]) == 1000
            and number(snapshot["world"]["width"]) == 1000, "Baseline bounds")
    agents = list(snapshot["agents"].values())
    require(len(agents) == 1000, "Baseline population")
    require(Counter(a["status"] for a in agents) == {"HEALTHY": 780, "INFECTED": 20, "ACTIVE": 200}, "Baseline statuses")
    roles = Counter((a["type"], a["role"]) for a in agents)
    require(roles == {("Human", None): 400, ("Human", "DOCTOR"): 80,
                     ("Human", "WARRIOR"): 120, ("Human", "SCOUT"): 80,
                     ("Human", "ENGINEER"): 120, ("Zombie", None): 120,
                     ("Zombie", "TYRANT"): 20, ("Zombie", "RUNNER"): 30,
                     ("Zombie", "SPITTER"): 20, ("Zombie", "SCREAMER"): 10}, "Baseline roles")
    totals = Counter()
    # Grid only accelerates the independent pair-distance check; it does not
    # generate positions or import the production spatial index.
    cells = defaultdict(list)
    for a in agents:
        require(a["life"] == 100 and number(a["stamina"]) == 100, "Baseline life/stamina")
        require(a["active_action"] is None and not a["effects"] and not a["cooldowns"], "Baseline idle state")
        expected_model = "HumanDefaultModel" if a["type"] == "Human" else "ZombieDefaultModel"
        require(a["model_assignment"]["model_id"] == expected_model, "Baseline model assignment")
        if a["type"] == "Human":
            require(number(a["hunger"]) == 20 and not any(a["reserved"].values()), "Baseline human fields")
            expected = {"FOOD": 0, "MEDICAL_SUPPLY": int(a["role"] == "DOCTOR"),
                        "MATERIAL": int(a["role"] == "ENGINEER")}
            require(all(a["inventory"].get(k, 0) == v for k, v in expected.items()), "Baseline carried supplies")
            totals.update(a["inventory"])
        if a["role"] == "SPITTER":
            require(a["spit_charges"] == 3, "Baseline Spitter charges")
        x, y = number(a["x"]), number(a["y"])
        if a["type"] == "Zombie":
            require(not any(u+2 < x < u+98 and v+2 < y < v+98
                            for u, v in ((150, 150), (750, 150), (150, 750), (750, 750))), "Initial zombie in shelter")
        cell = (x // 15, y // 15)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for bx, by, kind in cells[(cell[0]+dx, cell[1]+dy)]:
                    minimum = 2 if kind == a["type"] else 15
                    require((x-bx)**2 + (y-by)**2 >= minimum**2, "Baseline pair separation")
        cells[cell].append((x, y, a["type"]))
    require(len(snapshot["episodes"]) == 20, "Initial episode count")
    for ep in snapshot["episodes"].values():
        require(number(ep["onset_at"]) == 0 and number(ep["incubation_duration"]) == 300
                and ep["outcome"] == "ONGOING", "Initial episode parameters")
    expected_rectangles, expected_stocks = baseline_geometry()
    rectangles = [(b["kind"], *map(number, b["rect"])) for b in snapshot["barriers"].values()]
    require(Counter(rectangles) == Counter(expected_rectangles), "Baseline geometry differs from literal specification")
    for b in snapshot["barriers"].values():
        if b["kind"] == "Gate":
            require(b["mode"] == "CLOSED" and b["integrity"] == b["max_integrity"] == 200, "Baseline gate")
    observed_stocks = {}
    for s in snapshot["stockpiles"].values():
        point = (number(s["x"]), number(s["y"]))
        require(point not in observed_stocks, "Duplicate baseline stockpile position")
        observed_stocks[point] = {r: s["stock"].get(r, 0) for r in RESOURCES}
        require(not any(s["reserved"].values()), "Baseline stock reservation")
        totals.update(s["stock"])
    require(observed_stocks == expected_stocks, "Baseline stock locations/quantities")
    require(totals == {"FOOD": 600, "MEDICAL_SUPPLY": 280, "MATERIAL": 400}, "Baseline total resources")
    require(not snapshot["remains"] and not snapshot["signals"] and not snapshot["reservations"], "Baseline empty collections")


def validate_trials(records, spec):
    """A fixed five-sigma diagnostic, not a claim of stochastic proof."""
    seeds = spec["seeds"]
    require(isinstance(records, list) and len(records) == len(seeds), "Missing/extra trials")
    require([r["seed"] for r in records] == seeds, "Trial seed order/identity mismatch")
    probability = number(spec["probability"])
    require(0 < probability < 1, "Statistical check needs nondegenerate probability")
    outcomes = []
    for r in records:
        trace = r["trace"]
        validate_trace(trace)
        if spec["kind"] == "hit":
            draws = trace["random_draws"]
            require(len(draws) == 1 and draws[0]["channel"] == "hit", "Exactly one hit draw per trial")
            require(number(draws[0]["probability"]) == probability, "Wrong hit probability")
            outcomes.append(draws[0]["outcome"])
            end = trace["snapshots"]["end"]
            require(end["agents"]["h"]["life"] == (86 if outcomes[-1] else 100), "Hit draw/effect mismatch")
        elif spec["kind"] == "claim":
            end = trace["snapshots"]["end"]
            quantities = [end["agents"][a]["inventory"]["FOOD"] for a in ("a", "b")]
            require(sorted(quantities) == [0, 1] and end["stockpiles"]["s"]["stock"]["FOOD"] == 0,
                    "Arbitration must conserve the single item")
            outcomes.append(quantities[0] == 1)
        else:
            raise ValueError(f"Unknown trial kind {spec['kind']}")
    successes = sum(outcomes)
    n = len(records)
    # Squared form is exact; no floating point quantile or implementation RNG.
    deviation = Fraction(successes) - n * probability
    require(deviation**2 <= 25 * n * probability * (1-probability),
            f"Five-sigma trial diagnostic: {successes}/{n}, expected p={probability}")


def validate_performance(result, spec):
    """Recompute reported metrics from actual browser samples outside the adapter."""
    frames = [number(v) for v in result["frame_times_ms"]]
    inputs = sorted(number(v) for v in result["input_latencies_ms"])
    acks = sorted(number(v) for v in result["receipt_ack_latencies_ms"])
    require(len(frames) >= 20 and len(inputs) >= 20 and len(acks) >= 5, "Insufficient benchmark samples")
    require(all(v > 0 for v in frames) and all(v >= 0 for v in inputs+acks), "Invalid benchmark timing")
    require(result["measured_frames"] == len(frames), "Frame sample count mismatch")
    elapsed = sum(frames)
    target = number(spec["duration_seconds"]) * 1000
    require(abs(elapsed-target) <= max(frames)*2, "Incomplete benchmark interval")
    fps = 1000 * len(frames) / elapsed
    input_p95 = inputs[(95*len(inputs)+99)//100-1]
    ack_p95 = acks[(95*len(acks)+99)//100-1]
    for field, expected in (("fps", fps), ("input_latency_p95_ms", input_p95), ("receipt_ack_p95_ms", ack_p95)):
        require(abs(number(result[field])-expected) <= Fraction(1, 1000000), f"Derived metric mismatch: {field}")
    require(result["population"] == spec["population"], "Benchmark population mismatch")
    if spec["population"] == 1000:
        require(fps >= 30 and input_p95 <= 100 and ack_p95 <= 250, "1,000-agent GUI performance target missed")
