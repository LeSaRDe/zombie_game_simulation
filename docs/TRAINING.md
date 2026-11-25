# Learning and evaluation

Install the `learning` dependency extra, then run:

```sh
zombie-sim train training/smoke.toml --output artifacts/training/smoke
python scripts/train_policy.py --decisions 4096 --output artifacts/training/smoke
python scripts/train_policy.py --evaluate artifacts/training/smoke/selected --output artifacts/training/recheck
python scripts/train_policy.py --decisions 200000 --rollout 1024 --output artifacts/training/starter
```

Use `--config path/to/scenario.toml` and `--family Zombie` for another task. The default
curriculum is a bounded 60-second, six-agent world with supplied resources and frozen
utility opponents. This demonstrates training mechanics; it is not evidence of
convergence or policy superiority at the 1,000-agent baseline.

`ControlledAgentEnv` implements Gymnasium reset/step with a candidate-index action
space and a padded observation dictionary: `context`, `candidates`, `action_mask`.
The context has 32 normalized self/local summary features; mean/min neighborhood
pooling is permutation invariant. Candidates include the 29 action indicators,
normalized utility features, relative target/path information, duration, stamina and
resource estimates. The reversible candidate-index-to-intent map is saved in each
rollout. The 128-candidate cap and movement templates are declared encoder restrictions.
The same cap is stored in the learned artifact and applied during engine deployment.
Default-utility and random baselines evaluate their full observable candidate sets;
the learned encoder restriction does not prune those baseline choices.
Padding is masked and raises on attempted execution.

A step admits a whole frozen decision batch, then lets default opponents continue
until the controlled identity can decide again. `info.elapsed` is actual simulated
time. Death, conversion out of the controlled type, and the task's finite horizon are
termination. `decision_limit` is an external truncation and retains a bootstrap value.
Remaining finite task time is included in the actor context. A converted identity
may begin another zombie controller episode with fresh memory through
`env.reset(options={"continue_identity": agent_id, "family": "Zombie"})`. This retains
the world and time, archives the retired controller memory, and issues a new controller
episode ID. It is never treated as the same human-policy episode.

`DecisionBatchAEC` implements PettingZoo AEC collection. Every learner in a shared
batch sees frozen observations; admission happens only after all batch intents are
collected. Nonlearning agents use default models. It does not claim automatic
conversion to PettingZoo's Parallel API. Controller IDs are persistent simulation
IDs within an episode; type transitions end that controller episode.

The PyTorch model has two 128-unit context layers, a GRUCell with 128 private recurrent
units, candidate embeddings and a scalar value head. PPO uses learning rate 3e-4,
clip 0.2, four epochs, gradient norm 0.5, 256-decision minibatches and contiguous
32-step recurrent sequences. Sequence chunks reset at real episode boundaries and
use detached stored states at truncated backpropagation boundaries. Pass `--device cuda` to the standalone training script for an available GPU.
The CPU recipe
starts from a small behavior-cloning checkpoint of utility-policy decisions.

For an interval of duration dt, discount is `gamma**dt`, with gamma=0.99 per second.
GAE also uses `lambda**dt`, lambda=0.95. Timed discrete rewards are discounted at
their offsets within the interval. The human survival rate is integrated over the
interval, rather than assigning a fixed reward to every decision. True terminals
bootstrap zero; external truncations bootstrap the final value and end the GAE chain.
A collection boundary bootstraps normally and does not invent a terminal event.

Two experimental objectives are supplied, with all terms reported separately:

- `human_survival_v1`: +0.01 per second alive as human; −10 for human death/conversion;
  +2 per successful cure of another human; +0.01 per actual life restored to another.
- `zombie_pressure_v1`: +1 per newly caused infection; +0.02 per actual damage point
  to a human; −5 for own death. Misses, invalid targets and repeated exposure do not earn points.

The default seed partitions are training 100–109, validation 1000–1004, held-out
2000–2029. Sets must be disjoint. The runnable recipe saves optimizer/weights, a
manifest with configuration/encoder/reward/hyperparameters, full rollout records,
validation metrics and one held-out comparison of random candidates, utility,
imitation and PPO. Raw per-seed runs and an explicitly labeled normal-approximation
95% interval for mean reward are retained. Survival time accompanies reward so a
reward increase alone does not establish better behavior. Expand replication when
variance demands it; thirty runs are only a starting point.

Artifacts contain `weights.pt`, `manifest.json`, optional `optimizer.pt`, a selected
checkpoint, `rollouts.jsonl` and `report.json`. Reload checks the manifest and digest.
Results must state the actual decision budget and scope; a smoke artifact establishes
that updates, serialization and evaluation execute, not that the policy is optimal.

## Recorded CPU smoke result

`artifacts/training/smoke_final/report.json` records a completed 4,096-decision run using
Python 3.12, PyTorch 2.5.1+cpu and the six-agent, 60-second task. It performed 96 PPO
optimizer steps after 35 imitation examples. The PPO weights changed relative to the
imitation checkpoint, and reloading the selected artifact succeeded. The ordinary
simulation engine also executed that artifact through its `ppo:` model registry with
private 128-value recurrent memory; see `artifacts/model_checks/learned_engine.json`.

| Held-out policy | Seeds | Mean raw reward | Mean human survival |
|---|---:|---:|---:|
| Default utility | 30 | 0.6 | 60 s |
| Random observable candidates | 30 | 0.6 | 60 s |
| Imitation | 30 | 0.6 | 60 s |
| Recurrent PPO | 30 | 0.6 | 60 s |

All controllers reached the task horizon. This easy smoke scenario did not distinguish
policy quality; these results establish training, serialization and evaluation operation.
They do not establish an advantage for PPO or equivalent behavior in harder scenarios.
The full candidate mappings, elapsed times, masks, rewards, values, old log probabilities,
episode boundaries and recurrent inputs are retained in `rollouts.jsonl`.
