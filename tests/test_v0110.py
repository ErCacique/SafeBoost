"""v0.11.0: SafeTrim pasa a llamarse SafeBoost sin perder datos, tareas ni actualizaciones."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.constants import APP_NAME, KNOWN_PROCESSES, SAFETRIM_MIGRATED_MARKER
from core.migration import migrate_from_safetrim, migrate_tasks
from core.selection import load_selection
from core.update_check import check_latest
from tests.conftest import FakeRunner
from tests.test_migration import FIXTURE

ROOT = Path(__file__).resolve().parent.parent


def _safetrim_home(tmp_path: Path) -> Path:
    old = tmp_path / "SafeTrim"
    (old / "sessions").mkdir(parents=True)
    (old / "watch").mkdir()
    (old / "sessions" / "20261120-100000-000001-a.json").write_text(
        FIXTURE.read_text("utf-8"), encoding="utf-8"
    )
    (old / "watch" / "startup_known.json").write_text("[]", encoding="utf-8")
    (old / "settings.json").write_text(json.dumps({"maintenance": True}), encoding="utf-8")
    (old / "license.key").write_text("ST1.x.y", encoding="utf-8")
    (old / "tray.pid").write_text("999999", encoding="utf-8")
    return old


def test_name_is_safeboost() -> None:
    assert APP_NAME == "SafeBoost"
    # El proceso con el nombre antiguo sigue reconociéndose en el diagnóstico.
    assert "safeboost.exe" in KNOWN_PROCESSES and "safetrim.exe" in KNOWN_PROCESSES


def test_copies_everything_from_safetrim_once(tmp_path: Path) -> None:
    old, new = _safetrim_home(tmp_path), tmp_path / "SafeBoost"
    result = migrate_from_safetrim(None, old, new, overridden=False)
    assert result.migrated
    assert {"sessions", "watch", "settings.json", "license.key"} <= set(result.copied)
    assert "tray.pid" not in result.copied
    assert (new / "sessions" / "20261120-100000-000001-a.json").exists()
    assert (new / "license.key").read_text() == "ST1.x.y"
    # Copia, no mueve, y deja una marca para no repetir.
    assert (old / "sessions" / "20261120-100000-000001-a.json").exists()
    assert (old / SAFETRIM_MIGRATED_MARKER).exists()
    assert not migrate_from_safetrim(None, old, new, overridden=False).migrated


def test_does_not_overwrite_existing_safeboost_data(tmp_path: Path) -> None:
    old, new = _safetrim_home(tmp_path), tmp_path / "SafeBoost"
    (new / "sessions").mkdir(parents=True)
    (new / "sessions" / "own.json").write_text("{}", encoding="utf-8")
    assert not migrate_from_safetrim(None, old, new, overridden=False).migrated
    assert not migrate_from_safetrim(None, tmp_path / "nada", new, overridden=False).migrated
    assert not migrate_from_safetrim(None, old, tmp_path / "x", overridden=True).migrated


def test_recreates_old_scheduled_tasks_with_new_name() -> None:
    runner = FakeRunner()
    # Solo existían la de mantenimiento y la de medición tras reinicio.
    runner.respond_json("-TaskName 'Maintenance'", {"user": "PC\\Ana"})
    runner.respond_json("-TaskName 'PostRebootMetrics'", {"user": "SYSTEM"})
    recreated = migrate_tasks(runner, [r"C:\Program Files\SafeBoost\SafeBoost.exe"])
    assert recreated == ["Maintenance"]
    joined = "\n".join(runner.scripts)
    assert "Unregister-ScheduledTask -TaskPath '\\SafeTrim\\' -TaskName 'Maintenance'" in joined
    assert (
        "Unregister-ScheduledTask -TaskPath '\\SafeTrim\\' -TaskName 'PostRebootMetrics'" in joined
    )
    assert "-TaskPath '\\SafeBoost\\' -TaskName 'Maintenance'" in joined
    assert "SafeBoost.exe" in joined and "-UserId 'PC\\Ana'" in joined
    # La vigilancia no existía: no se crea.
    assert "-TaskPath '\\SafeBoost\\' -TaskName 'Tray'" not in joined


def test_old_selection_files_still_load(tmp_path: Path) -> None:
    from core.catalog import Catalog

    path = tmp_path / "sel.json"
    path.write_text(
        json.dumps({"format": "safetrim-selection", "version": 1, "tweaks": [], "params": {}}),
        encoding="utf-8",
    )
    selection, _warnings = load_selection(path, Catalog.load())
    assert selection.tweaks == []


class _Resp:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_a: object) -> None:
        return None


def test_updater_accepts_both_installer_names() -> None:
    for name in ("SafeBoost-Setup-0.11.0.exe", "SafeTrim-Setup-0.11.0.exe"):
        payload = json.dumps(
            {
                "tag_name": "v0.11.0",
                "html_url": "https://x/rel",
                "assets": [
                    {"name": name, "browser_download_url": f"https://x/{name}"},
                    {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"},
                ],
            }
        ).encode()
        info = check_latest("0.10.0", opener=lambda _r, timeout=0, p=payload: _Resp(p))
        assert info is not None and info.setup_url == f"https://x/{name}"


def test_release_publishes_compat_installer_for_safetrim_updater() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'Copy-Item "dist/SafeBoost-Setup-$v.exe" "dist/SafeTrim-Setup-$v.exe"' in workflow
    assert "dist/SafeTrim-Setup-*.exe" in workflow


def test_installer_moves_out_of_safetrim_folder() -> None:
    iss = (ROOT / "packaging" / "SafeBoost.iss").read_text(encoding="utf-8")
    assert "AppId={{86C1CB48-73C9-4787-AFB6-B5B74BC5F720}" in iss  # mismo AppId: actualiza
    assert "UsePreviousAppDir=no" in iss
    assert '{autopf}\\SafeTrim"' in iss and "CameFromSafeTrim" in iss
