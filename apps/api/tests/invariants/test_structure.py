"""Structural invariants: layering, endpoints that must not exist, registries (02/B1, 02/A16, 02/B4).

Each check reports how much it examined and fails if it examined nothing (10/H18).
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

from skeleton_proof_e_next_ai.api.app import create_app
from skeleton_proof_e_next_ai.domain.work_items import State
from skeleton_proof_e_next_ai.jobs import handlers
from skeleton_proof_e_next_ai.jobs.registry import REGISTRY

from ..conftest import settings_for

PKG = "skeleton_proof_e_next_ai"
SRC = Path(__file__).resolve().parents[2] / "src" / PKG

# layer -> internal layers it must never import (02/B1: dependencies point inward).
FORBIDDEN: dict[str, set[str]] = {
    "domain": {
        "api",
        "application",
        "workflow",
        "persistence",
        "integrations",
        "intelligence",
        "retrieval",
        "jobs",
        "security",
        "telemetry",
        "config",
    },
    "workflow": {"api", "application", "persistence", "integrations", "intelligence", "retrieval", "jobs", "security"},
    "application": {"api", "persistence", "integrations", "intelligence", "retrieval", "jobs", "security", "config"},
    "persistence": {"api", "application"},
    "integrations": {"api", "application", "persistence"},
    # The product AI is an adapter that writes no business state (02 §7): it sees the domain, never the edges.
    "intelligence": {"api", "application", "persistence", "workflow", "integrations", "retrieval", "jobs", "security"},
    # Search is an engine behind the Retriever port: it sees the domain and its ports, never the edges or the model.
    "retrieval": {"api", "application", "persistence", "workflow", "integrations", "intelligence", "jobs", "security"},
    "security": {"api", "application"},
    "jobs": {"api"},
    "telemetry": {"api", "application", "domain", "persistence", "jobs", "security", "integrations"},
    "config": {"api", "application", "domain", "persistence", "jobs", "security", "integrations", "telemetry"},
}


def _imported_layers(path: Path) -> set[str]:
    rel_parts = path.relative_to(SRC).parts
    layers: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative: resolve against this module's package
                base = list(rel_parts[:-1])[: len(rel_parts) - 1 - (node.level - 1)]
                target = [*base, *(node.module.split(".") if node.module else [])]
                if target:
                    layers.add(target[0])
                elif node.names:
                    layers.update(alias.name for alias in node.names)
            elif node.module and node.module.split(".")[0] == PKG:
                parts = node.module.split(".")
                if len(parts) > 1:
                    layers.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == PKG and len(parts) > 1:
                    layers.add(parts[1])
    return layers


def test_dependencies_point_inward() -> None:
    violations, examined = [], 0
    for path in sorted(SRC.rglob("*.py")):
        layer = path.relative_to(SRC).parts[0]
        if layer not in FORBIDDEN:
            continue
        examined += 1
        bad = _imported_layers(path) & FORBIDDEN[layer]
        if bad:
            violations.append(f"{path.relative_to(SRC)} ({layer}) imports {sorted(bad)}")
    print(f"layering: examined {examined} modules")
    assert examined >= 20, f"the layering test examined only {examined} modules; it is not seeing the code"
    assert not violations, "\n".join(violations)


# Every module that uses regular expressions, and why none of them reads a decision out of model prose (04 §8: "a
# regex over model prose fails a correct row"). A model's answer is read from its validated schema fields; a pattern
# may only refuse or raise risk (04/P4). A new entry needs a reason a reviewer can check.
REGEX_ALLOWED: dict[str, str] = {
    "persistence/db.py": "validates database role names from settings",
    "config/production.py": "checks the deployed build SHA's form in settings (07/O4)",
    "intelligence/agents.py": "checks prompt-variable values before a call",
    "intelligence/defence.py": "screens untrusted input before a call; it can only block or flag (04/P4)",
    "intelligence/validation.py": "finds links in output to refuse unlisted hosts; it can only reject (05/SG5)",
    "intelligence/mcp.py": "checks configured server and tool names",
    "intelligence/providers/embedding.py": "the fake embedder hashes the words of text a person added",
    "retrieval/chunking.py": "splits documents a person added, never model output",
}


def _uses_regex(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in {"re", "regex"} for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {"re", "regex"}:
            return True
    return False


def test_no_decision_is_read_out_of_model_prose() -> None:
    users, examined = set(), 0
    for path in SRC.rglob("*.py"):
        examined += 1
        if _uses_regex(ast.parse(path.read_text())):
            users.add(path.relative_to(SRC).as_posix())
    print(f"prose scanning: examined {examined} modules, {len(users)} use regular expressions")
    assert examined >= 20, f"the prose-scanning guard examined only {examined} modules; it is not seeing the code"
    unexplained = sorted(users - set(REGEX_ALLOWED))
    assert not unexplained, (
        f"{unexplained} use regular expressions without a reason in REGEX_ALLOWED. Read a model's answer from its "
        "schema fields, never by scanning its prose (04/P3); a pattern that only refuses can be listed with why"
    )


def test_endpoints_that_must_not_exist(tmp_path: Path) -> None:
    """02/A16: no client-writable state field, no bulk decisions, no route that runs model-written SQL."""
    spec = create_app(settings_for(tmp_path, tmp_path / "jwks.json")).openapi()
    routes = [(method.upper(), path) for path, ops in spec["paths"].items() for method in ops]
    assert len(routes) >= 10, f"the check must see the API's routes, not just the docs routes: {routes}"
    for method, path in routes:
        assert method != "PATCH", f"{method} {path}: state changes are named commands, never PATCH (02/A1)"
        for word in ("bulk", "sql", "raw-query", "execute"):
            assert word not in path, f"{method} {path} must not exist (02/A16)"


def test_the_worker_can_be_started() -> None:
    """Built is not reachable until something runs it (10/H18): `make worker` runs this module's main."""
    worker = importlib.import_module(f"{PKG}.jobs.__main__")
    assert callable(getattr(worker, "main", None)), "jobs/__main__.py must define main()"
    makefile = (SRC.parents[3] / "Makefile").read_text()
    assert f"python -m {PKG}.jobs" in makefile, "make worker must run the worker module"


def test_every_handler_module_registers_something() -> None:
    modules = [m.name for m in pkgutil.iter_modules(handlers.__path__)]
    assert modules, "no handler modules found"
    assert sorted(modules) == sorted(handlers.MODULES), "a handler module on disk is not listed in handlers.MODULES"
    for name in modules:
        mod = importlib.import_module(f"{handlers.__name__}.{name}")
        assert getattr(mod, "KINDS", None), f"handler module {name} registers no job kinds (02/B4)"
        assert set(mod.KINDS) <= REGISTRY.kinds


def test_every_event_the_slice_publishes_has_a_handler() -> None:
    source = (SRC / "application" / "work_items.py").read_text()
    assert '"work_item.created"' in source
    published = {"work_item.created"} | {f"work_item.{s.value}" for s in State if s is not State.DRAFT}
    assert published <= REGISTRY.kinds, f"events without a handler: {sorted(published - REGISTRY.kinds)}"
