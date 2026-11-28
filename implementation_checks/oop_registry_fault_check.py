"""Verify isolated catalog/fault objects and unchanged process-default hooks."""
from copy import deepcopy
import errno
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from zombie_sim import faults, policies
from zombie_sim.engine import Simulation
from zombie_sim.model_catalog import DEFAULT_MODEL_CATALOG, ModelCatalog, model_catalog


def main():
    catalogs = [ModelCatalog(), ModelCatalog()]
    before = model_catalog()
    calls = []
    def factory(parameters=None):
        calls.append(parameters)
        return policies.HumanDefaultModel(parameters)
    metadata = {"model_id": "isolated/model", "label": "Isolated example", "version": "1",
                "applicable_types": ["Human"], "description": "Catalog isolation check"}
    catalogs[0].register("isolated/model", factory, metadata=metadata)
    metadata["label"] = "Mutated outside"
    assert "isolated/model" not in catalogs[1].names()
    assert "isolated/model" not in DEFAULT_MODEL_CATALOG.names()
    description = catalogs[0].describe()
    choice = next(choice for choice in description["choices"] if choice["model_id"] == "isolated/model")
    assert choice["label"] == "Isolated example" and not calls
    choice["label"] = "Mutated output"
    assert next(choice for choice in catalogs[0].describe()["choices"] if choice["model_id"] == "isolated/model")["label"] == "Isolated example"
    assert isinstance(catalogs[0].create("isolated/model"), policies.HumanDefaultModel)
    assert calls == [None]
    saved_factories, saved_metadata = dict(catalogs[0].factories), deepcopy(catalogs[0].metadata)
    try:
        catalogs[0].register("invalid", factory, metadata={"model_id": "bad"})
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid declaration accepted")
    assert catalogs[0].factories == saved_factories and catalogs[0].metadata == saved_metadata
    assert model_catalog() == before

    one, two = faults.FaultInjector(), faults.FaultInjector()
    with TemporaryDirectory(prefix="oop-owned-faults-") as temporary:
        root = Path(temporary)
        trace = root / "faults.jsonl"
        one.arm("publication", occurrence=2, error="ENOSPC", trace_path=trace)
        two.hit("publication")  # Independently owned schedule remains disabled.
        one.hit("unrelated")
        one.hit("publication")
        try:
            one.hit("publication", revision=17)
        except OSError as exc:
            assert exc.errno == errno.ENOSPC
        else:
            raise AssertionError("Scheduled fault did not fire")
        one.hit("publication")  # A nonpersistent fault fires exactly once.
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        assert len(records) == 1 and records[0]["revision"] == 17
        one.arm("dependency_validation", omit_read_key="actor", trace_path=trace)
        reads = {"actor": 1, "target": 2}
        two.omit_dependency(reads)
        assert reads == {"actor": 1, "target": 2}
        one.omit_dependency(reads)
        assert reads == {"target": 2}
        one.clear()
        # Existing storage hooks route through the default object at the actual
        # commit boundary; rejected publication leaves the durable prefix intact.
        for backend in ("memory", "sqlite"):
            with Simulation({"agents": [{"id": "one", "type": "Human", "x": 10, "y": 10}],
                             "decision_mode": "scripted"}, workers=1, backend=backend,
                            history_path=root / (backend+".sqlite")) as sim:
                revision = sim.history.revision
                state = sim.history.state_at()
                faults.arm("before_history_commit", error="ENOSPC")
                try:
                    sim.advance_until(1)
                except OSError as exc:
                    assert exc.errno == errno.ENOSPC
                else:
                    raise AssertionError("Default storage injection was bypassed")
                finally:
                    faults.clear()
                assert sim.history.revision == revision
                assert sim.history.state_at() == state
                sim.advance_until(1)
                assert sim.history.revision > revision
    report = {"isolated_factory_and_metadata_ownership": True, "metadata_reads_do_not_instantiate_models": True,
              "metadata_input_output_detached": True, "invalid_registration_atomic": True,
              "fault_schedules_isolated": True, "fault_count_and_errno_and_trace_preserved": True,
              "dependency_omission_isolated": True, "real_memory_sqlite_commit_hooks_and_retry": True}
    path = Path(__file__).resolve().parents[1] / "artifacts/oop-refactor/registry-fault-checks.json"
    path.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
