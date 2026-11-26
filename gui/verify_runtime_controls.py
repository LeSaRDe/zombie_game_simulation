"""Regression checks for reported run-control races using real worker processes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import tempfile
import time

from zombie_sim.application import RunManager, RunInitializing


def await_status(manager,identity,status):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        row=next(r for r in manager.list_runs() if r["id"]==identity)
        if row["status"]==status:return row
        if row["status"]=="failed":raise AssertionError(row)
        time.sleep(.01)
    raise AssertionError((identity,status,row))


def main():
    report={}
    with tempfile.TemporaryDirectory(prefix="zombie-controls-") as directory:
        manager=RunManager(directory)
        try:
            config={"horizon":120,"checkpoint_interval":1000,"execution":{"workers":2},
                    "population":{"humans":16,"zombies":4,"infected":1}}
            # Creation and immediate repeated reads must never confuse an
            # initializing registered run with an unknown identity.
            identity=manager.create(config,"first",start=True)["run_id"]
            def poll():
                for _ in range(10):
                    assert manager._row(identity)["id"]==identity
                    try:
                        view=manager.snapshot(identity)
                        assert view["state"]["run_id"]==identity
                        assert int(view["revision"])<=int(view["committed_frontier"])
                    except RunInitializing:pass
                return True
            with ThreadPoolExecutor(8) as pool:assert all(pool.map(lambda _:poll(),range(8)))
            await_status(manager,identity,"running")
            report["concurrent_creation_reads"]="PASS"
            last=None
            for _ in range(3):
                row=next(r for r in manager.list_runs() if r["id"]==identity)
                paused=manager.command(identity,"pause",{"generation":row["generation"]})
                assert paused["status"]=="applied",paused
                before=manager.snapshot(identity)
                time.sleep(.15)
                after=manager.snapshot(identity)
                assert before["state"]==after["state"]
                assert before["revision"]==paused["revision"]==after["revision"]
                last=manager.command(identity,"continue",{"generation":paused["generation"]})
                assert last["status"]=="applied",last
            report["pause_quiescence_and_immediate_ack_generation"]="PASS"
            row=manager._row(identity)
            checkpoint=Path(row["directory"])/"worker-checkpoint.json"
            # Termination must preserve the existing checkpoint unchanged.
            previous=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            terminated=manager.command(identity,"terminate",{"generation":last["generation"]})
            assert terminated["status"]=="applied" and terminated["run_status"]=="terminated",terminated
            manager.processes[identity].join(timeout=5)
            assert not manager.processes[identity].is_alive()
            assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==previous
            assert not manager.connection.execute("SELECT 1 FROM worker_leases WHERE run_id=?",(identity,)).fetchone()
            try:manager.command(identity,"resume")
            except ValueError as error:assert "immutable" in str(error)
            else:raise AssertionError("Terminated run resumed")
            assert manager.command(identity,"terminate",{
                "command_id":terminated["command_id"],"generation":last["generation"]})==terminated
            try:manager.command(identity,"terminate",{"command_id":terminated["command_id"]})
            except ValueError as error:assert "different request content" in str(error)
            else:raise AssertionError("Retry changed the immutable original request")
            report["terminate_without_checkpoint_or_resume"]="PASS"
        finally:manager.close()
    output=Path("artifacts/runtime_controls");output.mkdir(parents=True,exist_ok=True)
    (output/"manager.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
