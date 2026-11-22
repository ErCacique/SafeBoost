"""Extensiones instaladas en los navegadores del usuario. Solo lee los archivos del perfil.

Chromium (Chrome, Edge, Brave, Opera): <perfil>/Extensions/<id>/<versión>/manifest.json, con el
nombre traducido en _locales cuando empieza por __MSG_. Firefox: <perfil>/extensions.json.

Se marcan dos cosas, sin juzgar si una extensión es maliciosa: las que pueden leer y cambiar
todas las webs (permiso amplio, lo normal en bloqueadores de anuncios pero también en el
adware) y las que por su nombre suelen ser publicidad (cupones, buscadores, "convertidores").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger

log = get_logger("extensions")

ALL_SITES = frozenset({"<all_urls>", "*://*/*", "http://*/*", "https://*/*"})

# Tipos de extensión que con frecuencia cambian el buscador o meten anuncios.
ADWARE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), why)
    for p, why in (
        (
            r"\bcoupon|cup[oó]n|descuento|cashback|deal finder|shopping assistant",
            "suele mostrar ofertas y anuncios",
        ),
        (
            r"\bsearch (bar|manager|protect|tool|baron)|safe ?search plus|\bsearch\b.*\bnew tab",
            "suele cambiar tu buscador",
        ),
        (r"(pdf|file|video|audio|mp3|youtube).{0,12}convert", "suele venir con publicidad"),
        (
            r"\bweather.{0,10}(tab|now)|\bmaps? ?(tab|now)|\bnews ?tab|\bgames? ?tab",
            "suele cambiar la nueva pestaña o el buscador",
        ),
        (r"\b(speed|pc) ?(up|boost)|optimi[sz]er|driver ?updater", "promete acelerar el equipo"),
    )
)

CHROMIUM_DATA: dict[str, str] = {
    "Chrome": r"Google\Chrome\User Data",
    "Edge": r"Microsoft\Edge\User Data",
    "Brave": r"BraveSoftware\Brave-Browser\User Data",
    "Opera": r"Opera Software\Opera Stable",
}
# Componentes internos que Chromium instala como extensiones y no se ven en su lista.
_INTERNAL_IDS = frozenset(
    {
        "nmmhkkegccagdldgiimedpiccmgmieda",  # Pagos de Chrome Web Store
        "ghbmnnjooekpmoecnnnilnnbdlolhkhi",  # Documentos de Google sin conexión
        "jmjflgjpcpepeafmmgdpfkogkghcpiha",  # Edge: componente interno
    }
)


@dataclass
class Extension:
    browser: str
    profile: str
    ext_id: str
    name: str
    version: str = ""
    all_sites: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return bool(self.warnings)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _localized(name: str, version_dir: Path, default_locale: str) -> str:
    match = re.fullmatch(r"__MSG_(.+)__", name)
    if not match:
        return name
    key = match.group(1).lower()
    for locale in (default_locale, "es", "en", "en_US"):
        messages = _read_json(version_dir / "_locales" / locale / "messages.json")
        if isinstance(messages, dict):
            for k, v in messages.items():
                if k.lower() == key and isinstance(v, dict) and v.get("message"):
                    return str(v["message"])
    return name


def classify(ext: Extension) -> Extension:
    if ext.all_sites:
        ext.warnings.append("puede leer y cambiar todas las webs que visitas")
    for pattern, why in ADWARE_PATTERNS:
        if pattern.search(ext.name):
            ext.warnings.append(why)
            break
    return ext


def _chromium(browser: str, root: Path) -> list[Extension]:
    out: list[Extension] = []
    if not root.is_dir():
        return out
    profiles = [root, *(p for p in root.iterdir() if p.is_dir())]
    for profile in profiles:
        ext_root = profile / "Extensions"
        if not (profile / "Preferences").is_file() or not ext_root.is_dir():
            continue
        for ext_dir in ext_root.iterdir():
            if not ext_dir.is_dir() or ext_dir.name in _INTERNAL_IDS:
                continue
            versions = sorted((v for v in ext_dir.iterdir() if v.is_dir()), key=lambda v: v.name)
            if not versions:
                continue
            latest = versions[-1]
            manifest = _read_json(latest / "manifest.json")
            if not isinstance(manifest, dict):
                continue
            name = _localized(
                str(manifest.get("name", ext_dir.name)),
                latest,
                str(manifest.get("default_locale", "en")),
            )
            perms = {
                str(p)
                for key in ("permissions", "host_permissions", "optional_permissions")
                for p in manifest.get(key, [])
                if isinstance(p, str)
            }
            for script in manifest.get("content_scripts", []):
                if isinstance(script, dict):
                    perms |= {str(m) for m in script.get("matches", [])}
            out.append(
                classify(
                    Extension(
                        browser=browser,
                        profile=profile.name if profile != root else "",
                        ext_id=ext_dir.name,
                        name=name,
                        version=str(manifest.get("version", "")),
                        all_sites=bool(perms & ALL_SITES),
                    )
                )
            )
    return out


def _firefox(root: Path) -> list[Extension]:
    out: list[Extension] = []
    if not root.is_dir():
        return out
    for profile in root.iterdir():
        data = _read_json(profile / "extensions.json")
        if not isinstance(data, dict):
            continue
        for addon in data.get("addons", []):
            if not isinstance(addon, dict) or addon.get("type") != "extension":
                continue
            if addon.get("location") != "app-profile":  # las del sistema no las instala el usuario
                continue
            locale = addon.get("defaultLocale") or {}
            perms = set((addon.get("userPermissions") or {}).get("origins", []))
            out.append(
                classify(
                    Extension(
                        browser="Firefox",
                        profile=profile.name,
                        ext_id=str(addon.get("id", "")),
                        name=str(locale.get("name") or addon.get("id", "")),
                        version=str(addon.get("version", "")),
                        all_sites=bool(perms & ALL_SITES),
                    )
                )
            )
    return out


def list_extensions(local_appdata: Path, roaming_appdata: Path) -> list[Extension]:
    """Todas las extensiones de los navegadores del usuario. Nunca lanza: un perfil ilegible se
    omite."""
    found: list[Extension] = []
    for browser, rel in CHROMIUM_DATA.items():
        # Opera guarda el perfil en Roaming; el resto en Local.
        base = roaming_appdata if browser == "Opera" else local_appdata
        try:
            found.extend(_chromium(browser, base / rel))
        except OSError as exc:
            log.warning("extensions_unreadable", extra={"browser": browser, "err": str(exc)})
    try:
        found.extend(_firefox(roaming_appdata / "Mozilla" / "Firefox" / "Profiles"))
    except OSError as exc:
        log.warning("extensions_unreadable", extra={"browser": "Firefox", "err": str(exc)})
    return sorted(found, key=lambda e: (not e.suspicious, e.browser, e.name.lower()))
