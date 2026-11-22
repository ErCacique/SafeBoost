"""Los handlers de tweaks/ solo cambian el sistema a través de HandlerContext.

HandlerContext.set_registry, run_checked, run_tool y ps_run aplican la lista de protección,
guardan el snapshot para deshacer y respetan el dry-run. Un handler que llame directamente a
ctx.registry.write o ctx.runner.run se saltaría las tres cosas sin que ningún otro test lo
note, así que este test lo prohíbe analizando el código fuente.
"""

from __future__ import annotations

import ast
from pathlib import Path

TWEAKS_DIR = Path(__file__).resolve().parent.parent / "tweaks"

# Métodos de Registry que solo leen. Cualquier otro uso de ctx.registry (write,
# delete_value, delete_key_if_empty, o guardarlo en una variable) es una infracción.
REGISTRY_READ_METHODS = frozenset({"read", "subkeys", "key_exists", "values", "locate"})

# Funciones que pueden usar ctx.runner directamente, con el motivo. Añadir una entrada
# exige justificar que solo lee o que comprueba ctx.dry_run antes de ejecutar.
RUNNER_ALLOWED = {
    ("_common", "ps_json"): "consulta PowerShell de solo lectura (ConvertTo-Json)",
    ("_common", "ps_run"): "comprueba ctx.dry_run y planifica antes de ejecutar",
    ("power", "_active_scheme"): "powercfg /getactivescheme (lectura)",
    ("power", "_schemes"): "powercfg /list (lectura)",
    ("power", "_dc_value"): "powercfg /q (lectura)",
    ("gaming", "hags_supported"): "dxdiag /t a un archivo temporal (lectura)",
}

# Atributos del contexto que un handler no debe tocar: los servicios se cambian con
# operaciones declarativas del catálogo, que el motor protege y registra.
FORBIDDEN_ATTRS = frozenset({"services"})


def _handler_modules() -> list[Path]:
    return sorted(p for p in TWEAKS_DIR.glob("*.py") if p.name != "__init__.py")


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return "<módulo>"


def find_violations(source: str, module: str) -> list[str]:
    """Devuelve una línea legible por cada acceso indebido a ctx.registry/runner/services."""
    tree = ast.parse(source)
    parents = _parents(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "ctx"
        ):
            continue
        func = _enclosing_function(node, parents)
        where = f"tweaks/{module}.py:{node.lineno} en {func}()"
        if node.attr == "registry":
            method = parents.get(node)
            call = parents.get(method) if method is not None else None
            is_read_call = (
                isinstance(method, ast.Attribute)
                and method.attr in REGISTRY_READ_METHODS
                and isinstance(call, ast.Call)
                and call.func is method
            )
            if not is_read_call:
                used = method.attr if isinstance(method, ast.Attribute) else "acceso directo"
                found.append(f"{where}: ctx.registry ({used}); usa ctx.set_registry")
        elif node.attr == "runner" and (module, func) not in RUNNER_ALLOWED:
            found.append(f"{where}: ctx.runner; usa run_tool, ctx.run_checked o ps_run")
        elif node.attr in FORBIDDEN_ATTRS:
            found.append(f"{where}: ctx.{node.attr}; usa una operación del catálogo")
    return found


def test_handlers_only_change_the_system_through_the_context() -> None:
    violations: list[str] = []
    for path in _handler_modules():
        violations += find_violations(path.read_text(encoding="utf-8"), path.stem)
    assert not violations, "Accesos que se saltan protección, snapshot o dry-run:\n" + "\n".join(
        violations
    )


def test_handler_context_parameter_is_always_named_ctx() -> None:
    # El análisis anterior busca el nombre "ctx"; renombrar el parámetro lo esquivaría.
    offenders: list[str] = []
    for path in _handler_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                if not annotation.endswith("HandlerContext") or arg.arg == "ctx":
                    continue
                # "_ctx" marca un parámetro que no se usa; se acepta mientras siga sin usarse.
                used = any(
                    isinstance(n, ast.Name) and n.id == arg.arg
                    for stmt in node.body
                    for n in ast.walk(stmt)
                )
                if arg.arg != "_ctx" or used:
                    offenders.append(f"tweaks/{path.name}:{node.lineno} {node.name}({arg.arg})")
    assert not offenders, "Parámetros HandlerContext que no se llaman ctx:\n" + "\n".join(offenders)


def test_runner_allowlist_has_no_stale_entries() -> None:
    # Si una función de la lista blanca desaparece o deja de usar ctx.runner, se quita.
    used: set[tuple[str, str]] = set()
    for path in _handler_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = _parents(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "runner"
                and isinstance(node.value, ast.Name)
                and node.value.id == "ctx"
            ):
                used.add((path.stem, _enclosing_function(node, parents)))
    assert set(RUNNER_ALLOWED) <= used, f"Entradas obsoletas: {set(RUNNER_ALLOWED) - used}"


def test_detector_catches_bypasses() -> None:
    source = """
def bad(ctx):
    ctx.registry.write("HKLM", "X", "y", value)
    reg = ctx.registry
    ctx.registry.delete_value("HKLM", "X", "y")
    ctx.runner.run(["sc.exe", "stop", "x"])
    ctx.services.stop("x")

def good(ctx):
    ctx.registry.read("HKLM", "X", "y")
    ctx.set_registry("HKLM", "X", "y", value)
    ctx.run_checked(["powercfg"], "x")
"""
    violations = find_violations(source, "fake")
    assert len(violations) == 5
    assert all("bad()" in v for v in violations)
