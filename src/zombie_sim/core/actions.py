"""Import compatibility for the retired mutable actions service."""
from .migration import UnsupportedMutationService


class ActionService(UnsupportedMutationService):
    """Migrate behavior to an isolated GameRuleSet or ActionHandler."""
