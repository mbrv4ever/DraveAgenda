# -*- coding: utf-8 -*-
"""stem.py - DraveJavis praat met neuvoice (neurale stem, draait op je eigen pc via ONNX).

Zinnen gaan in een wachtrij en worden achter elkaar uitgesproken, zodat de stem al begint
terwijl het antwoord nog binnenkomt. Levert ook een live volume-niveau (0..1) voor de kern.
Ontbreekt neuvoice of de geluidskaart, dan blijft de app gewoon werken (zonder stem).
"""
from __future__ import annotations

import queue
import re
import threading
import time

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None
try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None

FRAME = 0.03
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


try:
    from uitspraak import uitspraak as _uitspraak
except Exception:
    try:
        from .uitspraak import uitspraak as _uitspraak
    except Exception:  # zonder uitspraak.py gewoon de tekst zelf
        def _uitspraak(t, taal="nl"):
            return t


def spreekbaar(t):
    """Maak tekst geschikt om uit te spreken: geen markdown, links of emoji."""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_#`>|~]", "", t)
    t = _EMOJI.sub("", t)
    t = re.sub(r"\bDrave\s?Javis\b", "Dreev Djavis", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class Stem:
    def __init__(self, stem="Leon", taal="nl", snelheid=1.0):
        self.stem = stem
        self.taal = taal
        self.snelheid = snelheid
        self.aan = True
        self.status = "uit"          # uit | laden | klaar | mislukt | geen_neuvoice | geen_geluid
        self.stemmen = []
        self._tts = None
        self._stijl = None
        self._sr = 44100
        self._lock = threading.Lock()
        self._wachtrij = queue.Queue()
        self._env = None
        self._t0 = 0.0
        self._niveau = 0.0
        self.spreekt = False
        self._rekent = False
        self._generatie = 0
        self._speelrij = queue.Queue()
        self.stappen = 6               # minder stappen = sneller (5-10 klinkt prima)
        self.bij_begin = None
        threading.Thread(target=self._werker, daemon=True).start()
        threading.Thread(target=self._speler, daemon=True).start()

    # ------------------------------------------------------------ laden
    def warm_op(self):
        threading.Thread(target=self._laad, daemon=True).start()

    def _laad(self):
        if self._tts is not None or self.status in ("mislukt", "geen_neuvoice", "geen_geluid"):
            return self._tts is not None
        with self._lock:
            if self._tts is not None:
                return True
            if np is None or sd is None:
                self.status = "geen_geluid"
                return False
            try:
                from neuvoice import TTS
            except Exception:
                self.status = "geen_neuvoice"
                return False
            try:
                self.status = "laden"
                tts = TTS(auto_download=True)
                self.stemmen = list(getattr(tts, "voice_style_names", []) or [])
                kies = None
                for n in self.stemmen:
                    if n.lower() == (self.stem or "").lower():
                        kies = n
                if kies is None and self.stemmen:
                    voorkeur = [n for n in ("Leon", "Cole", "Cem") if n in self.stemmen]
                    kies = (voorkeur or self.stemmen)[0]
                self.stem = kies
                self._stijl = tts.get_voice_style(kies) if kies else None
                self._sr = int(getattr(tts, "sample_rate", 44100) or 44100)
                self._tts = tts
                self.status = "klaar"
                return True
            except Exception:
                self.status = "mislukt"
                return False

    def kies_stem(self, naam):
        self.stem = naam
        if self._tts is not None:
            try:
                self._stijl = self._tts.get_voice_style(naam)
            except Exception:
                pass

    # ------------------------------------------------------------ spreken
    # Twee draden: de ene rekent de volgende zin al uit terwijl de andere de huidige afspeelt.
    # Zo zit er geen stilte tussen de zinnen. bij_begin(tekst) wordt aangeroepen zodra een zin
    # hoorbaar begint (handig om de tekst tegelijk met de stem te tonen).
    def zeg(self, tekst, label=None):
        """Zin in de wachtrij zetten (niet-blokkerend). label = wat er bij het begin getoond wordt."""
        schoon = spreekbaar(tekst or "")
        if not self.aan:
            return False
        if not schoon:
            if self.bij_begin and label:
                self.bij_begin(label)
            return False
        self._wachtrij.put((self._generatie, schoon, label if label is not None else tekst))
        return True

    def stil(self):
        """Stop met praten en gooi alles wat nog komt weg."""
        self._generatie += 1
        for q in (self._wachtrij, self._speelrij):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
        try:
            if sd is not None:
                sd.stop()
        except Exception:
            pass
        self.spreekt = False
        self._rekent = False

    def bezig(self):
        return self.spreekt or self._rekent or not self._wachtrij.empty() or not self._speelrij.empty()

    def _werker(self):
        """Rekent zinnen om naar geluid (vooruit werken)."""
        while True:
            gen, tekst, label = self._wachtrij.get()
            if gen != self._generatie:
                continue
            if not self._laad():
                if self.bij_begin and label:
                    self.bij_begin(label)
                continue
            self._rekent = True
            try:
                with self._lock:
                    wav, _dur = self._tts.synthesize(_uitspraak(tekst, self.taal), voice_style=self._stijl, total_steps=self.stappen,
                                                     speed=max(0.6, min(1.8, float(self.snelheid))),
                                                     lang=self.taal)
                data = np.asarray(wav, dtype=np.float32).flatten()
                if gen == self._generatie and len(data) > 10:
                    self._speelrij.put((gen, data, self._omhullende(data), label))
            except Exception:
                if self.bij_begin and label:
                    self.bij_begin(label)
            finally:
                self._rekent = False

    def _speler(self):
        while True:
            gen, data, env, label = self._speelrij.get()
            if gen != self._generatie:
                continue
            try:
                self._env = env
                self._t0 = time.time()
                self.spreekt = True
                if self.bij_begin and label:
                    self.bij_begin(label)
                sd.play(data, self._sr)
                eind = time.time() + len(data) / float(self._sr)
                while time.time() < eind and gen == self._generatie:
                    time.sleep(0.015)
            except Exception:
                pass
            finally:
                self.spreekt = False

    def _omhullende(self, data):
        n = max(1, int(self._sr * FRAME))
        m = len(data) // n
        if m < 1:
            return np.array([0.5], dtype=np.float32)
        env = np.sqrt(np.mean(data[:m * n].reshape(m, n) ** 2, axis=1))
        top = float(env.max()) or 1.0
        return np.clip((env / top) ** 0.7, 0, 1).astype(np.float32)

    def niveau(self):
        doel = 0.0
        if self.spreekt and self._env is not None:
            i = int((time.time() - self._t0) / FRAME)
            if 0 <= i < len(self._env):
                doel = float(self._env[i])
        self._niveau += (doel - self._niveau) * 0.45
        return self._niveau
