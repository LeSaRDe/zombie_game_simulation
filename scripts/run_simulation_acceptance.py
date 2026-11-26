"""Execute the supplied simulation/validation cases without altering their oracles."""
import json
from pathlib import Path
import time
import unittest

from tests.suite import load_cases
from tests.run_acceptance import make_suite


def main():
    cases=[case for case in load_cases() if case["request"]["kind"] in {"simulation","validation"}]
    start=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2).run(make_suite(cases,"zombie_sim.testing:create_adapter",60))
    report={"scope":"partial: all supplied simulation and validation requests","adapter":"zombie_sim.testing:create_adapter",
            "selected_cases":len(cases),"executed":result.testsRun,"elapsed_seconds":time.monotonic()-start,
            "status":"PASS" if result.wasSuccessful() else "FAIL",
            "failures":[{"id":str(case),"traceback":error} for case,error in result.failures],
            "errors":[{"id":str(case),"traceback":error} for case,error in result.errors],
            "skipped":[{"id":str(case),"reason":reason} for case,reason in result.skipped]}
    path=Path("tests/results/simulation-validation.json");path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+"\n")
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__":raise SystemExit(main())
