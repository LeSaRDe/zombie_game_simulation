"""EventRandom: isolated semantic evaluation over a planning/read workspace."""
from __future__ import annotations
from fractions import Fraction
import hashlib
from .primitives import stamp


class EventRandom:
    def __init__(self, context):
        self.context = context

    def _random(self, domain, key):
        context = self.context
        if domain in {"hit", "infection"}:
            occurrence = context.occurrences.get(key, {})
            token = (str(occurrence.get("intent_id", key)), domain)
            injected = getattr(context, "_keyed_random_values", {})
            if token in injected:
                return injected[token]
        digest = hashlib.sha256(f"{context.seed}:{domain}:{key}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def inject_random_values(self, draws):
        """Set explicit keyed variates for controlled, reproducible experiments.

        This supplies numbers, never outcomes. Ordinary handlers still decide
        whether a draw occurs and calculate/record its actual probability.
        """
        context = self.context
        values = dict(getattr(context, "_keyed_random_values", {}))
        for draw in draws:
            channel = draw["channel"]
            value = float(Fraction(str(draw["value"])))
            if channel not in {"hit", "infection"} or not 0 <= value < 1:
                raise ValueError("Controlled draws require hit/infection and a finite value in [0, 1)")
            values[(str(draw["intent"]), channel)] = value
        context._keyed_random_values = values

    def _bernoulli(self, occurrence, channel, probability):
        context = self.context
        counters=context.execution_counters
        counters["bernoulli_calls"]+=1
        probability=min(1.,max(0.,float(probability)))
        raw=context._random(channel,occurrence["id"])
        result=raw < probability
        record={"occurrence":occurrence["id"],"channel":channel,"probability":probability,
                "value":raw,"outcome":result,"time":stamp(context.time)}
        context.random_draws.append(record)
        context._effects_buffer.append({"kind":"random_draw",**record})
        return result
