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

- Repo `ErCacique/WinOpt` (privado; el usuario dijo que lo hará público). Rama de trabajo
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
| 0.7.0 | (incluye 0.6.0) Hardware: qué RAM comprar, SMART/batería/CPU frenada/drivers, Defender; vigilancia: inicio nuevo, Evolución (gráfica, tendencia, foto antes/después), mantenimiento mensual, Privacidad |

Enlaces v0.7.0: `https://github.com/ErCacique/WinOpt/releases/tag/v0.7.0`.

## v0.8.0

Completa en la rama (versión 0.8.0): fabricantes, fuentes oficiales, modo juego, "Arreglar mi PC
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
