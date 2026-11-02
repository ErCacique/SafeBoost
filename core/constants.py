"""Constantes globales de WinTune: rutas, listas de protección y valores de configuración.

Todo valor "mágico" del proyecto vive aquí o en data/tweaks.json.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

APP_NAME: Final = "WinTune"
APP_VERSION: Final = "0.1.0"
APP_ID: Final = "ErCacique.WinTune"

# --------------------------------------------------------------------------- rutas


def _app_home() -> Path:
    """Raíz de datos locales. WINTUNE_HOME permite redirigirla (tests, portable)."""
    override = os.environ.get("WINTUNE_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def _resource_root() -> Path:
    """Raíz de recursos empaquetados: sys._MEIPASS con PyInstaller, raíz del repo en desarrollo."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


APP_HOME: Final = _app_home()
BACKUP_DIR: Final = APP_HOME / "backups"
SESSIONS_DIR: Final = APP_HOME / "sessions"
LOG_DIR: Final = APP_HOME / "logs"
METRICS_DIR: Final = APP_HOME / "metrics"
STARTUP_BACKUP_DIR: Final = APP_HOME / "startup_disabled"
SETTINGS_FILE: Final = APP_HOME / "settings.json"

RESOURCE_ROOT: Final = _resource_root()
TWEAKS_FILE: Final = RESOURCE_ROOT / "data" / "tweaks.json"

SYSTEM_ROOT: Final = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
SYSTEM32: Final = SYSTEM_ROOT / "System32"
POWERSHELL_EXE: Final = SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"

# Ejecutables que pueden invocar las operaciones "command" del catálogo.
ALLOWED_COMMAND_EXES: Final[dict[str, Path]] = {
    "powercfg": SYSTEM32 / "powercfg.exe",
    "netsh": SYSTEM32 / "netsh.exe",
}

# --------------------------------------------------------------------------- logging

LOG_FILE_NAME: Final = "wintune.jsonl"
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

# --------------------------------------------------------------------------- limpieza

CLEAN_TEMP_MIN_AGE_HOURS: Final = 24
CLEAN_WU_MIN_AGE_DAYS: Final = 10

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
