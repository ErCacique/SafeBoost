"""Informe HTML autocontenido de una sesión (para guardar o enviar)."""

from __future__ import annotations

from html import escape

from core.catalog import Catalog
from core.constants import APP_NAME, APP_VERSION
from core.metrics import MetricsStore, compare, human_bytes
from core.session import Session

STATUS_ES = {
    "applied": "Aplicado",
    "skipped": "Omitido",
    "failed": "Fallido",
    "partial": "Parcial",
    "reverted": "Revertido",
    "irreversible": "Irreversible",
}
STATUS_ORDER = {
    "failed": 0,
    "partial": 1,
    "irreversible": 2,
    "applied": 3,
    "reverted": 3,
    "skipped": 4,
}

_CSS = """
body{font-family:Segoe UI,system-ui,sans-serif;margin:2rem;color:#1f2328;background:#fff}
h1{margin:0 0 .25rem}h2{margin-top:2rem}.muted{color:#59636e}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid #d1d9e0;padding:.4rem .5rem;text-align:left;vertical-align:top}
.s-failed,.s-partial{color:#c62828;font-weight:600}.s-applied,.s-reverted{color:#2e7d32}
ul{margin:.25rem 0;padding-left:1.2rem}code{font-size:12px}
@media (prefers-color-scheme:dark){body{background:#16181d;color:#e6e8eb}
.muted{color:#9aa3b2}th,td{border-color:#2d333b}}
"""


def render_session_html(session: Session, catalog: Catalog, metrics: MetricsStore) -> str:
    kind = "Aplicación" if session.kind == "apply" else f"Reversión de {session.parent_id}"
    summary = ", ".join(f"{STATUS_ES[k]}: {v}" for k, v in session.summary().items() if v)
    env = session.env
    rows = []
    for tid, result in sorted(
        session.results.items(), key=lambda kv: STATUS_ORDER.get(kv[1].status, 9)
    ):
        name = catalog.get(tid).name if tid in catalog else tid
        details = "".join(f"<li>{escape(d)}</li>" for d in result.details)
        rows.append(
            f"<tr><td class='s-{escape(result.status)}'>{escape(STATUS_ES[result.status])}</td>"
            f"<td>{escape(name)}<br><code class='muted'>{escape(tid)}</code></td>"
            f"<td>{escape(result.message)}{f'<ul>{details}</ul>' if details else ''}</td></tr>"
        )
    measures = ""
    before, after = metrics.get(session.id, "before"), metrics.get(session.id, "after")
    if before and after:
        cmp = compare(before, after)
        items = [
            f"RAM libre: {human_bytes(cmp.ram_freed)}",
            f"Procesos: {cmp.process_delta:+d}",
            f"Espacio liberado: {human_bytes(cmp.disk_freed)}",
        ]
        reboot = metrics.get(session.id, "after_reboot")
        if reboot and reboot.boot and before.boot:
            delta = (reboot.boot.boot_ms - before.boot.boot_ms) / 1000
            items.append(
                f"Arranque: {before.boot.boot_ms / 1000:.1f} s → "
                f"{reboot.boot.boot_ms / 1000:.1f} s ({delta:+.1f} s)"
            )
        measures = (
            "<h2>Antes / después</h2><ul>"
            + "".join(f"<li>{escape(i)}</li>" for i in items)
            + "</ul>"
        )
    os_label = str(env.get("os_label", ""))
    edition = str(env.get("edition", "?"))
    restore = session.restore_point or "sin punto de restauración registrado"
    backups = "".join(f"<li><code>{escape(b)}</code></li>" for b in session.backups)
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(APP_NAME)} · sesión {escape(session.id)}</title><style>{_CSS}</style></head>
<body>
<h1>{escape(APP_NAME)} · {escape(kind)}</h1>
<p class="muted">Sesión <code>{escape(session.id)}</code> · {escape(session.created)} ·
SafeBoost {escape(session.app_version)} (informe generado con {escape(APP_VERSION)})</p>
<p class="muted">{escape(os_label)} · edición {escape(edition)} · {escape(restore)}</p>
<p><strong>{escape(summary or "Sin resultados")}</strong></p>
{measures}
<h2>Cambios</h2>
<table><thead><tr><th>Estado</th><th>Tweak</th><th>Detalle</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
{f"<h2>Copias .reg</h2><ul>{backups}</ul>" if backups else ""}
</body></html>
"""
