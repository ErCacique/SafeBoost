"""Documentación oficial de cada tweak: demuestra que ningún cambio es inventado.

Se asigna por prefijo de ID (el más largo gana) para no repetir la misma URL en cada entrada del
catálogo. Solo páginas estables de Microsoft (learn.microsoft.com) o del fabricante.
"""

from __future__ import annotations

SOURCES: dict[str, str] = {
    "bloatware.": "https://learn.microsoft.com/windows/application-management/remove-provisioned-apps-during-update",
    "bloatware.copilot_policy": "https://learn.microsoft.com/windows/client-management/manage-windows-copilot",
    "bloatware.news_interests": "https://learn.microsoft.com/windows/client-management/mdm/policy-csp-newsandinterests",
    "privacy.": "https://learn.microsoft.com/windows/privacy/manage-connections-from-windows-operating-system-components-to-microsoft-services",
    "privacy.diagtrack": "https://learn.microsoft.com/windows/privacy/configure-windows-diagnostic-data-in-your-organization",
    "privacy.telemetry_policy": "https://learn.microsoft.com/windows/privacy/configure-windows-diagnostic-data-in-your-organization",
    "privacy.advertising_id": "https://learn.microsoft.com/windows/client-management/mdm/policy-csp-privacy",
    "privacy.background_apps": "https://learn.microsoft.com/windows/client-management/mdm/policy-csp-privacy",
    "services.": "https://learn.microsoft.com/windows-server/security/windows-services/security-guidelines-for-disabling-system-services-in-windows-server",
    "services.sysmain": "https://learn.microsoft.com/windows-server/security/windows-services/security-guidelines-for-disabling-system-services-in-windows-server",
    "visual.": "https://learn.microsoft.com/troubleshoot/windows-client/performance/performance-options-visual-effects",
    "cleanup.": "https://learn.microsoft.com/windows-server/administration/windows-commands/cleanmgr",
    "power.": "https://learn.microsoft.com/windows-hardware/design/device-experiences/powercfg-command-line-options",
    "network.nagle_off": "https://learn.microsoft.com/troubleshoot/windows-server/networking/tcp-ip-performance-known-issues",
    "network.autotuning": "https://learn.microsoft.com/windows-server/networking/technologies/network-subsystem/net-sub-performance-tuning-nics",
    "network.dns": "https://learn.microsoft.com/windows-server/networking/dns/dns-overview",
    "performance.edge_": "https://learn.microsoft.com/deployedge/microsoft-edge-policies",
    "performance.chrome_background": "https://chromeenterprise.google/policies/#BackgroundModeEnabled",
    "performance.foreground_priority": "https://learn.microsoft.com/windows/win32/procthread/scheduling-priorities",
    "gaming.gamedvr_off": "https://learn.microsoft.com/windows/client-management/mdm/policy-csp-applicationmanagement",
    "gaming.hags": "https://devblogs.microsoft.com/directx/hardware-accelerated-gpu-scheduling/",
    "search.": "https://learn.microsoft.com/windows/win32/search/-search-indexing-process-overview",
    "memory.": "https://learn.microsoft.com/troubleshoot/windows-client/performance/how-to-determine-the-appropriate-page-file-size-for-64-bit-versions-of-windows",
    "security.cpu_mitigations_off": "https://learn.microsoft.com/troubleshoot/windows-server/performance/understand-speculative-execution-side-channel-vulnerabilities",
}


def source_for(tweak_id: str) -> str:
    """URL de documentación del prefijo más largo que coincide; "" si no hay ninguno."""
    best = ""
    for prefix in SOURCES:
        if tweak_id.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return SOURCES.get(best, "")
