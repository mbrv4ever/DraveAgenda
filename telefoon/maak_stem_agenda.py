# -*- coding: utf-8 -*-
# DraveAgenda - Copyright (C) 2026 Dravenlock (Roger & Claudio).
"""maak_stem_agenda.py - Leon spreekt de vaste zinnetjes in voor DraveAgenda op de telefoon. Draai: py -3.10 maak_stem_agenda.py"""
import os
import wave

import numpy as np

GETAL = ["", "één", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien", "elf", "twaalf"]
ZINNEN = {"v_niets": "Vandaag staat er niets in je agenda.",
          "v_n1": "Vandaag heb je één ding.",
          "v_veel": "Vandaag heb je veel dingen.",
          "test": "Hallo, ik ben Leon. Ik lees je agenda voor."}
for i in range(2, 13):
    ZINNEN["v_n%d" % i] = "Vandaag heb je %s dingen." % GETAL[i]


def main():
    from neuvoice import TTS
    uit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stem_agenda")
    os.makedirs(uit, exist_ok=True)
    tts = TTS(auto_download=True)
    namen = list(getattr(tts, "voice_style_names", []) or [])
    stijl = tts.get_voice_style("Leon" if "Leon" in namen else namen[0])
    sr = int(getattr(tts, "sample_rate", 44100) or 44100)
    for sleutel, tekst in ZINNEN.items():
        wav, _ = tts.synthesize(tekst, voice_style=stijl, total_steps=10, speed=0.9, lang="nl")
        x = np.asarray(wav, dtype=np.float32).flatten()
        drempel = 0.01 * (np.max(np.abs(x)) or 1)
        waar = np.where(np.abs(x) > drempel)[0]
        if len(waar):
            x = x[max(0, waar[0] - int(sr * 0.015)): waar[-1] + int(sr * 0.05)]
        x = np.concatenate([np.zeros(int(sr * 0.03), np.float32), x, np.zeros(int(sr * 0.05), np.float32)])
        n = int(len(x) * 22050 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
        x = x / (np.max(np.abs(x)) or 1) * 0.9
        with wave.open(os.path.join(uit, sleutel + ".wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes((x * 32767).astype("<i2").tobytes())
    print("KLAAR", len(ZINNEN))


if __name__ == "__main__":
    main()
