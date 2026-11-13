"""Produce coverage and an evidence-based report; never label missing checks proved."""
import json
import re
from pathlib import Path
from rdflib import Graph
from rdflib.namespace import RDF,SH,OWL
from build_spec import ROOT,SOURCE,Z,ACTIONS,ROLES,FIELDS

SECTIONS={
 1:('DOCUMENTATION','Version, scope, notation and confirmed choices.','No executable semantics are claimed for introductory prose.'),
 2:('PARTIAL','Core classes, selected disjointness/relationships/cardinalities, state identity and references.','Not every conceptual relation has a complete closed-world shape; cross-run scope is checked for state/world and assignment ownership, not every possible reference.'),
 3:('PARTIAL','World dimensions, point bounds, rectangles, gate integrity/mode, resource stocks/holders, baseline connectivity.','Continuous paths, runtime line of sight, barrier occupancy and construction geometry, sound propagation and signal delivery are not completely formalized.'),
 4:('PARTIAL','Common numeric fields, typed references, identity uniqueness, state status, death cleanup, active actions, role overrides.','Effective-property aggregation, complete cooldown/effect maps and global event provenance are not exhaustively checked.'),
 5:('PARTIAL','Human/zombie numeric dictionaries, inventory capacity, resistance bounds, episode progress, presence of starvation timers.','Continuous hunger accumulation and scheduled damage, feeding recovery, Spitter recharge scheduling and all timer recurrence laws remain behavioral obligations.'),
 6:('PARTIAL','Legal type/status/life combinations, episode timing, cure/conversion/death transition fragments, preserved identity/life/location, no recorded resurrection.','Complete inventory-drop accounting, remains creation, all cancellations, model-memory resets, and stochastic transmission are not proved.'),
 7:('PARTIAL','Eight typed role definitions, profile domains, type compatibility, role capabilities, common overrides and OWL impossible-extension detection.','All role-assignment interval overlap/retirement consequences and future extension equivalence require additional checks.'),
 8:('PARTIAL','Observation self-state/time/observer links, model identifiers/versions, intent/actor relationships.','Visibility completeness, private-memory isolation, stale-message policy, the one-second decision bound, and fallback decisions are not validated.'),
 9:('PARTIAL','Admitted occurrence schema, positive planned durations, actor eligibility/capability, flat stamina, target presence/reach, outcomes, cooldowns and overlap checks.','Full item/charge reservation lifecycle for every action, visibility, every cancellation branch, and global atomicity remain outside complete coverage.'),
 10:('PARTIAL','All four common action definitions with baseline duration/cost/cooldown and possible-effect classification.','The move trajectory, actual-distance energy, rest integration, signal reception and continuous clocks require a behavioral formalism or additional trace validators.'),
 11:('PARTIAL','All eight human action definitions and their common typed admission/resolution fields.','Per-action combat, pickup/drop/transfer/eating/first-aid/gate state effects are not exhaustively checked by the generic occurrence constraints.'),
 12:('PARTIAL','All four base zombie action definitions, ranges and costs; infection-capable versus damage-only classification.','Hit/exposure probability semantics, damage arithmetic, feeding and barrier destruction are not fully checked.'),
 13:('PARTIAL','All thirteen role action definitions; detailed Doctor treatment resource/deadline/lifecycle checks.','Even treatment remains partial: visibility, all self-treatment/cancellation variants and complete frame conditions are not exhaustively checked. Other role-specific effects are metadata, not executable laws.'),
 14:('PARTIAL','Causal-cycle rejection, overlapping actor-action rejection, and exclusion of two resolved reciprocal attacks in supplied traces.','Global equal-time precedence, first-valid winner selection, fair seeded arbitration, parallel serializability and all resource races are not proved.'),
 15:('PARTIAL','Baseline population allocations, seed/horizon, 28 barrier rectangles, 10 stockpiles, resource totals and exact rectangular connectivity.','A 1,000-agent initial placement is not generated. Placement feasibility, statistical significance, model behavior and gameplay balance are not established.'),
 16:('PARTIAL','Run/scenario/model/observation/event/history vocabulary and selected causal/reference constraints.','Full replay sufficiency, restartable private memory, counterfactual coupling and scientific measurement validity need later design and verification.'),
 17:('PARTIAL','Expected-good and expected-bad examples, real HermiT/OWLAPI and pySHACL runs, targeted constraints and diagnostic reports.','Passing examples is finite evidence; it is not exhaustive testing or a proof of every listed invariant.'),
 18:('DOCUMENTATION','Requirements correspondence and review priorities are retained in source and this coverage map.','Review guidance is not an executable game rule.'),
}

INVARIANTS={
 'V01':('UniqueAgentID','All other identity namespaces and cross-run links need broader coverage.'),
 'V02':('PositionBounds RectangleOrder','Continuous trajectories and dynamic obstacles are not covered in full.'),
 'V03':('StateStatus StateTypeFields AgentState_lifeShape','Snapshot checks are covered; complete evolution is not.'),
 'V04':('StateStatus DeadCleanup NoResurrection DeathTypes','Only represented states/transitions are checked; omitted future behavior is not proved.'),
 'V05':('StateStatus EpisodeOwnership','Global episode overlap/history completeness remains partial.'),
 'V06':('EpisodeDeadline EpisodeClosure EpisodeEndOrder CureEpisode ConversionDeadline','All host-death and duplicated lifecycle event cases are not exhaustively checked.'),
 'V07':('TransitionIdentity ConversionTypes ConversionPreserves ConversionDeadline','Inventory drops, cancellations and model-memory resets are gaps.'),
 'V08':('RoleCompatibility AliveAssignments ModelOwnership DeadCleanup','Assignments linked in snapshots are checked; full interval uniqueness is a gap.'),
 'V09':('ActionCapability RequiredTargets ActionAdmission','Complete contracts for all 29 actions are not enforced.'),
 'V10':('ActionState OneActionAtATime ActionDuration AdmissionCooldown ActionCooldown','General reservations and all interruption cases remain partial.'),
 'V11':('AgentState_staminaShape HumanState_hungerShape StarvationTimers','Rate integration and timer recurrence are gaps.'),
 'V12':('InventoryCapacity ReservationBound','Global transfer/consumption conservation remains a gap outside selected treatment checks.'),
 'V13':('ResourceStock_holderShape ReservationBound TreatmentReserve TreatmentConsume TreatmentFailureRelease','Nonmedical reservation release and charge/biomass lifecycles remain partial.'),
 'V14':('PositionBounds','Endpoint checks cannot prove path legality or speed at every instant.'),
 'V15':('ObservationSelf IntentAgreement','Sensing/occlusion/memory privacy and feasibility information leakage are gaps.'),
 'V16':('catalog probability parameter bounds','Actual random draws, sources, independence and their probability law are not validated.'),
 'V17':('AgentState_lifeShape TreatmentEffect CureStates','Physical damage and other healing arithmetic are not fully encoded.'),
 'V18':('StateStatus EpisodeOwnership','Lethal-hit ordering and reinfection transmission event laws remain a gap.'),
 'V19':('ReciprocalAttackExclusion','Winner arbitration and target-invalid ordering still require behavioral verification.'),
 'V20':('GateModeIntegrity GateStateIntegrity BarricadeStateIntegrity','Occupancy/construction race effects are not checked in full.'),
 'V21':('RemainsState_biomassShape BiomassReservation','Exactly one remains per death and biomass creation/consumption histories are not fully checked.'),
 'V22':('EpisodeDeadline InfectionProgress','Continuous clocks, equal-time phase ordering and selection-frequency independence are not proved.'),
 'V23':('baseline SHACL and independent RDF arithmetic/geometry checks','No complete initial agent placement or model execution is generated.'),
 'V24':('NoCausalCycle','Acyclicity is checked; completeness/replayability of the causal record is not proved.'),
 'V25':('StateStatus InfectionProgress RoleOverrides','All derived speed/sensing/effect/armor calculations are not yet checked.'),
}

def main():
    source=SOURCE.read_text(encoding='utf-8');lines=source.splitlines()
    shapes=Graph().parse(ROOT/'shapes.ttl'); ontology=Graph().parse(ROOT/'ontology.ttl')
    cases=json.loads((ROOT/'examples.json').read_text(encoding='utf-8'))
    # Every substantive source line after the navigation is accounted for. IDs
    # reference the frozen SHA-256 source and one-based line numbers, not a claim
    # that every English sentence has been translated into logic.
    units=[]; section=1;subsection='1';fence=False;table_header=False
    for i,line in enumerate(lines,1):
        m=re.match(r'^## (\d+)\.',line)
        if m:section=int(m.group(1));subsection=str(section)
        m=re.match(r'^### (\d+\.\d+)',line)
        if m:subsection=m.group(1)
        if line.startswith('```'):fence=not fence;continue
        if i<62 or fence or not line.strip() or line.startswith('#') or line.startswith('|---'):continue
        if line.startswith('|') and i<len(lines) and lines[i].startswith('|---'):continue
        status,represented,gap=SECTIONS[section]
        units.append({'id':f'MD-L{i:04d}','source_line':i,'section':subsection,'text':line,'status':status,'represented_aspects':represented,'remaining_obligations':gap})
    query_checks=[]
    for constraint,q in sorted(shapes.subject_objects(SH.select),key=lambda kv:str(kv[0])):
        key=str(constraint).split(':')[-1]
        query_checks.append({'constraint':key,'negative_examples':[c['name'] for c in cases if c.get('expected_constraint')==key],'query':str(q)})
    action_coverage=[]
    for a in ACTIONS:
        name=a[0]
        action_coverage.append({'action':name,'status':'PARTIAL','definition':'catalog.ttl#action_'+name,'formalized':'Baseline duration range, flat stamina cost, cooldown, target category, contact reach where applicable, capability provider, possible-effect categories. Generic occurrence checks apply.','specific_checks':['TreatmentTargetRecords','TreatmentStartTarget','TreatmentDeadline','TreatmentEffect','TreatmentSupplyEvidence','TreatmentReserve','TreatmentConsume','TreatmentFailureRelease','TreatmentCureRecord'] if name=='treat_infection' else [],'limitation':'Full action effects, geometry/observation evidence and all cancellation/frame cases are not completely formalized. Copied sourceText is documentation only.'})
    payload={'source':'../zombie_game_ontology_v0.1.md','units':units,'invariants':INVARIANTS,'actions':action_coverage,'sparql_constraint_test_map':query_checks,'interpretation':'PARTIAL identifies meaningful formalized/validated aspects, not full equivalence to the source. DOCUMENTATION is retained human context. No whole action is claimed completely formalized.'}
    (ROOT/'coverage.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    md=['# Formalization coverage','', 'The unchanged Markdown remains the semantic review baseline. This release supplies an OWL core, SHACL validation rules, and a baseline catalog. It is **not a complete formal behavioral specification**. Every action currently has PARTIAL coverage. Prose annotations are never counted as logical axioms or executable checks.','',f'The detailed [coverage register](coverage.json) accounts for **{len(units)} substantive source lines**, all 25 listed invariants, all 29 actions, and each embedded SPARQL constraint. Source IDs use one-based line numbers in the SHA-256-pinned Markdown.','', '| Source section | Status | Represented aspects | Remaining obligations |','|---|---|---|---|']
    for n,(status,done,gap) in SECTIONS.items():md.append(f'| {n} | {status} | {done} | {gap} |')
    md+=['','## Invariant correspondence','','| Source ID | Checks / evidence | Remaining limits |','|---|---|---|']
    for id,(checks,gap) in INVARIANTS.items():md.append(f'| {id} | {checks} | {gap} |')
    md+=['','## Action contracts','','All 29 named actions have structured definitions, capability links and possible-effect classifications in `catalog.ttl`. The common action shapes cover selected admission/timing/capability/reach/cooldown/overlap rules. Doctor treatment additionally has resource, deadline, cure and frame checks. These are finite-trace checks, not execution semantics.','', 'The following still require a separate behavioral specification or additional validators: complete numerical effects for other actions; trajectory/occlusion geometry; all item/charge reservations; exact continuous clocks; all lifecycle side effects; seeded fairness/probability laws; observation privacy; and complete replay history. Choosing the behavioral formalism remains a later design decision. No Common Logic file or theorem-prover result is claimed in this release.','', '## Validation coverage','','| SPARQL constraint | Dedicated expected-failure examples |','|---|---|']
    for q in query_checks:md.append('| '+q['constraint']+' | '+(', '.join(q['negative_examples']) or 'None yet; query parses and is included in conformance runs.')+' |')
    (ROOT/'COVERAGE.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    report_path=ROOT/'reports'/'validation.json'
    if report_path.exists():
        result=json.loads(report_path.read_text(encoding='utf-8')); checks=result['checks']; passed=sum(c['passed'] for c in checks)
        report=['# Validation report','',f'Overall result: **{"PASS" if result["all_passed"] else "FAIL"} — {passed}/{len(checks)} recorded checks met their expected outcomes.**','',f'Execution timestamp (UTC): `{result["generated_at_utc"]}`.','', 'Expected-failure fixtures count as successful tests only when they fail at the named expected constraint. A validation exception or an unrelated violation alone is not counted as a successful negative test.','', '## Tools and reproducibility','',f'- Python: `{result["python"].splitlines()[0]}`',f'- RDFLib: `{result["packages"]["rdflib"]}`',f'- pySHACL: `{result["packages"]["pyshacl"]}`; SHACL Core/SPARQL, explicit RDFS inference; SHACL-JS disabled.',f'- Owlready2: `{result["packages"]["owlready2"]}` supplies the HermiT/OWLAPI JAR. The actual checks call HermiT and OWLAPI through `OwlCheck.java`.',f'- Java: `{result.get("java_version", "not run").splitlines()[0]}`',f'- HermiT JAR SHA-256: `{result.get("hermit_jar_sha256", "not run")}`','', 'The full [machine-readable report](reports/validation.json) records versions, SHA-256 values and individual outcomes. Each SHACL fixture has text and RDF validation reports under `reports/`. OWL reports identify profile violations, consistency and unsatisfiable classes.','', '## Results','','| Check | Result |','|---|---|']
        for c in checks:report.append('| '+c['name']+' | '+('PASS' if c['passed'] else 'FAIL')+' |')
        report += ['', '## Execution location', '', f'Project root: {result["project_root"]}', '', f'Working directory: {result["working_directory"]}', '', f'Python executable: {result["python_executable"]}', '', f'Java executable: {result["java_executable"]}']
        report+=['','## Meaning of this result','','The OWL core and supplied catalog are checked for OWL 2 DL conformance, logical consistency and satisfiability of intended named classes. Separate cases check capability/classification inferences, a consistent conversion history, an inconsistent Human/Zombie state, and an impossible extension class. SHACL validates the named example graphs and baseline data; geometry/arithmetic checks inspect the baseline RDF independently.','', '**This result does not establish that all Markdown requirements are fully formalized or that a simulator implements them correctly.** Refer to [COVERAGE.md](COVERAGE.md) for the explicit missing and partial behavioral checks. No game simulation, training run, statistical-power assessment, or exhaustive temporal/probabilistic verification was performed.','', 'The source Markdown and plan are unchanged. The authoritative scope is TASK 1 in [zombie_game_plans.md](../../prompts/zombie_game_plans.md); the manifest records both source hashes.','']
        (ROOT/'VALIDATION_REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    print(f'Documented {len(units)} source units, 29 actions, 25 invariants and {len(query_checks)} SPARQL constraints.')

if __name__=='__main__':main()
