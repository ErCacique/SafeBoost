# Licencias de la edición Técnico

La edición Técnico añade la marca del técnico (nombre, contacto y logo) al informe para el
cliente. Todo lo demás es igual en la edición gratuita. La licencia se comprueba sin internet:
SafeTrim lleva la clave pública en `core/license.py` y solo quien tiene la clave privada puede
emitir licencias.

## La clave privada

- Es un archivo de texto con 64 caracteres hexadecimales (32 bytes).
- **No se sube nunca al repositorio** (`.gitignore` ignora `*private*.key`). Guárdala en un gestor
  de contraseñas y en una copia de seguridad cifrada.
- Si la pierdes, no podrás emitir licencias nuevas compatibles con las versiones publicadas.
  Las licencias ya emitidas seguirán funcionando.
- Si alguien la consigue, puede fabricar licencias: genera una nueva (ver más abajo) y publica
  una versión con la clave pública nueva. Las licencias antiguas dejarán de valer en esa versión.

## Emitir una licencia

```powershell
python scripts/license_tool.py issue --key C:\ruta\safetrim-license-private.key `
    --name "Taller Pérez" --email cliente@ejemplo.com --days 365
```

- `--days 0` (o sin `--days`) emite una licencia perpetua.
- El script comprueba que la licencia generada la acepta la clave pública de SafeTrim; si la clave
  privada no corresponde, se detiene sin dar una licencia inútil.
- Envía al cliente la línea que empieza por `ST1.`. Él la pega en **Ajustes → Edición Técnico →
  Introducir licencia**.

Para comprobar una licencia: `python scripts/license_tool.py verify "ST1.…"`.

## Cobrar

Al no depender de un servidor, sirve cualquier forma de cobro: transferencia, Bizum, Ko-fi,
Gumroad o Lemon Squeezy (con «entrega manual» o un producto digital cuyo contenido sea la
licencia). Lleva un registro del `id` que imprime cada licencia por si tienes que identificarla.

## Cambiar de clave

```powershell
python scripts/license_tool.py genkey C:\ruta\clave-nueva-private.key
```

Copia la clave pública que imprime en `PUBLIC_KEY` de `core/license.py`, actualiza el test que la
usa si hace falta y publica una versión nueva.

## Qué no protege

Es una comprobación local: alguien con conocimientos puede modificar el programa para saltársela,
como en casi cualquier software sin servidor. El objetivo es que pagar sea lo cómodo, no impedirlo
a toda costa.
