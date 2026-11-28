"""All 29 action strategies behind one admission/resolution contract.

Handlers calculate changes in an isolated rule workspace. ActionLifecycle owns
admission, reservations, cancellation, evidence and final event publication.
"""
from __future__ import annotations
from abc import ABC
from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction
import math
from types import MappingProxyType
from ..actions import ActionError, _clock, _stamp, _number, ATTACKS
from ..domain import RESOURCES, profile
from ..geometry import distance_to
from ..registry import ACTIONS
from ..domain_model import ActionDefinition


@dataclass
class ActionEvaluation:
    context: object
    actor: dict
    parameters: dict
    target_id: str | None
    target: dict
    collection: str
    duration: Fraction
    properties: dict
    completion: bool = False
    reservations: list = field(default_factory=list)
    dependencies: dict = field(default_factory=dict)
    travel_cost: float = 0.0

    def reserve(self, collection, holder, kind, resource, quantity):
        if self.completion: return
        obj = self.context.state[collection][str(holder)]
        available = (obj.get('inventory', {}).get(resource, 0) - obj.get('reserved', {}).get(resource, 0)
                     if kind == 'inventory' else obj.get('biomass', 0) - obj.get('reserved_biomass', 0)
                     if kind == 'biomass' else obj.get('spit_charges', 0) - obj.get('reserved_charges', 0))
        token = ('stock' if collection == 'stockpiles' else collection) + ':' + str(holder) + ':' + str(resource)
        self.dependencies[token] = dict(collection=collection, holder=str(holder), kind=kind, resource=resource, available=available)
        if available < quantity: raise ActionError('Insufficient unreserved resource')
        self.reservations.append(dict(collection=collection, holder=str(holder), kind=kind, resource=resource, quantity=quantity))


class ActionHandler(ABC):
    action: str
    duration_property: str | None = None

    def __init__(self, definition=None):
        self.definition = definition or ActionDefinition.from_catalog(self.action, ACTIONS[self.action])

    def __setattr__(self, name, value):
        if name == 'definition' and hasattr(self, name):
            raise AttributeError('Action definitions are frozen; compose a new handler explicitly')
        object.__setattr__(self, name, value)

    def prepare(self, evaluation):
        """Additional action-specific preconditions; common checks run first."""

    def declare_access(self, evaluation):
        return deepcopy(evaluation.dependencies)

    def validate_admission(self, context, actor, target_id, parameters, *, completion=False, occurrence=None):
        p = profile(actor, _stamp(context.time)); definition = self.definition
        parameters = deepcopy(parameters)
        expected = p.get(self.duration_property, definition.duration_min.value) if self.duration_property else definition.duration_min.value
        duration = _clock(parameters.get('duration', expected))
        if self.action in ('move', 'wait', 'rest'):
            if not definition.duration_min.value <= duration <= definition.duration_max.value:
                raise ActionError('Action duration is outside the catalog bounds')
        elif duration != _clock(expected): raise ActionError('Action duration must match its resolved contract')
        parameters['duration'] = _stamp(duration)
        reach = p.get('spit_range', 12) if self.action == 'spit' else definition.reach
        target_id, target, collection = context._target(actor, self.action, target_id, reach)
        evaluation = ActionEvaluation(context, actor, parameters, target_id, target, collection, duration, p, completion)
        self.prepare(evaluation)
        if completion and occurrence is not None:
            self._validate_reservations(context, occurrence)
        return dict(parameters=parameters, target=target_id, duration=duration, cost=float(definition.stamina_cost),
                    cooldown=float(definition.cooldown.value), reservations=evaluation.reservations,
                    travel_cost=evaluation.travel_cost, target_collection=collection,
                    _read_dependencies=self.declare_access(evaluation))

    @staticmethod
    def _validate_reservations(context, occurrence):
        for identity in occurrence.get('reservations', []):
            reservation = context.state['reservations'].get(identity)
            if reservation is None or reservation.get('occurrence_id') != occurrence['id']:
                raise ActionError('Occurrence no longer owns its resource reservation')
            obj = context.state[reservation['collection']].get(reservation['holder']); q = reservation['quantity']
            if obj is None: raise ActionError('Reservation holder disappeared')
            if reservation['kind'] == 'inventory' and (obj.get('inventory', {}).get(reservation['resource'], 0) < q or obj.get('reserved', {}).get(reservation['resource'], 0) < q):
                raise ActionError('Reserved inventory is no longer available')
            if reservation['kind'] == 'biomass' and (obj.get('biomass', 0) < q or obj.get('reserved_biomass', 0) < q):
                raise ActionError('Reserved biomass is no longer available')
            if reservation['kind'] == 'charge' and (obj.get('spit_charges', 0) < q or obj.get('reserved_charges', 0) < q):
                raise ActionError('Reserved charge is no longer available')

    def admit(self, lifecycle, intents): return lifecycle.submit_intents(intents)
    def cancel(self, context, occurrence, result): return context._finish(occurrence, result)
    def resolve(self, context, occurrence, actor): return 'SUCCEEDED'


class MoveHandler(ActionHandler):
    action = 'move'
    def prepare(self, e):
        if not e.completion:
            e.travel_cost = e.context._path_parameters(e.actor, self.action, e.parameters, e.duration, e.properties) * e.properties['movement_cost']


class DashHandler(MoveHandler):
    action = 'dash'; duration_property = 'dash_duration'


class WaitHandler(ActionHandler): action = 'wait'
class RestHandler(ActionHandler): action = 'rest'


class AttackHandler(ActionHandler):
    raw_property: str
    potency_property: str | None = None
    human_accuracy = False
    spends_charge = False

    def prepare(self, e):
        if self.spends_charge: e.reserve('agents', e.actor['id'], 'charge', 'SPIT_CHARGE', 1)

    def resolve(self, context, occurrence, actor):
        p = profile(actor, _stamp(context.time)); aid = actor['id']; target_id = occurrence['target']
        target = context.state['agents'][target_id]
        other = context.occurrences.get(target.get('active_action'))
        reciprocal = None
        if other and other['result'] == 'IN_PROGRESS' and other['action'] in ATTACKS and other.get('target') == aid and _clock(other['start_at']) < _clock(occurrence['planned_end']) and _clock(occurrence['start_at']) < _clock(other['planned_end']):
            reciprocal = other
            reciprocal['actor_before_end'] = deepcopy(occurrence['target_before_end'])
            reciprocal['target_before_end'] = deepcopy(occurrence['actor_before_end'])
        if self.spends_charge: context._release(occurrence, consume=True)
        probability = (float(min(Fraction(1), max(Fraction(0), Fraction('.5') + Fraction('.45') * Fraction(str(p['combat_skill'])))))
                       if self.human_accuracy else float(min(Fraction('.95'), max(Fraction(0), Fraction('.6') + Fraction('.3') * Fraction(str(p['attack_skill'])) + Fraction(str(p.get('rally_bonus', 0)))))))
        hit = context._bernoulli(occurrence, 'hit', probability)
        occurrence['hit'] = bool(hit)
        if hit:
            occurrence['damage'] = context._damage(target_id, p[self.raw_property], occurrence['id'])
            # Damage/death is staged first; a lethal hit never draws infection.
            current = context.state['agents'][target_id]
            if self.potency_property and current['life'] > 0 and current['type'] == 'Human' and not current.get('infection_episode'):
                context._expose(target_id, p[self.potency_property], occurrence)
        if reciprocal and reciprocal['result'] == 'IN_PROGRESS':
            context._finish(reciprocal, 'CANCELLED_BY_CONFLICT')
            reciprocal['conflict_winner'] = occurrence['id']; context._mark('occurrences', reciprocal['id'])
        return 'SUCCEEDED' if hit else 'MISSED'


class MeleeHandler(AttackHandler): action = 'melee'; raw_property = 'melee_damage'; human_accuracy = True
class PowerStrikeHandler(AttackHandler): action = 'power_strike'; raw_property = 'strike_damage'; human_accuracy = True
class ClawHandler(AttackHandler): action = 'claw'; raw_property = 'claw_damage'
class BiteHandler(AttackHandler): action = 'bite'; raw_property = 'bite_damage'; potency_property = 'virulence'
class SpitHandler(AttackHandler): action = 'spit'; raw_property = 'spit_damage'; potency_property = 'spit_potency'; spends_charge = True


class PortableResourceHandler(ActionHandler):
    def prepare(self, e):
        resource = e.parameters.get('resource', e.parameters.get('resource_type'))
        if resource not in RESOURCES: raise ActionError('A portable resource type is required')
        quantity = _number(e.parameters.get('quantity'), 'resource quantity', 1, integer=True)
        e.parameters['resource'] = resource
        recipient = e.actor if self.action == 'pickup' else e.target if self.action == 'transfer' else None
        if recipient and sum(recipient.get('inventory', {}).values()) + quantity > recipient['carry_capacity']:
            raise ActionError('Recipient cannot carry the entire quantity')
        e.reserve('stockpiles' if self.action == 'pickup' else 'agents', e.target_id if self.action == 'pickup' else e.actor['id'], 'inventory', resource, quantity)


class PickupHandler(PortableResourceHandler):
    action = 'pickup'
    def resolve(self, c, o, a):
        c._release(o, consume=True); r = o['parameters']['resource']; q = o['parameters']['quantity']
        a['inventory'][r] = a['inventory'].get(r, 0) + q; c._mark('agents', a['id'])
        return 'SUCCEEDED'


class DropHandler(PortableResourceHandler):
    action = 'drop'
    def resolve(self, c, o, a):
        c._release(o, consume=True)
        o['stockpile_id'] = c._drop(a, {o['parameters']['resource']: o['parameters']['quantity']})
        return 'SUCCEEDED'


class TransferHandler(PortableResourceHandler):
    action = 'transfer'
    def resolve(self, c, o, a):
        c._release(o, consume=True); r = o['parameters']['resource']; q = o['parameters']['quantity']
        target = c._touch(o['target']); target['inventory'][r] = target['inventory'].get(r, 0) + q
        return 'SUCCEEDED'


class EatHandler(ActionHandler):
    action = 'eat'
    def prepare(self, e):
        if e.actor.get('hunger', 0) <= 0: raise ActionError('Eating requires positive hunger')
        e.reserve('agents', e.actor['id'], 'inventory', 'FOOD', 1)
    def resolve(self, c, o, a):
        prepared = c.consume_prepared_effect(o, a, profile(a, _stamp(c.time)))
        c._release(o, consume=True)
        a['hunger'] = prepared['hunger'] if prepared is not None else max(0., a['hunger'] - 40)
        a['_hunger_generation'] = a.get('_hunger_generation', 0) + 1
        a['starvation_started_at'] = None; a['next_starvation_damage_at'] = None
        c._schedule_starvation(a)
        return 'SUCCEEDED'


class MedicalHandler(ActionHandler):
    def prepare(self, e): e.reserve('agents', e.actor['id'], 'inventory', 'MEDICAL_SUPPLY', 1)


class FirstAidHandler(MedicalHandler):
    action = 'first_aid'
    def prepare(self, e):
        if e.target['life'] >= 100: raise ActionError('First aid requires an injured target')
        super().prepare(e)
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); prepared = c.consume_prepared_effect(o, a, p)
        target = c._touch(o['target']); c._release(o, consume=True)
        if prepared is not None: o['healing'] = prepared['healing']; target['life'] = prepared['life']
        else:
            healing = 10 + math.floor(20 * p['medical_skill'] + .5)
            o['healing'] = min(100 - target['life'], healing); target['life'] += o['healing']
        return 'SUCCEEDED'


class TreatInfectionHandler(MedicalHandler):
    action = 'treat_infection'; duration_property = 'treatment_duration'
    def prepare(self, e):
        episode = e.context.state['episodes'].get(e.target.get('infection_episode'))
        if not episode or e.context.time >= _clock(episode['conversion_due_at']):
            raise ActionError('Treatment requires a living infected Human before its deadline')
        e.reserve('agents', e.actor['id'], 'inventory', 'MEDICAL_SUPPLY', int(e.properties.get('treatment_cost', 1)))
    def resolve(self, c, o, a):
        target = c._touch(o['target']); c._release(o, consume=True)
        eid = target['infection_episode']; episode = c.state['episodes'][eid]
        episode.update(outcome='CURED', ended_at=_stamp(c.time), end_revision=c.revision + 1)
        target['infection_episode'] = None
        c._effects_buffer.append(dict(kind='cure', agent_id=o['target'], actor=a['id'], target=o['target'], episode_id=eid, action_id=o['id'], before_state=deepcopy(o['target_before_end']), after_state=c._capture_action_agent(o['target'], after=True)))
        o['episode_id'] = eid; o['cure'] = True; c._mark('episodes', eid)
        return 'SUCCEEDED'


class ProphylaxisHandler(MedicalHandler):
    action = 'prophylaxis'
    def prepare(self, e):
        if e.target.get('infection_episode'): raise ActionError('Prophylaxis requires an uninfected Human')
        super().prepare(e)
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); c._release(o, consume=True)
        c._effect(o['target'], 'prophylaxis', p['prophylaxis_resistance'], p['prophylaxis_duration'], o['id'])
        return 'SUCCEEDED'


class FeedHandler(ActionHandler):
    action = 'feed'
    def prepare(self, e):
        if e.actor['life'] >= 100 and e.actor['stamina'] >= 100: raise ActionError('Feeding requires lost life or stamina')
        e.reserve('remains', e.target_id, 'biomass', 'BIOMASS', 1)
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); c._release(o, consume=True)
        o['healing'] = min(100 - a['life'], p['feed_healing'])
        a['life'] += o['healing']; a['stamina'] = min(100., a['stamina'] + p['feed_energy'])
        return 'SUCCEEDED'


class OpenGateHandler(ActionHandler):
    action = 'open_gate'; resulting_mode = 'OPEN'
    def prepare(self, e):
        if e.target.get('type') != 'Gate' or e.target.get('mode') != 'CLOSED': raise ActionError('Opening requires a CLOSED gate')
    def resolve(self, c, o, a):
        c.state['barriers'][o['target']]['mode'] = self.resulting_mode
        c._mark('barriers', o['target']); c._geometry_changed()
        return 'SUCCEEDED'


class CloseGateHandler(OpenGateHandler):
    action = 'close_gate'; resulting_mode = 'CLOSED'
    def prepare(self, e):
        if e.target.get('type') != 'Gate' or e.target.get('mode') != 'OPEN' or not e.context._gate_clear(e.target):
            raise ActionError('Closing requires an unoccupied OPEN gate without an overlapping barricade')


class SmashHandler(ActionHandler):
    action = 'smash'; damage_property = None
    def prepare(self, e):
        t = e.target
        if not (t.get('type') == 'Gate' and t.get('mode') == 'CLOSED' or t.get('type') == 'Barricade' and t.get('integrity', 0) > 0):
            raise ActionError('Barrier attack requires a CLOSED gate or intact barricade')
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); prepared = c.consume_prepared_effect(o, a, p); b = c.state['barriers'][o['target']]
        if prepared is not None: b['integrity'] = prepared['integrity']; o['integrity_damage'] = prepared['integrity_damage']
        else:
            amount = min(b['integrity'], p[self.damage_property] if self.damage_property else 20)
            b['integrity'] -= amount; o['integrity_damage'] = amount
        if b['type'] == 'Gate' and b['integrity'] == 0: b['mode'] = 'BREACHED'
        c._mark('barriers', o['target']); c._geometry_changed()
        return 'SUCCEEDED'


class DemolishHandler(SmashHandler): action = 'demolish'; damage_property = 'demolish_damage'


class RepairBarrierHandler(ActionHandler):
    action = 'repair_barrier'
    def prepare(self, e):
        t = e.target; kind = t.get('type')
        if kind not in ('Gate', 'Barricade') or t.get('integrity', 0) >= t.get('max_integrity', 0) or kind == 'Barricade' and t.get('integrity', 0) <= 0:
            raise ActionError('Repair requires a damaged gate or intact damaged barricade')
        if kind == 'Gate' and t.get('mode') == 'BREACHED' and not e.context._gate_clear(t): raise ActionError('Breached gate restoration requires an unoccupied footprint')
        e.reserve('agents', e.actor['id'], 'inventory', 'MATERIAL', int(e.properties.get('repair_material_cost', 1)))
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); prepared = c.consume_prepared_effect(o, a, p)
        c._release(o, consume=True); b = c.state['barriers'][o['target']]
        if prepared is not None: b['integrity'] = prepared['integrity']; o['integrity_restored'] = prepared['integrity_restored']
        else:
            amount = min(b['max_integrity'] - b['integrity'], p['repair_amount'])
            b['integrity'] += amount; o['integrity_restored'] = amount
        if b['type'] == 'Gate' and b['mode'] == 'BREACHED' and b['integrity'] > 0: b['mode'] = 'OPEN'
        c._mark('barriers', o['target']); c._geometry_changed()
        return 'SUCCEEDED'


class BuildBarricadeHandler(ActionHandler):
    action = 'build_barricade'
    def prepare(self, e):
        e.context._construction_footprint(e.actor, e.parameters)
        e.reserve('agents', e.actor['id'], 'inventory', 'MATERIAL', int(e.properties.get('build_material_cost', 2)))
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); c._release(o, consume=True); identity = c._id('barricade')
        c.state['barriers'][identity] = dict(id=identity, type='Barricade', footprint=o['parameters']['footprint'], integrity=p['build_integrity'], max_integrity=p['build_integrity'], creator_id=a['id'], created_at=_stamp(c.time))
        o['barrier_id'] = identity; c._mark('barriers', identity); c._geometry_changed()
        return 'SUCCEEDED'


class GuardHandler(ActionHandler):
    action = 'guard'; value_property = 'guard_resistance'; duration_property_effect = 'guard_duration'
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); c._effect(a['id'], self.action, p[self.value_property], p[self.duration_property_effect], o['id'])
        return 'SUCCEEDED'


class ReconHandler(GuardHandler): action = 'recon'; value_property = 'recon_radius'; duration_property_effect = 'recon_duration'


class RallyHandler(ActionHandler):
    action = 'rally'
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time))
        for target in list(c.state['agents'].values()):
            if target['id'] != a['id'] and target['life'] > 0 and target['type'] == 'Zombie' and distance_to(a, c._view_agent(target['id'])) <= p['rally_radius']:
                c._effect(target['id'], 'rallied', p['rally_hit_bonus'], p['rally_duration'], o['id'])
        c._broadcast(a['id'], 'RALLY', dict(position=dict(x=a['x'], y=a['y']), observed_at=_stamp(c.time)), p['rally_radius'], p['rally_duration'], o['id'])
        return 'SUCCEEDED'


class MarkTargetHandler(ActionHandler):
    action = 'mark_target'
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); target = c._view_agent(o['target'])
        payload = dict(entity_id=o['target'], type=target['type'], position=dict(x=target['x'], y=target['y']), observed_at=_stamp(c.time))
        c._broadcast(a['id'], 'TARGET_REPORT', payload, p['mark_radius'], 10, o['id'])
        return 'SUCCEEDED'


class SignalHandler(ActionHandler):
    action = 'signal'
    def prepare(self, e):
        if not e.completion: e.context._knowledge_payload(e.actor, self.action, e.parameters)
    def resolve(self, c, o, a):
        p = profile(a, _stamp(c.time)); parameters = o['parameters']
        payload = parameters.get('payload', {}) or dict(position=dict(x=a['x'], y=a['y']), observed_at=_stamp(c.time))
        c._broadcast(a['id'], 'HUNT_CUE' if self.action == 'scream' else parameters.get('kind', 'WARNING'), payload,
                     p['call_radius'] if self.action == 'scream' else 40, p['call_ttl'] if self.action == 'scream' else 8, o['id'])
        return 'SUCCEEDED'


class ScreamHandler(SignalHandler): action = 'scream'


class ActionHandlerRegistry:
    def __init__(self, handlers=None):
        implementations = (MoveHandler, WaitHandler, RestHandler, SignalHandler, MeleeHandler,
            PickupHandler, DropHandler, TransferHandler, EatHandler, FirstAidHandler, OpenGateHandler,
            CloseGateHandler, ClawHandler, BiteHandler, FeedHandler, SmashHandler, TreatInfectionHandler,
            ProphylaxisHandler, PowerStrikeHandler, GuardHandler, ReconHandler, MarkTargetHandler,
            BuildBarricadeHandler, RepairBarrierHandler, RallyHandler, DemolishHandler, DashHandler,
            SpitHandler, ScreamHandler)
        self._handlers = {cls.action: cls() for cls in implementations} if handlers is None else dict(handlers)
        if set(self._handlers) != set(ACTIONS): raise ValueError('Handler registry must match all 29 frozen action definitions exactly')
        if any(not isinstance(handler, ActionHandler) or name != handler.action for name, handler in self._handlers.items()):
            raise TypeError('Every action requires its matching ActionHandler strategy')
        self._handlers = MappingProxyType(self._handlers)
    def __getitem__(self, action): return self._handlers[action]
    def __iter__(self): return iter(self._handlers)
    def __len__(self): return len(self._handlers)
