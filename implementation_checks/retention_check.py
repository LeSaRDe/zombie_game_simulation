"""Verify opt-in complete ledger retention survives removal of test scratch data."""
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from zombie_sim.engine import Simulation
from zombie_sim.runtime import restore_revision
from zombie_sim.storage import History
from zombie_sim.testing import create_adapter, FrameworkTestAdapter


def main():
    with TemporaryDirectory() as outer:
        destination=Path(outer)/"retained"
        previous=os.environ.get("ZOMBIE_ACCEPTANCE_RETAIN_HISTORY")
        os.environ["ZOMBIE_ACCEPTANCE_RETAIN_HISTORY"]=str(destination)
        try:
            with TemporaryDirectory() as scratch:
                adapter=create_adapter(workdir=scratch)
                nested=FrameworkTestAdapter(workdir=Path(scratch)/"nested")
                assert nested.retention_directory is None
                sim=adapter.new_simulation({"agents":[{"id":"a","type":"Human","x":10,"y":10}]},
                                           {"decision_mode":"scripted","horizon":5})
                sim.submit_intents([{"actor":"a","action":"move","parameters":{"duration":2,
                    "path":[{"x":10,"y":10,"offset":0},{"x":14,"y":10,"offset":2}]}}])
                sim.advance_until(1,return_snapshot=False)
                expected=deepcopy(sim.state);events=list(sim.events);revision=sim.revision
                adapter.close();adapter.close()
        finally:
            if previous is None:os.environ.pop("ZOMBIE_ACCEPTANCE_RETAIN_HISTORY",None)
            else:os.environ["ZOMBIE_ACCEPTANCE_RETAIN_HISTORY"]=previous
        manifest=json.loads((destination/"retained-history.json").read_text())
        assert len(manifest["histories"])==1
        entry=manifest["histories"][0];assert entry["revision"]==revision
        path=Path(entry["path"]);history=History(path,read_only=True)
        try:assert history.state_at()==expected
        finally:history.close()
        clone=restore_revision(Simulation,path)
        try:
            assert list(clone.events)==events
            clone.advance_until(2,return_snapshot=False)
            assert clone.snapshot()["agents"]["a"]["x"]==14
        finally:clone.close()
    print("Opt-in retention preserves every event and exact busy-state continuation after scratch deletion; nested adapters do not duplicate retention.")


if __name__=="__main__":main()
