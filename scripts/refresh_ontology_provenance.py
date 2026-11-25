"""D8 maintenance: archive old evidence, refresh only the source-plan digest.

Run the existing formal validate.py and package_release.py afterwards. This
script never regenerates the ontology or changes its game rules.
"""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
FORMAL=ROOT/"ontology"/"formal_v0.1"


def main():
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    manifest_path=FORMAL/"manifest.json"
    original=manifest_path.read_bytes()
    manifest=json.loads(original)
    current=digest(FORMAL/manifest["source_plan"])
    old=manifest["source_plan_sha256"]
    if current==old:
        print("Plan provenance already current")
        return
    archive=FORMAL/"provenance"/("before-task2-"+old[:12])
    archive.mkdir(parents=True,exist_ok=False)
    for name in ("manifest.json","SHA256SUMS.txt"):
        shutil.copy2(FORMAL/name,archive/name)
    shutil.copytree(FORMAL/"reports",archive/"reports")
    release=ROOT/"ontology"/"zombie_game_formal_v0.1.zip"
    if release.exists():shutil.copy2(release,archive/release.name)
    unchanged={name:digest(FORMAL/name) for name in ("ontology.ttl","ontology.owl","catalog.ttl","baseline.ttl","shapes.ttl")}
    manifest["source_plan_sha256"]=current
    manifest_path.write_bytes(original.replace(old.encode(),current.encode()))
    record={"maintenance":"TASK 2 implementation plan D8", "old_plan_sha256":old,
            "current_plan_sha256":current,"preserved_evidence":str(archive.relative_to(ROOT)),
            "unchanged_rule_artifacts":unchanged,"source_markdown_sha256":manifest["source_sha256"],
            "validation_required":"ontology/formal_v0.1/validate.py; package_release.py"}
    (FORMAL/"provenance_refresh.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps(record,indent=2))


if __name__=="__main__":main()
