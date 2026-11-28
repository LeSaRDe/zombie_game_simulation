"""Truthful executable provenance for explicit runtime-v2 continuation.

Legacy checkpoints did not pin the whole engine. Their absence of a build
manifest is recorded as legacy provenance, never replaced by an invented hash.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from ..storage import canonical

ENGINE_COMPATIBILITY='zombie-sim/engine-v2'


def implementation_manifest():
    root=Path(__file__).resolve().parents[1]
    names={'engine.py','runtime.py','domain.py','geometry.py','config.py','registry.py',
           'parallel.py','policies.py','learning.py','modeling.py','entities.py',
           'model_catalog.py','artifact_pins.py','history_sequence.py','storage.py',
           'initial_state.py','role_allocation.py','actions.py'}
    for directory in ('core','domain_model','game_rules','state_management','execution','persistence'):
        names.update(str(path.relative_to(root)) for path in (root/directory).rglob('*.py'))
    files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sorted(names) if (root/name).is_file()}
    document={'schema':'zombie-sim/implementation-manifest-v1','compatibility':ENGINE_COMPATIBILITY,'files':files}
    return {**document,'sha256':hashlib.sha256(canonical(document).encode()).hexdigest()}


def validate_implementation(record):
    from ..artifact_pins import ArtifactMismatch
    if not isinstance(record,dict):raise ArtifactMismatch('engine_implementation','Missing runtime-v2 implementation manifest')
    document={key:value for key,value in record.items() if key!='sha256'}
    if hashlib.sha256(canonical(document).encode()).hexdigest()!=record.get('sha256'):
        raise ArtifactMismatch('engine_implementation','Implementation manifest checksum mismatch')
    if record!=implementation_manifest():
        raise ArtifactMismatch('engine_implementation','Runtime implementation differs; use the original build or an explicitly verified migration')
