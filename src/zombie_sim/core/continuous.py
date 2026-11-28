"""Compatibility read evaluator; staged mutations belong to game_rules."""
from ..game_rules.continuous import ContinuousEvolution
from .migration import unsupported_extension


class ContinuousStateService(ContinuousEvolution):
    """Evaluate detached records through a dated ReadProjection."""

    def _touch(self, aid):
        unsupported_extension("ContinuousStateService._touch")
