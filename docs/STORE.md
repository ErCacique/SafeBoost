# Publicar en Microsoft Store

La compilación de cada versión (`release.yml`) genera `SafeBoost-store-X.Y.Z.msix` como artefacto
del workflow (no como descarga pública). Es un paquete **sin firmar**: Microsoft lo firma al
publicarlo, y así Windows confía en el programa sin certificado de pago.

## Antes de empezar: posibles problemas

- SafeBoost necesita permisos de administrador y declara las capacidades restringidas
  `runFullTrust` y `allowElevation`. La Store las acepta en programas de escritorio, pero hay que
  justificarlas en el envío y la revisión puede pedir explicaciones.
- Las políticas de la Store miran con lupa los «optimizadores». Ayuda que SafeBoost sea
  transparente: simulación previa, todo deshacible, sin promesas exageradas ni publicidad.
- La vigilancia en segundo plano y la tarea mensual usan el Programador de tareas; dentro de un
  paquete MSIX la ruta del ejecutable cambia con cada actualización. Antes de publicar conviene
  probar en una VM que esas dos opciones siguen funcionando tras actualizar el paquete.

## Pasos

1. Crea una cuenta de desarrollador en [Partner Center](https://partner.microsoft.com/dashboard)
   (pago único para particulares).
2. Reserva el nombre «SafeBoost» (Aplicaciones y juegos → Nuevo producto → Aplicación MSIX o PWA).
3. En la app, abre **Administración de producto → Identidad del producto** y copia:
   - `Package/Identity/Name` → `identity_name`
   - `Package/Identity/Publisher` → `publisher` (empieza por `CN=`)
   - `Package/Properties/PublisherDisplayName` → `publisher_display_name`
4. Pon esos valores en `packaging/msix/store.json`, haz commit y publica una versión nueva.
5. Descarga el artefacto `SafeBoost-vX.Y.Z` del workflow de la Release y sube el `.msix` en
   **Paquetes** de tu envío.
6. Rellena la ficha (descripción, capturas de `site/img/`, clasificación por edades, política de
   privacidad: puedes enlazar la sección «Por qué es seguro» de la web) y envía a certificación.

## Probar el paquete en local

Un `.msix` sin firmar no se instala con doble clic. Para probarlo en una VM:

```powershell
# Requiere Modo de desarrollador activado (Configuración → Sistema → Para programadores)
Add-AppxPackage -Register .\msix\AppxManifest.xml   # desde la carpeta descomprimida del paquete
```

También puedes firmarlo con un certificado de prueba (`New-SelfSignedCertificate` + `signtool`)
e instalar ese certificado en «Personas de confianza» de la VM.
