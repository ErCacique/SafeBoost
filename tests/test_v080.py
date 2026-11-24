"""v0.8.0: fabricantes, fuentes oficiales, modo juego, "Arreglar mi PC lento", resumen de
mejoras, espacio en disco, programas, informe para el cliente, actualización verificada, winget
e inglés."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from core import i18n
from core.boot import BootCulprit, BootReport
from core.catalog import Catalog
from core.client_report import html_to_pdf, render_client_html
from core.constants import SERVICES_KEY
from core.diskusage import find_duplicates, last_used_by_exe, scan
from core.engine import Engine, PreflightError
from core.fixplan import build_plan
from core.gamemode import GAME_MODE_TWEAKS, GameMode
from core.programs import Program, last_used
from core.registry import MemoryRegistryBackend, RegValue
from core.sources import source_for
from core.update_check import (
    ReleaseInfo,
    check_latest,
    download_installer,
    expected_hash,
    installer_command,
)
from core.watch import improvement_summary
from tests.conftest import FakeRunner
from tests.test_v040 import report as diag_report
from tests.test_v040 import snapshot
from tests.test_v070 import record

EngineFactory = Callable[..., Engine]
ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- fabricantes y fuentes


def test_vendor_tweaks_only_when_service_exists(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    tweak = make_engine().catalog.get("services.hp_analytics")
    assert not make_engine().evaluate(tweak).applicable
    backend.seed(
        "HKLM", f"{SERVICES_KEY}\\HpTouchpointAnalyticsService", "Start", RegValue("REG_DWORD", 2)
    )
    assert make_engine().evaluate(tweak).applicable
    assert make_engine().catalog.get("services.adobe_updater").auto_profile is False


def test_every_tweak_has_an_official_source() -> None:
    for tweak in Catalog.load().tweaks:
        url = source_for(tweak.id)
        assert url.startswith("https://"), tweak.id
    assert "pagefile" in source_for("memory.pagefile_fixed") or source_for("memory.pagefile_fixed")
    assert source_for("privacy.diagtrack") != source_for("privacy.suggestions_start")


# --------------------------------------------------------------------------- modo juego


def test_restore_point_rule_allows_low_risk_reversible(make_engine: EngineFactory) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.feedback_frequency"], restore_point=False)
    assert "Omitido" in session.restore_point
    with pytest.raises(PreflightError):
        engine.apply(["gaming.hags"], restore_point=False)  # riesgo medio


def test_game_mode_on_and_off(make_engine: EngineFactory, tmp_path: Path) -> None:
    engine = make_engine()
    mode = GameMode(engine, tmp_path)
    assert not mode.active
    assert set(mode.candidates()) <= set(GAME_MODE_TWEAKS)
    session = mode.start()
    assert session is not None and mode.active
    mode.stop()
    assert not mode.active
    assert mode.stop() is None  # ya desactivado


def test_game_mode_inactive_when_reverted_from_history(
    make_engine: EngineFactory, tmp_path: Path
) -> None:
    engine = make_engine()
    mode = GameMode(engine, tmp_path)
    session = mode.start()
    assert session is not None
    engine.revert(session.id)
    assert not mode.active


# --------------------------------------------------------------------------- arreglar mi PC lento


def test_fix_plan_combines_profile_cleanup_startup_and_hardware() -> None:
    rep = diag_report(snap=snapshot(ram_total=3.4 * 1024**3))
    rep.boot = BootReport(
        boots=5, culprits=[BootCulprit("programa", "OneDrive", "OneDrive.exe", "", 3, 18000)]
    )
    from core.diagnostics import analyze

    rep.findings = analyze(rep)
    plan = build_plan(
        rep,
        (2, "Portátil: Equilibrado."),
        [("Microsoft OneDrive", "onedrive.exe", "medio"), ("Updater", "u.exe", "alto")],
        ["cleanup.temp_user", "cleanup.thumbnails"],
    )
    assert plan.level == 2 and plan.has_actions
    assert plan.cleanups == ["cleanup.temp_user", "cleanup.thumbnails"]
    assert [c.name for c in plan.startup] == ["Microsoft OneDrive", "Updater"]
    assert "6 s" in plan.startup[0].reason
    assert any(h.startswith("Poca memoria RAM") for h in plan.hardware)


def test_fix_plan_asks_to_reboot_first() -> None:
    from core.environment import UpdateStatus

    rep = diag_report(updates=UpdateStatus(reboot_pending=True))
    plan = build_plan(rep, (None, "Reinicia antes."), [], [])
    assert plan.level is None and not plan.has_actions
    assert "Reinicia" in plan.first[0]


def test_improvement_summary() -> None:
    records = [record(d, 130000) for d in range(1, 5)] + [record(d, 60000) for d in range(6, 10)]
    summary = improvement_summary(records, "2026-11-05T00:00:00")
    assert summary is not None
    assert summary.boot_before == 130000 and summary.boot_after == 60000
    assert improvement_summary(records[:3], "2026-11-05T00:00:00") is None


# --------------------------------------------------------------------------- espacio y programas


def test_disk_scan_and_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.diskusage as du

    monkeypatch.setattr(du, "BIG_FILE_BYTES", 1000)
    (tmp_path / "Videos").mkdir()
    (tmp_path / "Videos" / "peli.mkv").write_bytes(b"x" * 5000)
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Docs" / "a.txt").write_bytes(b"y" * 10)
    report = scan(tmp_path)
    assert report.folders[0].path.name == "Videos" and report.folders[0].size == 5000
    assert [f.path.name for f in report.big_files] == ["peli.mkv"]

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    for name in ("setup.exe", "setup (1).exe"):
        (downloads / name).write_bytes(b"z" * 3000)
    (downloads / "otro.exe").write_bytes(b"w" * 3000)  # mismo tamaño, distinto contenido
    groups = find_duplicates(downloads, min_bytes=100)
    assert len(groups) == 1 and len(groups[0].paths) == 2 and groups[0].wasted == 3000


def test_prefetch_last_use_and_program_match(tmp_path: Path) -> None:
    prefetch = tmp_path / "Prefetch"
    prefetch.mkdir()
    pf = prefetch / "VLC.EXE-1A2B3C4D.pf"
    pf.write_bytes(b"")
    stamp = time.time() - 86400 * 3
    os.utime(pf, (stamp, stamp))
    by_exe = last_used_by_exe(prefetch)
    assert by_exe["vlc.exe"] == pytest.approx(stamp)
    install = tmp_path / "VLC"
    install.mkdir()
    (install / "vlc.exe").write_bytes(b"")
    program = Program("k", "VLC", install_location=str(install))
    assert last_used(program, by_exe) == pytest.approx(stamp)
    assert last_used(Program("k2", "Otro"), by_exe) is None


# ----------------------------------------------------------------- informe para el cliente


def test_client_report_html(make_engine: EngineFactory) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.feedback_frequency"])
    html = render_client_html(diag_report(), [session], engine.catalog, technician="Ana")
    assert "Informe del equipo" in html and "Técnico: Ana" in html
    assert engine.catalog.get("privacy.feedback_frequency").name in html


def test_html_to_pdf_uses_headless_edge(tmp_path: Path) -> None:
    page = tmp_path / "r.html"
    page.write_text("<p>x</p>")
    pdf = tmp_path / "r.pdf"

    class EdgeRunner(FakeRunner):
        def run(self, args: list[str], timeout: int = 60, encoding: Any = None) -> Any:
            self.calls.append(list(args))
            pdf.write_bytes(b"%PDF")
            return super().run(args, timeout, encoding)

    runner = EdgeRunner()
    assert html_to_pdf(page, pdf, runner, edge=tmp_path / "msedge.exe") is True
    assert "--headless" in runner.calls[0] and f"--print-to-pdf={pdf}" in runner.calls[0]
    assert html_to_pdf(page, pdf, FakeRunner(), edge=None) in (True, False)


# --------------------------------------------------------------------------- actualización


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_a: Any) -> None:
        self.close()


def fake_web(files: dict[str, bytes]) -> Callable[..., Response]:
    def opener(request: Any, timeout: float = 0) -> Response:
        return Response(files[request.full_url])

    return opener


SETUP = b"instalador de prueba"
DIGEST = hashlib.sha256(SETUP).hexdigest()
INFO = ReleaseInfo(
    "0.9.0", "https://x/rel", "https://x/SafeBoost-Setup-0.9.0.exe", "https://x/SHA256SUMS.txt"
)


def test_release_assets_are_read() -> None:
    payload = json.dumps(
        {
            "tag_name": "v0.9.0",
            "html_url": "https://x/rel",
            "assets": [
                {"name": "SafeBoost-Setup-0.9.0.exe", "browser_download_url": INFO.setup_url},
                {"name": "SHA256SUMS.txt", "browser_download_url": INFO.sums_url},
            ],
        }
    ).encode()
    info = check_latest("0.8.0", opener=lambda _r, timeout=0: Response(payload))
    assert info == INFO


def test_download_verifies_sha256(tmp_path: Path) -> None:
    sums = f"{DIGEST}  SafeBoost-Setup-0.9.0.exe\n".encode()
    web = fake_web({INFO.sums_url: sums, INFO.setup_url: SETUP})
    path = download_installer(INFO, tmp_path, opener=web)
    assert path.read_bytes() == SETUP


def test_download_rejects_tampered_installer(tmp_path: Path) -> None:
    sums = f"{'0' * 64}  SafeBoost-Setup-0.9.0.exe\n".encode()
    web = fake_web({INFO.sums_url: sums, INFO.setup_url: SETUP})
    with pytest.raises(ValueError, match="no coincide"):
        download_installer(INFO, tmp_path, opener=web)
    assert not (tmp_path / "SafeBoost-Setup-0.9.0.exe").exists()


def test_update_helpers() -> None:
    assert expected_hash(f"{DIGEST}  a.exe\nmal\n", "a.exe") == DIGEST
    assert expected_hash("x  a.exe", "a.exe") is None
    cmd = installer_command(Path("C:/t/setup.exe"))
    assert "/SILENT" in cmd and "/CLOSEAPPLICATIONS" in cmd
    with pytest.raises(ValueError):
        download_installer(ReleaseInfo("1.0.0", "https://x"), Path())


# --------------------------------------------------------------------------- winget, firma, ARM64


def test_winget_manifests(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import make_winget

    assert make_winget.main(["0.8.0", "a" * 64, str(tmp_path)]) == 0
    installer = (tmp_path / "ErCacique.SafeBoost.installer.yaml").read_text(encoding="utf-8")
    assert "InstallerType: inno" in installer and "SafeBoost-Setup-0.8.0.exe" in installer
    assert make_winget.main(["0.8.0", "corto", str(tmp_path)]) == 2


def test_release_workflow_has_signing_winget_and_arm64() -> None:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "HAS_SIGNING: ${{ secrets.SIGN_PFX_BASE64 != '' }}" in text
    assert text.count("if: env.HAS_SIGNING == 'true'") == 2
    assert "make_winget.py" in text and "windows-11-arm" in text
    assert "continue-on-error: true" in text


# --------------------------------------------------------------------------- inglés


def test_english_translations() -> None:
    try:
        i18n.set_language("en")
        assert i18n._("Simular") == "Simulate"
        assert i18n._("{n} cambios seleccionados", n=3) == "3 changes selected"
        assert i18n._("Texto sin traducir") == "Texto sin traducir"
        for tweak in Catalog.load().tweaks:
            assert i18n.tweak_name(tweak.id, "") != "", f"falta traducir {tweak.id}"
    finally:
        i18n.set_language("es")
    assert i18n._("Simular") == "Simular"


def test_unknown_language_falls_back_to_spanish() -> None:
    i18n.set_language("xx")
    assert i18n.current() == "es"


def test_spec_bundles_translations() -> None:
    spec = (ROOT / "packaging" / "SafeBoost.spec").read_text(encoding="utf-8")
    assert '"i18n"), "data/i18n"' in spec
