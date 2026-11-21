# Changelog

Todos los cambios relevantes de SafeTrim (antes WinTune) se documentan aquí.

El formato sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.4.1] - 2026-11-21

### Changed
- **Arranque más rápido.** La detección del entorno hace una sola llamada a PowerShell en lugar
  de siete (arrancar PowerShell cuesta 2-4 s en un equipo flojo). Cada consulta va aislada en
  su propio try/catch, así que un fallo solo deja ese dato como desconocido.
- La comprobación de HAGS (`dxdiag`, 20-90 s en equipos flojos) ya no bloquea el arranque: se
  hace en segundo plano con la ventana abierta. Mientras tanto el tweak indica "comprobando
  compatibilidad" y, al terminar, las páginas se refrescan solas. La CLI la sigue resolviendo
  antes de aplicar.
- Las consultas del arranque se ejecutan con prioridad normal (la prioridad baja de la v0.4.0
  las dejaba al final de la cola si Windows Update ocupaba la CPU); la baja se mantiene para lo
  que viene después.
- Las impresoras se consultan por CIM con un límite de 15 s: `Get-Printer` podía quedarse
  colgado con una impresora de red apagada.

### Added
- La pantalla de carga muestra el paso en curso ("Disco, equipo, impresoras y
  actualizaciones…") y el log registra cuántos milisegundos tarda cada paso (`env_step`).

## [0.4.0] - 2026-11-21

### Added
- **Página Diagnóstico** ("¿por qué va lento?"): mide procesos durante 1,5 s (agrupados por
  ejecutable) y da un veredicto ordenado por gravedad: RAM insuficiente con ranuras libres y
  máximo admitido, memoria casi llena con el mayor consumidor, proceso que acapara la CPU con
  explicación de los procesos de Windows conocidos (Windows Update, Defender, indexado…),
  procesador modesto, disco mecánico, poco espacio y estado de Windows Update. Solo lee.
- **Windows Update**: se detecta un reinicio pendiente y los días desde la última
  actualización instalada. El Dashboard lo avisa y, con un reinicio pendiente, no recomienda
  ningún perfil hasta reiniciar.
- **Windows.old**: nueva limpieza opcional (`cleanup.windows_old`) que muestra el tamaño y la
  antigüedad de la copia de la versión anterior, avisa si aún se puede volver atrás y la borra
  con el Liberador de espacio de Windows (`cleanmgr /sagerun`). Irreversible, con confirmación
  aparte.
- **Windows 10 sin soporte**: aviso del fin de soporte (14-10-2025) y comprobación de los
  requisitos de Windows 11 que se pueden verificar (RAM, disco, TPM 2.0, UEFI con arranque
  seguro); para el procesador remite a "Comprobación de estado del PC".
- **Aviso de versión nueva**: consulta la última Release de GitHub al arrancar y muestra un
  enlace si hay una más reciente. Desactivable en Ajustes; en silencio si no hay red o el
  repositorio es privado.
- **Guía de primeros pasos** de tres pantallas en el primer arranque, con opción de pasar a modo
  real; se puede volver a abrir desde Ajustes.

### Changed
- La recomendación tiene en cuenta la RAM también en portátiles: con menos de 5 GB indica que
  los perfiles ayudan poco y que lo que se nota es ampliar memoria.
- Los procesos externos (PowerShell, sc, reg…) se lanzan con prioridad por debajo de lo normal y
  las consultas de PowerShell de una en una, para que la interfaz no se atasque en equipos
  flojos.

## [0.3.1] - 2026-11-08

### Fixed
- **Windows no soportado ya no permite aplicar cambios.** En builds anteriores a la 19045
  (Windows 10 22H2) o con una edición no reconocida, SafeTrim antes solo mostraba un aviso y
  dejaba aplicar perfiles. Ahora entra en modo solo simulación: el motor rechaza aplicar antes
  de crear el punto de restauración, el botón "Revisar y aplicar" queda desactivado y la barra
  lateral indica "Windows no soportado". Deshacer sesiones anteriores sigue permitido.
- La recomendación del Dashboard ya no propone un perfil en Windows no soportado: indica que
  hay que actualizar Windows.
- La RAM total se muestra con un decimal: un equipo de 3.4 GB aparecía como "3.1 GB de 3 GB".

### Added
- Test estático que impide que los handlers de `tweaks/` escriban en el registro o ejecuten
  comandos sin pasar por `HandlerContext` (protección, snapshot y dry-run).
- Ajuste `allow_unsupported_os` (sin opción en la interfaz), solo para VMs de prueba y CI.

## [0.3.0] - 2026-11-03

### Changed
- **El programa pasa a llamarse SafeTrim** (antes WinTune, nombre ya usado por otro
  optimizador de Windows). Cambian el ejecutable (`SafeTrim.exe`), la carpeta de datos
  (`%LOCALAPPDATA%\SafeTrim`), la carpeta de tareas programadas (`\SafeTrim\`), el log
  (`safetrim.jsonl`) y las variables de entorno (`SAFETRIM_HOME`, `SAFETRIM_E2E`).

### Added
- Migración automática desde WinTune: al arrancar se **copian** (no se mueven) sesiones,
  copias `.reg`, métricas, logs y ajustes de `%LOCALAPPDATA%\WinTune`, solo si esa carpeta es
  de este programa, y se elimina la tarea programada antigua. Las sesiones de WinTune se
  siguen pudiendo deshacer.
- Compatibilidad: se siguen aceptando los archivos de selección `wintune-selection` y la
  variable `WINTUNE_HOME`.

## [0.2.0] - 2026-11-03

### Added
- **Test de extremo a extremo en Windows real** (job `e2e` del CI): aplica de verdad todos los
  tweaks seguros para un runner (registro, servicios, tareas, energía, red, directivas),
  comprueba que quedan aplicados, los revierte y verifica el estado final. Solo se ejecuta con
  `WINTUNE_E2E=1`, como administrador y en Windows.
- **Verificación de la reversión:** tras Deshacer se comprueba cada valor de registro, servicio
  y tarea contra su estado previo, y la detección contra la registrada antes de aplicar. El
  resumen indica "Revertido y verificado" o "Revertido con diferencias" con el detalle.
- **Detección de deriva:** el Dashboard avisa si Windows ha deshecho cambios aplicados (p. ej.
  tras una actualización) y ofrece revisarlos y reaplicarlos.
- **Exportar e importar la selección** (JSON) desde el Dashboard, y CLI
  `WinTune --apply-selection archivo.json [--yes] [--include-irreversible]`: sin `--yes` solo
  simula; los tweaks de riesgo alto nunca se aplican por CLI.
- **Informe HTML** de cualquier sesión desde Historial.
- **Búsqueda y filtros** (Todos / Pendientes / Aplicados / Seleccionados) en las páginas de tweaks.

### Changed
- Las sesiones guardan `schema_version` y `app_version`; las sesiones de 0.1.x se migran al
  cargarlas y se siguen pudiendo deshacer. Una sesión de una versión más nueva se rechaza con
  un mensaje claro en lugar de fallar.
- La detección consulta todas las tareas programadas de una página en una sola llamada a
  PowerShell (antes, una por tarea).
- El modo `--demo` simula también `sc config` y el estado de las tareas.

### Fixed
- Con una edición de Windows no reconocida (Server, algunas OEM/IoT) se aplicaban a la vez los
  dos tweaks de telemetría, que son excluyentes (`AllowTelemetry` 1 y 0). Detectado por el
  nuevo test E2E. Ahora los tweaks limitados por edición no se aplican si la edición es
  desconocida, y un test del catálogo impide escrituras de registro en conflicto.
- La precarga de tareas ya no deja como "desconocida" una tarea ausente en la respuesta.

## [0.1.2] - 2026-11-03

### Changed
- Indexado por unidad: casillas con las unidades fijas detectadas (la del sistema aparece
  desmarcada y señalada) en lugar de escribir las letras a mano.
- Los parámetros configurables muestran etiquetas en español ("Proveedor DNS", "Unidades",
  "Tamaño (MB)"); el campo `label` es obligatorio en el esquema del catálogo.

### Fixed
- README: las copias `.reg` se guardan en una subcarpeta por sesión de `backups`.

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

[Unreleased]: https://github.com/ErCacique/WinOpt/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ErCacique/WinOpt/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ErCacique/WinOpt/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/ErCacique/WinOpt/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/ErCacique/WinOpt/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ErCacique/WinOpt/releases/tag/v0.1.0
