"""Build reviewable OWL/SHACL artifacts from a versioned, explicit formalization.

This is specification authoring/validation tooling, not the simulation engine.
The unchanged Markdown is the requirements source; extracted prose is labelled
documentation, never counted as an executable constraint.
"""
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import re

from rdflib import Graph, Namespace, URIRef, BNode, Literal
from rdflib.namespace import RDF, RDFS, OWL, XSD, SH
from rdflib.collection import Collection

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'zombie_game_ontology_v0.1.md'
PLAN = ROOT.parent.parent / 'prompts' / 'zombie_game_plans.md'
BASELINE_SHA256 = '20620b8f7f01a3b758fcbea0f0ca83ea3e65a5354071e6d7ef4dfa21a7ec9641'
Z = Namespace('urn:zombie-game:v0.1:')
PREFIX = 'PREFIX zg: <urn:zombie-game:v0.1:>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n'

def graph():
    g = Graph()
    for p,n in [('zg',Z),('owl',OWL),('rdfs',RDFS),('rdf',RDF),('xsd',XSD),('sh',SH)]: g.bind(p,n)
    return g

def lit(v):
    if isinstance(v, bool): return Literal(v)
    if isinstance(v, int): return Literal(v, datatype=XSD.integer)
    if isinstance(v, (float, Decimal)): return Literal(str(v), datatype=XSD.decimal)
    return Literal(v)

def seq(g, values):
    b=BNode(); Collection(g,b,list(values)); return b

def restriction(g, prop, kind, value):
    b=BNode(); g.add((b,RDF.type,OWL.Restriction)); g.add((b,OWL.onProperty,prop)); g.add((b,kind,value)); return b

def intersection(g, values):
    b=BNode(); g.add((b,RDF.type,OWL.Class)); g.add((b,OWL.intersectionOf,seq(g,values))); return b

def save(g, name):
    g.serialize(ROOT/name, format='turtle')

def different(g, values):
    b=BNode(); g.add((b,RDF.type,OWL.AllDifferent)); g.add((b,OWL.distinctMembers,seq(g,values)))

# (class, name, datatype, minimum, maximum, required). Bounds are inclusive.
FIELDS=[]
def fields(cls, names, dtype=XSD.decimal, lo=0, hi=None, required=True):
    for name in names.split(): FIELDS.append((cls,name,dtype,lo,hi,required))

fields('Agent','agent_id',XSD.integer,1)
fields('Agent','created_at')
fields('AgentState','atTime')
fields('AgentState','revision',XSD.integer)
fields('AgentState','life',XSD.integer,0,100)
fields('AgentState','max_life',XSD.integer,100,100)
fields('AgentState','x y speed sense_r base_sense_r movement_cost rest_rate')
fields('AgentState','base_speed',lo=None)
fields('AgentState','stamina',lo=0,hi=100)
fields('AgentState','max_stamina',lo=100,hi=100)
fields('AgentState','base_damage_resistance damage_resistance',hi=0.8)
fields('AgentState','death_at',required=False)
fields('HumanState','hunger',hi=100)
fields('HumanState','hunger_rate')
fields('HumanState','combat_skill medical_skill infection_resistance infection_resistance_effective infection_progress',hi=1)
fields('HumanState','melee_damage carry_capacity',XSD.integer)
fields('HumanState','starvation_started_at next_starvation_damage_at',required=False)
fields('ZombieState','attack_skill virulence',hi=1)
fields('ZombieState','claw_damage bite_damage feed_healing',XSD.integer)
fields('ZombieState','feed_energy')
fields('World','length width',lo=None)
fields('InfectionEpisode','onset_at conversion_due_at')
fields('InfectionEpisode','incubation_duration',lo=None)
fields('InfectionEpisode','onset_revision',XSD.integer)
fields('InfectionEpisode','ended_at',required=False)
fields('InfectionEpisode','end_revision',XSD.integer,required=False)
fields('RoleAssignment','start_at')
fields('RoleAssignment','end_at',required=False)
fields('ModelAssignment','start_at')
fields('ModelAssignment','end_at',required=False)
fields('Cooldown','until')
fields('ResourceStock','quantity reserved',XSD.integer)
fields('EnvironmentState','atTime')
fields('EnvironmentState','revision',XSD.integer)
fields('GateState','integrity',XSD.integer)
fields('GateState','max_integrity',XSD.integer,1)
fields('BarricadeState','integrity',XSD.integer)
fields('BarricadeState','max_integrity',XSD.integer,1)
fields('Rectangle','xmin ymin xmax ymax')
fields('Point','x y')
fields('RemainsState','biomass reserved_biomass',XSD.integer)
fields('TimedEffect','start_at end_at magnitude')
fields('Signal','emitted_at expires_at radius')
fields('Observation','atTime')
fields('Observation','revision',XSD.integer)
fields('Event','atTime')
fields('Event','revision',XSD.integer)
fields('ActionIntent','proposedAt')
fields('PopulationAllocation','count',XSD.integer,0)
fields('ActionOccurrence','startTime plannedEnd')
fields('ActionOccurrence','resolvedAt',required=False)
fields('ActionDefinition','duration_min duration_max',lo=None)
fields('ActionDefinition','stamina_cost cooldown')
fields('ActionDefinition','reach',required=False)
fields('SpitterState','spit_charges',XSD.integer)
fields('SpitterState','next_charge_at',required=False)

# Stable baseline registry: action, duration min/max, stamina, cooldown, reach,
# capability provider, possible effect categories. Exact contract text is copied
# separately from the Markdown to make partial semantic coverage explicit.
ACTIONS=[
 ('move',.25,5,0,0,None,'ALL','Movement'),
 ('wait',.25,5,0,0,None,'ALL','Waiting'),
 ('rest',1,5,0,0,None,'ALL','StaminaRestoration'),
 ('signal',.5,.5,1,2,None,'ALL','Communication'),
 ('melee',1,1,6,1,1.5,'Human','PhysicalDamage'),
 ('pickup',1,1,1,0,1.5,'Human','ResourceTransfer'),
 ('drop',.5,.5,0,0,None,'Human','ResourceTransfer'),
 ('transfer',1,1,1,0,1.5,'Human','ResourceTransfer'),
 ('eat',2,2,0,0,None,'Human','HungerReduction'),
 ('first_aid',3,3,4,2,1.5,'Human','LifeRestoration'),
 ('open_gate',1,1,1,0,2,'Human','GateOpening'),
 ('close_gate',1,1,1,0,2,'Human','GateClosing'),
 ('claw',1,1,6,1,1.5,'Zombie','PhysicalDamage'),
 ('bite',1.5,1.5,10,2,1.5,'Zombie','PhysicalDamage InfectionOnset'),
 ('feed',3,3,0,1,1.5,'Zombie','LifeRestoration StaminaRestoration'),
 ('smash',2,2,10,1,2,'Zombie','BarrierDamage'),
 ('treat_infection',4,4,6,2,1.5,'DOCTOR','InfectionCure'),
 ('prophylaxis',4,4,6,2,1.5,'DOCTOR','Prophylaxis'),
 ('power_strike',1.5,1.5,15,6,1.5,'WARRIOR','PhysicalDamage'),
 ('guard',1,1,8,8,None,'WARRIOR','Guard'),
 ('recon',2,2,6,20,None,'SCOUT','Recon'),
 ('mark_target',.5,.5,1,3,None,'SCOUT','Communication'),
 ('build_barricade',8,8,12,2,2,'ENGINEER','Construction'),
 ('repair_barrier',5,5,8,1,2,'ENGINEER','BarrierRepair'),
 ('rally',2,2,15,20,None,'TYRANT','Rallied Communication'),
 ('demolish',3,3,18,6,2,'TYRANT','BarrierDamage'),
 ('dash',1,1,12,8,None,'RUNNER','Movement Dash'),
 ('spit',1,1,8,8,12,'SPITTER','PhysicalDamage InfectionOnset'),
 ('scream',2,2,15,30,None,'SCREAMER','Communication'),
]
ROLES={
 'DOCTOR':('Human',{'medical_skill':.9,'treatment_duration':4.,'treatment_cost':1,'prophylaxis_resistance':.8,'prophylaxis_duration':120.}),
 'WARRIOR':('Human',{'combat_skill':.85,'melee_damage':22,'base_damage_resistance':.2,'strike_damage':34,'guard_resistance':.6,'guard_duration':4.}),
 'SCOUT':('Human',{'base_speed':2.6,'base_sense_r':55.,'recon_radius':85.,'recon_duration':12.,'mark_radius':90.}),
 'ENGINEER':('Human',{'carry_capacity':16,'build_integrity':100,'build_material_cost':2,'repair_amount':60,'repair_material_cost':1}),
 'TYRANT':('Zombie',{'base_speed':1.3,'base_damage_resistance':.3,'claw_damage':24,'attack_skill':.65,'rally_radius':30.,'rally_duration':10.,'rally_hit_bonus':.1,'demolish_damage':60}),
 'RUNNER':('Zombie',{'base_speed':3.2,'claw_damage':10,'dash_multiplier':1.5,'dash_duration':1.}),
 'SPITTER':('Zombie',{'base_speed':1.4,'spit_range':12.,'spit_damage':4,'spit_potency':.3,'max_spit_charges':3,'recharge_interval':30.}),
 'SCREAMER':('Zombie',{'base_sense_r':50.,'claw_damage':10,'call_radius':120.,'call_ttl':12.}),
}

def build():
    ROOT.mkdir(exist_ok=True)
    source=SOURCE.read_text(encoding='utf-8')
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=BASELINE_SHA256:
        raise RuntimeError('The source Markdown changed; review and update the formalization mapping before rebuilding.')
    core, cat, shapes=graph(),graph(),graph()
    core.add((Z.Ontology,RDF.type,OWL.Ontology))
    core.add((Z.Ontology,OWL.versionIRI,Z['ontology-0.1.0']))
    core.add((Z.Ontology,OWL.versionInfo,Literal('0.1.0')))
    for p in ['sourceSection','sourceText','coverage','requirementId']:
        core.add((Z[p],RDF.type,OWL.AnnotationProperty))
    core.add((Z.Ontology,Z.sourceText,Literal('Formalization of unchanged zombie_game_ontology_v0.1.md; data validation is a separate SHACL layer.')))
    classes='Agent AgentState HumanState ZombieState LivingState DeadState HealthyHumanState InfectedHumanState ActiveZombieState RoleDefinition HumanRoleDefinition ZombieRoleDefinition RoleAssignment Capability AgentType Status ActionStatus DecisionModel ModelAssignment ActionDefinition ActionIntent ActionOccurrence Event InfectionEpisode EpisodeOutcome Inventory ResourceStock ResourceType World ScenarioDefinition SimulationRun Observation Snapshot Effect TimedEffect EffectCategory Signal Intervention Measurement EnvironmentEntity EnvironmentState Gate GateState Obstacle ObstacleState Shelter Barricade BarricadeState Stockpile StockpileState Remains RemainsState Rectangle Point Cooldown GateMode ActionResult LifecycleTransition CureTransition ConversionTransition DeathTransition'.split()
    classes += [r.title()+'State' for r in ROLES]
    classes += ['InfectionCapableActionDefinition','HealingActionDefinition','CombatActionDefinition']
    classes += ['PopulationAllocation','BaselineScenarioDefinition']
    for name in classes:
        core.add((Z[name],RDF.type,OWL.Class)); core.add((Z[name],RDFS.label,Literal(name)))
    for child,parent in [('HumanState','AgentState'),('ZombieState','AgentState'),('LivingState','AgentState'),('DeadState','AgentState'),('HealthyHumanState','HumanState'),('InfectedHumanState','HumanState'),('ActiveZombieState','ZombieState'),('HumanRoleDefinition','RoleDefinition'),('ZombieRoleDefinition','RoleDefinition'),('TimedEffect','Effect')]:
        core.add((Z[child],RDFS.subClassOf,Z[parent]))
    for name in ['Gate','Obstacle','Shelter','Barricade','Stockpile','Remains']: core.add((Z[name],RDFS.subClassOf,Z.EnvironmentEntity))
    for name in ['GateState','ObstacleState','BarricadeState','StockpileState','RemainsState']: core.add((Z[name],RDFS.subClassOf,Z.EnvironmentState))
    for name in ['CureTransition','ConversionTransition','DeathTransition']: core.add((Z[name],RDFS.subClassOf,Z.LifecycleTransition))
    core.add((Z.BaselineScenarioDefinition,RDFS.subClassOf,Z.ScenarioDefinition))
    for a,b in [('HumanState','ZombieState'),('LivingState','DeadState'),('HumanRoleDefinition','ZombieRoleDefinition'),('Agent','AgentState'),('Agent','Remains'),('HealthyHumanState','InfectedHumanState')]: core.add((Z[a],OWL.disjointWith,Z[b]))
    object_names='inRun scenario world ofAgent hasState biologicalType status actionStatus activeRole roleDefinition compatibleType activeModel modelDefinition activeEpisode activeAction lastEvent deathCause hasTypeProfile hasRoleDefinition grants hasCapability capability mayCause inventory stock resourceType infectedAgent sourceAgent sourceEvent episodeOutcome ofEntity geometry comesFrom hasGate hasWall gateMode recipient effectCategory cooldownRecord forAction observes actor target actionDefinition realizes actorStart actorAfterStart actorBeforeEnd actorAfterEnd targetStart targetBeforeEnd targetAfterEnd actionResult beforeState afterState episode triggeredBy causesEffect cause hasEnvironmentState hasAgentState'.split()
    for p in object_names: core.add((Z[p],RDF.type,OWL.ObjectProperty))
    for p in ['atTime','revision','onset_revision','end_revision','length','width','agent_id','created_at']+[x[1] for x in FIELDS]: core.add((Z[p],RDF.type,OWL.DatatypeProperty))
    for p in ['label','model_id','model_version','source_kind','boundary_policy','coordinate_system','registry_version']:
        core.add((Z[p],RDF.type,OWL.DatatypeProperty))
    for p in ['initial_humans','initial_zombies','initial_infected','horizon','seed','allow_intraspecies_combat','count','target_kind']:
        core.add((Z[p],RDF.type,OWL.DatatypeProperty))
    core.add((Z.allocation,RDF.type,OWL.ObjectProperty))
    for p in ['biologicalType','status','actionStatus','activeRole','activeModel','activeEpisode','activeAction','ofAgent','inRun','world','roleDefinition']:
        core.add((Z[p],RDF.type,OWL.FunctionalProperty))
    for cls,n,dt,lo,hi,req in FIELDS:
        # Some numeric property names are shared by states and role profiles;
        # no broad domain axiom is imposed on them.
        core.add((Z[n],RDFS.range,dt))
    for p,c in [('ofAgent','Agent'),('activeRole','RoleAssignment'),('roleDefinition','RoleDefinition'),('activeModel','ModelAssignment'),('activeEpisode','InfectionEpisode'),('hasTypeProfile','AgentType'),('hasCapability','Capability'),('grants','Capability')]: core.add((Z[p],RDFS.range,Z[c]))
    for cls,property_name,range_cls in [('Agent','inRun','SimulationRun'),('AgentState','ofAgent','Agent'),('AgentState','world','World'),('RoleAssignment','roleDefinition','RoleDefinition'),('InfectionEpisode','infectedAgent','Agent')]:
        core.add((Z[cls],RDFS.subClassOf,restriction(core,Z[property_name],OWL.someValuesFrom,Z[range_cls])))
    for kind, names in {
        'AgentType':['Human','Zombie'], 'Status':['HEALTHY','INFECTED','ACTIVE','DEAD'],
        'ActionStatus':['IDLE','BUSY','ACTION_DEAD'],
        'EpisodeOutcome':['ONGOING','CURED','CONVERTED','HOST_DIED'],
        'ResourceType':['FOOD','MEDICAL_SUPPLY','MATERIAL','BIOMASS'],
        'GateMode':['OPEN','CLOSED','BREACHED'],
        'ActionResult':['SUCCEEDED','MISSED','FAILED_PRECONDITION','CANCELLED_BY_DEATH','CANCELLED_BY_CONVERSION','CANCELLED_BY_CONFLICT','CANCELLED_BY_INTERVENTION','PARTIAL_BLOCKED','IN_PROGRESS','REJECTED'],
    }.items():
        for n in names: core.add((Z[n],RDF.type,Z[kind]))
        different(core,[Z[n] for n in names])
    for cls,typ in [('HumanState','Human'),('ZombieState','Zombie')]:
        core.add((Z[cls],OWL.equivalentClass,intersection(core,[Z.AgentState,restriction(core,Z.biologicalType,OWL.hasValue,Z[typ])])))
    for cls,st in [('HealthyHumanState','HEALTHY'),('InfectedHumanState','INFECTED'),('ActiveZombieState','ACTIVE'),('DeadState','DEAD')]:
        core.add((Z[cls],OWL.equivalentClass,intersection(core,[Z.AgentState,restriction(core,Z.status,OWL.hasValue,Z[st])])))
    for cls in ['HealthyHumanState','InfectedHumanState','ActiveZombieState']: core.add((Z[cls],RDFS.subClassOf,Z.LivingState))
    core.add((Z.DeadState,RDFS.subClassOf,restriction(core,Z.life,OWL.hasValue,lit(0))))
    core.add((Z.DeadState,RDFS.subClassOf,restriction(core,Z.hasCapability,OWL.allValuesFrom,OWL.Nothing)))
    core.add((Z.DeadState,RDFS.subClassOf,restriction(core,Z.activeRole,OWL.maxCardinality,Literal(0,datatype=XSD.nonNegativeInteger))))
    core.add((Z.InfectedHumanState,RDFS.subClassOf,restriction(core,Z.activeEpisode,OWL.someValuesFrom,Z.InfectionEpisode)))
    core.add((Z.hasCapability,OWL.propertyChainAxiom,seq(core,[Z.hasTypeProfile,Z.grants])))
    core.add((Z.hasRoleDefinition,OWL.propertyChainAxiom,seq(core,[Z.activeRole,Z.roleDefinition])))
    core.add((Z.hasCapability,OWL.propertyChainAxiom,seq(core,[Z.hasRoleDefinition,Z.grants])))
    core.add((Z.activeRole,RDFS.domain,Z.LivingState))
    core.add((Z.hasTypeProfile,RDFS.domain,Z.LivingState))
    for role,(typ,props) in ROLES.items():
        cat.add((Z[role],RDF.type,Z[typ+'RoleDefinition'])); cat.add((Z[role],Z.compatibleType,Z[typ]))
        cat.add((Z[role],RDFS.label,Literal(role))); cat.add((Z[role],Z.registry_version,Literal('baseline_v0.1')))
        for p,v in props.items():
            core.add((Z[p],RDF.type,OWL.DatatypeProperty)); cat.add((Z[role],Z[p],lit(v)))
        cls=Z[role.title()+'State']
        core.add((cls,OWL.equivalentClass,intersection(core,[Z.LivingState,restriction(core,Z.hasRoleDefinition,OWL.hasValue,Z[role])])))
        core.add((cls,RDFS.subClassOf,Z[typ+'State']))
    different(core,[Z[r] for r in ROLES])
    action_text={}
    for line in source.split('## 10. Common actions')[1].split('## 14. Time')[0].splitlines():
        m=re.match(r'\| `([a-z_]+)` \|',line)
        if m: action_text[m.group(1)]=line
    assert set(action_text)=={a[0] for a in ACTIONS}
    for name,dmin,dmax,cost,cd,reach,provider,effects in ACTIONS:
        a,c=Z['action_'+name],Z['cap_'+name]
        cat.add((a,RDF.type,Z.ActionDefinition)); cat.add((c,RDF.type,Z.Capability))
        cat.add((a,RDFS.label,Literal(name))); cat.add((a,Z.capability,c))
        target_kind = ('Agent' if name in ['melee','transfer','first_aid','claw','bite','treat_infection','prophylaxis','power_strike','mark_target','spit'] else 'Environment' if name in ['pickup','open_gate','close_gate','feed','smash','repair_barrier','demolish'] else 'Path' if name in ['move','dash'] else 'Footprint' if name=='build_barricade' else 'SelfOrBroadcast')
        cat.add((a,Z.target_kind,Literal(target_kind)))
        cat.add((a,Z.sourceText,Literal(action_text[name])))
        cat.add((a,Z.coverage,Literal('PARTIAL: typed baseline parameters and shared checks; full behavioral coverage is listed in coverage.json.')))
        for p,v in [('duration_min',dmin),('duration_max',dmax),('stamina_cost',cost),('cooldown',cd)]: cat.add((a,Z[p],Literal(str(v),datatype=XSD.decimal)))
        if reach is not None: cat.add((a,Z.reach,Literal(str(reach),datatype=XSD.decimal)))
        for e in effects.split():
            core.add((Z[e+'Effect'],RDF.type,Z.EffectCategory)); cat.add((a,Z.mayCause,Z[e+'Effect']))
        for prov in (['Human','Zombie'] if provider=='ALL' else [provider]): cat.add((Z[prov],Z.grants,c))
    different(core,[Z['cap_'+a[0]] for a in ACTIONS])
    for cls,eff in [('InfectionCapableActionDefinition','InfectionOnset'),('HealingActionDefinition','LifeRestoration'),('CombatActionDefinition','PhysicalDamage')]:
        core.add((Z[cls],OWL.equivalentClass,intersection(core,[Z.ActionDefinition,restriction(core,Z.mayCause,OWL.hasValue,Z[eff+'Effect'])])))
    core.add((Z.CombatActionDefinition,RDFS.subClassOf,Z.ActionDefinition))
    build_shapes(core,shapes)
    save(core,'ontology.ttl'); save(cat,'catalog.ttl'); save(shapes,'shapes.ttl')
    # RDF/XML is an equivalent exchange form for the OWLAPI/HermiT tooling.
    combined=graph().parse(ROOT/'ontology.ttl')+graph().parse(ROOT/'catalog.ttl')
    combined.serialize(ROOT/'ontology.owl',format='xml')
    manifest={'source_file':'../zombie_game_ontology_v0.1.md','source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'ontology_namespace':str(Z),'ontology_version':'0.1.0','actions':[a[0] for a in ACTIONS],'roles':list(ROLES),'source_plan':'../../prompts/zombie_game_plans.md','source_plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'scope':'TASK 1: incremental OWL/SHACL formalization, requirement traceability, and reproducible validation.'}
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return core,cat,shapes

def build_shapes(core,g):
    shape_names=set()
    def shape(cls):
        s=Z[cls+'Shape']; g.add((s,RDF.type,SH.NodeShape)); g.add((s,SH.targetClass,Z[cls])); shape_names.add(cls); return s
    def prop(cls,name,dt=None,lo=None,hi=None,req=True,maxcount=1,klass=None,values=None):
        s=shape(cls); p=Z[cls+'_'+name+'Shape']; g.add((s,SH.property,p)); g.add((p,SH.path,Z[name]))
        if req: g.add((p,SH.minCount,lit(1)))
        if maxcount is not None: g.add((p,SH.maxCount,lit(maxcount)))
        if dt: g.add((p,SH.datatype,dt))
        if lo is not None: g.add((p,SH.minInclusive,lit(lo)))
        if hi is not None: g.add((p,SH.maxInclusive,lit(hi)))
        if klass: g.add((p,SH['class'],Z[klass])); g.add((p,SH.nodeKind,SH.IRI))
        if values: g.add((p,SH['in'],seq(g,[Z[v] for v in values])))
        g.add((p,SH.message,Literal(f'{cls}.{name}: required datatype, cardinality, range, or reference violated.')))
        return p
    def check(cls,id,message,where,tail=''):
        c=Z[id]; g.add((shape(cls),SH.sparql,c)); g.add((c,RDF.type,SH.SPARQLConstraint)); g.add((c,SH.message,Literal(id+': '+message)))
        g.add((c,SH.select,Literal(PREFIX+'SELECT $this WHERE {\n'+where+'\n} '+tail)))
    for cls,n,dt,lo,hi,req in FIELDS:
        p=prop(cls,n,dt,lo,hi,req)
        if n in ['base_speed','length','width','incubation_duration','duration_min','duration_max']: g.add((p,SH.minExclusive,lit(0)))
    for cls,n,klass,req,mc in [
      ('Agent','inRun','SimulationRun',True,1),('Agent','hasState','AgentState',True,None),
      ('SimulationRun','scenario','ScenarioDefinition',True,1),('SimulationRun','world','World',True,1),
      ('AgentState','ofAgent','Agent',True,1),('AgentState','world','World',True,1),
      ('AgentState','activeRole','RoleAssignment',False,1),('AgentState','activeModel','ModelAssignment',False,1),
      ('AgentState','activeEpisode','InfectionEpisode',False,1),('AgentState','activeAction','ActionOccurrence',False,1),
      ('AgentState','lastEvent','Event',True,1),('AgentState','cooldownRecord','Cooldown',False,None),
      ('AgentState','deathCause','Event',False,1),
      ('AgentState','hasTypeProfile','AgentType',False,1),('AgentState','effect','TimedEffect',False,None),
      ('HumanState','inventory','Inventory',True,1),('Inventory','stock','ResourceStock',False,None),
      ('RoleAssignment','ofAgent','Agent',True,1),('RoleAssignment','roleDefinition','RoleDefinition',True,1),
      ('ModelAssignment','ofAgent','Agent',True,1),('ModelAssignment','modelDefinition','DecisionModel',True,1),
      ('RoleDefinition','compatibleType','AgentType',True,1),('RoleDefinition','grants','Capability',True,None),
      ('InfectionEpisode','infectedAgent','Agent',True,1),('InfectionEpisode','sourceEvent','Event',True,1),
      ('InfectionEpisode','sourceAgent','Agent',False,1),('Cooldown','forAction','ActionDefinition',True,1),
      ('EnvironmentState','ofEntity','EnvironmentEntity',True,1),('EnvironmentState','world','World',True,1),
      ('EnvironmentState','geometry',None,True,1),('Gate','hasShelter','Shelter',True,1),
      ('Shelter','hasGate','Gate',True,None),('Shelter','hasWall','Obstacle',True,None),
      ('StockpileState','stock','ResourceStock',False,None),('Remains','comesFrom','Agent',True,1),
      ('TimedEffect','recipient','Agent',True,1),('TimedEffect','sourceEvent','Event',True,1),
      ('ActionDefinition','capability','Capability',True,1),('ActionDefinition','mayCause','EffectCategory',True,None),
      ('ActionIntent','actor','Agent',True,1),('ActionIntent','actionDefinition','ActionDefinition',True,1),('ActionIntent','observes','Observation',True,1),
      ('Observation','observer','Agent',True,1),('Observation','selfState','AgentState',True,1),
      ('ActionOccurrence','realizes','ActionIntent',True,1),('ActionOccurrence','actionDefinition','ActionDefinition',True,1),
      ('ActionOccurrence','actorStart','AgentState',True,1),('ActionOccurrence','actorAfterStart','AgentState',True,1),
      ('ActionOccurrence','actorBeforeEnd','AgentState',False,1),('ActionOccurrence','actorAfterEnd','AgentState',False,1),
      ('ActionOccurrence','targetStart','AgentState',False,1),('ActionOccurrence','targetBeforeEnd','AgentState',False,1),('ActionOccurrence','targetAfterEnd','AgentState',False,1),
      ('ActionOccurrence','targetEntity','EnvironmentState',False,1),('ActionOccurrence','footprint','Rectangle',False,1),
      ('PopulationAllocation','biologicalType','AgentType',True,1),('PopulationAllocation','roleDefinition','RoleDefinition',False,1),
      ('LifecycleTransition','beforeState','AgentState',True,1),('LifecycleTransition','afterState','AgentState',True,1),
      ('CureTransition','triggeredBy','ActionOccurrence',True,1),('CureTransition','episode','InfectionEpisode',True,1),('ConversionTransition','episode','InfectionEpisode',True,1),
    ]:
        if (Z[n],RDF.type,OWL.ObjectProperty) not in core: core.add((Z[n],RDF.type,OWL.ObjectProperty))
        prop(cls,n,klass=klass,req=req,maxcount=mc)
    for cls,n,values in [('AgentState','biologicalType',['Human','Zombie']),('AgentState','status',['HEALTHY','INFECTED','ACTIVE','DEAD']),('AgentState','actionStatus',['IDLE','BUSY','ACTION_DEAD']),('ResourceStock','resourceType',['FOOD','MEDICAL_SUPPLY','MATERIAL']),('GateState','gateMode',['OPEN','CLOSED','BREACHED']),('InfectionEpisode','episodeOutcome',['ONGOING','CURED','CONVERTED','HOST_DIED']),('ActionOccurrence','actionResult',['SUCCEEDED','MISSED','FAILED_PRECONDITION','CANCELLED_BY_DEATH','CANCELLED_BY_CONVERSION','CANCELLED_BY_CONFLICT','CANCELLED_BY_INTERVENTION','PARTIAL_BLOCKED','IN_PROGRESS'])]: prop(cls,n,values=values)
    for cls,n in [('DecisionModel','model_id'),('DecisionModel','model_version'),('InfectionEpisode','source_kind'),('ActionDefinition','target_kind')]: prop(cls,n,XSD.string)
    # Target human/zombie and role-specific shapes also from asserted profile/status,
    # without requiring the OWL reasoner to materialize classifications first.
    g.add((shape('HumanState'),SH.targetSubjectsOf,Z.hunger))
    g.add((shape('ZombieState'),SH.targetSubjectsOf,Z.virulence))
    check('Agent','UniqueAgentID','Agent ID is unique within a run.','$this zg:inRun ?r; zg:agent_id ?id. ?other a zg:Agent; zg:inRun ?r; zg:agent_id ?id. FILTER(?other != $this)')
    check('AgentState','StateTypeFields','Applicable type-specific fields and explicit state classification are required.','$this zg:biologicalType ?t. FILTER((?t=zg:Human && NOT EXISTS {$this a zg:HumanState; zg:hunger ?h; zg:inventory ?i}) || (?t=zg:Zombie && NOT EXISTS {$this a zg:ZombieState; zg:virulence ?v}) || (?t=zg:Zombie && EXISTS {$this zg:inventory ?i}) || (?t=zg:Zombie && EXISTS {$this zg:hunger ?h}))')
    check('AgentState','StateStatus','Type/status/life and active episode must agree.','$this zg:biologicalType ?t; zg:status ?s; zg:life ?l. FILTER((?l=0 && ?s!=zg:DEAD) || (?l>0 && ?s=zg:DEAD) || (?t=zg:Human && ?s=zg:ACTIVE) || (?t=zg:Zombie && ?s NOT IN (zg:ACTIVE,zg:DEAD)) || (?s=zg:INFECTED && NOT EXISTS {$this zg:activeEpisode ?e}) || (?s!=zg:INFECTED && EXISTS {$this zg:activeEpisode ?e}))')
    check('AgentState','StateIdentityRevision','One state per agent, time, and causal revision.','$this zg:ofAgent ?a; zg:atTime ?t; zg:revision ?r. ?other a zg:AgentState; zg:ofAgent ?a; zg:atTime ?t; zg:revision ?r. FILTER(?other!=$this)')
    check('AgentState','StateWorld','State world matches its agent run.','$this zg:ofAgent/zg:inRun/zg:world ?w; zg:world ?v. FILTER(?w!=?v)')
    check('AgentState','PositionBounds','Coordinates lie within the world.','$this zg:x ?x; zg:y ?y; zg:world ?w. ?w zg:length ?l; zg:width ?h. FILTER(?x<0 || ?y<0 || ?x>?l || ?y>?h)')
    check('AgentState','AliveAssignments','A living state has a model and its matching type capability profile.','$this zg:life ?l; zg:biologicalType ?t. FILTER(?l>0 && (NOT EXISTS {$this zg:activeModel ?m} || NOT EXISTS {$this zg:hasTypeProfile ?t}))')
    check('AgentState','DeadCleanup','Death clears active references, movement and sensing; death metadata is present.','$this zg:life 0. FILTER(EXISTS {$this zg:activeRole ?r} || EXISTS {$this zg:activeModel ?m} || EXISTS {$this zg:activeAction ?a} || EXISTS {$this zg:activeEpisode ?e} || EXISTS {$this zg:hasTypeProfile ?t} || EXISTS {$this zg:effect ?f} || EXISTS {$this zg:cooldownRecord ?c} || EXISTS {$this zg:speed ?s FILTER(?s!=0)} || EXISTS {$this zg:sense_r ?r FILTER(?r!=0)} || NOT EXISTS {$this zg:death_at ?d; zg:deathCause ?c})')
    check('AgentState','LivingDeathMetadata','Living agents have no death metadata.','$this zg:life ?l. FILTER(?l>0 && (EXISTS {$this zg:death_at ?d} || EXISTS {$this zg:deathCause ?c}))')
    check('AgentState','ActionState','BUSY iff a living state has an active action; dead action state is ACTION_DEAD.','$this zg:life ?l; zg:actionStatus ?s. FILTER((?l=0 && ?s!=zg:ACTION_DEAD) || (?l>0 && ?s=zg:ACTION_DEAD) || (?s=zg:BUSY && NOT EXISTS {$this zg:activeAction ?a}) || (?s!=zg:BUSY && EXISTS {$this zg:activeAction ?a}))')
    check('AgentState','RoleCompatibility','Active role belongs to this agent and supports this biological type.','$this zg:ofAgent ?a; zg:biologicalType ?t; zg:activeRole ?r. ?r zg:ofAgent ?b; zg:roleDefinition/zg:compatibleType ?rt. FILTER(?a!=?b || ?t!=?rt)')
    check('AgentState','RoleOverrides','Current common/type profile fields agree with the active role overrides.','$this zg:activeRole/zg:roleDefinition ?role. ?role ?p ?value. FILTER(?p IN (zg:base_speed,zg:base_sense_r,zg:base_damage_resistance,zg:medical_skill,zg:combat_skill,zg:melee_damage,zg:carry_capacity,zg:claw_damage,zg:attack_skill)) FILTER(NOT EXISTS {$this ?p ?value})')
    check('AgentState','RoleFieldApplicability','Spitter charges exist only for current Spitters and stay within their declared maximum.','OPTIONAL {$this zg:activeRole/zg:roleDefinition ?role} OPTIONAL {$this zg:spit_charges ?q} FILTER((?role=zg:SPITTER && !BOUND(?q)) || (BOUND(?q) && (!BOUND(?role) || ?role!=zg:SPITTER)) || (BOUND(?q) && EXISTS {zg:SPITTER zg:max_spit_charges ?max FILTER(?q>?max)}))')
    check('Observation','ObservationSelf','Observation observer, time, and revision match its self-state.','$this zg:observer ?a; zg:selfState ?s; zg:atTime ?t; zg:revision ?r. ?s zg:ofAgent ?b; zg:atTime ?u; zg:revision ?v. FILTER(?a!=?b || ?t!=?u || ?r!=?v)')
    check('AgentState','ModelOwnership','Active model assignment belongs to this agent.','$this zg:ofAgent ?a; zg:activeModel/zg:ofAgent ?b. FILTER(?a!=?b)')
    check('AgentState','EpisodeOwnership','Active episode belongs to this agent and is active at this causal revision.','$this zg:ofAgent ?a; zg:atTime ?t; zg:revision ?r; zg:activeEpisode ?e. ?e zg:infectedAgent ?b; zg:onset_at ?on; zg:onset_revision ?orr; zg:conversion_due_at ?due. OPTIONAL {?e zg:ended_at ?end; zg:end_revision ?er} FILTER(?a!=?b || ?t<?on || (?t=?on && ?r<?orr) || ?t>?due || (BOUND(?end) && (?t>?end || (?t=?end && ?r>=?er))))')
    check('AgentState','NoResurrection','No recorded later state of a dead identity is alive or changes its type/location.','$this zg:life 0; zg:ofAgent ?a; zg:atTime ?t; zg:revision ?r; zg:biologicalType ?ty; zg:x ?x; zg:y ?y. ?later a zg:AgentState; zg:ofAgent ?a; zg:atTime ?u; zg:revision ?v; zg:life ?l; zg:biologicalType ?lt; zg:x ?lx; zg:y ?ly. FILTER((?u>?t || (?u=?t && ?v>?r)) && (?l!=0 || ?ty!=?lt || ?x!=?lx || ?y!=?ly))')
    check('HumanState','InventoryCapacity','Total portable stock, including reservations, fits capacity.','$this zg:inventory/zg:stock/zg:quantity ?q; zg:carry_capacity ?c.', 'GROUP BY $this HAVING(SUM(?q)>MAX(?c))')
    check('HumanState','DeadInventory','A dead human has an empty inventory.','$this zg:life 0; zg:inventory/zg:stock/zg:quantity ?q. FILTER(?q!=0)')
    check('HumanState','InfectionProgress','Progress agrees with the referenced clock; it is zero without an episode.','$this zg:infection_progress ?p; zg:atTime ?t. OPTIONAL {$this zg:activeEpisode ?e. ?e zg:onset_at ?o; zg:incubation_duration ?d} FILTER((!BOUND(?e) && ?p!=0) || (BOUND(?e) && ABS(?p - ((?t-?o)/?d))>0.000000001))')
    check('HumanState','StarvationTimers','Living hunger-100 states require starvation timers; other states clear them.','$this zg:hunger ?h; zg:life ?l. FILTER((?h=100 && ?l>0 && NOT EXISTS {$this zg:starvation_started_at ?s; zg:next_starvation_damage_at ?n}) || ((?h<100 || ?l=0) && (EXISTS {$this zg:starvation_started_at ?s} || EXISTS {$this zg:next_starvation_damage_at ?n})))')
    check('Inventory','UniqueInventoryResource','One stock per portable resource type in each inventory.','$this zg:stock ?a,?b. ?a zg:resourceType ?t. ?b zg:resourceType ?t. FILTER(?a!=?b)')
    check('ResourceStock','ReservationBound','Reserved quantity cannot exceed total quantity.','$this zg:quantity ?q; zg:reserved ?r. FILTER(?r>?q)')
    holder=Z.ResourceStock_holderShape; g.add((shape('ResourceStock'),SH.property,holder)); path=BNode(); g.add((path,SH.inversePath,Z.stock)); g.add((holder,SH.path,path)); g.add((holder,SH.minCount,lit(1))); g.add((holder,SH.maxCount,lit(1)))
    holder_types=[]
    for cls in ['Inventory','StockpileState']:
        n=BNode(); g.add((n,SH['class'],Z[cls])); holder_types.append(n)
    g.add((holder,SH['or'],seq(g,holder_types))); g.add((holder,SH.message,Literal('A resource stock has exactly one inventory or stockpile-state holder.')))
    check('InfectionEpisode','EpisodeDeadline','Deadline equals onset plus positive incubation duration.','$this zg:onset_at ?o; zg:incubation_duration ?d; zg:conversion_due_at ?t. FILTER(?t != ?o+?d)')
    check('InfectionEpisode','EpisodeClosure','Closed outcomes have end time/revision; ongoing episodes have neither.','$this zg:episodeOutcome ?o. FILTER((?o=zg:ONGOING && (EXISTS {$this zg:ended_at ?e} || EXISTS {$this zg:end_revision ?r})) || (?o!=zg:ONGOING && NOT EXISTS {$this zg:ended_at ?e; zg:end_revision ?r}))')
    check('InfectionEpisode','EpisodeEndOrder','An episode cannot end before onset.','$this zg:onset_at ?o; zg:onset_revision ?r; zg:ended_at ?e; zg:end_revision ?v. FILTER(?e<?o || (?e=?o && ?v<?r))')
    for cls in ['RoleAssignment','ModelAssignment','TimedEffect']:
        check(cls,cls+'Interval','End cannot precede start.','$this zg:start_at ?s; zg:end_at ?e. FILTER(?e<?s)')
    check('Rectangle','RectangleOrder','Rectangle has strictly positive width and height.','$this zg:xmin ?a; zg:xmax ?b; zg:ymin ?c; zg:ymax ?d. FILTER(?a>=?b || ?c>=?d)')
    for cls in ['GateState','BarricadeState']:
        check(cls,cls+'Integrity','Integrity cannot exceed its maximum.','$this zg:integrity ?i; zg:max_integrity ?m. FILTER(?i>?m)')
    check('GateState','GateModeIntegrity','BREACHED iff gate integrity is zero.','$this zg:gateMode ?g; zg:integrity ?i. FILTER((?g=zg:BREACHED && ?i!=0) || (?g!=zg:BREACHED && ?i=0))')
    check('RemainsState','BiomassReservation','Biomass reservations cannot exceed biomass.','$this zg:biomass ?b; zg:reserved_biomass ?r. FILTER(?r>?b)')
    check('Event','NoCausalCycle','Event causal graph must be acyclic.','$this zg:cause+ $this.')
    check('ActionDefinition','DurationBounds','Maximum duration is not less than minimum duration.','$this zg:duration_min ?a; zg:duration_max ?b. FILTER(?a>?b)')
    for role,(typ,params) in ROLES.items():
        rs=Z[role+'ProfileShape']; g.add((rs,RDF.type,SH.NodeShape)); g.add((rs,SH.targetNode,Z[role]))
        for name,value in params.items():
            p=Z[role+'Profile_'+name+'Shape']; g.add((rs,SH.property,p)); g.add((p,SH.path,Z[name])); g.add((p,SH.minCount,lit(1))); g.add((p,SH.maxCount,lit(1)))
            g.add((p,SH.datatype,XSD.integer if isinstance(value,int) else XSD.decimal)); g.add((p,SH.minInclusive,lit(0)))
            if name.endswith(('duration','interval')) or name in ['base_speed'] or name.endswith('_cost') or name in ['build_integrity','max_spit_charges']: g.add((p,SH.minExclusive,lit(0)))
            if name in ['guard_resistance','base_damage_resistance']: g.add((p,SH.maxInclusive,lit(.8)))
            if name in ['combat_skill','medical_skill','attack_skill','prophylaxis_resistance','spit_potency','rally_hit_bonus']: g.add((p,SH.maxInclusive,lit(1)))
            if name=='dash_multiplier': g.set((p,SH.minInclusive,lit(1)))
    build_action_checks(core,g,prop,check)
    build_lifecycle_checks(core,g,prop,check)

def build_action_checks(core,g,prop,check):
    check('ActionOccurrence','IntentAgreement','The action realizes the same actor/action definition as its intent and cannot start before proposal.','$this zg:realizes ?i; zg:actorStart/zg:ofAgent ?a; zg:actionDefinition ?d; zg:startTime ?s. ?i zg:actor ?b; zg:actionDefinition ?e; zg:proposedAt ?p; zg:observes/zg:observer ?o. FILTER(?a!=?b || ?d!=?e || ?s<?p || ?a!=?o)')
    check('ActionOccurrence','RequiredTargets','Agent/environment/footprint actions carry the relevant target record.','$this zg:actionDefinition/zg:target_kind ?k. FILTER((?k="Agent" && NOT EXISTS {$this zg:targetStart ?s}) || (?k="Environment" && NOT EXISTS {$this zg:targetEntity ?e}) || (?k="Footprint" && NOT EXISTS {$this zg:footprint ?r}))')
    check('ActionOccurrence','ActionAdmission','Actor is alive and idle at admission, with enough flat stamina.','$this zg:actorStart ?s; zg:actionDefinition ?d. ?s zg:life ?l; zg:actionStatus ?as; zg:stamina ?st. ?d zg:stamina_cost ?cost. FILTER(?l<=0 || ?as!=zg:IDLE || ?st<?cost)')
    check('ActionOccurrence','ActionCapability','An explicit applicable type or role grants the required capability.','$this zg:actorStart ?s; zg:actionDefinition/zg:capability ?cap. FILTER(NOT EXISTS {?s zg:hasTypeProfile/zg:grants ?cap} && NOT EXISTS {?s zg:activeRole/zg:roleDefinition/zg:grants ?cap})')
    check('ActionOccurrence','ActionDuration','Planned duration is within the declared baseline bounds.','$this zg:startTime ?t; zg:plannedEnd ?e; zg:actionDefinition ?a. ?a zg:duration_min ?lo; zg:duration_max ?hi. FILTER(?e-?t<?lo || ?e-?t>?hi)')
    check('ActionOccurrence','AdmissionStamina','Flat stamina is paid exactly once at admission.','$this zg:actorStart ?b; zg:actorAfterStart ?a; zg:actionDefinition/zg:stamina_cost ?cost. ?b zg:stamina ?s. ?a zg:stamina ?v. FILTER(?v!=?s-?cost)')
    check('ActionOccurrence','ActorStartIdentity','Admission state records refer to the same actor/time, with increasing revision and the action becoming active.','$this zg:actorStart ?b; zg:actorAfterStart ?a; zg:startTime ?t. ?b zg:ofAgent ?x; zg:atTime ?bt; zg:revision ?br. ?a zg:ofAgent ?y; zg:atTime ?at; zg:revision ?ar. FILTER(?x!=?y || ?bt!=?t || ?at!=?t || ?ar<=?br || NOT EXISTS {?a zg:activeAction $this; zg:actionStatus zg:BUSY})')
    check('ActionOccurrence','AdmissionCooldown','The action is not admitted during its cooldown.','$this zg:startTime ?t; zg:actionDefinition ?d; zg:actorStart/zg:cooldownRecord ?c. ?c zg:forAction ?d; zg:until ?u. FILTER(?t<?u)')
    check('ActionOccurrence','ResultTiming','Ongoing occurrences lack final state/time; resolved attempts include them and do not end before admission.','$this zg:actionResult ?r; zg:startTime ?s; zg:plannedEnd ?p. OPTIONAL {$this zg:resolvedAt ?e} FILTER((?r=zg:IN_PROGRESS && (BOUND(?e) || EXISTS {$this zg:actorAfterEnd ?a})) || (?r!=zg:IN_PROGRESS && (!BOUND(?e) || NOT EXISTS {$this zg:actorBeforeEnd ?b; zg:actorAfterEnd ?a})) || (BOUND(?e) && ?e<?s) || (?r IN (zg:SUCCEEDED,zg:MISSED) && ?e!=?p))')
    check('ActionOccurrence','ActorEndIdentity','Resolution records refer to the same actor/time and increasing revision.','$this zg:actorStart/zg:ofAgent ?x; zg:actorBeforeEnd ?b; zg:actorAfterEnd ?a; zg:resolvedAt ?t. ?b zg:ofAgent ?y; zg:atTime ?bt; zg:revision ?br. ?a zg:ofAgent ?z; zg:atTime ?at; zg:revision ?ar. FILTER(?x!=?y || ?x!=?z || ?bt!=?t || ?at!=?t || ?ar<=?br)')
    check('ActionOccurrence','ActorResolutionAlive','Successful or missed actions require a living actor at resolution.','$this zg:actionResult ?r; zg:actorBeforeEnd/zg:life ?l. FILTER(?r IN (zg:SUCCEEDED,zg:MISSED) && ?l<=0)')
    check('ActionOccurrence','ActionRelease','A resolved action is not still active in its immediate actor post-state.','$this zg:actionResult ?r; zg:actorAfterEnd ?s. FILTER(?r!=zg:IN_PROGRESS) ?s zg:activeAction ?a.')
    check('ActionOccurrence','ActionCooldown','A completed attempt records its cooldown unless actor death/conversion retires it.','$this zg:actionResult ?r; zg:actionDefinition ?d; zg:resolvedAt ?t; zg:actorStart/zg:biologicalType ?old; zg:actorAfterEnd ?s. ?d zg:cooldown ?cd. ?s zg:life ?l; zg:biologicalType ?new. FILTER(?r!=zg:IN_PROGRESS && ?l>0 && ?old=?new && ?cd>0) FILTER(NOT EXISTS {?s zg:cooldownRecord [zg:forAction ?d; zg:until ?u] FILTER(?u=?t+?cd)})')
    check('ActionOccurrence','OneActionAtATime','Recorded action intervals for the same actor do not overlap.','$this zg:actorStart/zg:ofAgent ?actor; zg:startTime ?s; zg:plannedEnd ?p. OPTIONAL {$this zg:resolvedAt ?r} BIND(COALESCE(?r,?p) AS ?end) ?other a zg:ActionOccurrence; zg:actorStart/zg:ofAgent ?actor; zg:startTime ?os; zg:plannedEnd ?op. OPTIONAL {?other zg:resolvedAt ?orr} BIND(COALESCE(?orr,?op) AS ?oe) FILTER(?other!=$this && ?s<?oe && ?os<?end)')
    check('ActionOccurrence','ReciprocalAttackExclusion','Overlapping reciprocal attacks cannot both be valid resolved attempts, including misses.','$this zg:actionDefinition/zg:mayCause zg:PhysicalDamageEffect; zg:actionResult ?r; zg:actorStart/zg:ofAgent ?actor; zg:targetStart/zg:ofAgent ?target; zg:startTime ?s; zg:resolvedAt ?end. ?other a zg:ActionOccurrence; zg:actionDefinition/zg:mayCause zg:PhysicalDamageEffect; zg:actionResult ?orr; zg:actorStart/zg:ofAgent ?target; zg:targetStart/zg:ofAgent ?actor; zg:startTime ?os; zg:resolvedAt ?oe. FILTER(?other!=$this && ?r IN (zg:SUCCEEDED,zg:MISSED) && ?orr IN (zg:SUCCEEDED,zg:MISSED) && ?s<?oe && ?os<?end)')
    check('ActionOccurrence','MissOnlyAttack','Only stochastic agent attacks can MISS.','$this zg:actionResult zg:MISSED; zg:actionDefinition ?d. FILTER(?d NOT IN (zg:action_melee,zg:action_claw,zg:action_bite,zg:action_power_strike,zg:action_spit))')
    # Agent contact reach (barriers/resources need their own geometry evidence).
    check('ActionOccurrence','AgentStartReach','Agent-target interaction must be within declared reach at admission.','$this zg:actorStart ?a; zg:targetStart ?b; zg:actionDefinition/zg:reach ?r. ?a zg:x ?x; zg:y ?y. ?b zg:x ?u; zg:y ?v. FILTER((?x-?u)*(?x-?u)+(?y-?v)*(?y-?v)>?r*?r)')
    check('ActionOccurrence','AgentEndReach','Successful/missed agent interactions must remain within reach.','$this zg:actionResult ?result; zg:actorBeforeEnd ?a; zg:targetBeforeEnd ?b; zg:actionDefinition/zg:reach ?r. FILTER(?result IN (zg:SUCCEEDED,zg:MISSED)) ?a zg:x ?x; zg:y ?y. ?b zg:x ?u; zg:y ?v. FILTER((?x-?u)*(?x-?u)+(?y-?v)*(?y-?v)>?r*?r)')
    for p in ['actorMedicalBefore','actorMedicalAfter','actorMedicalReservedBefore','actorMedicalReservedAfter']:
        core.add((Z[p],RDF.type,OWL.DatatypeProperty))
    # Treatment has fully checkable numeric/resource/lifecycle consequences in this
    # profile. Visibility evidence and global causal completeness remain explicit gaps.
    check('ActionOccurrence','TreatmentTargetRecords','Treatment requires start target; successful treatment also requires resolution target records.','$this zg:actionDefinition zg:action_treat_infection; zg:actionResult ?r. FILTER(NOT EXISTS {$this zg:targetStart ?s} || (?r=zg:SUCCEEDED && NOT EXISTS {$this zg:targetBeforeEnd ?b; zg:targetAfterEnd ?a}))')
    check('ActionOccurrence','TreatmentStartTarget','Treatment starts on a living infected human.','$this zg:actionDefinition zg:action_treat_infection; zg:targetStart ?s. ?s zg:status ?st; zg:biologicalType ?ty; zg:life ?l. FILTER(?st!=zg:INFECTED || ?ty!=zg:Human || ?l<=0)')
    check('ActionOccurrence','TreatmentDeadline','Successful treatment completes strictly before the episode deadline.','$this zg:actionDefinition zg:action_treat_infection; zg:actionResult zg:SUCCEEDED; zg:resolvedAt ?t; zg:targetBeforeEnd/zg:activeEpisode/zg:conversion_due_at ?due. FILTER(?t>=?due)')
    check('ActionOccurrence','TreatmentEffect','Successful treatment ends infection without changing target life or position.','$this zg:actionDefinition zg:action_treat_infection; zg:actionResult zg:SUCCEEDED; zg:targetBeforeEnd ?b; zg:targetAfterEnd ?a. ?b zg:ofAgent ?i; zg:life ?l; zg:x ?x; zg:y ?y; zg:status ?old. ?a zg:ofAgent ?j; zg:life ?v; zg:x ?u; zg:y ?w; zg:status ?new; zg:biologicalType ?ty. FILTER(?i!=?j || ?old!=zg:INFECTED || ?new!=zg:HEALTHY || ?ty!=zg:Human || ?l!=?v || ?x!=?u || ?y!=?w || EXISTS {?a zg:activeEpisode ?e})')
    check('ActionOccurrence','TreatmentSupplyEvidence','Treatment resource states must record medical stock at admission and resolution.','$this zg:actionDefinition zg:action_treat_infection; zg:actionResult ?r; zg:actorStart ?s; zg:actorAfterStart ?a. FILTER(NOT EXISTS {?s zg:inventory/zg:stock [zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?q; zg:reserved ?v]} || NOT EXISTS {?a zg:inventory/zg:stock [zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?q; zg:reserved ?v]} || (?r!=zg:IN_PROGRESS && (NOT EXISTS {$this zg:actorBeforeEnd/zg:inventory/zg:stock [zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?q; zg:reserved ?v]} || NOT EXISTS {$this zg:actorAfterEnd/zg:inventory/zg:stock [zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?q; zg:reserved ?v]})))')
    check('ActionOccurrence','TreatmentReserve','Admission reserves one available medical item without consuming it.','$this zg:actionDefinition zg:action_treat_infection; zg:actorStart/zg:inventory/zg:stock ?b; zg:actorAfterStart/zg:inventory/zg:stock ?a. ?b zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?q; zg:reserved ?r. ?a zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?v; zg:reserved ?s. FILTER(?q-?r<1 || ?v!=?q || ?s!=?r+1)')
    check('ActionOccurrence','TreatmentConsume','Successful treatment consumes one reserved medical item.','$this zg:actionDefinition zg:action_treat_infection; zg:actionResult zg:SUCCEEDED; zg:actorBeforeEnd/zg:inventory/zg:stock ?b; zg:actorAfterEnd/zg:inventory/zg:stock ?a. ?b zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?q; zg:reserved ?r. ?a zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?v; zg:reserved ?s. FILTER(?r<1 || ?v!=?q-1 || ?s!=?r-1)')
    check('ActionOccurrence','TreatmentCureRecord','Successful treatment includes its linked cure transition and closed episode.','$this zg:actionDefinition zg:action_treat_infection; zg:actionResult zg:SUCCEEDED. FILTER(NOT EXISTS {?c a zg:CureTransition; zg:triggeredBy $this})')
    check('ActionOccurrence','TreatmentFailureRelease','A target-precondition failure releases the medical reservation without consuming the item.','$this zg:actionDefinition zg:action_treat_infection; zg:actionResult zg:FAILED_PRECONDITION; zg:actorBeforeEnd/zg:inventory/zg:stock ?b; zg:actorAfterEnd/zg:inventory/zg:stock ?a. ?b zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?q; zg:reserved ?r. ?a zg:resourceType zg:MEDICAL_SUPPLY; zg:quantity ?v; zg:reserved ?s. FILTER(?r<1 || ?v!=?q || ?s!=?r-1)')

def build_lifecycle_checks(core,g,prop,check):
    check('LifecycleTransition','TransitionIdentity','Atomic lifecycle transitions preserve identity and time, and increase causal revision.','$this zg:beforeState ?b; zg:afterState ?a. ?b zg:ofAgent ?i; zg:atTime ?t; zg:revision ?r. ?a zg:ofAgent ?j; zg:atTime ?u; zg:revision ?s. FILTER(?i!=?j || ?t!=?u || ?s<=?r)')
    check('ConversionTransition','ConversionTypes','Conversion changes living infected Human to active, role-free Zombie.','$this zg:beforeState ?b; zg:afterState ?a. ?b zg:biologicalType ?bt; zg:status ?bs; zg:life ?bl. ?a zg:biologicalType ?at; zg:status ?as. FILTER(?bt!=zg:Human || ?bs!=zg:INFECTED || ?bl<=0 || ?at!=zg:Zombie || ?as!=zg:ACTIVE || EXISTS {?a zg:activeRole ?r} || EXISTS {?a zg:inventory ?i})')
    check('ConversionTransition','ConversionPreserves','Conversion preserves current life, stamina and position.','$this zg:beforeState ?b; zg:afterState ?a. ?b zg:life ?l; zg:stamina ?s; zg:x ?x; zg:y ?y. ?a zg:life ?m; zg:stamina ?t; zg:x ?u; zg:y ?v. FILTER(?l!=?m || ?s!=?t || ?x!=?u || ?y!=?v)')
    check('ConversionTransition','ConversionDeadline','Conversion occurs exactly at its episode deadline and closes that episode as CONVERTED.','$this zg:episode ?e; zg:beforeState ?b; zg:afterState ?a. ?b zg:activeEpisode ?be. ?a zg:atTime ?t; zg:revision ?r. ?e zg:conversion_due_at ?due; zg:episodeOutcome ?out; zg:ended_at ?end; zg:end_revision ?er. FILTER(?be!=?e || ?t!=?due || ?out!=zg:CONVERTED || ?end!=?t || ?er!=?r)')
    check('CureTransition','CureStates','Cure changes INFECTED to HEALTHY while preserving type and life.','$this zg:beforeState ?b; zg:afterState ?a. ?b zg:status ?bs; zg:biologicalType ?bt; zg:life ?l. ?a zg:status ?as; zg:biologicalType ?at; zg:life ?v. FILTER(?bs!=zg:INFECTED || ?as!=zg:HEALTHY || ?bt!=zg:Human || ?at!=zg:Human || ?l<=0 || ?v!=?l)')
    check('CureTransition','CureEpisode','Cure closes the exact active episode before its deadline.','$this zg:episode ?e; zg:beforeState ?b; zg:afterState ?a; zg:triggeredBy ?act. ?b zg:activeEpisode ?old. ?a zg:atTime ?t; zg:revision ?r. ?e zg:conversion_due_at ?due; zg:episodeOutcome ?out; zg:ended_at ?end; zg:end_revision ?er. FILTER(?old!=?e || ?t>=?due || ?out!=zg:CURED || ?end!=?t || ?er!=?r || NOT EXISTS {?act zg:actionDefinition zg:action_treat_infection; zg:actionResult zg:SUCCEEDED; zg:targetBeforeEnd ?b; zg:targetAfterEnd ?a})')
    check('DeathTransition','DeathTypes','Death changes positive life to zero and preserves type and location.','$this zg:beforeState ?b; zg:afterState ?a. ?b zg:life ?l; zg:biologicalType ?ty; zg:x ?x; zg:y ?y. ?a zg:life ?v; zg:status ?s; zg:biologicalType ?at; zg:x ?u; zg:y ?w. FILTER(?l<=0 || ?v!=0 || ?s!=zg:DEAD || ?ty!=?at || ?x!=?u || ?y!=?w)')

if __name__=='__main__':
    c,a,s=build()
    print(f'Generated OWL {len(c)} triples, catalog {len(a)} triples, SHACL {len(s)} triples.')
