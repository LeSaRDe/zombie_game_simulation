"""Inspect identity, conversion and immutable world versions with public APIs.

Run from the repository: PYTHONPATH=src python examples/deep_oop_inspect.py
The history is temporary; use history_path=... to retain your own experiment.
"""
import json
from zombie_sim import Simulation
from zombie_sim.domain_model import HumanState, ZombieState
from zombie_sim.game_rules import ActionHandlerRegistry


def main():
    configuration = {
        'seed': 73, 'decision_mode': 'scripted', 'horizon': 4,
        'incubation_duration': 2, 'execution': {'workers': 1},
        'agents': [{'id': 'doctor', 'type': 'Human', 'role': 'DOCTOR',
                    'x': 10, 'y': 10, 'life': 64, 'stamina': 44, 'infected': True}],
    }
    with Simulation(configuration, workers=1) as simulation:
        original = simulation.state_coordinator.current_world
        original_agent = original.agent('doctor')
        simulation.submit_intents({'id': 'waiting', 'actor': 'doctor', 'action': 'wait',
                                   'parameters': {'duration': 3}})
        simulation.advance_until(2, return_snapshot=False)
        current = simulation.state_coordinator.current_world
        converted_agent = current.agent('doctor')
        assert isinstance(original_agent.current_state, HumanState)
        assert isinstance(converted_agent.current_state, ZombieState)
        assert converted_agent.identity == original_agent.identity
        assert converted_agent.current_state.life == 64
        assert converted_agent.current_state.stamina == 44
        assert original.agent('doctor').current_state.role == 'DOCTOR'
        assert converted_agent.current_state.role is None
        assert sum(stock['inventory'].get('MEDICAL_SUPPLY', 0)
                   for stock in simulation.world_view['stockpiles'].values()) == 1
        handlers = ActionHandlerRegistry()
        print(json.dumps({
            'identity': {'run_id': converted_agent.identity.run_id, 'agent_id': converted_agent.identity.agent_id},
            'before': {'revision': original.revision, 'state_class': type(original_agent.current_state).__name__,
                       'role': original_agent.current_state.role},
            'after': {'revision': current.revision, 'state_class': type(converted_agent.current_state).__name__,
                      'role': converted_agent.current_state.role, 'life': converted_agent.current_state.life,
                      'stamina': converted_agent.current_state.stamina},
            'action_result': simulation.occurrences['action-1']['result'],
            'dropped_stock': {key: value.to_record() for key, value in current.collections['stockpiles'].items()},
            'handlers': {action: type(handlers[action]).__name__ for action in handlers},
        }, indent=2))


if __name__ == '__main__':
    main()
