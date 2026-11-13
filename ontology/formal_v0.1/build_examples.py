"""Independent fixed fixtures and counterexamples with explicit expectations."""
from pathlib import Path
import copy
import json
from rdflib import Graph, Namespace, Literal
from rdflib.namespace import RDF, OWL, XSD
from build_spec import Z, ROOT, graph, lit, seq, restriction, intersection

E=Namespace('urn:zombie-game:example:')

def add(g,s,p,v): g.add((s,Z[p],v if hasattr(v,'n3') else lit(v)))
def setv(g,s,p,v): g.remove((s,Z[p],None)); add(g,s,p,v)
def typ(g,s,c): g.add((s,RDF.type,Z[c])); return s
def base():
    g=graph(); g.bind('ex',E)
    typ(g,E.run,'SimulationRun'); typ(g,E.scenario,'ScenarioDefinition'); typ(g,E.world,'World')
    add(g,E.run,'scenario',E.scenario); add(g,E.run,'world',E.world)
    add(g,E.world,'length',1000.); add(g,E.world,'width',1000.)
    typ(g,E.model,'DecisionModel'); add(g,E.model,'model_id','fixture-model'); add(g,E.model,'model_version','1')
    typ(g,E.init,'Event'); add(g,E.init,'atTime',0.); add(g,E.init,'revision',0)
    return g

def agent(g,name,id):
    a=typ(g,E[name],'Agent'); add(g,a,'agent_id',id); add(g,a,'created_at',0.); add(g,a,'inRun',E.run); return a

def inventory(g,s,med=0,reserved=0,food=0,material=0):
    i=typ(g,E[str(s).split(':')[-1]+'_inventory'],'Inventory'); add(g,s,'inventory',i)
    for name,q,r in [('MEDICAL_SUPPLY',med,reserved),('FOOD',food,0),('MATERIAL',material,0)]:
        st=typ(g,E[str(s).split(':')[-1]+'_'+name],'ResourceStock'); add(g,i,'stock',st)
        add(g,st,'resourceType',Z[name]); add(g,st,'quantity',q); add(g,st,'reserved',r)
    return i

def state(g,name,a,time=0.,rev=0,kind='Human',status='HEALTHY',life=100,stamina=100.,role=None,episode=None,med=0,reserved=0,busy=None,x=10.,y=10.):
    s=typ(g,E[name],'AgentState'); typ(g,s,kind+'State'); add(g,a,'hasState',s)
    for p,v in {'ofAgent':a,'world':E.world,'atTime':float(time),'revision':rev,'biologicalType':Z[kind],'status':Z[status], 'life':life,'max_life':100,'x':x,'y':y,'base_speed':2. if kind=='Human' else 1.6,'speed':(2. if kind=='Human' else 1.6) if life else 0.,'base_sense_r':40. if kind=='Human' else 35.,'sense_r':(40. if kind=='Human' else 35.) if life else 0.,'stamina':stamina,'max_stamina':100.,'movement_cost':.10 if kind=='Human' else .08,'rest_rate':4. if kind=='Human' else 3.,'base_damage_resistance':0.,'damage_resistance':0.,'actionStatus':Z.ACTION_DEAD if not life else Z.BUSY if busy else Z.IDLE,'lastEvent':E.init}.items(): add(g,s,p,v)
    if life:
        add(g,s,'hasTypeProfile',Z[kind]); m=typ(g,E[str(a).split(':')[-1]+'_'+kind+'_model'],'ModelAssignment'); add(g,m,'ofAgent',a); add(g,m,'modelDefinition',E.model); add(g,m,'start_at',0.); add(g,s,'activeModel',m)
    else: add(g,s,'death_at',float(time)); add(g,s,'deathCause',E.init)
    if role:
        r=typ(g,E[str(a).split(':')[-1]+'_'+role+'_role'],'RoleAssignment'); add(g,r,'ofAgent',a); add(g,r,'roleDefinition',Z[role]); add(g,r,'start_at',0.); add(g,s,'activeRole',r)
    if busy: add(g,s,'activeAction',busy)
    if kind=='Human':
        for p,v in {'hunger':20.,'hunger_rate':.05,'combat_skill':.35,'melee_damage':16,'medical_skill':.9 if role=='DOCTOR' else .2,'infection_resistance':.2,'infection_resistance_effective':.2,'infection_progress':0.,'carry_capacity':10}.items(): add(g,s,p,v)
        inventory(g,s,med,reserved)
    else:
        for p,v in {'attack_skill':.4,'virulence':.45,'claw_damage':14,'bite_damage':6,'feed_healing':8,'feed_energy':12.}.items(): add(g,s,p,v)
    if episode:
        add(g,s,'activeEpisode',episode)
        onset=float(g.value(episode,Z.onset_at)); dur=float(g.value(episode,Z.incubation_duration))
        setv(g,s,'infection_progress',(float(time)-onset)/dur)
    return s

def episode(g,name,a,onset=0.,duration=300.,outcome='ONGOING',end=None,end_rev=None):
    e=typ(g,E[name],'InfectionEpisode')
    for p,v in {'infectedAgent':a,'onset_at':onset,'onset_revision':0,'incubation_duration':duration,'conversion_due_at':onset+duration,'episodeOutcome':Z[outcome],'source_kind':'INITIAL_CONDITION','sourceEvent':E.init}.items(): add(g,e,p,v)
    if end is not None: add(g,e,'ended_at',end); add(g,e,'end_revision',end_rev)
    return e

def treatment():
    g=base(); d=agent(g,'doctor',1); h=agent(g,'patient',2); a=typ(g,E.treatment,'ActionOccurrence'); intent=typ(g,E.intent,'ActionIntent')
    ep=episode(g,'episode',h,onset=0.,duration=300.,outcome='CURED',end=104.,end_rev=1)
    s0=state(g,'doctor_start',d,100.,0,role='DOCTOR',stamina=80.,med=2)
    s1=state(g,'doctor_admitted',d,100.,1,role='DOCTOR',stamina=74.,med=2,reserved=1,busy=a)
    s2=state(g,'doctor_pre_end',d,104.,0,role='DOCTOR',stamina=74.,med=2,reserved=1,busy=a)
    s3=state(g,'doctor_post_end',d,104.,1,role='DOCTOR',stamina=74.,med=1)
    cooldown=typ(g,E.treatment_cooldown,'Cooldown'); add(g,cooldown,'forAction',Z.action_treat_infection); add(g,cooldown,'until',106.); add(g,s3,'cooldownRecord',cooldown)
    t0=state(g,'patient_start',h,100.,0,status='INFECTED',episode=ep,life=60,x=11.)
    t1=state(g,'patient_pre_end',h,104.,0,status='INFECTED',episode=ep,life=60,x=11.)
    t2=state(g,'patient_post_end',h,104.,1,life=60,x=11.)
    obs=typ(g,E.observation,'Observation')
    for p,v in {'observer':d,'selfState':s0,'atTime':100.,'revision':0}.items():add(g,obs,p,v)
    for p,v in {'actor':d,'actionDefinition':Z.action_treat_infection,'proposedAt':100.,'observes':obs}.items():add(g,intent,p,v)
    for p,v in {'realizes':intent,'actionDefinition':Z.action_treat_infection,'actorStart':s0,'actorAfterStart':s1,'actorBeforeEnd':s2,'actorAfterEnd':s3,'targetStart':t0,'targetBeforeEnd':t1,'targetAfterEnd':t2,'startTime':100.,'plannedEnd':104.,'resolvedAt':104.,'actionResult':Z.SUCCEEDED}.items(): add(g,a,p,v)
    c=typ(g,E.cure,'CureTransition'); typ(g,c,'LifecycleTransition')
    for p,v in {'beforeState':t1,'afterState':t2,'episode':ep,'triggeredBy':a}.items(): add(g,c,p,v)
    return g

def conversion():
    g=base(); h=agent(g,'person',17); ep=episode(g,'episode',h,outcome='CONVERTED',end=300.,end_rev=1)
    b=state(g,'human_before',h,300.,0,status='INFECTED',episode=ep,life=64,stamina=32.,role='DOCTOR')
    a=state(g,'zombie_after',h,300.,1,kind='Zombie',status='ACTIVE',life=64,stamina=32.)
    tr=typ(g,E.conversion,'ConversionTransition'); typ(g,tr,'LifecycleTransition')
    for p,v in {'beforeState':b,'afterState':a,'episode':ep}.items(): add(g,tr,p,v)
    return g

def death():
    g=base(); h=agent(g,'person',17); b=state(g,'before',h,10.,0,life=5); a=state(g,'after',h,10.,1,status='DEAD',life=0)
    tr=typ(g,E.death,'DeathTransition'); typ(g,tr,'LifecycleTransition'); add(g,tr,'beforeState',b); add(g,tr,'afterState',a)
    return g

def simple():
    g=base(); a=agent(g,'person',1); state(g,'state',a); return g

def mutate(fn,changes):
    g=fn(); changes(g); return g

def build():
    out=ROOT/'examples'; out.mkdir(exist_ok=True); manifest=[]
    def case(name,g,valid=True,expected=None):
        filename=name+'.ttl'; g.serialize(out/filename,format='turtle')
        manifest.append({'name':name,'file':'examples/'+filename,'expected_conforms':valid,'expected_constraint':expected})
    case('valid_state',simple())
    case('valid_treatment',treatment())
    case('valid_conversion_preserves_identity',conversion())
    case('valid_death',death())
    case('missing_life',mutate(simple,lambda g:g.remove((E.state,Z.life,None))),False,'AgentState_lifeShape')
    case('life_above_100',mutate(simple,lambda g:setv(g,E.state,'life',101)),False,'AgentState_lifeShape')
    case('position_outside_world',mutate(simple,lambda g:setv(g,E.state,'x',1001.)),False,'PositionBounds')
    case('dead_with_positive_life',mutate(simple,lambda g:setv(g,E.state,'status',Z.DEAD)),False,'StateStatus')
    case('human_with_tyrant_role',mutate(simple,lambda g:(typ(g,E.badrole,'RoleAssignment'),add(g,E.badrole,'roleDefinition',Z.TYRANT),add(g,E.badrole,'ofAgent',E.person),add(g,E.badrole,'start_at',0.),add(g,E.state,'activeRole',E.badrole))),False,'RoleCompatibility')
    case('infected_without_episode',mutate(simple,lambda g:setv(g,E.state,'status',Z.INFECTED)),False,'StateStatus')
    case('reservation_exceeds_stock',mutate(simple,lambda g:setv(g,E.state_MEDICAL_SUPPLY,'reserved',1)),False,'ReservationBound')
    case('inventory_over_capacity',mutate(simple,lambda g:setv(g,E.state_FOOD,'quantity',11)),False,'InventoryCapacity')
    case('duplicate_agent_id',mutate(simple,lambda g:(agent(g,'duplicate',1),state(g,'duplicate_state',E.duplicate))),False,'UniqueAgentID')
    case('resurrection',mutate(death,lambda g:state(g,'resurrected',E.person,11.,0)),False,'NoResurrection')
    case('conversion_heals',mutate(conversion,lambda g:setv(g,E.zombie_after,'life',100)),False,'ConversionPreserves')
    case('conversion_retains_role',mutate(conversion,lambda g:add(g,E.zombie_after,'activeRole',E.person_DOCTOR_role)),False,'ConversionTypes')
    case('conversion_wrong_deadline',mutate(conversion,lambda g:setv(g,E.episode,'conversion_due_at',301.)),False,'ConversionDeadline')
    case('treatment_at_deadline',mutate(treatment,lambda g:(setv(g,E.episode,'incubation_duration',104.),setv(g,E.episode,'conversion_due_at',104.),setv(g,E.patient_start,'infection_progress',100./104.),setv(g,E.patient_pre_end,'infection_progress',1.))),False,'TreatmentDeadline')
    case('treatment_free_supply',mutate(treatment,lambda g:setv(g,E.doctor_post_end_MEDICAL_SUPPLY,'quantity',2)),False,'TreatmentConsume')
    case('treatment_reservation_missing',mutate(treatment,lambda g:setv(g,E.doctor_admitted_MEDICAL_SUPPLY,'reserved',0)),False,'TreatmentReserve')
    case('treatment_no_stamina_cost',mutate(treatment,lambda g:setv(g,E.doctor_admitted,'stamina',80.)),False,'AdmissionStamina')
    case('treatment_out_of_reach',mutate(treatment,lambda g:setv(g,E.patient_start,'x',12.)),False,'AgentStartReach')
    case('treatment_heals_life',mutate(treatment,lambda g:setv(g,E.patient_post_end,'life',100)),False,'TreatmentEffect')
    case('treatment_missing_cure_record',mutate(treatment,lambda g:g.remove((E.cure,RDF.type,Z.CureTransition))),False,'TreatmentCureRecord')
    case('treatment_dead_actor',mutate(treatment,lambda g:setv(g,E.doctor_start,'life',0)),False,'ActionAdmission')
    case('treatment_invalid_duration',mutate(treatment,lambda g:setv(g,E.treatment,'plannedEnd',105.)),False,'ActionDuration')
    case('treatment_miss_invalid',mutate(treatment,lambda g:setv(g,E.treatment,'actionResult',Z.MISSED)),False,'MissOnlyAttack')
    case('causal_cycle',mutate(simple,lambda g:add(g,E.init,'cause',E.init)),False,'NoCausalCycle')
    case('treatment_missing_target',mutate(treatment,lambda g:g.remove((E.treatment,Z.targetStart,None))),False,'RequiredTargets')
    case('treatment_wrong_intent_actor',mutate(treatment,lambda g:setv(g,E.intent,'actor',E.patient)),False,'IntentAgreement')
    case('doctor_wrong_skill',mutate(treatment,lambda g:setv(g,E.doctor_start,'medical_skill',.2)),False,'RoleOverrides')
    case('treatment_missing_cooldown',mutate(treatment,lambda g:g.remove((E.doctor_post_end,Z.cooldownRecord,None))),False,'ActionCooldown')
    case('orphan_resource',mutate(simple,lambda g:(typ(g,E.orphan,'ResourceStock'),add(g,E.orphan,'resourceType',Z.FOOD),add(g,E.orphan,'quantity',1),add(g,E.orphan,'reserved',0))),False,'ResourceStock_holderShape')
    g=base(); ent=typ(g,E.gate,'Gate'); shelter=typ(g,E.shelter,'Shelter'); wall=typ(g,E.wall,'Obstacle')
    add(g,ent,'hasShelter',shelter); add(g,shelter,'hasGate',ent); add(g,shelter,'hasWall',wall)
    geom=typ(g,E.rect,'Rectangle')
    for p,v in {'xmin':10.,'xmax':16.,'ymin':10.,'ymax':12.}.items(): add(g,geom,p,v)
    gate=typ(g,E.gate_state,'GateState'); typ(g,gate,'EnvironmentState')
    for p,v in {'ofEntity':ent,'world':E.world,'geometry':geom,'atTime':0.,'revision':0,'integrity':200,'max_integrity':200,'gateMode':Z.CLOSED}.items(): add(g,gate,p,v)
    case('valid_gate',g)
    bad=copy.deepcopy(g); setv(bad,gate,'gateMode',Z.BREACHED); case('breached_gate_with_integrity',bad,False,'GateModeIntegrity')
    (ROOT/'examples.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    # OWL cases are separate: inference inputs intentionally omit inferred types.
    og=graph(); a=E.owl_state; r=E.owl_role_assignment
    typ(og,a,'AgentState'); add(og,a,'status',Z.INFECTED); add(og,a,'biologicalType',Z.Human); add(og,a,'activeRole',r); add(og,r,'roleDefinition',Z.DOCTOR); add(og,a,'hasTypeProfile',Z.Human)
    og.serialize(out/'owl_inference.ttl',format='turtle')
    bad=graph(); typ(bad,E.contradiction,'HumanState'); typ(bad,E.contradiction,'ZombieState'); bad.serialize(out/'owl_inconsistent_state.ttl',format='turtle')
    bad=graph(); bad.add((E.ImpossibleDoctorZombie,RDF.type,OWL.Class)); from rdflib.namespace import RDFS
    bad.add((E.ImpossibleDoctorZombie,RDFS.subClassOf,Z.DoctorState)); bad.add((E.ImpossibleDoctorZombie,RDFS.subClassOf,Z.ZombieState)); bad.serialize(out/'owl_unsatisfiable_extension.ttl',format='turtle')
    print(f'Generated {len(manifest)} SHACL cases and three OWL cases.')

if __name__=='__main__': build()
