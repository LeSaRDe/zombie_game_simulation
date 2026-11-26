"""Combine explicit acceptance reports without rerunning or weakening assertions."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.suite import load_cases

REPORTS = [
    'tests/results/core-final.json',
    'tests/results/browser-final.json',
    'tests/results/performance.json',
    'tests/results/statistical-final.json',
    'tests/results/training.json',
    'tests/results/policy-final.json',
    'tests/results/formal-final.json',
    'tests/results/lifecycle-integration-final.json',
    'artifacts/acceptance-baseline-full-final.json',
]


def summarize():
    catalog = {case['id'] for case in load_cases()}
    covered = set()
    evidence = []
    for relative in REPORTS:
        path = ROOT / relative
        if not path.exists():
            evidence.append({'path': relative, 'status': 'MISSING'})
            continue
        raw = path.read_bytes()
        report = json.loads(raw)
        identities = report.get('selected_ids', [])
        valid = (report.get('status') == 'PASS'
                 and report.get('executed') == len(identities)
                 and len(identities) == len(set(identities))
                 and set(identities) <= catalog
                 and not any(report.get(key) for key in ('failures', 'errors', 'skipped')))
        if valid:
            covered.update(identities)
        evidence.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest(),
                         'status': report.get('status'), 'accepted_as_passing_evidence': valid,
                         'adapter': report.get('adapter'),
                         'evaluation_scope': ('assertions on recovered completed-run captures'
                                              if report.get('adapter') == 'zombie_sim.testing_recovery:create_adapter'
                                              else 'adapter execution'),
                         'case_count': len(identities), 'elapsed_seconds': report.get('elapsed_seconds')})
    missing = sorted(catalog - covered)
    return {'status': 'PASS' if not missing else 'INCOMPLETE',
            'scope': 'combined per-tier executions; not a single runner invocation',
            'catalog_cases': len(catalog), 'passing_cases': len(covered),
            'missing_passing_evidence': missing, 'reports': evidence,
            'test_source_manifest_sha256': hashlib.sha256((ROOT/'tests/source_manifest.json').read_bytes()).hexdigest()}


if __name__ == '__main__':
    result = summarize()
    destination = ROOT/'tests/results/combined-final.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2)+'\n')
    print(f"{result['status']}: {result['passing_cases']}/{result['catalog_cases']} cases have passing evidence")
    print(destination)
