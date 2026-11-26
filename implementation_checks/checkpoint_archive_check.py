"""Exercise archive links and a later rolling replacement on an isolated worker."""
from pathlib import Path
import multiprocessing
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.archive_checkpoint import archive,digest
from scripts import archive_checkpoint as archiver
from zombie_sim.engine import Simulation
from zombie_sim.runtime import restore_revision
from zombie_sim.storage import History


def coordinator(pipe,directory):
    root=Path(directory)
    sim=Simulation({"agents":[{"id":"a","type":"Human","x":10,"y":10}],
                    "decision_mode":"scripted","horizon":5,"execution":{"workers":1}},history_path=root/"run.sqlite")
    checkpoint=root/"rolling.json"
    try:
        sim.submit_intents([{"actor":"a","action":"move","parameters":{"duration":2,
            "path":[{"x":10,"y":10,"offset":0},{"x":14,"y":10,"offset":2}]}}])
        sim.advance_until(1,return_snapshot=False);sim.checkpoint(checkpoint)
        pipe.send({"revision":sim.revision,"checkpoint":str(checkpoint)})
        command=pipe.recv()
        while command=="ping":
            pipe.send("alive");command=pipe.recv()
        assert command=="replace"
        sim.advance_until(2,return_snapshot=False);sim.checkpoint(checkpoint)
        pipe.send({"revision":sim.revision,"state":sim.state,"events":list(sim.events)})
        assert pipe.recv()=="close"
    finally:sim.close();pipe.close()


def journal(path):
    connection=sqlite3.connect(f"file:{path}?mode=ro",uri=True)
    try:return {table:connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("commits","runtime_commits","events","checkpoints")}
    finally:connection.close()


def main():
    with TemporaryDirectory() as directory:
        root=Path(directory);run=root/"run";run.mkdir()
        context=multiprocessing.get_context("spawn");parent,child=context.Pipe()
        process=context.Process(target=coordinator,args=(child,str(run)));process.start();child.close()
        try:
            first=parent.recv();checkpoint=Path(first["checkpoint"]);sidecar=checkpoint.with_suffix(".history.sqlite");ledger=run/"run.sqlite"
            before=journal(ledger);source_hashes={str(path):digest(path) for path in (checkpoint,sidecar)}
            history=History(sidecar,read_only=True)
            try:states=[history.state_at(revision=revision) for revision in range(first["revision"]+1)]
            finally:history.close()
            original_check=archiver.check_files;calls=0
            def failing_final_check(*args):
                nonlocal calls
                calls+=1
                if calls==2:raise ValueError("Injected final validation failure")
                return original_check(*args)
            try:
                archiver.check_files=failing_final_check
                try:archive(ledger,checkpoint,first["revision"],root/"archive",process.pid)
                except ValueError as error:assert "Injected final validation failure" in str(error)
                else:raise AssertionError("Expected final revalidation failure")
            finally:archiver.check_files=original_check
            parent.send("ping");assert parent.recv()=="alive"
            assert not checkpoint.is_symlink() and not sidecar.is_symlink()
            assert journal(ledger)==before
            result=archive(ledger,checkpoint,first["revision"],root/"archive",process.pid)
            assert result["status"]=="APPLIED" and 0<result["coordinator_stop_seconds"]<2
            assert checkpoint.is_symlink() and sidecar.is_symlink()
            assert source_hashes=={str(path):digest(path) for path in (checkpoint,sidecar)}
            assert journal(ledger)==before
            assert archive(ledger,checkpoint,first["revision"],root/"archive",process.pid)==result
            archived_sidecar=sidecar.resolve();archived_json=checkpoint.resolve()
            assert result["model_pins"]
            for pin in result["model_pins"]:
                assert not Path(pin["source"]).is_symlink()
                assert digest(pin["target"])==digest(pin["source"])==pin["sha256"]
            pinned=Simulation.restore(archived_json)
            try:assert pinned.state==states[-1]
            finally:pinned.close()
            history=History(archived_sidecar,read_only=True)
            try:assert states==[history.state_at(revision=revision) for revision in range(first["revision"]+1)]
            finally:history.close()
            parent.send("replace");second=parent.recv()
            assert second["revision"]>first["revision"]
            assert not checkpoint.is_symlink() and not sidecar.is_symlink()
            assert digest(archived_json)==source_hashes[str(checkpoint)]
            assert digest(archived_sidecar)==source_hashes[str(sidecar)]
            clone=restore_revision(Simulation,archived_sidecar)
            try:
                clone.advance_until(2,return_snapshot=False)
                assert clone.state==second["state"] and list(clone.events)==second["events"]
            finally:clone.close()
            current=Simulation.restore(checkpoint)
            try:assert current.state==second["state"]
            finally:current.close()
            parent.send("close");process.join(10);assert process.exitcode==0
            print({"archive":"passed","historical_revisions_verified":len(states),
                   "coordinator_stop_seconds":result["coordinator_stop_seconds"],
                   "later_rolling_publication":"replaced links; archived bytes unchanged"})
        finally:
            if process.is_alive():process.terminate();process.join(5)
            parent.close()


if __name__=="__main__":main()
