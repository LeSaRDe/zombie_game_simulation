"""Exercise retained command payloads and recovery of real durable reservations."""
from copy import deepcopy
import errno
import tempfile
import time
import unittest
from unittest.mock import patch

from zombie_sim.application import RunManager


def await_receipt(manager,identity):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        result=manager.command_result(identity)
        if result["status"]!="pending":return result
        time.sleep(.02)
    raise TimeoutError(identity)


def await_ready(manager,run_id):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        row=manager._row(run_id)
        if row["status"]!="initializing":
            if row["status"]=="failed":raise RuntimeError(row["error"])
            return row
        time.sleep(.02)
    raise TimeoutError(run_id)


class RetainedCommandChecks(unittest.TestCase):
    def test_payloads_and_reservations(self):
        with tempfile.TemporaryDirectory(prefix="zombie-command-check-") as directory:
            manager=RunManager(directory)
            config={"preset":"small","seed":91,"decision_mode":"scripted","horizon":10,
                    "execution":{"workers":1}}
            try:
                # The run/receipt reservation is durable before process launch.
                with patch.object(manager,"launch_worker",side_effect=OSError(errno.EAGAIN,"process launch unavailable")):
                    with self.assertRaises(OSError):manager.create(config,"new")
                original=manager.command_result("new")
                self.assertEqual(manager.create(deepcopy(config),"new")["run_id"],original["run_id"])
                run_id=original["run_id"];await_ready(manager,run_id)
                with self.assertRaisesRegex(ValueError,"different request content"):
                    manager.create({**config,"seed":92},"new")
                self.assertEqual(len(manager.list_runs()),1)

                # A branch reserves its child identity before materialization.
                request={"command_id":"branch","revision":"0","seed":92,"generation":manager._row(run_id)["generation"]}
                with patch("zombie_sim.runtime.branch",side_effect=OSError(errno.ENOSPC,"branch staging unavailable")):
                    with self.assertRaises(OSError):manager.branch(run_id,request)
                reserved=manager.command_result("branch")["run_id"]
                changed={**request,"seed":93}
                with self.assertRaisesRegex(ValueError,"different request content"):manager.branch(run_id,changed)
                # Later unrelated controls must not invalidate a reserved branch.
                manager.command(run_id,"pause",{"command_id":"advance-generation"})
                branch=manager.branch(run_id,deepcopy(request));self.assertEqual(branch["run_id"],reserved)
                await_ready(manager,reserved)
                self.assertEqual(manager.branch(run_id,deepcopy(request))["run_id"],reserved)
                with self.assertRaisesRegex(ValueError,"different request content"):manager.branch(run_id,changed)
                self.assertEqual(len(manager.list_runs()),2)

                # Omitted revision means the frontier at original acceptance,
                # never the frontier reached while recovering a failed stage.
                latest={"command_id":"latest-branch","seed":93,"generation":manager._row(run_id)["generation"]}
                parent_history=manager.history(run_id)
                try:selected_revision=parent_history.revision
                finally:parent_history.close()
                with patch("zombie_sim.runtime.branch",side_effect=OSError(errno.ENOSPC,"branch staging unavailable")):
                    with self.assertRaises(OSError):manager.branch(run_id,latest)
                reserved_latest=manager.command_result("latest-branch")
                self.assertEqual(reserved_latest["parent_revision"],str(selected_revision))
                manager.command(run_id,"advance",{"command_id":"later-parent","time":"1"})
                advanced_history=manager.history(run_id)
                try:self.assertGreater(advanced_history.revision,selected_revision)
                finally:advanced_history.close()
                recovered=manager.branch(run_id,deepcopy(latest))
                self.assertEqual(recovered["run_id"],reserved_latest["run_id"])
                self.assertEqual(recovered["parent_revision"],str(selected_revision))
                await_ready(manager,recovered["run_id"])
                child_history=manager.history(recovered["run_id"])
                try:self.assertEqual(child_history.state_at()["lineage"]["revision"],selected_revision)
                finally:child_history.close()
                original_cursor=(recovered["revision"],recovered["time"])
                manager.command(recovered["run_id"],"advance",{"command_id":"later-child","time":"2"})
                from zombie_sim.command_recovery import reply
                reread=reply(manager,manager.command_result("latest-branch"))
                self.assertEqual((reread["revision"],reread["time"]),original_cursor)
                self.assertEqual(manager.branch(run_id,deepcopy(latest)),reread)
                self.assertEqual(len(manager.list_runs()),3)

                # A retained pending control receipt must restart a dead worker.
                manager.command(run_id,"stop",{"command_id":"stop"})
                manager.processes[run_id].join(timeout=10)
                self.assertFalse(manager.processes[run_id].is_alive())
                pause={"command_id":"paused-again","generation":manager._row(run_id)["generation"]}
                with patch.object(manager,"launch_worker",side_effect=OSError(errno.EAGAIN,"process launch unavailable")):
                    with self.assertRaises(OSError):manager.command(run_id,"pause",pause,wait=False)
                manager.command(run_id,"pause",deepcopy(pause),wait=False)
                receipt=await_receipt(manager,"paused-again");self.assertEqual(receipt["status"],"applied")
                self.assertEqual(manager.command(run_id,"pause",deepcopy(pause)),receipt)
                with self.assertRaisesRegex(ValueError,"different request content"):
                    manager.command(run_id,"pause",{**pause,"generation":999})
                history=manager.history(run_id)
                try:self.assertEqual(sum(row["command_id"]=="paused-again" for row in history.command_results()),1)
                finally:history.close()
            finally:manager.close()


if __name__=="__main__":unittest.main(verbosity=2)
