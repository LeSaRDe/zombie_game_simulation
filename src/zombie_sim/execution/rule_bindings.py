"""Inspectable rule implementations, recorded separately from game configuration.

Rules never read implementation files. The composition/restart boundary does
that once, before creating a ledger. Stateful strategy instances require an
explicit runtime codec instead of silently losing parameters on continuation.
"""
from __future__ import annotations
import hashlib
import inspect

from ..core.composition import ServiceBindingMismatch
from ..game_rules import GameRuleSet, ActionHandlerRegistry


def _identity(implementation):
    lineage = []
    for cls in implementation.__mro__:
        if cls is object or cls.__module__ == 'abc':
            continue
        filename = inspect.getsourcefile(cls)
        if filename is None:
            raise ValueError('Custom rule implementations need inspectable source for exact restart')
        with open(filename, 'rb') as source:
            digest = hashlib.sha256(source.read()).hexdigest()
        lineage.append({'module': cls.__module__, 'class': cls.__qualname__, 'file_sha256': digest})
    return lineage


def rule_manifest(rules):
    if set(vars(rules)) != {'handlers'}:
        raise ValueError('Rule sets cannot carry unrecorded instance state; use recorded scenario parameters')
    defaults = ActionHandlerRegistry()
    custom = {}
    for action in rules.handlers:
        handler = rules.handlers[action]
        if set(vars(handler)) != {'definition'}:
            raise ValueError(f'Handler {action!r} cannot carry unrecorded instance state; use recorded scenario parameters')
        if handler.definition != defaults[action].definition:
            raise ValueError(f'Handler {action!r} must preserve its frozen ontology action definition')
        if type(handler) is not type(defaults[action]):
            custom[action] = _identity(type(handler))
    if not custom and type(rules) is GameRuleSet and type(rules.handlers) is ActionHandlerRegistry:
        return None
    return {'schema': 'zombie-sim/rule-bindings-v1', 'rules': _identity(type(rules)),
            'registry': _identity(type(rules.handlers)), 'handlers': custom}


def validate_rule_restart(recorded, rules=None):
    if recorded != rule_manifest(rules if rules is not None else GameRuleSet()):
        raise ServiceBindingMismatch('Rule bindings differ; provide the original explicit rule_set to restore or branch')
