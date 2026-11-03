# Changelog

Todos los cambios relevantes de WinTune se documentan aquí.

El formato sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.1.1] - 2026-11-03

### Fixed
- La interfaz se congelaba hasta 90 s la primera vez que se abría "Optimización" o se elegía
  un perfil: la comprobación de soporte de HAGS (dxdiag) se ejecutaba en el hilo de Tk. Ahora
  todas las comprobaciones de hardware se hacen al arrancar, en segundo plano.
- La medición "después del reinicio" podía guardarse sin haber reiniciado si no había dato de
  arranque previo. Ahora solo cuenta un arranque registrado después de aplicar la sesión.
- Si `Remove-AppxPackage -AllUsers` falla (ocurre con algunos paquetes en Windows 10), se
  reintenta para el usuario interactivo y se informa en el resumen en lugar de marcar fallo.
- Deshacer la eliminación de apps reinstalaba con winget en la cuenta elevada; si es distinta
  del usuario con sesión, ahora se ejecuta en la sesión de ese usuario (tarea temporal).

### Added
- Medición automática del arranque tras el siguiente reinicio: tarea programada temporal
  (`\WinTune\PostRebootMetrics`) que se elimina sola. Se puede desactivar en Ajustes.
- Icono de la aplicación (`assets/wintune.ico`, generado con `scripts/make_icon.py`).
- `--self-test` comprueba también que el icono va empaquetado.

## [0.1.0] - 2026-11-03

### Added
- Estructura del repositorio, `pyproject.toml` y dependencias fijadas.
- Catálogo declarativo `data/tweaks.json` (70 entradas en 3 niveles) y su esquema
  `data/tweaks.schema.json` con reglas de coherencia: las acciones irreversibles y los
  tweaks de riesgo alto nunca entran en perfiles automáticos.
- README interno con perfiles, tabla de tweaks y sección "Qué NO toca WinTune".
- Motor (`core/`): registro con resolución de HKCU al usuario interactivo, servicios, AppX,
  tareas programadas, detección de entorno (build, edición, SSD/HDD, portátil, dominio/Entra/MDM,
  impresoras), lista de protección en tiempo de ejecución, simulación, aplicación por sesión
  con snapshots, reversión en orden inverso, puntos de restauración y copias `.reg`.
- Handlers (`tweaks/`): limpieza con antigüedad mínima, planes de energía, Nagle, autotuning,
  DNS, archivo de paginación, indexado por unidad, soporte HAGS y gestor de inicio.
- Interfaz CustomTkinter con dashboard, selector de perfil, revisión previa con confirmaciones,
  resumen, historial con deshacer, ajustes, log en vivo y modo `--demo`.
- `--self-test` para verificar el catálogo y los handlers dentro del ejecutable.
- Tests (pytest) con registro y comandos simulados, más tests de `winreg` nativo en Windows.
- CI (`ci.yml`), release con SHA256 (`release.yml`), Dependabot y pre-commit (ruff, gitleaks,
  validación del catálogo, bloqueo de commits a `main`).
- Documentación de configuración de GitHub y de distribución/firma de código.

[Unreleased]: https://github.com/ErCacique/WinOpt/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/ErCacique/WinOpt/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ErCacique/WinOpt/releases/tag/v0.1.0
