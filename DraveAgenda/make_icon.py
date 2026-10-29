# Maakt assets/icon.ico (en icon.png) voor DraveAgenda: de Dravenlock-draak met een kalender-badge. Pillow nodig.
# Bron: assets/icon_bron.png (512x512). Een geldige .ico via Pillow, anders weigert PyInstaller.
import os
from PIL import Image

HIER = os.path.dirname(os.path.abspath(__file__))
bron = os.path.join(HIER, "assets", "icon_bron.png")
img = Image.open(bron).convert("RGBA").resize((512, 512), Image.LANCZOS)
img.save(os.path.join(HIER, "assets", "icon.png"))
img.save(os.path.join(HIER, "assets", "icon.ico"), format="ICO",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icoon klaar")
