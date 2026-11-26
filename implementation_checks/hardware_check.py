"""Focused checks for hardware budgets and cooperative committed boundaries."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from zombie_sim.hardware import worker_budget,available_resources
from zombie_sim import hardware
from zombie_sim.engine import Simulation


def main():
    resources={"logical_cpus":24,"affinity_cpus":24,"cpu_capacity":24.,"available_memory_bytes":64*1024**3,"limit_sources":[]}
    assert worker_budget("auto",resources=resources)["workers"]==23
    assert worker_budget(20,resources=resources)["workers"]==20
    assert worker_budget(100,resources=resources)["workers"]==24
    assert worker_budget(20,resources={**resources,"cpu_capacity":2.5})["workers"]==3
    assert worker_budget("auto",resources={**resources,"cpu_capacity":1.})["workers"]==1
    assert worker_budget(20,resources={**resources,"available_memory_bytes":512*1024**2})["workers"]==1
    assert worker_budget(20,resources=resources,concurrent_runs=6)["workers"]==4
    assert worker_budget("auto",resources=resources,population=2)["workers"]==2
    for invalid in (0,-1,True,"20",1.5):
        try:worker_budget(invalid,resources=resources)
        except ValueError:pass
        else:raise AssertionError(invalid)
    original_text=hardware._text
    combined="/sys/fs/cgroup/cpu,cpuacct/jobs/scenario"
    files={"/proc/self/cgroup":"2:cpu,cpuacct:/jobs/scenario",
           "/proc/meminfo":"MemAvailable: 4194304 kB",
           combined+"/cpu.cfs_quota_us":"150000",
           combined+"/cpu.cfs_period_us":"100000"}
    try:
        hardware._text=lambda path:files.get(str(path))
        detected=available_resources()
        assert detected["cpu_capacity"]==1.5,detected
        assert combined+"/cpu.cfs_quota_us" in detected["limit_sources"]
    finally:hardware._text=original_text
    config={"agents":[{"id":"a","type":"Human","x":5,"y":5}],"execution":{"workers":1},"horizon":10}
    sim=Simulation(config)
    try:
        revision=sim.revision
        result=sim.advance_until(8,return_snapshot=False,should_yield=lambda:True)
        assert sim.time==0 and sim.revision==revision and result["status"]=="PAUSED"
        result=sim.advance_until(8,return_snapshot=False,should_yield=lambda:sim.revision>revision)
        assert sim.time<8 and sim.revision>revision and result["status"]=="PAUSED"
        assert sim.history.revision==sim.revision and not sim._dirty
        sim.advance_until(8,return_snapshot=False)
        assert sim.time==8
    finally:sim.close()
    print({"hardware":available_resources(),"budgets_and_cooperative_yield":"passed"})


if __name__=="__main__":main()
