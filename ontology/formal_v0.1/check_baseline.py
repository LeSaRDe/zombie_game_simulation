"""Independent arithmetic and exact rectangular-cell connectivity checks on RDF."""
from collections import deque
from rdflib.namespace import RDF
from build_spec import Z

def check(g):
    results=[]
    def record(name,passed,**details):results.append({'name':name,'passed':bool(passed),**details})
    scenario=next(g.subjects(RDF.type,Z.BaselineScenarioDefinition))
    allocs=list(g.objects(scenario,Z.allocation))
    counts={(str(g.value(a,Z.biologicalType)).split(':')[-1],str(g.value(a,Z.roleDefinition)).split(':')[-1] if g.value(a,Z.roleDefinition) else None):int(g.value(a,Z['count'])) for a in allocs}
    expected={('Human',None):400,('Human','DOCTOR'):80,('Human','WARRIOR'):120,('Human','SCOUT'):80,('Human','ENGINEER'):120,('Zombie',None):120,('Zombie','TYRANT'):20,('Zombie','RUNNER'):30,('Zombie','SPITTER'):20,('Zombie','SCREAMER'):10}
    record('Baseline population allocations',len(allocs)==10 and counts==expected and int(g.value(scenario,Z.initial_humans))==800 and int(g.value(scenario,Z.initial_zombies))==200 and int(g.value(scenario,Z.initial_infected))==20)
    resource_totals={r:0 for r in ['FOOD','MEDICAL_SUPPLY','MATERIAL']}
    points=[];rectangles=[]
    for state in g.objects(scenario,Z.hasEnvironmentState):
        geom=g.value(state,Z.geometry)
        if (geom,RDF.type,Z.Rectangle) in g:
            rect=tuple(float(g.value(geom,Z[p])) for p in ['xmin','ymin','xmax','ymax'])
            rectangles.append((rect,(state,RDF.type,Z.GateState) in g))
        elif (state,RDF.type,Z.StockpileState) in g:
            points.append((float(g.value(geom,Z.x)),float(g.value(geom,Z.y))))
            for stock in g.objects(state,Z.stock): resource_totals[str(g.value(stock,Z.resourceType)).split(':')[-1]]+=int(g.value(stock,Z.quantity))
    resource_totals['MEDICAL_SUPPLY']+=counts[('Human','DOCTOR')]
    resource_totals['MATERIAL']+=counts[('Human','ENGINEER')]
    record('Baseline portable-resource totals',resource_totals=={'FOOD':600,'MEDICAL_SUPPLY':280,'MATERIAL':400},totals=resource_totals)
    world=g.value(scenario,Z.world); length=float(g.value(world,Z.length));width=float(g.value(world,Z.width))
    inside=all(0<=a<b<=length and 0<=c<d<=width for (a,c,b,d),gate in rectangles)
    overlapping=[]
    for i,(r,_) in enumerate(rectangles):
        for q,_ in rectangles[i+1:]:
            if max(r[0],q[0])<min(r[2],q[2]) and max(r[1],q[1])<min(r[3],q[3]):overlapping.append((r,q))
    def blocked(p,rects):return any(a<=p[0]<=b and c<=p[1]<=d for a,c,b,d in rects)
    closed=[r for r,_ in rectangles];opened=[r for r,gate in rectangles if not gate]
    record('Baseline geometry bounds and nonoverlap',inside and not overlapping and len(closed)==28 and len(points)==10 and all(not blocked(p,closed) for p in points))
    xs=sorted({0.,length}|{r[k] for r in closed for k in [0,2]});ys=sorted({0.,width}|{r[k] for r in closed for k in [1,3]})
    centers={(i,j):((xs[i]+xs[i+1])/2,(ys[j]+ys[j+1])/2) for i in range(len(xs)-1) for j in range(len(ys)-1)}
    def components(rects):
        free={k for k,v in centers.items() if not blocked(v,rects)};labels={};cid=0
        while free:
            cid+=1;start=free.pop();labels[start]=cid;q=deque([start])
            while q:
                i,j=q.popleft()
                for n in [(i-1,j),(i+1,j),(i,j-1),(i,j+1)]:
                    if n not in free:continue
                    edge=(xs[i] if n[0]<i else xs[i+1],centers[(i,j)][1]) if n[0]!=i else (centers[(i,j)][0],ys[j] if n[1]<j else ys[j+1])
                    if blocked(edge,rects):continue
                    free.remove(n);labels[n]=cid;q.append(n)
        return labels,cid
    _,nc=components(closed); lab,no=components(opened)
    point_labels=[]
    for x,y in points:point_labels.append({v for (i,j),v in lab.items() if xs[i]<=x<=xs[i+1] and ys[j]<=y<=ys[j+1]})
    record('Baseline shelter connectivity',nc==5 and no==1 and all(len(s)==1 for s in point_labels),closed_regions=nc,open_regions=no)
    return results
