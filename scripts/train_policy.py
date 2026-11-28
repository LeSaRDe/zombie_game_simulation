#!/usr/bin/env python3
"""Train/evaluate the observation-only candidate PPO demonstration."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from zombie_sim.config import resolve_config
from zombie_sim.learning import TrainingConfig
from zombie_sim.training_pipeline import TrainingPipeline, EvaluationPipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",help="Scenario TOML file; default tiny 60-second curriculum")
    parser.add_argument("--output",default="artifacts/training/smoke")
    parser.add_argument("--decisions",type=int,default=4096)
    parser.add_argument("--rollout",type=int,default=1024)
    parser.add_argument("--family",choices=("Human","Zombie"),default="Human")
    parser.add_argument("--device",default="cpu",help="PyTorch training device, e.g. cpu or cuda")
    parser.add_argument("--seed",type=int,default=20261106)
    parser.add_argument("--evaluate",help="Evaluate a saved artifact directory")
    parser.add_argument("--evaluation-seeds",type=int,default=30)
    args=parser.parse_args()
    config=resolve_config(args.config or {"scenario":"training_tiny_v1","horizon":60,
        "world":{"length":60,"width":60},"population":{"humans":4,"zombies":2,"infected":0,"human_roles":{"WARRIOR":1,"DOCTOR":1},"zombie_roles":{"RUNNER":1}},
        "placement":{"cross_type_separation":10},"stockpiles":[{"id":"training_supplies","x":30,"y":30,"inventory":{"FOOD":12,"MEDICAL_SUPPLY":8,"MATERIAL":4}}]})
    settings=TrainingConfig(decisions=args.decisions,rollout=args.rollout,family=args.family,seed=args.seed,device=args.device,evaluation_seeds=tuple(range(2000,2000+args.evaluation_seeds)))
    report=(EvaluationPipeline(config,args.evaluate,settings.evaluation_seeds,family=args.family).run()
            if args.evaluate else TrainingPipeline(config,args.output,settings).run())
    if args.evaluate:
        path=Path(args.output);path.mkdir(parents=True,exist_ok=True);(path/"evaluation.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"artifact":report.get("artifact",args.evaluate),"decisions":report.get("decisions"),"mean_reward":report.get("mean_reward"),"weights_changed":report.get("weights_changed")},indent=2))

if __name__=="__main__":main()
