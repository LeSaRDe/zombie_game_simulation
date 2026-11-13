"""Reproducible specification checks. Exit nonzero on any unexpected result.

No simulation is run. Negative fixtures are expected to fail validation, and must
fail at the named constraint (an unrelated error is not counted as success).
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, OWL, SH
from rdflib.plugins.sparql.parser import parseQuery
from pyshacl import validate as shacl_validate
import owlready2
from build_spec import ROOT,Z

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def java_tools():
    candidates=[]
    if os.environ.get('JAVA_HOME'): candidates.append(Path(os.environ['JAVA_HOME'])/'bin')
    candidates+=sorted((ROOT/'.runtime').glob('jdk-*/bin'))
    if shutil.which('javac'): candidates.append(Path(shutil.which('javac')).parent)
    suffix='.exe' if os.name=='nt' else ''
    for c in candidates:
        if (c/('java'+suffix)).exists() and (c/('javac'+suffix)).exists(): return c/('java'+suffix),c/('javac'+suffix)
    raise RuntimeError('A JDK is required: set JAVA_HOME or extract one under .runtime/.')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--only',choices=['all','owl','shacl'],default='all'); ap.add_argument('--case'); args=ap.parse_args()
    reports=ROOT/'reports'; reports.mkdir(exist_ok=True)
    data={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'command':sys.argv,'python':sys.version,'packages':{p:importlib.metadata.version(p) for p in ['rdflib','pyshacl','owlready2','owlrl']},'checks':[]}
    data.update({'project_root':str(ROOT.parent.parent),'working_directory':str(Path.cwd()),'python_executable':sys.executable})
    def record(name,passed,**details):
        data['checks'].append({'name':name,'passed':bool(passed),**details})
        print(('PASS ' if passed else 'FAIL ')+name,flush=True)
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    record('Source Markdown unchanged',sha(ROOT/manifest['source_file'])==manifest['source_sha256'])
    record('Current plan reference and hash verified',sha(ROOT/manifest['source_plan'])==manifest['source_plan_sha256'])
    ont=Graph().parse(ROOT/'ontology.ttl'); cat=Graph().parse(ROOT/'catalog.ttl'); shapes=Graph().parse(ROOT/'shapes.ttl')
    exchange=Graph().parse(ROOT/'ontology.owl',format='xml')
    from rdflib.compare import isomorphic
    record('OWL Turtle and RDF/XML equivalent',isomorphic(ont+cat,exchange))
    input_files=['ontology.ttl','catalog.ttl','shapes.ttl','ontology.owl','manifest.json',
                 'baseline.ttl','examples.json','requirements.txt','toolchain.json',
                 'build_spec.py','build_examples.py','build_baseline.py','validate.py',
                 'check_baseline.py','check_constraint_boundaries.py','OwlCheck.java']
    input_files.append(manifest['source_plan'])
    input_files += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'examples').glob('*.ttl'))]
    for name in input_files:
        data.setdefault('artifact_sha256',{})[name]=sha(ROOT/name)
    if args.only in ['all','owl']:
        java,javac=java_tools(); jar=Path(owlready2.__file__).parent/'hermit'/'HermiT.jar'
        data['java_executable']=str(java)
        data['hermit_jar']=str(jar)
        data['java_version']=subprocess.run([str(java),'-version'],capture_output=True,text=True,check=True).stderr.strip()
        data['hermit_jar_sha256']=sha(jar)
        classes=ROOT/'.runtime'/'classes'; classes.mkdir(parents=True,exist_ok=True)
        subprocess.run([str(javac),'-cp',str(jar),'-d',str(classes),str(ROOT/'OwlCheck.java')],check=True,capture_output=True,text=True)
        for name,file in [('core',None),('inference','owl_inference.ttl'),('conversion_history','valid_conversion_preserves_identity.ttl'),('invalid_state','owl_inconsistent_state.ttl'),('impossible_extension','owl_unsatisfiable_extension.ttl')]:
            g=ont+cat
            if file: g+=Graph().parse(ROOT/'examples'/file)
            infile=ROOT/'.runtime'/('owl_'+name+'.owl'); outfile=reports/('owl_'+name+'.json')
            g.serialize(infile,format='xml')
            proc=subprocess.run([str(java),'-Xmx1024m','-cp',os.pathsep.join([str(jar),str(classes)]),'OwlCheck',str(infile),str(outfile)],capture_output=True,text=True,timeout=180)
            (reports/('owl_'+name+'.log')).write_text(proc.stdout+proc.stderr,encoding='utf-8')
            if proc.returncode: raise RuntimeError(proc.stdout+proc.stderr)
            result=json.loads(outfile.read_text(encoding='utf-8'))
            record('OWL 2 DL profile: '+name,result['owl2_dl'],report=outfile.name)
            if not result['owl2_dl']: continue
            if name=='core':
                record('OWL core logically consistent',result['consistent'])
                record('All intended named classes satisfiable',result['consistent'] and not result['unsatisfiable_classes'],classes=result['named_class_count'])
                record('Infection-capable action classification',set(result['infection_capable_actions'])=={str(Z.action_bite),str(Z.action_spit)})
            elif name=='inference':
                record('Doctor and infected state classifications inferred',result['consistent'] and {str(Z.DoctorState),str(Z.InfectedHumanState)}.issubset(result['inferred_types']))
                record('Role and type capabilities inferred',{str(Z.cap_treat_infection),str(Z.cap_move)}.issubset(result['inferred_capabilities']))
            elif name=='conversion_history': record('Time-indexed human/zombie history consistent',result['consistent'] and not result['unsatisfiable_classes'])
            elif name=='invalid_state': record('Contradictory Human/Zombie state rejected',not result['consistent'])
            else: record('Impossible extension detected before instantiation',result['consistent'] and 'urn:zombie-game:example:ImpossibleDoctorZombie' in result['unsatisfiable_classes'])
    if args.only in ['all','shacl']:
        failures=[]
        for c,q in shapes.subject_objects(SH.select):
            try: parseQuery(str(q))
            except Exception as ex: failures.append({'constraint':str(c),'error':str(ex)})
        record('Every embedded SPARQL constraint parses',not failures,errors=failures)
        if failures: raise RuntimeError('SPARQL syntax errors')
        from check_constraint_boundaries import check as check_boundaries
        for row in check_boundaries(shapes):
            record(row.pop('name'),row.pop('passed'),**row)
        # This includes the vocabulary individuals, not just TBox inoculation.
        # RDFS inference is explicit; no OWL closed-world behavior is assumed.
        ok,report,txt=shacl_validate(ont+cat,shacl_graph=shapes,inference='rdfs',meta_shacl=True)
        record('SHACL meta-validation and baseline catalog conformance',ok)
        (reports/'catalog_validation.txt').write_text(txt,encoding='utf-8')
        if not args.case:
            baseline=Graph().parse(ROOT/'baseline.ttl')
            ok,report,txt=shacl_validate(ont+cat+baseline,shacl_graph=shapes,inference='rdfs')
            record('Baseline configuration SHACL conformance',ok)
            (reports/'baseline_validation.txt').write_text(txt,encoding='utf-8')
            from check_baseline import check as check_baseline
            for row in check_baseline(baseline):
                record(row.pop('name'),row.pop('passed'),**row)
        cases=json.loads((ROOT/'examples.json').read_text(encoding='utf-8'))
        for case in cases:
            if args.case and args.case!=case['name']: continue
            g=ont+cat+Graph().parse(ROOT/case['file'])
            try:
                ok,report,txt=shacl_validate(g,shacl_graph=shapes,inference='rdfs',meta_shacl=False)
                found={str(v).split(':')[-1] for p in [SH.sourceConstraint,SH.sourceShape] for v in report.objects(None,p)}
                expected=case.get('expected_constraint')
                passed=bool(ok)==case['expected_conforms'] and (not expected or expected in found)
                (reports/(case['name']+'.txt')).write_text(txt,encoding='utf-8'); report.serialize(reports/(case['name']+'.ttl'),format='turtle')
                record('SHACL: '+case['name'],passed,expected_conforms=case['expected_conforms'],actual_conforms=bool(ok),expected_constraint=expected,observed_constraints=sorted(found))
            except Exception as ex: record('SHACL: '+case['name'],False,error=repr(ex))
    data['all_passed']=all(c['passed'] for c in data['checks'])
    data['scope']='OWL consistency/satisfiability/inference and finite-graph SHACL conformance; not proof of full gameplay or all possible executions.'
    filename='validation.json' if args.only=='all' and not args.case else 'validation_'+args.only+('_'+args.case if args.case else '')+'.json'
    (reports/filename).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(f"{sum(c['passed'] for c in data['checks'])}/{len(data['checks'])} checks passed. Report: {filename}",flush=True)
    return 0 if data['all_passed'] else 1

if __name__=='__main__': raise SystemExit(main())
