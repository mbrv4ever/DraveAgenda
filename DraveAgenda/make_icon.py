# Maakt assets/icon.png + assets/icon.ico voor DraveAgenda (eigen ontwerp: kalenderblad met een gouden belletje). Pillow nodig.
import os
from PIL import Image, ImageDraw

HIER = os.path.dirname(os.path.abspath(__file__))
N = 512
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((16, 16, N - 16, N - 16), radius=96, fill=(18, 20, 30, 255), outline=(111, 163, 214, 255), width=10)
# kalenderblad
d.rounded_rectangle((90, 110, 422, 430), radius=34, fill=(240, 240, 246, 255))
d.rounded_rectangle((90, 110, 422, 200), radius=34, fill=(111, 163, 214, 255))
d.rectangle((90, 170, 422, 200), fill=(111, 163, 214, 255))
for x in (170, 342):
    d.rounded_rectangle((x - 14, 78, x + 14, 150), radius=12, fill=(200, 205, 220, 255))
# raster met dagen
for r in range(3):
    for c in range(5):
        x, y = 122 + c * 56, 226 + r * 62
        kleur = (255, 179, 71, 255) if (r, c) == (1, 2) else (170, 176, 196, 255)
        d.rounded_rectangle((x, y, x + 40, y + 40), radius=8, fill=kleur)
# gouden belletje
bx, by = 386, 382
d.ellipse((bx - 70, by - 70, bx + 70, by + 70), fill=(18, 20, 30, 255))
d.pieslice((bx - 48, by - 56, bx + 48, by + 40), 180, 360, fill=(255, 179, 71, 255))
d.rectangle((bx - 48, by - 8, bx + 48, by + 22), fill=(255, 179, 71, 255))
d.rounded_rectangle((bx - 60, by + 16, bx + 60, by + 34), radius=8, fill=(255, 179, 71, 255))
d.ellipse((bx - 13, by + 30, bx + 13, by + 56), fill=(255, 179, 71, 255))
d.ellipse((bx - 9, by - 70, bx + 9, by - 52), fill=(255, 179, 71, 255))
os.makedirs(os.path.join(HIER, "assets"), exist_ok=True)
img.save(os.path.join(HIER, "assets", "icon.png"))
img.save(os.path.join(HIER, "assets", "icon.ico"), format="ICO",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icoon klaar")
