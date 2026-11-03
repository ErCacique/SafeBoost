"""Valida data/tweaks.json: esquema JSON, reglas de coherencia y handlers resolubles.

Uso: python scripts/validate_tweaks.py [ruta]   (código de salida 1 si hay errores)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from core.catalog import structural_errors  # noqa: E402
from core.context import HandlerError, resolve_handler  # noqa: E402

SCHEMA = ROOT / "data" / "tweaks.schema.json"
DEFAULT = ROOT / "data" / "tweaks.json"


def handler_refs(tweak: dict) -> list[str]:
    refs = [
        op["ref"]
        for key in ("apply", "revert", "detect")
        for op in tweak.get(key, [])
        if isinstance(op, dict) and op.get("op") == "handler"
    ]
    check = tweak.get("requires", {}).get("check")
    if check:
        refs.append(check)
    return refs


def validate(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: no se pudo leer: {exc}"]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<raíz>'}: {err.message}"
        for err in Draft202012Validator(schema).iter_errors(data)
    ]
    errors += structural_errors(data)
    for tweak in data.get("tweaks", []) if isinstance(data, dict) else []:
        for ref in handler_refs(tweak):
            try:
                resolve_handler(ref)
            except HandlerError as exc:
                errors.append(f"{tweak.get('id')}: {exc}")
    return errors


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    errors = validate(path)
    if errors:
        print(f"{path}: {len(errors)} error(es)")
        for error in errors:
            print(f"  - {error}")
        return 1
    count = len(json.loads(path.read_text(encoding="utf-8"))["tweaks"])
    print(f"{path}: OK ({count} tweaks)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
