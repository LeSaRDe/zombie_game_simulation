"""Independent AEC checks for asynchronous, elapsed-time reward accounting.

Run directly with the training environment. These scenarios use only the public
AEC interface and its declared candidate action encoding.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zombie_sim.learning import DecisionBatchAEC
from zombie_sim.policies import ACTION_NAMES


def scenario(*, infected: bool = False) -> dict:
    first = {"id": "a", "type": "Human", "x": 10, "y": 10, "stamina": 50}
    if infected:
        first["infected"] = True
    return {
        "scenario": "independent_aec_interval_check",
        "seed": 1,
        "horizon": 8,
        "world": {"length": 40, "width": 40},
        "incubation_duration": 1,
        "placement": {"minimum_separation": 0, "cross_type_separation": 0},
        "agents": [first, {"id": "b", "type": "Human", "x": 30, "y": 30, "stamina": 50}],
    }


def select_action(env: DecisionBatchAEC, name: str) -> int:
    observation = env.observe(env.agent_selection)
    column = ACTION_NAMES.index(name)
    for index, allowed in enumerate(observation["action_mask"]):
        if allowed and observation["candidates"][index, column] == 1:
            return index
    raise AssertionError(f"No unmasked {name!r} candidate for {env.agent_selection}")


def assert_five_second_return(env: DecisionBatchAEC) -> dict:
    assert env.agent_selection == "b", env.agent_selection
    _, reward, terminated, truncated, info = env.last()
    assert not terminated and not truncated
    assert math.isclose(info["elapsed"], 5.0, abs_tol=1e-12), info
    # Independently integrate the declared 0.01-per-second survival reward.
    # The default gamma is 0.99 per simulated second, relative to B's action.
    expected = 0.01 * math.expm1(5.0 * math.log(0.99)) / math.log(0.99)
    assert math.isclose(reward, expected, rel_tol=1e-12, abs_tol=1e-12), (reward, expected)
    return {"elapsed": info["elapsed"], "reward": reward, "expected_reward": expected}


def conversion_dead_step() -> dict:
    env = DecisionBatchAEC(scenario(infected=True), controlled_ids=["a", "b"])
    try:
        env.reset(seed=1)
        selected = []
        for _ in range(2):
            selected.append(env.agent_selection)
            env.step(select_action(env, "rest"))
        assert selected == ["a", "b"], selected
        assert env.agent_selection == "a"
        _, _, terminated, truncated, info = env.last()
        assert terminated and not truncated
        assert math.isclose(info["elapsed"], 1.0, abs_tol=1e-12), info
        # A converts after one second. Removing A advances the still-resting B
        # to its next decision at five seconds; all five seconds must count.
        env.step(None)
        return assert_five_second_return(env)
    finally:
        env.close()


def unequal_action_durations() -> dict:
    env = DecisionBatchAEC(scenario(), controlled_ids=["a", "b"])
    try:
        env.reset(seed=1)
        b_has_acted = False
        for _ in range(12):
            if env.agent_selection == "b" and b_has_acted:
                return assert_five_second_return(env)
            action = "rest" if env.agent_selection == "b" else "wait"
            b_has_acted |= env.agent_selection == "b"
            env.step(select_action(env, action))
        raise AssertionError("B did not reach its next decision within twelve selections")
    finally:
        env.close()


if __name__ == "__main__":
    print({"conversion_dead_step": conversion_dead_step(),
           "unequal_action_durations": unequal_action_durations()})
