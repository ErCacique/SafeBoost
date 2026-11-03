"""Genera assets/wintune.ico (medidor azul sobre fondo oscuro).

Uso: pip install pillow && python scripts/make_icon.py assets/wintune.ico preview.png
"""

import math
import sys

from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((32, 32, S - 32, S - 32), radius=200, fill=(22, 24, 29, 255))
box = (176, 216, S - 176, S - 136)
d.arc(box, start=150, end=390, fill=(55, 65, 81, 255), width=96)  # pista
d.arc(box, start=150, end=330, fill=(59, 130, 246, 255), width=96)  # progreso
cx, cy = S / 2, (box[1] + box[3]) / 2
ang = math.radians(330 - 360)
r = (box[2] - box[0]) / 2 - 150
tip = (cx + r * math.cos(ang), cy + r * math.sin(ang))
d.line((cx, cy, *tip), fill=(240, 244, 248, 255), width=56)
d.ellipse((cx - 70, cy - 70, cx + 70, cy + 70), fill=(240, 244, 248, 255))
img.save(
    sys.argv[1], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
)
img.resize((256, 256), Image.LANCZOS).save(sys.argv[2])
