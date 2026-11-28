"""Stable source-pinned custom policy for legacy/v2 memory-codec comparisons."""
from dataclasses import dataclass
from zombie_sim import ActionIntent, Decision, ObjectDecisionModel


@dataclass(frozen=True)
class PrivateCounter:
    value: int


class CounterMemoryModel(ObjectDecisionModel):
    model_id = "deep-oop/counter-memory"
    version = "1.0.0"
    applicable_types = ("Human", "Zombie")

    def initial_memory(self, agent):
        return PrivateCounter(40)

    def choose(self, observation, memory, rng):
        if not isinstance(memory, PrivateCounter):
            raise TypeError("Policy must receive its decoded private memory type")
        return Decision(ActionIntent("wait", parameters={"duration": 1}), PrivateCounter(memory.value + 1))

    def encode_memory(self, memory):
        return {"counter": memory.value}

    def decode_memory(self, payload):
        return PrivateCounter(payload["counter"])
