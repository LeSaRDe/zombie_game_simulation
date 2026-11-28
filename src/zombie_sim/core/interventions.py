"""Import compatibility for the retired mutable interventions service."""
from .migration import UnsupportedMutationService


class InterventionService(UnsupportedMutationService):
    """Migrate behavior to an isolated GameRuleSet or ActionHandler."""
