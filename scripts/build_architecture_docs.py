"""Rebuild the offline architecture atlas and code index from local sources.

Requires Graphviz's dot executable and the installed GUI Node/TypeScript tools.
Run: .runtimeenv/bin/python scripts/build_architecture_docs.py
"""
from __future__ import annotations
import ast
from html import escape
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/architecture"


def anchor(path):
    return re.sub(r"[^a-z0-9]+", "-", str(path).lower()).strip("-")


def node(name, label, source=None, color="#e8f2fc"):
    attributes={"label":label,"fillcolor":color}
    if source:
        attributes.update(URL="code-index.html#"+anchor(source),target="_top",tooltip=source)
    return name+" ["+", ".join(key+"="+json.dumps(value,ensure_ascii=False) for key,value in attributes.items())+"];"


def edge(a,b,label="",style="solid"):
    return f'{a} -> {b} [label={json.dumps(label)}, style={json.dumps(style)}];'


def graph(title, nodes, edges, *, direction="LR"):
    return "\n".join([
        "digraph architecture {",f'rankdir={direction};',
        'graph [bgcolor="transparent", pad="0.3", nodesep="0.35", ranksep="0.6", fontname="DejaVu Sans", fontsize=17];',
        'node [shape=box, style="rounded,filled", color="#a4b4c8", fontname="DejaVu Sans", fontsize=12, margin="0.16,0.12"];',
        'edge [color="#64748b", fontcolor="#475569", fontname="DejaVu Sans", fontsize=10, arrowsize=0.7];',
        *[node(*entry) for entry in nodes], *[edge(*entry) for entry in edges], "}"])


DIAGRAMS = [
    ('overview', '1. The complete system', 'The live path separates ontology domain values, game rule calculation, committed state ownership and persistence. Functional React views remain backed by controller objects.',
     graph('1. The complete system', [('user', 'Researcher / model author', None, '#fff0d8'),
 ('entry', 'Launcher · CLI · Python framework', 'src/zombie_sim/framework.py'),
 ('gui', 'Functional React + typed controllers', 'gui/src/views/Workspace.tsx'),
 ('http', 'HTTP / managed run worker', 'src/zombie_sim/services/workspace.py'),
 ('sim', 'Simulation\nexecution coordinator', 'src/zombie_sim/engine.py'),
 ('rules',
  'GameRuleSet\nhandlers + lifecycle + observations',
  'src/zombie_sim/game_rules/session.py',
  '#fff0d8'),
 ('state',
  'StateCoordinator\nWorldAggregate + RuntimeState',
  'src/zombie_sim/state_management/coordinator.py',
  '#e5f5eb'),
 ('domain',
  'Immutable domain values\nAgent · typed state · role · activity · event',
  'src/zombie_sim/domain_model/agents.py'),
 ('ports',
  'PersistenceBundle\natomic write + dated query ports',
  'src/zombie_sim/persistence/bundle.py',
  '#e5f5eb'),
 ('analysis', 'Metrics · cohorts · timeline · exports', 'src/zombie_sim/measurements.py', '#e5f5eb'),
 ('model', 'Decision model\nlocal observation + private memory', 'src/zombie_sim/modeling.py', '#fff0d8')],
       [('user', 'entry'),
 ('user', 'gui'),
 ('gui', 'http', 'HTTP / WS'),
 ('http', 'sim'),
 ('entry', 'sim'),
 ('sim', 'rules', 'request + immutable reads'),
 ('rules', 'state', 'typed TransitionPlan'),
 ('state', 'ports', 'atomic CommitBundle'),
 ('rules', 'domain', 'typed values'),
 ('state', 'domain', 'authoritative values'),
 ('sim', 'model', 'local observations'),
 ('model', 'sim', 'intent + new memory'),
 ('analysis', 'ports', 'read-only dated queries')], direction="TB")),
    ('domain', '2. Persistent identity, typed state and roles', 'Human and Zombie are current AgentState variants. The same AgentIdentity survives conversion. Roles and model assignments are independent, and historical event payloads preserve earlier state values.',
     graph('2. Persistent identity, typed state and roles', [('agent', 'Agent', 'src/zombie_sim/domain_model/agents.py'),
 ('identity', 'AgentIdentity\nrun_id + agent_id', 'src/zombie_sim/domain_model/values.py'),
 ('state', 'AgentState (abstract)', 'src/zombie_sim/domain_model/agents.py'),
 ('human', 'HumanState\nhunger + inventory + starvation', 'src/zombie_sim/domain_model/agents.py'),
 ('zombie', 'ZombieState', 'src/zombie_sim/domain_model/agents.py'),
 ('role', 'RoleAssignment\nper-agent assignment and charges', 'src/zombie_sim/domain_model/roles.py'),
 ('definition',
  'RoleDefinition\nshared immutable parameters/capabilities',
  'src/zombie_sim/domain_model/roles.py'),
 ('humanroles',
  'HumanRoleDefinition\nDoctor · Warrior · Scout · Engineer',
  'src/zombie_sim/domain_model/roles.py'),
 ('zombieroles',
  'ZombieRoleDefinition\nTyrant · Runner · Spitter · Screamer',
  'src/zombie_sim/domain_model/roles.py'),
 ('model', 'ModelAssignment', 'src/zombie_sim/domain_model/agents.py'),
 ('profile',
  'ProfileResolver + shared ProfileValues\ntype → role → overrides → timed effects',
  'src/zombie_sim/domain_model/profiles.py'),
 ('history', 'DomainEvent\ntyped before/after state evidence', 'src/zombie_sim/domain_model/events.py')],
       [('agent', 'identity', '1 stable identity'),
 ('agent', 'state', '1 current state'),
 ('human', 'state', 'inherits'),
 ('zombie', 'state', 'inherits'),
 ('state', 'role', '0..1 active assignment'),
 ('role', 'definition', 'shared definition'),
 ('humanroles', 'definition', 'inherits'),
 ('zombieroles', 'definition', 'inherits'),
 ('state', 'model', '0..1 active controller'),
 ('profile', 'state', 'derive current properties'),
 ('history', 'state', 'retains dated values')], direction="TB")),
    ('engine', '3. Rule calculation and state ownership', 'GameRuleSet never receives a Simulation, database or publisher. Its PlanningSession can mutate only an isolated draft and runtime branch. Typed plans cross the boundary to revision validation and atomic publication.',
     graph('3. Rule calculation and state ownership', [('sim', 'Simulation._run_rule', 'src/zombie_sim/engine.py'),
 ('request', 'RuleRequest', 'src/zombie_sim/game_rules/session.py'),
 ('rules', 'GameRuleSet', 'src/zombie_sim/game_rules/session.py'),
 ('session', 'PlanningSession\nisolated WorldDraft + runtime fork', 'src/zombie_sim/game_rules/session.py'),
 ('handlers', 'ActionHandlerRegistry\n29 named handlers', 'src/zombie_sim/game_rules/handlers.py'),
 ('lifecycle',
  'Damage / Resource / Infection / Death /\nConversion / Effect / Signal / Geometry rules',
  'src/zombie_sim/game_rules/lifecycle.py'),
 ('plan',
  'TransitionPlan\nStateChange + DomainEvent + RuntimeSnapshot',
  'src/zombie_sim/game_rules/session.py'),
 ('coordinator',
  'StateCoordinator + UnitOfWork\nvalidate revision, invariants and references',
  'src/zombie_sim/state_management/coordinator.py'),
 ('world',
  'WorldAggregate\nimmutable typed authoritative values',
  'src/zombie_sim/state_management/world.py'),
 ('runtime',
  'RuntimeState\nexact queue + memory + counters',
  'src/zombie_sim/state_management/runtime_state.py')],
       [('sim', 'request', 'construct'),
 ('sim', 'rules', 'read-only world + snapshot'),
 ('request', 'rules'),
 ('rules', 'session', 'new per request'),
 ('session', 'handlers', 'dispatch'),
 ('session', 'lifecycle', 'apply semantic rules'),
 ('session', 'plan', 'return'),
 ('sim', 'coordinator', 'begin/commit plan'),
 ('plan', 'coordinator'),
 ('coordinator', 'world', 'replace after durability'),
 ('sim', 'runtime', 'adopt confirmed continuation')], direction="TB")),
    ('flow', '4. One atomic simulation transition', 'The ontology time phases and canonical random keys are unchanged. Rules produce a proposal without publication; the atomic persistence result determines whether the new typed world becomes visible.',
     graph('4. One atomic simulation transition', [('queue',
  'ScheduledTask heap\nFraction time, phase, priority, serial',
  'src/zombie_sim/domain_model/activities.py'),
 ('boundary',
  'ScheduledBoundary\nretain prior runtime; stage heap + decision set',
  'src/zombie_sim/execution/scheduled_boundary.py'),
 ('rules',
  'GameRuleSet.plan\nimmutable WorldReadView + RuntimeSnapshot',
  'src/zombie_sim/game_rules/session.py'),
 ('draft',
  'PlanningSession\nread set, changed entities, causal events',
  'src/zombie_sim/game_rules/session.py'),
 ('plan', 'TransitionPlan\nexpected revision + typed changes', 'src/zombie_sim/game_rules/session.py'),
 ('validate',
  'UnitOfWork\nstale-read + transition validation',
  'src/zombie_sim/state_management/coordinator.py'),
 ('bundle',
  'CommitBundle\nworld delta + runtime delta + events + receipt',
  'src/zombie_sim/persistence/contracts.py'),
 ('atomic',
  'AtomicCommitPort.commit\nrevision + transaction identity',
  'src/zombie_sim/persistence/contracts.py'),
 ('resolve',
  'resolve_transaction\nrecover uncertain commit outcome',
  'src/zombie_sim/persistence/contracts.py'),
 ('publish',
  'Publish immutable WorldAggregate\nadopt RuntimeState; notify ledger views',
  'src/zombie_sim/engine.py')],
       [('queue', 'boundary', 'due work'),
 ('boundary', 'rules', 'reversible preparation'),
 ('rules', 'draft'),
 ('draft', 'plan'),
 ('plan', 'validate'),
 ('validate', 'bundle'),
 ('bundle', 'atomic'),
 ('atomic', 'publish', 'durable success'),
 ('atomic', 'resolve', 'outcome unknown'),
 ('resolve', 'publish', 'identity confirmed'),
 ('atomic', 'boundary', 'failure before publication: restore', 'dashed')], direction="TB")),
    ("workspace", "5. Managed runs, HTTP and analysis", "WorkspaceServices owns the application lifetime. Each run has one writer process. Read pools and exporters operate on committed history. Shutdown drains accepted work, closes readers/viewers, and reconciles run controls before service exit.",
     graph("Workspace", [
        ("http","WorkspaceHTTPApplication\nFastAPI composition + lifecycle","src/zombie_sim/server.py"),
        ("controllers","ConfigurationHTTPController\nRunHTTPController / HTTPReadController\nLiveViewSession per socket","src/zombie_sim/server.py"),
        ("ws","WorkspaceServices\nclose() / context manager","src/zombie_sim/services/workspace.py"),
        ("manager","RunManager\napplication use cases + coordination","src/zombie_sim/application.py"),
        ("repo","RunRepository\nmanager journal + registered runs","src/zombie_sim/application.py","#e5f5eb"),
        ("supervisor","WorkerSupervisor\nprocess start · status · cleanup","src/zombie_sim/application.py"),
        ("worker","RunWorker\nwriter lease + engine + control loop","src/zombie_sim/application.py"),
        ("queries","HistoryQueryService\nWAL readers + bounded snapshot cache","src/zombie_sim/application.py","#e5f5eb"),
        ("reads","ReadPool class\nordinary pool + separate export pool\ncancellable reader processes","src/zombie_sim/read_tasks.py"),
        ("child","Read-only RunManager per reader child\nseparate repository, caches and registry","src/zombie_sim/application.py","#e5f5eb"),
        ("child_queries","Child HistoryQueryService\nchild-owned WAL readers / caches","src/zombie_sim/application.py","#e5f5eb"),
        ("child_analysis","Child analysis-service instances\nmetrics · comparison · timeline · visualization","src/zombie_sim/metrics.py","#e5f5eb"),
        ("journal","manager.sqlite\nshared durable commands / run metadata",None,"#e5f5eb"),
        ("ops","ReadOperationRegistry\nexplicit operation → handler","src/zombie_sim/read_tasks.py","#fff0d8"),
        ("analysis","MetricsService / ComparisonService\nTimelineService / SurvivalMeasurement\nVisualizationService","src/zombie_sim/metrics.py","#e5f5eb"),
        ("exports","ExportJobs → ExportService\nExportRendererRegistry + 6 strategies","src/zombie_sim/export_jobs.py"),
        ("shutdown","ShutdownCoordinator\ndrain · reconcile · stop · close","src/zombie_sim/service_shutdown.py"),
        ("commands","CommandReceiptService / ScriptCommandService\nimmutable request identity + recovery","src/zombie_sim/command_recovery.py")],
       [("http","ws","owns"),("http","controllers"),("controllers","manager"),("controllers","reads"),
        ("ws","manager"),("ws","reads"),("ws","exports"),("ws","shutdown"),
        ("manager","repo"),("manager","supervisor"),("manager","queries"),("manager","analysis"),
        ("supervisor","worker","one process / run"),("worker","journal","own journal connection"),("repo","journal"),
        ("reads","child","one per process"),("child","ops"),("child","child_queries"),("child","child_analysis"),
        ("ops","child_analysis"),("ops","child_queries"),("child","journal","read-only repository"),
        ("exports","reads","creates own export pool"),("commands","repo"),("shutdown","manager"),("shutdown","exports"),("shutdown","reads") ],direction="TB")),
    ('storage', '6. Persistence contracts and restart', 'State ownership is independent of storage. Memory live projections, durable SQLite journals and a fully independent in-memory contract backend implement the same transaction/read boundaries. Unsupported schema or implementation versions fail explicitly.',
     graph('6. Persistence contracts and restart', [('sim', 'Simulation / StateCoordinator', 'src/zombie_sim/state_management/coordinator.py'),
 ('factory', 'PersistenceFactoryPort\ndefault PersistenceBundleFactory', 'src/zombie_sim/persistence/bundle.py'),
 ('bundle',
  'PersistenceBundle\ncompatible atomic/read/checkpoint adapters',
  'src/zombie_sim/persistence/bundle.py'),
 ('atomic', 'AtomicCommitPort', 'src/zombie_sim/persistence/contracts.py'),
 ('read', 'HistoryQueryPort', 'src/zombie_sim/persistence/contracts.py'),
 ('sql',
  'History + SQLiteHistoryQueries\nMemoryStore / SQLiteStore',
  'src/zombie_sim/persistence/sqlite_queries.py'),
 ('memory',
  'InMemoryHistory + MemoryStore\nindependent nondurable backend',
  'src/zombie_sim/persistence/memory.py'),
 ('checkpoint',
  'CheckpointAdapter + RuntimeService\nversioned codecs + owned publication generation',
  'src/zombie_sim/persistence/checkpoint.py'),
 ('research', 'Metrics · cohorts · comparison · export', 'src/zombie_sim/metrics.py'),
 ('manifest',
  'Implementation manifest\nlegacy-read/default restart compatibility',
  'src/zombie_sim/persistence/versioning.py')],
       [('factory', 'bundle', 'creates'),
 ('sim', 'bundle', 'injected owner'),
 ('bundle', 'atomic', 'write port'),
 ('bundle', 'read', 'query port'),
 ('atomic', 'sql', 'durable implementation'),
 ('atomic', 'memory', 'contract implementation'),
 ('read', 'sql', 'dated queries'),
 ('read', 'memory', 'same contract'),
 ('research', 'read', 'no SQL knowledge'),
 ('checkpoint', 'read', 'verified prefix'),
 ('checkpoint', 'manifest', 'validate before restore')], direction="TB")),
    ('runtime', '7. Snapshot isolation without whole-memory copies', 'Runtime snapshots retain immutable cells. Exact built-in trees use copy-on-write branches; custom or aliased Python graphs use per-agent opaque copies. Unread model memories retain stable cell identities. Queue forks stay concrete heap-compatible lists of immutable ScheduledTask values.',
     graph('7. Snapshot isolation without whole-memory copies', [('runtime',
  'RuntimeState\nexplicit durable field register',
  'src/zombie_sim/state_management/runtime_state.py'),
 ('snapshot',
  'RuntimeSnapshot\nimmutable cells + field presence',
  'src/zombie_sim/state_management/runtime_state.py'),
 ('branch',
  'RuntimeState fork\nbranch-owned config / memory wrappers',
  'src/zombie_sim/state_management/runtime_state.py'),
 ('mapping', 'MappingCell / SequenceCell / OpaqueCell', 'src/zombie_sim/state_management/runtime_values.py'),
 ('cow',
  'CowDict / CowList\nnested mutations remain local',
  'src/zombie_sim/state_management/runtime_values.py'),
 ('opaque',
  'Opaque private memory\npreserve custom types, aliases and cycles',
  'src/zombie_sim/state_management/runtime_values.py'),
 ('journal',
  'RuntimeService.capture_delta\nstable cell tokens identify changes',
  'src/zombie_sim/core/runtime_service.py'),
 ('codec',
  'Explicit JSON / runtime boundary\nplain records preserve list vs tuple',
  'src/zombie_sim/value_codec.py')],
       [('runtime', 'snapshot', 'seal'),
 ('snapshot', 'mapping', 'share immutable values'),
 ('snapshot', 'branch', 'fork'),
 ('branch', 'cow', 'owns wrappers'),
 ('cow', 'mapping', 'reuse until changed'),
 ('branch', 'opaque', 'detach on writable access'),
 ('branch', 'journal', 'changed continuation'),
 ('journal', 'codec', 'encode changed cells only')], direction="TB")),
    ("gui", "8. GUI objects behind functional React views", "React still renders and subscribes. Controllers own requests, retries, generation checks, caches and cleanup. Canvas and Plotly drawing have dedicated owners. Exact rational values remain authoritative; rounded labels are presentation only.",
     graph("GUI", [
        ("main","main.tsx → Workspace\nReact composition entrypoint","gui/src/main.tsx"),
        ("views","Functional views\nConfiguration · World · InterventionDialog\ncharts · tables · inspection panels","gui/src/views/Configuration.tsx"),
        ("api","ApiClient\ntransport + abort + instrumentation","gui/src/core/ApiClient.ts"),
        ("observable","ObservableController\nsubscribe / notify / cleanup","gui/src/core/ObservableController.ts"),
        ("catalog","RunCatalog\nmonotonic summaries + polling","gui/src/core/RunCatalog.ts"),
        ("editor","ConfigurationEditor\natomic draft + validation + preview + launch","gui/src/core/ConfigurationEditor.ts"),
        ("command","CommandSession + ExecutionSession\nretained requests + receipt reconciliation","gui/src/core/CommandSession.ts"),
        ("view","ViewSession\nseek generations + WS follow lifecycle","gui/src/core/ViewSession.ts"),
        ("query","QueryReader\nsingle in-flight request + cancellation","gui/src/core/QueryReader.ts"),
        ("readers","StatisticsReader / CohortReader\nEventsReader / ComparisonReader","gui/src/core/AnalysisReaders.ts"),
        ("export","ExportSession\nexport job polling + cancellation","gui/src/core/ExportSession.ts"),
        ("world","WorldRenderer\nCanvas scene + transforms + hit testing","gui/src/core/WorldRenderer.ts"),
        ("plot","PopulationPresenter / ComparisonPresenter\nPlotlyHost serializes draw + purge","gui/src/core/PlotlyHost.ts"),
        ("time","ExactTime / ExactCursor\nTimeValue / ExactTimeInput","gui/src/core/contracts.ts","#fff0d8")],
       [("main","views"),
        *[("views",n,"owns / subscribes") for n in ("catalog","editor","command","export")],
        *[(n,"observable","extends","dashed") for n in ("catalog","editor","command","export")],
        ("views","view"),("views","readers","thin hooks"),("readers","query","inherits"),
        *[(n,"api") for n in ("catalog","editor","view","readers")],
        ("views","world"),("views","plot"),("views","time") ])),
    ("modeling", "9. Modeling, research and training", "Extend behavior by implementing small contracts. Biological type, role, model assignment and persistent identity are separate. Model input has no global-state lookup. Learning keeps its existing pinned kernels and adds injectable orchestration.",
     graph("Modeling", [
        ("framework","SimulationFramework\nconfiguration + model registry + factories","src/zombie_sim/framework.py"),
        ("builder","ScenarioBuilder\nvalidated, detached configuration records","src/zombie_sim/modeling.py"),
        ("experiment","Experiment\nadvance · observe · snapshot · checkpoint\nexplicit close / context manager","src/zombie_sim/framework.py"),
        ("world","WorldView → AgentView\nHistoryCursor + scoped AgentIdentity","src/zombie_sim/entities.py","#e5f5eb"),
        ("observe","ObservationView → AgentView\nlocal immutable facts; unscoped local IDs","src/zombie_sim/entities.py","#fff0d8"),
        ("model","ObjectDecisionModel (abstract)\nchoose / initial_memory / memory codecs","src/zombie_sim/modeling.py","#fff0d8"),
        ("decision","Decision → ActionIntent\nexisting ontology action vocabulary","src/zombie_sim/entities.py"),
        ("registry","ModelRegistry / ModelCatalog\nlegacy factory compatibility + metadata","src/zombie_sim/modeling.py"),
        ("measure","MeasurementRegistry\npure versioned Measurement strategies","src/zombie_sim/measurements.py","#fff0d8"),
        ("train","TrainingPipeline / EvaluationPipeline\nscenario · splits · output · backend","src/zombie_sim/training_pipeline.py"),
        ("backend","LearningBackend protocol\nRecurrentPPOBackend","src/zombie_sim/training_pipeline.py","#fff0d8"),
        ("learning","ControlledAgentEnv / DecisionBatchAEC\nCandidateCodec / LearnedModel\nbyte-preserved learning kernels","src/zombie_sim/learning.py"),
        ("builtin","HumanDefaultModel / ZombieDefaultModel\nRandomLegalModel / UtilityModel\nbyte-preserved policy kernels","src/zombie_sim/policies.py")],
       [("framework","builder"),("framework","experiment"),("framework","registry"),
        ("experiment","world","snapshot"),("experiment","observe","observe"),("observe","model","choose input"),
        ("model","decision"),("registry","model","creates"),("registry","builtin","creates"),
        ("experiment","measure"),("world","measure","read-only input"),
        ("train","backend","injectable","dashed"),("backend","learning"),("learning","registry","model artifact") ],direction="TB"))
]

CSS = """*{box-sizing:border-box}body{margin:0;background:#f4f7fb;color:#172a40;font:16px/1.6 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:34px}h1{font-size:36px;line-height:1.15;margin:8px 0 16px}h2{line-height:1.25}a{color:#145e9f}header{max-width:1000px;margin-bottom:24px}.eyebrow{letter-spacing:.12em;text-transform:uppercase;font-size:12px;font-weight:700;color:#42627f}.lead{font-size:19px}.card,details{background:white;border:1px solid #d6e0eb;border-radius:12px;padding:24px;margin:20px 0;box-shadow:0 3px 12px #1e395407}nav{display:flex;flex-wrap:wrap;gap:10px}nav a,.button{border:1px solid #bdcede;border-radius:8px;background:white;padding:7px 12px;text-decoration:none}figure{margin:0}.canvas{overflow:auto;border-top:1px solid #e2e8f0;margin-top:18px;padding:15px 0}.canvas svg{width:100%;height:auto;min-width:720px;display:block}.tools{display:flex;align-items:center;gap:18px;flex-wrap:wrap;font-size:14px}.tools input{width:160px}code{font-family:ui-monospace,monospace;font-size:.86em}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f9;padding:14px;border-radius:8px}summary{cursor:pointer;font-weight:650}table{width:100%;border-collapse:collapse}td,th{padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}small,.muted{color:#50677f}#filter{width:100%;padding:12px;font:inherit;border:1px solid #a9bed3;border-radius:8px}details:target{border-color:#145e9f}body.index main{max-width:1100px}.symbols{margin-top:14px}footer{padding:25px 0;color:#50677f}@media(max-width:700px){main{padding:16px}.card,details{padding:16px}h1{font-size:28px}}@media print{body{background:white}main{max-width:none;padding:0}.tools,nav,#filter{display:none}.card{break-inside:avoid;box-shadow:none}.canvas svg{min-width:0}details{break-inside:avoid}}"""


def page(title, body, index=False):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(title)+'</title><style>'+CSS+'</style><body'+(' class="index"' if index else '')+'><main>'+body+'</main></body></html>'


def typescript_inventory(paths):
    program=r'''
const fs=require('node:fs'),ts=require(process.argv[1]);
const files=JSON.parse(fs.readFileSync(0,'utf8')),result={};
for(const file of files){
 const tree=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true,file.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS);
 const symbols=[];
 for(const item of tree.statements){
  const kind=ts.isClassDeclaration(item)?'class':ts.isInterfaceDeclaration(item)?'interface':ts.isTypeAliasDeclaration(item)?'type':ts.isFunctionDeclaration(item)?'function':null;
  if(!kind)continue;
  const name=item.name?.getText(tree)||'default',methods=[];
  for(const member of item.members||[]){
   if(!ts.isMethodDeclaration(member)&&!ts.isConstructorDeclaration(member)&&!ts.isGetAccessor(member)&&!ts.isSetAccessor(member)&&!ts.isMethodSignature(member))continue;
   const method=ts.isConstructorDeclaration(member)?'constructor':member.name.getText(tree);
   const signature=method+'('+member.parameters.map(p=>p.getText(tree)).join(', ')+')'+(member.type?': '+member.type.getText(tree):'');
   methods.push({name:method,signature,line:tree.getLineAndCharacterOfPosition(member.getStart(tree)).line+1});
  }
  symbols.push({kind,name,line:tree.getLineAndCharacterOfPosition(item.getStart(tree)).line+1,methods});
 }
 result[file]=symbols;
}
process.stdout.write(JSON.stringify(result));
'''
    result=subprocess.run([str(ROOT/'.runtimeenv/bin/node'),'-e',program,str(ROOT/'gui/node_modules/typescript')],input=json.dumps([str(p) for p in paths]),text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


def code_index():
    files=sorted((ROOT/"src/zombie_sim").rglob("*.py"))+sorted((ROOT/"gui/src").rglob("*.ts"))+sorted((ROOT/"gui/src").rglob("*.tsx"))+sorted((ROOT/"scripts").glob("*.py"))
    sections=[]; inventory=[]
    typed=typescript_inventory([p for p in files if p.suffix in ('.ts','.tsx')])
    for path in files:
        if any(part in {"__pycache__","spec","static"} for part in path.parts): continue
        relative=path.relative_to(ROOT); source=path.read_text(); rows=[]; symbols=[]; description=""
        if path.suffix==".py":
            tree=ast.parse(source); description=ast.get_docstring(tree) or ""
            for item in tree.body:
                if isinstance(item,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                    kind="class" if isinstance(item,ast.ClassDef) else "function"
                    signature=(item.name+'('+', '.join(ast.unparse(x) for x in item.bases)+')') if kind=='class' else item.name+'('+ast.unparse(item.args)+')'
                    methods=[{"name":m.name,"line":m.lineno,"signature":m.name+'('+ast.unparse(m.args)+')'} for m in getattr(item,"body",[]) if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef))] if kind=='class' else []
                    symbols.append({"kind":kind,"name":item.name,"line":item.lineno,"signature":signature,"methods":methods})
                    doc=ast.get_docstring(item) or ""
                    methods_html=''.join('<li><code>'+escape(m['signature'])+'</code> <small>line '+str(m['line'])+'</small></li>' for m in methods)
                    rows.append('<div class="symbols"><strong>'+kind+'</strong> <code>'+escape(signature)+'</code> <small>line '+str(item.lineno)+'</small>'+('<p>'+escape(doc)+'</p>' if doc else '')+('<details><summary>Methods ('+str(len(methods))+')</summary><ul>'+methods_html+'</ul></details>' if methods else '')+'</div>')
        else:
            symbols=typed[str(path)]
            for symbol in symbols:
                methods=symbol['methods']
                methods_html=''.join('<li><code>'+escape(m['signature'])+'</code> <small>line '+str(m['line'])+'</small></li>' for m in methods)
                rows.append('<div class="symbols"><strong>'+symbol['kind']+'</strong> <code>'+escape(symbol['name'])+'</code> <small>line '+str(symbol['line'])+'</small>'+('<details><summary>Methods ('+str(len(methods))+')</summary><ul>'+methods_html+'</ul></details>' if methods else '')+'</div>')
            if not rows: rows=['<p>View, hook, pure helper, or composition module. Open the source for declarations.</p>']
        inventory.append({"path":str(relative),"lines":len(source.splitlines()),"description":description,"symbols":symbols})
        sections.append('<details id="'+anchor(relative)+'"><summary>'+escape(str(relative))+' <small>· '+str(len(source.splitlines()))+' lines</small></summary><p><a href="../../'+str(relative)+'">Open source file</a></p>'+('<p>'+escape(description)+'</p>' if description else '')+''.join(rows)+'</details>')
    body='<header><div class="eyebrow">Zombie Simulation • code atlas</div><h1>Find the owning class</h1><p>Generated from current Python AST and TypeScript declarations. Search a class, method, or file. Class methods expand below each entry. Python compatibility functions and pure helpers are included.</p><nav><a href="index.html">Architecture diagrams</a><a href="../ARCHITECTURE.md">Reading guide</a><a href="code-index.json">Machine-readable index</a></nav></header><label for="filter">Filter '+str(len(inventory))+' modules</label><input id="filter" type="search" placeholder="Try SchedulerService, checkpoint, QueryReader, training…">'+''.join(sections)
    body+='''<script>const entries=[...document.querySelectorAll('main>details')];document.querySelector('#filter').addEventListener('input',event=>{const q=event.target.value.toLowerCase();for(const entry of entries){entry.hidden=!entry.textContent.toLowerCase().includes(q);if(q&&!entry.hidden)entry.open=true;else if(!q)entry.open=false;}});function reveal(){const id=location.hash.slice(1),target=document.getElementById(id);if(target){target.open=true;target.scrollIntoView();}}addEventListener('hashchange',reveal);reveal();</script>'''
    (OUT/'code-index.html').write_text(page("Zombie Simulation · Code index",body,True))
    (OUT/'code-index.json').write_text(json.dumps(inventory,indent=2)+"\n")
    return inventory


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    inventory=code_index()
    body='<header><div class="eyebrow">Zombie Simulation • architecture atlas</div><h1>From a model idea to an audited run</h1><p class="lead">Nine linked diagrams explain the framework’s objects, ownership and execution. Click any implementation box to open its code-index entry.</p><p>Designed for offline use. Every diagram has an editable Graphviz source and a standalone SVG. Use the zoom slider to inspect labels; drag the horizontal scrollbar when zoomed.</p><nav><a href="code-index.html">Search all '+str(len(inventory))+' code modules</a><a href="../ARCHITECTURE.md">Read the architecture guide</a><a href="../OOP_REFACTOR.md">Changes and verification</a></nav></header><nav>'+''.join('<a href="#'+name+'">'+escape(title.split('. ',1)[1])+'</a>' for name,title,_,_ in DIAGRAMS)+'</nav>'
    for name,title,description,dot in DIAGRAMS:
        (OUT/(name+'.dot')).write_text(dot+'\n')
        subprocess.run(['dot','-Tsvg',str(OUT/(name+'.dot')),'-o',str(OUT/(name+'.svg'))],check=True)
        svg=(OUT/(name+'.svg')).read_text(); svg=svg[svg.index('<svg'):]
        body+='<section class="card" id="'+name+'"><h2>'+escape(title)+'</h2><p>'+escape(description)+'</p><div class="tools"><label>Zoom <input type="range" min="100" max="300" step="25" value="100" aria-label="Zoom '+escape(title)+'"></label><a href="'+name+'.svg">Open SVG</a><a href="'+name+'.dot">Editable DOT</a></div><figure class="canvas">'+svg+'</figure></section>'
    body+='<footer>Generated from the repository by scripts/build_architecture_docs.py. Pure numerical/serialization functions and thin process/HTTP entrypoints intentionally remain functions; object ownership follows state and behavior.</footer><script>for(const slider of document.querySelectorAll("input[type=range]")){slider.addEventListener("input",()=>{slider.closest("section").querySelector("svg").style.width=slider.value+"%";});}</script>'
    (OUT/'index.html').write_text(page("Zombie Simulation · Architecture atlas",body))
    print(json.dumps({"diagrams":len(DIAGRAMS),"indexed_modules":len(inventory),"output":str(OUT/'index.html')}))


if __name__=="__main__": main()
