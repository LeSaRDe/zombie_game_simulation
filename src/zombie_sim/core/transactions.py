"""Import compatibility for the retired mutable transactions service."""
from .migration import UnsupportedMutationService


class TransactionService(UnsupportedMutationService):
    """Migrate behavior to an isolated GameRuleSet or ActionHandler."""
