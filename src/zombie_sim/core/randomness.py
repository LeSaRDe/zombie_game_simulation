"""Pure semantic variates; draw evidence belongs to isolated rule planning."""
from fractions import Fraction
import hashlib


class RandomService:
    """No engine reference, mutable world, history, or publishing capability."""

    def __init__(self, context=None):
        if context is not None:
            from .migration import unsupported_extension
            unsupported_extension('RandomService mutable context')

    @staticmethod
    def value(seed, domain, key):
        digest = hashlib.sha256(f'{seed}:{domain}:{key}'.encode()).digest()
        return int.from_bytes(digest[:8], 'big') / 2**64

    @staticmethod
    def controlled_values(draws, existing=None):
        """Validate and return new controlled inputs without mutating the caller."""
        values = dict(existing or {})
        for draw in draws:
            channel = draw['channel']
            value = float(Fraction(str(draw['value'])))
            if channel not in {'hit', 'infection'} or not 0 <= value < 1:
                raise ValueError('Controlled draws require hit/infection and a finite value in [0, 1)')
            values[(str(draw['intent']), channel)] = value
        return values
