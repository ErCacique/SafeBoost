# Distribución del ejecutable

> Precios y condiciones de terceros son orientativos y cambian. Verifícalos antes de contratar.

## El problema de partida

El repo es privado, así que los assets de sus Releases **solo los descargan usuarios con
acceso al repo**. Un enlace a `github.com/ErCacique/WinOpt/releases/...` devuelve 404 a
cualquier otra persona.

## Opciones para entregar `WinTune.exe` a terceros

### a) Invitar colaboradores al repo privado

*Settings → Collaborators → Add people*.

| Pros | Contras |
|---|---|
| Cero infraestructura y gratis | En un repo **personal**, un colaborador tiene acceso de **escritura**: no existe un rol de solo lectura (eso requiere una organización) |
| Descargan el Release con su cuenta | Ven todo el código y el historial |
| Revocas el acceso cuando quieras | Cada destinatario necesita una cuenta de GitHub |

Adecuado solo para una o dos personas de confianza (p. ej. alguien que te ayuda a probar).

### b) Repo público aparte solo con Releases y README (recomendada)

Por ejemplo `ErCacique/WinTune-releases`, con un README (qué es, requisitos, cómo verificar el
SHA256, aviso de SmartScreen) y solo Releases. El código sigue en el repo privado.

| Pros | Contras |
|---|---|
| Enlace público estable, sin cuenta para descargar | El binario es público: cualquiera puede descargarlo y analizarlo |
| El código y el historial siguen privados | Hay dos repos que mantener sincronizados (automatizable) |
| Notas de versión y SHA256 visibles junto a la descarga | Requiere un token con permiso de escritura sobre el repo público, guardado como secreto |
| Gratis; en repos públicos el secret scanning también es gratis | Los issues públicos pueden llenarse de peticiones (se pueden desactivar) |

Para automatizarlo, añade al final de `release.yml`, con un *fine-grained PAT* limitado a
`Contents: Read and write` **solo** sobre el repo público y guardado como secreto
`RELEASES_TOKEN`:

```yaml
      - name: Publicar en el repo público de releases
        if: startsWith(github.ref, 'refs/tags/')
        env:
          GH_TOKEN: ${{ secrets.RELEASES_TOKEN }}
        run: >
          gh release create "${{ github.ref_name }}" dist/WinTune.exe dist/WinTune.exe.sha256
          --repo ErCacique/WinTune-releases --title "WinTune ${{ github.ref_name }}"
          --notes "SHA256: ${{ steps.hash.outputs.sha256 }}"
```

### c) Otro almacenamiento (Cloudflare R2, S3, OneDrive/Google Drive, web propia)

| Pros | Contras |
|---|---|
| Control fino: enlaces con caducidad o protegidos | Configuración y, según el servicio, coste de almacenamiento o tráfico |
| No depende de GitHub | Los enlaces compartidos se filtran con facilidad |
| | Drive/OneDrive muestran avisos de "no se puede analizar" con ejecutables, y a veces los bloquean |
| | El SHA256 hay que publicarlo aparte, en un canal distinto del binario |

## Antivirus y SmartScreen

### Por qué saltan los falsos positivos

- **PyInstaller `--onefile`**: el bootloader es el mismo que usan muchos programas maliciosos
  empaquetados con PyInstaller, y el ejecutable se autoextrae en `%TEMP%` al arrancar.
- **Lo que hace WinTune**: pide administrador, modifica el registro y los servicios, y
  desinstala paquetes. Es justo el comportamiento que vigilan las heurísticas.
- **Sin firma y con poca difusión**: un binario nuevo, sin firmar y con pocas descargas no
  tiene reputación.

### Qué ya se hace en este repo

- **UPX desactivado** (`upx=False`): los binarios comprimidos disparan más detecciones.
- **Recurso de versión completo** (`packaging/version_info.txt`): empresa, producto y versión.
- **Sin descargas ni ejecución de código remoto en tiempo de ejecución.** La única excepción
  es `winget` al revertir apps, y siempre a petición del usuario.
- **SHA256 publicado siempre** junto al `.exe` en el cuerpo del Release y en `WinTune.exe.sha256`.

### Qué puedes hacer además

1. **Antes de publicar**, analiza el `.exe` en VirusTotal. Ten en cuenta que VirusTotal
   comparte las muestras con los fabricantes de antivirus.
2. **Si Microsoft Defender lo marca**, envíalo como falso positivo en
   <https://www.microsoft.com/wdsi/filesubmission> (*Software developer*). Suele resolverse en
   pocos días, y por versión.
3. **Si las detecciones persisten**:
   - **`--onedir`** en lugar de `--onefile` reduce detecciones, a cambio de distribuir una
     carpeta (zip).
   - **Compilar el bootloader de PyInstaller desde el código fuente** cambia su firma binaria.
     Es más trabajo y hay que repetirlo en cada actualización de PyInstaller.

### SmartScreen ("Windows protegió su PC")

Aparece en archivos descargados de internet (marca *Mark of the Web*) sin firma o sin
reputación. El usuario puede pulsar **Más información → Ejecutar de todas formas**, o bien
*Propiedades → Desbloquear* antes de abrir el archivo. La reputación se acumula con descargas
del mismo binario firmado; sin firma, cada versión empieza de cero.

Instrucciones para el destinatario (copiar en el README público):

```powershell
# 1. Verificar que el archivo es el publicado
(Get-FileHash .\WinTune.exe -Algorithm SHA256).Hash.ToLower()
# 2. Comparar con el SHA256 del Release. Si coincide y SmartScreen avisa:
#    Más información → Ejecutar de todas formas
```

## Firma de código

No se asume ningún certificado. Opciones, de más a menos recomendable para este caso:

| Opción | Coste orientativo | Requisitos y notas |
|---|---|---|
| **Azure Artifact Signing** (antes *Trusted Signing*) | ~10 USD/mes (plan Basic) | Validación de identidad por Microsoft. La disponibilidad para particulares ha estado limitada por país (inicialmente EE. UU. y Canadá): comprueba si cumples. Se integra con GitHub Actions, sin hardware y con certificados de vida corta gestionados por Microsoft. Construye reputación de SmartScreen. |
| **Certificado OV** (Sectigo, DigiCert, SSL.com, Certum…) | ~200-500 USD/año | Desde 2023 la clave privada debe estar en hardware (token o HSM). Para firmar en CI necesitas un servicio de firma en la nube de la CA (coste extra) o Azure Key Vault con HSM. Validación de persona física posible. La validez máxima de los certificados se está acortando (CA/Browser Forum): confirma la duración con la CA. |
| **Certificado EV** | ~300-700 USD/año | Desde 2024 ya **no** concede reputación inmediata en SmartScreen: se comporta como un OV a esos efectos. Solo compensa para drivers de kernel. No recomendado aquí. |
| **Certum Open Source / SignPath Foundation** | Bajo o gratuito | **Solo para proyectos de código abierto**: aplicable únicamente si el repo se hace público. |
| **Autofirmado** | 0 | No sirve para terceros: SmartScreen y los antivirus lo tratan como sin firmar, salvo que cada usuario instale tu certificado raíz, cosa que no debe pedirse. |

**Recomendación:**

- **Mientras solo lo uses tú** o un círculo pequeño: sin firma, con el SHA256 publicado y la
  opción (b).
- **Si empiezas a distribuirlo con regularidad**: Azure Artifact Signing si eres elegible;
  si no, un OV con firma en la nube de la CA.

Cuando tengas certificado, se añade un paso `signtool sign /fd sha256 /tr <TSA> /td sha256` (o
la acción oficial del servicio) entre "PyInstaller" y "SHA256" en `release.yml`. El hash debe
calcularse **después** de firmar.
