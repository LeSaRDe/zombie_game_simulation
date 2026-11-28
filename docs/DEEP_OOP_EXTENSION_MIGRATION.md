# Migrating framework extensions

The supported simulation entry points remain `Simulation`, `SimulationFramework`, the CLI, and the web application. Policy/model extensions continue to receive local observations and return intents plus private memory. A previously imported checkpoint with default engine behavior can continue through the reviewed legacy runtime reader.

Game behavior now belongs to `GameRuleSet` and `ActionHandler` implementations. A rule runs against an isolated `WorldDraft` and `RuntimeSnapshot`, then returns a `TransitionPlan`. `StateCoordinator` validates that proposal, and `UnitOfWork` commits world changes, pending work/private memory, events and a command receipt through one `AtomicCommitPort`. A handler must not receive a live `Simulation`, store, history reader, or publisher. Custom rule implementations are source-pinned; restoring them requires the original explicit `rule_set=`. Branches inherit that rule set.

A custom read-only observation service remains supported:

```python
from zombie_sim import Simulation
from zombie_sim.core import SimulationServiceFactory
from zombie_sim.core.observations import ObservationService

class ResearchObservations(ObservationService):
    def observe(self, agent_id):
        observation = super().observe(agent_id)
        # Return a detached, model-facing observation.
        return observation

factory = SimulationServiceFactory({"observations": ResearchObservations})
with Simulation({"preset": "small"}, workers=1, service_factory=factory) as run:
    agent_id = next(iter(run.world_view["agents"]))
    observation = run.observe(agent_id)
```

The observation service receives a dated `ReadProjection`. It exposes detached world records and local geometric caches; it has no engine reference, repository or commit method. Custom observation, scheduler, decision, runtime and executor services must have inspectable source and use `workers=1`. Provide the same `service_factory=` when restoring. Scheduler and decision services orchestrate calls; action semantics still enter the rule planner.

The old `core.actions.ActionService`, `LifecycleService`, `InterventionService` and `TransactionService` names are retained only to provide a migration error. Instantiating them or binding them in a factory raises `LegacyExtensionError`. Overrides of the old mutable `continuous` and `randomness` services also require migration to rule implementations. `RandomService` now provides context-free keyed variates and controlled-input validation; Bernoulli effects and their audit records are produced inside rule planning.

A `Simulation` subclass that overrides private mutation or observation hooks such as `_damage`, `_resolve` or `_nearby` is rejected before a ledger is opened. Move mutation logic into a rule/handler, and move observation customization into `ObservationService`. The former `ActionSystemMixin` is not an alternative mutation route. Rejection leaves existing ledgers available for read-only replay; the system never silently substitutes default behavior for a recorded custom implementation.

Persistence extensions use a coordinated `PersistenceBundleFactory`, supplied through `persistence_factory=`. Its live store, history queries, atomic commit operation and checkpoint operations must share one durability boundary. Production `memory` and `sqlite` modes both retain durable SQLite history. The independent `contract-memory` adapter uses no SQLite and is intentionally nondurable: it supports in-process query/commit contract tests but cannot recover a discarded process or export a portable history sidecar.

`PersistenceFactoryPort` declares `create`, `restore`, `open_history`, and `export_prefix(source, destination, revision, state)`. The last operation owns restored-prefix copying, so a replacement backend can supply its own implementation for checkpoint, journal and branch restoration. Runtime restoration does not construct a concrete SQLite checkpoint adapter behind the factory.

Rolling checkpoint publication keeps the preceding JSON and canonical `.history.sqlite` pair valid while staging and syncing a unique new sidecar and content-addressed model pins. The envelope is then published before the new sidecar replaces the canonical name. If a process dies in that interval, restoration accepts the pending local generation only when its checksum matches the new envelope and any existing canonical sidecar matches the recorded previous checksum. Arbitrary corruption still fails. Successful rolling checkpoints retain one canonical sidecar; retry removes only the immediately preceding, explicitly recorded pending generation. Repeated abrupt process deaths can leave older unreferenced generation files, which are retained rather than deleting files whose ownership is no longer recorded. User-named checkpoint bundles and archived histories are never cleaned by this mechanism.

The regression evidence is executable in `tests/architecture/test_extension_migration.py`, `test_state_integrity.py`, `test_persistence_contract.py`, `test_simulation_ports.py`, `test_restore_factory.py`, and `test_checkpoint_publication.py`. `implementation_checks/oop_core_check.py` retains the custom observation/scheduler/runtime restore assertions and verifies the explicit migration diagnostic for old private coordinator hooks.
