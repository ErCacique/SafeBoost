"""Constantes globales de SafeTrim: rutas, listas de protección y valores de configuración.

Todo valor "mágico" del proyecto vive aquí o en data/tweaks.json.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

APP_NAME: Final = "SafeTrim"
APP_VERSION: Final = "0.5.0"
APP_ID: Final = "ErCacique.SafeTrim"

# --------------------------------------------------------------------------- rutas


# Versión portable (USB): si junto al .exe hay un archivo con este nombre, los datos se guardan
# en una carpeta al lado del programa y no se toca %LOCALAPPDATA%.
PORTABLE_MARKER: Final = "portable.txt"
PORTABLE_DATA_DIR: Final = "SafeTrimData"


def _portable_home() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    return exe_dir / PORTABLE_DATA_DIR if (exe_dir / PORTABLE_MARKER).exists() else None


def _home_override() -> str | None:
    # WINTUNE_HOME es el nombre anterior de la variable (hasta 0.2.x): se sigue aceptando.
    env = os.environ.get("SAFETRIM_HOME") or os.environ.get("WINTUNE_HOME")
    if env:
        return env
    portable = _portable_home()
    return str(portable) if portable else None


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))


def _app_home() -> Path:
    """Raíz de datos locales. SAFETRIM_HOME permite redirigirla (tests, portable)."""
    override = _home_override()
    if override:
        return Path(override)
    return _local_appdata() / APP_NAME


def _resource_root() -> Path:
    """Raíz de recursos empaquetados: sys._MEIPASS con PyInstaller, raíz del repo en desarrollo."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


APP_HOME: Final = _app_home()
HOME_OVERRIDDEN: Final = _home_override() is not None
PORTABLE_MODE: Final = _portable_home() is not None

# Nombre anterior del programa (hasta 0.2.x). Se usa solo para migrar datos y tareas.
LEGACY_APP_NAME: Final = "WinTune"
LEGACY_HOME: Final = _local_appdata() / LEGACY_APP_NAME
LEGACY_LOG_FILE_NAME: Final = "wintune.jsonl"
LEGACY_TASK_FOLDER: Final = "\\WinTune\\"
LEGACY_SELECTION_FORMATS: Final = ("wintune-selection",)
# Marca que se deja en la carpeta antigua tras copiarla (no se borra nada).
LEGACY_MIGRATED_MARKER: Final = "MIGRADO_A_SAFETRIM.txt"
BACKUP_DIR: Final = APP_HOME / "backups"
SESSIONS_DIR: Final = APP_HOME / "sessions"
LOG_DIR: Final = APP_HOME / "logs"
METRICS_DIR: Final = APP_HOME / "metrics"
SETTINGS_FILE: Final = APP_HOME / "settings.json"

RESOURCE_ROOT: Final = _resource_root()
TWEAKS_FILE: Final = RESOURCE_ROOT / "data" / "tweaks.json"
ICON_FILE: Final = RESOURCE_ROOT / "assets" / "safetrim.ico"


def self_command() -> list[str]:
    """Orden para relanzar SafeTrim: el .exe empaquetado o `python main.py` en desarrollo."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(RESOURCE_ROOT / "main.py")]


SYSTEM_ROOT: Final = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
SYSTEM32: Final = SYSTEM_ROOT / "System32"
POWERSHELL_EXE: Final = SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"

# Ejecutables que pueden invocar las operaciones "command" del catálogo.
ALLOWED_COMMAND_EXES: Final[dict[str, Path]] = {
    "powercfg": SYSTEM32 / "powercfg.exe",
    "netsh": SYSTEM32 / "netsh.exe",
    # Liberador de espacio: solo con el perfil /sagerun que prepara tweaks.cleanup (Windows.old).
    "cleanmgr": SYSTEM32 / "cleanmgr.exe",
}

# --------------------------------------------------------------------------- logging

LOG_FILE_NAME: Final = "safetrim.jsonl"
LOG_MAX_BYTES: Final = 2 * 1024 * 1024
LOG_BACKUP_COUNT: Final = 5

# --------------------------------------------------------------------------- Windows

MIN_BUILD_WIN10: Final = 19045
MIN_BUILD_WIN11: Final = 22000
SUPPORTED_EDITIONS: Final = ("home", "pro", "enterprise", "education")

# EditionID del registro → edición normalizada.
EDITION_MAP: Final[dict[str, str]] = {
    "Core": "home",
    "CoreN": "home",
    "CoreSingleLanguage": "home",
    "CoreCountrySpecific": "home",
    "Professional": "pro",
    "ProfessionalN": "pro",
    "ProfessionalWorkstation": "pro",
    "ProfessionalEducation": "education",
    "Enterprise": "enterprise",
    "EnterpriseN": "enterprise",
    "EnterpriseS": "enterprise",
    "IoTEnterprise": "enterprise",
    "IoTEnterpriseS": "enterprise",
    "Education": "education",
    "EducationN": "education",
}

# Win32_SystemEnclosure.ChassisTypes que indican portátil/tableta.
LAPTOP_CHASSIS_TYPES: Final = frozenset({8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32})

# Impresoras virtuales que no cuentan como "hay impresoras instaladas".
VIRTUAL_PRINTER_MARKERS: Final = (
    "Microsoft Print to PDF",
    "Microsoft XPS Document Writer",
    "OneNote",
    "Fax",
    "Send To OneNote",
)

# --------------------------------------------------------------------------- lista de protección
# Se comprueba en cada operación (core/protection.py), independientemente del catálogo.

PROTECTED_SERVICES: Final = frozenset(
    s.lower()
    for s in (
        # Defender / Seguridad de Windows
        "WinDefend",
        "WdNisSvc",
        "WdNisDrv",
        "WdFilter",
        "WdBoot",
        "Sense",
        "SecurityHealthService",
        "wscsvc",
        "mpssvc",
        "SgrmBroker",
        # Windows Update (núcleo)
        "wuauserv",
        "UsoSvc",
        "BITS",
        "TrustedInstaller",
        "WaaSMedicSvc",
        "DoSvc",
        # Store / AppX
        "AppXSvc",
        "ClipSVC",
        "InstallService",
        "StateRepository",
        "LicenseManager",
        # Red esencial
        "Dhcp",
        "Dnscache",
        "NlaSvc",
        "netprofm",
        "nsi",
        "LanmanWorkstation",
        "WlanSvc",
        "WwanSvc",
        "RpcSs",
        "RpcEptMapper",
        "BFE",
        "iphlpsvc",
        "Netman",
        "WinHttpAutoProxySvc",
        # Núcleo del sistema
        "EventLog",
        "PlugPlay",
        "Power",
        "ProfSvc",
        "Schedule",
        "SamSs",
        "LSM",
        "gpsvc",
        "CryptSvc",
        "DcomLaunch",
        "Winmgmt",
        "Audiosrv",
        "AudioEndpointBuilder",
        "Themes",
        "VSS",
        "swprv",
        "SENS",
        "UserManager",
        "CoreMessagingRegistrar",
        "BrokerInfrastructure",
    )
)

# Solo protegidos si hay alguna impresora física o de red instalada.
PRINT_SERVICES: Final = frozenset({"spooler", "printnotify"})

# Prefijos de paquetes AppX que nunca se eliminan (comparación case-insensitive).
PROTECTED_APPX_PREFIXES: Final = (
    "Microsoft.WindowsStore",
    "Microsoft.StorePurchaseApp",
    "Microsoft.DesktopAppInstaller",
    "Microsoft.SecHealthUI",
    "Microsoft.Windows.SecHealthUI",
    "Microsoft.NET.",
    "Microsoft.VCLibs.",
    "Microsoft.UI.Xaml.",
    "Microsoft.WindowsAppRuntime.",
    "Microsoft.Services.Store.Engagement",
    "Microsoft.XboxIdentityProvider",
    "Microsoft.Xbox.TCUI",
    "Microsoft.AAD.BrokerPlugin",
    "Microsoft.AccountsControl",
    "Microsoft.Windows.ShellExperienceHost",
    "Microsoft.Windows.StartMenuExperienceHost",
    "MicrosoftWindows.Client.CBS",
    "MicrosoftWindows.Client.Core",
    "Microsoft.Windows.CloudExperienceHost",
    "MSTeams",  # Teams nuevo: también se usa para trabajo
)

# Rutas de registro (relativas a HKLM, en minúsculas) que nunca se escriben.
PROTECTED_REGISTRY_PREFIXES: Final = (
    r"software\policies\microsoft\windows defender",
    r"software\microsoft\windows defender",
    r"software\policies\microsoft\windows\windowsupdate",
    r"software\microsoft\windowsupdate",
    r"system\currentcontrolset\control\class",  # drivers de dispositivo
)

# Tipos de servicio que son drivers (SERVICE_KERNEL_DRIVER | SERVICE_FILE_SYSTEM_DRIVER).
DRIVER_SERVICE_TYPE_MASK: Final = 0x1 | 0x2

# Marcador de clave de directiva: en equipos gestionados no se escribe.
POLICY_PATH_MARKER: Final = "\\policies\\"

# --------------------------------------------------------------------------- servicios

SERVICES_KEY: Final = r"SYSTEM\CurrentControlSet\Services"
SERVICE_START_VALUES: Final[dict[str, int]] = {
    "automatic": 2,
    "automatic_delayed": 2,
    "manual": 3,
    "disabled": 4,
}
SC_START_ARG: Final[dict[str, str]] = {
    "automatic": "auto",
    "automatic_delayed": "delayed-auto",
    "manual": "demand",
    "disabled": "disabled",
}

# --------------------------------------------------------------------------- restauración

SYSTEM_RESTORE_KEY: Final = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore"
RESTORE_FREQUENCY_VALUE: Final = "SystemRestorePointCreationFrequency"
RESTORE_POINT_TYPE: Final = "MODIFY_SETTINGS"
RSTRUI_EXE: Final = SYSTEM32 / "rstrui.exe"

# --------------------------------------------------------------------------- tiempos (segundos)

TIMEOUT_DEFAULT: Final = 60
TIMEOUT_POWERSHELL: Final = 120
TIMEOUT_APPX: Final = 300
TIMEOUT_RESTORE_POINT: Final = 600
TIMEOUT_WINGET: Final = 600
TIMEOUT_DXDIAG: Final = 90

# --------------------------------------------------------------------------- tareas propias

# Carpeta del Programador de tareas para las tareas temporales que crea SafeTrim.
SAFETRIM_TASK_FOLDER: Final = "\\SafeTrim\\"
POST_REBOOT_TASK_NAME: Final = "PostRebootMetrics"
# Retraso tras el inicio de sesión: Windows registra el evento de arranque unos minutos
# después de terminar el arranque.
POST_REBOOT_DELAY: Final = "PT10M"

# --------------------------------------------------------------------------- limpieza

CLEAN_TEMP_MIN_AGE_HOURS: Final = 24
CLEAN_WU_MIN_AGE_DAYS: Final = 10
CLEAN_PREFETCH_MIN_AGE_DAYS: Final = 90
# Por debajo de este tamaño una limpieza se considera ya hecha.
CLEAN_NEGLIGIBLE_BYTES: Final = 1024 * 1024
# Windows permite volver a la versión anterior durante 10 días tras una actualización grande.
WINDOWS_OLD_ROLLBACK_DAYS: Final = 10
CLEANMGR_PROFILE: Final = 42  # /sagerun:42 → valor StateFlags0042
CLEANMGR_PREVIOUS_INSTALLS_KEY: Final = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VolumeCaches\Previous Installations"
)
TIMEOUT_CLEANMGR: Final = 1800

# --------------------------------------------------------------------------- energía

POWER_SCHEMES: Final[dict[str, str]] = {
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "ultimate_performance": "e9a42b02-d5df-448d-aa00-03f14749eb61",
    "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
}

# --------------------------------------------------------------------------- red

DNS_PROVIDERS: Final[dict[str, tuple[str, ...]]] = {
    "cloudflare": ("1.1.1.1", "1.0.0.1"),
    "quad9": ("9.9.9.9", "149.112.112.112"),
    "google": ("8.8.8.8", "8.8.4.4"),
}
TCPIP_INTERFACES_KEY: Final = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"

# --------------------------------------------------------------------------- inicio

RUN_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
)
STARTUP_APPROVED_KEYS: Final[dict[str, str]] = {
    "run": r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
    "run32": r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32",
    "folder": r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder",
}

# --------------------------------------------------------------------------- métricas

DIAG_PERF_LOG: Final = "Microsoft-Windows-Diagnostics-Performance/Operational"
BOOT_EVENT_ID: Final = 100
BOOT_DEGRADATION_EVENT_ID: Final = 101

# Umbrales para recomendar perfil (RAM en GiB).
RECOMMEND_LOW_RAM_GIB: Final = 8
RECOMMEND_HIGH_PROC_COUNT: Final = 200
# Por debajo de esta RAM (GiB) ningún perfil sustituye a ampliar memoria. 5 deja dentro los
# equipos de 4 GB, que psutil ve como ~3.8 GiB, y fuera los de 6 GB.
LOW_RAM_GIB: Final = 5

# --------------------------------------------------------------------------- diagnóstico

DIAG_SAMPLE_SECONDS: Final = 1.5
DIAG_TOP_PROCESSES: Final = 5
DIAG_RAM_PRESSURE_PERCENT: Final = 85
DIAG_CPU_BUSY_PERCENT: Final = 80
DIAG_PROCESS_HOG_PERCENT: Final = 25
DIAG_LOW_DISK_FREE_PERCENT: Final = 10
DIAG_WEAK_CPU_THREADS: Final = 2
# Un elemento que retrasa el arranque de media más que esto se señala en el veredicto.
DIAG_BOOT_CULPRIT_WARN_MS: Final = 3000

# Procesos de Windows y programas comunes → explicación en lenguaje claro (nombre en minúsculas).
_WU_HINT = "Windows Update instalando o preparando actualizaciones: déjalo terminar y reinicia."
_SEARCH_HINT = "La búsqueda de Windows indexando archivos. Se calma sola al terminar."
_DEFENDER_HINT = "Windows Defender analizando archivos. Es normal unos minutos; no lo desactives."
_BROWSER_HINT = "Navegador: cada pestaña abierta consume memoria. Cierra las que no uses."
KNOWN_PROCESSES: Final[dict[str, str]] = {
    "msmpeng.exe": _DEFENDER_HINT,
    "mpdefendercoreservice.exe": _DEFENDER_HINT,
    "tiworker.exe": _WU_HINT,
    "trustedinstaller.exe": _WU_HINT,
    "mousocoreworker.exe": _WU_HINT,
    "wuauclt.exe": _WU_HINT,
    "usoclient.exe": _WU_HINT,
    "sihclient.exe": _WU_HINT,
    "searchindexer.exe": _SEARCH_HINT,
    "searchprotocolhost.exe": _SEARCH_HINT,
    "searchfilterhost.exe": _SEARCH_HINT,
    "compattelrunner.exe": (
        "Telemetría de compatibilidad de Windows. El perfil 1 desactiva su tarea."
    ),
    "memory compression": (
        "Windows está comprimiendo memoria porque se queda sin RAM: síntoma de RAM insuficiente."
    ),
    "svchost.exe": (
        "Servicios de Windows agrupados. Si es alto mucho rato, suele ser Windows Update."
    ),
    "dwm.exe": "Gestor de ventanas de Windows (dibuja la pantalla).",
    "onedrive.exe": "OneDrive sincronizando archivos.",
    "chrome.exe": _BROWSER_HINT,
    "msedge.exe": _BROWSER_HINT,
    "firefox.exe": _BROWSER_HINT,
    "opera.exe": _BROWSER_HINT,
    "brave.exe": _BROWSER_HINT,
    "safetrim.exe": "SafeTrim (este programa).",
}

# --------------------------------------------------------------------------- Windows Update

# Cualquiera de estas claves presente = hay un reinicio pendiente de actualizaciones.
WU_REBOOT_KEYS: Final = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
)
UPDATE_STALE_DAYS: Final = 60

# --------------------------------------------------------------------------- Windows 10/11

WIN10_END_OF_SUPPORT: Final = "14 de octubre de 2025"
WIN11_MIN_RAM_GIB: Final = 4
WIN11_MIN_STORAGE_GIB: Final = 64

# --------------------------------------------------------------------------- versión nueva

UPDATE_REPO: Final = "ErCacique/WinOpt"
UPDATE_API_URL: Final = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
UPDATE_CHECK_TIMEOUT: Final = 5

# --------------------------------------------------------------------------- procesos externos

# En equipos flojos, varias PowerShell a la vez saturan la CPU: se lanzan de una en una.
POWERSHELL_MAX_CONCURRENT: Final = 1

# Comprobaciones requires.check demasiado lentas para el arranque (dxdiag: 20-90 s en equipos
# flojos). La interfaz las resuelve en segundo plano con la ventana ya abierta.
SLOW_CHECKS: Final = frozenset({"tweaks.gaming:hags_supported"})
