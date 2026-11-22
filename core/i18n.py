"""Traducción de la interfaz (español por defecto, inglés opcional).

Estilo gettext: el texto original en español es la clave; si no hay traducción se muestra el
original. Se fija el idioma una vez al arrancar (Ajustes → Idioma, requiere reiniciar). En esta
versión están traducidos el menú, los títulos de página, los botones principales, la guía de
inicio y los nombres de los tweaks; el resto de textos sigue en español.
"""

from __future__ import annotations

import json
from typing import Any

from core.constants import RESOURCE_ROOT
from core.logger import get_logger

log = get_logger("i18n")

LANGUAGES = {"es": "Español", "en": "English"}
_ui: dict[str, str] = {}
_tweaks: dict[str, str] = {}
_lang = "es"


def set_language(lang: str) -> None:
    global _lang, _ui, _tweaks
    _lang, _ui, _tweaks = lang, {}, {}
    if lang == "es":
        return
    path = RESOURCE_ROOT / "data" / "i18n" / f"{lang}.json"
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("i18n_unavailable", extra={"lang": lang, "err": str(exc)})
        _lang = "es"
        return
    _ui = dict(data.get("ui", {}))
    _tweaks = dict(data.get("tweaks", {}))


def current() -> str:
    return _lang


def _(text: str, **fmt: Any) -> str:
    out = _ui.get(text, text)
    return out.format(**fmt) if fmt else out


def tweak_name(tweak_id: str, default: str) -> str:
    return _tweaks.get(tweak_id, default)
