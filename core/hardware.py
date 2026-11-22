"""Salud del hardware: RAM (y qué comprar), discos, batería, rendimiento del procesador, drivers.

Todo sale de una única consulta de PowerShell (CIM), cada parte aislada en su try/catch: un
dato que falte solo deja esa sección vacía. Las funciones de análisis son puras y devuelven
hallazgos como tuplas (nivel, título, detalle) para no depender de core.diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from core.logger import get_logger
from core.metrics import human_bytes
from core.process import CommandError, Runner, as_list

log = get_logger("hardware")
_Date = date  # GpuDriver tiene un campo llamado `date`

GIB = 1024**3
HwFinding = tuple[str, str, str]  # (nivel, título, detalle)

# SMBIOS: tipo de memoria (Win32_PhysicalMemory.SMBIOSMemoryType).
MEMORY_TYPES: dict[int, str] = {
    20: "DDR",
    21: "DDR2",
    24: "DDR3",
    26: "DDR4",
    27: "LPDDR",
    28: "LPDDR2",
    29: "LPDDR3",
    30: "LPDDR4",
    34: "DDR5",
    35: "LPDDR5",
}
# Win32_PhysicalMemory.FormFactor
FORM_FACTORS: dict[int, str] = {8: "DIMM", 12: "SO-DIMM"}

# Códigos de error del Administrador de dispositivos más habituales.
DEVICE_ERRORS: dict[int, str] = {
    1: "configuración incorrecta",
    3: "driver dañado o sin memoria suficiente",
    10: "el dispositivo no puede iniciarse",
    12: "conflicto de recursos",
    14: "hay que reiniciar",
    18: "hay que reinstalar el driver",
    19: "configuración del registro dañada",
    21: "Windows lo está quitando",
    24: "no está presente o falta el driver",
    28: "no tiene driver instalado",
    31: "Windows no puede cargar su driver",
    37: "el driver devolvió un error",
    39: "el driver falta o está dañado",
    43: "Windows lo detuvo porque informó de problemas",
    45: "no está conectado",
    52: "driver sin firma digital válida",
}

DISK_WEAR_WARN = 80  # % de vida del SSD consumida
DISK_TEMP_WARN = 60  # °C
BATTERY_WARN = 60  # % de la capacidad original
BATTERY_INFO = 80
THROTTLE_BUSY_UTILITY = 70  # % de uso a partir del cual se mira la velocidad
THROTTLE_PERFORMANCE = 60  # % de la velocidad nominal por debajo de lo cual es sospechoso
GPU_DRIVER_OLD_DAYS = 3 * 365

HARDWARE_SCRIPT = (
    "$r = @{};"
    "try { $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1;"
    " $r.cpu=[string]$cpu.Name; $r.cores=[int]$cpu.NumberOfCores;"
    " $r.threads=[int]$cpu.NumberOfLogicalProcessors; $r.mhz=[int]$cpu.MaxClockSpeed } catch {};"
    # Win32_PhysicalMemoryArray.Use = 3 → memoria del sistema (no caché ni vídeo).
    "try { $arr = @(Get-CimInstance Win32_PhysicalMemoryArray | Where-Object { $_.Use -eq 3 });"
    " $r.slots=[int](($arr | Measure-Object -Property MemoryDevices -Sum).Sum);"
    " $r.max_kb=[int64](($arr | Measure-Object -Property MaxCapacityEx -Sum).Sum) } catch {};"
    "try { $r.modules = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {"
    " @{cap=[int64]$_.Capacity; type=[int]$_.SMBIOSMemoryType; form=[int]$_.FormFactor;"
    " speed=[int]$_.Speed; maker=[string]$_.Manufacturer; part=([string]$_.PartNumber).Trim()}"
    " }) } catch {};"
    "try { $r.tpm = [string](Get-CimInstance -Namespace root/cimv2/security/microsofttpm"
    " -ClassName Win32_Tpm -ErrorAction Stop).SpecVersion } catch {};"
    "try { $r.secure_boot = [bool](Confirm-SecureBootUEFI -ErrorAction Stop) } catch {};"
    "$r.firmware = [string]$env:firmware_type;"
    "try { $r.disks = @(Get-PhysicalDisk | ForEach-Object {"
    " $c = $_ | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue;"
    " @{name=[string]$_.FriendlyName; media=[string]$_.MediaType; size=[int64]$_.Size;"
    " health=[string]$_.HealthStatus; wear=$c.Wear; temp=$c.Temperature;"
    " read_errors=$c.ReadErrorsUncorrected; hours=$c.PowerOnHours} }) } catch {};"
    "try { $s = Get-CimInstance -Namespace root/wmi -ClassName BatteryStaticData"
    " -ErrorAction Stop | Select-Object -First 1;"
    " $f = Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity"
    " -ErrorAction Stop | Select-Object -First 1;"
    " $cc = try { (Get-CimInstance -Namespace root/wmi -ClassName BatteryCycleCount"
    " -ErrorAction Stop | Select-Object -First 1).CycleCount } catch { $null };"
    " if ($s -and $f) { $r.battery = @{design=[int64]$s.DesignedCapacity;"
    " full=[int64]$f.FullChargedCapacity; cycles=$cc} } } catch {};"
    # Nombres de clase CIM, no de contador: los contadores de rendimiento están traducidos.
    "try { $p = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation"
    " -Filter \"Name='_Total'\" -ErrorAction Stop;"
    " $r.cpu_perf = @{performance=[int]$p.PercentProcessorPerformance;"
    " utility=[int]$p.PercentProcessorUtility} } catch {};"
    "try { $r.devices = @(Get-CimInstance Win32_PnPEntity -Filter 'ConfigManagerErrorCode<>0'"
    " | Where-Object { $_.ConfigManagerErrorCode -ne 22 } | ForEach-Object {"
    " @{name=[string]$_.Name; code=[int]$_.ConfigManagerErrorCode} }) } catch {};"
    "try { $r.gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {"
    " @{name=[string]$_.Name; version=[string]$_.DriverVersion;"
    " date=$(if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { '' })} })"
    " } catch {};"
    "$r | ConvertTo-Json -Compress -Depth 4"
)


@dataclass
class MemoryModule:
    capacity: int
    mem_type: int = 0
    form: int = 0
    speed: int = 0  # MHz (MT/s)
    maker: str = ""
    part: str = ""

    @property
    def type_name(self) -> str:
        return MEMORY_TYPES.get(self.mem_type, "")

    @property
    def form_name(self) -> str:
        return FORM_FACTORS.get(self.form, "")

    @property
    def soldered(self) -> bool:
        # LPDDR va soldada a la placa: no se puede ampliar.
        return self.type_name.startswith("LP")


@dataclass
class DiskHealth:
    name: str
    media: str = ""
    size: int = 0
    health: str = ""  # Healthy / Warning / Unhealthy
    wear: int | None = None  # % de vida consumida (SSD)
    temp: int | None = None  # °C
    read_errors: int | None = None
    hours: int | None = None


@dataclass
class BatteryHealth:
    design: int  # mWh
    full: int  # mWh
    cycles: int | None = None

    @property
    def percent(self) -> int:
        return round(self.full / self.design * 100) if self.design else 0


@dataclass
class CpuPerf:
    performance: int  # % de la frecuencia nominal (>100 con turbo)
    utility: int  # % de uso


@dataclass
class DeviceProblem:
    name: str
    code: int

    @property
    def meaning(self) -> str:
        return DEVICE_ERRORS.get(self.code, f"error {self.code}")


@dataclass
class GpuDriver:
    name: str
    version: str = ""
    date: str = ""  # YYYY-MM-DD

    def age_days(self, today: _Date | None = None) -> int | None:
        try:
            built = date.fromisoformat(self.date)
        except ValueError:
            return None
        return ((today or date.today()) - built).days


@dataclass
class HardwareDetails:
    memory: list[MemoryModule] = field(default_factory=list)
    disks: list[DiskHealth] = field(default_factory=list)
    battery: BatteryHealth | None = None
    cpu_perf: CpuPerf | None = None
    devices: list[DeviceProblem] = field(default_factory=list)
    gpus: list[GpuDriver] = field(default_factory=list)


# --------------------------------------------------------------------------- parseo


def _int(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def parse_details(data: dict) -> HardwareDetails:
    details = HardwareDetails()
    for mod in as_list(data.get("modules")):
        if isinstance(mod, dict):
            if _int(mod.get("cap")):
                details.memory.append(
                    MemoryModule(
                        capacity=_int(mod.get("cap")) or 0,
                        mem_type=_int(mod.get("type")) or 0,
                        form=_int(mod.get("form")) or 0,
                        speed=_int(mod.get("speed")) or 0,
                        maker=str(mod.get("maker") or "").strip(),
                        part=str(mod.get("part") or "").strip(),
                    )
                )
        elif _int(mod):  # formato antiguo: solo la capacidad
            details.memory.append(MemoryModule(capacity=_int(mod) or 0))
    for disk in as_list(data.get("disks")):
        if isinstance(disk, dict):
            details.disks.append(
                DiskHealth(
                    name=str(disk.get("name") or "Disco").strip(),
                    media=str(disk.get("media") or ""),
                    size=_int(disk.get("size")) or 0,
                    health=str(disk.get("health") or ""),
                    wear=_int(disk.get("wear")),
                    temp=_int(disk.get("temp")),
                    read_errors=_int(disk.get("read_errors")),
                    hours=_int(disk.get("hours")),
                )
            )
    battery = data.get("battery")
    if isinstance(battery, dict) and _int(battery.get("design")):
        details.battery = BatteryHealth(
            _int(battery.get("design")) or 0,
            _int(battery.get("full")) or 0,
            _int(battery.get("cycles")),
        )
    perf = data.get("cpu_perf")
    if isinstance(perf, dict) and _int(perf.get("performance")) is not None:
        details.cpu_perf = CpuPerf(
            _int(perf.get("performance")) or 0, _int(perf.get("utility")) or 0
        )
    for dev in as_list(data.get("devices")):
        if isinstance(dev, dict) and _int(dev.get("code")):
            details.devices.append(
                DeviceProblem(str(dev.get("name") or "Dispositivo"), _int(dev.get("code")) or 0)
            )
    for gpu in as_list(data.get("gpus")):
        if isinstance(gpu, dict) and gpu.get("name"):
            details.gpus.append(
                GpuDriver(
                    str(gpu["name"]), str(gpu.get("version") or ""), str(gpu.get("date") or "")
                )
            )
    return details


def query_hardware(runner: Runner) -> dict | None:
    try:
        data = runner.powershell_json(HARDWARE_SCRIPT)
    except CommandError as exc:
        log.warning("hardware_query_failed", extra={"err": str(exc)})
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- qué RAM comprar


def ram_purchase_advice(
    memory: list[MemoryModule], slots: int, max_capacity: int, installed: int
) -> str:
    """Qué módulo comprar exactamente, con lo que Windows sabe de la memoria instalada."""
    if not memory:
        return ""
    first = memory[0]
    if any(m.soldered for m in memory):
        return (
            f"La memoria es {first.type_name} soldada a la placa: no se puede ampliar. "
            "La alternativa es aligerar lo que arranca con Windows."
        )
    kind = " ".join(p for p in (first.type_name, first.form_name) if p) or "del mismo tipo"
    speed = max((m.speed for m in memory), default=0)
    speed_text = f" a {speed} MHz o más (funcionará a {speed} MHz)" if speed else ""
    target = 8 * GIB if installed < 8 * GIB else 16 * GIB
    if max_capacity:
        target = min(target, max_capacity)
    free = max(slots - len(memory), 0) if slots else None
    if free:
        add = max(target - installed, 4 * GIB)
        size = 8 if add > 4 * GIB else 4
        same = round(first.capacity / GIB)
        tip = (
            f" Si eliges {same} GB, igual que el actual, funcionará en doble canal"
            " (algo más rápido)."
            if same in (4, 8) and same != size
            else ""
        )
        return (
            f"Compra un módulo {kind} de {size} GB{speed_text} y ponlo en la ranura libre "
            f"({free} de {slots} libre).{tip}"
        )
    biggest = min(target, max_capacity) if max_capacity else target
    return (
        f"Todas las ranuras ({slots or len(memory)}) están ocupadas: sustituye los módulos por "
        f"{kind}{speed_text} hasta sumar {human_bytes(biggest)}."
    )


# --------------------------------------------------------------------------- análisis


def hardware_findings(
    details: HardwareDetails, plugged: bool | None = None, today: date | None = None
) -> list[HwFinding]:
    out: list[HwFinding] = []
    for disk in details.disks:
        health = disk.health.lower()
        if health in ("unhealthy", "warning") or (disk.read_errors or 0) > 0:
            out.append(
                (
                    "critical",
                    "El disco puede estar fallando",
                    f"{disk.name} informa de estado “{disk.health or 'con errores'}”"
                    + (f" y {disk.read_errors} errores de lectura" if disk.read_errors else "")
                    + ". Haz una copia de seguridad de tus archivos cuanto antes y plantéate "
                    "cambiarlo: un disco que falla hace que todo vaya lento.",
                )
            )
        elif disk.wear is not None and disk.wear >= DISK_WEAR_WARN:
            out.append(
                (
                    "warning",
                    "SSD desgastado",
                    f"{disk.name} ha consumido el {disk.wear} % de su vida útil estimada. "
                    "Sigue funcionando, pero conviene tener copia de seguridad.",
                )
            )
        if disk.temp is not None and disk.temp >= DISK_TEMP_WARN:
            out.append(
                (
                    "warning",
                    "Disco muy caliente",
                    f"{disk.name} está a {disk.temp} °C. Revisa la ventilación del equipo.",
                )
            )
    battery = details.battery
    if battery and battery.percent:
        cycles = f" tras {battery.cycles} ciclos de carga" if battery.cycles else ""
        if battery.percent < BATTERY_WARN:
            out.append(
                (
                    "warning",
                    "Batería muy gastada",
                    f"La batería conserva el {battery.percent} % de su capacidad original"
                    f"{cycles}. Cambiarla devolvería la autonomía; no afecta a la velocidad "
                    "con el cargador enchufado.",
                )
            )
        elif battery.percent < BATTERY_INFO:
            out.append(
                (
                    "info",
                    "Batería algo gastada",
                    f"La batería conserva el {battery.percent} % de su capacidad original{cycles}.",
                )
            )
    perf = details.cpu_perf
    if perf and perf.utility >= THROTTLE_BUSY_UTILITY and perf.performance < THROTTLE_PERFORMANCE:
        cause = (
            "Estás con batería: el modo de ahorro reduce la velocidad a propósito."
            if plugged is False
            else "Con el cargador puesto, lo más probable es calor: limpia el ventilador y las "
            "rejillas, y no lo uses sobre superficies blandas."
        )
        out.append(
            (
                "warning",
                "Procesador frenado",
                f"El procesador está ocupado pero va al {perf.performance} % de su velocidad "
                f"normal. {cause}",
            )
        )
    for dev in details.devices:
        out.append(
            (
                "warning",
                "Dispositivo con problemas",
                f"{dev.name}: {dev.meaning}. Instala el driver desde la web del fabricante del "
                "equipo.",
            )
        )
    for gpu in details.gpus:
        age = gpu.age_days(today)
        if age is not None and age > GPU_DRIVER_OLD_DAYS:
            out.append(
                (
                    "info",
                    "Driver de gráfica antiguo",
                    f"El driver de {gpu.name} es de {gpu.date[:4]} (versión {gpu.version}). "
                    "Uno reciente de la web del fabricante puede mejorar estabilidad y vídeo.",
                )
            )
    return out
