"""Reproducible boundary families with independently calculated expectations.

These finite families supplement, rather than replace, hand-written traces.
No simulator values are used to calculate expected outcomes.
"""
from fractions import Fraction
from tests.spec.dsl import agent, world, submit, advance, snapshot, check, case


def decimal(value):
    value = Fraction(value)
    # All numbers used here have finite decimal representations.
    from decimal import Decimal
    return str(Decimal(value.numerator) / Decimal(value.denominator))


def cases():
    result = []
    # Resistance boundaries and overkill: independently implement the stated
    # mathematical rounding law, not a call to a production damage reducer.
    for resistance in ("0", "0.2", "0.3", "0.6", "0.8"):
        raw_after_armor = 14 * (1 - Fraction(resistance))
        mitigated = (raw_after_armor + Fraction(1, 2)).numerator // (raw_after_armor + Fraction(1, 2)).denominator
        for life in (1, 5, 14, 100):
            remaining = max(0, life - mitigated)
            result.append(case(
                f"generated.damage.r{resistance.replace('.', '_')}.life{life}",
                ["V03", "V04", "V17", "V18"],
                world(agent("z", "Zombie"), agent("h", x="11", life=life,
                                                     base_damage_resistance=resistance)),
                [submit("attack", "z", "claw", "h"), advance("1"), snapshot()],
                [check("/snapshots/end/agents/h/life", remaining),
                 check("/snapshots/end/agents/h/status", "DEAD" if remaining == 0 else "HEALTHY"),
                 check("/random_draws/*/channel", ["hit"], "set_eq"),
                 check("/random_draws/*", 1, "count"),
                 check("/random_draws/0/probability", "0.72", "numeric_eq"),
                 check("/random_draws/0/outcome", True),
                 check("/snapshots/end/remains/*", 1 if remaining == 0 else 0, "count")],
                actions=["claw"], source=["ontology §6.5", "ontology §12"],
                draws=[{"intent": "attack", "channel": "hit", "value": "0"}],
                description=f"Armor {resistance} at life {life}; death follows clamped integer damage."))
    # Hit and exposure are separate. Exact boundary draws exercise p=0 and the
    # strict Bernoulli convention u < p without asserting sample frequencies.
    for resistance in ("0", "0.2", "0.8", "1"):
        probability = Fraction("0.45") * (1 - Fraction(resistance))
        for suffix, draw in (("zero", Fraction(0)), ("at_probability", probability),
                             ("near_one", Fraction("0.999999999999"))):
            infected = draw < probability
            result.append(case(
                f"generated.exposure.r{resistance.replace('.', '_')}.{suffix}",
                ["V05", "V06", "V16", "V18"],
                world(agent("z", "Zombie"), agent("h", x="11", infection_resistance=resistance)),
                [submit("attack", "z", "bite", "h"), advance("1.5"), snapshot()],
                [check("/snapshots/end/agents/h/life", 94),
                 check("/snapshots/end/agents/h/status", "INFECTED" if infected else "HEALTHY"),
                 check("/snapshots/end/episodes/*", int(infected), "count"),
                 check("/random_draws/*", decimal(probability), "numeric_eq",
                       where={"channel": "infection"}, field="probability")],
                actions=["bite"], source=["ontology §6.2", "ontology §12"],
                draws=[{"intent": "attack", "channel": "hit", "value": "0"},
                       {"intent": "attack", "channel": "infection", "value": decimal(draw)}],
                description="Conditional exposure at a precise probability boundary."))
    for dx, dy in (("2", "0"), ("0", "2"), ("-2", "0"), ("0", "-2"), ("1.2", "1.6")):
        end_x, end_y = Fraction(10) + Fraction(dx), Fraction(10) + Fraction(dy)
        mid_x, mid_y = Fraction(10) + Fraction(dx)/2, Fraction(10) + Fraction(dy)/2
        result.append(case(
            f"generated.motion.{dx.replace('.', '_').replace('-', 'm')}.{dy.replace('.', '_').replace('-', 'm')}",
            ["V02", "V11", "V14", "V22"], world(agent()),
            [submit("travel", "h", "move", duration="1", path=[
                {"x": "10", "y": "10", "offset": "0"},
                {"x": decimal(end_x), "y": decimal(end_y), "offset": "1"}]),
             advance("0.5"), snapshot("mid"), advance("1"), snapshot()],
            [check("/snapshots/mid/agents/h/x", decimal(mid_x), "approx"),
             check("/snapshots/mid/agents/h/y", decimal(mid_y), "approx"),
             check("/snapshots/mid/agents/h/stamina", "99.9", "approx"),
             check("/snapshots/end/agents/h/x", decimal(end_x), "approx"),
             check("/snapshots/end/agents/h/y", decimal(end_y), "approx"),
             check("/snapshots/end/agents/h/stamina", "99.8", "approx")],
            actions=["move"], source=["ontology §10", "ontology §14.1"],
            description="Axis/diagonal motion has the same actual two-metre energy cost."))
    for resource in ("FOOD", "MEDICAL_SUPPLY", "MATERIAL"):
        for quantity in (1, 5, 10):
            source_inventory = {r: quantity if r == resource else 0 for r in ("FOOD", "MEDICAL_SUPPLY", "MATERIAL")}
            result.append(case(
                f"generated.transfer.{resource.lower()}.{quantity}", ["V12", "V13"],
                world(agent("giver", inventory=source_inventory), agent("receiver", x="11")),
                [submit("give", "giver", "transfer", "receiver", resource_type=resource, quantity=quantity),
                 snapshot("reserved"), advance("1"), snapshot()],
                [check(f"/snapshots/reserved/agents/giver/inventory/{resource}", quantity),
                 check(f"/snapshots/reserved/agents/giver/reserved/{resource}", quantity),
                 check(f"/snapshots/end/agents/giver/inventory/{resource}", 0),
                 check(f"/snapshots/end/agents/receiver/inventory/{resource}", quantity),
                 check(f"/snapshots/end/agents/*/inventory/{resource}", quantity, "sum_eq"),
                 check("/occurrences/give/result", "SUCCEEDED")], actions=["transfer"],
                source=["ontology §3.3", "ontology §9.2", "ontology §11"],
                description="Atomic exact transfer preserves each portable resource at capacity boundaries."))
    for dt in ("0.25", "1", "5"):
        hunger = Fraction(20) + Fraction("0.05") * Fraction(dt)
        result.append(case(
            f"generated.wait.{dt.replace('.', '_')}", ["V10", "V11", "V22"], world(agent(stamina="40")),
            [submit("idle", "h", "wait", duration=dt), advance(dt), snapshot()],
            [check("/snapshots/end/agents/h/hunger", decimal(hunger), "numeric_eq"),
             check("/snapshots/end/agents/h/stamina", "40", "numeric_eq"),
             check("/occurrences/idle/resolved_at", dt, "numeric_eq")], actions=["wait"],
            source=["ontology §5.1", "ontology §10"], description="Waiting preserves stamina but not biological time."))
    return result
