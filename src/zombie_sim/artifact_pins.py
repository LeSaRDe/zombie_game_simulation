"""Checkpoint pins for the actual ontology and executable model artifacts."""
from __future__ import annotations
import hashlib
import inspect
import json
import os
from pathlib import Path

from .registry import source_hashes
from .storage import canonical


class ArtifactMismatch(ValueError):
    code="ARTIFACT_MISMATCH"
    def __init__(self,component,message):
        self.component=component
        super().__init__(message)


def ontology_pin():
    semantic_names={"ontology.ttl","ontology.owl","catalog.ttl","baseline.ttl","shapes.ttl","ontology_markdown"}
    return {key:value for key,value in source_hashes().items() if key in semantic_names}


def model_artifact(model_id,parameters=None):
    from .policies import create_model
    model=create_model(model_id,parameters)
    manifest=model.manifest()
    source=Path(inspect.getfile(type(model)))
    return {"assignment_id":model_id,"manifest":manifest,
            "implementation_sha256":hashlib.sha256(source.read_bytes()).hexdigest()}


def write_pins(sim,checkpoint_path):
    checkpoint_path=Path(checkpoint_path)
    directory=checkpoint_path.with_suffix(".models")
    directory.mkdir(parents=True,exist_ok=True)
    models=[]
    assignments={canonical({"model_id":a["model_assignment"]["model_id"],"parameters":a["model_assignment"].get("parameters")})
                 for a in sim.state["agents"].values() if a.get("model_assignment")}
    for encoded in sorted(assignments):
        assignment=json.loads(encoded);name=assignment["model_id"]
        artifact=model_artifact(name,assignment["parameters"]);content=canonical(artifact).encode()
        digest=hashlib.sha256(content).hexdigest();path=directory/(digest+".json")
        # Content-addressed artifacts keep the previous checkpoint usable if a
        # process stops before the new envelope is atomically published.
        temporary=path.with_suffix(".partial")
        with temporary.open("wb") as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        models.append({**assignment,"path":str(path.relative_to(checkpoint_path.parent)),"sha256":digest})
    descriptor=os.open(directory,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return {"schema":"zombie-sim/artifact-pins-v1","ontology":ontology_pin(),"models":models}


def validate_pins(pins,checkpoint_path):
    if pins.get("schema")!="zombie-sim/artifact-pins-v1":
        raise ArtifactMismatch("ontology_fingerprint","Unknown checkpoint artifact pin schema")
    if pins["ontology"]!=ontology_pin():
        raise ArtifactMismatch("ontology_fingerprint","Checkpoint ontology fingerprint differs from the installed semantic sources")
    for record in pins["models"]:
        path=Path(checkpoint_path).parent/record["path"]
        try:
            content=path.read_bytes()
            valid=hashlib.sha256(content).hexdigest()==record["sha256"]
            if valid:valid=json.loads(content)==model_artifact(record["model_id"],record.get("parameters"))
        except (OSError,ValueError,TypeError):valid=False
        if not valid:
            raise ArtifactMismatch("model_artifact_checksum",f"Pinned model artifact unavailable or changed: {record['model_id']}")
