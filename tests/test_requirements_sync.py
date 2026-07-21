"""Guard: every third-party package imported under src/ must be declared
in requirements.txt, so a fresh server install (Docker) never crashes with
ModuleNotFoundError for a package that only existed on a developer machine.
"""

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"

# import name -> PyPI package name, where they differ
MODULE_TO_PACKAGE = {
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
    "PIL": "Pillow",
    "yaml": "PyYAML",
}

LOCAL_MODULES = {"src"}


def _src_imports() -> set:
    """Collect top-level module names imported anywhere under src/."""
    modules = set()
    for py_file in SRC_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def _declared_packages() -> set:
    """Parse requirements.txt into a set of normalized package names."""
    packages = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[=<>!\[; ]", line, maxsplit=1)[0]
        packages.add(name.lower().replace("_", "-"))
    return packages


def test_every_src_import_is_declared_in_requirements():
    stdlib = set(sys.stdlib_module_names)
    declared = _declared_packages()

    third_party = {
        mod for mod in _src_imports()
        if mod not in stdlib and mod not in LOCAL_MODULES and not mod.startswith("_")
    }
    missing = {
        mod for mod in third_party
        if MODULE_TO_PACKAGE.get(mod, mod).lower().replace("_", "-") not in declared
    }

    assert not missing, (
        f"src/ imports packages missing from requirements.txt: {sorted(missing)}. "
        "Add them so fresh installs (Docker/server) do not crash on startup."
    )
