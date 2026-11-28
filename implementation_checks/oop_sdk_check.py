"""Independent public-OOP extension, isolation and restart integration checks."""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
from random import Random
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from oop_custom_model import PatientModel, MeanLivingStamina
from zombie_sim import (ActionIntent, AgentView, Decision, ExactTime, HistoryCursor,
                        MeasurementRegistry, ModelRegistry, SimulationFramework)
from zombie_sim import ObjectDecisionModel
from zombie_sim.learning import TrainingConfig
from zombie_sim.training_pipeline import TrainingPipeline, EvaluationPipeline


@dataclass
class CounterMemory:
    count: int


class CodecModel(ObjectDecisionModel):
    model_id = "example/codec"
    def initial_memory(self, agent):
        return CounterMemory(40)
    def choose(self, observation, memory, rng):
        assert isinstance(memory, CounterMemory)
        return Decision(ActionIntent("wait", parameters={"duration":1}), CounterMemory(memory.count+1))
    def encode_memory(self, memory):
        return {"count": memory.count}
    def decode_memory(self, payload):
        return CounterMemory(payload["count"])


def main():
    checks = []
    def checked(name): checks.append(name)
    def rejects(call, exception=ValueError):
        try: call()
        except exception: return
        raise AssertionError("Invalid operation accepted")

    cursor = HistoryCursor("run", ExactTime(Fraction(1, 10**25)), 10**30)
    assert HistoryCursor.from_record(cursor.to_record()) == cursor
    assert str(ExactTime.parse("1/3").plus("2/3")) == "1"
    for value in (True, -1, "nan"):
        rejects(lambda: ExactTime.parse(value))
    rejects(lambda: HistoryCursor("run", ExactTime(0), 1.5))
    checked("exact rational cursors and unbounded revision roundtrip")

    source = {"id":"a", "type":"Human", "life":100, "x":1, "y":2,
              "inventory":{"FOOD":1}, "role":"SCOUT"}
    view = AgentView(source, "run")
    source["inventory"]["FOOD"] = 4
    assert view["inventory"]["FOOD"] == 1
    rejects(lambda: view["inventory"].__setitem__("FOOD", 7), AttributeError)
    detached = view.to_record(); detached["inventory"]["FOOD"] = 9
    assert view["inventory"]["FOOD"] == 1
    converted = AgentView({**source, "type":"Zombie", "role":None}, "run")
    assert converted.identity == view.identity and converted.biological_type != view.biological_type
    assert AgentView(source).identity is None and AgentView(source).agent_id == "a"
    rejects(lambda: AgentView({**source,"mutable":{1,2}}),TypeError)
    checked("nested immutable views detach input/output and preserve biological identity")

    registry = ModelRegistry()
    registry.register("example/patient", PatientModel, label="Patient policy")
    assert "example/patient" in registry.names()
    framework = SimulationFramework(models=registry)
    framework.measurements.register(MeanLivingStamina())
    assert "mean_living_stamina" not in MeasurementRegistry().names()
    builder = framework.scenario().set(horizon=5,seed=42).decision_models(
        human="example/patient", zombie="example/patient")
    draft = builder.draft(); draft["seed"] = 99
    assert builder.build()["seed"] == 42
    assert builder.build()["human_model"] == "example/patient"
    checked("instance-owned measurements and validated detached scenario construction")

    with TemporaryDirectory(prefix="zombie-oop-sdk-") as directory:
        path = Path(directory)
        with framework.create(builder, workers=1, history_path=path/"run.sqlite") as experiment:
            original = experiment.snapshot()
            observation = experiment.observe("1")
            model = registry.create("example/patient")
            memory = {"decisions": 9}
            result = model.decide(observation.to_record(), memory, Random(7))
            assert memory == {"decisions":9} and result[1]["value"] == {"decisions":10}
            assert result[0]["action"] == "wait"
            rejects(lambda: model.encode_memory({"x":float("nan")}))
            assert model.decode_memory(model.encode_memory(result[1]["value"])) == {"decisions":10}
            assert "run_id" not in observation and not hasattr(observation, "simulation")
            experiment.advance("3/2")
            assert str(original.cursor.time) == "0"
            measured = experiment.measure()
            assert measured["measurements"]["population"]["values"]["living_humans"] == 16
            assert measured["measurements"]["mean_living_stamina"]["values"]["living_count"] == 20
            checkpoint = path/"session.json"
            experiment.checkpoint(checkpoint)
            with framework.restore(checkpoint, history_path=path/"restored.sqlite", workers=1) as restored:
                assert restored.snapshot().to_record() == experiment.snapshot().to_record()
                restored.advance(4); experiment.advance(4)
                assert restored.snapshot().to_record() == experiment.snapshot().to_record()
                assert restored.simulation.memories == experiment.simulation.memories
                assert list(restored.simulation.random_draws) == list(experiment.simulation.random_draws)
            checked("real typed custom model decisions, private memory, artifact-pinned checkpoint continuation")
        experiment.close()
        rejects(experiment.snapshot, RuntimeError)
        checked("experiment closes owned simulation and rejects use after close")

        registry.register("example/codec", CodecModel)
        codec_scenario=framework.scenario().set(horizon=5).decision_models(human="example/codec",zombie="example/codec")
        with framework.create(codec_scenario,workers=1) as experiment:
            experiment.advance("1/2")
            assert experiment.simulation.memories["1"]["value"] == {"count":41}
            checkpoint=path/"codec.json"
            experiment.checkpoint(checkpoint)
            with framework.restore(checkpoint,workers=1) as restored:
                restored.advance("3/2"); experiment.advance("3/2")
                assert restored.simulation.memories==experiment.simulation.memories
                assert restored.simulation.memories["1"]["value"] == {"count":42}
                assert restored.snapshot().to_record()==experiment.snapshot().to_record()
        checked("custom initial memory and non-JSON memory codec execute through real decisions and restart")

        base_path=path/"oop_inherited_base.py"
        base_source=("from zombie_sim import ObjectDecisionModel, Decision, ActionIntent\n"
                     "class ParentModel(ObjectDecisionModel):\n"
                     "    def choose(self, observation, memory, rng):\n"
                     "        return Decision(ActionIntent('wait', parameters={'duration':1}), memory)\n")
        base_path.write_text(base_source)
        child_path=path/"oop_inherited_child.py"
        child_path.write_text("from oop_inherited_base import ParentModel\nclass ChildModel(ParentModel):\n    model_id='example/inherited'\n")
        for name,module_path in (("oop_inherited_base",base_path),("oop_inherited_child",child_path)):
            spec=importlib.util.spec_from_file_location(name,module_path)
            module=importlib.util.module_from_spec(spec)
            sys.modules[name]=module; spec.loader.exec_module(module)
        registry.register("example/inherited",sys.modules["oop_inherited_child"].ChildModel)
        inherited=framework.scenario().set(horizon=5).decision_models(human="example/inherited",zombie="example/inherited")
        with framework.create(inherited,workers=1) as experiment:
            experiment.advance("1/2")
            checkpoint=path/"inherited.json"; experiment.checkpoint(checkpoint)
            base_path.write_text(base_source+"# changed inherited implementation\n")
            from zombie_sim.artifact_pins import ArtifactMismatch
            rejects(lambda: framework.restore(checkpoint,workers=1),ArtifactMismatch)
            base_path.write_text(base_source)
            with framework.restore(checkpoint,workers=1) as restored:
                restored.advance("3/2"); experiment.advance("3/2")
                assert restored.snapshot().to_record()==experiment.snapshot().to_record()
        checked("checkpoint rejects changed intermediate model superclass source and restores exact original")

    calls=[]
    class Backend:
        def train(self, config, output, settings):
            calls.append(("train",config["seed"],settings.decisions))
            config["seed"]=999; settings.decisions=999
            return {"trained":True}
        def evaluate(self, config, artifact, seeds, **options):
            calls.append(("evaluate",tuple(seeds), options["policy"]))
            return {"evaluated":True}
    config = {"seed":42,"horizon":5}
    settings = TrainingConfig(decisions=8)
    pipeline=TrainingPipeline(config, "unused-injected-output",settings,backend=Backend())
    config["seed"]=0; settings.decisions=1
    assert pipeline.run()==pipeline.run()=={"trained":True}
    assert calls[:2]==[("train",42,8)]*2
    assert EvaluationPipeline({"horizon":5},seeds=[31,32],backend=Backend(),policy="default").run()=={"evaluated":True}
    rejects(lambda: EvaluationPipeline({},seeds=[31,31]))
    rejects(lambda: TrainingConfig(train_seeds=(1,),validation_seeds=(1,)))
    checked("training/evaluation backend injection, detached inputs and split/seed validation")

    # Source provenance schema is inspected by the final audit; the model file
    # pins are additionally checked against the preserved original package here.
    for name in ("policies.py","learning.py"):
        before=ROOT/"artifacts/oop-refactor/baseline-package/zombie_sim"/name
        after=ROOT/"src/zombie_sim"/name
        assert hashlib.sha256(before.read_bytes()).digest()==hashlib.sha256(after.read_bytes()).digest()
    checked("existing built-in and learned model implementation pins remain byte-identical")
    import os
    output=Path(os.environ.get('ZOMBIE_VERIFICATION_OUTPUT_ROOT', str(ROOT/'artifacts/oop-refactor')))/'sdk-checks.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"passed":len(checks),"checks":checks},indent=2)+"\n")
    print(json.dumps({"passed":len(checks),"checks":checks},indent=2))


if __name__=="__main__": main()
