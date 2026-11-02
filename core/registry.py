"""Acceso al registro con backend intercambiable y resolución de HKCU al usuario interactivo.

El backend real usa winreg (solo Windows); MemoryRegistryBackend sirve para tests y para
desarrollar en Linux.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from core.constants import BACKUP_DIR
from core.logger import get_logger
from core.process import CommandError, Runner, resolve_exe

log = get_logger("registry")

Root = Literal["HKLM", "HKCU", "HKU"]
RegKind = Literal["REG_DWORD", "REG_QWORD", "REG_SZ", "REG_EXPAND_SZ", "REG_BINARY", "REG_MULTI_SZ"]
RegData = int | str | bytes | list[str]


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegValue:
    kind: RegKind
    data: RegData

    def to_json(self) -> dict[str, Any]:
        data: Any = self.data.hex() if isinstance(self.data, bytes) else self.data
        return {"kind": self.kind, "data": data}

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> RegValue:
        return cls.from_catalog(payload["kind"], payload["data"])

    @classmethod
    def from_catalog(cls, kind: str, value: Any) -> RegValue:
        """Convierte un valor tal como aparece en tweaks.json al tipo nativo."""
        match kind:
            case "REG_DWORD" | "REG_QWORD":
                return cls(kind, int(value))
            case "REG_SZ" | "REG_EXPAND_SZ":
                return cls(kind, str(value))
            case "REG_BINARY":
                return cls(kind, bytes.fromhex(value) if isinstance(value, str) else bytes(value))
            case "REG_MULTI_SZ":
                return cls(kind, [str(v) for v in value])
            case _:
                raise RegistryError(f"Tipo de registro no soportado: {kind}")

    def display(self) -> str:
        if isinstance(self.data, bytes):
            return self.data.hex(" ").upper()
        if isinstance(self.data, list):
            return " | ".join(self.data)
        return str(self.data)


class RegistryBackend(Protocol):
    def read(self, root: Root, path: str, name: str) -> RegValue | None: ...
    def write(self, root: Root, path: str, name: str, value: RegValue) -> None: ...
    def delete_value(self, root: Root, path: str, name: str) -> bool: ...
    def key_exists(self, root: Root, path: str) -> bool: ...
    def delete_key_if_empty(self, root: Root, path: str) -> bool: ...
    def subkeys(self, root: Root, path: str) -> list[str]: ...
    def values(self, root: Root, path: str) -> dict[str, RegValue]: ...


# --------------------------------------------------------------------------- backend en memoria


class MemoryRegistryBackend:
    """Registro simulado. Claves y nombres case-insensitive como en Windows, pero conserva
    la grafía original de cada nombre de valor."""

    def __init__(self) -> None:
        # (raíz, ruta en minúsculas) -> {nombre en minúsculas: (nombre original, valor)}
        self._keys: dict[tuple[str, str], dict[str, tuple[str, RegValue]]] = {}

    @staticmethod
    def _k(root: Root, path: str) -> tuple[str, str]:
        return root.upper(), path.strip("\\").lower()

    def seed(self, root: Root, path: str, name: str, value: RegValue) -> None:
        self.write(root, path, name, value)

    def read(self, root: Root, path: str, name: str) -> RegValue | None:
        entry = self._keys.get(self._k(root, path), {}).get(name.lower())
        return entry[1] if entry else None

    def write(self, root: Root, path: str, name: str, value: RegValue) -> None:
        # Crear también las claves padre, como CreateKeyEx.
        parts = path.strip("\\").split("\\")
        for i in range(1, len(parts) + 1):
            self._keys.setdefault(self._k(root, "\\".join(parts[:i])), {})
        self._keys[self._k(root, path)][name.lower()] = (name, value)

    def delete_value(self, root: Root, path: str, name: str) -> bool:
        values = self._keys.get(self._k(root, path))
        if values is None or name.lower() not in values:
            return False
        del values[name.lower()]
        return True

    def key_exists(self, root: Root, path: str) -> bool:
        return self._k(root, path) in self._keys

    def delete_key_if_empty(self, root: Root, path: str) -> bool:
        key = self._k(root, path)
        if key not in self._keys or self._keys[key] or self.subkeys(root, path):
            return False
        del self._keys[key]
        return True

    def subkeys(self, root: Root, path: str) -> list[str]:
        r, p = self._k(root, path)
        prefix = p + "\\" if p else ""
        out = set()
        for kr, kp in self._keys:
            if kr == r and kp.startswith(prefix) and kp != p:
                out.add(kp[len(prefix) :].split("\\")[0])
        return sorted(out)

    def values(self, root: Root, path: str) -> dict[str, RegValue]:
        return {name: value for name, value in self._keys.get(self._k(root, path), {}).values()}


# --------------------------------------------------------------------------- backend winreg


class WinRegBackend:
    """Backend real. Abre siempre la vista de 64 bits para evitar la redirección WOW64."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RegistryError("WinRegBackend solo está disponible en Windows")
        import winreg

        self._w = winreg
        self._roots = {
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKU": winreg.HKEY_USERS,
        }
        self._kinds: dict[str, int] = {
            "REG_DWORD": winreg.REG_DWORD,
            "REG_QWORD": winreg.REG_QWORD,
            "REG_SZ": winreg.REG_SZ,
            "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
            "REG_BINARY": winreg.REG_BINARY,
            "REG_MULTI_SZ": winreg.REG_MULTI_SZ,
        }
        self._kind_names = {v: k for k, v in self._kinds.items()}

    def _open(self, root: Root, path: str, write: bool = False) -> Any:
        rights = self._w.KEY_WOW64_64KEY | (
            self._w.KEY_READ | self._w.KEY_SET_VALUE if write else self._w.KEY_READ
        )
        return self._w.OpenKey(self._roots[root], path, 0, rights)

    def read(self, root: Root, path: str, name: str) -> RegValue | None:
        try:
            with self._open(root, path) as key:
                data, kind = self._w.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        kind_name = self._kind_names.get(kind)
        if kind_name is None:
            raise RegistryError(f"Tipo de valor no soportado ({kind}) en {root}\\{path}\\{name}")
        return RegValue(kind_name, data)  # type: ignore[arg-type]

    def write(self, root: Root, path: str, name: str, value: RegValue) -> None:
        rights = self._w.KEY_WOW64_64KEY | self._w.KEY_SET_VALUE
        with self._w.CreateKeyEx(self._roots[root], path, 0, rights) as key:
            self._w.SetValueEx(key, name, 0, self._kinds[value.kind], value.data)

    def delete_value(self, root: Root, path: str, name: str) -> bool:
        try:
            with self._open(root, path, write=True) as key:
                self._w.DeleteValue(key, name)
        except FileNotFoundError:
            return False
        return True

    def key_exists(self, root: Root, path: str) -> bool:
        try:
            with self._open(root, path):
                return True
        except FileNotFoundError:
            return False

    def delete_key_if_empty(self, root: Root, path: str) -> bool:
        if self.subkeys(root, path) or self.values(root, path):
            return False
        try:
            self._w.DeleteKeyEx(self._roots[root], path, self._w.KEY_WOW64_64KEY, 0)
        except OSError:
            return False
        return True

    def subkeys(self, root: Root, path: str) -> list[str]:
        out: list[str] = []
        try:
            with self._open(root, path) as key:
                i = 0
                while True:
                    try:
                        out.append(self._w.EnumKey(key, i))
                    except OSError:
                        break
                    i += 1
        except FileNotFoundError:
            return []
        return out

    def values(self, root: Root, path: str) -> dict[str, RegValue]:
        out: dict[str, RegValue] = {}
        try:
            with self._open(root, path) as key:
                i = 0
                while True:
                    try:
                        name, data, kind = self._w.EnumValue(key, i)
                    except OSError:
                        break
                    kind_name = self._kind_names.get(kind)
                    if kind_name:
                        out[name] = RegValue(kind_name, data)  # type: ignore[arg-type]
                    i += 1
        except FileNotFoundError:
            return {}
        return out


# --------------------------------------------------------------------------- fachada


@dataclass(frozen=True)
class Location:
    """Ubicación física ya resuelta (HKCU convertido a HKU\\<SID> si procede)."""

    root: Root
    path: str

    def __str__(self) -> str:
        return f"{self.root}\\{self.path}"


class Registry:
    """Fachada sobre un backend. Resuelve HKCU contra el usuario interactivo.

    Si WinTune se eleva con credenciales de otro administrador, el HKCU del proceso es el de
    ese administrador; escribir ahí no afectaría al usuario que tiene la sesión abierta.
    """

    def __init__(self, backend: RegistryBackend, user_sid: str | None = None) -> None:
        self.backend = backend
        self.user_sid = user_sid

    def locate(self, hive: str, path: str) -> Location:
        path = path.strip("\\")
        if hive == "HKCU" and self.user_sid:
            return Location("HKU", f"{self.user_sid}\\{path}")
        if hive not in ("HKLM", "HKCU", "HKU"):
            raise RegistryError(f"Hive no soportado: {hive}")
        return Location(hive, path)  # type: ignore[arg-type]

    def read(self, hive: str, path: str, name: str) -> RegValue | None:
        loc = self.locate(hive, path)
        return self.backend.read(loc.root, loc.path, name)

    def write(self, hive: str, path: str, name: str, value: RegValue) -> None:
        loc = self.locate(hive, path)
        log.info("reg_write", extra={"key": str(loc), "value_name": name, "value": value.display()})
        self.backend.write(loc.root, loc.path, name, value)

    def delete_value(self, hive: str, path: str, name: str) -> bool:
        loc = self.locate(hive, path)
        log.info("reg_delete", extra={"key": str(loc), "value_name": name})
        return self.backend.delete_value(loc.root, loc.path, name)

    def key_exists(self, hive: str, path: str) -> bool:
        loc = self.locate(hive, path)
        return self.backend.key_exists(loc.root, loc.path)

    def delete_key_if_empty(self, hive: str, path: str) -> bool:
        loc = self.locate(hive, path)
        return self.backend.delete_key_if_empty(loc.root, loc.path)

    def subkeys(self, hive: str, path: str) -> list[str]:
        loc = self.locate(hive, path)
        return self.backend.subkeys(loc.root, loc.path)

    def values(self, hive: str, path: str) -> dict[str, RegValue]:
        loc = self.locate(hive, path)
        return self.backend.values(loc.root, loc.path)


def values_equal(current: RegValue | None, target: RegValue) -> bool:
    """Compara normalizando tipos equivalentes (DWORD/QWORD, SZ/EXPAND_SZ)."""
    if current is None:
        return False
    if isinstance(target.data, int) and isinstance(current.data, int):
        return current.data == target.data
    if isinstance(target.data, str) and isinstance(current.data, str):
        return current.data == target.data
    return current.data == target.data


# --------------------------------------------------------------------------- copias .reg

_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


def export_key(runner: Runner, location: Location, session_dir: Path | None = None) -> Path | None:
    """Exporta una clave a .reg con timestamp. Devuelve None si la clave no existe."""
    target_dir = session_dir or BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = _SANITIZE.sub("_", str(location))[-120:]
    target = target_dir / f"{stamp}_{safe}.reg"
    root_name = {"HKLM": "HKLM", "HKCU": "HKCU", "HKU": "HKU"}[location.root]
    try:
        result = runner.run(
            [resolve_exe("reg.exe"), "export", f"{root_name}\\{location.path}", str(target), "/y"]
        )
    except CommandError as exc:
        log.warning("reg_export_error", extra={"key": str(location), "err": str(exc)})
        return None
    if not result.ok:
        # reg.exe devuelve 1 si la clave no existe: no es un error, no hay nada que copiar.
        log.info("reg_export_skipped", extra={"key": str(location), "err": result.error_text()})
        return None
    return target
