"""Bounded cross-entity validation before a transaction reaches persistence.

Only changed records and their directly referenced owners are inspected. The
reservation-holder index avoids scanning accumulated event/action history.
"""
from __future__ import annotations
from collections import Counter


class InvalidTransition(ValueError):
    """A proposed successor violates identity or referential consistency."""


def validate_transition(previous, world, changes):
    candidates={(change.collection,change.identity) for change in changes}
    holders=set()

    def entity(collection,identity):
        value=world.collections.get(collection,{}).get(str(identity))
        if value is None:raise InvalidTransition(f'Missing {collection} reference {identity!r}')
        return value

    for change in changes:
        if change.collection not in world.collections:
            raise InvalidTransition(f'Unknown collection {change.collection!r}')
        old=previous.collections[change.collection].get(change.identity)
        if change.value is None and old is not None and change.collection in {'agents','occurrences','episodes','intents'}:
            raise InvalidTransition('Persistent identities and causal records cannot be deleted')
        if change.value is not None:
            record=change.value.to_record()
            if str(record.get('id'))!=change.identity:
                raise InvalidTransition('Collection key and entity identity disagree')
        for value in (old,change.value):
            if value is None:continue
            if change.collection=='agents':
                state=value.current_state
                if state.active_action:candidates.add(('occurrences',state.active_action))
                if state.infection_episode:candidates.add(('episodes',state.infection_episode))
                holders.add(('agents',change.identity))
            elif change.collection=='reservations':
                candidates.add(('occurrences',value.occurrence_id))
                candidates.add(('agents',value.actor))
                holders.add((value.collection,value.holder))
            elif change.collection=='occurrences':
                candidates.add(('agents',value.actor))
                candidates.update(('reservations',key) for key in value.reservations if key in world.collections['reservations'])
            elif change.collection=='episodes':candidates.add(('agents',value.agent_id))
            elif change.collection in {'stockpiles','remains'}:holders.add((change.collection,change.identity))

    for collection,identity in candidates:
        value=world.collections[collection].get(identity)
        if value is None:continue  # Removed reservations are checked through their owner.
        if collection=='agents':
            state=value.current_state
            state.validate()
            if value.identity.run_id!=world.run_id:
                raise InvalidTransition('Agent identity belongs to a different run')
            old=previous.collections['agents'].get(identity)
            if old is not None:old.with_state(state)  # Enforces terminal death/type/location.
            if state.active_action:
                action=entity('occurrences',state.active_action)
                if action.actor!=identity or action.result!='IN_PROGRESS':
                    raise InvalidTransition('Active action is not an ongoing occurrence owned by this agent')
            if state.infection_episode:
                episode=entity('episodes',state.infection_episode)
                if episode.agent_id!=identity or episode.ended_at is not None or episode.outcome not in {None,'ONGOING'}:
                    raise InvalidTransition('Current infection points to another host or a closed episode')
            if state.model_assignment and (old is None or old.current_state.model_assignment!=state.model_assignment or old.current_state.biological_type!=state.biological_type):
                from ..domain import decision_model_assignment
                assignment=state.model_assignment.to_record()
                decision_model_assignment(assignment['model_id'],assignment.get('version'),assignment.get('parameters'),agent_type=state.biological_type)
        elif collection=='occurrences':
            actor=entity('agents',value.actor).current_state
            intent=entity('intents',value.intent_id)
            if intent.actor!=value.actor:
                raise InvalidTransition('Occurrence and admitted intent have different actors')
            if value.result=='IN_PROGRESS' and (not actor.alive or actor.active_action!=identity):
                raise InvalidTransition('Ongoing occurrence is not the living actor\'s active action')
            if value.target is not None and value.target_collection:
                entity(value.target_collection,value.target)
            for reservation_id in value.reservations:
                reservation=entity('reservations',reservation_id)
                if reservation.occurrence_id!=identity or reservation.actor!=value.actor:
                    raise InvalidTransition('Occurrence references an unowned reservation')
        elif collection=='episodes':
            host=entity('agents',value.agent_id).current_state
            if value.ended_at is None and value.outcome in {None,'ONGOING'} and host.infection_episode!=identity:
                raise InvalidTransition('Ongoing episode is not installed on its host')
        elif collection=='reservations':
            occurrence=entity('occurrences',value.occurrence_id)
            entity('agents',value.actor)
            holder=entity(value.collection,value.holder).to_record()
            if occurrence.result!='IN_PROGRESS' or identity not in occurrence.reservations or occurrence.actor!=value.actor:
                raise InvalidTransition('Reservation has no matching ongoing owner')
            if value.kind=='inventory':
                from ..domain_model.resources import RESOURCES
                if value.collection not in {'agents','stockpiles'} or value.resource not in RESOURCES or 'inventory' not in holder:
                    raise InvalidTransition('Inventory reservation has an incompatible resource holder')
            elif value.kind=='biomass':
                if value.collection!='remains' or value.resource!='BIOMASS':raise InvalidTransition('Invalid biomass reservation')
            elif value.kind=='charge':
                if value.collection!='agents' or value.resource!='SPIT_CHARGE' or holder.get('role')!='SPITTER':raise InvalidTransition('Invalid Spitter charge reservation')
            else:raise InvalidTransition('Unknown reservation kind')

    for collection,identity in holders:
        value=world.collections.get(collection,{}).get(identity)
        reservations=world.reservations_by_holder.get((collection,identity),())
        if value is None:
            if reservations:raise InvalidTransition('A removed entity still holds reservations')
            continue
        record=value.to_record()
        totals=Counter()
        for key in reservations:
            reservation=entity('reservations',key)
            totals[reservation.resource]+=reservation.quantity
        if 'inventory' in record:
            for resource,quantity in record.get('reserved',{}).items():
                if quantity!=totals[resource]:raise InvalidTransition('Reserved inventory disagrees with owned reservations')
        if record.get('reserved_biomass',0)!=totals['BIOMASS']:
            raise InvalidTransition('Reserved biomass disagrees with owned reservations')
        if record.get('reserved_charges',0)!=totals['SPIT_CHARGE']:
            raise InvalidTransition('Reserved charges disagree with owned reservations')
