"""Prueba de humo de la interfaz: abre SafeBoost en modo demo, recorre todas las páginas (y las
vistas de Espacio) y falla si alguna lanza una excepción. Opcionalmente guarda una captura de
cada página.

Uso:
    python scripts/ui_smoke.py [--lang es|en] [--screenshots CARPETA] [--timeout 120]

Código de salida: 0 bien, 1 alguna página falló, 2 la interfaz no llegó a construirse.
Los datos se guardan en una carpeta temporal (SAFEBOOST_HOME), nunca en los del usuario.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PAGE_DELAY_MS = 700


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", default="es")
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--delay", type=int, default=PAGE_DELAY_MS, help="ms por pantalla (más para capturas)"
    )
    args = parser.parse_args(argv)

    # Antes de importar core: APP_HOME se calcula al importar core.constants.
    os.environ["SAFEBOOST_HOME"] = tempfile.mkdtemp(prefix="safeboost-smoke-")
    sys.path.insert(0, str(ROOT))

    import customtkinter as ctk

    from core.app import build_context
    from core.demo import DemoRunner, demo_environment, demo_registry
    from core.i18n import set_language
    from core.settings import Settings
    from ui.app import PAGES, MainWindow
    from ui.theme import COLOR_THEME

    set_language(args.lang)
    settings = Settings(first_run=False, check_updates=False, language=args.lang)
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme(COLOR_THEME)
    errors: list[str] = []

    def builder(progress: Any) -> Any:
        backend = demo_registry()
        return build_context(
            settings=settings,
            backend=backend,
            runner=DemoRunner(backend),
            env=demo_environment(),
            defer_slow_checks=True,
            progress=progress,
        )

    class SmokeWindow(MainWindow):
        def report_callback_exception(self, exc: type, val: BaseException, tb: Any) -> None:
            errors.append(f"{self.current}: {''.join(traceback.format_exception(exc, val, tb))}")

    window = SmokeWindow(builder)
    steps: list[tuple[str, str | None]] = [(key, None) for key, _l, _c in PAGES]
    space_views = ("Carpetas", "Archivos grandes", "Duplicados", "Programas", "Navegadores")
    steps += [("space", view) for view in space_views]

    def capture(name: str) -> None:
        if args.screenshots is None or (sys.platform != "win32" and not os.environ.get("DISPLAY")):
            return
        from PIL import ImageGrab

        args.screenshots.mkdir(parents=True, exist_ok=True)
        window.update()
        box = (
            window.winfo_rootx(),
            window.winfo_rooty(),
            window.winfo_rootx() + window.winfo_width(),
            window.winfo_rooty() + window.winfo_height(),
        )
        ImageGrab.grab(box).save(args.screenshots / f"{args.lang}-{name}.png")

    def run_step(index: int) -> None:
        if window.ui is None:
            window.after(500, lambda: run_step(index))
            return
        if index > 0:
            key, view = steps[index - 1]
            capture(key if view is None else f"{key}-{view}")
        if index >= len(steps):
            window.after(args.delay, window.destroy)
            return
        key, view = steps[index]
        try:
            window.show(key)
            if view is not None:
                page: Any = window.pages[key]
                page.view.set(view)
                page._show(view)
            print(f"OK  {key}{' / ' + view if view else ''}", flush=True)
        except Exception:  # noqa: BLE001 - se informa y se sigue con la siguiente página
            errors.append(f"{key}/{view}: {traceback.format_exc()}")
        window.after(args.delay, lambda: run_step(index + 1))

    built = {"ok": False}

    def watchdog() -> None:
        if not built["ok"]:
            errors.append("La interfaz no terminó de construirse a tiempo")
            window.destroy()

    def mark_built() -> None:
        if window.ui is not None:
            built["ok"] = True
        else:
            window.after(200, mark_built)

    window.after(200, mark_built)
    window.after(args.timeout * 1000, watchdog)
    window.after(500, lambda: run_step(0))
    window.mainloop()

    if not built["ok"]:
        print("\n".join(errors), file=sys.stderr)
        return 2
    if errors:
        print(f"\n{len(errors)} errores en la interfaz:\n", file=sys.stderr)
        print("\n\n".join(errors), file=sys.stderr)
        return 1
    print(f"\nInterfaz OK: {len(steps)} pantallas sin errores ({args.lang}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
