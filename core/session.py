"""Registro de cambios por sesión: fuente de verdad para Deshacer."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from core.constants import APP_VERSION, BACKUP_DIR, SESSIONS_DIR
from core.logger import get_logger

log = get_logger("session")

# Versión del formato JSON de las sesiones. Subirla exige añadir una migración en
# MIGRATIONS: Deshacer tiene que seguir funcionando con sesiones creadas por versiones viejas.
SESSION_SCHEMA_VERSION = 2


class SessionVersionError(ValueError):
    """La sesión la creó una versión de SafeTrim más nueva que la instalada."""


def _migrate_1_to_2(data: dict[str, Any]) -> dict[str, Any]:
    # v1 (SafeTrim 0.1.x) no guardaba versión ni la detección previa/verificación por tweak.
    data["app_version"] = "0.1.x"
    for result in data.get("results", {}).values():
        result.setdefault("detect_before", None)
        result.setdefault("verified", None)
    return data


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _migrate_1_to_2}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Lleva un JSON de sesión de cualquier versión anterior a SESSION_SCHEMA_VERSION."""
    data = dict(data)
    version = int(data.get("schema_version", 1))
    if version > SESSION_SCHEMA_VERSION:
        raise SessionVersionError(
            f"La sesión {data.get('id')} usa el formato v{version}; esta versión de SafeTrim "
            f"solo entiende hasta v{SESSION_SCHEMA_VERSION}. Actualiza SafeTrim para deshacerla."
        )
    while version < SESSION_SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    return data


ChangeKind = Literal["registry", "service", "task", "appx", "command", "handler"]
TweakStatus = Literal["applied", "skipped", "failed", "partial", "reverted", "irreversible"]


@dataclass
class Change:
    """Un cambio atómico con su estado anterior. `before=None` significa 'no existía'."""

    tweak_id: str
    kind: ChangeKind
    target: dict[str, Any]
    before: Any
    after: Any
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class TweakResult:
    tweak_id: str
    status: TweakStatus
    message: str = ""
    details: list[str] = field(default_factory=list)
    # Estado detectado antes de aplicar (para verificar la reversión) y resultado de esa
    # verificación al deshacer: True = volvió al estado previo, False = hay diferencias.
    detect_before: str | None = None
    verified: bool | None = None


@dataclass
class Session:
    id: str
    kind: Literal["apply", "revert"]
    created: str
    profile: int | None = None
    parent_id: str | None = None
    restore_point: str = ""
    env: dict[str, Any] = field(default_factory=dict)
    selected: list[str] = field(default_factory=list)
    results: dict[str, TweakResult] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    handler_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    backups: list[str] = field(default_factory=list)
    reverted_by: str | None = None
    finished: str | None = None
    schema_version: int = SESSION_SCHEMA_VERSION
    app_version: str = APP_VERSION

    @classmethod
    def new(cls, kind: Literal["apply", "revert"], **kwargs: Any) -> Session:
        stamp = datetime.now()
        sid = f"{stamp:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        return cls(id=sid, kind=kind, created=stamp.isoformat(timespec="seconds"), **kwargs)

    @property
    def backup_dir(self) -> Path:
        return BACKUP_DIR / self.id

    def changes_for(self, tweak_id: str) -> list[Change]:
        return [c for c in self.changes if c.tweak_id == tweak_id]

    def summary(self) -> dict[str, int]:
        out = {
            "applied": 0,
            "skipped": 0,
            "failed": 0,
            "partial": 0,
            "reverted": 0,
            "irreversible": 0,
        }
        for result in self.results.values():
            out[result.status] = out.get(result.status, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["results"] = {k: asdict(v) for k, v in self.results.items()}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        data = migrate(data)
        data["results"] = {k: TweakResult(**v) for k, v in data.get("results", {}).items()}
        data["changes"] = [Change(**c) for c in data.get("changes", [])]
        return cls(**data)


class SessionStore:
    def __init__(self, directory: Path = SESSIONS_DIR) -> None:
        self.directory = directory

    def path_for(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.json"

    def save(self, session: Session) -> None:
        """Escritura atómica: un corte de luz no deja un JSON a medias."""
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.path_for(session.id)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(target)

    def load(self, session_id: str) -> Session:
        return Session.from_dict(json.loads(self.path_for(session_id).read_text(encoding="utf-8")))

    def list(self) -> list[Session]:
        if not self.directory.exists():
            return []
        sessions: list[Session] = []
        for path in sorted(self.directory.glob("*.json"), reverse=True):
            try:
                sessions.append(Session.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                log.warning("session_unreadable", extra={"file": path.name, "err": str(exc)})
        return sessions
