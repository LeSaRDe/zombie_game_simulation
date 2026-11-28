"""Import guards supplement, rather than replace, runtime port-isolation tests."""
import ast
from importlib.util import resolve_name
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/zombie_sim"


def imports(path):
    module = "zombie_sim." + ".".join(path.relative_to(SOURCE).with_suffix("").parts)
    package = module.rpartition(".")[0]
    if path.name == "__init__.py":
        package = module.removesuffix(".__init__")
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            for item in node.names:
                yield node.lineno, item.name
        elif isinstance(node, ast.ImportFrom):
            name = resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module or ""
            yield node.lineno, name


class DependencyBoundaryTests(unittest.TestCase):
    def test_OOP_ARCHITECTURE_domain_rules_and_state_use_ports_not_concrete_backends(self):
        forbidden = ("sqlite3", "zombie_sim.storage", "zombie_sim.engine", "zombie_sim.runtime",
                     "zombie_sim.application", "zombie_sim.http_api", "zombie_sim.export_jobs")
        violations = []
        for layer in ("domain_model", "game_rules", "state_management"):
            directory = SOURCE / layer
            self.assertTrue(directory.is_dir(), f"Required architecture layer is absent: {layer}")
            for path in sorted(directory.rglob("*.py")):
                for line, module in imports(path):
                    concrete = any(module == name or module.startswith(name + ".") for name in forbidden)
                    persistence = module.startswith("zombie_sim.persistence") and module != "zombie_sim.persistence.contracts"
                    if concrete or persistence:
                        violations.append(f"{path.relative_to(ROOT)}:{line}: {module}")
        self.assertEqual(violations, [], "Concrete infrastructure escaped its adapter boundary")

    def test_OOP_ARCHITECTURE_domain_rules_do_not_open_files_or_connections(self):
        violations = []
        for layer in ("domain_model", "game_rules"):
            for path in sorted((SOURCE / layer).rglob("*.py")):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "exec", "eval"}:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.id}")
                    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"connect", "read_bytes", "write_bytes", "read_text", "write_text"}:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.attr}")
        self.assertEqual(violations, [], "Rule/domain code cannot perform persistence or dynamic code loading")


if __name__ == "__main__":
    unittest.main()
