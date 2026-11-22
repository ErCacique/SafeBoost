"""Edición Técnico: licencia firmada que se comprueba sin internet, y marca personalizada.

Formato de la licencia (una línea de texto):  ST1.<datos>.<firma>
- datos: JSON en base64url con el titular (n), su correo (e, opcional), la edición (ed), la
  fecha de emisión (iat), la de caducidad (exp, null = perpetua) y un identificador (id).
- firma: Ed25519 de "ST1.<datos>" con la clave privada del autor (scripts/license_tool.py).

SafeTrim solo lleva la clave pública: nadie puede fabricar licencias sin la privada, y la
comprobación no envía nada a ningún sitio. Lo que desbloquea la licencia es la marca del técnico
en el informe para el cliente (nombre, contacto y logo); el resto del programa es igual.
"""

from __future__ import annotations

import base64
import binascii
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from core import ed25519
from core.constants import APP_HOME
from core.logger import get_logger

log = get_logger("license")

PREFIX = "ST1"
# Clave pública de ErCacique. La privada correspondiente nunca está en el repositorio.
PUBLIC_KEY = bytes.fromhex(
    "ae173df0850adcb20eca04c7d411c5adef5c287ad7fcf21ab1d29ff2b80a921a"  # gitleaks:allow (pública)
)
LICENSE_FILE = APP_HOME / "license.key"
BRANDING_FILE = APP_HOME / "branding.json"
LOGO_FILE = APP_HOME / "branding-logo"
EDITIONS = {"tecnico": "Técnico"}
MAX_LOGO_BYTES = 512 * 1024


class LicenseError(ValueError):
    pass


@dataclass(frozen=True)
class License:
    holder: str
    email: str
    edition: str
    issued: str
    expires: str | None
    license_id: str

    @property
    def edition_label(self) -> str:
        return EDITIONS.get(self.edition, self.edition)

    def expired(self, today: date | None = None) -> bool:
        if not self.expires:
            return False
        return (today or date.today()).isoformat() > self.expires


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def encode_license(payload: dict, private_seed: bytes) -> str:
    """Firma una licencia (solo en el equipo del autor, con scripts/license_tool.py)."""
    body = _b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    signed = f"{PREFIX}.{body}"
    return f"{signed}.{_b64encode(ed25519.sign(private_seed, signed.encode()))}"


def parse_license(text: str, public_key: bytes = PUBLIC_KEY, today: date | None = None) -> License:
    """Comprueba firma y caducidad. Lanza LicenseError con un motivo legible."""
    parts = "".join(text.split()).split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("No es una licencia de SafeTrim (debe empezar por ST1.)")
    try:
        signature = _b64decode(parts[2])
        payload = json.loads(_b64decode(parts[1]))
    except (binascii.Error, ValueError) as exc:
        raise LicenseError("La licencia está incompleta o mal copiada") from exc
    if not ed25519.verify(public_key, f"{parts[0]}.{parts[1]}".encode(), signature):
        raise LicenseError("La firma no es válida: la licencia está modificada o mal copiada")
    if not isinstance(payload, dict) or payload.get("ed") not in EDITIONS:
        raise LicenseError("Edición desconocida")
    lic = License(
        holder=str(payload.get("n", "")),
        email=str(payload.get("e", "")),
        edition=str(payload["ed"]),
        issued=str(payload.get("iat", "")),
        expires=payload.get("exp") or None,
        license_id=str(payload.get("id", "")),
    )
    if lic.expired(today):
        raise LicenseError(f"La licencia caducó el {lic.expires}")
    return lic


def load_license(path: Path = LICENSE_FILE) -> License | None:
    try:
        return parse_license(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    except LicenseError as exc:
        log.warning("license_invalid", extra={"err": str(exc)})
        return None


def save_license(text: str, path: Path = LICENSE_FILE) -> License:
    lic = parse_license(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(text.split()) + "\n", encoding="utf-8")
    log.info("license_saved", extra={"edition": lic.edition, "id": lic.license_id})
    return lic


def remove_license(path: Path = LICENSE_FILE) -> None:
    path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- marca


@dataclass
class Branding:
    business: str = ""
    contact: str = ""
    has_logo: bool = False

    @classmethod
    def load(cls, path: Path = BRANDING_FILE) -> Branding:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path = BRANDING_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    def logo_data_uri(self, logo: Path = LOGO_FILE) -> str:
        """Logo incrustado en el HTML del informe (sin archivos aparte)."""
        if not self.has_logo:
            return ""
        try:
            data = logo.read_bytes()
        except OSError:
            return ""
        mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def set_logo(source: Path, branding: Branding, logo: Path = LOGO_FILE) -> None:
    head = source.read_bytes()[:8]
    if not (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8")):
        raise LicenseError("El logo debe ser PNG o JPG")
    if source.stat().st_size > MAX_LOGO_BYTES:
        raise LicenseError("El logo ocupa más de 512 KB; usa una imagen más pequeña")
    logo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, logo)
    branding.has_logo = True
    branding.save()
