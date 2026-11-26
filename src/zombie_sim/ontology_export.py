"""Export realized state and transitions to the unchanged v0.1 RDF vocabulary.

No specification example is used as simulator output. This serializer needs no
RDF dependency; optional independent SHACL validation uses rdflib and pyshacl.
"""
from __future__ import annotations
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path
from urllib.parse import quote
from .domain import RESOURCES, TYPE_PROFILES, action_status, profile, status
from .geometry import rect
from .registry import NS, ONTOLOGY_DIR

INTEGER_FIELDS={"life","max_life","revision","agent_id","carry_capacity","melee_damage","claw_damage","bite_damage","feed_healing","spit_charges","integrity","max_integrity","biomass","reserved_biomass","onset_revision","end_revision","quantity","reserved"}
COMMON_FIELDS=("base_speed","base_sense_r","movement_cost","rest_rate","base_damage_resistance","max_life","max_stamina","speed","sense_r","damage_resistance")
HUMAN_FIELDS=("hunger_rate","combat_skill","melee_damage","medical_skill","infection_resistance","infection_resistance_effective","carry_capacity")
ZOMBIE_FIELDS=("attack_skill","virulence","claw_damage","bite_damage","feed_healing","feed_energy")


def _decimal(value):
    fraction=Fraction(str(value))
    with localcontext() as ctx:
        ctx.prec=60
        number=Decimal(fraction.numerator)/Decimal(fraction.denominator)
    if not number.is_finite():
        raise ValueError("RDF numeric values must be finite")
    lexical=format(number,"f")
    # The original RoleOverrides query matches literal RDF terms, including
    # lexical form. Turtle decimal constants such as 55.0 remain decimals even
    # when their numeric value is integral.
    return lexical if "." in lexical else lexical+".0"


class _Writer:
    def __init__(self,run_id):
        self.base="urn:zombie-sim:run:"+quote(str(run_id),safe="")+":"
        self.lines=set()
        self.events={}
        self.latest_episodes={}
        self.event_aliases={}
        self.state_nodes={}
        self.context={}
        self.occurrences={}
        self.agent_ids={}
    def uri(self,*parts):
        return "<"+self.base+":".join(quote(str(p),safe="") for p in parts)+">"
    def triple(self,s,p,o):
        self.lines.add(f"{s} {'a' if p=='a' else 'zg:'+p} {o} .")
    def literal(self,s,p,value,datatype=None):
        if value is None:
            return
        if datatype is None:
            datatype="integer" if p in INTEGER_FIELDS else "decimal" if isinstance(value,(int,float,Decimal)) else "string"
        lexical=str(int(value)) if datatype=="integer" else _decimal(value) if datatype=="decimal" else str(value)
        self.triple(s,p,json.dumps(lexical,ensure_ascii=False)+"^^xsd:"+datatype)
    def type(self,s,*classes):
        for cls in classes:
            self.triple(s,"a","zg:"+cls)
    def event(self,identifier,time=None,revision=None):
        identifier=self.event_aliases.get(str(identifier),identifier)
        record=self.events.get(str(identifier),{})
        if time is None:
            time=record.get("time",record.get("atTime"))
        if revision is None:
            revision=record.get("revision")
        node=self.uri("event",identifier)
        self.type(node,"Event")
        if time is not None:
            self.literal(node,"atTime",time,"decimal")
        if revision is not None:
            self.literal(node,"revision",revision)
        return node
    def stocks(self,holder,inventory,reserved):
        for resource in RESOURCES:
            stock=self.uri("stock",holder,resource)
            self.type(stock,"ResourceStock"); self.triple(holder,"stock",stock)
            self.triple(stock,"resourceType","zg:"+resource)
            self.literal(stock,"quantity",inventory.get(resource,0))
            self.literal(stock,"reserved",reserved.get(resource,0))
    def text(self):
        return "@prefix zg: <"+NS+"> .\n@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n"+"\n".join(sorted(self.lines))+"\n"


def _agent_state(writer,agent,state):
    identifier=str(agent["id"]); time=state["time"]; revision=state["revision"]
    identity=writer.uri("agent",identifier)
    current=writer.uri("state",identifier,time,revision)
    fields=("type","role","life","stamina","x","y","hunger","inventory","reserved",
            "infection_episode","active_action","effects","cooldowns","death_at","death_cause")
    recorded={key:agent.get(key) for key in fields}
    if current in writer.state_nodes:
        if writer.state_nodes[current]!=recorded:
            changed=[key for key in fields if writer.state_nodes[current].get(key)!=recorded.get(key)]
            raise ValueError(f"Conflicting actual agent records at {identifier}/{time}/{revision}: {changed}; export cannot invent an intermediate revision")
        return current
    writer.state_nodes[current]=recorded
    world=writer.uri("world"); run=writer.uri("run")
    writer.type(identity,"Agent"); writer.triple(identity,"inRun",run)
    # RDF uses positive integer IDs. Preserve integer identities and allocate a
    # stable export-local integer for named runtime identities; the URI retains
    # the original run namespace and name, including all causal references.
    integer_id=writer.agent_ids[identifier]
    writer.literal(identity,"agent_id",integer_id)
    writer.literal(identity,"created_at",agent.get("created_at",0),"decimal")
    writer.triple(identity,"hasState",current)
    writer.type(current,"AgentState",agent["type"]+"State")
    writer.triple(current,"ofAgent",identity); writer.triple(current,"world",world)
    writer.triple(current,"biologicalType","zg:"+agent["type"])
    if agent["life"]>0:
        writer.triple(current,"hasTypeProfile","zg:"+agent["type"])
    writer.triple(current,"status","zg:"+status(agent))
    writer.triple(current,"actionStatus","zg:"+("ACTION_DEAD" if action_status(agent)=="DEAD" else action_status(agent)))
    writer.literal(current,"atTime",time,"decimal"); writer.literal(current,"revision",revision)
    for key in ("life","stamina","x","y"):
        writer.literal(current,key,agent[key],"integer" if key=="life" else "decimal")
    properties=profile(agent,time)
    for key in COMMON_FIELDS+(HUMAN_FIELDS if agent["type"]=="Human" else ZOMBIE_FIELDS):
        writer.literal(current,key,properties[key],"integer" if key in INTEGER_FIELDS else "decimal")
    last_id=agent.get("last_state_event_id","initialization")
    last=writer.event(last_id,0 if last_id=="initialization" else None,0 if last_id=="initialization" else None)
    writer.triple(current,"lastEvent",last)
    if agent.get("role"):
        role=writer.uri("role",identifier,agent["role"],agent.get("role_started_at",0))
        writer.type(role,"RoleAssignment"); writer.triple(role,"ofAgent",identity)
        writer.triple(role,"roleDefinition","zg:"+agent["role"])
        writer.literal(role,"start_at",agent.get("role_started_at",0),"decimal")
        writer.triple(current,"activeRole",role)
    assignment=agent.get("model_assignment")
    if assignment:
        model_id=assignment.get("model_id",agent["type"]+"DefaultModel")
        version=assignment.get("version","1")
        model=writer.uri("model",model_id,version)
        model_assignment=writer.uri("model_assignment",identifier,model_id,assignment.get("start_at",0))
        writer.type(model,"DecisionModel"); writer.literal(model,"model_id",model_id); writer.literal(model,"model_version",version)
        writer.type(model_assignment,"ModelAssignment"); writer.triple(model_assignment,"ofAgent",identity)
        writer.triple(model_assignment,"modelDefinition",model)
        writer.literal(model_assignment,"start_at",assignment.get("start_at",0),"decimal")
        writer.triple(current,"activeModel",model_assignment)
    if agent["type"]=="Human":
        writer.literal(current,"hunger",agent["hunger"],"decimal")
        inventory=writer.uri("inventory",identifier,time,revision)
        writer.type(inventory,"Inventory"); writer.triple(current,"inventory",inventory)
        writer.stocks(inventory,agent.get("inventory",{}),agent.get("reserved",{}))
        active=agent.get("infection_episode")
        progress=Decimal(0)
        if active:
            episode=state.get("episodes",{}).get(active)
            if episode is None:
                raise ValueError(f"Missing active episode {active}")
            progress=max(Decimal(0),min(Decimal(1),Decimal(_decimal((Fraction(str(time))-Fraction(str(episode["onset_at"])))/Fraction(str(episode["incubation_duration"]))))))
            writer.triple(current,"activeEpisode",writer.uri("episode",active))
        writer.literal(current,"infection_progress",progress,"decimal")
        for key in ("starvation_started_at","next_starvation_damage_at"):
            writer.literal(current,key,agent.get(key),"decimal")
    if agent.get("role")=="SPITTER":
        writer.literal(current,"spit_charges",agent.get("spit_charges",3))
        writer.literal(current,"next_charge_at",agent.get("next_charge_at"),"decimal")
    if agent["life"]==0:
        writer.literal(current,"death_at",agent.get("death_at"),"decimal")
        cause=agent.get("death_cause")
        if isinstance(cause,dict):
            cause=cause.get("event_id",cause.get("cause"))
        if cause:
            writer.triple(current,"deathCause",writer.event(cause))
    for name,until in agent.get("cooldowns",{}).items():
        cooldown=writer.uri("cooldown",identifier,time,revision,name)
        writer.type(cooldown,"Cooldown"); writer.triple(cooldown,"forAction","zg:action_"+name)
        writer.literal(cooldown,"until",until,"decimal"); writer.triple(current,"cooldownRecord",cooldown)
    effects=agent.get("effects",{})
    for index,effect in enumerate(effects.values() if isinstance(effects,dict) else effects):
        if not isinstance(effect,dict):
            continue
        effect_node=writer.uri("effect",identifier,time,revision,index)
        writer.type(effect_node,"TimedEffect"); writer.triple(current,"effect",effect_node)
        writer.triple(effect_node,"recipient",identity)
        writer.literal(effect_node,"start_at",effect.get("start_at",0),"decimal")
        writer.literal(effect_node,"end_at",effect["end_at"],"decimal")
        writer.literal(effect_node,"magnitude",effect.get("value",effect.get("strength",0)),"decimal")
        writer.triple(effect_node,"sourceEvent",writer.event(effect.get("source_event_id",effect.get("source",last_id))))
    if agent.get("active_action"):
        active=agent["active_action"]
        occurrence_id=active.get("id") if isinstance(active,dict) else active
        writer.triple(current,"activeAction",writer.uri("action",occurrence_id))
        # The occurrence is supplied by export_history's real admission records.
        # Missing records are deliberately left visible to SHACL as missing data.
    return current


def _environment_state(writer,collection,identifier,item,time,revision):
    kind=item.get("type","Stockpile" if collection=="stockpiles" else "Remains" if collection=="remains" else "Obstacle")
    entity=writer.uri("entity",identifier)
    current=writer.uri("environment_state",identifier,time,revision)
    geometry=writer.uri("geometry",identifier,time,revision)
    writer.type(entity,kind); writer.type(current,"EnvironmentState",kind+"State")
    writer.triple(current,"ofEntity",entity); writer.triple(current,"world",writer.uri("world"))
    writer.triple(current,"geometry",geometry)
    writer.literal(current,"atTime",time,"decimal"); writer.literal(current,"revision",revision)
    if collection=="barriers":
        writer.type(geometry,"Rectangle")
        for key,value in zip(("xmin","ymin","xmax","ymax"),rect(item)):
            writer.literal(geometry,key,value,"decimal")
        if kind in ("Gate","Barricade"):
            for key in ("integrity","max_integrity"):
                writer.literal(current,key,item[key])
        if kind=="Gate":
            writer.triple(current,"gateMode","zg:"+item["mode"])
            if item.get("shelter_id"):
                writer.triple(entity,"hasShelter",writer.uri("entity",item["shelter_id"]))
    else:
        writer.type(geometry,"Point")
        for key in ("x","y"):
            writer.literal(geometry,key,item[key],"decimal")
        if collection=="stockpiles":
            writer.stocks(current,item.get("inventory",{}),item.get("reserved",{}))
        else:
            writer.literal(current,"biomass",item["biomass"])
            writer.literal(current,"reserved_biomass",item.get("reserved_biomass",item.get("reserved",0)))
            writer.triple(entity,"comesFrom",writer.uri("agent",item["source_agent_id"]))
    return current


def _snapshot(writer,state):
    run,world,scenario=writer.uri("run"),writer.uri("world"),writer.uri("scenario",state.get("scenario_fingerprint","unidentified"))
    writer.type(run,"SimulationRun"); writer.type(world,"World"); writer.type(scenario,"ScenarioDefinition")
    writer.triple(run,"world",world); writer.triple(run,"scenario",scenario)
    writer.literal(world,"length",state["world"]["length"],"decimal")
    writer.literal(world,"width",state["world"]["width"],"decimal")
    for agent in state["agents"].values():
        _agent_state(writer,agent,state)
    for identifier,episode in state.get("episodes",{}).items():
        episode=writer.latest_episodes.get(identifier,episode)
        node=writer.uri("episode",identifier); writer.type(node,"InfectionEpisode")
        writer.triple(node,"infectedAgent",writer.uri("agent",episode["agent_id"]))
        for key in ("onset_at","incubation_duration","conversion_due_at","ended_at"):
            writer.literal(node,key,episode.get(key),"decimal")
        for key in ("onset_revision","end_revision"):
            writer.literal(node,key,episode.get(key))
        writer.literal(node,"source_kind",episode.get("source_kind","INITIAL_CONDITION"))
        writer.triple(node,"episodeOutcome","zg:"+(episode.get("outcome") or "ONGOING"))
        source=episode.get("source_event_id","initialization")
        writer.triple(node,"sourceEvent",writer.event(source,0 if source=="initialization" else None,0 if source=="initialization" else None))
        if episode.get("source_agent_id"):
            writer.triple(node,"sourceAgent",writer.uri("agent",episode["source_agent_id"]))
    for collection in ("barriers","stockpiles","remains"):
        for identifier,item in state.get(collection,{}).items():
            _environment_state(writer,collection,identifier,item,state["time"],state["revision"])
    for identifier,shelter in state.get("shelters",{}).items():
        node=writer.uri("entity",identifier); writer.type(node,"Shelter")
        for key,predicate in (("walls","hasWall"),("gates","hasGate")):
            for item in shelter[key]:
                writer.triple(node,predicate,writer.uri("entity",item))
    for identifier,signal in state.get("signals",{}).items():
        node=writer.uri("signal",identifier); writer.type(node,"Signal")
        for key in ("radius","emitted_at","expires_at"):
            writer.literal(node,key,signal[key],"decimal")


def _captured_state(writer,agent,time,revision):
    """Serialize a recorded boundary, retaining its actual causal coordinates."""
    context={**writer.context,"time":agent.get("at_time",time),
             "revision":agent.get("revision",revision),"episodes":writer.latest_episodes}
    return _agent_state(writer,agent,context)


def _actions(writer):
    for identifier,occurrence in writer.occurrences.items():
        node=writer.uri("action",identifier)
        writer.type(node,"ActionOccurrence")
        writer.triple(node,"actionDefinition","zg:action_"+occurrence["action"])
        writer.triple(node,"actionResult","zg:"+occurrence["result"])
        for predicate,key in (("startTime","start_at"),("plannedEnd","planned_end"),("resolvedAt","resolved_at")):
            writer.literal(node,predicate,occurrence.get(key),"decimal")
        start=occurrence.get("actor_start")
        if not start:
            raise ValueError(f"Action {identifier} has no recorded admission state")
        initial_revision=start.get("revision",0)
        end_event=writer.events.get(writer.event_aliases.get(identifier,""),{})
        end_revision=end_event.get("revision",initial_revision+1)
        for predicate,key,after in (("actorStart","actor_start",False),("actorAfterStart","actor_after_start",True),
                ("targetStart","target_start",False),("actorBeforeEnd","actor_before_end",False),
                ("actorAfterEnd","actor_after_end",True),("targetBeforeEnd","target_before_end",False),
                ("targetAfterEnd","target_after_end",True)):
            agent=occurrence.get(key)
            if agent is None:
                continue
            ending="end" in key
            when=occurrence.get("resolved_at",occurrence["planned_end"]) if ending else occurrence["start_at"]
            revision=end_revision-int(not after) if ending else initial_revision+int(after)
            writer.triple(node,predicate,_captured_state(writer,agent,when,revision))
        intent=writer.uri("intent",occurrence["intent_id"])
        observation=writer.uri("observation",occurrence["intent_id"])
        writer.type(intent,"ActionIntent");writer.type(observation,"Observation")
        writer.triple(node,"realizes",intent)
        writer.triple(intent,"actionDefinition","zg:action_"+occurrence["action"])
        writer.triple(intent,"actor",writer.uri("agent",occurrence["actor"]))
        writer.triple(intent,"observes",observation)
        writer.literal(intent,"proposedAt",occurrence["start_at"],"decimal")
        writer.triple(observation,"observer",writer.uri("agent",occurrence["actor"]))
        writer.literal(observation,"atTime",occurrence["start_at"],"decimal")
        writer.literal(observation,"revision",initial_revision)
        writer.triple(observation,"selfState",_captured_state(writer,start,occurrence["start_at"],initial_revision))
        environment=occurrence.get("environment_start")
        if environment:
            writer.triple(node,"targetEntity",_environment_state(writer,occurrence["target_collection"],
                occurrence["target"],environment,occurrence["start_at"],initial_revision))
        footprint=occurrence.get("parameters",{}).get("footprint")
        if footprint:
            geometry=writer.uri("action_footprint",identifier);writer.type(geometry,"Rectangle")
            for key,value in zip(("xmin","ymin","xmax","ymax"),rect({"footprint":footprint})):
                writer.literal(geometry,key,value,"decimal")
            writer.triple(node,"footprint",geometry)


def _events(writer,events):
    for event in events:
        identifier=event.get("event_id",event.get("id"))
        if identifier is None:
            raise ValueError("Exported events require id/event_id")
        node=writer.event(identifier,event.get("time",event.get("atTime")),event.get("revision"))
        for predecessor in event.get("caused_by",event.get("causes",[])):
            writer.triple(node,"cause",writer.event(predecessor))
        kind=event.get("kind",event.get("type",""))
        before=event.get("before_state");after=event.get("after_state")
        if kind in ("conversion","cure","death") and before and after:
            cls={"conversion":"ConversionTransition","cure":"CureTransition","death":"DeathTransition"}[kind]
            writer.type(node,"LifecycleTransition",cls)
            identifier=event.get("agent_id",before.get("id"))
            for side,snapshot,offset in (("beforeState",before,-1),("afterState",after,0)):
                if "agents" in snapshot:
                    _snapshot(writer,snapshot)
                    state_node=writer.uri("state",identifier,snapshot["time"],snapshot["revision"])
                else:
                    # Lifecycle records contain the actual agent immediately around
                    # their atomic commit; their stale per-agent revision is not
                    # the event boundary's global causal revision.
                    snapshot={**snapshot,"at_time":event["time"],"revision":event["revision"]+offset}
                    state_node=_captured_state(writer,snapshot,event["time"],event["revision"]+offset)
                writer.triple(node,side,state_node)
            if event.get("episode_id"):
                writer.triple(node,"episode",writer.uri("episode",event["episode_id"]))
            if event.get("action_id"):
                writer.triple(node,"triggeredBy",writer.uri("action",event["action_id"]))


def export_snapshot(state,path=None,run_id=None,events=()):
    """Export a real snapshot and its recorded action boundaries, if present."""
    return export_history([state],events,path,run_id or state.get("run_id","run"))


def export_history(snapshots,events=(),path=None,run_id="run"):
    """Export realized state, action and lifecycle evidence in the original vocabulary.

    Supply the actual event ledger along with snapshots to resolve source-event
    links. No example, successful outcome, event time, or state is synthesized.
    An admission Observation records only the captured actor self-state; policy
    internals and unrecorded observations are intentionally outside this export.
    """
    from copy import deepcopy
    snapshots=list(snapshots);events=list(events)
    if not snapshots:
        raise ValueError("RDF history export requires at least one actual snapshot")
    writer=_Writer(run_id);writer.context=snapshots[-1]
    identifiers=sorted({str(identifier) for snapshot in snapshots for identifier in snapshot["agents"]})
    used=set()
    for identifier in identifiers:
        if identifier.isdigit() and int(identifier)>0 and int(identifier) not in used:
            writer.agent_ids[identifier]=int(identifier);used.add(int(identifier))
    next_id=1
    for identifier in identifiers:
        if identifier not in writer.agent_ids:
            while next_id in used:next_id+=1
            writer.agent_ids[identifier]=next_id;used.add(next_id)
    for snapshot in snapshots:
        writer.latest_episodes.update(deepcopy(snapshot.get("episodes",{})))
        writer.occurrences.update(deepcopy(snapshot.get("occurrences",{})))
    for event in events:
        identifier=str(event.get("event_id",event.get("id")))
        writer.events[identifier]=event
        if event.get("occurrence") and event.get("kind") in ("action_completed","action_result"):
            writer.event_aliases[str(event["occurrence"])]=identifier
        if event.get("kind")=="death" and event.get("source") not in writer.occurrences:
            writer.event_aliases[str(event.get("source"))]=identifier
    for snapshot in snapshots:
        snapshot=deepcopy(snapshot);snapshot["episodes"]=writer.latest_episodes
        _snapshot(writer,snapshot)
    _actions(writer)
    _events(writer,events)
    text=writer.text()
    if path is not None:
        Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text(text)
    return text


def validate_export(path,report_path=None):
    """Run real SHACL; absence of optional tooling is an actionable error."""
    try:
        import rdflib
        from pyshacl import validate
    except ImportError as exc:
        raise RuntimeError("RDF validation requires rdflib and pyshacl; use ontology/formal_v0.1/.venv/bin/python or install the ontology optional dependencies") from exc
    graph=rdflib.Graph()
    for source in (ONTOLOGY_DIR/"ontology.ttl",ONTOLOGY_DIR/"catalog.ttl",Path(path)):
        graph.parse(source,format="turtle")
    conforms,report,text=validate(graph,shacl_graph=str(ONTOLOGY_DIR/"shapes.ttl"),inference="rdfs",advanced=True)
    if report_path is not None:
        Path(report_path).write_text(text)
    return {"conforms":bool(conforms),"report":text,"validation_profile":"original_baseline_v0.1","scope":"Only constraints present in the original SHACL shapes; this is not complete behavior certification."}
