"""Exercise stream control races without opening a service or touching user runs."""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zombie_sim.server import create_app


def head(revision=7, generation=1, status="paused"):
    terminal = status == "terminated"
    return {"run_id": "fixture", "revision": str(revision), "time": "1",
            "generation": generation, "status": status,
            "resource_status": {"phase": "stopped" if terminal else status,
                                "worker_active": not terminal, "cleanup_complete": terminal}}


def bundle(current, revision=None):
    revision = str(revision if revision is not None else current["revision"])
    return {"run_id": "fixture", "sequence": revision, "revision": revision,
            "committed_frontier": revision, "time": current["time"], "state": {},
            "control": {key: copy.deepcopy(current[key])
                        for key in ("status", "generation", "resource_status")}}


class FakeSocket:
    def __init__(self, token, on_idle=None):
        self.headers = {"origin": "http://127.0.0.1"}
        self.cookies = {"zombie_session": token}
        self.sent = []
        self.acks = []
        self.closes = []
        self.accepted = False
        self.on_idle = on_idle

    async def accept(self):
        self.accepted = True

    async def send_json(self, packet):
        assert len(self.sent) == len(self.acks), "More than one outstanding frame"
        self.sent.append(copy.deepcopy(packet))

    async def receive_json(self):
        if len(self.sent) > len(self.acks):
            sequence = self.sent[-1]["sequence"]
            self.acks.append(sequence)
            return {"ack": sequence}
        if self.on_idle is not None:
            return self.on_idle()
        raise RuntimeError("Fixture disconnected")

    async def close(self, code=1000):
        self.closes.append(code)


class StreamChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="zombie-issue1-stream-")
        self.app = create_app(self.temporary.name)
        self.manager = self.app.state.manager
        self.endpoint = next(route.endpoint for route in self.app.routes
                             if getattr(route, "path", "") == "/api/runs/{run_id}/stream")

    def tearDown(self):
        self.app.state.exports.close()
        self.manager.close()
        self.temporary.cleanup()

    def run_stream(self, socket):
        async def dispatch(function, *args):
            # These manager methods are deterministic fakes. Actual concurrent
            # reconstruction and workers are exercised by issue1_check.py.
            return function(*args)

        with patch("zombie_sim.server.asyncio.to_thread", dispatch):
            asyncio.run(asyncio.wait_for(self.endpoint(socket, "fixture"), timeout=3))

    def test_termination_overtaking_projection_sends_only_final_boundary(self):
        current = head(status="running")
        calls = {"head": 0, "snapshot": 0}

        def read_head(_):
            calls["head"] += 1
            return copy.deepcopy(current)

        def snapshot(_):
            calls["snapshot"] += 1
            if calls["snapshot"] == 1:
                # Model work that began at revision 7, then received fresh
                # terminal controls after the coordinator committed revision 9.
                current.update(head(revision=9, generation=2, status="terminated"))
                return bundle(current, revision=7)
            return bundle(current)

        self.manager.read_head = read_head
        self.manager.snapshot = snapshot
        socket = FakeSocket(self.app.state.session_token)
        self.run_stream(socket)
        self.assertTrue(socket.accepted)
        self.assertEqual([packet["revision"] for packet in socket.sent], ["9"])
        self.assertEqual(socket.acks, ["9"])
        self.assertEqual(socket.closes, [1000])
        self.assertEqual(calls["snapshot"], 2)
        self.assertGreaterEqual(calls["head"], 4)

    def test_paused_control_change_at_same_revision_sends_new_control(self):
        current = head()
        calls = {"snapshot": 0, "idle": 0}

        def snapshot(_):
            calls["snapshot"] += 1
            return bundle(current)

        def on_idle():
            calls["idle"] += 1
            if calls["idle"] == 1:
                current["generation"] = 2
                return {"ping": True}
            raise RuntimeError("Fixture disconnected after control update")

        self.manager.read_head = lambda _: copy.deepcopy(current)
        self.manager.snapshot = snapshot
        socket = FakeSocket(self.app.state.session_token, on_idle)
        self.run_stream(socket)
        self.assertEqual([packet["sequence"] for packet in socket.sent], ["7", "7"])
        self.assertEqual([packet["control"]["generation"] for packet in socket.sent], [1, 2])
        self.assertEqual(calls["snapshot"], 2)
        self.assertEqual(socket.acks, ["7", "7"])
        self.assertEqual(socket.closes, [1000])


if __name__ == "__main__":
    unittest.main(verbosity=2)
