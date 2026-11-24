# Auditoría de seguridad · SafeBoost 0.11.0 (2026-11-24)

SafeBoost se ejecuta como administrador, así que el riesgo principal no es que alguien ataque el
programa desde fuera, sino que **un programa sin permisos del mismo equipo** use SafeBoost para
hacer algo con permisos de administrador (escalada de privilegios), o que unos datos manipulados
lleguen a una orden del sistema.

Herramientas: pip-audit 2.10.1 (dependencias), bandit 1.9.4 (análisis estático) y revisión manual
de los puntos donde datos externos llegan a PowerShell, a `cmd.exe`, al sistema de archivos o al
Programador de tareas. Semgrep no se pudo usar: el entorno de trabajo bloquea su servidor de reglas.

Todos los hallazgos están corregidos en la **0.11.1**, con tests en `tests/test_v0111.py`.

## Hallazgos

| # | Gravedad | Qué pasaba | Arreglo |
|---|---|---|---|
| 1 | Alta | `ps_quote` solo escapaba la comilla `'`. PowerShell acepta también `‘ ’ ‚ ‛` como comillas simples: un programa de inicio llamado `Spotify’; …` (lo puede crear cualquiera en HKCU\Run) cerraba la cadena e inyectaba órdenes que SafeBoost ejecutaba como administrador al desactivarlo o retrasarlo. | Se duplican las cinco comillas. |
| 2 | Alta | La limpieza (temporales, papelera, caché de navegadores) recorría las carpetas con `rglob`, que entra en *junctions*. Un programa sin permisos podía crear en `%TEMP%` o en `C:\Windows\Temp` una junction hacia `C:\Windows\System32` y SafeBoost borraba allí archivos de más de 24 h. | Recorrido propio con `os.scandir` que nunca entra en enlaces ni junctions, tampoco si la carpeta raíz lo es. |
| 3 | Alta | «Desinstalar» (programas del fabricante) ejecutaba como administrador la orden registrada del programa, también si estaba en HKCU, que cualquier programa del usuario puede escribir con un nombre como «McAfee». | Solo entradas de HKLM (requieren administrador para escribirse). Se muestra la orden exacta antes de ejecutarla y `cmd.exe` se llama con ruta completa. |
| 4 | Alta (portable) | El mantenimiento mensual, la vigilancia y la medición tras reiniciar son tareas elevadas (la última, como SYSTEM). Con la versión portable o desde una carpeta del usuario, apuntaban a un .exe que cualquiera puede sustituir: administrador sin UAC en cada inicio de sesión. | Solo se crean si el .exe está en Program Files o Windows. La medición tras reiniciar ya no usa SYSTEM, sino la cuenta del usuario elevada. |
| 5 | Media | «Actualizar ahora» descargaba el instalador en el `%TEMP%` del usuario; otro programa podía cambiarlo entre la comprobación SHA-256 y su ejecución como administrador. | Se descarga en una carpeta nueva dentro de `C:\Windows\Temp` (creada por el proceso elevado) y la huella se vuelve a comprobar justo antes de ejecutarlo. |
| 6 | Media | Pillow 12.3.0 tenía 8 vulnerabilidades conocidas (CVE-2026-112892, CVE-2026-112393, CVE-2026-96638, CVE-2026-96640, CVE-2026-96778, GHSA-78g4-xqwv-q3g8, CVE-2026-128067, CVE-2026-128066). | Pillow 13.0.0. La CI ejecuta ahora pip-audit en cada cambio. |
| 7 | Media | Los parámetros de un archivo de selección importado (que puede venir de otra persona) llegaban a los handlers sin validar. | `clean_params`: solo parámetros declarados por el tweak y con un valor válido para su tipo (lista cerrada, entero, booleano o letras de unidad). |

## Revisado sin problemas

- Licencias: firma Ed25519 verificada antes de leer los datos; el JSON no se usa en órdenes.
- Informes HTML y PDF: todo el texto variable se escapa.
- Extensiones de navegador e inventario de programas: solo lectura y se muestran como texto.
- Inicio retrasado: la tarea se crea con la cuenta del usuario y permisos limitados (no eleva).
- Avisos de bandit restantes: uso de `subprocess` con listas de argumentos (sin shell), aleatorio no criptográfico en la prueba de rendimiento (correcto) y `0.0.0.0` como valor de comparación de IP en red (no abre ningún puerto).

## Pendiente o fuera del código

- **Firma del código**: sin certificado, la integridad de las actualizaciones depende de la cuenta
  de GitHub (instalador y SHA256SUMS salen de la misma Release). Activar la verificación en dos
  pasos de GitHub es lo más importante; un certificado de firma lo reforzaría.
- **Semgrep**: requiere permitir `semgrep.dev` en la red del entorno de Claude.
- Con el repositorio público: activar Dependabot alerts, secret scanning y CodeQL (gratis).
