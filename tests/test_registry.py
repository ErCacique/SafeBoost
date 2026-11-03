"""Registro en memoria, resolución de HKCU y conversión de valores."""

from __future__ import annotations

import pytest

from core.registry import (
    Location,
    MemoryRegistryBackend,
    Registry,
    RegistryError,
    RegValue,
    export_key,
    values_equal,
)
from tests.conftest import USER_SID, FakeRunner


def test_hkcu_resolves_to_interactive_user() -> None:
    reg = Registry(MemoryRegistryBackend(), USER_SID)
    assert reg.locate("HKCU", r"Software\X") == Location("HKU", rf"{USER_SID}\Software\X")
    assert reg.locate("HKLM", r"\SOFTWARE\X\\") == Location("HKLM", r"SOFTWARE\X")


def test_hkcu_without_sid_stays_hkcu() -> None:
    assert Registry(MemoryRegistryBackend()).locate("HKCU", "A").root == "HKCU"


def test_unknown_hive_rejected() -> None:
    with pytest.raises(RegistryError):
        Registry(MemoryRegistryBackend()).locate("HKCR", "A")


def test_memory_backend_is_case_insensitive_and_creates_parents() -> None:
    b = MemoryRegistryBackend()
    b.write("HKLM", r"A\B\C", "Val", RegValue("REG_DWORD", 1))
    assert b.read("HKLM", r"a\b\c", "VAL") == RegValue("REG_DWORD", 1)
    assert b.key_exists("HKLM", "A")
    assert b.subkeys("HKLM", "A") == ["b"]


def test_delete_key_if_empty() -> None:
    b = MemoryRegistryBackend()
    b.write("HKLM", r"A\B", "v", RegValue("REG_SZ", "x"))
    assert not b.delete_key_if_empty("HKLM", r"A\B")
    b.delete_value("HKLM", r"A\B", "v")
    assert b.delete_key_if_empty("HKLM", r"A\B")
    assert not b.key_exists("HKLM", r"A\B")


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("REG_DWORD", 1, 1),
        ("REG_SZ", "2", "2"),
        ("REG_BINARY", "9012038010000000", bytes.fromhex("9012038010000000")),
        ("REG_MULTI_SZ", ["a", "b"], ["a", "b"]),
    ],
)
def test_from_catalog_and_json_roundtrip(kind: str, raw: object, expected: object) -> None:
    value = RegValue.from_catalog(kind, raw)
    assert value.data == expected
    assert RegValue.from_json(value.to_json()) == value


def test_values_equal() -> None:
    assert values_equal(RegValue("REG_DWORD", 0), RegValue("REG_QWORD", 0))
    assert not values_equal(None, RegValue("REG_DWORD", 0))
    assert not values_equal(RegValue("REG_SZ", "0"), RegValue("REG_DWORD", 0))


def test_export_key_uses_reg_exe(tmp_path, runner: FakeRunner) -> None:
    path = export_key(runner, Location("HKLM", r"SOFTWARE\X"), tmp_path)
    assert path is not None
    assert path.suffix == ".reg"
    args = runner.calls[-1]
    assert args[1:3] == ["export", r"HKLM\SOFTWARE\X"]


def test_export_missing_key_returns_none(tmp_path, runner: FakeRunner) -> None:
    runner.fail_on.append("export")
    assert export_key(runner, Location("HKLM", r"SOFTWARE\Nope"), tmp_path) is None
