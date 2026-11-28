"""Read-only customization seam over the shared observation implementation."""
from ..game_rules.observations import ObservationBuilder


class ObservationService(ObservationBuilder):
    """Receives a ReadProjection with no engine, repository or commit methods."""
