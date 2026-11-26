"""Compare conservative trajectory buckets against the original exact point grid."""
from pathlib import Path
import math
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zombie_sim.engine import Simulation,point


class ReferenceGrid(Simulation):
    def _nearby(self,position,radius):
        size=50.
        if getattr(self,'_spatial_time',None)!=self.time:
            self._spatial_time=self.time;self._spatial_cells={};self._position_cache={}
            for aid,a in self.state['agents'].items():
                occurrence=self.occurrences.get(a.get('active_action'))
                location=self._path_position(occurrence,self.time)[0] if occurrence and occurrence['action'] in {'move','dash'} else point(a)
                self._position_cache[aid]=location
                self._spatial_cells.setdefault((math.floor(location[0]/size),math.floor(location[1]/size)),[]).append(aid)
        return [aid for x in range(math.floor((position[0]-radius)/size),math.floor((position[0]+radius)/size)+1)
                for y in range(math.floor((position[1]-radius)/size),math.floor((position[1]+radius)/size)+1)
                for aid in self._spatial_cells.get((x,y),[])]


def run(cls):
    sim=cls({'preset':'baseline','execution':{'workers':1},'checkpoint_interval':1800})
    try:
        sim.advance_until(10,return_snapshot=False)
        state=sim.snapshot();state.pop('run_id',None)
        return state,list(sim.events)
    finally:sim.close()


if __name__=='__main__':
    old,events=run(ReferenceGrid);new,records=run(Simulation)
    assert old==new,'Swept buckets changed final world'
    assert events==records,'Swept buckets changed semantic history'
    print('1000-agent t10 exact point-grid/swept-bucket state and every event equal')
