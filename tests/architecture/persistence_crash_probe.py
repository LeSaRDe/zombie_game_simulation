"""Owned child process that exits at the real durable transaction hook."""
import argparse
from zombie_sim import faults
from zombie_sim.persistence import PersistenceBundleFactory
from tests.architecture.test_persistence_contract import change, initial_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--point", required=True)
    parser.add_argument("--trace", required=True)
    args = parser.parse_args()
    persistence = PersistenceBundleFactory().create(initial_state(), args.path, args.backend)
    persistence.history.initialize_runtime({"schema": "test-runtime-v1", "attributes": {}, "queue": {}, "memories": {}}, revision=0)
    faults.arm(args.point, crash=True, trace_path=args.trace)
    persistence.atomic.commit(change(), 0, "transaction-1")
    raise AssertionError("Real transaction hook failed to terminate the owned child")


if __name__ == "__main__":
    main()
