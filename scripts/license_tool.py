"""Emitir licencias de la edición Técnico (solo el autor, en su equipo).

    python scripts/license_tool.py issue --key RUTA_CLAVE_PRIVADA --name "Taller Pérez" \
        [--email cliente@ejemplo.com] [--days 365]
    python scripts/license_tool.py verify "ST1.xxxx.yyyy"
    python scripts/license_tool.py genkey RUTA   # cambiar de clave (docs/LICENCIAS.md)

La clave privada es un archivo con 64 caracteres hexadecimales. No la subas nunca al repositorio:
quien la tenga puede fabricar licencias.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ed25519
from core.license import LicenseError, encode_license, parse_license


def _read_seed(path: Path) -> bytes:
    try:
        seed = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"No se pudo leer la clave privada {path}: {exc}") from exc
    if len(seed) != 32:
        raise SystemExit("La clave privada debe tener 64 caracteres hexadecimales")
    return seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    issue = sub.add_parser("issue", help="emite una licencia")
    issue.add_argument("--key", type=Path, required=True)
    issue.add_argument("--name", required=True)
    issue.add_argument("--email", default="")
    issue.add_argument("--days", type=int, default=0, help="0 = perpetua")
    verify = sub.add_parser(
        "verify", help="comprueba una licencia con la clave pública de SafeBoost"
    )
    verify.add_argument("license")
    genkey = sub.add_parser("genkey", help="crea un par de claves nuevo")
    genkey.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "genkey":
        if args.path.exists():
            raise SystemExit(f"{args.path} ya existe: no se sobrescribe una clave")
        seed = os.urandom(32)
        args.path.write_text(seed.hex() + "\n", encoding="ascii")
        print(f"Clave privada guardada en {args.path}")
        print(
            f"Clave pública (ponla en core/license.py PUBLIC_KEY): {ed25519.public_key(seed).hex()}"
        )
        return 0
    if args.cmd == "verify":
        try:
            lic = parse_license(args.license)
        except LicenseError as exc:
            print(f"NO válida: {exc}")
            return 1
        print(
            f"Válida: {lic.holder} · edición {lic.edition_label} · caduca {lic.expires or 'nunca'}"
        )
        return 0

    seed = _read_seed(args.key)
    today = date.today()
    payload = {
        "n": args.name,
        "e": args.email,
        "ed": "tecnico",
        "iat": today.isoformat(),
        "exp": (today + timedelta(days=args.days)).isoformat() if args.days > 0 else None,
        "id": secrets.token_hex(6),
    }
    text = encode_license(payload, seed)
    try:
        parse_license(text)
    except LicenseError as exc:
        raise SystemExit(
            f"La clave privada no corresponde a la pública de SafeBoost: {exc}"
        ) from exc
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
