# Research test operations

`research.py` adds deterministic mixed sequences, two replicated statistical
diagnostics, and a real full-baseline execution to the shared adapter contract.

`trials.execute` receives `seeds`, a `world`, and simulation `steps`. Create a fresh
real framework instance for every seed, execute the exact steps, and return an
ordered list at `captures[label]` of `{seed, trace}`. Each trace has the complete
simulation response schema. No injected draws, retained model/world state between
trials, regenerated expected outcomes or reseeding to obtain passing frequencies.
Parallel scheduling is allowed if each trial's semantic seed/state remains isolated.

The runner independently inspects every returned trace. Hit trials require the
literal base-zombie claw probability 0.72 and life damage consistent with its raw
draw. Claim trials derive the winner from the two inventories and verify that
exactly one unit was transferred. A fixed 1,024-seed sample uses a predeclared
five-standard-deviation bound, calculated exactly from the stated probability.
This detects gross systematic bias; it does not prove randomness or distributional
equivalence. Investigate a failure without changing the seed list to make it pass.

The baseline case uses `run.*` operations from SYSTEM_OPERATIONS.md with
`decision_mode: model`. Capture initial state **before** the first decision is
admitted. Then run the real default models until 1,800 seconds or no living agents.
Do not end on extinction of only one type. The independent baseline oracle checks
all initial populations/roles, inventory totals, literal obstacle/gate/stockpile
geometry, model assignments, infection episodes and 2 m / 15 m spacing. These
checks establish constraints, not uniform conditional placement distribution.

Mixed sequences are generated deterministically in the test authoring layer.
Every admission and completion is sampled; shared snapshot invariants and explicit
resource/hunger/final-position assertions are applied. They supplement hand-worked
conflict, lifecycle and geometry examples. They are bounded generated tests, not a
claim of exhaustive state-space exploration or a property-testing shrinker.
