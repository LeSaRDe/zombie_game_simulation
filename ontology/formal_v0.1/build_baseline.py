"""Encode the specified initial world and population allocations, not a simulation."""
import json
from rdflib import Namespace, Literal
from rdflib.namespace import RDF, XSD
from build_spec import ROOT, Z, graph, lit

B=Namespace('urn:zombie-game:baseline:')

def build():
    g=graph(); g.bind('base',B)
    def node(name,cls):
        n=B[name]; g.add((n,RDF.type,Z[cls])); return n
    def add(s,p,o): g.add((s,Z[p],o if hasattr(o,'n3') else lit(o)))
    world=node('world','World'); add(world,'length',1000.); add(world,'width',1000.)
    add(world,'boundary_policy','CLOSED'); add(world,'coordinate_system','CartesianXYMeters')
    scenario=node('scenario','BaselineScenarioDefinition'); g.add((scenario,RDF.type,Z.ScenarioDefinition)); add(scenario,'world',world)
    for p,v in {'label':'baseline_v0.1','initial_humans':800,'initial_zombies':200,'initial_infected':20,'horizon':1800.,'incubation_duration':300.,'seed':20261106,'allow_intraspecies_combat':False}.items(): add(scenario,p,v)
    allocations=[]
    for kind,counts in [('Human',[(None,400),('DOCTOR',80),('WARRIOR',120),('SCOUT',80),('ENGINEER',120)]),('Zombie',[(None,120),('TYRANT',20),('RUNNER',30),('SPITTER',20),('SCREAMER',10)])]:
        for role,count in counts:
            alloc=node(kind+'_'+str(role),'PopulationAllocation'); add(scenario,'allocation',alloc); add(alloc,'biologicalType',Z[kind]); add(alloc,'count',count)
            if role: add(alloc,'roleDefinition',Z[role])
            allocations.append({'type':kind,'role':role,'count':count})
    rectangles=[]; stockpiles=[]; gates=[]
    def rectangle(name,coords):
        n=node(name,'Rectangle')
        for p,v in zip(['xmin','ymin','xmax','ymax'],coords): add(n,p,float(v))
        return n
    def env(name,kind,coords,gate=False):
        entity=node(name,kind); state=node(name+'_initial',kind+'State'); g.add((state,RDF.type,Z.EnvironmentState))
        for p,v in {'ofEntity':entity,'world':world,'geometry':rectangle(name+'_rect',coords),'atTime':0.,'revision':0}.items():add(state,p,v)
        add(scenario,'hasEnvironmentState',state); rectangles.append({'name':name,'kind':kind,'rect':coords})
        if gate:
            add(state,'gateMode',Z.CLOSED); add(state,'integrity',200); add(state,'max_integrity',200); gates.append(name)
        return entity,state
    def stock(name,xy,counts):
        ent=node(name,'Stockpile'); state=node(name+'_initial','StockpileState'); g.add((state,RDF.type,Z.EnvironmentState)); point=node(name+'_point','Point')
        add(point,'x',float(xy[0])); add(point,'y',float(xy[1]))
        for p,v in {'ofEntity':ent,'world':world,'geometry':point,'atTime':0.,'revision':0}.items():add(state,p,v)
        add(scenario,'hasEnvironmentState',state)
        for resource,q in zip(['FOOD','MEDICAL_SUPPLY','MATERIAL'],counts):
            r=node(name+'_'+resource,'ResourceStock'); add(state,'stock',r); add(r,'resourceType',Z[resource]); add(r,'quantity',q); add(r,'reserved',0)
        stockpiles.append({'name':name,'point':xy,'quantities':dict(zip(['FOOD','MEDICAL_SUPPLY','MATERIAL'],counts))})
    local=[('north',(0,98,100,100)),('west',(0,2,2,98)),('east',(98,2,100,98)),('southwest',(0,0,47,2)),('southeast',(53,0,100,2))]
    origins=[(150,150),(750,150),(150,750),(750,750)]
    for k,(x,y) in enumerate(origins,1):
        shelter=node(f'shelter{k}','Shelter'); add(shelter,'geometry',rectangle(f'shelter{k}_interior',(x+2,y+2,x+98,y+98)))
        for side,(a,b,c,d) in local:
            wall,_=env(f'shelter{k}_{side}','Obstacle',(x+a,y+b,x+c,y+d)); add(shelter,'hasWall',wall)
        gate,_=env(f'shelter{k}_gate','Gate',(x+47,y,x+53,y+2),True); add(gate,'hasShelter',shelter); add(shelter,'hasGate',gate)
        stock(f'shelter{k}_stock',(x+50,y+50),(60,20,40))
    for k,r in enumerate([(420,180,460,340),(540,660,580,820),(180,540,340,580),(660,420,820,460)],1): env(f'obstacle{k}','Obstacle',r)
    for k,xy in enumerate([(100,500),(300,500),(500,100),(500,300),(700,500),(900,500)],1):stock(f'exterior_stock{k}',xy,(60,20,20))
    g.serialize(ROOT/'baseline.ttl',format='turtle')
    (ROOT/'baseline-summary.json').write_text(json.dumps({'world':[1000,1000],'population_allocations':allocations,'initial_infected':20,'shelter_origins':origins,'barriers':rectangles,'stockpiles':stockpiles,'initial_carried_totals':{'FOOD':0,'MEDICAL_SUPPLY':80,'MATERIAL':120}},indent=2)+'\n',encoding='utf-8')
    print(f'Generated baseline world: {len(rectangles)} barrier rectangles, {len(stockpiles)} stockpiles, 10 population allocations.')
    return g

if __name__=='__main__': build()
