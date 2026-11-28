"""Import compatibility for the retired mutable lifecycle service."""
from .migration import UnsupportedMutationService


class LifecycleService(UnsupportedMutationService):
    """Migrate behavior to an isolated GameRuleSet or ActionHandler."""
