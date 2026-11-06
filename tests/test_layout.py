"""The rules that keep one copy of everything once radio.py is split into tfm/ (tfm/__init__.py):
nothing imports radio, the tfm modules are imported as modules and never by name, and each
top-level name is defined in one module only, the one a test patches."""

import ast
import unittest

from radio_test_support import code_files


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


class Layout(unittest.TestCase):
    def test_nothing_imports_radio(self):
        for f in code_files():
            for node in ast.walk(_tree(f)):
                if isinstance(node, ast.Import):
                    self.assertNotIn("radio", [a.name for a in node.names], f"{f.name}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "radio", f"{f.name}:{node.lineno}")

    def test_tfm_modules_are_imported_as_modules(self):
        mods = {f.stem for f in code_files()[1:]}
        for f in code_files():
            for node in ast.walk(_tree(f)):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tfm"):
                    self.assertEqual(node.module, "tfm", f"{f.name}:{node.lineno} imports names")
                    self.assertLessEqual({a.name for a in node.names}, mods, f"{f.name}:{node.lineno}")

    def test_each_name_is_defined_in_one_module(self):
        homes = {}
        for f in code_files():
            names = set()
            for node in _tree(f).body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        names |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
            for name in names:
                homes.setdefault(name, []).append(f.name)
        self.assertEqual({n: fs for n, fs in homes.items() if len(fs) > 1}, {})


if __name__ == "__main__":
    unittest.main()
