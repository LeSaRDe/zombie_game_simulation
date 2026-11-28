"""Explicit diagnostics for extensions of the former mutable coordinator."""


class LegacyExtensionError(ValueError):
    """An old extension requires migration to an isolated rule/read port."""


MUTATION_SERVICES = frozenset({'transactions', 'actions', 'lifecycle', 'interventions'})
LEGACY_BEHAVIOR_BINDINGS = MUTATION_SERVICES | {'continuous', 'randomness'}


def unsupported_extension(name):
    raise LegacyExtensionError(
        f"Legacy mutable extension {name!r} is unsupported. Move game behavior to "
        "GameRuleSet/ActionHandler and return a TransitionPlan; use an "
        "ObservationService over ReadProjection for read-only views. "
        "Existing ledgers remain available for read-only replay.")


class UnsupportedMutationService:
    """Import compatibility only; never retains a mutable engine reference."""
    def __init__(self, context=None):
        unsupported_extension(type(self).__name__)


LEGACY_PRIVATE_HOOKS = frozenset({
    '_finalize_action_evidence', '_capture_action_agent', '_perceived', '_target',
    '_path_parameters', '_gate_clear', '_construction_footprint', '_knowledge_payload',
    '_action_plan', '_action_plan_checked', '_submit_intents_inner', '_release',
    '_resolve', '_id', '_mark', '_touch', '_bernoulli', '_damage', '_drop',
    '_close_episode', '_die', '_convert', '_expose', '_effect', '_broadcast',
    '_finish', '_geometry_changed', '_apply_intervention', '_nearby', '_view_agent',
    '_evaluate', '_path_position', '_position_at', '_random',
})


def validate_simulation_subclass(implementation, base):
    """Reject undisclosed mutable hooks before initialization or durable writes."""
    for parent in implementation.__mro__:
        if parent is base:
            break
        names = LEGACY_PRIVATE_HOOKS.intersection(parent.__dict__)
        if names:
            unsupported_extension(parent.__qualname__ + '.' + sorted(names)[0])
