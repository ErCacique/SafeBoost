"""Informe para el cliente (técnicos): estado del equipo, cambios hechos y recomendaciones.

Se genera en HTML y se convierte a PDF con Microsoft Edge en modo headless, que viene con
Windows 10/11; sin Edge se guarda el HTML (se puede imprimir a PDF desde cualquier navegador).
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from core.catalog import Catalog
from core.constants import APP_NAME, APP_VERSION
from core.diagnostics import DiagnosticReport
from core.hardware import ram_purchase_advice
from core.license import Branding
from core.metrics import human_bytes
from core.process import CommandError, Runner
from core.report import _CSS
from core.session import Session

EDGE_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
LEVEL_LABEL = {"critical": "Importante", "warning": "Atención", "info": "Información", "ok": "Bien"}


def render_client_html(
    report: DiagnosticReport,
    sessions: list[Session],
    catalog: Catalog,
    technician: str = "",
    branding: Branding | None = None,
) -> str:
    """`branding` (edición Técnico) pone el nombre, contacto y logo del técnico en la cabecera."""
    env, snap, hw = report.env, report.snapshot, report.hardware
    rows = [
        ("Sistema", env.os_label + f" · {env.edition.capitalize()}"),
        ("Procesador", hw.cpu_name if hw and hw.cpu_name else "desconocido"),
        ("Memoria", f"{human_bytes(report.ram_installed)} ({snap.ram_percent:.0f} % en uso)"),
        (
            "Disco del sistema",
            f"{env.disk_type.upper()} · {human_bytes(snap.disk_free)} libres de "
            f"{human_bytes(snap.disk_total)}",
        ),
    ]
    if hw and hw.details.battery and hw.details.battery.percent:
        rows.append(("Batería", f"{hw.details.battery.percent} % de su capacidad original"))
    equipo = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
    findings = "".join(
        f"<li><b>{escape(LEVEL_LABEL[f.level])} · {escape(f.title)}</b><br>{escape(f.detail)}</li>"
        for f in report.findings
    )
    applied = [s for s in sessions if s.kind == "apply" and not s.reverted_by]
    changes = []
    for session in applied:
        names = [
            catalog.get(tid).name if tid in catalog else tid
            for tid, r in session.results.items()
            if r.status in ("applied", "partial")
        ]
        if names:
            changes.append(
                f"<li>{escape(session.created.replace('T', ' '))}: "
                + escape(", ".join(names))
                + "</li>"
            )
    advice = (
        ram_purchase_advice(hw.details.memory, hw.slots, hw.max_capacity, report.ram_installed)
        if hw
        else ""
    )
    by = f" · Técnico: {escape(technician)}" if technician else ""
    header = ""
    if branding is not None and (branding.business or branding.has_logo):
        logo = branding.logo_data_uri()
        header = (
            '<div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">'
            + (f'<img src="{logo}" alt="" style="max-height:64px;max-width:200px">' if logo else "")
            + f"<div><b>{escape(branding.business)}</b><br>"
            + f'<span class="muted">{escape(branding.contact)}</span></div></div>'
        )
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Informe del equipo</title><style>{_CSS}</style></head><body>
{header}<h1>Informe del equipo</h1>
<p class="muted">{datetime.now():%Y-%m-%d %H:%M} · {APP_NAME} {APP_VERSION}{by}</p>
<h2>Equipo</h2><table>{equipo}</table>
<h2>Diagnóstico</h2><ul>{findings or "<li>Sin problemas detectados.</li>"}</ul>
<h2>Cambios realizados</h2>
<ul>{"".join(changes) or "<li>No se ha aplicado ningún cambio.</li>"}</ul>
<p class="muted">Todos los cambios se pueden deshacer desde SafeBoost (Historial), salvo las
limpiezas de archivos.</p>
{f"<h2>Recomendación de hardware</h2><p>{escape(advice)}</p>" if advice else ""}
</body></html>"""


def find_edge() -> Path | None:
    return next((p for p in EDGE_CANDIDATES if p.exists()), None)


def html_to_pdf(html: Path, pdf: Path, runner: Runner, edge: Path | None = None) -> bool:
    """Imprime el HTML a PDF con Edge headless. False si no hay Edge o falla."""
    edge = edge or find_edge()
    if edge is None:
        return False
    try:
        result = runner.run(
            [
                str(edge),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf}",
                html.resolve().as_uri(),
            ],
            timeout=120,
        )
    except CommandError:
        return False
    return result.ok and pdf.exists()
