"""Funciones de la 0.2.0: deriva, precarga de tareas, selección exportable, informe y CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from core.catalog import Catalog
from core.context import DetectState
from core.engine import Engine
from core.metrics import MetricsStore
from core.registry import MemoryRegistryBackend
from core.report import render_session_html
from core.selection import Selection, SelectionError, load_selection
from core.tasks import TaskManager
from tests.conftest import USER_SID, FakeRunner, make_tweak

EngineFactory = Callable[..., Engine]
SIUF = rf"{USER_SID}\Software\Microsoft\Siuf\Rules"


# --------------------------------------------------------------------------- deriva


def test_drift_detects_values_reverted_by_windows(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    engine.apply(["privacy.feedback_frequency", "privacy.tailored_experiences"])
    assert engine.drift() == []
    # Una actualización de Windows restablece el valor.
    backend.delete_value("HKU", SIUF, "NumberOfSIUFInPeriod")
    items = engine.drift()
    assert [i.tweak_id for i in items] == ["privacy.feedback_frequency"]
    assert items[0].state == DetectState.NOT_APPLIED


def test_drift_ignores_reverted_sessions(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.feedback_frequency"])
    engine.revert(session.id)
    assert engine.drift() == []


def test_drift_detects_reinstalled_app(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.appx_installed = ["Microsoft.BingNews"]
    engine = make_engine()
    engine.apply(["bloatware.bing_news"])
    assert engine.drift() == []
    runner.appx_installed.append("Microsoft.BingNews")
    assert [i.tweak_id for i in engine.drift()] == ["bloatware.bing_news"]


def test_drift_uses_latest_session_per_tweak(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    engine.apply(["privacy.feedback_frequency"])
    backend.delete_value("HKU", SIUF, "NumberOfSIUFInPeriod")
    engine.apply(["privacy.feedback_frequency"])  # reaplicado
    assert engine.drift() == []


# --------------------------------------------------------------------------- precarga de tareas


def test_task_prefetch_uses_one_powershell_call(runner: FakeRunner) -> None:
    paths = [r"\Microsoft\Windows\A\T1", r"\Microsoft\Windows\B\T2"]
    runner.respond_json(
        "foreach ($p in",
        {r"\Microsoft\Windows\A\T1": "Disabled", r"\Microsoft\Windows\B\T2": "Missing"},
    )
    tasks = TaskManager(runner)
    tasks.prefetch(paths)
    calls = len(runner.scripts)
    assert not tasks.query(paths[0]).enabled
    assert not tasks.query(paths[1]).exists
    assert len(runner.scripts) == calls  # servidas desde la caché
    tasks.set_enabled(paths[0], True)  # invalida esa entrada
    assert tasks.query(paths[0]).enabled  # consulta real (FakeRunner: Ready)


def test_task_prefetch_unexpected_output_falls_back(runner: FakeRunner) -> None:
    runner.respond_json("foreach ($p in", "no-es-un-dict")
    tasks = TaskManager(runner)
    tasks.prefetch([r"\X\Y"])  # no debe lanzar
    calls = len(runner.scripts)
    assert tasks.query(r"\X\Y").enabled  # consulta individual (FakeRunner: Ready)
    assert len(runner.scripts) == calls + 1


# --------------------------------------------------------------------------- selección


def test_selection_roundtrip(tmp_path: Path) -> None:
    catalog = Catalog.load()
    path = tmp_path / "sel.json"
    Selection(
        tweaks=["privacy.diagtrack", "network.dns"],
        params={"network.dns": {"provider": "quad9"}},
        profile=2,
    ).save(path)
    selection, warnings = load_selection(path, catalog)
    assert warnings == []
    assert selection.tweaks == ["privacy.diagtrack", "network.dns"]
    assert selection.params == {"network.dns": {"provider": "quad9"}}
    assert selection.profile == 2


def test_selection_drops_unknown_ids(tmp_path: Path) -> None:
    path = tmp_path / "sel.json"
    path.write_text(
        json.dumps(
            {
                "format": "safeboost-selection",
                "version": 1,
                "tweaks": ["privacy.diagtrack", "no.existe"],
                "params": {"no.existe": {"x": 1}},
            }
        )
    )
    selection, warnings = load_selection(path, Catalog.load())
    assert selection.tweaks == ["privacy.diagtrack"]
    assert selection.params == {}
    assert warnings == ["no.existe: no existe en esta versión del catálogo"]


@pytest.mark.parametrize(
    "payload",
    [
        {"format": "otro", "tweaks": []},
        {"format": "safeboost-selection", "version": 99, "tweaks": []},
        {"format": "safeboost-selection", "tweaks": "privacy.diagtrack"},
        "no es json",
    ],
)
def test_selection_rejects_invalid(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "sel.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    with pytest.raises(SelectionError):
        load_selection(path, Catalog.load())


# --------------------------------------------------------------------------- informe


def test_report_escapes_and_lists_results(make_engine: EngineFactory, tmp_path: Path) -> None:
    evil = make_tweak(
        id="test.xss",
        name="<script>alert(1)</script>",
        apply=[
            {
                "op": "registry_set",
                "hive": "HKLM",
                "path": r"SOFTWARE\SafeBoostTest",
                "name": "X",
                "kind": "REG_DWORD",
                "value": 1,
            }
        ],
    )
    engine = make_engine(Catalog([evil]))
    session = engine.apply(["test.xss"])
    html = render_session_html(session, engine.catalog, MetricsStore(tmp_path))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Aplicado" in html
    assert session.id in html


# --------------------------------------------------------------------------- CLI


def _selection_file(tmp_path: Path, tweaks: list[str]) -> Path:
    path = tmp_path / "sel.json"
    Selection(tweaks=tweaks).save(path)
    return path


def test_cli_without_yes_only_simulates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import main

    path = _selection_file(tmp_path, ["privacy.feedback_frequency"])
    assert main.main(["--demo", "--apply-selection", str(path)]) == 0
    out = capsys.readouterr().out
    assert "+ privacy.feedback_frequency" in out
    assert "Solo simulación" in out
    assert "Sesión" not in out


def test_cli_yes_applies_and_skips_high_risk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import main

    path = _selection_file(tmp_path, ["privacy.feedback_frequency", "security.cpu_mitigations_off"])
    assert main.main(["--demo", "--apply-selection", str(path), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Omitido (riesgo alto, solo desde la interfaz): security.cpu_mitigations_off" in out
    assert "[applied] privacy.feedback_frequency" in out
    assert "security.cpu_mitigations_off: " not in out.split("Sesión")[1]


def test_cli_bad_file_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import main

    bad = tmp_path / "x.json"
    bad.write_text("{}")
    assert main.main(["--demo", "--apply-selection", str(bad)]) == 2
    assert "Error:" in capsys.readouterr().out


def test_cli_requires_windows_without_demo(tmp_path: Path, monkeypatch) -> None:
    import main

    monkeypatch.setattr("sys.platform", "linux")
    assert main.main(["--apply-selection", str(tmp_path / "x.json")]) == 2


def test_task_prefetch_missing_path_falls_back_to_query(runner: FakeRunner) -> None:
    runner.respond_json("foreach ($p in", {r"\A\T1": "Disabled"})  # falta \B\T2
    tasks = TaskManager(runner)
    tasks.prefetch([r"\A\T1", r"\B\T2"])
    calls = len(runner.scripts)
    assert tasks.query(r"\B\T2").status == "Ready"  # consulta individual, no "Unknown"
    assert len(runner.scripts) == calls + 1
