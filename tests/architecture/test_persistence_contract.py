"""Exercise persistence ports with the same effects on independent backends.

These tests provide data and independent expected records, not a fake simulator.
The contract-memory backend must work without opening a SQLite connection.
"""
from copy import deepcopy
from pathlib import Path
import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from zombie_sim import faults
from zombie_sim.persistence import PersistenceBundleFactory
from zombie_sim.persistence.contracts import CommitBundle, TransactionMismatch, CommitOutcomeUnknown
from zombie_sim.storage import VersionConflict


BACKENDS = ("memory", "sqlite", "contract-memory")


def initial_state():
    return {"time": "0", "revision": 0, "agents": {
        "a": {"id": "a", "type": "Human", "life": 100}}, "reservations": {}}


def change(life=99, *, transaction="transaction-1"):
    return CommitBundle(
        world_delta=[["set", ["time"], "1/3"], ["set", ["revision"], 1],
                     ["set", ["agents", "a", "life"], life]],
        runtime_delta=[["set", ["queue", "timer"], {"at": "2/3", "agent": "a"}],
                       ["set", ["memories", "a"], {"count": 1}]],
        events=({"id": "e1", "kind": "test_effect", "time": "1/3", "revision": 1,
                 "actor": "a", "transaction_id": transaction},),
        command_result={"command_id": "command-1", "status": "applied",
                        "control": {"generation": 1}},
    )


class PersistenceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="deep-oop-store-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def create(self, backend):
        bundle = PersistenceBundleFactory().create(initial_state(), self.root / (backend + ".sqlite"), backend)
        self.addCleanup(bundle.close)
        bundle.history.initialize_runtime({"schema": "test-runtime-v1", "attributes": {},
                                          "queue": {}, "memories": {}}, revision=0)
        return bundle

    def test_OOP_BACKEND_atomic_bundle_publishes_world_runtime_event_and_receipt(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                request = change()
                before = deepcopy(request)
                result = persistence.atomic.commit(request, 0, "transaction-1")
                self.assertEqual(request, before, "Commit must not mutate the caller's bundle")
                self.assertEqual((result.revision, result.time, result.transaction_id), (1, "1/3", "transaction-1"))
                self.assertEqual(persistence.store.read_view()["agents"]["a"]["life"], 99)
                self.assertEqual(persistence.history.state_at(revision=1)["agents"]["a"]["life"], 99)
                runtime = persistence.history.runtime_at(1)
                self.assertEqual(runtime["queue"], {"timer": {"at": "2/3", "agent": "a"}})
                self.assertEqual(runtime["memories"], {"a": {"count": 1}})
                self.assertEqual([e["id"] for e in persistence.history.events()], ["e1"])
                receipt = persistence.history.command_result("command-1")
                self.assertEqual(receipt["status"], "applied")
                self.assertEqual(receipt["control"], {"generation": 1})
                self.assertEqual(persistence.atomic.resolve_transaction("transaction-1"), result)
                self.assertIsNone(persistence.atomic.resolve_transaction("never-committed"))

    def test_OOP_ATOMIC_idempotency_and_changed_payload_rejection(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                result = persistence.atomic.commit(change(), 0, "transaction-1")
                self.assertEqual(persistence.atomic.commit(change(), 0, "transaction-1"), result)
                with self.assertRaises(TransactionMismatch):
                    persistence.atomic.commit(change(life=98), 0, "transaction-1")
                self.assertEqual(persistence.history.revision, 1)
                self.assertEqual(len(persistence.history.events()), 1)
                self.assertEqual(persistence.store.read_view()["agents"]["a"]["life"], 99)

    def test_OOP_ATOMIC_stale_revision_cannot_publish_any_part(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                persistence.atomic.commit(change(), 0, "transaction-1")
                before = persistence.history.state_at()
                runtime = persistence.history.runtime_at()
                with self.assertRaises(VersionConflict):
                    persistence.atomic.commit(change(life=98, transaction="stale"), 0, "stale")
                self.assertEqual(persistence.history.state_at(), before)
                self.assertEqual(persistence.history.runtime_at(), runtime)
                self.assertIsNone(persistence.atomic.resolve_transaction("stale"))

    def test_OOP_ATOMIC_receipt_is_bound_to_its_transaction_not_latest_command(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                original = persistence.atomic.commit(change(), 0, "transaction-1")
                persistence.history.finish_command({"command_id": "later-control", "status": "applied"}, {"generation": 2})
                self.assertEqual(persistence.atomic.resolve_transaction("transaction-1"), original)
                self.assertEqual(persistence.atomic.resolve_transaction("transaction-1").command_result["command_id"], "command-1")
                second = persistence.atomic.commit(CommitBundle([
                    ["set", ["revision"], 2], ["set", ["time"], "2/3"]]), 1, "transaction-2")
                self.assertIsNone(second.command_result)
                persistence.history.finish_command({"command_id": "unrelated-control", "status": "applied"}, {"generation": 3})
                self.assertEqual(persistence.atomic.resolve_transaction("transaction-2"), second)
                self.assertIsNone(persistence.atomic.resolve_transaction("transaction-2").command_result)

    def test_OOP_STATE_OWNERSHIP_inputs_and_query_results_are_detached(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                state = initial_state()
                persistence = PersistenceBundleFactory().create(state, self.root / (backend + ".sqlite"), backend)
                self.addCleanup(persistence.close)
                state["agents"]["a"]["life"] = 0
                self.assertEqual(persistence.store.read_view()["agents"]["a"]["life"], 100)
                for snapshot in (persistence.store.read_view(), persistence.history.state_at()):
                    snapshot["agents"]["a"]["life"] = 1
                    self.assertEqual(persistence.store.read_view()["agents"]["a"]["life"], 100)
                    self.assertEqual(persistence.history.state_at()["agents"]["a"]["life"], 100)

    def test_OOP_BACKEND_contract_memory_uses_no_sqlite_connection(self):
        with patch("sqlite3.connect", side_effect=AssertionError("Concrete SQLite access escaped its adapter")):
            persistence = self.create("contract-memory")
            persistence.atomic.commit(change(), 0, "transaction-1")
            self.assertEqual(persistence.history.state_at("1/3")["revision"], 1)
            self.assertEqual(persistence.history.runtime_at()["memories"]["a"]["count"], 1)
            self.assertEqual(persistence.history.command_result("command-1")["status"], "applied")
            persistence.close()

    def test_OOP_BACKEND_research_and_timeline_use_independent_query_port(self):
        from zombie_sim.history_sequence import LedgerRecords
        from zombie_sim.metrics import MetricsService
        from zombie_sim.timeline import TimelineService
        with patch("sqlite3.connect", side_effect=AssertionError("Analysis bypassed the history query port")):
            persistence = self.create("contract-memory")
            persistence.atomic.commit(change(), 0, "transaction-1")
            records = LedgerRecords(persistence.history)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["id"], "e1")
            records[0]["kind"] = "changed-outside"
            self.assertEqual(records[0]["kind"], "test_effect")
            metrics = MetricsService()
            self.addCleanup(metrics.close)
            samples = metrics.metrics_at_times(persistence.history, ["0", "1/3"], 1)
            self.assertEqual([s["time"] for s in samples], ["0", "1/3"])
            self.assertEqual([s["healthy"] for s in samples], [1, 1])
            self.assertEqual([s["dead"] for s in samples], [0, 0])
            timeline = TimelineService().page(persistence.history, "contract-run", revision=1, agent="a")
            self.assertEqual(timeline["cursor"], {"time": "1/3", "revision": "1"})
            self.assertEqual([record["id"] for record in timeline["records"]], ["e1"])
            self.assertEqual(timeline["records"][0]["revision_before"], "0")
            self.assertEqual(timeline["records"][0]["revision_after"], "1")
            self.assertEqual(persistence.history.revision, 1)

    def test_OOP_HISTORY_exact_time_and_detached_prior_revision(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                persistence.atomic.commit(change(), 0, "transaction-1")
                self.assertEqual(persistence.history.state_at("0.333333333333333333")["agents"]["a"]["life"], 100)
                self.assertEqual(persistence.history.state_at("1/3")["agents"]["a"]["life"], 99)
                self.assertEqual(persistence.history.state_at(revision=0)["time"], "0")
                self.assertEqual(persistence.history.cursor_at("1/3"), (1, "1", "3"))
                self.assertEqual(persistence.history.origin(), (0, "0", "1"))
                self.assertEqual(persistence.history.state_at(revision=persistence.history.origin()[0])["agents"]["a"]["life"], 100)

    def test_OOP_HISTORY_query_cancellation_propagates(self):
        class Cancelled(RuntimeError):
            pass

        def cancel():
            raise Cancelled("The caller cancelled the read")

        for backend in BACKENDS:
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                persistence.atomic.commit(change(), 0, "transaction-1")
                with self.assertRaises(Cancelled):
                    persistence.history.state_at(revision=1, check_cancelled=cancel)
                self.assertEqual(persistence.history.revision, 1)

    def test_OOP_ATOMIC_before_commit_failure_rolls_back_all_parts(self):
        for backend in ("memory", "sqlite"):
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                before = persistence.history.state_at()
                runtime_before = persistence.history.runtime_at()
                faults.arm("before_history_commit", error="ENOSPC")
                try:
                    with self.assertRaises(OSError):
                        persistence.atomic.commit(change(), 0, "transaction-1")
                finally:
                    faults.clear()
                self.assertEqual(persistence.store.read_view(), before)
                self.assertEqual(persistence.history.state_at(), before)
                self.assertEqual(persistence.history.runtime_at(), runtime_before)
                self.assertEqual(persistence.history.events(), [])
                self.assertIsNone(persistence.history.command_result("command-1"))
                self.assertIsNone(persistence.atomic.resolve_transaction("transaction-1"))
                self.assertEqual(persistence.atomic.commit(change(), 0, "transaction-1").revision, 1)

    def test_OOP_CONTINUATION_closed_bundle_can_be_restored(self):
        for backend in ("memory", "sqlite"):
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                result = persistence.atomic.commit(change(), 0, "transaction-1")
                persistence.close()
                restored = PersistenceBundleFactory().restore(self.root / (backend + ".sqlite"), backend)
                self.addCleanup(restored.close)
                self.assertEqual(restored.store.read_view()["agents"]["a"]["life"], 99)
                self.assertEqual(restored.history.runtime_at()["memories"]["a"], {"count": 1})
                self.assertEqual(restored.atomic.resolve_transaction("transaction-1"), result)
                self.assertEqual(restored.atomic.commit(change(), 0, "transaction-1"), result)

    def test_OOP_ATOMIC_uncertain_commit_reconciles_before_retry(self):
        for backend in ("memory", "sqlite"):
            with self.subTest(backend=backend):
                persistence = self.create(backend)
                faults.arm("after_history_commit_before_publish", error="EIO")
                try:
                    with self.assertRaises(CommitOutcomeUnknown):
                        persistence.atomic.commit(change(), 0, "transaction-1")
                finally:
                    faults.clear()
                result = persistence.atomic.resolve_transaction("transaction-1")
                self.assertIsNotNone(result)
                self.assertEqual(result.revision, 1)
                self.assertEqual(persistence.store.read_view()["agents"]["a"]["life"], 99)
                self.assertEqual(persistence.atomic.commit(change(), 0, "transaction-1"), result)
                self.assertEqual(len(persistence.history.events()), 1)

    def test_OOP_ATOMIC_process_death_recovers_without_volatile_objects(self):
        for backend in ("memory", "sqlite"):
            for point, expected_revision in (("before_history_commit", 0), ("after_history_commit_before_publish", 1)):
                with self.subTest(backend=backend, point=point):
                    path = self.root / f"crash-{backend}-{point}.sqlite"
                    trace = path.with_suffix(".trace.jsonl")
                    completed = subprocess.run([sys.executable, "-m", "tests.architecture.persistence_crash_probe",
                        "--path", str(path), "--backend", backend, "--point", point, "--trace", str(trace)],
                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), capture_output=True, text=True, timeout=30)
                    self.assertEqual(completed.returncode, 86, completed.stdout + completed.stderr)
                    observed = [json.loads(line) for line in trace.read_text().splitlines()]
                    self.assertEqual(len(observed), 1)
                    self.assertEqual(observed[0]["point"], point)
                    self.assertNotEqual(observed[0]["pid"], os.getpid())
                    restored = PersistenceBundleFactory().restore(path, backend)
                    self.addCleanup(restored.close)
                    self.assertEqual(restored.history.revision, expected_revision)
                    if expected_revision == 0:
                        self.assertIsNone(restored.atomic.resolve_transaction("transaction-1"))
                        self.assertEqual(restored.store.read_view()["agents"]["a"]["life"], 100)
                    else:
                        self.assertEqual(restored.atomic.resolve_transaction("transaction-1").revision, 1)
                        self.assertEqual(restored.store.read_view()["agents"]["a"]["life"], 99)
                    committed = restored.atomic.commit(change(), 0, "transaction-1")
                    self.assertEqual(committed.revision, 1)
                    self.assertEqual(restored.history.runtime_at()["memories"]["a"], {"count": 1})
                    self.assertEqual([event["id"] for event in restored.history.events()], ["e1"])
                    self.assertEqual(restored.history.command_result("command-1")["status"], "applied")


if __name__ == "__main__":
    unittest.main()
