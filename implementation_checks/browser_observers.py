"""Run unchanged supplied browser observer/replay contracts against real services."""
import json
from pathlib import Path
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.suite import load_cases
from tests.run_acceptance import make_suite

if __name__ == '__main__':
    prefixes=('GUI_LINKED','GUI_STEP','GUI_REPLAY','GUI_STREAM','GUI_STALE_SEEK','GUI_CAUSAL','GUI_RECIPROCAL','GUI_OBSERVATION','GUI_OBSERVER')
    cases=[case for case in load_cases() if case['id'].startswith(prefixes)]
    result=unittest.TextTestRunner(verbosity=2).run(make_suite(cases,'zombie_sim.testing:create_adapter',90))
    Path('artifacts/acceptance-browser-observers.json').write_text(json.dumps({'executed':result.testsRun,'failures':[{'id':str(case),'traceback':trace} for case,trace in result.failures],'errors':[{'id':str(case),'traceback':trace} for case,trace in result.errors],'passed':result.wasSuccessful()},indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
