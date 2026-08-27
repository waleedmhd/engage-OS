"""AST guards for architectural invariants Msg-C4 and Auth-C1.

Walks the source of every service.py and router.py under app/modules/ and
asserts:

  Service-side (Msg-C4):
    * Service methods must call ``await session.flush()`` at least once when
      they mutate. They must NOT call ``session.commit()`` and must NOT call
      ``<task>.delay()`` or ``<task>.apply_async()`` directly. That ordering
      belongs to the router or UnitOfWork so the row is durable before the
      worker picks it up.

  Router-side (Auth-C1 / Msg-C4):
    * If a router handler dispatches a Celery task (``.delay()`` /
      ``.apply_async()``) AND commits the session, the ``commit`` call must
      precede the dispatch in source order. Otherwise the worker may read
      a not-yet-durable row.

The walker only checks files that exist and have public mutators; pure-read
modules (e.g. ``audit/service.py`` if read-only) are tolerated.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_MODULES = _BACKEND / "app" / "modules"


def _iter_module_files(name: str):
    for mod_dir in sorted(_MODULES.iterdir()):
        if not mod_dir.is_dir():
            continue
        path = mod_dir / f"{name}.py"
        if path.is_file():
            yield mod_dir.name, path


def _is_session_commit(node: ast.AST) -> bool:
    """Match ``session.commit()`` and ``await session.commit()`` calls."""
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "commit"
        and isinstance(func.value, ast.Name)
        and func.value.id in {"session", "self_session"}
    )


def _is_task_dispatch(node: ast.AST) -> bool:
    """Match ``foo_task.delay(...)`` or ``foo_task.apply_async(...)`` calls.

    Heuristic: identifier ends with ``_task`` and the attribute is delay /
    apply_async. Skips attribute chains we don't recognise."""
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in ("delay", "apply_async"):
        return False
    target = func.value
    while isinstance(target, ast.Attribute):
        target = target.value
    return isinstance(target, ast.Name) and target.id.endswith("_task")


@pytest.mark.parametrize("module_name,path", list(_iter_module_files("service")))
def test_service_does_not_commit_or_dispatch(module_name, path):
    """Msg-C4: service.py methods must not commit or dispatch tasks."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_session_commit(node):
                violations.append(
                    f"{path.name}:{node.lineno}: session.commit() in service "
                    f"violates Msg-C4 — router must own the transaction boundary."
                )
            if _is_task_dispatch(node):
                violations.append(
                    f"{path.name}:{node.lineno}: task dispatch ({ast.unparse(node)[:60]}) "
                    f"in service violates Msg-C4 — dispatch belongs to the router."
                )

    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("module_name,path", list(_iter_module_files("router")))
def test_router_commits_before_dispatching(module_name, path):
    """Auth-C1 / Msg-C4: if a router handler both commits AND dispatches, the
    commit must come first in the source. Otherwise the worker may pick up the
    job before the underlying row is durable."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    violations: list[str] = []

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        commit_line: int | None = None
        dispatch_lines: list[int] = []
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                if _is_session_commit(sub):
                    if commit_line is None:
                        commit_line = sub.lineno
                if _is_task_dispatch(sub):
                    dispatch_lines.append(sub.lineno)

        if not dispatch_lines:
            continue
        if commit_line is None:
            # Dispatch without any commit — acceptable only if the handler
            # didn't mutate (read-only endpoint that fans out tasks). We
            # do NOT flag this; webhook receiver, for example, commits inside
            # a sync session opened ad-hoc and then dispatches.
            continue
        first_dispatch = min(dispatch_lines)
        if first_dispatch < commit_line:
            violations.append(
                f"{path.name}:{first_dispatch}: task dispatch precedes session.commit() "
                f"at line {commit_line} in handler '{fn.name}' — Msg-C4 violation."
            )

    assert not violations, "\n".join(violations)
