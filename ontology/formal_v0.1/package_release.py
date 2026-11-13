"""Archive the reviewed artifacts and their checksums, excluding local runtimes."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from build_spec import ROOT, SOURCE, PLAN


def main():
    project = ROOT.parent.parent
    report = json.loads((ROOT / 'reports/validation.json').read_text(encoding='utf-8'))
    if not report['all_passed']:
        raise RuntimeError('Release requires a passing complete validation report.')
    for relative, expected in report['artifact_sha256'].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError('Artifact changed after validation: ' + relative)
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != manifest['source_sha256']:
        raise RuntimeError('Source differs from the validated baseline.')
    files = [p for p in ROOT.iterdir() if p.is_file()
             and (p.suffix in {'.py', '.java', '.md', '.ttl', '.owl', '.json', '.txt'}
                  or p.name == '.gitignore') and p.name != 'SHA256SUMS.txt']
    files += sorted((ROOT / 'examples').glob('*.ttl'))
    cases = json.loads((ROOT / 'examples.json').read_text(encoding='utf-8'))
    selected = {'validation.json', 'catalog_validation.txt', 'baseline_validation.txt'}
    for case in cases:
        selected.update({case['name'] + '.txt', case['name'] + '.ttl'})
    for name in ['core', 'inference', 'conversion_history', 'invalid_state', 'impossible_extension']:
        selected.update({'owl_' + name + '.json', 'owl_' + name + '.log'})
    files += [ROOT / 'reports' / name for name in sorted(selected)]
    files += [SOURCE, PLAN]
    files = sorted(set(files))
    for path in files:
        path.resolve().relative_to(project.resolve())
        if not path.is_file():
            raise RuntimeError('Missing release file: ' + str(path))
    sums = ROOT / 'SHA256SUMS.txt'
    sums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' +
                            p.relative_to(project).as_posix() + '\n' for p in files), encoding='utf-8')
    files.append(sums)
    archive = ROOT.parent / 'zombie_game_formal_v0.1.zip'
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED, compresslevel=9) as z:
        for path in files:
            z.write(path, path.relative_to(project).as_posix())
    with ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('Archive CRC verification failed.')
        forbidden = {'.venv', '.runtime', '__pycache__'}
        if any(forbidden.intersection(Path(n).parts) for n in z.namelist()):
            raise RuntimeError('Local runtime leaked into archive.')
    print(json.dumps({'archive': str(archive), 'files': len(files),
                      'bytes': archive.stat().st_size,
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__':
    main()
