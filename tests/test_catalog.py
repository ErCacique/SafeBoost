"""Validación del catálogo y selección por perfil."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from core.catalog import Catalog, evaluate, profile_selection, structural_errors
from core.environment import EnvironmentInfo
from scripts.validate_tweaks import validate

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data" / "tweaks.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "data" / "tweaks.schema.json").read_text(encoding="utf-8"))


def schema_errors(data: dict) -> list[str]:
    return [e.message for e in Draft202012Validator(SCHEMA).iter_errors(data)]


def test_catalog_is_valid() -> None:
    assert validate(ROOT / "data" / "tweaks.json") == []


@pytest.mark.parametrize("field", ["apply", "revert", "detect"])
def test_schema_rejects_missing_required_action(field: str) -> None:
    broken = copy.deepcopy(DATA)
    del broken["tweaks"][0][field]
    assert schema_errors(broken)
    assert any(field in e for e in structural_errors(broken))


def test_schema_rejects_irreversible_in_auto_profile() -> None:
    broken = copy.deepcopy(DATA)
    tweak = next(t for t in broken["tweaks"] if t["kind"] == "tweak")
    tweak["reversible"] = False
    tweak["revert_note"] = "x"
    tweak["auto_profile"] = True
    assert schema_errors(broken)
    assert structural_errors(broken)


def test_schema_rejects_high_risk_in_auto_profile() -> None:
    broken = copy.deepcopy(DATA)
    broken["tweaks"][0]["risk"] = "alto"
    assert schema_errors(broken)


def test_unknown_operation_rejected() -> None:
    broken = copy.deepcopy(DATA)
    broken["tweaks"][0]["apply"] = [{"op": "format_disk"}]
    assert schema_errors(broken)


def test_cpu_mitigations_require_double_confirmation() -> None:
    tweak = Catalog.load().get("security.cpu_mitigations_off")
    assert tweak.risk == "alto"
    assert tweak.confirm_double
    assert not tweak.auto_profile


def test_all_actions_are_irreversible_and_explained() -> None:
    for tweak in Catalog.load().tweaks:
        if tweak.is_action:
            assert not tweak.reversible
            assert tweak.revert_note


def test_profiles_are_cumulative(env: EnvironmentInfo) -> None:
    catalog = Catalog.load()
    no_check = lambda _ref: False  # noqa: E731
    l1 = set(profile_selection(catalog, env, 1, no_check))
    l2 = set(profile_selection(catalog, env, 2, no_check))
    l3 = set(profile_selection(catalog, env, 3, no_check))
    assert l1 < l2 < l3
    assert all(catalog.get(t).level == 1 for t in l1)


def test_profiles_never_include_manual_or_high_risk(env: EnvironmentInfo) -> None:
    catalog = Catalog.load()
    selected = profile_selection(catalog, env, 3, lambda _ref: True)
    for tid in selected:
        tweak = catalog.get(tid)
        assert tweak.auto_profile
        assert tweak.risk != "alto"
    assert "security.cpu_mitigations_off" not in selected
    assert "network.dns" not in selected
    assert "power.hibernate_off" not in selected


def test_sysmain_only_on_ssd(env: EnvironmentInfo) -> None:
    tweak = Catalog.load().get("services.sysmain")
    assert evaluate(tweak, env, 2).preselect
    env.disk_type = "hdd"
    result = evaluate(tweak, env, 2)
    assert not result.applicable
    assert "SSD" in result.reasons[0]


def test_high_performance_preselected_only_on_desktop(env: EnvironmentInfo) -> None:
    tweak = Catalog.load().get("power.high_performance")
    assert evaluate(tweak, env, 2).preselect
    env.chassis = "laptop"
    result = evaluate(tweak, env, 2)
    assert result.applicable
    assert not result.preselect


def test_spooler_excluded_with_printers(env: EnvironmentInfo) -> None:
    tweak = Catalog.load().get("services.spooler")
    env.printers = ["HP LaserJet"]
    assert not evaluate(tweak, env, 3).applicable


def test_managed_device_excludes_policy_only_tweaks(env: EnvironmentInfo) -> None:
    catalog = Catalog.load()
    env.domain_joined = True
    assert not evaluate(catalog.get("bloatware.news_interests"), env, 1).applicable
    assert not evaluate(catalog.get("privacy.dmwappush"), env, 1).applicable
    # Mezcla de valor de usuario + directiva: sigue aplicable (la directiva se omite).
    assert evaluate(catalog.get("privacy.advertising_id"), env, 1).applicable


def test_edition_specific_telemetry(env: EnvironmentInfo) -> None:
    catalog = Catalog.load()
    assert evaluate(catalog.get("privacy.telemetry_policy_required"), env, 1).applicable
    assert not evaluate(catalog.get("privacy.telemetry_policy_security"), env, 1).applicable
    env.edition = "enterprise"
    assert evaluate(catalog.get("privacy.telemetry_policy_security"), env, 1).applicable


def test_build_window(env: EnvironmentInfo) -> None:
    tweak = Catalog.load().get("bloatware.copilot_policy")
    env.build = 26100
    assert not evaluate(tweak, env, 1).applicable
    env.build = 22631
    assert evaluate(tweak, env, 1).applicable


def test_unknown_edition_excludes_edition_specific_tweaks(env: EnvironmentInfo) -> None:
    """Regresión (detectada por el e2e en Windows Server): con edición desconocida se
    aplicaban a la vez los dos tweaks de telemetría, que son excluyentes."""
    catalog = Catalog.load()
    env.edition = "unknown"
    assert not evaluate(catalog.get("privacy.telemetry_policy_required"), env, 1).applicable
    assert not evaluate(catalog.get("privacy.telemetry_policy_security"), env, 1).applicable
    assert evaluate(catalog.get("privacy.advertising_id"), env, 1).applicable


def _scope_overlaps(a: dict, b: dict) -> bool:
    wa, wb = a["windows"], b["windows"]
    if not set(wa["editions"]) & set(wb["editions"]):
        return False
    lo = max(wa["min_build"], wb["min_build"])
    hi = min(wa["max_build"] or 10**9, wb["max_build"] or 10**9)
    return lo <= hi


def test_no_conflicting_registry_writes_in_same_scope() -> None:
    """Dos tweaks que escriben el mismo valor con datos distintos deben ser excluyentes
    (por edición o por build); si no, aplicarlos juntos deja un estado imprevisible."""
    writes: dict[tuple[str, str, str], list[tuple[dict, object]]] = {}
    for tweak in DATA["tweaks"]:
        for op in tweak["apply"]:
            if op["op"] == "registry_set":
                key = (op["hive"], op["path"].lower(), op["name"].lower())
                writes.setdefault(key, []).append((tweak, op["value"]))
    conflicts = []
    for key, entries in writes.items():
        for i, (ta, va) in enumerate(entries):
            for tb, vb in entries[i + 1 :]:
                if va != vb and _scope_overlaps(ta, tb):
                    conflicts.append(f"{ta['id']} y {tb['id']} escriben {key} distinto")
    assert not conflicts, conflicts
