"""Generate the offline UML class atlas from Python and TypeScript ASTs.

Uses installed Graphviz and GUI TypeScript tools. No application imports,
simulation execution, network access or third-party UML renderer is required.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
from html import escape
import json
from pathlib import Path
import re
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/classes"
SOURCE_ROOTS = ("src/zombie_sim", "gui/src", "scripts", "examples", "tests",
                "implementation_checks", "ontology/formal_v0.1")
GROUPS = {
    "domain": "Domain, configuration and ontology",
    "rules": "Game rules, action handlers and transition planning",
    "state": "Typed state ownership and transaction coordination",
    "engine": "Simulation engine and service composition",
    "contracts": "Public structural contracts",
    "models": "Decision models and Python modeling API",
    "persistence": "State, history and exact restart",
    "application": "Managed execution, HTTP and commands",
    "analysis": "Analysis, visualization and export",
    "learning": "Training and evaluation",
    "gui": "GUI controllers, readers and presenters",
    "operations": "Launcher and operational tooling",
    "examples": "Runnable modeling examples",
    "verification": "Verification adapters and test classes",
}
COLORS = {key: value for key, value in zip(GROUPS, (
    "#e8f3fb", "#fff3df", "#e7f5ec", "#e7eefc", "#fff1d9", "#e9f4ed", "#e5f3f0", "#edf0fc",
    "#e6f4f7", "#f2eafa", "#fceef0", "#f0eee8", "#eef6df", "#f1f3f5"))}


def category(path):
    if path.startswith(("tests/", "implementation_checks/")) or Path(path).name.startswith("testing"):
        return "verification"
    if path.startswith("gui/"): return "gui"
    if path.startswith("examples/"): return "examples"
    if path.startswith(("scripts/", "ontology/")): return "operations"
    if "/domain_model/" in path: return "domain"
    if "/game_rules/" in path: return "rules"
    if "/state_management/" in path: return "state"
    if "/persistence/" in path: return "persistence"
    if "/execution/" in path: return "engine"
    name = Path(path).stem
    if name in {"storage", "history_sequence", "runtime", "runtime_service", "artifact_pins"}: return "persistence"
    if name in {"engine", "actions", "parallel", "interrupts"} or "/core/" in path: return "engine"
    if name in {"entities", "domain", "config", "config_io", "registry", "initial_state"}: return "domain"
    if name == "interfaces": return "contracts"
    if name in {"policies", "modeling", "model_catalog", "framework"}: return "models"
    if name in {"learning", "training_pipeline"}: return "learning"
    if name in {"metrics", "measurements", "comparison", "cohort_survival", "timeline", "visualization", "export_jobs", "ontology_export"}: return "analysis"
    if name == "faults": return "verification"
    return "application"


def visibility(name):
    return "+" if not name.startswith("_") or name.startswith("__") and name.endswith("__") else "-" if name.startswith("__") else "#"


def compact(text, length=66):
    value = " ".join(str(text).split())
    return value if len(value) <= length else value[:length-1] + "…"


def module_name(path):
    parts = list(Path(path).with_suffix("").parts)
    if parts[0] == "src": parts.pop(0)
    if parts[-1] == "__init__": parts.pop()
    return ".".join(parts)


def python_inventory(path):
    relative = str(path.relative_to(ROOT)); tree = ast.parse(path.read_text())
    module = module_name(relative); package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    imports = {}
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            for alias in item.names: imports[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(item, ast.ImportFrom):
            prefix = package.split(".")[:len(package.split("."))-item.level+1] if item.level else []
            target = ".".join([*prefix, *([item.module] if item.module else [])])
            for alias in item.names: imports[alias.asname or alias.name] = target + "." + alias.name
    result = []

    class Visitor(ast.NodeVisitor):
        scope = []

        def visit_FunctionDef(self, item):
            self.scope.extend((item.name, "<locals>")); self.generic_visit(item); self.scope[-2:] = []
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, item):
            qualname = ".".join([*self.scope, item.name]); bases = [ast.unparse(base) for base in item.bases]
            decorators = [ast.unparse(d) for d in item.decorator_list]
            kind = "protocol" if "Protocol" in bases else "dataclass" if any("dataclass" in d for d in decorators) else "class"
            if any("abstractmethod" in ast.unparse(d) for method in item.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) for d in method.decorator_list): kind = "abstract class"
            attributes = {}; methods = []
            def attr(name, annotation="", line=None, role="instance"):
                old = attributes.get(name)
                if old and (old["type"] or not annotation): return
                attributes[name] = {"name": name, "type": annotation, "visibility": visibility(name), "line": line or item.lineno, "role": role}
            for child in item.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    attr(child.target.id, ast.unparse(child.annotation), child.lineno, "instance" if kind == "protocol" or any("dataclass" in d for d in decorators) else "class")
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name): attr(target.id, "", child.lineno, "class")
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
                decs = [ast.unparse(d) for d in child.decorator_list]
                if "property" in decs or "cached_property" in decs:
                    attr(child.name, ast.unparse(child.returns) if child.returns else "", child.lineno, "read-only property")
                else:
                    methods.append({"name": child.name, "signature": child.name + "(" + ast.unparse(child.args) + ")" + (" -> " + ast.unparse(child.returns) if child.returns else ""),
                                    "visibility": visibility(child.name), "line": child.lineno, "decorators": decs, "async": isinstance(child, ast.AsyncFunctionDef), "doc": ast.get_docstring(child) or ""})
                argtypes = {a.arg: ast.unparse(a.annotation) for a in [*child.args.posonlyargs, *child.args.args, *child.args.kwonlyargs] if a.annotation}
                class Fields(ast.NodeVisitor):
                    def visit_ClassDef(self, nested): pass
                    def field(self, target, value=None, annotation=None):
                        if isinstance(target, (ast.Tuple, ast.List)):
                            for element in target.elts: self.field(element)
                        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                            inferred = ast.unparse(annotation) if annotation else argtypes.get(value.id, "") if isinstance(value, ast.Name) else ""
                            attr(target.attr, inferred, getattr(target, "lineno", child.lineno))
                    def visit_Assign(self, assignment):
                        for target in assignment.targets: self.field(target, assignment.value)
                        self.generic_visit(assignment)
                    def visit_AnnAssign(self, assignment):
                        self.field(assignment.target, assignment.value, assignment.annotation); self.generic_visit(assignment)
                for statement in child.body: Fields().visit(statement)
            if any("frozen=True" in decorator for decorator in decorators):
                for attribute in attributes.values(): attribute["readonly"] = True
            result.append({"id": relative + "::" + qualname, "path": relative, "module": module, "name": item.name, "qualname": qualname,
                           "language": "Python", "kind": kind, "line": item.lineno, "end_line": item.end_lineno, "group": category(relative),
                           "doc": ast.get_docstring(item) or "", "bases": bases, "imports": imports, "attributes": list(attributes.values()), "methods": methods,
                           "decorators": decorators, "nested": bool(self.scope), "external": False})
            self.scope.append(item.name); self.generic_visit(item); self.scope.pop()
    Visitor().visit(tree)
    return result


def typescript_inventory(paths):
    program = r'''
const ts=require(process.argv[1]),fs=require('node:fs');
const files=JSON.parse(fs.readFileSync(0,'utf8')),rows=[];
const has=(node,kind)=>!!node.modifiers?.some(m=>m.kind===kind);
const vis=node=>has(node,ts.SyntaxKind.PrivateKeyword)||node.name?.kind===ts.SyntaxKind.PrivateIdentifier?'-':has(node,ts.SyntaxKind.ProtectedKeyword)?'#':'+';
for(const file of files){
 const tree=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true,file.endsWith('.tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS),imports={};
 const text=node=>node?node.getText(tree):'';
 const line=node=>tree.getLineAndCharacterOfPosition(node.getStart(tree)).line+1;
 for(const statement of tree.statements){
  if(!ts.isImportDeclaration(statement)||!statement.importClause)continue;
  const from=statement.moduleSpecifier.text,clause=statement.importClause;
  if(clause.name)imports[clause.name.text]={module:from,symbol:'default'};
  if(clause.namedBindings&&ts.isNamedImports(clause.namedBindings))for(const e of clause.namedBindings.elements)imports[e.name.text]={module:from,symbol:e.propertyName?.text||e.name.text};
 }
 function visit(item,scope=[]){
  if((ts.isClassDeclaration(item)||ts.isInterfaceDeclaration(item))&&item.name){
   const name=item.name.text,qualname=[...scope,name].join('.'),attributes=[],methods=[],bases=[];
   const operation=(member,fn,method)=>({name:method,signature:method+(member.questionToken?'?':'')+'('+fn.parameters.map(p=>text(p)).join(', ')+')'+(fn.type?': '+text(fn.type):''),visibility:vis(member),line:line(member),decorators:[],async:has(fn,ts.SyntaxKind.AsyncKeyword),static:has(member,ts.SyntaxKind.StaticKeyword),abstract:has(member,ts.SyntaxKind.AbstractKeyword),optional:!!member.questionToken,doc:''});
   for(const member of item.members){
    const name=ts.isConstructorDeclaration(member)?'constructor':text(member.name);
    if(ts.isMethodDeclaration(member)||ts.isMethodSignature(member)||ts.isConstructorDeclaration(member))methods.push(operation(member,member,name));
    else if((ts.isPropertyDeclaration(member)||ts.isPropertySignature(member))&&member.initializer&&(ts.isArrowFunction(member.initializer)||ts.isFunctionExpression(member.initializer)))methods.push({...operation(member,member.initializer,name),role:'callable property'});
    else if(ts.isGetAccessor(member)||ts.isSetAccessor(member)||ts.isPropertyDeclaration(member)||ts.isPropertySignature(member))attributes.push({name,type:text(member.type),visibility:vis(member),line:line(member),role:ts.isGetAccessor(member)?'read-only property':'instance',optional:!!member.questionToken,readonly:has(member,ts.SyntaxKind.ReadonlyKeyword)||ts.isGetAccessor(member),static:has(member,ts.SyntaxKind.StaticKeyword)});
    if(ts.isConstructorDeclaration(member))for(const p of member.parameters){
     if(p.modifiers?.some(m=>[ts.SyntaxKind.PrivateKeyword,ts.SyntaxKind.ProtectedKeyword,ts.SyntaxKind.PublicKeyword,ts.SyntaxKind.ReadonlyKeyword].includes(m.kind)))attributes.push({name:text(p.name),type:text(p.type),visibility:vis(p),line:line(p),role:'constructor property',optional:!!p.questionToken,readonly:has(p,ts.SyntaxKind.ReadonlyKeyword)});
    }
   }
   for(const heritage of item.heritageClauses||[])for(const type of heritage.types)bases.push({expression:text(type.expression),kind:heritage.token===ts.SyntaxKind.ImplementsKeyword?'realization':'inheritance'});
   rows.push({path:file,name,qualname,language:'TypeScript',kind:ts.isInterfaceDeclaration(item)?'interface':item.modifiers?.some(m=>m.kind===ts.SyntaxKind.AbstractKeyword)?'abstract class':'class',line:line(item),end_line:tree.getLineAndCharacterOfPosition(item.end).line+1,doc:ts.getJSDocCommentsAndTags(item).map(text).join('\n'),attributes,methods,bases,imports,nested:scope.length>0,external:false});
   ts.forEachChild(item,child=>visit(child,[...scope,name]));return;
  }
  ts.forEachChild(item,child=>visit(child,scope));
 }
 visit(tree);
}
process.stdout.write(JSON.stringify(rows));
'''
    process = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), "-e", program, str(ROOT / "gui/node_modules/typescript")],
                             input=json.dumps([str(p) for p in paths]), text=True, capture_output=True, check=True)
    rows = json.loads(process.stdout)
    for row in rows:
        row["path"] = str(Path(row["path"]).relative_to(ROOT)); row["id"] = row["path"] + "::" + row["qualname"]
        row["module"] = row["path"]; row["group"] = category(row["path"])
    return rows


def inventory():
    paths = sorted({p for folder in SOURCE_ROOTS for p in (ROOT / folder).rglob("*") if p.suffix in (".py", ".ts", ".tsx")
                    and not any(part.startswith(".") or part in ("__pycache__", "node_modules", "static", "dist") for part in p.relative_to(ROOT).parts)})
    # Include Python browser harnesses and JS tooling in the source coverage list.
    paths += sorted((ROOT / "gui").glob("*.py"))
    rows = [row for path in paths if path.suffix == ".py" for row in python_inventory(path)]
    rows += typescript_inventory([p for p in paths if p.suffix in (".ts", ".tsx")])
    return sorted(rows, key=lambda row: row["id"]), paths


def inheritance(rows):
    by_id = {r["id"]: r for r in rows}; by_name = defaultdict(list); by_fullname = {}
    for row in rows:
        by_name[row["name"]].append(row)
        by_fullname[row["module"] + "." + row["qualname"]] = row
    externals = {}; edges = []
    def resolve(row, expression):
        name = re.sub(r"\[.*|<.*", "", expression)
        if name in ("object", "ABC", "Protocol", "Generic"): return None
        same = [r for r in by_name.get(name, []) if r["path"] == row["path"] and r["id"] != row["id"]]
        if len(same) == 1: return same[0]["id"]
        if same:
            enclosing = row["qualname"].rsplit(".", 1)[0]
            scoped = [r for r in same if r["qualname"].rsplit(".", 1)[0] == enclosing]
            if len(scoped) == 1: return scoped[0]["id"]
        qualified = name; first = name.split(".")[0]
        if row["language"] == "TypeScript" and first in row["imports"]:
            imp = row["imports"][first]
            target = (ROOT / row["path"]).parent / imp["module"]
            for suffix in (".ts", ".tsx", "/index.ts"):
                candidate = Path(str(target) + suffix).resolve()
                if candidate.is_relative_to(ROOT):
                    key = str(candidate.relative_to(ROOT)) + "::" + imp["symbol"]
                    if key in by_id: return key
            qualified = imp["module"] + "." + imp["symbol"]
        elif row["language"] == "Python":
            if first in row["imports"]: qualified = row["imports"][first] + name[len(first):]
            if qualified in by_fullname: return by_fullname[qualified]["id"]
            # The optional environment bases are deliberately conditional.
            optional = {"_GymBase": "gymnasium.Env | object (optional)", "_AECBase": "pettingzoo.AECEnv | object (optional)", "nn.Module": "torch.nn.Module"}
            qualified = optional.get(name, qualified)
        if len(by_name.get(name, [])) == 1: return by_name[name][0]["id"]
        identifier = "external::" + qualified
        externals.setdefault(identifier, {"id": identifier, "name": qualified, "qualname": qualified, "path": "", "line": 0,
                                         "language": "External", "group": "external", "kind": "external base", "doc": "Referenced base class supplied by Python or an optional library; not a project implementation.",
                                         "external": True, "attributes": [], "methods": [], "bases": []})
        return identifier
    for row in rows:
        for base in row["bases"]:
            expression = base["expression"] if isinstance(base, dict) else base
            target = resolve(row, expression)
            if target:
                edges.append({"source": row["id"], "target": target, "kind": base.get("kind", "inheritance") if isinstance(base, dict) else "inheritance",
                              "label": "", "evidence": row["path"] + ":" + str(row["line"]), "origin": "AST", "base_expression": expression})
    return list(externals.values()), edges


def symbol_id(value): return "c" + hashlib.sha256(value.encode()).hexdigest()[:14]


def display_method(method):
    signature = method["signature"]
    signature = re.sub(r"\(self,?\s*|\(cls,?\s*", "(", signature)
    suffix = " {static}" if method.get("static") or "staticmethod" in method.get("decorators", []) else " {class method}" if "classmethod" in method.get("decorators", []) else ""
    return method["visibility"] + " " + compact(signature) + suffix


def label(row, mode="detail", boundary=False):
    color = "#f4f5f7" if row["external"] or boundary else COLORS.get(row["group"], "#edf2f7")
    stereotype = row["kind"] + (" · boundary reference" if boundary else "")
    title = "<BR/>".join(escape(part) for part in textwrap.wrap(row["name"], 42))
    table = f'<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6" COLOR="#93a7bb"><TR><TD BGCOLOR="{color}"><FONT POINT-SIZE="10">«{escape(stereotype)}»</FONT><BR/><B>{title}</B>'
    if row.get("path"): table += '<BR/><FONT POINT-SIZE="9">' + escape(Path(row["path"]).name) + ":" + str(row["line"]) + '</FONT>'
    table += '</TD></TR>'
    if not row["external"] and not boundary:
        fields = row["attributes"]
        operations = sorted(row["methods"], key=lambda m: (m["name"] not in ("__init__", "constructor"), m["visibility"] != "+", m["line"]))
        field_limit, method_limit = (2, 3) if mode == "compact" else (5, 7)
        field_lines = [a["visibility"] + " " + a["name"] + ("?" if a.get("optional") else "") + (": " + a["type"] if a["type"] else "") + (" {readOnly}" if a.get("readonly") or a.get("role") == "read-only property" else "") for a in fields[:field_limit]]
        op_lines = [display_method(m) for m in operations[:method_limit]]
        if len(fields) > field_limit: field_lines.append(f"… {len(fields)-field_limit} more attributes")
        if len(operations) > method_limit: op_lines.append(f"… {len(operations)-method_limit} more operations")
        for lines in (field_lines or ["—"], op_lines or ["—"]):
            table += '<HR/><TR><TD ALIGN="LEFT">' + '<BR ALIGN="LEFT"/>'.join(escape(compact(line)) for line in lines) + '</TD></TR>'
    return table + '</TABLE>'


def diagram(name, selected, rows, relationships, *, mode="detail", boundary=True, cluster=False):
    by_id = {r["id"]: r for r in rows}; own = set(selected)
    edges = [r for r in relationships if r["source"] in own and r["target"] in own]
    if boundary:
        edges += [r for r in relationships if (r["source"] in own) != (r["target"] in own)
                  and r["kind"] in ("inheritance", "realization", "composition", "aggregation", "association")]
    included = own | {r[key] for r in edges for key in ("source", "target")}
    lines = ['digraph classes {', 'rankdir=TB;', 'graph [bgcolor="transparent", pad="0.25", nodesep="0.4", ranksep="0.75", fontname="DejaVu Sans", fontsize=16, compound=true, newrank=true];',
             'node [shape=plain, fontname="DejaVu Sans", fontsize=11];',
             'edge [fontname="DejaVu Sans", fontsize=9, color="#536c85", fontcolor="#344f69", arrowsize=0.8];']
    def add_nodes(ids):
        for key in sorted(ids):
            row = by_id[key]; attrs = {"id": symbol_id(key), "URL": "#" + symbol_id(key), "tooltip": key, "target": "_top"}
            lines.append(symbol_id(key) + ' [label=<' + label(row, mode, key not in own) + '>, ' + ', '.join(k+'='+json.dumps(v, ensure_ascii=False) for k,v in attrs.items()) + '];')
    if cluster:
        for group in [*GROUPS, "external"]:
            ids = {key for key in included if by_id[key]["group"] == group}
            if not ids: continue
            lines.append('subgraph cluster_' + group + ' { label=' + json.dumps(GROUPS.get(group, "External bases")) + '; color="#cbd5e1"; style="rounded";')
            add_nodes(ids); lines.append('}')
    else: add_nodes(included)
    for relation in edges:
        kind = relation["kind"]
        attrs = {"tooltip": (relation.get("label", "") + " | " + relation.get("evidence", "") + " | " + relation.get("note", "")).strip(" |")}
        if kind in ("inheritance", "realization"):
            attrs.update(arrowhead="empty", style="dashed" if kind == "realization" else "solid", label="«structural»" if kind == "realization" and relation.get("origin") != "AST" else "")
        elif kind in ("composition", "aggregation"):
            attrs.update(dir="both", arrowtail="diamond" if kind == "composition" else "odiamond", arrowhead="none", label=relation.get("label", ""))
        else: attrs.update(arrowhead="vee", style="dashed" if kind == "dependency" else "solid", label=relation.get("label", ""))
        if kind in ("composition", "aggregation", "association"):
            attrs.update(headlabel=relation.get("target_multiplicity", ""), labeldistance="1.7")
        lines.append(symbol_id(relation["source"]) + ' -> ' + symbol_id(relation["target"]) + ' [' + ', '.join(k+'='+json.dumps(v,ensure_ascii=False) for k,v in attrs.items()) + '];')
    lines.append('}'); dot = "\n".join(lines) + "\n"
    (OUT / (name + ".dot")).write_text(dot)
    rendered = subprocess.run(['dot', '-Tsvg', str(OUT / (name + '.dot')), '-o', str(OUT / (name + '.svg'))], text=True, capture_output=True)
    if rendered.returncode:
        raise RuntimeError(f"Graphviz failed for {name}: {rendered.stderr}")
    svg = (OUT / (name + '.svg')).read_text(); svg = svg[svg.index('<svg'):]
    return {"svg": svg, "classes": len(own), "boundary_classes": len(included-own), "relationships": len(edges), "name": name}


CSS = '''*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#162d43;font:15px/1.55 system-ui,sans-serif}header{padding:25px 30px 17px;background:#fff;border-bottom:1px solid #ccd9e5}h1{font-size:30px;margin:3px 0 9px;line-height:1.2}h2{font-size:21px}h3{margin-top:24px}a{color:#12609d}header p{max-width:1200px;margin:9px 0}.eyebrow{font-size:11px;letter-spacing:.13em;font-weight:700;text-transform:uppercase;color:#4b6680}.layout{display:grid;grid-template-columns:minmax(0,1fr) 370px;gap:16px;padding:18px}main,aside{min-width:0}.toolbar,.inspector,.legend{padding:15px;background:white;border:1px solid #cedbe7;border-radius:10px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}select,input,button{font:inherit}select,button,input[type=search]{border:1px solid #a8bed1;border-radius:6px;padding:7px;background:white;color:#16324a}select{max-width:100%}button{cursor:pointer}.toolbar label{font-size:13px}.toolbar input[type=range]{width:120px}.meta{padding:9px 2px;font-size:13px;color:#526b82}.canvas{height:72vh;min-height:480px;overflow:auto;background:white;border:1px solid #cedbe7;border-radius:10px;padding:18px}.canvas svg{display:block;width:100%;height:auto;min-width:1050px}.canvas .node{cursor:pointer}.canvas .node.selected polygon{stroke:#df7400;stroke-width:3px}.inspector{max-height:84vh;overflow:auto;position:sticky;top:12px;overflow-wrap:anywhere}.legend{margin-top:14px}.legend ul{display:flex;gap:17px;list-style:none;padding:0;flex-wrap:wrap;font-size:13px}.tag{display:inline-block;padding:2px 7px;background:#e7eff6;border-radius:4px;font-size:12px}.results{list-style:none;padding:0;max-height:190px;overflow:auto}.results button{width:100%;text-align:left;border:0;border-bottom:1px solid #e2eaf2;border-radius:0;font-size:13px;padding:7px}.results small{color:#526b82;display:block}.member{border-bottom:1px solid #e5edf4;padding:7px 0;font:12px/1.6 ui-monospace,monospace}.note{font-size:13px;color:#526b82}.full{width:100%}#details:focus{outline:2px solid #266a9b}.rel{margin:9px 0;padding:8px;background:#f5f8fb;border-radius:5px;font-size:13px}.rel a{cursor:pointer}code{font-family:ui-monospace,monospace;font-size:.88em}.empty{color:#61758a}.key{display:inline-flex;gap:5px;align-items:center}.key svg{width:52px;height:18px}footer{padding:15px 30px;color:#526b82;font-size:13px}@media(max-width:1050px){.layout{grid-template-columns:1fr}.inspector{position:static;max-height:none}.canvas{height:65vh}.canvas svg{min-width:950px}}@media print{.toolbar,.inspector,footer{display:none}.layout{display:block}.canvas{height:auto;overflow:visible;border:0}.canvas svg{min-width:0}}'''


def html_atlas(rows, relations, diagrams, coverage):
    public_rows = [{**row, "svg_id": symbol_id(row["id"])} for row in rows]
    payload = json.dumps({"rows":public_rows,"relations":relations,"diagrams":diagrams,"coverage":coverage}, ensure_ascii=False).replace("</", "<\\/")
    options = [("overview", "Start here · core class overview"), ("application-all", "All implementation classes and contracts"), ("whole-project", "Entire project · including tests and examples")]
    options += [(group, title) for group,title in GROUPS.items() if group in diagrams]
    options_html = "".join('<option value="'+value+'">'+escape(text)+'</option>' for value,text in options)
    legend = '''<ul><li>△ Solid line: inherits</li><li>△ Dashed line: implements / structural contract</li><li>◆ Filled diamond at owner: composition</li><li>◇ Hollow diamond: shared/injected aggregation</li><li>→ Solid line: association</li><li>⇢ Dashed line: dependency</li></ul>'''
    body = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Zombie Simulation · UML class atlas</title><style>'''+CSS+'''</style><body>
<header><div class="eyebrow">Zombie Simulation · complete class diagram</div><h1>Classes, contracts and ownership</h1><p>Choose the whole-project view or a subsystem. Click a class to inspect <strong>all declared attributes and operations</strong>, relationships, and its source location. Search includes nested and test classes.</p><p class="note">Boxes show a compact selection of members; the inspector contains the full extracted list. Inherited members remain on their defining base class. React function components and type aliases are not classes. External libraries are boundary references.</p><a href="../CLASS_DIAGRAM.md">Reading guide</a> · <a href="../architecture/index.html">Architecture flow diagrams</a> · <a href="class-model.json">Complete machine-readable model</a></header>
<div class="layout"><main><div class="toolbar"><label>Diagram <select id="diagram">'''+options_html+'''</select></label><label>Zoom <input id="zoom" type="range" min="1" max="200" step="1" value="100"><span id="zoomLabel">100%</span></label><button id="fit">Fit whole diagram</button><button id="readable">Readable size</button><a id="svgLink" href="overview.svg">Open SVG</a><a id="dotLink" href="overview.dot">Editable DOT</a></div><div class="meta" id="meta"></div><div class="canvas" id="canvas" aria-label="UML class diagram"></div><section class="legend"><strong>UML notation</strong>'''+legend+'''<p class="note">Multiplicity labels describe targets per source instance: 0..1 optional, 1 required, * multiple. Inverse uniqueness is not asserted. Structural realization means signature-reviewed duck typing, not an explicit base declaration. Ownership notes in the inspector explain injection and process boundaries. + public; # Python underscore/protected convention; − private. Blank compartments mean no own members found, not an absence of inherited behavior.</p></section></main>
<aside><section class="inspector"><label for="search"><strong>Find a class or interface</strong></label><input class="full" id="search" type="search" placeholder="Simulation, RunWorker, ExactTime…"><div class="meta" id="counts"></div><ul class="results" id="results"></ul><div id="details" tabindex="-1"><h2>Select a class</h2><p>Click any class box or search result. The details show its complete declared members and evidence for relationships.</p></div></section></aside></div><footer>Generated by scripts/build_class_diagrams.py from Python and TypeScript ASTs plus reviewed relationships. No simulation behavior is changed by generating these diagrams.</footer>
<script type="application/json" id="model">'''+payload+'''</script><script>
const model=JSON.parse(document.querySelector('#model').textContent),byId=new Map(model.rows.map(r=>[r.id,r])),bySvg=new Map(model.rows.map(r=>[r.svg_id,r]));
const selector=document.querySelector('#diagram'),canvas=document.querySelector('#canvas'),zoom=document.querySelector('#zoom'),details=document.querySelector('#details');let selected;let bootstrapping=true;
const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
function scale(value){const svg=canvas.querySelector('svg');zoom.value=String(Math.max(1,Math.round(value)));document.querySelector('#zoomLabel').textContent=Math.round(value)+'%';svg.style.minWidth='0';svg.style.width=(svg.viewBox.baseVal.width*value/100)+'px';}
function center(node){if(!node)return;const r=node.getBoundingClientRect(),c=canvas.getBoundingClientRect();canvas.scrollTo({left:canvas.scrollLeft+r.left-c.left-(canvas.clientWidth-r.width)/2,top:canvas.scrollTop+r.top-c.top-(canvas.clientHeight-r.height)/2});}
function showDiagram(name){selector.value=name;const d=model.diagrams[name];canvas.innerHTML=d.svg;scale(100);canvas.scrollTo(0,0);document.querySelector('#meta').textContent=d.classes+' classes/contracts in this view · '+d.boundary_classes+' boundary references · '+d.relationships+' relationships. Readable native scale; scroll to explore or fit the whole diagram.';document.querySelector('#svgLink').href=name+'.svg';document.querySelector('#dotLink').href=name+'.dot';for(const node of canvas.querySelectorAll('.node')){node.setAttribute('tabindex','0');node.setAttribute('role','button');node.setAttribute('aria-label',bySvg.get(node.id)?.name||'Class');node.addEventListener('click',event=>{event.preventDefault();inspect(bySvg.get(node.id)?.id);});node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();inspect(bySvg.get(node.id)?.id);}});}if(selected){const node=canvas.querySelector('#'+byId.get(selected)?.svg_id);node?.classList.add('selected');center(node);}}
function inspect(id,navigate=false){const row=byId.get(id);if(!row)return;selected=id;if(navigate&&!canvas.querySelector('#'+row.svg_id)){showDiagram(model.diagrams[row.group]?row.group:'whole-project');}for(const n of canvas.querySelectorAll('.selected'))n.classList.remove('selected');const node=canvas.querySelector('#'+row.svg_id);node?.classList.add('selected');if(navigate)center(node);details.replaceChildren();details.append(el('h2',row.name),el('span',row.kind+' · '+row.language,'tag'));if(row.path){const source=el('a',row.path+':'+row.line);source.href='../../'+row.path;source.title='Open source file; line '+row.line;details.append(el('p'));details.lastChild.append(source);}if(row.nested)details.append(el('p','Nested definition: '+row.qualname,'note'));if(row.doc)details.append(el('p',row.doc,'note'));for(const [title,members] of [['Attributes and properties',row.attributes],['Declared operations',row.methods]]){details.append(el('h3',title+' ('+members.length+')'));if(!members.length)details.append(el('p','No own declarations. See base-class relationships.','empty'));for(const member of members){details.append(el('div',member.visibility+' '+(member.signature||member.name+(member.optional?'?':'')+(member.type?': '+member.type:''))+(member.static||member.decorators?.includes('staticmethod')?' {static}':'')+(member.decorators?.includes('classmethod')?' {class method}':'')+(member.readonly||member.role==='read-only property'?' {readOnly}':'')+(member.abstract||member.decorators?.includes('abstractmethod')?' {abstract}':'')+'  [line '+member.line+']','member'));}}const rels=model.relations.filter(r=>r.source===id||r.target===id);details.append(el('h3','Relationships ('+rels.length+')'));for(const r of rels){const other=byId.get(r.source===id?r.target:r.source),box=el('div',undefined,'rel'),link=el('a',other?.name||'External');link.href='#'+other.svg_id;link.onclick=e=>{e.preventDefault();inspect(other.id,true);};box.append(el('strong',(r.source===id?'→ ':'← ')+r.kind+' '),link);if(r.label)box.append(el('div',r.label));box.append(el('div',r.evidence||'AST declaration','note'));if(r.note)box.append(el('div',r.note,'note'));details.append(box);}if(!bootstrapping)history.replaceState(null,'','#'+row.svg_id);}
function search(){const term=document.querySelector('#search').value.toLowerCase(),list=document.querySelector('#results');list.replaceChildren();const score=r=>r.name.toLowerCase()===term?0:r.name.toLowerCase().startsWith(term)?1:2;const found=model.rows.filter(r=>!r.external&&[r.name,r.qualname,r.path,r.kind].some(x=>x.toLowerCase().includes(term))).sort((a,b)=>score(a)-score(b)||a.id.localeCompare(b.id));document.querySelector('#counts').textContent=found.length+' matching definitions / '+model.coverage.definitions+' total';for(const row of found.slice(0,100)){const item=el('li'),button=el('button',row.name+' · '+row.kind);button.append(el('small',row.path));button.onclick=()=>inspect(row.id,true);item.append(button);list.append(item);}if(found.length>100)list.append(el('li','Type to narrow these '+found.length+' results.','note'));}
selector.onchange=()=>showDiagram(selector.value);zoom.oninput=()=>scale(Number(zoom.value));document.querySelector('#fit').onclick=()=>{const vb=canvas.querySelector('svg').viewBox.baseVal;scale(100*Math.min((canvas.clientWidth-40)/vb.width,(canvas.clientHeight-40)/vb.height));canvas.scrollTo(0,0);};document.querySelector('#readable').onclick=()=>{scale(100);if(selected)center(canvas.querySelector('#'+byId.get(selected).svg_id));};document.querySelector('#search').oninput=search;showDiagram('overview');search();const initial=bySvg.get(location.hash.slice(1))||model.rows.find(r=>r.path==='src/zombie_sim/engine.py'&&r.name==='Simulation');if(initial){inspect(initial.id,false);center(canvas.querySelector('#'+initial.svg_id));}bootstrapping=false;addEventListener('load',()=>window.scrollTo(0,0),{once:true});
</script></body></html>'''
    (OUT / "index.html").write_text(body)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    project, paths = inventory(); externals, inherited = inheritance(project)
    reviewed = json.loads((OUT / "relationships.json").read_text())
    rows = project + externals; by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows), "Duplicate class identity"
    for relation in reviewed:
        assert relation["source"] in by_id, relation["source"]
        assert relation["target"] in by_id, relation["target"]
        relation.setdefault("origin", "reviewed source")
    relations = inherited + reviewed
    for row in project:
        if row["kind"] == "class" and (row["name"].endswith(("Error", "Mismatch", "Cancelled", "Unavailable", "Conflict")) or any(base in ("Exception", "RuntimeError", "ValueError") for base in row["bases"] if isinstance(base, str))): row["kind"] = "exception"
    coverage = {"definitions": len(project), "implementation_definitions": sum(row["group"] != "verification" for row in project), "verification_definitions": sum(row["group"] == "verification" for row in project),
                "by_language": dict(Counter(row["language"] for row in project)), "by_group": dict(Counter(row["group"] for row in project)),
                "by_kind": dict(Counter(row["kind"] for row in project)), "nested_definitions": [row["id"] for row in project if row["nested"]],
                "reviewed_relationships": len(reviewed), "declared_inheritance_and_implements": len(inherited), "external_base_references": len(externals),
                "source_files": {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
                "scope": "All named Python class declarations and TypeScript class/interface declarations in source roots; includes nested classes and verification code. External dependency implementations, historical artifacts, generated bundles, pure functions, anonymous runtime-generated types and TS type aliases are not project class definitions.", "source_roots": SOURCE_ROOTS}
    (OUT / "class-model.json").write_text(json.dumps({"coverage": coverage, "classes": rows, "relationships": relations}, indent=2, ensure_ascii=False) + "\n")
    overview_names = {"Simulation", "GameRuleSet", "ActionHandlerRegistry", "ActionHandler", "TransitionPlan", "StateCoordinator", "UnitOfWork", "WorldAggregate", "RuntimeState", "PersistenceBundle", "AtomicCommitPort", "HistoryQueryPort", "Agent", "AgentState", "HumanState", "ZombieState", "RoleDefinition", "RoleAssignment", "DomainEvent", "ActionIntent", "ActionOccurrence", "ScheduledTask"}
    overview = {row["id"] for row in project if row["name"] in overview_names and row["group"] != "verification"}
    diagrams = {"overview": diagram("overview", overview, rows, relations, mode="compact", boundary=False)}
    diagrams["application-all"] = diagram("application-all", {row["id"] for row in project if row["group"] not in ("verification", "examples")}, rows, relations, mode="compact", boundary=False, cluster=True)
    diagrams["whole-project"] = diagram("whole-project", {row["id"] for row in project}, rows, relations, mode="compact", boundary=True, cluster=True)
    for group in GROUPS:
        selected = {row["id"] for row in project if row["group"] == group}
        if selected: diagrams[group] = diagram(group, selected, rows, relations, boundary=True)
    html_atlas(rows, relations, diagrams, coverage)
    summary = {**{k:v for k,v in coverage.items() if k not in ("source_files", "nested_definitions")}, "diagrams": {name:{k:v for k,v in data.items() if k != "svg"} for name,data in diagrams.items()}}
    (OUT / "coverage.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    guide = ROOT / "docs/CLASS_DIAGRAM.md"
    if guide.exists():
        document = guide.read_text()
        for key, label in (("definitions", "class/interface definitions"),
                           ("declared_inheritance_and_implements", "declared inheritance/implementation edges"),
                           ("reviewed_relationships", "reviewed relationships")):
            document = re.sub(r"\*\*\d+ " + re.escape(label) + r"\*\*", f"**{coverage[key]} {label}**", document)
        guide.write_text(document)
    print(json.dumps({"definitions": len(project), "relationships": len(relations), "diagrams": len(diagrams), "output": str(OUT / "index.html")}))


if __name__ == "__main__": main()
