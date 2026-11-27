"""Check retained inputs, documentation links and the packaged GUI artifact."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BEFORE = Path('/tmp/zombie-remaining-before-doup96mn')


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    retained = []
    for relative in ('prompts', 'tests', 'src/zombie_sim/policies.py'):
        original = BEFORE / relative
        files = original.rglob('*') if original.is_dir() else [original]
        for path in files:
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                target = ROOT / path.relative_to(BEFORE)
                assert target.is_file() and digest(path) == digest(target), target
                retained.append(str(path.relative_to(BEFORE)))
    assert not subprocess.check_output(['git', 'diff', '--name-only', '--', 'ontology'], cwd=ROOT, text=True).strip()
    checked = []
    for name in ('README.md', 'docs/ISSUE_REVIEW.md', 'docs/USER_GUIDE.md', 'docs/START_STOP_GUIDE.md', 'docs/GUI.md', 'docs/MODELS.md'):
        path = ROOT / name
        for destination in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if destination.startswith(('http:', 'https:', '#', 'mailto:')): continue
            file = destination.split('#', 1)[0]
            if not file: continue
            assert (path.parent / file).exists(), (name, destination)
            checked.append({'document': name, 'target': destination})
    static = ROOT / 'src/zombie_sim/static'
    index = (static / 'index.html').read_text()
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index)
    assert len(assets) >= 2
    for asset in assets:
        packaged = static / asset.lstrip('/')
        assert packaged.is_file(), asset
        built = ROOT / 'gui/dist' / asset.lstrip('/')
        assert built.is_file() and digest(packaged) == digest(built), asset
    subprocess.run(['git', 'diff', '--check', '--', '.', ':!prompts/zombie_game_plans.md'], cwd=ROOT, check=True)
    report = {'status': 'PASS', 'retained_inputs': retained, 'ontology_diff': [],
              'documentation_links_checked': len(checked), 'packaged_assets': assets,
              'note': 'The unchanged user-edited plan is excluded from whitespace checking; its original CRLF/trailing whitespace is retained.'}
    (ROOT / 'artifacts/remaining-review.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({**report, 'retained_inputs': len(retained)}, indent=2))


if __name__ == '__main__': main()
