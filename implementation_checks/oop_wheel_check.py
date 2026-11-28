"""Verify the offline OOP wheel's new modules, SDK, pins and old-run restart.

Requires the output of scripts/build_verified_wheel.py in the requested directory.
All SDK execution occurs in that build's fresh, dependency-free installed venv.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

ISOLATED_SDK_CHECK = r'''
from dataclasses import dataclass, asdict
import importlib
import json
from pathlib import Path
import sys
from zombie_sim import ActionIntent, Decision, ObjectDecisionModel, Simulation, SimulationFramework
from zombie_sim.core import SimulationServiceFactory, ServiceBindingMismatch
from zombie_sim.core.observations import ObservationService
from zombie_sim.registry import DEFAULT_CATALOG, ONTOLOGY_DIR
from zombie_sim.config import ConfigurationService

stage, result_path, module_path = map(Path, sys.argv[1:4])
installed = Path(importlib.import_module('zombie_sim').__file__).parent.resolve()
assert installed.is_relative_to(Path(sys.prefix))
assert not any('workspace/zombie_game_simulation' in name for name in sys.path)
modules = json.loads(module_path.read_text())
for name in modules:
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(installed), name
assert ONTOLOGY_DIR.resolve() == installed / 'spec/formal_v0.1'
assert len(DEFAULT_CATALOG.actions) == 29 and len(DEFAULT_CATALOG.roles) == 8
assert DEFAULT_CATALOG.baseline_graph()
baseline = ConfigurationService().resolve({'preset': 'baseline'})
assert baseline['population']['humans'] == 800 and baseline['population']['zombies'] == 200

@dataclass
class Memory:
    choices: int

class PackagingModel(ObjectDecisionModel):
    model_id = 'packaging/typed'
    version = '1.0.0'
    def initial_memory(self, agent):
        return Memory(41)
    def encode_memory(self, memory):
        return asdict(memory)
    def decode_memory(self, payload):
        return Memory(**payload)
    def choose(self, observation, memory, rng):
        assert isinstance(memory, Memory)
        assert observation.self_state.identity is None
        memory.choices += 1
        return Decision(ActionIntent('wait', parameters={'duration': '1/2'}), memory)

class CountingObservation(ObservationService):
    def observe(self, aid):
        self.calls = getattr(self, 'calls', 0) + 1
        return super().observe(aid)

framework = SimulationFramework()
framework.models.register('packaging/typed', PackagingModel, label='Packaging typed model')
scenario = (framework.scenario().set(seed=92, horizon=4)
    .agents([{'id':'h', 'type':'Human', 'x':10, 'y':10},
             {'id':'z', 'type':'Zombie', 'x':35, 'y':10}])
    .decision_models(human='packaging/typed', zombie='packaging/typed'))
backends = []
for backend in ('memory', 'sqlite'):
    with framework.create(scenario, workers=1, backend=backend) as experiment:
        experiment.advance('5/4')
        assert experiment.simulation.memories['h']['value']['choices'] > 41
        checkpoint = experiment.checkpoint(stage / ('sdk-'+backend+'.json'))
        with framework.restore(checkpoint, workers=1, backend=backend) as resumed:
            resumed.advance(3); experiment.advance(3)
            assert resumed.snapshot().to_record() == experiment.snapshot().to_record()
            assert resumed.simulation.memories == experiment.simulation.memories
            assert list(resumed.simulation.events) == list(experiment.simulation.events)
        assert experiment.measure()['measurements']['population']['values']['living_humans'] == 1
    backends.append(backend)

factory = SimulationServiceFactory({'observations': CountingObservation})
with Simulation({'preset':'small', 'horizon':3}, workers=1, service_factory=factory) as simulation:
    simulation.advance_until(1)
    assert simulation.services.observations.calls > 0
    checkpoint = simulation.checkpoint(stage / 'sdk-custom-services.json')
    try:
        Simulation.restore(checkpoint, workers=1)
    except ServiceBindingMismatch:
        pass
    else:
        raise AssertionError('Installed custom services silently defaulted during restore')
    with Simulation.restore(checkpoint, workers=1, service_factory=factory) as resumed:
        simulation.advance_until(2); resumed.advance_until(2)
        assert simulation.snapshot() == resumed.snapshot()

# A checkpoint written by the original pre-refactor source package must retain
# its exact built-in-model and ontology pins when opened from the installed wheel.
with Simulation.restore(stage / 'before-refactor.json', workers=1, backend='memory') as resumed:
    resumed.advance_until(5, return_snapshot=False)
    attrs = resumed.serialize()['attributes']; attrs.pop('history_path', None)
    actual = {'state':resumed.snapshot(), 'events':list(resumed.events),
              'decisions':list(resumed.decisions), 'random_draws':list(resumed.random_draws),
              'runtime_attributes':attrs}
    assert actual == json.loads((stage / 'before-refactor-trace.json').read_text())
third_party = sorted({module.__name__.split('.')[0] for module in tuple(sys.modules.values())
    if getattr(module, '__file__', None) and '/site-packages/' in str(module.__file__)})
assert third_party == ['zombie_sim'], third_party
report = {'new_modules_imported':modules, 'bundled_ontology_default_path':str(ONTOLOGY_DIR),
          'formal_baseline_config_loaded':True, 'typed_model_codec_and_restart_backends':backends,
          'typed_measurements':True, 'custom_services_and_restart_guard':True,
          'pre_refactor_bundle_exact_continuation':True, 'only_installed_package_and_stdlib_loaded':third_party,
          'isolated_python':sys.version, 'installed_package':str(installed)}
result_path.write_text(json.dumps(report,indent=2)+'\n')
'''


def main():
    distribution = ROOT / (sys.argv[1] if len(sys.argv)>1 else 'artifacts/oop-refactor/distribution')
    packaging = json.loads((distribution/'wheel_verification.json').read_text())
    stage = Path(packaging['clean_staging'])
    baseline = json.loads((ROOT/'artifacts/oop-refactor/source-before.json').read_text())
    new_modules = sorted(name[:-3].replace('/', '.') for name in packaging['packaged_sha256']
                         if name.endswith('.py') and 'src/'+name not in baseline and not name.endswith('/__init__.py'))
    (stage/'new_modules.json').write_text(json.dumps(new_modules))
    env = dict(os.environ, PYTHONPATH=str(ROOT/'artifacts/oop-refactor/baseline-package'),
               PYTHONDONTWRITEBYTECODE='1', ZOMBIE_ONTOLOGY_DIR=str(ROOT/'ontology/formal_v0.1'))
    options = {'mode':'model','backend':'memory','workers':1,
               'checkpoint_output':str(stage/'before-refactor.json'),
               'output':str(stage/'before-refactor-trace.json')}
    subprocess.run([sys.executable,str(ROOT/'implementation_checks/oop_core_check.py'),'--probe',json.dumps(options)],
                   cwd=stage,env=env,check=True,capture_output=True,text=True)
    script=stage/'isolated_sdk_check.py';script.write_text(ISOLATED_SDK_CHECK)
    isolated_env={key:value for key,value in os.environ.items() if key not in {'PYTHONPATH','PYTHONHOME','ZOMBIE_ONTOLOGY_DIR'}}
    subprocess.run([packaging['python_executable'],'-I',str(script),str(stage),str(distribution/'isolated_sdk.json'),str(stage/'new_modules.json')],
                   cwd=stage,env=isolated_env,check=True,capture_output=True,text=True)
    with zipfile.ZipFile(packaging['wheel']) as archive:
        preserved={}
        for filename in ('policies.py','learning.py'):
            old=(ROOT/'artifacts/oop-refactor/baseline-package/zombie_sim'/filename).read_bytes()
            packaged=archive.read('zombie_sim/'+filename)
            assert old==packaged, filename
            preserved[filename]=hashlib.sha256(packaged).hexdigest()
    result=json.loads((distribution/'isolated_sdk.json').read_text())
    result.update(wheel=packaging['wheel'],wheel_sha256=packaging['sha256'],preserved_model_implementation_hashes=preserved)
    (distribution/'isolated_sdk.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
