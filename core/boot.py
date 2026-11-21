"""Qué retrasa el arranque: eventos 101-110 de Microsoft-Windows-Diagnostics-Performance.

Windows registra, en cada arranque lento, qué programa, servicio o driver lo retrasó y cuántos
milisegundos. Aquí se agregan los de los últimos días para decir, por ejemplo, "OneDrive retrasa
el arranque unos 6 s en 4 de cada 5 arranques". Solo lee el registro de eventos (requiere admin).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.constants import BOOT_EVENT_ID, DIAG_PERF_LOG
from core.logger import get_logger
from core.process import CommandError, Runner, as_list, ps_quote

log = get_logger("boot")

BOOT_CULPRIT_DAYS = 60
BOOT_CULPRIT_TOP = 8
# Por debajo de esto un retraso no merece la atención del usuario.
BOOT_CULPRIT_MIN_MS = 1000

# EventID → qué tipo de cosa retrasó el arranque.
EVENT_KINDS: dict[int, str] = {
    101: "programa",
    102: "driver",
    103: "servicio",
    104: "componente del sistema",
    105: "dispositivo",
    106: "optimización en segundo plano",
    107: "directivas del equipo",
    108: "directivas del usuario",
    109: "dispositivo",
    110: "inicio de sesión",
}


@dataclass
class BootCulprit:
    kind: str
    name: str  # nombre legible (FriendlyName) o, si no hay, el del archivo
    file: str  # nombre del archivo (Name), útil para cruzarlo con los programas de inicio
    company: str
    count: int = 0
    total_ms: int = 0
    max_ms: int = 0

    @property
    def avg_ms(self) -> int:
        return self.total_ms // self.count if self.count else 0

    @property
    def advice(self) -> str:
        if self.kind == "programa":
            return "Si no lo necesitas nada más encender, desactívalo en la página Inicio."
        if self.kind == "servicio":
            return "Si es de un fabricante (actualizadores, utilidades), puede pasarse a Manual."
        if self.kind == "driver":
            return "Actualiza el driver desde la web del fabricante del equipo."
        if self.kind == "optimización en segundo plano":
            return "Es Windows reorganizando archivos tras cambios; suele bajar solo."
        return ""


@dataclass
class BootReport:
    boots: int = 0  # arranques registrados en el periodo
    culprits: list[BootCulprit] = field(default_factory=list)
    available: bool = True  # False si el registro de eventos no se pudo leer


def _script(days: int) -> str:
    ids = ",".join(str(i) for i in EVENT_KINDS)
    log_name = ps_quote(DIAG_PERF_LOG)
    since = f"(Get-Date).AddDays(-{days})"
    return (
        f"$ev = @(Get-WinEvent -FilterHashtable @{{LogName={log_name}; Id={ids};"
        f" StartTime={since}}} -MaxEvents 500 -ErrorAction SilentlyContinue);"
        f"$boots = @(Get-WinEvent -FilterHashtable @{{LogName={log_name}; Id={BOOT_EVENT_ID};"
        f" StartTime={since}}} -ErrorAction SilentlyContinue).Count;"
        "$items = foreach ($e in $ev) { $x = [xml]$e.ToXml(); $d = @{};"
        " foreach ($n in $x.Event.EventData.Data) { $d[[string]$n.Name] = [string]$n.'#text' };"
        " @{id=$e.Id; name=$d['Name']; friendly=$d['FriendlyName']; company=$d['CompanyName'];"
        " total=$d['TotalTime']; degradation=$d['DegradationTime']} };"
        "@{boots=$boots; items=@($items)} | ConvertTo-Json -Compress -Depth 4"
    )


def _ms(value: object) -> int:
    try:
        return max(int(float(str(value))), 0)
    except (TypeError, ValueError):
        return 0


def aggregate(data: dict, top: int = BOOT_CULPRIT_TOP) -> BootReport:
    """Agrupa los eventos por elemento y ordena por retraso acumulado. Función pura."""
    report = BootReport(boots=_ms(data.get("boots")))
    grouped: dict[tuple[str, str], BootCulprit] = {}
    for item in as_list(data.get("items")):
        if not isinstance(item, dict):
            continue
        kind = EVENT_KINDS.get(_ms(item.get("id")))
        if kind is None:
            continue
        file = str(item.get("name") or "").strip()
        name = str(item.get("friendly") or "").strip() or file or kind
        # DegradationTime es lo que se pasó de lo normal; si falta, el tiempo total.
        delay = _ms(item.get("degradation")) or _ms(item.get("total"))
        key = (kind, (file or name).lower())
        culprit = grouped.setdefault(
            key, BootCulprit(kind, name, file, str(item.get("company") or "").strip())
        )
        culprit.count += 1
        culprit.total_ms += delay
        culprit.max_ms = max(culprit.max_ms, delay)
    culprits = [c for c in grouped.values() if c.avg_ms >= BOOT_CULPRIT_MIN_MS]
    culprits.sort(key=lambda c: c.total_ms, reverse=True)
    report.culprits = culprits[:top]
    return report


def read_boot_culprits(runner: Runner, days: int = BOOT_CULPRIT_DAYS) -> BootReport:
    try:
        data = runner.powershell_json(_script(days))
    except CommandError as exc:
        log.warning("boot_culprits_unavailable", extra={"err": str(exc)})
        return BootReport(available=False)
    if not isinstance(data, dict):
        return BootReport()
    return aggregate(data)
