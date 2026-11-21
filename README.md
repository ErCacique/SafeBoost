# SafeTrim

> Antes se llamaba **WinTune** (hasta la 0.2.x). Al primer arranque, SafeTrim copia los datos de
> `%LOCALAPPDATA%\WinTune` a `%LOCALAPPDATA%\SafeTrim`, así que las sesiones aplicadas con
> WinTune se pueden seguir deshaciendo. La carpeta antigua no se borra.

Herramienta de escritorio para eliminar bloatware y optimizar Windows 10/11 de forma
**reversible**, con tres perfiles acumulativos (Conservador, Equilibrado, Máximo), modo
simulación, copias de seguridad automáticas y deshacer por sesión.

> Repositorio privado de un único mantenedor. Documento interno.

## Requisitos

| Componente | Versión |
|---|---|
| Windows | 10 22H2 (build 19045) · 11 22H2 o superior (22621, 22631, 26100, 26200) |
| Ediciones | Home, Pro, Enterprise, Education |
| Python (desarrollo) | 3.12.x (el proyecto fija 3.12) |
| CustomTkinter | 5.2.2 (la 6.0.0 existe pero es una versión mayor; no se adopta hasta probarla) |
| psutil | 7.2.2 |
| PyInstaller | 6.22.3 |

En un Windows fuera de esta tabla (por ejemplo, Windows 10 1909) SafeTrim abre en modo
solo simulación: muestra el estado y simula, pero no aplica cambios hasta actualizar Windows.

El ejecutable se ejecuta siempre con privilegios de administrador (manifest `requireAdministrator`).

## Instalación para desarrollo

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pre-commit install
pre-commit install --hook-type pre-push
python main.py            # pide UAC si la consola no está elevada
python main.py --demo     # interfaz con un sistema simulado: no toca nada
```

`--demo` funciona en cualquier sistema operativo (registro en memoria, comandos simulados) y
sirve para desarrollar la interfaz. En Linux/macOS se pueden ejecutar además `ruff`, `pytest` y
la validación del catálogo.

### Comprobaciones locales

```bash
ruff check . && ruff format --check .
python scripts/validate_tweaks.py      # esquema + reglas + handlers resolubles
pytest                                  # en Linux se omiten los tests marcados "windows"
# El test e2e (tests/e2e) APLICA tweaks reales: solo corre con SAFETRIM_E2E=1, como admin y
# en Windows. Lo ejecuta el CI en una VM desechable; no lo lances en tu equipo.
pwsh -File scripts/verify_store_ids.ps1 # solo Windows: valida los IDs de Store del catálogo
```

### Empaquetado

```powershell
pip install -r requirements-build.txt   # PyInstaller 6.22.3
pyinstaller --clean --noconfirm packaging/SafeTrim.spec
.\dist\SafeTrim.exe --self-test           # catálogo y handlers dentro del binario
(Get-FileHash .\dist\SafeTrim.exe -Algorithm SHA256).Hash.ToLower()
```

El `.spec` genera un único `.exe` sin consola, con manifest `requireAdministrator`, sin UPX y
con recurso de versión. La línea de comandos equivalente está comentada al principio del
`.spec`. Los handlers de `tweaks/` se declaran como *hidden imports* porque se cargan
dinámicamente; `--self-test` lo verifica en `release.yml`.

## Uso

0. **Primeros pasos**: la primera vez, una guía de tres pantallas explica el modo simulación,
   la red de seguridad y cómo aplicar (se puede volver a abrir en Ajustes).
1. **Dashboard**: muestra RAM, CPU, disco, procesos, último tiempo de arranque y el
   entorno detectado (build, edición, SSD/HDD, portátil/sobremesa, dominio/MDM). Recomienda
   un perfil, o pide reiniciar o actualizar Windows antes si hay actualizaciones pendientes o
   atrasadas. Con menos de 5 GB de RAM avisa de que lo que más se nota es ampliar memoria.
   Si hay una versión nueva de SafeTrim publicada, muestra un aviso con el enlace.
1. **Diagnóstico**: "¿por qué va lento?". Mide durante un par de segundos y da un veredicto en
   lenguaje claro: RAM insuficiente (con ranuras libres y máximo admitido), procesos que
   acaparan CPU o memoria con explicación de los procesos de Windows conocidos, procesador
   modesto, disco duro mecánico, poco espacio, Windows Update pendiente o atrasado y, en
   Windows 10, si el equipo cumple los requisitos de Windows 11. Solo lee.
2. **Elegir perfil** (1, 2 o 3) y, si se quiere, marcar o desmarcar tweaks concretos en cada
   página (Bloatware, Inicio, Servicios, Limpieza, Optimización).
3. **Simulación (dry-run)**: activada por defecto la primera vez. Muestra cada cambio exacto
   (clave, valor actual → valor nuevo, servicio, paquete…) sin ejecutar nada.
4. **Revisión**: lista final con riesgo por cambio. Las acciones irreversibles (limpieza)
   requieren una casilla de confirmación aparte; los tweaks de riesgo alto, doble confirmación.
5. **Aplicar**: SafeTrim crea un punto de restauración, exporta las claves de registro
   afectadas a `.reg` y aplica. Un fallo en un tweak no detiene el resto.
6. **Resumen**: aplicados / omitidos / fallidos con la causa de cada uno, y medición antes/después.
7. **Historial/Deshacer**: revierte cualquier sesión anterior y verifica que cada cambio volvió
   a su estado previo ("Revertido y verificado"), exporta un informe HTML de la sesión, o abre
   "Restaurar sistema".
8. **Tras reiniciar**, una tarea temporal mide el nuevo tiempo de arranque y se elimina sola
   (desactivable en Ajustes). El resultado aparece en "Antes / después" del Dashboard.

### Datos locales

| Ruta | Contenido |
|---|---|
| `%LOCALAPPDATA%\SafeTrim\backups\<id de sesión>` | `.reg` de cada clave afectada (`YYYYMMDD-HHMMSS_<clave>.reg`), una carpeta por sesión |
| `%LOCALAPPDATA%\SafeTrim\sessions` | Registro de cambios por sesión (JSON): fuente de verdad para Deshacer |
| `%LOCALAPPDATA%\SafeTrim\logs` | Logs estructurados (JSON Lines) y logs exportados |
| `%LOCALAPPDATA%\SafeTrim\metrics` | Mediciones antes/después, incluido el tiempo de arranque tras reiniciar |

### Deriva tras actualizaciones de Windows

Al abrir SafeTrim, el Dashboard comprueba si alguno de los cambios aplicados (en sesiones no
deshechas) ya no está en vigor. Las actualizaciones grandes de Windows suelen restablecer
ajustes y reinstalar apps. Si hay deriva, se muestra la lista y un botón para revisarla y
reaplicarla con el flujo normal de simulación y confirmación.

### Replicar una configuración en otros equipos

*Dashboard → Exportar selección…* guarda los tweaks elegidos y sus parámetros en un JSON.
En otro equipo, *Importar selección…* los carga en la interfaz, o desde una consola de
administrador:

```powershell
.\SafeTrim.exe --apply-selection seleccion.json                 # solo simulación
.\SafeTrim.exe --apply-selection seleccion.json --yes           # aplica
.\SafeTrim.exe --apply-selection seleccion.json --yes --include-irreversible   # + limpieza
```

Los tweaks de riesgo alto (mitigaciones de CPU) nunca se aplican por CLI. Códigos de salida:
0 correcto, 1 sin permisos, 2 archivo o condiciones previas, 3 hubo fallos.

## Perfiles

Los perfiles son **acumulativos**: el nivel 2 incluye el 1 y el nivel 3 incluye el 1 y el 2.
Un perfil solo preselecciona los tweaks con `auto_profile: true` que cumplan las condiciones
del equipo. Lo demás aparece desmarcado y se puede activar a mano.

| Perfil | Qué incluye | Riesgo |
|---|---|---|
| **1 · Conservador** | Eliminar apps preinstaladas (AppX + provisioned), telemetría, ID de publicidad, sugerencias y anuncios, tareas de telemetría | Bajo. Todo reversible; las apps se reinstalan desde la Store (requiere red) |
| **2 · Equilibrado** | Nivel 1 + gestor de programas de inicio, servicios innecesarios a Manual, efectos visuales de rendimiento, limpieza, plan de energía | Bajo-medio. La limpieza es irreversible y pide confirmación aparte |
| **3 · Máximo** | Nivel 2 + red, prioridad de CPU, Game DVR, HAGS, indexado, servicios en segundo plano, memoria virtual | Medio. Algunas opciones exigen reinicio |

Fuera de cualquier perfil (solo manuales): hibernación, plan Máximo rendimiento, DNS,
indexado por unidad, pagefile fijo y **mitigaciones de CPU** (riesgo alto, doble confirmación).

### Gestor de programas de inicio (nivel 2)

No es un tweak del catálogo, sino una herramienta interactiva: enumera las claves `Run`/`RunOnce`
(HKLM, HKCU, WOW6432Node), las carpetas Startup y las tareas programadas con disparador de
inicio de sesión. Muestra un **impacto estimado**: se calcula con los eventos de
`Microsoft-Windows-Diagnostics-Performance` cuando existen y, si no, con una heurística (tamaño
del binario, editor, si es un actualizador). Windows no expone por API el valor del
Administrador de tareas. Desactivar una entrada usa el mismo mecanismo que el
Administrador de tareas (valores `StartupApproved`, o deshabilitar la tarea): no se borra nada,
y cada cambio queda en una sesión que se puede deshacer desde Historial.

## Modelo de tweaks

Cada entrada de `data/tweaks.json` se valida contra `data/tweaks.schema.json` (CI y pre-commit).
Campos obligatorios: `id`, `name`, `description`, `rationale`, `category`, `level`, `risk`,
`windows`, `kind`, `reversible`, `auto_profile`, `confirm_double`, `reboot_required`, `requires`,
`auto_when`, `apply`, `revert` y `detect`.

- **Operaciones `apply`**: `registry_set`, `registry_delete`, `service_start`, `appx_remove`,
  `task_state`, `command` (solo `powercfg`/`netsh`) y `handler` (función Python en `tweaks/`
  para lógica que no cabe en un JSON).
- **`revert`**: operaciones explícitas, `restore_snapshot` (restaura el estado previo
  capturado antes de aplicar, incluida la *ausencia* de un valor) o `none` (solo acciones).
- **`detect`**: `match_apply` (comprueba que cada operación de `apply` está en su estado
  objetivo), `registry_equals` o `handler`. Resultado: `applied`, `not_applied`, `partial`,
  `not_applicable` o `unknown`.
- **`requires`**: condiciones obligatorias (`disk`, `chassis`, `no_printers`, `not_domain`,
  `not_managed`, `check`). Si no se cumplen, el tweak aparece como "no aplicable".
- **`auto_when`**: condiciones para que un perfil lo preseleccione. Sin ellas sigue disponible a mano.
- **Reglas del esquema**: `kind: action` ⇒ `reversible: false`; tweak irreversible ⇒
  `auto_profile: false`; `risk: alto` ⇒ `auto_profile: false`; `confirm_double` ⇒ `risk: alto`.
- **`HKCU`** se resuelve contra el **usuario interactivo** (`HKU\<SID>` del dueño de
  `explorer.exe`), no contra la cuenta que eleva. Si se elevara con otra cuenta
  administradora, los cambios irían a ese perfil.
- Toda escritura bajo `...\Policies\...` es una **directiva**: en equipos de dominio o
  gestionados por MDM se omite con aviso, porque la GPO/Intune la sobrescribiría.

## Tabla de tweaks

### Nivel 1

| ID | Tweak | Riesgo | Perfil auto | Reversible | Windows |
|---|---|---|---|---|---|
| `bloatware.candy_crush` | Eliminar Candy Crush Saga y Soda Saga | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.xbox_app` | Eliminar App Xbox | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.solitaire` | Eliminar Microsoft Solitaire Collection | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.bing_news` | Eliminar Noticias (Bing News) | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.bing_weather` | Eliminar El Tiempo (Bing Weather) | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.clipchamp` | Eliminar Clipchamp | bajo | Sí | Sí, vía Store | 11 |
| `bloatware.teams_personal` | Eliminar Microsoft Teams (personal / Chat de Windows 11) | bajo | Sí | Sí, vía Store | 11 |
| `bloatware.cortana` | Eliminar Cortana | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.get_help` | Eliminar Obtener ayuda | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.tips` | Eliminar Sugerencias (Tips) | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.feedback_hub` | Eliminar Centro de opiniones (Feedback Hub) | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.mixed_reality` | Eliminar Portal de realidad mixta | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.viewer_3d` | Eliminar Visor 3D | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.paint_3d` | Eliminar Paint 3D | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.skype` | Eliminar Skype (retirado en 2025) | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.phone_link` | Eliminar Vincular al teléfono (Your Phone / Phone Link) | bajo | Sí | Sí, vía Store | 10/11 |
| `bloatware.widgets` | Eliminar Widgets (Windows Web Experience Pack) | bajo | Sí | Sí, vía Store | 11 |
| `bloatware.copilot` | Eliminar Copilot (app) | bajo | Sí | Sí, vía Store | 11 |
| `bloatware.news_interests` | Desactivar Widgets / Noticias e intereses | bajo | Sí | Sí | 10/11 |
| `bloatware.copilot_policy` | Desactivar Copilot por directiva | bajo | Sí | Sí | 11 |
| `privacy.diagtrack` | Desactivar servicio de telemetría (DiagTrack) | bajo | Sí | Sí | 10/11 |
| `privacy.dmwappush` | Desactivar dmwappushservice | bajo | Sí · requiere not_managed | Sí | 10/11 |
| `privacy.telemetry_policy_required` | Telemetría al mínimo permitido (Home/Pro) | bajo | Sí | Sí | 10/11 (Home/Pro) |
| `privacy.telemetry_policy_security` | Telemetría a nivel Seguridad (Enterprise/Education) | bajo | Sí | Sí | 10/11 (Enterprise/Education) |
| `privacy.advertising_id` | Desactivar ID de publicidad | bajo | Sí | Sí | 10/11 |
| `privacy.tailored_experiences` | Desactivar experiencias personalizadas | bajo | Sí | Sí | 10/11 |
| `privacy.suggestions_start` | Quitar sugerencias del menú Inicio | bajo | Sí | Sí | 10/11 |
| `privacy.suggestions_settings` | Quitar sugerencias en Configuración y consejos | bajo | Sí | Sí | 10/11 |
| `privacy.suggestions_lockscreen` | Quitar anuncios y datos curiosos de la pantalla de bloqueo | bajo | Sí | Sí | 10/11 |
| `privacy.silent_app_install` | Impedir la reinstalación silenciosa de apps promocionadas | bajo | Sí | Sí | 10/11 |
| `privacy.feedback_frequency` | No pedir opiniones (frecuencia de comentarios: nunca) | bajo | Sí | Sí | 10/11 |
| `privacy.task_compat_appraiser` | Desactivar tareas de telemetría: Compatibility Appraiser | bajo | Sí | Sí | 10/11 |
| `privacy.task_ceip` | Desactivar tareas de telemetría: Programa de mejora de la experiencia del cliente (CEIP) | bajo | Sí | Sí | 10/11 |
| `privacy.task_disk_diag` | Desactivar tareas de telemetría: Recopilador de diagnóstico de disco | bajo | Sí | Sí | 10/11 |

### Nivel 2

| ID | Tweak | Riesgo | Perfil auto | Reversible | Windows |
|---|---|---|---|---|---|
| `services.fax` | Fax: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.mapsbroker` | Administrador de mapas descargados: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.retaildemo` | Servicio de demostración comercial: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.wersvc` | Informe de errores de Windows: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.sysmain` | SysMain (Superfetch): pasar a Manual | bajo | Sí · requiere disk=ssd | Sí | 10/11 |
| `visual.best_performance` | Efectos visuales: mejor rendimiento (con suavizado de fuentes) | bajo | Sí | Sí | 10/11 |
| `cleanup.temp_user` | Limpiar: Temporales del usuario | bajo | Sí | No (acción) | 10/11 |
| `cleanup.temp_windows` | Limpiar: Temporales de Windows | bajo | Sí | No (acción) | 10/11 |
| `cleanup.wu_cache` | Limpiar: Caché de descargas de Windows Update | bajo | Sí | No (acción) | 10/11 |
| `cleanup.prefetch_orphans` | Limpiar: Prefetch obsoleto (>90 días) | bajo | Sí | No (acción) | 10/11 |
| `cleanup.recycle_bin` | Limpiar: Papelera de reciclaje | bajo | Sí | No (acción) | 10/11 |
| `cleanup.thumbnails` | Limpiar: Caché de miniaturas | bajo | Sí | No (acción) | 10/11 |
| `cleanup.windows_old` | Limpiar: Copia de la versión anterior de Windows (Windows.old), con el Liberador de espacio | medio | No · requiere que exista | No (acción) | 10/11 |
| `power.hibernate_off` | Desactivar hibernación | medio | No | Sí | 10/11 |
| `power.high_performance` | Plan de energía: Alto rendimiento | bajo | Sí (si chassis=desktop) | Sí | 10/11 |
| `power.ultimate_performance` | Plan de energía: Máximo rendimiento | medio | No · requiere chassis=desktop | Sí | 10/11 |

### Nivel 3

| ID | Tweak | Riesgo | Perfil auto | Reversible | Windows |
|---|---|---|---|---|---|
| `network.nagle_off` | Desactivar algoritmo de Nagle | bajo | Sí | Sí | 10/11 |
| `network.autotuning_normal` | TCP autotuning en 'normal' | bajo | Sí | Sí | 10/11 |
| `network.dns` | Cambiar servidores DNS | medio | No · requiere not_domain | Sí | 10/11 |
| `performance.foreground_priority` | Prioridad de CPU para la app en primer plano | bajo | Sí | Sí | 10/11 |
| `gaming.gamedvr_off` | Desactivar Game DVR y Game Bar | bajo | Sí | Sí | 10/11 |
| `gaming.hags` | Programación de GPU acelerada por hardware (HAGS) | medio | Sí · requiere check=tweaks.gaming:hags_supported | Sí | 10/11 |
| `search.indexing_drives` | Desactivar indexado en unidades seleccionadas | bajo | No | Sí | 10/11 |
| `services.pcasvc` | Asistente de compatibilidad de programas: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.trkwks` | Cliente de seguimiento de vínculos distribuidos: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.wisvc` | Servicio de Windows Insider: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.phonesvc` | Servicio telefónico: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.wmpnetworksvc` | Uso compartido de red del Reproductor de Windows Media: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.xblauthmanager` | Administración de autenticación de Xbox Live: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.xblgamesave` | Partida guardada en Xbox Live: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.xboxnetapisvc` | Servicio de red de Xbox Live: pasar a Manual | bajo | Sí | Sí | 10/11 |
| `services.lfsvc` | Servicio de geolocalización: pasar a Manual | bajo | Sí · requiere chassis=desktop | Sí | 10/11 |
| `services.spooler` | Cola de impresión: pasar a Manual | bajo | Sí · requiere no_printers | Sí | 10/11 |
| `privacy.background_apps` | Restringir apps en segundo plano | medio | Sí | Sí | 10/11 |
| `memory.pagefile_system_managed` | Archivo de paginación gestionado por el sistema | bajo | Sí | Sí | 10/11 |
| `memory.pagefile_fixed` | Archivo de paginación con tamaño fijo | alto | No | Sí | 10/11 |
| `security.cpu_mitigations_off` | Desactivar mitigaciones de CPU (Spectre/Meltdown) | alto | No | Sí | 10/11 |

Notas:
- "Reversible vía Store": la reversión reinstala la app con `winget install --source msstore`.
  Requiere red. Cuatro entradas (`candy_crush`, `teams_personal`, `tips`, `skype`) no tienen
  ID de Store verificado y se buscan por nombre.
- Las apps que ya no vienen en builds recientes (Mixed Reality Portal, Paint 3D, Skype…) se
  muestran como "no aplicable" si no están instaladas.
- En Home/Pro, `AllowTelemetry=0` no se respeta; por eso hay dos tweaks de telemetría según la edición.

## Qué NO toca SafeTrim

La lista de protección está en código (`core/constants.py`) y se comprueba en **cada**
operación. Un `tweaks.json` editado por error no puede saltársela.

- **Windows Defender / Seguridad de Windows**: `WinDefend`, `WdNisSvc`, `Sense`, `SecurityHealthService`,
  `wscsvc`, `mpssvc` (firewall), paquete `Microsoft.SecHealthUI`.
- **Windows Update (núcleo)**: `wuauserv`, `UsoSvc`, `BITS`, `TrustedInstaller`, `WaaSMedicSvc`,
  `DoSvc`. La limpieza de caché borra solo descargas antiguas sin detener servicios.
- **Microsoft Store e infraestructura AppX**: `Microsoft.WindowsStore`, `Microsoft.StorePurchaseApp`,
  `Microsoft.DesktopAppInstaller` (winget), `AppXSvc`, `ClipSVC`, `InstallService`.
- **Red esencial**: `Dhcp`, `Dnscache`, `NlaSvc`, `netprofm`, `nsi`, `LanmanWorkstation`,
  `WlanSvc`, `WwanSvc`, `RpcSs`, `BFE`, `iphlpsvc`.
- **Drivers**: no se desinstalan ni se modifican servicios de tipo kernel/filesystem driver.
- **Runtimes**: .NET (`Microsoft.NET.*`), `Microsoft.VCLibs.*`, `Microsoft.UI.Xaml.*`,
  VC++ Redistributables y `Microsoft.WindowsAppRuntime.*`.
- **Impresión**: `Spooler` y `PrintNotify` si hay alguna impresora física o de red instalada.
- **Identidad Xbox**: `Microsoft.XboxIdentityProvider` y `Microsoft.Xbox.TCUI`, que necesitan
  los juegos de PC y Game Pass.
- **Teams de trabajo**: el paquete `MSTeams` (Teams nuevo) no se elimina; solo `MicrosoftTeams` (Chat personal).
- **Búsqueda**: el servicio `WSearch` no se desactiva; solo el atributo de indexado por unidad.

## Seguridad operativa

- **Punto de restauración** obligatorio antes de aplicar. Si Protección del sistema está desactivada
  o la creación falla, SafeTrim bloquea la aplicación salvo que en Ajustes se active
  "Continuar sin punto de restauración". Durante la sesión se ajusta temporalmente
  `SystemRestorePointCreationFrequency` para saltar el límite de 24 h de Windows, y después se restaura.
- **Copia `.reg`** de cada clave afectada, con timestamp, además del registro JSON de sesión.
  El JSON es el que usa Deshacer, porque un `.reg` no puede expresar "este valor no existía".
- **Dominio / Entra ID / MDM** (detectado con `dsregcmd /status`): aviso permanente y directivas
  desactivadas. `dmwappushservice` no se toca.
- **Procesos externos con prioridad baja** y PowerShell de uno en uno, para no saturar equipos
  con poca CPU o RAM.
- **Red**: la única conexión es la consulta de la última versión a la API de Releases de GitHub
  al arrancar (desactivable en Ajustes). Con el repositorio privado responde 404 y SafeTrim no
  muestra nada; el aviso solo funciona si las Releases son públicas.
- **Valida siempre en una VM con snapshots** (Hyper-V o VirtualBox) antes de usar una versión
  nueva en un equipo real.

## Estructura del repositorio

```
main.py                 Punto de entrada (comprueba admin y lanza la UI)
core/                   Motor: registro, servicios, AppX, tareas, restauración, logging, entorno
tweaks/                 Handlers Python por categoría (referenciados desde tweaks.json)
ui/                     CustomTkinter: ventana, sidebar, páginas, diálogos
data/tweaks.json        Catálogo declarativo
data/tweaks.schema.json Esquema JSON del catálogo
tests/                  pytest con registro/servicios simulados
packaging/              .spec de PyInstaller y recurso de versión del .exe
scripts/                Validación del catálogo y de IDs de Store
docs/                   Configuración de GitHub y distribución
.github/                CI, release y Dependabot
```

## Flujo de trabajo

- Ramas `feat/*` y `fix/*` → PR hacia `main` (contra uno mismo) para que se ejecute el CI.
- Commits con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/), versiones con SemVer.
- Release: tag `vX.Y.Z` en `main` → `release.yml` compila, calcula el SHA256 y publica.
- Configuración de GitHub (protección de rama según plan, escaneo de secretos, consumo de
  minutos, publicación de versiones): [`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md).
- Entrega del `.exe` a terceros, antivirus/SmartScreen y firma de código:
  [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md).

## Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Estructura, README, pyproject, catálogo y esquema | ✅ |
| 2 | `core/` | ✅ |
| 3 | `tweaks/` (handlers) | ✅ |
| 4 | `ui/` y `main.py` | ✅ |
| 5 | Tests, GitHub Actions, empaquetado, docs de distribución | ✅ |

Probado: lint, 110 tests con registro simulado, recorrido completo de la UI en `--demo` y
`--self-test` del binario de PyInstaller. **No probado todavía sobre Windows real**: ver Pendiente.

## Pendiente

- **Validar en una VM Windows 10 22H2 y 11 24H2** (con snapshot): perfil 1, 2 y 3, Deshacer,
  y medición del arranque tras reiniciar. Es la primera ejecución sobre un sistema real.
- Ejecutar `scripts/verify_store_ids.ps1` y completar los cuatro `store_id: null`.
- Si el repo se hace público: añadir `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md` y plantillas
  de issues/PR, y revisar el historial en busca de datos personales.
