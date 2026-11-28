"""A complete, small OOP modeling example using only existing ontology actions.

Run from the repository: PYTHONPATH=src .runtimeenv/bin/python examples/oop_custom_model.py
This intentionally simple policy is an extension example, not a good survivor.
"""
from __future__ import annotations

import json
from random import Random

from zombie_sim import (ActionIntent, Decision, ObjectDecisionModel,
                        ObservationView, SimulationFramework)


class PatientModel(ObjectDecisionModel):
    model_id = "example/patient"
    version = "1.0.0"
    applicable_types = ("Human", "Zombie")

    def choose(self, observation: ObservationView, memory, rng: Random) -> Decision:
        # The observation is immutable and contains only locally visible data.
        memory = dict(memory or {})
        memory["decisions"] = memory.get("decisions", 0) + 1
        agent = observation.self_state
        action = "rest" if agent["stamina"] < 90 else "wait"
        return Decision(ActionIntent(action, parameters={"duration": 1}), memory,
                        {"reason": "Recover when tired; otherwise hold position"})


class MeanLivingStamina:
    name = "mean_living_stamina"
    version = "1"

    def measure(self, world):
        values = [agent["stamina"] for agent in world.agents.values() if agent.alive]
        return {"mean": sum(values) / len(values) if values else None,
                "living_count": len(values)}


def main():
    framework = SimulationFramework()
    # Register during startup. A new process must register the same plugin before
    # restoring its checkpoints. This example uses one worker explicitly.
    framework.models.register("example/patient", PatientModel, label="Patient example policy",
                              description="Rest when tired; otherwise wait.")
    framework.measurements.register(MeanLivingStamina())
    scenario = (framework.scenario().set(horizon=5, seed=42)
                .decision_models(human="example/patient", zombie="example/patient"))
    with framework.create(scenario, workers=1) as experiment:
        experiment.advance(5)
        print(json.dumps(experiment.measure(), indent=2))


if __name__ == "__main__":
    main()
