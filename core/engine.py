"""Motor de WinTune: detección, simulación, aplicación por sesión y reversión.

Principios:
- Un fallo en un tweak (o en una operación) no aborta el resto.
- Cada cambio se registra con su estado previo antes de pasar al siguiente.
- La sesión se guarda en disco tras cada tweak, así sobrevive a un cierre inesperado.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from core.appx import AppxError, AppxManager
from core.catalog import Applicability, Catalog, Tweak, evaluate, is_policy_op
from core.constants import ALLOWED_COMMAND_EXES, SC_START_ARG
from core.context import (
    DetectResult,
    DetectState,
    HandlerContext,
    HandlerError,
    SkipOperation,
    resolve_handler,
)
from core.environment import EnvironmentInfo
from core.logger import get_logger
from core.process import CommandError, Runner
from core.protection import ProtectionError, ProtectionGuard
from core.registry import Registry, RegistryError, RegValue, export_key, values_equal
from core.restore import RestoreManager
from core.services import ServiceError, ServiceManager
from core.session import Session, SessionStore, TweakResult
from core.settings import Settings
from core.tasks import TaskError, TaskManager

log = get_logger("engine")

ProgressFn = Callable[[float, str], None]
Outcome = Literal["changed", "unchanged", "skipped"]

# Errores esperables de una operación: se registran como fallo del tweak, no se propagan.
OP_ERRORS: tuple[type[BaseException], ...] = (
    AppxError,
    CommandError,
    HandlerError,
    OSError,
    ProtectionError,
    RegistryError,
    ServiceError,
    TaskError,
    ValueError,
    KeyError,
)


class PreflightError(RuntimeError):
    """No se cumplen las condiciones para aplicar (admin, punto de restauración...)."""


@dataclass(frozen=True)
class DriftItem:
    tweak_id: str
    session_id: str
    state: DetectState
    detail: str = ""


@dataclass
class PlanItem:
    tweak: Tweak
    applicability: Applicability
    lines: list[str] = field(default_factory=list)
    already_applied: bool = False
    error: str = ""


def _noop_progress(_fraction: float, _message: str) -> None:
    return None


class Engine:
    def __init__(
        self,
        catalog: Catalog,
        env: EnvironmentInfo,
        registry: Registry,
        runner: Runner,
        services: ServiceManager,
        appx: AppxManager,
        tasks: TaskManager,
        restore: RestoreManager,
        store: SessionStore,
        settings: Settings,
    ) -> None:
        self.catalog = catalog
        self.env = env
        self.registry = registry
        self.runner = runner
        self.services = services
        self.appx = appx
        self.tasks = tasks
        self.restore = restore
        self.store = store
        self.settings = settings
        self.guard = ProtectionGuard(env, services)
        self._check_cache: dict[str, bool] = {}
        self._check_lock = threading.Lock()
        self._lock = threading.Lock()

    # ================================================================== contexto

    def _ctx(
        self,
        tweak: Tweak,
        dry_run: bool,
        session: Session | None = None,
        params: dict[str, Any] | None = None,
        prior: Session | None = None,
    ) -> HandlerContext:
        merged = {k: v.get("default") for k, v in tweak.params.items()}
        merged.update(params or {})
        ctx = HandlerContext(
            tweak=tweak,
            env=self.env,
            registry=self.registry,
            runner=self.runner,
            services=self.services,
            guard=self.guard,
            dry_run=dry_run,
            params=merged,
            session=session,
            prior_session=prior,
        )
        if session is not None:
            ctx.state = session.handler_state.setdefault(tweak.id, {})
        if prior is not None:
            ctx.prior_state = prior.handler_state.get(tweak.id, {})
        return ctx

    def check(self, ref: str) -> bool:
        """Resuelve condiciones requires.check (p. ej. soporte de HAGS). Se cachea."""
        with self._check_lock:
            if ref not in self._check_cache:
                func = resolve_handler(ref)
                dummy = self.catalog.tweaks[0]
                self._check_cache[ref] = bool(func(self._ctx(dummy, dry_run=True)))
            return self._check_cache[ref]

    def warm_checks(self) -> None:
        """Ejecuta todas las comprobaciones de hardware del catálogo y las deja en caché.

        Algunas son lentas (dxdiag tarda hasta 90 s): se llama desde el hilo de arranque para
        que la interfaz nunca las dispare desde el hilo de Tk al evaluar un tweak.
        """
        refs = {t.requires["check"] for t in self.catalog.tweaks if t.requires.get("check")}
        for ref in sorted(refs):
            try:
                self.check(ref)
            except Exception as exc:  # noqa: BLE001 - un check roto equivale a "no soportado"
                log.warning("check_failed", extra={"ref": ref, "err": str(exc)})
                with self._check_lock:
                    self._check_cache[ref] = False

    def evaluate(self, tweak: Tweak, level: int = 3) -> Applicability:
        return evaluate(tweak, self.env, level, self.check)

    # ================================================================== detección

    def detect(self, tweak: Tweak) -> DetectResult:
        applicability = self.evaluate(tweak)
        if not applicability.applicable:
            return DetectResult(DetectState.NOT_APPLICABLE, "; ".join(applicability.reasons))
        ctx = self._ctx(tweak, dry_run=True)
        partial: list[bool | None] = []
        for op in tweak.detect:
            try:
                kind = op["op"]
                if kind == "match_apply":
                    partial.extend(self._check_op(a, ctx) for a in tweak.apply)
                elif kind == "registry_equals":
                    target = self.registry.read(op["hive"], op["path"], op["name"])
                    expected = RegValue.from_catalog(
                        "REG_DWORD" if isinstance(op["value"], int) else "REG_SZ", op["value"]
                    )
                    partial.append(values_equal(target, expected))
                elif kind == "handler":
                    ctx.params.update(op.get("params", {}))
                    result = resolve_handler(op["ref"])(ctx)
                    if isinstance(result, DetectResult):
                        return result
                    partial.append(bool(result))
            except OP_ERRORS as exc:
                log.warning("detect_failed", extra={"tweak": tweak.id, "err": str(exc)})
                return DetectResult(DetectState.UNKNOWN, str(exc))
        if not any(c is not None for c in partial) and all(
            op["op"] == "appx_remove" for op in tweak.apply
        ):
            return DetectResult(DetectState.APPLIED, "No instalado")
        return combine_checks(partial)

    def prefetch(self, tweaks: list[Tweak]) -> None:
        """Precarga en bloque lo que la detección consultaría uno a uno (tareas y AppX)."""
        paths = [op["path"] for tweak in tweaks for op in tweak.apply if op["op"] == "task_state"]
        self.tasks.prefetch(paths)
        if any(op["op"] == "appx_remove" for tweak in tweaks for op in tweak.apply):
            try:
                self.appx.inventory(refresh=True)
            except AppxError as exc:
                log.warning("appx_prefetch_failed", extra={"err": str(exc)})

    def drift(self) -> list[DriftItem]:
        """Tweaks aplicados en sesiones vigentes que ya no están aplicados (deriva).

        Las actualizaciones de Windows suelen revertir ajustes y reinstalar apps. Se mira la
        sesión más reciente de cada tweak; las sesiones deshechas no cuentan.
        """
        self.tasks.clear_cache()
        candidates: list[tuple[Tweak, str]] = []
        seen: set[str] = set()
        for session in self.store.list():  # de más reciente a más antigua
            if session.kind != "apply" or session.reverted_by:
                continue
            for tid, result in session.results.items():
                if tid in seen or tid not in self.catalog:
                    continue
                if result.status not in ("applied", "partial"):
                    continue
                seen.add(tid)
                tweak = self.catalog.get(tid)
                if not tweak.is_action:
                    candidates.append((tweak, session.id))
        self.prefetch([t for t, _ in candidates])
        items: list[DriftItem] = []
        for tweak, session_id in candidates:
            result = self.detect(tweak)
            if result.state in (DetectState.NOT_APPLIED, DetectState.PARTIAL):
                items.append(DriftItem(tweak.id, session_id, result.state, result.detail))
        log.info("drift", extra={"count": len(items)})
        return items

    def _check_op(self, op: dict[str, Any], ctx: HandlerContext) -> bool | None:
        """¿Está esta operación de apply en su estado objetivo? None = no evaluable."""
        kind = op["op"]
        if kind == "registry_set":
            if is_policy_op(op) and self.env.managed:
                return None
            target = RegValue.from_catalog(op["kind"], op["value"])
            return values_equal(self.registry.read(op["hive"], op["path"], op["name"]), target)
        if kind == "registry_delete":
            return self.registry.read(op["hive"], op["path"], op["name"]) is None
        if kind == "service_start":
            state = self.services.state(op["name"])
            return None if not state.exists else state.start == op["start"]
        if kind == "task_state":
            info = self.tasks.query(op["path"])
            return None if not info.exists else info.enabled == op["enabled"]
        if kind == "appx_remove":
            # Ausente = nada que hacer (None); presente = pendiente. Ver detect().
            return False if self.appx.inventory().present(op["package"]) else None
        return None  # command / handler: no se pueden verificar de forma genérica

    # ================================================================== simulación

    def plan(
        self, tweak_ids: list[str], params: dict[str, dict[str, Any]] | None = None
    ) -> list[PlanItem]:
        """Dry-run: describe exactamente qué cambiaría, sin modificar nada."""
        params = params or {}
        items: list[PlanItem] = []
        for tid in tweak_ids:
            tweak = self.catalog.get(tid)
            item = PlanItem(tweak, self.evaluate(tweak))
            if not item.applicability.applicable:
                items.append(item)
                continue
            ctx = self._ctx(tweak, dry_run=True, params=params.get(tid))
            outcomes: list[Outcome] = []
            for op in tweak.apply:
                try:
                    outcomes.append(self._exec_op(op, ctx))
                except SkipOperation as skip:
                    ctx.plan(f"(omitido) {skip}")
                    outcomes.append("skipped")
                except OP_ERRORS as exc:
                    item.error = str(exc)
                    ctx.plan(f"(error al simular) {exc}")
            item.lines = ctx.planned
            item.already_applied = bool(outcomes) and all(o != "changed" for o in outcomes)
            items.append(item)
        return items

    # ================================================================== aplicación

    def apply(
        self,
        tweak_ids: list[str],
        params: dict[str, dict[str, Any]] | None = None,
        profile: int | None = None,
        confirmed: set[str] | None = None,
        progress: ProgressFn = _noop_progress,
        cancel: threading.Event | None = None,
    ) -> Session:
        """Aplica los tweaks seleccionados en una sesión nueva.

        `confirmed` debe contener los IDs de acciones irreversibles y de tweaks con doble
        confirmación; si falta alguno se omite (defensa en profundidad frente a la UI).
        """
        if not self._lock.acquire(blocking=False):
            raise PreflightError("Ya hay una operación en curso")
        try:
            return self._apply(
                tweak_ids, params or {}, profile, confirmed or set(), progress, cancel
            )
        finally:
            self._lock.release()

    def _apply(
        self,
        tweak_ids: list[str],
        params: dict[str, dict[str, Any]],
        profile: int | None,
        confirmed: set[str],
        progress: ProgressFn,
        cancel: threading.Event | None,
    ) -> Session:
        session = Session.new(
            "apply", profile=profile, env=self.env.to_dict(), selected=list(tweak_ids)
        )
        total = len(tweak_ids) + 2
        self.tasks.clear_cache()  # el estado real manda al aplicar, no lo detectado antes
        progress(0.0, "Comprobaciones previas")
        self._preflight(session, tweak_ids)
        self.store.save(session)
        progress(1 / total, "Copias de seguridad creadas")

        for index, tid in enumerate(tweak_ids, start=2):
            if cancel is not None and cancel.is_set():
                session.results[tid] = TweakResult(tid, "skipped", "Cancelado por el usuario")
                continue
            tweak = self.catalog.get(tid)
            progress(index / total, tweak.name)
            needs_confirmation = tweak.is_action or tweak.confirm_double
            if needs_confirmation and tid not in confirmed:
                session.results[tid] = TweakResult(tid, "skipped", "Falta confirmación explícita")
                continue
            session.results[tid] = self._apply_one(tweak, session, params.get(tid))
            self.store.save(session)

        session.finished = _now()
        self.store.save(session)
        progress(1.0, "Terminado")
        log.info("session_finished", extra={"session": session.id, "summary": session.summary()})
        return session

    def _preflight(self, session: Session, tweak_ids: list[str]) -> None:
        if not self.env.is_admin:
            raise PreflightError("WinTune necesita ejecutarse como administrador")
        result = self.restore.create(f"WinTune {session.id}")
        session.restore_point = result.message
        if not result.ok:
            if not self.settings.allow_without_restore_point:
                raise PreflightError(
                    f"{result.message}. Activa la Protección del sistema o permite continuar sin "
                    "punto de restauración en Ajustes."
                )
            log.warning("no_restore_point", extra={"session": session.id, "detail": result.message})
        if self.settings.export_reg_backups:
            self._export_backups(session, tweak_ids)

    def _export_backups(self, session: Session, tweak_ids: list[str]) -> None:
        keys: dict[str, tuple[str, str]] = {}
        for tid in tweak_ids:
            for op in self.catalog.get(tid).apply:
                if op["op"] in ("registry_set", "registry_delete"):
                    loc = self.registry.locate(op["hive"], op["path"])
                    keys[str(loc).lower()] = (op["hive"], op["path"])
        for hive, path in keys.values():
            exported = export_key(self.runner, self.registry.locate(hive, path), session.backup_dir)
            if exported:
                session.backups.append(str(exported))

    def _apply_one(
        self, tweak: Tweak, session: Session, params: dict[str, Any] | None
    ) -> TweakResult:
        applicability = self.evaluate(tweak)
        if not applicability.applicable:
            return TweakResult(
                tweak.id, "skipped", "No aplicable: " + "; ".join(applicability.reasons)
            )
        detect_before = self._safe_detect(tweak) if not tweak.is_action else None
        ctx = self._ctx(tweak, dry_run=False, session=session, params=params)
        outcomes: list[Outcome] = []
        errors: list[str] = []
        skips: list[str] = []
        for op in tweak.apply:
            try:
                outcomes.append(self._exec_op(op, ctx))
            except SkipOperation as skip:
                skips.append(str(skip))
                outcomes.append("skipped")
            except OP_ERRORS as exc:
                errors.append(f"{op['op']}: {exc}")
                log.error("op_failed", extra={"tweak": tweak.id, "op": op["op"], "err": str(exc)})
        changed = "changed" in outcomes
        details = ctx.notes + skips + errors
        if errors:
            status = "partial" if changed else "failed"
            return TweakResult(tweak.id, status, errors[0], details, detect_before)
        if changed:
            msg = "Requiere reiniciar" if tweak.reboot_required else "Aplicado"
            return TweakResult(tweak.id, "applied", msg, details, detect_before)
        if skips and all(o == "skipped" for o in outcomes):
            return TweakResult(tweak.id, "skipped", skips[0], details)
        return TweakResult(tweak.id, "skipped", "Ya estaba aplicado", details)

    # ================================================================== operaciones

    def _exec_op(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        kind = op["op"]
        executor = getattr(self, f"_op_{kind}", None)
        if executor is None:
            raise ValueError(f"Operación desconocida: {kind}")
        return executor(op, ctx)

    def _op_registry_set(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        if is_policy_op(op) and self.env.managed:
            raise SkipOperation(f"Directiva {op['name']} omitida: equipo gestionado")
        value = RegValue.from_catalog(op["kind"], op["value"])
        return (
            "changed"
            if ctx.set_registry(op["hive"], op["path"], op["name"], value)
            else "unchanged"
        )

    def _op_registry_delete(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        self.guard.check_registry(op["hive"], op["path"])
        current = self.registry.read(op["hive"], op["path"], op["name"])
        if current is None:
            return "unchanged"
        loc = self.registry.locate(op["hive"], op["path"])
        if ctx.dry_run:
            ctx.plan(f"Registro {loc}\\{op['name']}: {current.display()} → (eliminar)")
            return "changed"
        self.registry.delete_value(op["hive"], op["path"], op["name"])
        ctx.record(
            "registry",
            {"hive": op["hive"], "path": op["path"], "name": op["name"], "key_existed": True},
            current.to_json(),
            None,
        )
        return "changed"

    def _op_service_start(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        name, target = op["name"], op["start"]
        self.guard.check_service(name)
        state = self.services.state(name)
        if not state.exists:
            raise SkipOperation(f"El servicio {name} no existe en este equipo")
        if state.start == target:
            return "unchanged"
        if ctx.dry_run:
            stop = " y detener" if op.get("stop") else ""
            ctx.plan(f"Servicio {name}: inicio {state.start} → {target}{stop}")
            return "changed"
        self.services.set_start(name, target)
        ctx.record("service", {"name": name}, state.start, target)
        if op.get("stop"):
            self.services.stop(name)
        return "changed"

    def _op_task_state(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        info = self.tasks.query(op["path"])
        if not info.exists:
            raise SkipOperation(f"La tarea {op['path']} no existe en esta build")
        if info.enabled == op["enabled"]:
            return "unchanged"
        if ctx.dry_run:
            verb = "habilitar" if op["enabled"] else "deshabilitar"
            ctx.plan(f"Tarea {op['path']}: {verb}")
            return "changed"
        self.tasks.set_enabled(op["path"], op["enabled"])
        ctx.record("task", {"path": op["path"]}, info.enabled, op["enabled"])
        return "changed"

    def _op_appx_remove(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        package = op["package"]
        self.guard.check_appx(package)
        if not self.appx.inventory().present(package):
            raise SkipOperation(f"{package} no está instalado")
        if ctx.dry_run:
            scope = " (instalado + aprovisionado)" if op.get("provisioned") else ""
            ctx.plan(f"AppX {package}: eliminar para todos los usuarios{scope}")
            return "changed"
        removed = self.appx.remove(package, bool(op.get("provisioned")))
        for note in self.appx.pop_notes():
            ctx.note(note)
        ctx.record("appx", {"package": package}, "present", removed)
        return "changed"

    def _op_appx_reinstall(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        if self.appx.inventory().present(op["package"]):
            return "unchanged"
        if ctx.dry_run:
            ctx.plan(f"Reinstalar {op['store_name']} desde Microsoft Store (winget)")
            return "changed"
        self.appx.reinstall(op["package"], op.get("store_id"), op["store_name"])
        ctx.record("appx", {"package": op["package"]}, "absent", "reinstalled")
        return "changed"

    def _op_command(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        exe = op["exe"]
        self.guard.check_command(exe)
        args = [str(ALLOWED_COMMAND_EXES[exe]), *op["args"]]
        ctx.run_checked(args, f"{exe} {' '.join(op['args'])}")
        if not ctx.dry_run:
            ctx.record("command", {"exe": exe, "args": op["args"]}, None, None)
        return "changed"

    def _op_handler(self, op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        func = resolve_handler(op["ref"])
        ctx.params.update(op.get("params", {}))
        result = func(ctx)
        return "unchanged" if result is False else "changed"

    def _op_none(self, op: dict[str, Any], _ctx: HandlerContext) -> Outcome:
        raise SkipOperation(op.get("reason", "Operación irreversible"))

    def _op_restore_snapshot(self, _op: dict[str, Any], ctx: HandlerContext) -> Outcome:
        if ctx.prior_session is None:
            raise HandlerError("restore_snapshot solo es válido al revertir una sesión")
        changes = list(reversed(ctx.prior_session.changes_for(ctx.tweak.id)))
        restored = False
        for change in changes:
            restored |= self._restore_change(change.kind, change.target, change.before, ctx)
        return "changed" if restored else "unchanged"

    def _restore_change(
        self, kind: str, target: dict[str, Any], before: Any, ctx: HandlerContext
    ) -> bool:
        if kind == "registry":
            hive, path, name = target["hive"], target["path"], target["name"]
            loc = self.registry.locate(hive, path)
            if ctx.dry_run:
                shown = RegValue.from_json(before).display() if before else "(eliminar)"
                ctx.plan(f"Restaurar {loc}\\{name} → {shown}")
                return True
            if before is None:
                self.registry.delete_value(hive, path, name)
                if not target.get("key_existed", True):
                    self.registry.delete_key_if_empty(hive, path)
            else:
                self.registry.write(hive, path, name, RegValue.from_json(before))
            return True
        if kind == "service":
            if before not in SC_START_ARG:
                return False
            if ctx.dry_run:
                ctx.plan(f"Restaurar servicio {target['name']} → inicio {before}")
                return True
            self.services.set_start(target["name"], before)
            if before in ("automatic", "automatic_delayed"):
                self.services.start(target["name"])
            return True
        if kind == "task":
            if ctx.dry_run:
                state = "habilitada" if before else "deshabilitada"
                ctx.plan(f"Restaurar tarea {target['path']} → {state}")
                return True
            self.tasks.set_enabled(target["path"], bool(before))
            return True
        # appx/command/handler se revierten con operaciones explícitas del catálogo.
        return False

    # ================================================================== reversión

    def revert(
        self,
        session_id: str,
        only: set[str] | None = None,
        dry_run: bool = False,
        progress: ProgressFn = _noop_progress,
        cancel: threading.Event | None = None,
    ) -> Session:
        if not self._lock.acquire(blocking=False):
            raise PreflightError("Ya hay una operación en curso")
        try:
            return self._revert(session_id, only, dry_run, progress, cancel)
        finally:
            self._lock.release()

    def _revert(
        self,
        session_id: str,
        only: set[str] | None,
        dry_run: bool,
        progress: ProgressFn,
        cancel: threading.Event | None,
    ) -> Session:
        self.tasks.clear_cache()
        original = self.store.load(session_id)
        if original.kind != "apply":
            raise PreflightError("Solo se pueden deshacer sesiones de aplicación")
        if not dry_run and not self.env.is_admin:
            raise PreflightError("WinTune necesita ejecutarse como administrador")
        session = Session.new("revert", parent_id=original.id, env=self.env.to_dict())
        targets = [
            tid
            for tid, res in original.results.items()
            if res.status in ("applied", "partial") and (only is None or tid in only)
        ]
        # Orden inverso al de aplicación: deshace dependencias en el orden correcto.
        targets.reverse()
        session.selected = targets
        for index, tid in enumerate(targets):
            if cancel is not None and cancel.is_set():
                session.results[tid] = TweakResult(tid, "skipped", "Cancelado por el usuario")
                continue
            progress(index / max(len(targets), 1), f"Revirtiendo {tid}")
            session.results[tid] = self._revert_one(tid, original, session, dry_run)
            if not dry_run:
                self.store.save(session)
        session.finished = _now()
        if not dry_run:
            self.store.save(session)
            original.reverted_by = session.id
            self.store.save(original)
        progress(1.0, "Reversión terminada")
        return session

    def _revert_one(
        self, tid: str, original: Session, session: Session, dry_run: bool
    ) -> TweakResult:
        if tid in self.catalog:
            tweak = self.catalog.get(tid)
            ops = tweak.revert
        else:
            # El tweak ya no existe en el catálogo actual: se restaura su snapshot.
            ops = [{"op": "restore_snapshot"}]
            tweak = dataclasses.replace(
                self.catalog.tweaks[0], id=tid, name=tid, revert=ops, params={}
            )
        ctx = self._ctx(tweak, dry_run=dry_run, session=session, prior=original)
        errors: list[str] = []
        irreversible: list[str] = []
        changed = False
        for op in ops:
            try:
                changed |= self._exec_op(op, ctx) == "changed"
            except SkipOperation as skip:
                if op["op"] == "none":
                    irreversible.append(str(skip))
            except OP_ERRORS as exc:
                errors.append(f"{op['op']}: {exc}")
                log.error("revert_failed", extra={"tweak": tid, "err": str(exc)})
        details = ctx.planned + ctx.notes + errors
        if irreversible and not changed:
            return TweakResult(tid, "irreversible", irreversible[0], details)
        if errors:
            return TweakResult(tid, "partial" if changed else "failed", errors[0], details)
        if dry_run:
            return TweakResult(tid, "reverted", "Simulado", details)
        diffs = self._verify_revert(tid, original)
        if diffs:
            return TweakResult(
                tid, "partial", "Revertido con diferencias", details + diffs, verified=False
            )
        return TweakResult(tid, "reverted", "Revertido y verificado", details, verified=True)

    def _safe_detect(self, tweak: Tweak) -> str | None:
        try:
            return self.detect(tweak).state.value
        except OP_ERRORS as exc:
            log.warning("detect_failed", extra={"tweak": tweak.id, "err": str(exc)})
            return None

    def _verify_revert(self, tid: str, original: Session) -> list[str]:
        """Comprueba que lo revertido volvió al estado previo. Devuelve las diferencias."""
        diffs: list[str] = []
        for change in original.changes_for(tid):
            target, before = change.target, change.before
            try:
                if change.kind == "registry":
                    current = self.registry.read(target["hive"], target["path"], target["name"])
                    expected = RegValue.from_json(before) if before else None
                    same = (current is None and expected is None) or (
                        expected is not None and values_equal(current, expected)
                    )
                    if not same:
                        shown = current.display() if current else "(no existe)"
                        wanted = expected.display() if expected else "(no existe)"
                        diffs.append(f"{target['name']}: {shown} (esperado {wanted})")
                elif change.kind == "service" and before in SC_START_ARG:
                    current_start = self.services.state(target["name"]).start
                    if current_start != before:
                        diffs.append(
                            f"Servicio {target['name']}: {current_start} (esperado {before})"
                        )
                elif change.kind == "task":
                    info = self.tasks.query(target["path"])
                    if info.exists and info.enabled != bool(before):
                        diffs.append(f"Tarea {target['path']}: no volvió a su estado")
            except OP_ERRORS as exc:
                diffs.append(f"No se pudo verificar {change.kind}: {exc}")
        previous = original.results[tid].detect_before if tid in original.results else None
        if tid in self.catalog and previous in (DetectState.NOT_APPLIED, DetectState.PARTIAL):
            # Solo se compara la detección si antes NO estaba aplicado: si ya lo estaba,
            # la sesión no cambió nada y no hay estado previo distinto que recuperar.
            now = self._safe_detect(self.catalog.get(tid))
            if now is not None and now != previous:
                diffs.append(f"Estado detectado: {now} (antes de aplicar: {previous})")
        return diffs


def combine_checks(checks: list[bool | None]) -> DetectResult:
    known = [c for c in checks if c is not None]
    if not known:
        return DetectResult(DetectState.UNKNOWN if checks else DetectState.NOT_APPLICABLE)
    if all(known):
        return DetectResult(DetectState.APPLIED)
    if not any(known):
        return DetectResult(DetectState.NOT_APPLIED)
    return DetectResult(DetectState.PARTIAL, f"{sum(known)}/{len(known)} aplicados")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
