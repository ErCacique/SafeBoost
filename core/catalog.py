"""Carga del catálogo data/tweaks.json, evaluación de condiciones y selección por perfil."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.constants import POLICY_PATH_MARKER, SUPPORTED_EDITIONS, TWEAKS_FILE
from core.environment import EnvironmentInfo

REQUIRED_FIELDS = (
    "id",
    "name",
    "description",
    "rationale",
    "category",
    "level",
    "risk",
    "windows",
    "kind",
    "reversible",
    "auto_profile",
    "confirm_double",
    "reboot_required",
    "requires",
    "auto_when",
    "apply",
    "revert",
    "detect",
)

CATEGORY_LABELS: dict[str, str] = {
    "bloatware": "Bloatware",
    "privacy": "Privacidad y telemetría",
    "services": "Servicios",
    "visual": "Efectos visuales",
    "cleanup": "Limpieza",
    "power": "Energía",
    "network": "Red",
    "performance": "Rendimiento",
    "gaming": "Juegos",
    "search": "Búsqueda",
    "memory": "Memoria virtual",
    "security": "Seguridad",
}

LEVEL_LABELS: dict[int, str] = {1: "Conservador", 2: "Equilibrado", 3: "Máximo"}


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Tweak:
    id: str
    name: str
    description: str
    rationale: str
    category: str
    level: int
    risk: str
    windows: dict[str, Any]
    kind: str
    reversible: bool
    auto_profile: bool
    confirm_double: bool
    reboot_required: bool
    requires: dict[str, Any]
    auto_when: dict[str, Any]
    apply: list[dict[str, Any]]
    revert: list[dict[str, Any]]
    detect: list[dict[str, Any]]
    revert_note: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Tweak:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in raw.items() if k in known})

    @property
    def is_action(self) -> bool:
        return self.kind == "action"

    @property
    def is_irreversible(self) -> bool:
        return not self.reversible

    def policy_ops(self) -> list[dict[str, Any]]:
        return [op for op in self.apply if is_policy_op(op)]

    @property
    def only_policies(self) -> bool:
        return (
            bool(self.apply)
            and all(is_policy_op(op) or op["op"] == "handler" for op in self.apply)
            and any(is_policy_op(op) for op in self.apply)
        )


def is_policy_op(op: dict[str, Any]) -> bool:
    return op.get("op") == "registry_set" and POLICY_PATH_MARKER in (
        "\\" + op.get("path", "").lower() + "\\"
    )


def structural_errors(data: Any) -> list[str]:
    """Validación mínima en runtime (el esquema completo se valida en CI con jsonschema)."""
    errors: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("tweaks"), list):
        return ["La raíz debe ser un objeto con la lista 'tweaks'."]
    seen: set[str] = set()
    for i, raw in enumerate(data["tweaks"]):
        tid = raw.get("id", f"#{i}") if isinstance(raw, dict) else f"#{i}"
        if not isinstance(raw, dict):
            errors.append(f"{tid}: no es un objeto")
            continue
        missing = [f for f in REQUIRED_FIELDS if f not in raw]
        if missing:
            errors.append(f"{tid}: faltan campos {', '.join(missing)}")
            continue
        for key in ("apply", "revert", "detect"):
            if not isinstance(raw[key], list) or not raw[key]:
                errors.append(f"{tid}: '{key}' debe ser una lista no vacía")
        if tid in seen:
            errors.append(f"{tid}: id duplicado")
        seen.add(tid)
        if raw["kind"] == "action" and raw["reversible"]:
            errors.append(f"{tid}: una acción no puede ser reversible")
        if not raw["reversible"] and raw["kind"] == "tweak" and raw["auto_profile"]:
            errors.append(f"{tid}: un tweak irreversible no puede estar en perfiles automáticos")
        if raw["risk"] == "alto" and raw["auto_profile"]:
            errors.append(f"{tid}: riesgo alto no puede estar en perfiles automáticos")
        if raw["confirm_double"] and raw["risk"] != "alto":
            errors.append(f"{tid}: confirm_double solo se permite con riesgo alto")
    return errors


class Catalog:
    def __init__(self, tweaks: Iterable[Tweak]) -> None:
        self.tweaks: list[Tweak] = list(tweaks)
        self._by_id = {t.id: t for t in self.tweaks}

    @classmethod
    def load(cls, path: Path = TWEAKS_FILE) -> Catalog:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"No se pudo leer {path}: {exc}") from exc
        errors = structural_errors(data)
        if errors:
            raise CatalogError("Catálogo inválido:\n" + "\n".join(errors))
        return cls(Tweak.from_dict(t) for t in data["tweaks"])

    def get(self, tweak_id: str) -> Tweak:
        try:
            return self._by_id[tweak_id]
        except KeyError as exc:
            raise CatalogError(f"Tweak desconocido: {tweak_id}") from exc

    def __contains__(self, tweak_id: object) -> bool:
        return tweak_id in self._by_id

    def by_category(self, *categories: str) -> list[Tweak]:
        return [t for t in self.tweaks if t.category in categories]

    def up_to_level(self, level: int) -> list[Tweak]:
        return [t for t in self.tweaks if t.level <= level]


# --------------------------------------------------------------------------- condiciones

CheckResolver = Callable[[str], bool]


def windows_reasons(tweak: Tweak, env: EnvironmentInfo) -> list[str]:
    w = tweak.windows
    reasons: list[str] = []
    if env.build and env.build < w["min_build"]:
        reasons.append(f"requiere build {w['min_build']} o superior")
    if env.build and w.get("max_build") is not None and env.build > w["max_build"]:
        reasons.append(f"solo aplica hasta la build {w['max_build']}")
    edition_specific = set(w["editions"]) != set(SUPPORTED_EDITIONS)
    if env.edition == "unknown":
        # Con una edición no reconocida (Server, algunas OEM/IoT) no se puede saber cuál de
        # dos tweaks excluyentes por edición corresponde: se descartan ambos.
        if edition_specific:
            reasons.append("edición de Windows no reconocida")
    elif env.edition not in w["editions"]:
        reasons.append(f"no aplica a la edición {env.edition}")
    return reasons


def condition_reasons(
    conds: dict[str, Any], env: EnvironmentInfo, check: CheckResolver | None = None
) -> list[str]:
    """Devuelve las condiciones que no se cumplen (lista vacía = se cumplen todas)."""
    reasons: list[str] = []
    disk = conds.get("disk")
    if disk and env.disk_type != disk:
        reasons.append(f"requiere disco {disk.upper()} (detectado: {env.disk_type})")
    chassis = conds.get("chassis")
    if chassis and env.chassis != chassis:
        label = {"desktop": "sobremesa", "laptop": "portátil"}[chassis]
        reasons.append(f"solo en {label}")
    if conds.get("no_printers") and env.has_printers:
        reasons.append("hay impresoras instaladas")
    if conds.get("not_domain") and env.domain_joined:
        reasons.append("equipo unido a dominio")
    if conds.get("not_managed") and env.managed:
        reasons.append("equipo gestionado (dominio/Entra ID/MDM)")
    ref = conds.get("check")
    if ref:
        try:
            ok = check(ref) if check else False
        except Exception as exc:  # noqa: BLE001 - una comprobación rota no debe tumbar la UI
            reasons.append(f"comprobación {ref} falló: {exc}")
        else:
            if not ok:
                reasons.append("hardware o driver no compatible")
    return reasons


@dataclass(frozen=True)
class Applicability:
    applicable: bool
    reasons: tuple[str, ...]
    preselect: bool
    preselect_reasons: tuple[str, ...] = ()


def evaluate(
    tweak: Tweak, env: EnvironmentInfo, level: int, check: CheckResolver | None = None
) -> Applicability:
    hard = windows_reasons(tweak, env) + condition_reasons(tweak.requires, env, check)
    if env.managed and tweak.only_policies:
        hard.append("solo contiene directivas y el equipo está gestionado")
    applicable = not hard
    soft = condition_reasons(tweak.auto_when, env, check) if applicable else []
    preselect = applicable and tweak.auto_profile and tweak.level <= level and not soft
    return Applicability(applicable, tuple(hard), preselect, tuple(soft))


def profile_selection(
    catalog: Catalog, env: EnvironmentInfo, level: int, check: CheckResolver | None = None
) -> list[str]:
    """IDs preseleccionados por un perfil (acumulativo hasta 'level')."""
    return [t.id for t in catalog.up_to_level(level) if evaluate(t, env, level, check).preselect]
