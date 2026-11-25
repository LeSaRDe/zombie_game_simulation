# Focused formal trace exports

The three `FORMAL_actual_*_trace` integration cases run real controlled
simulations, then export treatment, conversion, or death history. They complement
the numerical/behavioral tests; the existing formal package has explicitly partial
coverage and is not a complete formalization of simulation semantics.

## Adapter operation

`trace.export_turtle(run, kind, subject, label)` exports a focused trace from the
named **executed run**, where `kind` is `treatment`, `conversion`, or `death`, and
`subject` is the agent alias. Return the following capture under
`response.captures[label]`:

```json
{
  "turtle": "@prefix zg: <urn:zombie-game:v0.1:> . ...",
  "bindings": {
    "agents": {"patient": "urn:actual-run:agent:2", "doctor": "urn:actual-run:agent:1"},
    "transition": "urn:actual-run:cure:17",
    "occurrence": "urn:actual-run:action:12"
  }
}
```

Use actual exported agent IRIs; aliases are binding labels, not changes to numeric
`zg:agent_id`. The treatment case binds `patient` and `doctor`, and requires the
`occurrence` binding. Conversion/death bind `h`; `occurrence` is not required.

Export the relevant `zg:Agent`, `zg:AgentState`, `zg:LifecycleTransition` and
specialized transition, episode, assignment, inventory/stock, observation, action,
event, world, run, and scenario dependencies needed by the real shapes. Use the
exact vocabulary in `ontology/formal_v0.1/ontology.ttl` and the catalog. Transition
before/after snapshots share a semantic timestamp and have increasing revisions;
treatment also includes admission and resolution snapshots. Bindings must resolve
to records in the returned graph. Include exactly one focused transition of the
requested kind. Existing example files show the serialization shape, but returning
their contents instead of exporting the executed trace does not implement this
operation. Other run entities may be excluded by this focused export.

No simulator-generated `conforms` flag or validation report is accepted as proof.
The harness reads Turtle itself, combines it with the **repository's** ontology and
catalog, runs the repository's SHACL shapes through pySHACL with RDFS inference,
then checks raw RDF identity, timestamps, life/stamina/hunger, status/type, episode outcome,
and treatment inventory consumption against literal expectations. The adapter
cannot supply replacement shapes. The checker does not invoke OWL/Java tooling,
change ontology files, or rerun the historical release validator/hash audit.

## Runner hook and dependencies

Each case carries `formal_checks` metadata. For each entry `spec`, resolve the JSON
pointer `spec.path` in the response and call
`tests.formal_checks.validate_formal_export(capture, spec)`. The checker raises
`ContractFailure` on invalid/missing exports, conformance failures, inconsistent
facts, or unavailable dependencies. Ordinary case collection uses the standard
library; selected formal integration cases require **RDFLib 7.6.0** and
**pySHACL 0.40.2**, as pinned by the existing formal package requirements. A new
environment can install those two versions and their normal transitive dependencies.
The already provisioned `ontology/formal_v0.1/.venv` contains them.

Independent checker self-tests are deliberately outside the standard-library
harness discovery directory:

```bash
ontology/formal_v0.1/.venv/bin/python -m unittest discover -s tests/formal_harness -v
```

Those self-tests use reviewed static examples solely to test the reader and
validator. Positive samples update copied hunger literals to the actual elapsed
clock; the original illustrative examples hold hunger at 20. A negative check
rejects returning an unchanged static example as an executed trace. Other tests
cover SHACL violations and a graph which passes SHACL but violates the expected
life value. Passing them does not establish product conformance.
