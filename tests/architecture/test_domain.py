"""Behavioral contracts for immutable domain values and their legacy boundary."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import unittest

from zombie_sim.domain import capabilities, make_agent, profile
from zombie_sim.domain_model import (Agent, AgentState, CodecError, DomainCodec, DomainEvent,
                                     ExactTime, HumanState, ZombieState, RoleRegistry,
                                     HumanRoleDefinition, ZombieRoleDefinition, ScheduledTask)
from zombie_sim.domain_model.activities import RejectedActionIntent
from zombie_sim.engine import Simulation
from zombie_sim.testing import fixture_config


class DomainValueTests(unittest.TestCase):
    def setUp(self):
        self.roles = RoleRegistry.default()
        self.codec = DomainCodec(self.roles)

    def test_all_roles_preserve_capabilities_profiles_and_wire_records(self):
        cases = [("Human", None), ("Zombie", None)] + [(role.compatible_type, role.role_id) for role in self.roles.definitions]
        for kind, role in cases:
            with self.subTest(kind=kind, role=role):
                raw = make_agent("7", kind, role)
                raw.update(_evaluated_at="7/3", _generation=3, _hunger_generation=2, revision=5)
                agent = Agent.from_record(raw, "run-1", roles=self.roles)
                self.assertEqual(agent.to_record(), raw)
                state = agent.current_state
                self.assertIsInstance(state, HumanState if kind == "Human" else ZombieState)
                self.assertEqual(list(state.capabilities), capabilities(raw))
                self.assertEqual(state.effective_profile().to_record(), profile(raw))
                if role:
                    definition = state.role_assignment.definition
                    self.assertIsInstance(definition, HumanRoleDefinition if kind == "Human" else ZombieRoleDefinition)
                    with self.assertRaises(FrozenInstanceError):
                        definition.role_id = "OTHER"

    def test_nested_values_and_encoded_records_are_detached(self):
        raw = make_agent("7", "Human", "DOCTOR", model_memory={"seen": ["z1"]})
        agent = Agent.from_record(raw, "run-1", roles=self.roles)
        before = agent.to_record()
        raw["inventory"]["MEDICAL_SUPPLY"] = 8
        raw["model_memory"]["seen"].append("z2")
        encoded = agent.to_record()
        encoded["inventory"]["MEDICAL_SUPPLY"] = 20
        encoded["model_memory"]["seen"].append("z3")
        self.assertEqual(agent.to_record(), before)
        with self.assertRaises(FrozenInstanceError):
            agent.current_state.life = 0

    def test_spitter_reservoir_is_per_assignment(self):
        a = Agent.from_record(make_agent("1", "Zombie", "SPITTER"), "run", roles=self.roles)
        b = Agent.from_record(make_agent("2", "Zombie", "SPITTER", spit_charges=1, next_charge_at="30"), "run", roles=self.roles)
        self.assertIs(a.current_state.role_assignment.definition, b.current_state.role_assignment.definition)
        self.assertIsNot(a.current_state.role_assignment.state, b.current_state.role_assignment.state)
        self.assertEqual(a.current_state.role_state.charges, 3)
        self.assertEqual(b.current_state.role_state.charges, 1)
        self.assertNotIn("spit_charges", a.current_state.role_assignment.definition.parameters.to_record())

    def test_derived_status_and_applicable_fields_cannot_disagree(self):
        raw = make_agent("1")
        for mutation in ({"status": "ACTIVE"}, {"role": "TYRANT"}, {"life": 101}, {"action_state": "BUSY"}, {"unknown_runtime_secret": 42}):
            with self.subTest(mutation=mutation), self.assertRaises(CodecError):
                Agent.from_record({**raw, **mutation}, "run", roles=self.roles)
        zombie = make_agent("2", "Zombie")
        with self.assertRaises(CodecError):
            Agent.from_record({**zombie, "hunger": 0}, "run", roles=self.roles)
        with self.assertRaises(CodecError):
            Agent.from_record({**raw, "reserved": {"FOOD": 1}}, "run", roles=self.roles)

    def test_identity_scope_and_terminal_death(self):
        raw = make_agent("7")
        alive = Agent.from_record(raw, "run-a", roles=self.roles)
        alternate = Agent.from_record(raw, "run-b", roles=self.roles)
        self.assertNotEqual(alive.identity, alternate.identity)
        terminal = {**raw, "life": 0, "model_assignment": None, "death_at": "5", "death_cause": "hit"}
        dead = alive.with_state(AgentState.from_record(terminal, roles=self.roles))
        self.assertIsInstance(dead.current_state, HumanState)
        self.assertEqual(dead.identity, alive.identity)
        self.assertEqual(dead.current_state.status, "DEAD")
        self.assertEqual(dead.current_state.capabilities, ())
        with self.assertRaises(CodecError):
            dead.with_state(alive.current_state)
        self.assertEqual(alive.current_state.life, 100)

    def test_effects_use_exact_exclusive_end_without_changing_prior_state(self):
        raw = make_agent("7", "Human", "WARRIOR", effects={"guard": {"kind": "guard", "value": .6, "start_at": "1/3", "end_at": "2/3", "source": "guard1"}})
        state = AgentState.from_record(raw, roles=self.roles)
        self.assertEqual(state.effective_profile("1/3").damage_resistance, .6)
        self.assertEqual(state.effective_profile("2/3").damage_resistance, .2)
        self.assertEqual(state.to_record(), raw)

    def test_profile_cache_preserves_numeric_wire_types_and_rejects_boolean(self):
        from zombie_sim.domain_model.profiles import ProfileValues
        integral = ProfileValues(base_speed=3)
        decimal = ProfileValues(base_speed=3.0)
        self.assertNotEqual(integral, decimal)
        self.assertEqual(integral, ProfileValues(base_speed=3))
        self.assertEqual(hash(integral), hash(ProfileValues(base_speed=3)))
        self.assertIs(integral._cache_key, integral._cache_key)
        self.assertEqual(replace(integral, base_speed=3.0), decimal)
        raw = make_agent("7")
        self.assertIs(type(profile({**raw, "profile": {"base_speed": 3}})["base_speed"]), int)
        self.assertIs(type(profile({**raw, "profile": {"base_speed": 3.0}})["base_speed"]), float)
        profile({**raw, "profile": {"infection_resistance": 1}})
        with self.assertRaises(CodecError):
            profile({**raw, "profile": {"infection_resistance": True}})

    def test_exact_times_preserve_legacy_tokens_and_order(self):
        for token in ("2/3", "1.250", 3, 3.5):
            self.assertEqual(ExactTime.parse(token).to_record(), token)
        self.assertEqual(ExactTime.parse("1/3").plus("2/3").value, Fraction(1))
        task = (Fraction(1, 3), 3, .5, 9, {"kind": "conversion", "agent": "7", "episode": "e1"})
        decoded = ScheduledTask.from_record(task)
        self.assertEqual(decoded.order_key, task[:4])
        self.assertEqual(decoded.to_record(), ["1/3", 3, .5, 9, task[4]])

    def test_real_model_run_all_records_and_event_payloads_round_trip(self):
        sim = Simulation({"preset": "small"}, workers=1)
        self.addCleanup(sim.close)
        sim.advance_until(5)
        for collection in ("agents", "barriers", "shelters", "stockpiles", "remains", "episodes", "signals", "reservations", "interventions", "intents", "occurrences"):
            for key, raw in sim.state.get(collection, {}).items():
                with self.subTest(collection=collection, key=key):
                    decoded = self.codec.decode_entity(collection, raw, sim.state["run_id"])
                    self.assertEqual(decoded.to_record(), raw)
        for event in sim.events:
            self.assertEqual(DomainEvent.from_record(event).to_record(), event)

    def test_conversion_history_keeps_human_evidence_and_zombie_current_state(self):
        config = fixture_config({"agents": [{"id": "h", "type": "Human", "role": "DOCTOR", "x": 10, "y": 10, "life": 64, "stamina": 32, "infection": {"onset_at": "0", "incubation_duration": "3"}}]}, {"decision_mode": "scripted"})
        sim = Simulation(config, workers=1)
        self.addCleanup(sim.close)
        before = Agent.from_record(sim.state["agents"]["h"], sim.state["run_id"], roles=self.roles)
        sim.advance_until(3)
        after = Agent.from_record(sim.state["agents"]["h"], sim.state["run_id"], roles=self.roles)
        self.assertEqual(before.identity, after.identity)
        self.assertIsInstance(before.current_state, HumanState)
        self.assertIsInstance(after.current_state, ZombieState)
        self.assertEqual((after.current_state.life, after.current_state.stamina), (64, 32))
        for event in sim.events:
            self.assertEqual(DomainEvent.from_record(event).to_record(), event)

    def test_rejected_malformed_submission_is_audit_evidence_not_executable_parameters(self):
        raw = {"id": "bad", "actor": "7", "action": "not-an-action", "parameters": "malformed", "unknown": [1], "proposed_at": "0", "audit_reason": "invalid", "outcome": {"id": "bad", "actor": "7", "status": "REJECTED", "reason": "PRECONDITION_FAILED"}}
        decoded = self.codec.decode_entity("intents", raw, "run")
        self.assertIsInstance(decoded, RejectedActionIntent)
        self.assertEqual(decoded.to_record(), raw)
        raw["unknown"].append(2)
        self.assertEqual(decoded.to_record()["unknown"], [1])

    def test_runtime_unknown_assignment_cannot_silently_escape_snapshot(self):
        from zombie_sim.state_management import RuntimeState
        runtime = RuntimeState.from_attributes({"time": "1/3", "memories": {"h": {"seen": (1, 2)}}})
        with self.assertRaisesRegex(AttributeError, "Unknown runtime field"):
            runtime.unregistered_extension = {"lost": True}
        self.assertEqual(runtime.snapshot().to_attributes()["time"], Fraction(1, 3))
        self.assertEqual(runtime.snapshot().fork().memories["h"]["seen"], (1, 2))


if __name__ == "__main__":
    unittest.main()
