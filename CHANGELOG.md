# Changelog

Todos los cambios relevantes de SafeTrim (antes WinTune) se documentan aquí.

El formato sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.13.0] - 2026-11-24

### Added
- **«Arreglar mi PC» como pantalla** (paso 1 de 2): el plan para tu equipo con una casilla por
  cambio (perfil recomendado, limpieza), avisos de qué hacer antes, los programas de inicio que
  conviene revisar y lo que ningún ajuste arregla. «Aplicar N cambios» lleva a la revisión y al
  resumen con el antes y el después de siempre (paso 2). Sustituye al diálogo anterior.
- **Buscar actualizaciones** (Ajustes): dice claramente «Tienes la última versión», «Hay una
  versión nueva» (con opción de instalarla) o por qué no se pudo comprobar (sin conexión,
  versiones no públicas, límite de GitHub…). El aviso automático al arrancar sigue siendo
  silencioso si falla.

### Fixed
- La web (GitHub Pages) se publica en dos fases, construir y desplegar, como la plantilla
  oficial; en una sola fase `deploy-pages` v5 no encontraba el paquete.

## [0.12.0] - 2026-11-24

### Added
- **Interfaz nueva con dos modos** (interruptor «Vista» abajo en el menú; se recuerda):
  - **Fácil** (por defecto): pantalla Inicio con la **nota de salud del equipo** (0-100, en un
    anillo de color), una frase que explica qué le pasa, el botón «Arreglar mi PC», cuatro
    tarjetas de semáforo (arranque, memoria, disco, seguridad) y atajos a liberar espacio, modo
    juego y modo ahorro. Menú de 8 secciones con iconos: Inicio, Revisar el PC, Arranque, Espacio,
    Evolución, Privacidad, Deshacer cambios y Ajustes.
  - **Avanzado**: todas las secciones de siempre, agrupadas (Equipo, Optimizar, SafeBoost).
- Nota de salud calculada en `core/health.py` a partir del diagnóstico (no mide nada nuevo).

### Changed
- Paleta azul marino con tarjetas con borde, iconos de línea dibujados por el programa, chips de
  estado con palabra y color (no solo color), en tema oscuro y claro.
- Diagnóstico: cada hallazgo es una tarjeta con icono y nivel. Programas de inicio: barra de
  impacto por programa.
- Ninguna función se ha quitado: el modo Avanzado mantiene todas las pantallas anteriores.

## [0.11.2] - 2026-11-24

### Changed
- El repositorio pasa a llamarse `ErCacique/SafeBoost` (antes `WinOpt`). El aviso de versiones,
  el instalador, la web, winget y la documentación usan la dirección nueva. Las versiones ya
  instaladas siguen encontrando actualizaciones: GitHub redirige la dirección antigua.

## [0.11.1] - 2026-11-24

### Security
Auditoría completa (informe en `docs/AUDITORIA-SEGURIDAD.md`). Todos los fallos eran explotables
solo desde el propio equipo (un programa sin permisos aprovechando que SafeBoost es administrador).
- Las órdenes de PowerShell escapan también las comillas tipográficas (‘ ’ ‚ ‛), que PowerShell
  trata como comillas: un nombre de programa de inicio manipulado ya no puede inyectar órdenes.
- La limpieza nunca entra en enlaces ni junctions: antes se podía dirigir el borrado a carpetas
  del sistema desde %TEMP%.
- «Desinstalar» programas del fabricante solo usa entradas de HKLM y muestra la orden exacta.
- Las tareas elevadas (mantenimiento, vigilancia, medición tras reiniciar) solo se crean con la
  versión instalada en Program Files; la medición tras reiniciar ya no se ejecuta como SYSTEM.
- «Actualizar ahora» descarga en una carpeta protegida y vuelve a comprobar la huella SHA-256
  justo antes de instalar.
- Pillow 13.0.0 (corrige 8 CVE). La CI comprueba las dependencias con pip-audit.
- Los parámetros de un archivo de selección importado se validan.

## [0.11.0] - 2026-11-24

### Changed
- **SafeTrim pasa a llamarse SafeBoost.** Programa, instalador, carpeta de datos
  (`%LOCALAPPDATA%\SafeBoost`, `SafeBoostData` en la portable), tareas programadas
  (`\SafeBoost\`), web y documentación.

### Migración automática
- Al primer arranque se copian todos los datos de SafeTrim (sesiones para deshacer, copias .reg,
  vigilancia, ajustes, licencia Técnico, mediciones) y se recrean con el nombre nuevo el
  mantenimiento mensual y la vigilancia en segundo plano si estaban activos. No se borra nada.
- El instalador mantiene el mismo identificador: actualiza SafeTrim sin desinstalar, se instala en
  `C:\Program Files\SafeBoost` y elimina la carpeta y los accesos directos antiguos.
- Las Releases publican también `SafeTrim-Setup-X.exe` (copia idéntica) para que "Actualizar
  ahora" de SafeTrim 0.10.x siga funcionando. Se aceptan los archivos de selección
  `safetrim-selection` y la variable `SAFETRIM_HOME`. Las licencias `ST1.` siguen siendo válidas.
- El desinstalador quita también las tareas de mantenimiento y vigilancia.

## [0.10.0] - 2026-11-22

### Added
- **Prueba de rendimiento** (Evolución): disco (secuencial y archivos pequeños), procesador (uno y
  todos los núcleos) y lo que tardan en abrirse el Bloc de notas y Paint. Guarda el historial y
  compara con la primera medición.
- **Navegadores** (Espacio): tamaño de la caché de Chrome, Edge, Brave, Opera y Firefox con
  limpieza segura (nuevo `cleanup.browser_cache`; no toca cookies, historial ni contraseñas y omite
  los navegadores abiertos) y lista de extensiones con avisos (acceso a todas las webs, tipos que
  suelen ser publicidad).
- **Modo ahorro** (Dashboard, solo con batería): ahorro de batería al 50 %, procesador al 80 % y
  pantalla apagada a los 3 minutos, solo con batería. Tres tweaks nuevos `power.dc_*`, deshacibles.
- **Vigilancia en segundo plano** (Ajustes, desactivada por defecto): icono junto al reloj que
  avisa al momento cuando un programa se añade al inicio y, si lo pides, activa el modo juego al
  abrir un juego de Steam, Epic, GOG, Xbox… y lo desactiva al cerrarlo.
- **Inglés completo**: descripciones, motivos y notas de los 82 tweaks y el veredicto del
  diagnóstico.
- **Edición Técnico**: licencia firmada (Ed25519) que se comprueba sin internet; con ella, el
  informe para el cliente lleva el nombre, contacto y logo del técnico (Ajustes → Edición Técnico).
  `scripts/license_tool.py` emite licencias; ver `docs/LICENCIAS.md`.
- **Microsoft Store**: la Release genera un paquete MSIX sin firmar listo para Partner Center
  (`docs/STORE.md`).
- **Web** en `site/` con publicación automática en GitHub Pages cuando el repo sea público.

### Changed
- CI: comprobación de tipos (mypy), cobertura mínima del 80 % y prueba de humo de la interfaz en
  Linux (Xvfb) y en Windows real, con capturas de cada pantalla como artefacto.
- mypy encontró y se corrigieron varios errores latentes de tipos (ninguno visible para el
  usuario).

## [0.9.0] - 2026-11-22

### Added
- **Informes de error sin conexión**: si algo falla (interfaz, hilos o el propio proceso) se
  guarda un informe en `crashes/` (se conservan los 20 últimos) y se incluye en "Exportar logs".
  No se envía nada a ningún sitio.
- **Estado de seguridad** (Diagnóstico): Windows Defender y definiciones, firewall por perfil,
  activación de Windows, control de cuentas (UAC), BitLocker y actualizaciones. Antivirus,
  firewall o UAC desactivados aparecen como problema importante en el veredicto.
- **Retrasar 90 s** un programa de inicio (página Inicio): en vez de desactivarlo, arranca 90 s
  después de iniciar sesión mediante una tarea programada en `\SafeTrim\Delayed\`. Se deshace
  desde Historial (borra la tarea y reactiva la entrada).
- **Programas de prueba o del fabricante** (Espacio → Programas): antivirus de prueba, juegos
  preinstalados y utilidades OEM prescindibles, con botón para abrir su desinstalador oficial
  (con confirmación; los MSI se desinstalan con `/X`).
- **Drivers y BIOS de tu modelo** (Diagnóstico): fabricante, modelo y número de serie, y enlace
  directo a la página de soporte (Dell y Lenovo por número de serie).

## [0.8.0] - 2026-11-21

### Added
- **"Arreglar mi PC lento"** (Dashboard): diagnostica el equipo y propone un plan revisable
  (qué hacer primero, perfil recomendado + limpieza segura, programas de inicio que retrasan el
  arranque y consejos de hardware). Prepara la selección y abre la simulación; nada se aplica
  sin confirmar. Sustituye al "perfil para equipos antiguos".
- **Modo juego** con un clic: plan de alto rendimiento, Game DVR desactivado y prioridad al
  primer plano; se desactiva igual (es una sesión normal, también deshacible desde Historial).
  No se activa solo al abrir un juego.
- **Servicios de fabricantes**: HP Insights Analytics, NVIDIA Telemetry, Adobe Genuine y (opcional)
  el actualizador de Acrobat pasan a Manual; solo aparecen si el servicio existe.
- **Documentación oficial** de cada tweak (Microsoft Learn o el fabricante) en su detalle.
- **Página Espacio**: carpetas y archivos más grandes, duplicados en Descargas (mismo SHA-256) y
  programas instalados por tamaño con último uso estimado (Prefetch). Solo lee.
- **Informe para el cliente** (Diagnóstico) en PDF, generado con Microsoft Edge en modo headless
  (o HTML si no hay Edge).
- **Actualizar ahora**: descarga el instalador del Release, comprueba su SHA-256 con
  `SHA256SUMS.txt` y lo ejecuta en modo silencioso. Requiere Releases públicas.
- **Inglés** (Ajustes → Idioma): menú, títulos, botones principales y nombres de los tweaks. Las
  descripciones y los textos del diagnóstico siguen en español en esta versión.
- **Resumen "desde que usas SafeTrim"** en Evolución (arranque, programas de inicio y RAM).
- Release: manifiestos de **winget**, **portable ARM64** (job opcional en `windows-11-arm`) y
  **firma de código** automática si existen los secretos `SIGN_PFX_BASE64` y
  `SIGN_PFX_PASSWORD`.

### Changed
- `restore_point=False` se admite también para tweaks reversibles de riesgo bajo (modo juego).

## [0.7.0] - 2026-11-21

### Added
- **Avisos de programas nuevos al inicio**: al abrir SafeTrim compara los programas que arrancan
  con Windows con los de la última vez y avisa en el Dashboard de los nuevos, con acceso directo
  a la página Inicio. También anota los programas instalados desde la última vez.
- **Página Evolución**: gráfica del tiempo de arranque de los últimos 30 arranques medidos,
  detección de empeoramiento ("desde el día 14 arranca 28 s más lento; coincide con: Spotify")
  y lista de lo que ha cambiado (programas instalados, añadidos al inicio, mantenimientos).
- **Qué instala un programa**: foto del sistema antes de instalar (servicios y su tipo de inicio,
  tareas programadas, programas de inicio e instalados) y comparación después, para ver lo que
  el instalador añadió sin avisar.
- **Mantenimiento mensual** (opcional, en Ajustes): tarea programada cada 4 semanas que
  comprueba si Windows ha deshecho cambios, limpia temporales y miniaturas con las mismas reglas
  de antigüedad y registra programas nuevos. El informe aparece en el Dashboard.
- **Página Privacidad**: qué programas han usado la cámara, el micrófono y la ubicación, cuándo,
  y cuáles los están usando ahora mismo, con acceso a la página de Configuración de Windows para
  quitar permisos.

### Changed
- `Engine.apply(..., restore_point=False)` solo se admite para limpiezas, que un punto de
  restauración no recupera; lo usa el mantenimiento mensual.
- Menú lateral más compacto para que quepan las 11 páginas en pantallas pequeñas.

## [0.6.0] - 2026-11-21

### Added
- **Qué RAM comprar**: el Diagnóstico lee el tipo (DDR3/DDR4/DDR5), el formato (SO-DIMM de
  portátil o DIMM de sobremesa), la velocidad, el fabricante y el modelo de cada módulo, y dice
  exactamente qué comprar ("un módulo DDR4 SO-DIMM de 8 GB a 2400 MHz en la ranura libre"),
  con aviso de doble canal y de memoria soldada (LPDDR) que no se puede ampliar.
- **Salud del disco**: estado SMART, errores de lectura, desgaste del SSD, temperatura y horas de
  uso. Un disco con avisos o errores aparece como hallazgo grave con consejo de copia de
  seguridad.
- **Salud de la batería**: capacidad actual frente a la original y ciclos de carga.
- **Procesador frenado**: si está ocupado pero va por debajo del 60 % de su velocidad, avisa y
  distingue entre ahorro de batería y calor (ventilador sucio).
- **Dispositivos con problemas** (código de error del Administrador de dispositivos explicado) y
  **driver de gráfica de más de 3 años**.
- **Análisis rápido con Windows Defender** desde Diagnóstico. Si otro antivirus está activo,
  lo indica en lugar de analizar; avisa si las definiciones están desactualizadas.

### Changed
- Todos los datos de hardware salen de una sola consulta de PowerShell con cada sección aislada.
  El rendimiento del procesador se lee por CIM, no con contadores de rendimiento, cuyos nombres
  están traducidos al idioma de Windows.

## [0.5.0] - 2026-11-21

### Added
- **Qué retrasa el arranque**: el Diagnóstico lee los eventos 101-110 del registro de rendimiento
  de arranque de Windows (últimos 60 días) y lista los programas, servicios y drivers que lo
  retrasan, cuántas veces y cuántos segundos, con un consejo para cada tipo. Si alguno supera
  los 3 s de media aparece en el veredicto.
- **Navegadores en segundo plano**: tres tweaks nuevos de nivel 2 (Edge Startup boost, Edge y
  Chrome en segundo plano al cerrarlos), reversibles y preseleccionados solo con menos de 5 GB
  de RAM. El de Chrome solo aparece si está instalado. Son directivas: los navegadores mostrarán
  "Tu organización administra este navegador", y en equipos gestionados no se aplican.
- **Kit de rescate**: `SafeTrim.exe --undo-all` deshace todas las sesiones sin interfaz (también
  en modo seguro), con un acceso directo en el menú Inicio. Si se abre sin consola crea una.
- **Instalador y versión portable**: el release publica `SafeTrim-Setup-X.Y.Z.exe` (Inno Setup)
  y `SafeTrim-portable-X.Y.Z.zip`. Con `portable.txt` junto al `.exe`, los datos se guardan en
  `SafeTrimData\` al lado del programa (ideal para USB y técnicos).

### Changed
- El programa se empaqueta en modo *onedir* en lugar de un único `.exe`: abre varios segundos
  antes en equipos lentos y da menos falsos positivos de antivirus.
- La ventana se adapta a la pantalla: en portátiles de 1366x768 con escalado al 125 % se
  maximiza en lugar de salirse por los bordes; los diálogos y los textos largos también se
  ajustan.

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
