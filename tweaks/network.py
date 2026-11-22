"""Red: algoritmo de Nagle, TCP autotuning y servidores DNS."""

from __future__ import annotations

from core.constants import DNS_PROVIDERS, TCPIP_INTERFACES_KEY
from core.context import DetectResult, DetectState, HandlerContext, HandlerError, SkipOperation
from core.process import ps_quote
from core.registry import RegValue
from tweaks._common import ps_json, ps_run, run_tool

NAGLE_VALUES = ("TcpAckFrequency", "TCPNoDelay")
# Direcciones que Windows guarda en el registro cuando una interfaz no tiene IP.
NO_ADDRESS = ("", "0.0.0.0")  # noqa: S104 - no es un bind, es un valor a ignorar
AUTOTUNING_LEVELS = ("disabled", "highlyrestricted", "restricted", "normal", "experimental")


# --------------------------------------------------------------------------- Nagle


def _active_interfaces(ctx: HandlerContext) -> list[str]:
    """Subclaves {GUID} de Tcpip\\Interfaces con dirección IPv4 (DHCP o estática)."""
    out = []
    for guid in ctx.registry.subkeys("HKLM", TCPIP_INTERFACES_KEY):
        path = f"{TCPIP_INTERFACES_KEY}\\{guid}"
        dhcp = ctx.registry.read("HKLM", path, "DhcpIPAddress")
        static = ctx.registry.read("HKLM", path, "IPAddress")
        has_dhcp = dhcp is not None and dhcp.data not in NO_ADDRESS
        has_static = (
            static is not None
            and isinstance(static.data, list)
            and any(ip not in NO_ADDRESS for ip in static.data)
        )
        if has_dhcp or has_static:
            out.append(path)
    return out


def set_nagle(ctx: HandlerContext) -> bool:
    if ctx.params.get("enabled", False):
        raise HandlerError("set_nagle solo admite enabled=false; se revierte con restore_snapshot")
    interfaces = _active_interfaces(ctx)
    if not interfaces:
        raise SkipOperation("No hay interfaces de red con IPv4 configurada")
    changed = False
    for path in interfaces:
        for name in NAGLE_VALUES:
            changed |= ctx.set_registry("HKLM", path, name, RegValue("REG_DWORD", 1))
    return changed


def detect_nagle(ctx: HandlerContext) -> DetectResult:
    interfaces = _active_interfaces(ctx)
    if not interfaces:
        return DetectResult(DetectState.NOT_APPLICABLE, "Sin interfaces activas")
    flags = []
    for path in interfaces:
        for name in NAGLE_VALUES:
            value = ctx.registry.read("HKLM", path, name)
            flags.append(value is not None and value.data == 1)
    if all(flags):
        return DetectResult(DetectState.APPLIED)
    return DetectResult(DetectState.PARTIAL if any(flags) else DetectState.NOT_APPLIED)


# --------------------------------------------------------------------------- autotuning


def _autotuning_level(ctx: HandlerContext) -> str:
    rows = ps_json(
        ctx,
        "Get-NetTCPSetting | Where-Object { $_.SettingName -eq 'Internet' } | "
        "ForEach-Object { @{level=$_.AutoTuningLevelLocal.ToString()} } | ConvertTo-Json -Compress",
    )
    if not rows:
        raise HandlerError("No se pudo leer el nivel de autotuning")
    return str(rows[0]["level"]).lower()


def _set_level(ctx: HandlerContext, level: str) -> None:
    if level not in AUTOTUNING_LEVELS:
        raise HandlerError(f"Nivel de autotuning no válido: {level}")
    run_tool(
        ctx,
        "netsh",
        ["interface", "tcp", "set", "global", f"autotuninglevel={level}"],
        f"TCP autotuning → {level}",
    )


def set_autotuning(ctx: HandlerContext) -> bool:
    target = ctx.params["level"]
    current = _autotuning_level(ctx)
    if current == target:
        return False
    _set_level(ctx, target)
    if not ctx.dry_run:
        ctx.state["previous"] = current
    return True


def restore_autotuning(ctx: HandlerContext) -> bool:
    previous = ctx.prior_state.get("previous")
    if not previous:
        return False
    _set_level(ctx, previous)
    return True


def detect_autotuning(ctx: HandlerContext) -> DetectResult:
    current = _autotuning_level(ctx)
    target = ctx.params["level"]
    state = DetectState.APPLIED if current == target else DetectState.NOT_APPLIED
    return DetectResult(state, f"Actual: {current}")


# --------------------------------------------------------------------------- DNS


def _adapters(ctx: HandlerContext) -> list[dict]:
    """Adaptadores físicos conectados con sus DNS IPv4 y si son estáticos o por DHCP."""
    rows = ps_json(
        ctx,
        "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object {"
        " $g = $_.InterfaceGuid;"
        " $k = Get-ItemProperty ('HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters"
        "\\Interfaces\\' + $g) -ErrorAction SilentlyContinue;"
        " $d = (Get-DnsClientServerAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4)"
        ".ServerAddresses;"
        " @{index=$_.ifIndex; name=$_.Name; static=[string]$k.NameServer; servers=@($d)} }"
        " | ConvertTo-Json -Depth 3 -Compress",
    )
    return rows


def set_dns(ctx: HandlerContext) -> bool:
    provider = ctx.params.get("provider")
    if not provider:
        raise HandlerError("Elige un proveedor DNS antes de aplicar este tweak")
    servers = DNS_PROVIDERS.get(provider)
    if servers is None:
        raise HandlerError(f"Proveedor DNS desconocido: {provider}")
    adapters = _adapters(ctx)
    if not adapters:
        raise SkipOperation("No hay adaptadores de red conectados")
    previous = []
    changed = False
    for adapter in adapters:
        if list(adapter.get("servers") or []) == list(servers):
            continue
        # NameServer vacío en el registro = DNS asignado por DHCP.
        static = [s for s in str(adapter.get("static") or "").replace(",", " ").split() if s]
        previous.append({"index": adapter["index"], "name": adapter["name"], "static": static})
        addr = ",".join(ps_quote(s) for s in servers)
        ps_run(
            ctx,
            f"Set-DnsClientServerAddress -InterfaceIndex {int(adapter['index'])} "
            f"-ServerAddresses @({addr})",
            f"DNS de {adapter['name']} → {provider} ({', '.join(servers)})",
        )
        changed = True
    if changed:
        ps_run(ctx, "Clear-DnsClientCache", "Vaciar la caché DNS")
        if not ctx.dry_run:
            ctx.state["adapters"] = previous
    return changed


def restore_dns(ctx: HandlerContext) -> bool:
    adapters = ctx.prior_state.get("adapters") or []
    for adapter in adapters:
        index = int(adapter["index"])
        if adapter["static"]:
            addr = ",".join(ps_quote(s) for s in adapter["static"])
            script = (
                f"Set-DnsClientServerAddress -InterfaceIndex {index} -ServerAddresses @({addr})"
            )
            what = f"DNS de {adapter['name']} → {', '.join(adapter['static'])}"
        else:
            script = f"Set-DnsClientServerAddress -InterfaceIndex {index} -ResetServerAddresses"
            what = f"DNS de {adapter['name']} → automático (DHCP)"
        ps_run(ctx, script, what)
    if adapters:
        ps_run(ctx, "Clear-DnsClientCache", "Vaciar la caché DNS")
    return bool(adapters)


def detect_dns(ctx: HandlerContext) -> DetectResult:
    adapters = _adapters(ctx)
    if not adapters:
        return DetectResult(DetectState.NOT_APPLICABLE, "Sin adaptadores conectados")
    for provider, servers in DNS_PROVIDERS.items():
        if all(list(a.get("servers") or []) == list(servers) for a in adapters):
            return DetectResult(DetectState.APPLIED, f"Usando {provider}", {"provider": provider})
    current = ", ".join(sorted({s for a in adapters for s in (a.get("servers") or [])}))
    return DetectResult(DetectState.NOT_APPLIED, f"DNS actuales: {current or 'ninguno'}")
