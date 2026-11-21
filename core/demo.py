"""Modo demostración (`python main.py --demo`): entorno y sistema simulados.

Permite desarrollar y probar la interfaz fuera de Windows o sin privilegios. Nada de lo que
se "aplica" en este modo toca el sistema real: el registro es en memoria y los comandos se
responden con datos ficticios.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from core.constants import SERVICES_KEY
from core.environment import EnvironmentInfo
from core.process import CommandResult
from core.registry import MemoryRegistryBackend, RegValue

DEMO_SID = "S-1-5-21-1000000000-2000000000-3000000000-1001"

_DEMO_SERVICES: dict[str, int] = {
    "DiagTrack": 2,
    "dmwappushservice": 3,
    "Fax": 3,
    "MapsBroker": 2,
    "RetailDemo": 3,
    "WerSvc": 3,
    "SysMain": 2,
    "PcaSvc": 2,
    "TrkWks": 2,
    "wisvc": 3,
    "PhoneSvc": 3,
    "WMPNetworkSvc": 3,
    "XblAuthManager": 3,
    "XblGameSave": 3,
    "XboxNetApiSvc": 3,
    "lfsvc": 3,
    "Spooler": 2,
    "WinDefend": 2,
    "wuauserv": 3,
}


def demo_environment() -> EnvironmentInfo:
    return EnvironmentInfo(
        build=22631,
        ubr=4317,
        display_version="23H2",
        product_name="Windows 10 Pro",
        edition_id="Professional",
        edition="pro",
        system_drive="C:",
        disk_type="ssd",
        chassis="desktop",
        interactive_user="DEMO\\usuario",
        interactive_sid=DEMO_SID,
        elevated_user="DEMO\\usuario",
        is_admin=True,
        fixed_drives=["C:", "D:"],
        warnings=["Modo demostración: ningún cambio afecta al sistema real."],
    )


def demo_registry() -> MemoryRegistryBackend:
    backend = MemoryRegistryBackend()
    for name, start in _DEMO_SERVICES.items():
        key = f"{SERVICES_KEY}\\{name}"
        backend.seed("HKLM", key, "Start", RegValue("REG_DWORD", start))
        backend.seed("HKLM", key, "Type", RegValue("REG_DWORD", 16))
    backend.seed(
        "HKLM",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
        "SecurityHealth",
        RegValue("REG_EXPAND_SZ", r"%windir%\system32\SecurityHealthSystray.exe"),
    )
    user_run = rf"{DEMO_SID}\Software\Microsoft\Windows\CurrentVersion\Run"
    backend.seed(
        "HKU",
        user_run,
        "OneDrive",
        RegValue("REG_SZ", r'"C:\Program Files\Microsoft OneDrive\OneDrive.exe" /background'),
    )
    backend.seed(
        "HKU",
        user_run,
        "Spotify",
        RegValue("REG_SZ", r'"C:\Users\usuario\AppData\Roaming\Spotify\Spotify.exe" /minimized'),
    )
    backend.seed(
        "HKLM",
        r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{11111111-2222-3333-4444-555555555555}",
        "DhcpIPAddress",
        RegValue("REG_SZ", "192.168.1.20"),
    )
    backend.seed(
        "HKLM",
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore",
        "RPSessionInterval",
        RegValue("REG_DWORD", 1),
    )
    return backend


class DemoRunner:
    """Responde a los comandos con datos plausibles. No ejecuta nada."""

    def __init__(self, backend: MemoryRegistryBackend | None = None) -> None:
        # Con el backend del registro simulado, "sc config" cambia el Start del servicio igual
        # que en Windows; así la detección, la deriva y la verificación son coherentes.
        self.backend = backend
        self._sequence = 40
        self._scheme = "381b4222-f694-41f0-9685-ff5bb260df2e"
        self._removed: set[str] = set()
        self._tasks: dict[str, str] = {}

    def run(self, args: list[str], timeout: int = 60, encoding: str | None = None) -> CommandResult:
        joined = " ".join(args).lower()
        out = ""
        if "/getactivescheme" in joined:
            out = f"GUID del plan de energía: {self._scheme}  (Demo)"
        elif "/list" in joined and "powercfg" in joined:
            out = (
                "381b4222-f694-41f0-9685-ff5bb260df2e (Equilibrado)\n"
                "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c (Alto rendimiento)"
            )
        elif "/setactive" in joined:
            self._scheme = args[-1].lower()
        elif "dxdiag" in joined:
            return CommandResult(tuple(args), 1, "", "dxdiag no disponible en demo")
        elif self.backend is not None and len(args) >= 5 and args[1] == "config":
            start = {"auto": 2, "delayed-auto": 2, "demand": 3, "disabled": 4}.get(args[4])
            if start is not None:
                key = f"{SERVICES_KEY}\\{args[2]}"
                self.backend.write("HKLM", key, "Start", RegValue("REG_DWORD", start))
        return CommandResult(tuple(args), 0, out, "")

    @staticmethod
    def _task_path(script: str) -> str:
        quoted = script.split("'")
        return quoted[1] + quoted[3]

    def powershell(self, script: str, timeout: int = 120) -> CommandResult:
        for verb, state in (
            ("Disable-ScheduledTask", "Disabled"),
            ("Enable-ScheduledTask", "Ready"),
        ):
            if script.startswith(verb):
                self._tasks[self._task_path(script).lower()] = state
        if "Remove-AppxPackage" in script or "Remove-AppxProvisionedPackage" in script:
            self._removed.add(script.split("'")[1].split("_")[0].lower())
        return CommandResult(("powershell",), 0, "", "")

    def powershell_json(self, script: str, timeout: int = 120) -> Any:
        if "Get-AppxPackage" in script:
            names = [
                "king.com.CandyCrushSaga",
                "Microsoft.BingNews",
                "Microsoft.BingWeather",
                "Clipchamp.Clipchamp",
                "Microsoft.MicrosoftSolitaireCollection",
                "Microsoft.GetHelp",
                "Microsoft.Getstarted",
                "Microsoft.WindowsFeedbackHub",
                "Microsoft.YourPhone",
                "Microsoft.Copilot",
                "Microsoft.GamingApp",
            ]
            live = [n for n in names if n.lower() not in self._removed]
            return {
                "installed": [
                    {"Name": n, "PackageFullName": f"{n}_1.0.0.0_x64__demo"} for n in live
                ],
                "provisioned": [
                    {"DisplayName": n, "PackageName": f"{n}_1.0.0.0_neutral_~_demo"} for n in live
                ],
            }
        if "SequenceNumber" in script:
            self._sequence += 1
            return self._sequence
        if "MSFT_TaskLogonTrigger" in script:
            return [
                {
                    "path": "\\Adobe Acrobat Update Task",
                    "state": "Ready",
                    "action": r"C:\Program Files (x86)\Common Files\Adobe\ARM\1.0\AdobeARM.exe",
                }
            ]
        if "foreach ($p in" in script and "Get-ScheduledTask" in script:
            paths = re.findall(r"'(\\[^']+)'", script.split("foreach ($p in")[1].split(")")[0])
            return {p: self._tasks.get(p.lower(), "Ready") for p in paths}
        if "Get-ScheduledTask -TaskPath" in script:
            return {"state": self._tasks.get(self._task_path(script).lower(), "Ready")}
        if "Get-NetTCPSetting" in script:
            return [{"level": "Normal"}]
        if "Get-NetAdapter" in script:
            return [{"index": 12, "name": "Ethernet", "static": "", "servers": ["192.168.1.1"]}]
        if "Win32_PageFileSetting" in script:
            return {"auto": True, "settings": []}
        if "Win32_PhysicalMemoryArray" in script:
            return {
                "cpu": "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz",
                "cores": 4,
                "threads": 8,
                "mhz": 1800,
                "slots": 2,
                "max_kb": 32 * 1024 * 1024,
                "modules": [
                    {
                        "cap": 8 * 1024**3,
                        "type": 26,
                        "form": 12,
                        "speed": 2400,
                        "maker": "Samsung",
                        "part": "M471A1K43CB1-CTD",
                    }
                ],
                "disks": [
                    {
                        "name": "WDC PC SN520 256GB",
                        "media": "SSD",
                        "size": 256 * 10**9,
                        "health": "Healthy",
                        "wear": 7,
                        "temp": 38,
                        "read_errors": 0,
                        "hours": 6120,
                    }
                ],
                "battery": {"design": 41000, "full": 29500, "cycles": 412},
                "cpu_perf": {"performance": 92, "utility": 18},
                "devices": [],
                "gpus": [
                    {
                        "name": "Intel(R) UHD Graphics 620",
                        "version": "26.20.100.7262",
                        "date": "2019-09-25",
                    }
                ],
                "tpm": "2.0, 0, 1.38",
                "secure_boot": True,
                "firmware": "UEFI",
            }
        if "Start-MpScan" in script:
            return {"enabled": True, "threats": [], "signature_age": 1}
        if "DegradationTime" in script:
            return {
                "boots": 9,
                "items": [
                    {
                        "id": 101,
                        "name": "OneDrive.exe",
                        "friendly": "Microsoft OneDrive",
                        "company": "Microsoft",
                        "total": "9100",
                        "degradation": "6200",
                    },
                    {
                        "id": 101,
                        "name": "OneDrive.exe",
                        "friendly": "Microsoft OneDrive",
                        "company": "Microsoft",
                        "total": "8800",
                        "degradation": "5900",
                    },
                    {
                        "id": 103,
                        "name": "HPAppHelperCap",
                        "friendly": "HP App Helper HSA Service",
                        "company": "HP Inc.",
                        "total": "5200",
                        "degradation": "4100",
                    },
                    {
                        "id": 102,
                        "name": "iaStorAC.sys",
                        "friendly": "Intel RST",
                        "company": "Intel",
                        "total": "2300",
                        "degradation": "1500",
                    },
                ],
            }
        if "Get-HotFix" in script:
            return 12
        if "Win32_Volume" in script:
            return [{"letter": "C:", "indexing": True}, {"letter": "D:", "indexing": True}]
        if "EventID=100" in script:
            return {"boot_ms": 24310, "timestamp": datetime.now().replace(hour=8).isoformat()}
        return None
