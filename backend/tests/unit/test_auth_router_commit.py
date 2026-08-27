"""Router-level Auth-C1 regression tests.

Auth-C1: AuthService.login() and refresh() flush only — they do not commit.
The router MUST commit after the service returns, otherwise the RefreshToken
row is buffered in memory but never durable.

These tests use AST analysis on the router source to verify the
service.* call comes BEFORE session.commit() in source order.
"""

from __future__ import annotations

import ast
import inspect

from app.modules.auth import router as auth_router_module


def _function_ast(fn) -> ast.FunctionDef:
    """Return the AST FunctionDef node for a (sync or async) function."""
    src = inspect.getsource(fn)
    # textwrap to handle indented decorated functions
    import textwrap
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise AssertionError(f"no FunctionDef in {fn!r}")


def _service_call_lineno(fn_ast: ast.AST, service_method: str) -> int | None:
    """Return the line number (within the function) of the call to
    `service.<service_method>(...)`."""
    for node in ast.walk(fn_ast):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == service_method:
                return node.lineno
    return None


def _commit_call_lineno(fn_ast: ast.AST) -> int | None:
    """Return the line number of `session.commit()` (or `<x>.commit()`)."""
    for node in ast.walk(fn_ast):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "commit":
                return node.lineno
    return None


def test_login_router_calls_session_commit_after_service():
    """Auth-C1: router.login must call session.commit() AFTER service.login()."""
    fn_ast = _function_ast(auth_router_module.login)
    service_line = _service_call_lineno(fn_ast, "login")
    commit_line = _commit_call_lineno(fn_ast)
    assert service_line is not None, "router.login does not call service.login"
    assert commit_line is not None, (
        "Auth-C1 regression: router.login does not call session.commit()."
    )
    assert service_line < commit_line, (
        f"Auth-C1 regression: session.commit() (line {commit_line}) must be "
        f"called AFTER service.login() (line {service_line})."
    )


def test_refresh_router_calls_session_commit_after_service():
    """Auth-C1: router.refresh must call session.commit() AFTER service.refresh()."""
    fn_ast = _function_ast(auth_router_module.refresh)
    service_line = _service_call_lineno(fn_ast, "refresh")
    commit_line = _commit_call_lineno(fn_ast)
    assert service_line is not None and commit_line is not None
    assert service_line < commit_line, (
        f"Auth-C1 regression: session.commit() (line {commit_line}) must be "
        f"called AFTER service.refresh() (line {service_line})."
    )


def test_logout_router_calls_session_commit():
    """Auth-C1 sibling: logout revokes a token and must commit it."""
    fn_ast = _function_ast(auth_router_module.logout)
    commit_line = _commit_call_lineno(fn_ast)
    assert commit_line is not None, (
        "Auth-C1 regression: router.logout does not call session.commit()."
    )
