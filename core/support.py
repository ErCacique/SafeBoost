"""Página de soporte y drivers del modelo exacto del equipo (fabricante, modelo, n.º de serie)."""

from __future__ import annotations

from urllib.parse import quote

# Dell admite el número de serie (service tag) en la URL; el resto, la página de drivers del
# fabricante, donde el usuario introduce el número de serie que SafeBoost le muestra.
VENDORS: tuple[tuple[str, str], ...] = (
    ("dell", "https://www.dell.com/support/home/product-support/servicetag/{serial}/drivers"),
    ("hewlett", "https://support.hp.com/drivers"),
    ("hp", "https://support.hp.com/drivers"),
    ("lenovo", "https://pcsupport.lenovo.com/products/{serial}/downloads"),
    ("asus", "https://www.asus.com/support/download-center/"),
    ("acer", "https://www.acer.com/support/drivers-and-manuals"),
    ("msi", "https://www.msi.com/support/download"),
    (
        "microsoft",
        "https://support.microsoft.com/surface/download-drivers-and-firmware-for-surface",
    ),
    ("samsung", "https://www.samsung.com/support/"),
    ("toshiba", "https://support.dynabook.com/"),
    ("dynabook", "https://support.dynabook.com/"),
    ("huawei", "https://consumer.huawei.com/support/"),
)
# Valores que los fabricantes dejan sin rellenar y no sirven como número de serie.
_PLACEHOLDERS = {"", "to be filled by o.e.m.", "default string", "system serial number", "0"}


def support_url(manufacturer: str, serial: str = "") -> str:
    maker = manufacturer.lower()
    clean = serial.strip()
    usable = clean.lower() not in _PLACEHOLDERS
    for key, template in VENDORS:
        if key in maker:
            if "{serial}" in template:
                if not usable:
                    return template.split("{serial}")[0].rsplit("/", 2)[0] + "/"
                return template.format(serial=quote(clean))
            return template
    return ""
