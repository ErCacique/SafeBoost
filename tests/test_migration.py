"""Migración de datos de WinTune (nombre anterior, hasta 0.2.x) a SafeBoost."""

from __future__ import annotations

import json
from pathlib import Path

from core.catalog import Catalog
from core.constants import LEGACY_MIGRATED_MARKER
from core.migration import looks_like_ours, migrate_legacy_data
from core.selection import load_selection
from core.session import Session
from tests.conftest import FakeRunner

FIXTURE = Path(__file__).parent / "fixtures" / "session_v1.json"


def _legacy(tmp_path: Path) -> Path:
    legacy = tmp_path / "WinTune"
    (legacy / "sessions").mkdir(parents=True)
    (legacy / "backups" / "s1").mkdir(parents=True)
    (legacy / "sessions" / "20261102-120000-v1demo.json").write_text(
        FIXTURE.read_text("utf-8"), encoding="utf-8"
    )
    (legacy / "backups" / "s1" / "a.reg").write_text("Windows Registry Editor", encoding="utf-8")
    (legacy / "settings.json").write_text(json.dumps({"dry_run": False}), encoding="utf-8")
    return legacy


def test_copies_legacy_data_and_keeps_original(tmp_path: Path) -> None:
    legacy, new = _legacy(tmp_path), tmp_path / "SafeBoost"
    runner = FakeRunner()
    result = migrate_legacy_data(runner, legacy, new, overridden=False)
    assert result.migrated
    assert set(result.copied) == {"sessions", "backups", "settings.json"}
    # Copia, no mueve: los datos antiguos siguen ahí, con una marca.
    assert (legacy / "sessions" / "20261102-120000-v1demo.json").exists()
    assert (legacy / LEGACY_MIGRATED_MARKER).exists()
    copied = json.loads((new / "sessions" / "20261102-120000-v1demo.json").read_text("utf-8"))
    assert Session.from_dict(copied).results["privacy.diagtrack"].status == "applied"
    assert (new / "backups" / "s1" / "a.reg").exists()
    # Se elimina la tarea programada antigua de WinTune.
    assert any("-TaskPath '\\WinTune\\'" in s for s in runner.scripts)


def test_migration_runs_once(tmp_path: Path) -> None:
    legacy, new = _legacy(tmp_path), tmp_path / "SafeBoost"
    assert migrate_legacy_data(None, legacy, new, overridden=False).migrated
    assert not migrate_legacy_data(None, legacy, new, overridden=False).migrated


def test_does_not_touch_another_programs_wintune_folder(tmp_path: Path) -> None:
    other = tmp_path / "WinTune"
    other.mkdir()
    (other / "config.ini").write_text("[otro programa]", encoding="utf-8")
    result = migrate_legacy_data(None, other, tmp_path / "SafeBoost", overridden=False)
    assert not result.migrated
    assert "no es de este programa" in result.reason
    assert not (other / LEGACY_MIGRATED_MARKER).exists()
    assert not looks_like_ours(other)


def test_skips_when_new_home_already_has_sessions(tmp_path: Path) -> None:
    legacy, new = _legacy(tmp_path), tmp_path / "SafeBoost"
    (new / "sessions").mkdir(parents=True)
    (new / "sessions" / "x.json").write_text("{}", encoding="utf-8")
    assert not migrate_legacy_data(None, legacy, new, overridden=False).migrated


def test_skips_when_home_overridden(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    assert not migrate_legacy_data(None, legacy, tmp_path / "S", overridden=True).migrated


def test_legacy_selection_files_still_import(tmp_path: Path) -> None:
    path = tmp_path / "sel.json"
    path.write_text(
        json.dumps({"format": "wintune-selection", "version": 1, "tweaks": ["privacy.diagtrack"]}),
        encoding="utf-8",
    )
    selection, warnings = load_selection(path, Catalog.load())
    assert selection.tweaks == ["privacy.diagtrack"]
    assert warnings == []


def test_legacy_env_var_is_accepted(monkeypatch, tmp_path: Path) -> None:
    from core.constants import _home_override

    monkeypatch.delenv("SAFEBOOST_HOME", raising=False)
    monkeypatch.setenv("WINTUNE_HOME", str(tmp_path))
    assert _home_override() == str(tmp_path)
    monkeypatch.setenv("SAFEBOOST_HOME", str(tmp_path / "nuevo"))
    assert _home_override() == str(tmp_path / "nuevo")  # la variable nueva tiene prioridad
