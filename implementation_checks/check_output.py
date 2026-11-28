"""Optional isolated artifact root for rerunning historical regression checks."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def artifact_output(default):
    """Keep historical defaults unless the qualification runner opts in."""
    path = Path(default)
    override = os.environ.get('ZOMBIE_VERIFICATION_OUTPUT_ROOT')
    if override:
        absolute = path if path.is_absolute() else ROOT / path
        path = Path(override) / absolute.relative_to(ROOT / 'artifacts')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
