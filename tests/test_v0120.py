"""v0.12.0: interfaz nueva (modo Fácil y Avanzado, nota de salud, iconos)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core import i18n
from core.health import HealthInputs, assess
from core.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_health_matches_the_mockup_laptop() -> None:
    # El portátil del usuario: 134 s de arranque y 3,4 GB de RAM.
    health = assess(HealthInputs(boot_s=134, ram_gib=3.4, ram_percent=82, disk_free_pct=35))
    assert health.score == 60 and health.tone == "warning" and health.label == "MEJORABLE"
    assert health.headline == "Tu PC tarda 2 minutos en arrancar y se queda sin memoria"


def test_health_good_pc_has_positive_headline_even_with_a_detail() -> None:
    perfect = assess(HealthInputs(boot_s=25, ram_gib=16, ram_percent=40, disk_free_pct=60))
    assert perfect.score == 100 and perfect.tone == "ok" and not perfect.issues
    detail = assess(HealthInputs(boot_s=25, ram_gib=16, ram_percent=40, disk_free_pct=15))
    assert detail.tone == "ok" and detail.headline == "Tu PC está en buena forma"
    assert "poco espacio" in detail.detail


def test_health_security_and_floor() -> None:
    bad = assess(
        HealthInputs(
            boot_s=200,
            ram_gib=2,
            ram_percent=95,
            disk_free_pct=3,
            hdd=True,
            security_problems=["Firewall", "Antivirus"],
            reboot_pending=True,
        )
    )
    assert bad.score <= 10 and bad.tone == "critical" and bad.label == "NECESITA AYUDA"
    assert bad.headline.startswith("Tu PC tarda") or "seguridad" in bad.headline
    # Lo más grave va primero: el arranque de 200 s (25) antes que la seguridad (15).
    assert bad.issues[0].startswith("tarda")


def test_health_without_boot_data_does_not_penalize() -> None:
    assert assess(HealthInputs(boot_s=None, ram_gib=16, ram_percent=30)).score == 100


def test_health_in_english() -> None:
    try:
        i18n.set_language("en")
        health = assess(HealthInputs(boot_s=134, ram_gib=3.4, ram_percent=82, disk_free_pct=35))
        assert health.label == "COULD BE BETTER"
        assert health.headline == "Your PC takes 2 minutes to start and runs out of memory"
    finally:
        i18n.set_language("es")


def test_every_icon_renders() -> None:
    from ui.icons import PAINTERS, render

    for name in PAINTERS:
        image = render(name, "#ffffff", 40)
        assert image.size == (40, 40)
        assert image.getbbox() is not None, f"icono vacío: {name}"
    with pytest.raises(KeyError):
        render("no-existe", "#fff", 10)


def test_easy_mode_is_the_default() -> None:
    assert Settings().ui_mode == "easy"


def _module_ast(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"))


def _nav(name: str) -> list[tuple[str | None, str, str]]:
    """Lee EASY_NAV / ADVANCED_NAV de ui/app.py sin importar Tk."""
    for node in _module_ast("ui/app.py").body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == name:
            return ast.literal_eval(node.value)  # type: ignore[arg-type]
    raise AssertionError(name)


def test_both_menus_reach_every_section_they_promise() -> None:
    pages = {
        elt.elts[0].value  # type: ignore[attr-defined]
        for node in _module_ast("ui/app.py").body
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PAGES"
        for elt in node.value.elts  # type: ignore[union-attr]
    }
    easy = {k for k, _l, _i in _nav("EASY_NAV") if k}
    advanced = {k for k, _l, _i in _nav("ADVANCED_NAV") if k}
    assert easy <= pages and advanced <= pages
    # Nada se pierde: el modo Avanzado tiene todas las secciones salvo el Inicio del Fácil.
    assert advanced == pages - {"home"}
    assert {
        "home",
        "diagnostics",
        "startup",
        "space",
        "evolution",
        "privacy",
        "history",
        "settings",
    } == easy
    from ui.icons import PAINTERS

    assert all(i in PAINTERS for _k, _l, i in _nav("EASY_NAV") + _nav("ADVANCED_NAV") if _k)


def test_new_interface_texts_are_translated() -> None:
    en = json.loads((ROOT / "data" / "i18n" / "en.json").read_text(encoding="utf-8"))["ui"]
    for module in ("core/health.py", "ui/pages/home_page.py", "ui/widgets.py", "ui/app.py"):
        for node in ast.walk(_module_ast(module)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value in en, f"{module}: falta {node.args[0].value!r}"
    for _k, label, _i in _nav("EASY_NAV") + _nav("ADVANCED_NAV"):
        assert label in en, f"menú sin traducir: {label}"
    assert en["Inicio"] == "Home"
