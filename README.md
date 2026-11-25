# Zombie Game Simulation Framework

An ontology-driven, continuous-time simulation of humans and zombies, with
interchangeable decision models, durable experiment history, a local graphical
workspace, and a runnable recurrent PPO training example.

The implementation follows `ontology/zombie_game_ontology_v0.1.md`, its formal
OWL/SHACL package, and the two TASK 2 implementation-plan documents in `prompts/`.
The separate acceptance suite was not consulted or executed during implementation.

## Start a simulation

Python 3.12 or later is required. The core simulator uses the Python standard
library. Install optional dependencies for the features you use:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[gui,ontology,analysis]'
zombie-sim validate configs/small.toml --preview
zombie-sim run configs/small.toml --output runs/example --until 30
zombie-sim inspect runs/example
zombie-sim replay runs/example --time 15 --output runs/example/replay.json
zombie-sim resume runs/example --until 120
```

Use a fresh output directory for each new run. Resuming preserves the run identity;
branching creates a new one. `--backend sqlite` selects the database live-state
backend; memory mode still writes complete durable history. `--workers 2` enables
the process pool without changing the semantic scenario fingerprint.

`configs/baseline.toml` imports the ontology's 1,000-agent, 1,800-second scenario.
Its constrained relocation placement approximation was explicitly approved on
2026-11-25. Every run records the sampler, approval, attempts, acceptance and
constraint checks. This sampler does not claim the exact conditioned joint
distribution. Exact joint rejection remains available as `placement.sampler =
"exact"`; no initialization mode silently reduces population or relaxes geometry.

## Open the graphical workspace

```bash
zombie-sim gui --experiments-dir runs/workspace --port 8765
```

Open **http://127.0.0.1:8765**. The workspace provides scenario editing and preview,
run controls, a pan/zoom map, agent inspection, population charts, fixed and dynamic
cohorts, event history, recorded observations, replay, interventions and exports.
Simulation workers run independently of browser rendering. Assets are local; the
viewer does not require a CDN. See [the GUI guide](docs/GUI.md) for the complete
workflow and validation boundaries.

The source tree includes a built viewer. To rebuild it after editing TypeScript:

```bash
cd gui
pnpm install --frozen-lockfile
pnpm run build
```

## Use the Python API

```python
from zombie_sim import Simulation

with Simulation("configs/small.toml", history_path="runs/api/run.sqlite") as sim:
    sim.advance_until(10, return_snapshot=False)
    state = sim.snapshot()
    observation = sim.observe(next(iter(state["agents"])))
    checkpoint = sim.checkpoint("runs/api/checkpoint.json")

with Simulation.restore(checkpoint) as resumed:
    resumed.advance_until(20)
```

Semantic time accepts exact rational strings such as `"1/3"`. Observations contain
local sensed information and received signals. Policies receive private per-agent
memory separately; they cannot write world state. Use `decision_mode="scripted"`
and `submit_intents(...)` for experiments with externally supplied actions.

## Train and evaluate a policy

Use Python 3.12 with a compatible PyTorch build for the documented CPU recipe:

```bash
python -m pip install -e '.[learning]'
zombie-sim train training/smoke.toml --output artifacts/training/example
```

The implementation includes Gymnasium and PettingZoo AEC adapters, variable
duration rewards, imitation learning, recurrent PPO, checkpoint loading and
separate training/validation/held-out seeds. A smoke-trained artifact demonstrates
execution and reproducibility; it does not establish convergence or superiority.
See [training](docs/TRAINING.md) and [decision models](docs/MODELS.md).

## Implementation and evidence

- [Ontology mapping](docs/ONTOLOGY_MAPPING.md): profiles, roles, all 29 action
  contracts, initialization, geometry and RDF export.
- [Storage](docs/STORAGE.md): transactional live stores, ledger, replay and recovery.
- [Implementation and validation](docs/IMPLEMENTATION.md): architecture, measured
  checks, reproducible commands and remaining practical limits.
- [Plan provenance maintenance](ontology/formal_v0.1/provenance_refresh.json): the
  D8 metadata refresh and location of the preserved original validation evidence.

`implementation_checks/` contains independent checks written from the ontology
during implementation. It is separate from the supplied acceptance suite. These
checks and recorded smoke runs are evidence for the exercised paths, not a claim
that all possible simulations or the untouched acceptance suite have passed.
