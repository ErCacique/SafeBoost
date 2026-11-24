# Estado del proyecto SafeTrim (traspaso de contexto)

Documento de trabajo para retomar el proyecto sin perder nada si se comprime la conversación o
se reinicia el entorno. Última actualización: 2026-11-21.

## Usuario y forma de trabajar

- Desarrollador freelance (web, Node.js, Python, automatización con IA). Respuestas **en español**,
  técnicas y directas, sin relleno; prosa salvo contenido enumerativo; código completo con manejo
  de errores; preguntar si hay ambigüedad que cambie el resultado; avisar de problemas aunque no
  los pregunte. Cuando pide explicaciones "como a un niño de 8 años", pasos muy simples.
- Dio permiso general: "Haz todo tú, te doy mi permiso". Se fusionan PR y se publican versiones
  cuando la CI está en verde, avisándole.
- El usuario pidió continuar la v0.8.0 (la pausa anterior ya no está vigente).

## Repositorio y procedimiento

- Repo `ErCacique/SafeBoost` (antes WinOpt, renombrado el 2026-11-24; GitHub redirige los enlaces antiguos. Privado; el usuario dijo que lo hará público). Rama de trabajo
  **`ccr-66de96ff-ie0yja`**: solo se hace push ahí. Force-push denegado: para sincronizar con
  `main` tras un squash merge, `git merge origin/main` en la rama.
- Commits terminan con:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` y
  `Claude-Session: https://claude.ai/code/session_01EBLXLf7oDWSdG4hb81cniW`.
  PR (borrador) terminan con `🤖 Generated with [Claude Code](https://claude.com/claude-code)` +
  la URL de sesión. No poner identificadores de modelo en commits/PR.
- Al fusionar (squash) pasar `commit_message` explícito: si no, GitHub concatena todo el historial.
- **Publicar versión**: subir `APP_VERSION` (`core/constants.py`), `pyproject.toml` y
  `packaging/version_info.txt` (3 sitios) + entrada en `CHANGELOG.md`; fusionar PR; lanzar
  `release.yml` por `workflow_dispatch` en `main` con input `tag: vX.Y.Z` (el push de tags está
  bloqueado en la sesión). Con `tag` vacío sobre la rama solo compila (sirve para probar el
  empaquetado antes de fusionar).
- Release publica `SafeTrim-Setup-X.Y.Z.exe` (Inno Setup), `SafeTrim-portable-X.Y.Z.zip`
  (lleva `portable.txt`) y `SHA256SUMS.txt`.
- Comprobaciones locales: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`,
  `.venv/bin/python scripts/validate_tweaks.py`, `.venv/bin/pytest -q`,
  `.venv/bin/python main.py --self-test`.
- CI (`ci.yml`): Linux (lint, catálogo, tests, gitleaks), Windows (winreg nativo) y **E2E en
  Windows real** (aplica y revierte tweaks; `test_read_only_queries_on_real_windows` ejecuta las
  consultas de PowerShell de hardware, arranque y Windows Update). El runner es Windows Server:
  edición no reconocida (se usa `allow_unsupported_os=True` en el E2E) y registro
  Diagnostics-Performance desactivado.
- Capturas de la UI: `xvfb-run` + scripts de demo (`main.py --demo`); el modo demo usa
  `core/demo.py` (DemoRunner y registro simulado con datos de ejemplo).

## Versiones publicadas

| Versión | Contenido principal |
|---|---|
| 0.1.x–0.3.x | Base del programa; renombrado WinTune → SafeTrim (0.3.0) |
| 0.3.1 | Solo simulación en Windows no soportado; RAM total con decimal |
| 0.4.0 | Diagnóstico, Windows Update, Windows.old, recomendación por RAM, prioridad baja, aviso de versión, guía de inicio, Windows 11 |
| 0.4.1 | Arranque rápido: una sola PowerShell, dxdiag (HAGS) en segundo plano, progreso por pasos |
| 0.5.0 | Qué retrasa el arranque (eventos 101-110), navegadores en segundo plano, `--undo-all`, instalador + portable (onedir), ventana para pantallas pequeñas |
| 0.8.0 | Arreglar mi PC lento, modo juego, fabricantes, fuentes oficiales, Espacio, informe PDF, actualización verificada, inglés parcial, winget, ARM64 (portable), firma preparada |
| 0.11.2 | Repositorio renombrado a ErCacique/SafeBoost: enlaces y aviso de versiones actualizados |
| 0.11.1 | Auditoría de seguridad: 7 arreglos (comillas PowerShell, junctions en limpieza, desinstalador HKCU, tareas elevadas, actualizador, Pillow, parámetros) |
| 0.11.0 | Cambio de nombre SafeTrim → SafeBoost con migración automática de datos, tareas, instalador y actualizador |
| 0.10.0 | Prueba de rendimiento, navegadores (caché y extensiones), modo ahorro, vigilancia en segundo plano (bandeja), inglés completo, licencia Técnico (Ed25519 offline), MSIX, web, mypy/cobertura/humo de UI |
| 0.9.0 | Informes de error locales, estado de seguridad, retrasar inicio 90 s, programas del fabricante con desinstalador, soporte del modelo |
| 0.7.0 | (incluye 0.6.0) Hardware: qué RAM comprar, SMART/batería/CPU frenada/drivers, Defender; vigilancia: inicio nuevo, Evolución (gráfica, tendencia, foto antes/después), mantenimiento mensual, Privacidad |

Última publicada: v0.11.2 (`https://github.com/ErCacique/SafeBoost/releases/tag/v0.11.2`), con instalador, portable x64, portable ARM64, SHA256SUMS y manifiestos de winget.

## v0.8.0 (publicada el 2026-11-22)

Incluye: fabricantes, fuentes oficiales, modo juego, "Arreglar mi PC
lento", resumen de mejoras, página Espacio, informe PDF (Edge headless), actualización verificada,
winget, ARM64 opcional, firma preparada, inglés parcial (menú, títulos, botones, nombres de
tweaks; descripciones y diagnóstico siguen en español). Tests en `tests/test_v080.py`.
Pendiente posible: traducir descripciones y textos del diagnóstico al inglés.

## Tareas manuales del usuario

1. Probar en una VM o en su portátil (lo está usando: HP, Celeron, ~3,4 GB RAM, Windows 10 22H2
   build 19045.2965 actualizado desde 1909, SSD, arranque medido 134,8 s).
2. Ejecutar `scripts/verify_store_ids.ps1` (4 `store_id` vacíos en el catálogo).
3. Comprobar la marca SafeTrim (EUIPO/OEPM).
4. Activar alertas de Dependabot; hacer público el repo (necesario para aviso de versión,
   actualización automática y winget).
5. Opcional: certificado de firma de código.

## Lecciones aprendidas

- `Get-WinEvent -FilterHashtable` lanza un error que `-ErrorAction SilentlyContinue` no frena si
  el registro no existe o no hay eventos: envolver en `try/catch` (ya hecho en `core/boot.py` y
  `tweaks/startup.py`).
- Las consultas de PowerShell que devuelven vacío ante error deben probarse en el E2E real.
- Ids de sesión con microsegundos: dos sesiones en el mismo segundo se ordenaban al azar.
- Contadores de rendimiento de Windows están traducidos: usar clases CIM.
- El registro simulado devuelve subclaves en minúsculas; el de Windows no.

## v0.9.0 (2026-11-22, pedida: "Hazlas todas, de la 1 a la 5")

Módulos: `core/crash.py`, `core/security.py`, `core/support.py`, `core/oem.py`,
`StartupManager.delay` (cambio `task_created`, deshecho en `core/engine.py`). Tests en
`tests/test_v090.py`; seguridad añadida al E2E de solo lectura.

1. Informe de errores sin conexión (excepciones de Tk, hilos y proceso → APP_HOME/crashes, diálogo "Exportar informe").
2. Estado de seguridad (Defender, firewall, activación, UAC, BitLocker, actualizaciones) en Diagnóstico.
3. Retrasar programas de inicio (tarea programada al iniciar sesión con retraso, en vez de desactivar), deshacible.
4. Programas basura del fabricante (Win32: pruebas de antivirus, utilidades OEM) con desinstalador del fabricante y confirmación.
5. Página de soporte del modelo (fabricante, modelo, nº de serie; Dell con service tag).

## v0.10.0 (2026-11-22, pedida: "Sigue con los pasos del 6 al 15")

Decisiones del usuario: licencia **clave firmada offline**; Store **solo preparado** (sin cuenta de
Partner Center todavía); web en **GitHub Pages** (se activa cuando el repo sea público).

Módulos nuevos: `core/benchmark.py`, `core/extensions.py`, `core/tray.py` (`--tray`, tarea
`\SafeTrim\Tray`), `core/ed25519.py` (RFC 8032 en Python puro), `core/license.py`,
`scripts/license_tool.py`, `scripts/make_msix.py`, `scripts/ui_smoke.py`, `site/`,
`.github/workflows/pages.yml`. `core/gamemode.py` generaliza `TweakMode` (GameMode, BatteryMode).
Tweaks nuevos: `cleanup.browser_cache`, `power.dc_battery_saver`, `power.dc_cpu_max`,
`power.dc_display_off` (handlers `tweaks.power:*_dc_value`, lectura con `powercfg /q`).
Dependencias nuevas: pystray 0.19.5, pillow 12.3.0, six 1.17.0 (runtime); mypy 2.3.1 y
pytest-cov 7.0.0 (dev). Tests en `tests/test_v0100.py`.

**Clave privada de licencias**: se generó en la sesión y se entregó al usuario como archivo; NO
está en el repo. Clave pública en `core/license.py`. Procedimiento en `docs/LICENCIAS.md`.

Lecciones: mypy con `platform = "win32"` evita falsos positivos de winreg/ctypes; las rutas
relativas de Windows con `\` deben unirse por partes (`joinpath(*rel.split("\\"))`) para que los
tests funcionen en Linux; pystray no se puede importar en Linux sin pantalla (importarlo dentro de
`run_tray`).

## v0.11.0 · SafeTrim → SafeBoost (2026-11-24)

El usuario eligió el nombre **SafeBoost**. El repositorio se renombró después a SafeBoost (v0.11.2). Compatibilidad:
`core/migration.py:migrate_from_safetrim` (copia la carpeta entera una vez, marca
`MIGRADO_A_SAFEBOOST.txt`) y `migrate_tasks` (lee el usuario de \\SafeTrim\\Maintenance y Tray,
las borra y las recrea en \\SafeBoost\\); se ejecuta al principio de `main()` con permisos de
administrador. Instalador con el mismo AppId, `UsePreviousAppDir=no` e `[InstallDelete]` de
`{autopf}\\SafeTrim`; tras una actualización silenciosa desde SafeTrim abre el nuevo .exe. La
Release publica `SafeTrim-Setup-X.exe` como copia para el actualizador de 0.10.x: mantenerlo al
menos un par de versiones. Las tareas \\SafeTrim\\Delayed\\ (inicio retrasado) siguen funcionando y
se deshacen con su sesión, que guarda la carpeta. Tests en `tests/test_v0110.py`.
Aviso de marca: el nombre se parece a SAFEBOOT (software de cifrado registrado) y "Boost" es
frecuente en optimizadores (p. ej. STARTUP BOOST de Boost Software); pendiente de comprobar en EUIPO/OEPM.

## v0.11.1 · Auditoría de seguridad (2026-11-24)

Informe y tabla de hallazgos en `docs/AUDITORIA-SEGURIDAD.md`; tests en `tests/test_v0111.py`.
Reglas que deben mantenerse: todo texto externo a PowerShell con `ps_quote`; recorrer carpetas a
limpiar con `tweaks.cleanup._walk` (nunca `rglob`); toda tarea elevada nueva debe comprobar
`constants.protected_location`; parámetros de usuario pasan por `engine.clean_params`; nada que se
vaya a ejecutar elevado puede salir de HKCU ni de carpetas del usuario.

## v0.11.2 · Repositorio renombrado (2026-11-24)

WinOpt → SafeBoost en GitHub. No crear nunca otro repo llamado WinOpt en la cuenta: rompería la
redirección de la que dependen las versiones antiguas para encontrar actualizaciones.
