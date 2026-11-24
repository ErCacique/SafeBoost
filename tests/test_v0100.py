"""v0.10.0: prueba de rendimiento, navegadores, modo ahorro, vigilancia en segundo plano, inglés
completo, licencia Técnico, MSIX y utilidades de calidad."""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from core import benchmark, ed25519, i18n
from core.appx import AppxManager
from core.catalog import Catalog
from core.client_report import render_client_html
from core.demo import DemoRunner
from core.engine import Engine
from core.environment import EnvironmentInfo
from core.extensions import Extension, classify, list_extensions
from core.gamemode import BatteryMode
from core.license import (
    Branding,
    LicenseError,
    encode_license,
    load_license,
    parse_license,
    save_license,
    set_logo,
)
from core.registry import MemoryRegistryBackend, Registry
from core.restore import RestoreManager
from core.services import ServiceManager
from core.session import SessionStore
from core.settings import Settings
from core.tasks import TaskManager
from core.tray import GameWatcher, is_game, running_games, schedule_tray
from scripts.make_msix import msix_version, render_manifest
from tests.conftest import FakeRunner
from tests.test_v040 import report
from tweaks import cleanup

ROOT = Path(__file__).resolve().parent.parent
SEED = bytes(range(32))
PUB = ed25519.public_key(SEED)

# --------------------------------------------------------------------------- Ed25519 y licencia


def test_ed25519_rfc8032_vector() -> None:
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pub = ed25519.public_key(seed)
    assert pub.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ed25519.sign(seed, b"")
    assert sig.hex().startswith("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065")
    assert ed25519.verify(pub, b"", sig)
    assert not ed25519.verify(pub, b"x", sig)
    assert not ed25519.verify(pub, b"", bytes(64))


def _license(**overrides: Any) -> str:
    payload = {"n": "Taller Pérez", "e": "", "ed": "tecnico", "iat": "2026-11-22", "exp": None}
    payload.update(overrides)
    return encode_license({**payload, "id": "abc"}, SEED)


def test_license_valid_and_tampered() -> None:
    text = _license()
    lic = parse_license(text, PUB)
    assert lic.holder == "Taller Pérez" and lic.edition_label == "Técnico" and not lic.expires
    prefix, _body, sig = text.split(".")
    forged = json.dumps({"n": "Otro", "ed": "tecnico"}).encode()
    import base64

    fake_body = base64.urlsafe_b64encode(forged).rstrip(b"=").decode()
    with pytest.raises(LicenseError, match="firma"):
        parse_license(f"{prefix}.{fake_body}.{sig}", PUB)
    with pytest.raises(LicenseError, match="ST1"):
        parse_license("hola", PUB)
    with pytest.raises(LicenseError, match="firma"):
        parse_license(text)  # firmada con otra clave: la pública real de SafeBoost no la acepta


def test_license_expiry() -> None:
    text = _license(exp="2026-12-31")
    assert parse_license(text, PUB, today=date(2026, 12, 31)).expires == "2026-12-31"
    with pytest.raises(LicenseError, match="caducó"):
        parse_license(text, PUB, today=date(2027, 1, 1))


def test_license_store_and_branding(tmp_path: Path, monkeypatch: Any) -> None:
    import core.license as lic_mod

    monkeypatch.setattr(lic_mod, "PUBLIC_KEY", PUB)
    monkeypatch.setattr(lic_mod.parse_license, "__defaults__", (PUB, None))
    path = tmp_path / "license.key"
    save_license("  " + _license() + "\n", path)
    assert load_license(path) is not None
    path.write_text("ST1.roto.roto")
    assert load_license(path) is None

    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    branding = Branding(business="Taller Pérez", contact="600 000 000")
    monkeypatch.setattr(lic_mod, "BRANDING_FILE", tmp_path / "branding.json")
    monkeypatch.setattr(lic_mod, "LOGO_FILE", tmp_path / "branding-logo")
    set_logo(logo, branding, tmp_path / "branding-logo")
    assert branding.has_logo
    assert branding.logo_data_uri(tmp_path / "branding-logo").startswith("data:image/png;base64,")
    bad = tmp_path / "logo.gif"
    bad.write_bytes(b"GIF89a")
    with pytest.raises(LicenseError, match="PNG o JPG"):
        set_logo(bad, branding, tmp_path / "x")


def test_client_report_branding() -> None:
    html = render_client_html(
        report(), [], Catalog.load(), branding=Branding(business="Taller <Pérez>", contact="web")
    )
    assert "Taller &lt;Pérez&gt;" in html
    assert "Taller" not in render_client_html(report(), [], Catalog.load())


def test_license_tool_issue_and_verify(tmp_path: Path, capsys: Any) -> None:
    from scripts import license_tool

    key = tmp_path / "k.key"
    assert license_tool.main(["genkey", str(key)]) == 0
    with pytest.raises(SystemExit):
        license_tool.main(["genkey", str(key)])  # no sobrescribe
    capsys.readouterr()
    # Con una clave que no es la de SafeBoost, emitir avisa en vez de dar una licencia inútil.
    with pytest.raises(SystemExit, match="no corresponde"):
        license_tool.main(["issue", "--key", str(key), "--name", "X"])
    assert license_tool.main(["verify", "ST1.a.b"]) == 1


# --------------------------------------------------------------------------- modo ahorro


def _demo_engine(tmp_path: Path, has_battery: bool = True) -> Engine:
    backend = MemoryRegistryBackend()
    runner = DemoRunner(backend)
    env = EnvironmentInfo(
        build=22631, edition="home", chassis="laptop", has_battery=has_battery, is_admin=True
    )
    registry = Registry(backend)
    return Engine(
        catalog=Catalog.load(),
        env=env,
        registry=registry,
        runner=runner,
        services=ServiceManager(registry, runner),
        appx=AppxManager(runner),
        tasks=TaskManager(runner),
        restore=RestoreManager(registry, runner, env.system_drive),
        store=SessionStore(tmp_path / "sessions"),
        settings=Settings(dry_run=False),
    )


def test_battery_mode_applies_dc_values_and_reverts(tmp_path: Path) -> None:
    engine = _demo_engine(tmp_path)
    runner: Any = engine.runner
    mode = BatteryMode(engine, tmp_path)
    assert mode.available() and set(mode.candidates()) == set(mode.tweaks)
    session = mode.start()
    assert session is not None and mode.active
    assert runner._dc == {"esbattthreshold": 50, "procthrottlemax": 80, "videoidle": 180}
    assert all(engine.detect(engine.catalog.get(t)).state.value == "applied" for t in mode.tweaks)
    mode.stop()
    assert not mode.active
    assert runner._dc == {"esbattthreshold": 20, "procthrottlemax": 100, "videoidle": 300}


def test_battery_tweaks_need_a_battery(tmp_path: Path) -> None:
    engine = _demo_engine(tmp_path, has_battery=False)
    assert BatteryMode(engine, tmp_path).candidates() == []


# --------------------------------------------------------------------------- navegadores


def _chromium_ext(root: Path, ext_id: str, manifest: dict, messages: dict | None = None) -> None:
    version = root / "Default" / "Extensions" / ext_id / "1.0_0"
    version.mkdir(parents=True)
    (root / "Default" / "Preferences").write_text("{}")
    (version / "manifest.json").write_text(json.dumps(manifest))
    if messages:
        loc = version / "_locales" / "en"
        loc.mkdir(parents=True)
        (loc / "messages.json").write_text(json.dumps(messages))


def test_extensions_chromium_and_firefox(tmp_path: Path) -> None:
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    chrome = local / "Google" / "Chrome" / "User Data"
    _chromium_ext(
        chrome,
        "aaaa",
        {
            "name": "__MSG_appName__",
            "version": "2.1",
            "default_locale": "en",
            "permissions": ["storage"],
            "host_permissions": ["<all_urls>"],
        },
        {"appName": {"message": "uBlock Origin"}},
    )
    _chromium_ext(chrome, "bbbb", {"name": "Super Coupon Finder", "version": "1"})
    ff = roaming / "Mozilla" / "Firefox" / "Profiles" / "x.default"
    ff.mkdir(parents=True)
    (ff / "extensions.json").write_text(
        json.dumps(
            {
                "addons": [
                    {
                        "id": "a@b",
                        "type": "extension",
                        "location": "app-profile",
                        "version": "3",
                        "defaultLocale": {"name": "Dark Reader"},
                        "userPermissions": {"origins": ["<all_urls>"]},
                    },
                    {"id": "sys@mozilla", "type": "extension", "location": "app-system-defaults"},
                ]
            }
        )
    )
    found = {e.name: e for e in list_extensions(local, roaming)}
    assert set(found) == {"uBlock Origin", "Super Coupon Finder", "Dark Reader"}
    assert found["uBlock Origin"].all_sites and found["uBlock Origin"].version == "2.1"
    assert "anuncios" in " ".join(found["Super Coupon Finder"].warnings)
    assert found["Dark Reader"].browser == "Firefox" and found["Dark Reader"].all_sites
    # Los sospechosos van primero.
    assert next(iter(list_extensions(local, roaming))).suspicious


def test_extension_classification_is_not_too_eager() -> None:
    plain = classify(Extension("Chrome", "", "x", "Google Translate"))
    assert not plain.suspicious
    assert classify(Extension("Edge", "", "y", "PDF Converter Pro")).warnings


def test_browser_cache_skips_open_browsers(tmp_path: Path, monkeypatch: Any) -> None:
    for rel in (r"Google\Chrome\User Data", r"Microsoft\Edge\User Data"):
        cache = tmp_path.joinpath(*rel.split("\\"), "Default", "Cache", "Cache_Data")
        cache.mkdir(parents=True)
        (cache / "f_000001").write_bytes(b"x" * 1000)
    caches = cleanup.browser_caches(tmp_path)
    assert set(caches) == {"Chrome", "Edge"}
    assert cleanup.folder_bytes(caches["Chrome"]) == 1000
    monkeypatch.setattr(cleanup, "_running_browsers", lambda: {"Edge"})
    monkeypatch.setattr(cleanup, "user_local_appdata", lambda _ctx: tmp_path)
    targets, skipped = cleanup._browser_targets(None)  # type: ignore[arg-type]
    assert skipped == ["Edge"] and len(targets) == 1


# --------------------------------------------------------------------------- rendimiento


def test_benchmark_runs_and_stores(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(benchmark, "DISK_MB", 4)
    monkeypatch.setattr(benchmark, "RANDOM_SECONDS", 0.05)
    monkeypatch.setattr(benchmark, "CPU_ROUNDS", 1)
    monkeypatch.setattr(benchmark, "CPU_BLOCK", 1024 * 1024)
    steps: list[str] = []
    runner = DemoRunner()
    result = benchmark.run_benchmark(runner, tmp_path, lambda _f, s: steps.append(s))
    assert result.errors == []
    assert result.disk_write_mbs and result.disk_read_mbs and result.disk_random_iops
    assert result.cpu_single_mbs and result.cpu_multi_mbs and result.threads >= 1
    assert result.apps_ms == {"notepad.exe": 420, "mspaint.exe": 1310}
    assert len(steps) == 3 and not list(tmp_path.glob("safeboost-bench-*"))
    store = benchmark.BenchStore(tmp_path / "b.json")
    store.add(result)
    store.add(result)
    assert len(store.load()) == 2


def test_benchmark_change_pct() -> None:
    assert benchmark.change_pct(100, 150) == 50
    assert benchmark.change_pct(1000, 500, higher_is_better=False) == 50
    assert benchmark.change_pct(None, 5) is None


# --------------------------------------------------------------------------- vigilancia


def test_game_detection() -> None:
    assert is_game(r"D:\SteamLibrary\steamapps\common\Hades\Hades.exe")
    assert is_game(r"C:\Program Files\Epic Games\Fortnite\FortniteClient.exe")
    assert not is_game(r"C:\Program Files (x86)\Steam\steam.exe")
    assert not is_game(r"C:\Program Files\Epic Games\Launcher\EpicGamesLauncher.exe")
    assert not is_game(r"C:\Windows\explorer.exe")
    procs = [("Hades.exe", r"D:\steamapps\common\Hades\Hades.exe"), ("x.exe", "")]
    assert running_games(procs) == ["Hades.exe"]


def test_game_watcher_only_stops_what_it_started() -> None:
    w = GameWatcher(grace_s=30)
    assert w.tick(["g.exe"], mode_active=False, now=0) == "start"
    w.auto_started = True
    assert w.tick(["g.exe"], mode_active=True, now=10) is None
    assert w.tick([], mode_active=True, now=20) is None  # aún dentro del margen
    assert w.tick([], mode_active=True, now=41) == "stop"
    # Si el usuario ya tenía el modo juego activo, la vigilancia no lo apaga.
    manual = GameWatcher()
    assert manual.tick(["g.exe"], mode_active=True, now=0) is None
    assert manual.tick([], mode_active=True, now=100) is None
    # Si el usuario lo apagó a mano mientras jugaba, no se vuelve a encender en esa partida.
    w2 = GameWatcher(auto_started=True)
    assert w2.tick([], mode_active=False, now=0) is None and not w2.auto_started


def test_tray_task_script() -> None:
    runner = FakeRunner()
    assert schedule_tray(runner, [r"C:\SafeBoost\SafeBoost.exe"], "PC\\Ana")
    script = runner.scripts[-1]
    assert "-Argument '--tray'" in script and "-AtLogOn -User 'PC\\Ana'" in script
    assert "-RunLevel Highest" in script and "\\SafeBoost\\" in script


def test_settings_defaults_keep_nothing_resident() -> None:
    settings = Settings()
    assert settings.background_watch is False and settings.auto_game_mode is False


# --------------------------------------------------------------------------- inglés


def test_every_tweak_fully_translated() -> None:
    try:
        i18n.set_language("en")
        for tweak in Catalog.load().tweaks:
            for field in ("description", "rationale"):
                translated = i18n.tweak_text(tweak.id, field, "")
                assert translated and translated != getattr(tweak, field), (tweak.id, field)
            if tweak.revert_note:
                assert i18n.tweak_text(tweak.id, "revert_note", ""), tweak.id
    finally:
        i18n.set_language("es")


def test_diagnostic_texts_have_translations() -> None:
    en = json.loads((ROOT / "data" / "i18n" / "en.json").read_text(encoding="utf-8"))["ui"]
    for module in ("core/diagnostics.py", "core/hardware.py"):
        tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value in en, f"{module}: falta traducir {node.args[0].value!r}"


def test_verdict_in_english() -> None:
    try:
        i18n.set_language("en")
        from tests.test_v040 import analyze

        rep = report()
        rep.snapshot.ram_percent = 95
        titles = {f.title for f in analyze(rep)}
        assert "Memory almost full" in titles or "Low RAM" in titles
    finally:
        i18n.set_language("es")


# --------------------------------------------------------------------------- MSIX


def test_msix_manifest() -> None:
    assert msix_version("0.10.0") == "0.10.0.0"
    with pytest.raises(ValueError):
        msix_version("1.0")
    xml = render_manifest(
        "1.2.3", {"identity_name": "A.B", "publisher": "CN=X", "publisher_display_name": "Y"}
    )
    assert 'Version="1.2.3.0"' in xml and 'Publisher="CN=X"' in xml and "{{" not in xml
    assert "allowElevation" in xml and "runFullTrust" in xml
