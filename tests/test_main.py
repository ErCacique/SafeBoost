"""Modos de línea de comandos sin interfaz: --self-test y --capture-boot."""

from __future__ import annotations

import pytest

import main


def test_self_test_ok(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("tkinter")
    assert main.main(["--self-test"]) == 0
    assert "self-test OK: 74 tweaks" in capsys.readouterr().out


def test_capture_boot_removes_task_when_nothing_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from core.metrics import MetricsStore
    from tests.conftest import FakeRunner

    runner = FakeRunner()
    store = MetricsStore(tmp_path)
    monkeypatch.setattr("core.process.SubprocessRunner", lambda: runner)
    monkeypatch.setattr("core.metrics.MetricsStore", lambda: store)
    assert main.main(["--capture-boot"]) == 0
    assert any("Unregister-ScheduledTask" in s for s in runner.scripts)
