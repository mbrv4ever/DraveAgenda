# -*- coding: utf-8 -*-
# DraveAgenda voor Android - Copyright (C) 2026 Dravenlock (Roger & Claudio). Vrije software onder de GNU GPL v3.0.
"""agenda_app.py - DraveAgenda op de telefoon: vandaag en de komende dagen, groot en duidelijk.

De pc-app is de 'kluis'. De telefoon wisselt alles uit met de pc (thuis op de wifi, of onderweg via Tailscale).
Herinneringen komen als melding, ook als de app dicht is. Leon leest je dag voor (de pc maakt zijn zinnetjes).
"""
import datetime as dt
import json
import os
import threading
import time

import pygame

import agenda_sync as S
import model as M
import wekker

VERSIE = "0.1"
ANDROID = "ANDROID_PRIVATE" in os.environ or "ANDROID_ARGUMENT" in os.environ
HIER = os.path.dirname(os.path.abspath(__file__))
DAGEN_VOORUIT = 14

ZWART = (10, 8, 16)
PANEEL = (22, 22, 30)
BLAUW = (111, 163, 214)
BLAUW_D = (34, 52, 78)
ZILVER = (230, 230, 236)
GRIJS = (150, 150, 162)
GOUD = (255, 179, 71)
GEEL = (255, 222, 60)
ROOD = (225, 70, 70)
ROOD_D = (122, 36, 36)
GROEN = (90, 210, 140)
WIT = (250, 250, 255)
HERINNER = [(-1, "Geen"), (0, "Op het moment zelf"), (15, "15 minuten ervoor"), (60, "1 uur ervoor"),
            (1440, "1 dag ervoor")]


def data_map():
    basis = (os.environ.get("ANDROID_PRIVATE") or HIER) if ANDROID else HIER
    p = os.path.join(basis, "DraveAgenda-data")
    os.makedirs(p, exist_ok=True)
    return p


class Stem:
    """Leon: vaste zinnetjes (bij de app) en zinnetjes die de pc gemaakt heeft. Ontbreekt er een,
    dan leest de stem van Android die zin voor."""

    def __init__(self, clipmap):
        self.clipmap = clipmap
        self.vast, self.cache = {}, {}
        self.rij, self.kanaal, self.vrij = [], None, 0
        self.tts, self.tts_klaar, self.tts_bezig_tot, self.tts_start = None, False, 0, 0
        try:
            pygame.mixer.init(22050, -16, 1, 1024)
            m = os.path.join(HIER, "stem_agenda")
            for f in os.listdir(m):
                if f.endswith(".wav"):
                    self.vast[f[:-4]] = os.path.join(m, f)
        except Exception:
            pass

    def _clip(self, k):
        if k in self.cache:
            return self.cache[k]
        p = self.vast.get(k) or os.path.join(self.clipmap, k + ".wav")
        try:
            s = pygame.mixer.Sound(p) if os.path.exists(p) else None
        except Exception:
            s = None
        if s is not None:
            self.cache[k] = s
        return s

    def heeft(self, k):
        return k in self.vast or os.path.exists(os.path.join(self.clipmap, k + ".wav"))

    def zeg(self, delen):
        """delen = lijst van sleutels of ('tekst', 'zin voor Android')"""
        self.stil()
        self.rij = list(delen)

    def stil(self):
        self.rij = []
        try:
            if self.kanaal:
                self.kanaal.stop()
            if self.tts:
                self.tts.stop()
        except Exception:
            pass

    def bezig(self):
        return bool(self.rij) or (self.kanaal is not None and self.kanaal.get_busy()) or time.time() < self.tts_bezig_tot

    def _android_zeg(self, tekst):
        try:
            if self.tts is None:
                from jnius import autoclass, PythonJavaClass, java_method

                class Klaar(PythonJavaClass):
                    __javainterfaces__ = ["android/speech/tts/TextToSpeech$OnInitListener"]

                    def __init__(s2, stem):
                        super().__init__()
                        s2.stem = stem

                    @java_method("(I)V")
                    def onInit(s2, status):
                        s2.stem.tts_klaar = status == 0

                act = autoclass("org.kivy.android.PythonActivity").mActivity
                self._klaar = Klaar(self)
                self.tts = autoclass("android.speech.tts.TextToSpeech")(act, self._klaar)
                self._Locale = autoclass("java.util.Locale")
                t0 = time.time()
                while not self.tts_klaar and time.time() - t0 < 3:
                    time.sleep(0.05)
                self.tts.setLanguage(self._Locale("nl", "NL"))
                self.tts.setSpeechRate(0.9)
            self.tts.speak(tekst, 1, None, "drave")
            self.tts_start = time.time()
            self.tts_bezig_tot = time.time() + 1.0 + len(tekst) * 0.1
        except Exception:
            self.tts_bezig_tot = 0

    def update(self):
        nu = time.time()
        if self.kanaal is not None and self.kanaal.get_busy():
            self.vrij = nu + 0.06
            return
        if nu < self.tts_bezig_tot:
            try:      # na een seconde: is Android al klaar met praten?
                if self.tts is not None and nu - self.tts_start > 1.0 and not self.tts.isSpeaking():
                    self.tts_bezig_tot = 0
            except Exception:
                pass
            return
        if self.rij and nu >= self.vrij:
            d = self.rij.pop(0)
            if isinstance(d, tuple):
                self.tts_start = nu
                self.tts_bezig_tot = nu + 1.5
                threading.Thread(target=self._android_zeg, args=(d[1],), daemon=True).start()
            else:
                s = self._clip(d)
                if s is not None:
                    self.kanaal = s.play()
            self.vrij = nu + 0.25


class App:
    def __init__(self):
        pygame.init()
        self.data = data_map()
        self.clipmap = os.path.join(self.data, "leon")
        os.makedirs(self.clipmap, exist_ok=True)
        try:
            grens = time.time() - 30 * 86400
            for f in os.listdir(self.clipmap):
                if os.path.getmtime(os.path.join(self.clipmap, f)) < grens:
                    os.remove(os.path.join(self.clipmap, f))
        except Exception:
            pass
        self.agenda = M.Agenda(self.data)
        self.agenda.code = ""                    # op de telefoon: de code van de pc (staat in instellingen)
        self.inst = {"pc": "", "code": ""}
        try:
            with open(os.path.join(self.data, "instellingen.json"), encoding="utf-8") as f:
                self.inst.update(json.load(f))
        except Exception:
            pass
        if ANDROID:
            info = pygame.display.Info()
            pw, ph = max(1, info.current_w), max(1, info.current_h)
            self.W, self.H = 540, int(540 * max(pw, ph) / min(pw, ph))
            self.venster = pygame.display.set_mode((self.W, self.H), pygame.FULLSCREEN | pygame.SCALED)
        else:
            self.W, self.H = 540, 1040
            self.venster = pygame.display.set_mode((self.W, self.H))
        pygame.display.set_caption("DraveAgenda")
        fb = os.path.join(HIER, "assets", "DejaVuSans-Bold.ttf")
        fr = os.path.join(HIER, "assets", "DejaVuSans.ttf")
        self.f_reus = pygame.font.Font(fb, 64)
        self.f_groot = pygame.font.Font(fb, 38)
        self.f = pygame.font.Font(fb, 28)
        self.f_mid = pygame.font.Font(fb, 24)
        self.f_klein = pygame.font.Font(fr, 22)
        self.f_mini = pygame.font.Font(fr, 18)
        self.klok = pygame.time.Clock()
        self.stem = Stem(self.clipmap)
        self.scherm = "nu"
        self.knoppen, self.sleep, self.scroll, self.max_scroll = [], None, 0, 0
        self.melding = None
        self.bezig = False
        self.vraag = None
        self.keuze = None              # (tekst, [(label, actie)]) bij een keuze met meer knoppen
        self.stop = False
        self.antwoord = None
        self.inv = None                # nieuwe afspraak in de maak
        self.open = None               # (afspraak-id, dag) op het detailscherm
        self.koppel = None
        self.vandaag = dt.date.today()
        wekker.vraag_toestemming()
        self.plan_herinneringen()
        threading.Thread(target=self._uitwisselen, args=(True,), daemon=True).start()

    # ------------------------------------------------------------ hulp
    def bewaar(self):
        try:
            with open(os.path.join(self.data, "instellingen.json"), "w", encoding="utf-8") as f:
                json.dump(self.inst, f)
        except Exception:
            pass

    def meld(self, t, s=3.0):
        self.melding = (t, time.time() + s)

    def tekst(self, t, font, kleur_, x, y, midden=False, rechts=False, max_b=None):
        if max_b:
            while font.size(t)[0] > max_b and len(t) > 3:
                t = t[:-4] + "..."
        img = font.render(t, True, kleur_)
        r = img.get_rect()
        if midden:
            r.midtop = (x, y)
        elif rechts:
            r.topright = (x, y)
        else:
            r.topleft = (x, y)
        self.venster.blit(img, r)
        return r

    def breek(self, tekst, font, breed):
        regels, nu = [], ""
        for w in tekst.split():
            if font.size((nu + " " + w).strip())[0] <= breed:
                nu = (nu + " " + w).strip()
            else:
                if nu:
                    regels.append(nu)
                nu = w
        if nu:
            regels.append(nu)
        return regels or [""]

    def knop(self, rect, label, actie, kleur_=BLAUW_D, rand=BLAUW, font=None, tekstkleur=ZILVER):
        r = pygame.Rect(rect)
        pygame.draw.rect(self.venster, kleur_, r, border_radius=14)
        pygame.draw.rect(self.venster, rand, r, 3, border_radius=14)
        if label:
            f = font or self.f
            while f.size(label)[0] > r.w - 16 and f is not self.f_mini:
                f = {self.f_groot: self.f, self.f: self.f_mid, self.f_mid: self.f_klein}.get(f, self.f_mini)
            img = f.render(label, True, tekstkleur)
            self.venster.blit(img, img.get_rect(center=r.center))
        self.knoppen.append((r, actie))
        return r

    def naar(self, s):
        if s not in ("wat", "waar", "kop_adres"):
            try:
                pygame.key.stop_text_input()
            except Exception:
                pass
        self.scherm = s
        self.scroll = 0

    def kop(self, titel, terug=True, terug_naar="nu"):
        if terug:
            self.knop((16, 16, 140, 72), "Terug", lambda: self.naar(terug_naar), kleur_=PANEEL)
            self.tekst(titel, self.f_groot, ZILVER, 176, 30, max_b=self.W - 190)
        else:
            self.tekst(titel, self.f_groot, ZILVER, 20, 26)

    def dagnaam(self, d):
        if d == self.vandaag:
            return "Vandaag"
        if d == self.vandaag + dt.timedelta(days=1):
            return "Morgen"
        if d == self.vandaag + dt.timedelta(days=2):
            return "Overmorgen"
        return M.DAGEN[d.weekday()].capitalize()

    def korte_datum(self, d):
        return "%s %d %s" % (M.DAGEN[d.weekday()], d.day, M.MAANDEN[d.month - 1])

    # ------------------------------------------------------------ herinneringen en Leon
    def plan_herinneringen(self):
        nu = dt.datetime.now()
        with self.agenda.lock:
            lijst = M.herinneringen(list(self.agenda.afspraken), nu, nu + dt.timedelta(days=DAGEN_VOORUIT))
        uit = []
        for a, dag, start in lijst:
            m = a.get("herinner", -1)
            wanneer = start - dt.timedelta(minutes=m)
            if a.get("hele_dag") or not a.get("begin"):
                tijdtekst = "de hele dag"
            else:
                tijdtekst = "om " + a["begin"] + ((" tot " + a["eind"]) if a.get("eind") else "")
            tekst = "%s, %s%s" % (self.dagnaam(dag) if (dag - self.vandaag).days < 3 else self.korte_datum(dag),
                                  tijdtekst, (" - " + a["plaats"]) if a.get("plaats") else "")
            uit.append((wanneer.timestamp(), "⏰ " + M.omschrijving(a, dag, met_tijd=False), tekst))
        if ANDROID:
            threading.Thread(target=wekker.plan, args=(self.data, uit), daemon=True).start()

    def wil_clips(self):
        """De Leon-zinnetjes die de telefoon de komende dagen nodig heeft (sleutel -> tekst)."""
        wil = {}
        with self.agenda.lock:
            A = list(self.agenda.afspraken)
        for i in range(DAGEN_VOORUIT):
            d = self.vandaag + dt.timedelta(days=i)
            for a in M.op_dag(A, d):
                z = S.zin(a, d)
                wil[S.sleutel(z)] = z
        return wil

    def lees_voor(self, dag=None):
        if self.stem.bezig():
            self.stem.stil()
            return
        d = dag or self.vandaag
        with self.agenda.lock:
            lijst = M.op_dag(list(self.agenda.afspraken), d)
        if not lijst:
            self.stem.zeg(["v_niets"])
            return
        delen = ["v_n%d" % len(lijst) if len(lijst) <= 12 else "v_veel"]
        for a in lijst:
            z = S.zin(a, d)
            k = S.sleutel(z)
            delen.append(k if self.stem.heeft(k) else ("tekst", z))
        self.stem.zeg(delen)

    def lees_een(self, a, d):
        z = S.zin(a, d)
        k = S.sleutel(z)
        self.stem.zeg([k if self.stem.heeft(k) else ("tekst", z)])

    # ------------------------------------------------------------ uitwisselen
    def _uitwisselen(self, stil=False):
        t0 = time.time()
        while self.bezig and time.time() - t0 < 30:
            time.sleep(0.2)
        self.bezig = True
        try:
            code = self.inst.get("code", "")
            if not code:
                if not stil:
                    self.antwoord = (False, "Nog niet gekoppeld. Kies Menu en dan Koppelen met de pc.")
                return
            adressen = [a for a in [self.inst.get("pc")] if a]
            gevonden = S.zoek_kluis(1.5)
            if gevonden and gevonden not in adressen:
                adressen.insert(0, gevonden)
            if not adressen:
                if not stil:
                    self.antwoord = (False, "De pc is niet gevonden. Typ het adres van de pc bij Menu, Koppelen.")
                return
            laatste = (False, "De pc is niet te vinden.")
            for a in adressen:
                ok, t = S.uitwisselen(self.agenda, a, code, self.wil_clips(), self.clipmap)
                laatste = (ok, t)
                if ok:
                    wil = self.wil_clips()
                    if any(not self.stem.heeft(k) for k in wil):     # nieuwe afspraken binnen: de pc vast laten beginnen met Leon
                        S.uitwisselen(self.agenda, a, code, wil, self.clipmap)
                    if a != self.inst.get("pc"):
                        self.inst["pc"] = a
                        self.bewaar()
                    self.inst["laatst"] = time.time()
                    self.bewaar()
                    self.plan_herinneringen()
                    if not stil:
                        self.antwoord = (True, t)
                    return
            if not stil:
                self.antwoord = (False, laatste[1] + " Staat de pc aan, met DraveAgenda, en Tailscale aan?")
        finally:
            self.bezig = False

    def bijwerken(self):
        self.meld("Bijwerken...", 10)
        threading.Thread(target=self._uitwisselen, daemon=True).start()

    def na_wijziging(self):
        self.plan_herinneringen()
        threading.Thread(target=self._uitwisselen, args=(True,), daemon=True).start()

    # ------------------------------------------------------------ schermen: vandaag en de komende dagen
    def scherm_nu(self):
        v, W, H = self.venster, self.W, self.H
        self.tekst("DraveAgenda", self.f_groot, ZILVER, 20, 26)
        self.knop((W - 150, 16, 134, 72), "Menu", lambda: self.naar("menu"), kleur_=PANEEL)
        boven, onder = 104, H - 128
        oud = v.get_clip()
        v.set_clip(pygame.Rect(0, boven, W, onder - boven))
        y = boven + 6 - self.scroll
        with self.agenda.lock:
            A = list(self.agenda.afspraken)
        lege_dagen = 0
        for i in range(DAGEN_VOORUIT):
            d = self.vandaag + dt.timedelta(days=i)
            lijst = M.op_dag(A, d)
            if not lijst and i > 1:
                lege_dagen += 1
                continue
            # dagkop
            naam = self.dagnaam(d)
            kleur_kop = GOUD if i == 0 else ZILVER
            if boven - 60 < y < onder:
                self.tekst(naam, self.f, kleur_kop, 20, y)
                self.tekst("%d %s" % (d.day, M.MAANDEN[d.month - 1]), self.f_klein, GRIJS,
                           24 + self.f.size(naam)[0] + 14, y + 5)
            y += 44
            if not lijst:
                if boven - 60 < y < onder:
                    self.tekst("Niets gepland.", self.f_klein, GRIJS, 24, y)
                y += 44
                continue
            for a in lijst:
                h = 96 if a.get("plaats") else 80
                if y + h > boven - 10 and y < onder:
                    r = pygame.Rect(16, y, W - 32, h)
                    kl = M.SOORTEN.get(a.get("soort"), M.SOORTEN["overig"])[1]
                    self.knop(r, "", lambda a=a, d=d: self.open_detail(a, d), kleur_=PANEEL, rand=(50, 50, 62))
                    pygame.draw.rect(v, kl, (r.x, r.y, 12, r.h), border_top_left_radius=14, border_bottom_left_radius=14)
                    tijd = "Hele dag" if (a.get("hele_dag") or not a.get("begin")) else a["begin"]
                    self.tekst(tijd, self.f_mid, GOUD if a.get("soort") == "verjaardag" else BLAUW, r.x + 26, r.y + 12)
                    tx = r.x + 26 + max(self.f_mid.size("Hele dag")[0], self.f_mid.size("00:00")[0]) + 16
                    self.tekst(M.omschrijving(a, d, met_tijd=False), self.f_mid, ZILVER, tx, r.y + 12, max_b=r.right - tx - 14)
                    onderregel = []
                    if a.get("eind") and not a.get("hele_dag"):
                        onderregel.append("tot " + a["eind"])
                    if a.get("plaats"):
                        onderregel.append(a["plaats"])
                    if onderregel:
                        self.tekst("  ·  ".join(onderregel), self.f_klein, GRIJS, tx, r.y + 52, max_b=r.right - tx - 14)
                    elif a.get("herinner", -1) is not None and a.get("herinner", -1) >= 0:
                        self.tekst("herinnering aan", self.f_mini, GRIJS, tx, r.y + 48)
                y += h + 10
            y += 10
        if lege_dagen == DAGEN_VOORUIT - 2 and boven - 60 < y < onder:
            self.tekst("De komende twee weken verder niets.", self.f_klein, GRIJS, 24, y)
            y += 44
        v.set_clip(oud)
        self.knoppen = [k for k in self.knoppen if k[0].bottom <= onder + 2 and k[0].y >= boven - 4 or k[0].y < 100]
        self.max_scroll = max(0, (y + self.scroll) - onder + 20)
        # onderbalk
        pygame.draw.rect(v, ZWART, (0, onder, W, H - onder))
        bw = (W - 16 * 4) // 3
        self.knop((16, onder + 14, bw, 100), "+ Nieuw", self.start_nieuw, kleur_=BLAUW, rand=GEEL, tekstkleur=ZWART,
                  font=self.f)
        self.knop((32 + bw, onder + 14, bw, 100), "Stop" if self.stem.bezig() else "Lees voor", lambda: self.lees_voor(),
                  font=self.f_mid)
        self.knop((48 + bw * 2, onder + 14, bw, 100), "Bijwerken", self.bijwerken, font=self.f_mid)

    # --- detail
    def open_detail(self, a, d):
        self.open = (a["id"], d)
        self.naar("detail")

    def _zoek(self, id_):
        with self.agenda.lock:
            return next((a for a in self.agenda.afspraken if a["id"] == id_), None)

    def scherm_detail(self):
        W = self.W
        a = self._zoek(self.open[0]) if self.open else None
        if not a:
            self.naar("nu")
            return
        d = self.open[1]
        self.kop("Afspraak")
        y = 112
        for r in self.breek(M.omschrijving(a, d, met_tijd=False), self.f_groot, W - 40)[:3]:
            self.tekst(r, self.f_groot, GOUD if a.get("soort") == "verjaardag" else WIT, 20, y)
            y += 48
        y += 8
        regels = [self.dagnaam(d) + ", " + self.korte_datum(d)]
        if a.get("hele_dag") or not a.get("begin"):
            regels.append("De hele dag")
        else:
            regels.append("Om " + a["begin"] + ((" tot " + a["eind"]) if a.get("eind") else ""))
        if a.get("plaats"):
            regels.append("Waar: " + a["plaats"])
        if a.get("herhaal", "geen") != "geen":
            regels.append(M.HERHAAL.get(a["herhaal"], ""))
        m = a.get("herinner", -1)
        regels.append("Herinnering: " + dict(HERINNER).get(m, "%d minuten ervoor" % m) if m is not None else "Geen herinnering")
        for t in regels:
            for r in self.breek(t, self.f, W - 40):
                self.tekst(r, self.f, ZILVER, 20, y)
                y += 40
            y += 4
        if a.get("notitie"):
            y += 6
            for r in self.breek(a["notitie"], self.f_klein, W - 40)[:8]:
                self.tekst(r, self.f_klein, GRIJS, 20, y)
                y += 30
        H = self.H
        self.knop((16, H - 236, W - 32, 96), "Lees voor", lambda: self.lees_een(a, d))
        self.knop((16, H - 124, W - 32, 96), "Verwijderen", lambda: self.vraag_weg(a, d), kleur_=ROOD_D, rand=ROOD)

    def vraag_weg(self, a, d):
        if a.get("herhaal", "geen") != "geen":
            self.keuze = ("'%s' komt vaker terug. Wat wil je weghalen?" % a.get("titel", ""),
                          [("Alleen deze keer", lambda: self._weg(a, d)), ("Alle keren", lambda: self._weg(a, None)),
                           ("Niets", lambda: None)])
        else:
            self.vraag = ("'%s' verwijderen?" % a.get("titel", ""), lambda: self._weg(a, None))

    def _weg(self, a, d):
        self.agenda.weg(a, d)
        self.meld("Verwijderd.", 2)
        self.naar("nu")
        self.na_wijziging()

    # --- nieuwe afspraak: wat, dag, tijd, waar, herinnering
    def start_nieuw(self):
        self.inv = dict(titel="", datum=self.vandaag, tijd="", hele_dag=False, plaats="", herinner=15)
        self.naar("wat")
        self.typen()

    def typen(self):
        try:
            pygame.key.start_text_input()
            pygame.key.set_text_input_rect(pygame.Rect(16, 150, self.W - 32, 100))
        except Exception:
            pass

    def scherm_wat(self):
        self._tekstveld("Wat is het?", "titel", "Bijvoorbeeld: Kapper, Dokter, Verjaardag...", self._na_wat)

    def scherm_waar(self):
        self._tekstveld("Waar? (mag leeg)", "plaats", "Bijvoorbeeld: Arnhem, bij oma...", lambda: self.naar("herinner"),
                        terug_naar="tijd")

    def _tekstveld(self, titel, veld, uitleg, verder, terug_naar="nu"):
        W = self.W
        self.kop(titel, terug_naar=terug_naar)
        r = pygame.Rect(16, 150, W - 32, 100)
        pygame.draw.rect(self.venster, WIT, r, border_radius=14)
        pygame.draw.rect(self.venster, GEEL, r, 4, border_radius=14)
        t = self.inv[veld]
        knipper = "|" if int(time.time() * 2) % 2 else " "
        if t:
            zicht = t
            while self.f.size(zicht + "|")[0] > r.w - 30 and len(zicht) > 1:
                zicht = zicht[1:]                    # lange tekst: het laatste stuk laten zien
            self.venster.blit(self.f.render(zicht + knipper, True, ZWART), (r.x + 15, r.y + 30))
        else:
            self.tekst(uitleg, self.f_klein, GRIJS, r.x + 15, r.y + 36, max_b=r.w - 30)
        self.knoppen.append((r, self.typen))
        self.knop((16, 270, W - 32, 96), "Verder", verder, kleur_=BLAUW, rand=GEEL, tekstkleur=ZWART, font=self.f)
        self.tekst("Tik op het witte vak als het toetsenbord weg is.", self.f_mini, GRIJS, 20, 380)

    def _na_wat(self):
        if not self.inv["titel"].strip():
            self.meld("Typ eerst wat het is.", 2)
            return
        self.naar("dag")

    def scherm_dag(self):
        W = self.W
        self.kop("Welke dag?", terug_naar="wat")
        d = self.inv["datum"]
        r = pygame.Rect(16, 110, W - 32, 130)
        pygame.draw.rect(self.venster, PANEEL, r, border_radius=16)
        pygame.draw.rect(self.venster, GEEL, r, 4, border_radius=16)
        self.tekst(self.dagnaam(d), self.f_groot, GOUD, r.centerx, r.y + 16, midden=True)
        self.tekst("%d %s %d" % (d.day, M.MAANDEN[d.month - 1], d.year), self.f, ZILVER, r.centerx, r.y + 72, midden=True)

        def zet(n):
            self.inv["datum"] = max(self.vandaag, d + dt.timedelta(days=n))

        def maand(n):
            j, m = d.year, d.month + n
            j, m = j + (m - 1) // 12, (m - 1) % 12 + 1
            self.inv["datum"] = max(self.vandaag, dt.date(j, m, min(d.day, 28 if m == 2 else 30)))
        bw = (W - 48) // 2
        y = 260
        for (l1, f1), (l2, f2) in ((("- 1 dag", lambda: zet(-1)), ("+ 1 dag", lambda: zet(1))),
                                   (("- 1 week", lambda: zet(-7)), ("+ 1 week", lambda: zet(7))),
                                   (("- 1 maand", lambda: maand(-1)), ("+ 1 maand", lambda: maand(1)))):
            self.knop((16, y, bw, 90), l1, f1, kleur_=PANEEL)
            self.knop((32 + bw, y, bw, 90), l2, f2, kleur_=PANEEL)
            y += 104
        self.knop((16, y, bw, 90), "Vandaag", lambda: self.inv.update(datum=self.vandaag), kleur_=PANEEL)
        self.knop((32 + bw, y, bw, 90), "Morgen", lambda: self.inv.update(datum=self.vandaag + dt.timedelta(days=1)),
                  kleur_=PANEEL)
        y += 110
        self.knop((16, y, W - 32, 96), "Verder", lambda: self.naar("tijd"), kleur_=BLAUW, rand=GEEL, tekstkleur=ZWART,
                  font=self.f)

    def scherm_tijd(self):
        W = self.W
        self.kop("Hoe laat?", terug_naar="dag")
        t = self.inv["tijd"]
        r = pygame.Rect(16, 110, W - 32, 110)
        pygame.draw.rect(self.venster, WIT, r, border_radius=14)
        pygame.draw.rect(self.venster, GEEL, r, 4, border_radius=14)
        toon = (t + "____")[:4]
        self.tekst("%s%s:%s%s" % tuple(toon), self.f_reus, ZWART if t else GRIJS, r.centerx, r.y + 18, midden=True)
        self.tekst("Typ 4 cijfers, bijvoorbeeld 1430 voor half drie 's middags.", self.f_mini, GRIJS, 20, 228)
        toetsen = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "<"]
        kw, kh = (W - 56) // 3, 86
        ty = 262
        for i, k in enumerate(toetsen):
            if not k:
                continue
            x = 16 + (i % 3) * (kw + 12)
            self.knop((x, ty + (i // 3) * (kh + 10), kw, kh), "wissen" if k == "<" else k,
                      lambda k=k: self.tijd_toets(k), kleur_=PANEEL, font=self.f_groot if k != "<" else self.f)
        y = ty + 4 * (kh + 10) + 6
        bw = (W - 48) // 2
        self.knop((16, y, bw, 96), "Hele dag", self.hele_dag, kleur_=PANEEL, rand=GOUD)
        self.knop((32 + bw, y, bw, 96), "Verder", self.na_tijd, kleur_=BLAUW, rand=GEEL, tekstkleur=ZWART, font=self.f)

    def tijd_toets(self, k):
        t = self.inv["tijd"]
        if k == "<":
            self.inv["tijd"] = t[:-1]
        elif len(t) < 4:
            self.inv["tijd"] = t + k

    def hele_dag(self):
        self.inv["hele_dag"] = True
        self.inv["tijd"] = ""
        self.naar("waar")
        self.typen()

    def na_tijd(self):
        t = self.inv["tijd"]
        if len(t) == 3:
            t = "0" + t
        if len(t) != 4 or int(t[:2]) > 23 or int(t[2:]) > 59:
            self.meld("Typ de tijd met 4 cijfers, bijvoorbeeld 0930 of 1430. Of kies Hele dag.", 5)
            return
        self.inv["tijd"] = t
        self.inv["hele_dag"] = False
        self.naar("waar")
        self.typen()

    def scherm_herinner(self):
        W = self.W
        self.kop("Herinnering?", terug_naar="waar")
        y = 116
        for m, naam in HERINNER:
            if m == 1440 and self.inv["hele_dag"]:
                naam = "1 dag ervoor (om 9 uur)"
            if m == 0 and self.inv["hele_dag"]:
                naam = "Op de dag zelf (om 9 uur)"
            gekozen = self.inv["herinner"] == m
            self.knop((16, y, W - 32, 88), naam, lambda m=m: self.inv.update(herinner=m),
                      kleur_=BLAUW_D if gekozen else PANEEL, rand=GEEL if gekozen else (60, 60, 72))
            y += 100
        y += 10
        self.knop((16, y, W - 32, 100), "Bewaren", self.bewaar_nieuw, kleur_=BLAUW, rand=GEEL, tekstkleur=ZWART,
                  font=self.f_groot)

    def bewaar_nieuw(self):
        i = self.inv
        t = i["tijd"]
        a = M.nieuw(titel=i["titel"].strip(), datum=i["datum"].isoformat(), hele_dag=i["hele_dag"],
                    begin="" if i["hele_dag"] else "%s:%s" % (t[:2], t[2:]), plaats=i["plaats"].strip(),
                    herinner=i["herinner"])
        self.agenda.zet(a)
        self.inv = None
        self.naar("nu")
        self.meld("Bewaard: " + a["titel"], 2.5)
        self.na_wijziging()

    # --- menu en koppelen
    def scherm_menu(self):
        W = self.W
        self.kop("Menu")
        y = 120
        for label, actie in (("Koppelen met de pc", self.start_koppel),
                             ("Nu bijwerken", self.bijwerken),
                             ("Leon testen", lambda: self.stem.zeg(["test"])),
                             ("Herinnering testen", self.test_herinnering)):
            self.knop((16, y, W - 32, 88), label, actie, kleur_=PANEEL)
            y += 100
        y += 10
        info = ["Gekoppeld met de pc: " + ("ja" if self.inst.get("code") else "nee")]
        if self.inst.get("pc"):
            info.append("Pc: " + self.inst["pc"].replace("http://", ""))
        if self.inst.get("laatst"):
            info.append("Laatst bijgewerkt: " + time.strftime("%d-%m %H:%M", time.localtime(self.inst["laatst"])))
        with self.agenda.lock:
            info.append("Afspraken op deze telefoon: %d" % len(self.agenda.afspraken))
        info.append("Alles blijft op je eigen telefoon en pc.")
        info.append("DraveAgenda %s  -  Dravenlock (Roger & Claudio)" % VERSIE)
        for t in info:
            for r in self.breek(t, self.f_klein, W - 40):
                self.tekst(r, self.f_klein, BLAUW if t.startswith("DraveAgenda") else GRIJS, 20, y)
                y += 30
            y += 6

    def test_herinnering(self):
        if wekker.test("⏰ Test van DraveAgenda", "Zo ziet een herinnering eruit."):
            self.meld("Kijk bovenaan je scherm: daar staat de test.", 4)
        else:
            self.meld("Herinneringen werken alleen op de telefoon.", 3)

    def start_koppel(self):
        self.koppel = dict(stap="code", tekst="")
        self.naar("koppel")

    def scherm_koppel(self):
        v, W = self.venster, self.W
        kp = self.koppel
        self.kop("Koppelen" if kp["stap"] == "code" else "Adres van de pc")
        uitleg = ("Open DraveAgenda op de pc, kies Meer en dan Telefoon koppelen. Typ de code van 4 cijfers die daar staat."
                  if kp["stap"] == "code" else
                  "De pc is niet vanzelf gevonden. Typ nu het ADRES (met puntjes) dat op de pc bij Telefoon koppelen staat. "
                  "Met Tailscale begint het met 100.")
        y = 104
        for r in self.breek(uitleg, self.f_klein, W - 40):
            self.tekst(r, self.f_klein, GRIJS, 20, y)
            y += 28
        veld = pygame.Rect(16, y + 10, W - 32, 100)
        pygame.draw.rect(v, WIT, veld, border_radius=14)
        pygame.draw.rect(v, GEEL, veld, 4, border_radius=14)
        self.tekst(kp["tekst"] or " ", self.f_groot, ZWART, veld.centerx, veld.y + 26, midden=True)
        toetsen = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "." if kp["stap"] == "adres" else "", "0", "<"]
        kw, kh = (W - 56) // 3, 90
        ty = veld.bottom + 18
        for i, t in enumerate(toetsen):
            if not t:
                continue
            x = 16 + (i % 3) * (kw + 12)
            self.knop((x, ty + (i // 3) * (kh + 10), kw, kh), "wissen" if t == "<" else t,
                      lambda t=t: self.koppel_toets(t), kleur_=PANEEL, font=self.f_groot if t != "<" else self.f)
        y = ty + 4 * (kh + 10) + 6
        self.knop((16, y, W - 32, 96), "Koppelen" if kp["stap"] == "code" else "Klaar", self.koppel_verder,
                  kleur_=BLAUW, rand=GEEL, tekstkleur=ZWART, font=self.f_groot)
        if kp["stap"] == "code" and self.inst.get("code"):
            self.knop((16, y + 112, W - 32, 80), "Adres van de pc typen", lambda: self.koppel.update(stap="adres", tekst=""),
                      kleur_=PANEEL, font=self.f_mid)

    def koppel_toets(self, t):
        kp = self.koppel
        if t == "<":
            kp["tekst"] = kp["tekst"][:-1]
        elif len(kp["tekst"]) < (4 if kp["stap"] == "code" else 15):
            kp["tekst"] += t

    def koppel_verder(self):
        kp = self.koppel
        if kp["stap"] == "code":
            if len(kp["tekst"]) != 4:
                self.meld("De code heeft 4 cijfers.", 2)
                return
            self.inst["code"] = kp["tekst"]
            self.bewaar()
            self.meld("Zoeken naar de pc...", 12)
            threading.Thread(target=self._koppel_test, daemon=True).start()
        else:
            if kp["tekst"].count(".") != 3:
                self.meld("Een adres heeft 3 puntjes, zoals 100.64.12.34", 6)
                return
            self.inst["pc"] = "http://%s" % kp["tekst"]
            self.bewaar()
            self.bijwerken()
            self.naar("nu")

    def _koppel_test(self):
        t0 = time.time()
        while self.bezig and time.time() - t0 < 30:
            time.sleep(0.2)
        self.antwoord = None
        self._uitwisselen()
        ok = self.antwoord and self.antwoord[0]
        if ok:
            self.naar("nu")
        elif self.antwoord and "code" in self.antwoord[1]:
            self.koppel = dict(stap="code", tekst="")
        else:
            self.antwoord = (False, "De pc is niet vanzelf gevonden. Typ nu het adres van de pc.")
            self.koppel = dict(stap="adres", tekst="")

    # ------------------------------------------------------------ tekenen en de lus
    def teken(self):
        self.knoppen = []
        self.venster.fill(ZWART)
        getattr(self, "scherm_" + self.scherm)()
        tekst = None
        if self.vraag or self.keuze:
            vr = self.vraag[0] if self.vraag else self.keuze[0]
            knoppen = [("Ja", self.vraag_ja), ("Nee", lambda: setattr(self, "vraag", None))] if self.vraag else \
                [(l, (lambda f=f: (setattr(self, "keuze", None), f()))) for l, f in self.keuze[1]]
            hoogte = 150 + (100 if self.vraag else 100 * len(knoppen))
            r = pygame.Rect(24, self.H // 2 - hoogte // 2, self.W - 48, hoogte)
            pygame.draw.rect(self.venster, PANEEL, r, border_radius=18)
            pygame.draw.rect(self.venster, GEEL, r, 4, border_radius=18)
            for i, regel in enumerate(self.breek(vr, self.f, r.w - 40)[:3]):
                self.tekst(regel, self.f, ZILVER, r.centerx, r.y + 22 + i * 38, midden=True)
            self.knoppen = []
            if self.vraag:
                bw = (r.w - 60) // 2
                self.knop((r.x + 20, r.bottom - 106, bw, 86), "Ja", self.vraag_ja, kleur_=ROOD_D, rand=ROOD)
                self.knop((r.x + 40 + bw, r.bottom - 106, bw, 86), "Nee", lambda: setattr(self, "vraag", None),
                          kleur_=PANEEL)
            else:
                y = r.y + 140
                for l, f in knoppen:
                    self.knop((r.x + 20, y, r.w - 40, 86), l, f, kleur_=ROOD_D if l == "Alle keren" else PANEEL,
                              rand=ROOD if l == "Alle keren" else BLAUW)
                    y += 100
        elif self.melding and time.time() < self.melding[1]:
            tekst = self.melding[0]
        if tekst:
            regels = self.breek(tekst, self.f_mid, self.W - 90)[:4]
            hh = 60 + len(regels) * 34
            r = pygame.Rect(30, self.H // 2 - hh // 2, self.W - 60, hh)
            pygame.draw.rect(self.venster, PANEEL, r, border_radius=16)
            pygame.draw.rect(self.venster, GEEL, r, 4, border_radius=16)
            for i, regel in enumerate(regels):
                self.tekst(regel, self.f_mid, ZILVER, r.centerx, r.y + 30 + i * 34, midden=True)
        pygame.display.flip()

    def vraag_ja(self):
        actie = self.vraag[1]
        self.vraag = None
        actie()

    def klik(self, pos):
        if self.melding and time.time() < self.melding[1] and not (self.vraag or self.keuze):
            if self.melding[1] - time.time() > 2:       # tik = melding weg (behalve bij 'bezig')
                self.melding = None
                return
        for r, actie in reversed(self.knoppen):
            if r.collidepoint(pos):
                actie()
                return

    def terug(self):
        if self.vraag or self.keuze:
            self.vraag = self.keuze = None
        elif self.scherm == "nu":
            self.stop = True
        else:
            vorige = {"dag": "wat", "tijd": "dag", "waar": "tijd", "herinner": "waar"}.get(self.scherm, "nu")
            if vorige == "nu":
                self.inv = None
            self.naar(vorige)
            if vorige in ("wat", "waar"):
                self.typen()

    def run(self):
        while not self.stop:
            self.klok.tick(30)
            if dt.date.today() != self.vandaag:
                self.vandaag = dt.date.today()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.stop = True
                elif e.type == pygame.TEXTINPUT and self.scherm in ("wat", "waar"):
                    veld = "titel" if self.scherm == "wat" else "plaats"
                    if len(self.inv[veld]) < 80:
                        self.inv[veld] += e.text
                elif e.type == pygame.KEYDOWN:
                    if e.key in (pygame.K_AC_BACK, pygame.K_ESCAPE):
                        self.terug()
                    elif e.key == pygame.K_BACKSPACE and self.scherm in ("wat", "waar"):
                        veld = "titel" if self.scherm == "wat" else "plaats"
                        self.inv[veld] = self.inv[veld][:-1]
                    elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.scherm in ("wat", "waar"):
                        self._na_wat() if self.scherm == "wat" else self.naar("herinner")
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.sleep = (e.pos, self.scroll, False)
                elif e.type == pygame.MOUSEMOTION and self.sleep and e.buttons[0]:
                    (sx, sy), s0, _ = self.sleep
                    if abs(e.pos[1] - sy) > 20 and self.scherm == "nu":
                        self.scroll = max(0, min(self.max_scroll, s0 - (e.pos[1] - sy)))
                        self.sleep = ((sx, sy), s0, True)
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                    if self.sleep and not self.sleep[2]:
                        self.klik(e.pos)
                    self.sleep = None
                elif e.type == getattr(pygame, "APP_WILLENTERFOREGROUND", -1) or \
                        e.type == getattr(pygame, "WINDOWFOCUSGAINED", -2):
                    if time.time() - self.inst.get("laatst", 0) > 60:
                        threading.Thread(target=self._uitwisselen, args=(True,), daemon=True).start()
            if self.antwoord:
                ok, t = self.antwoord
                self.antwoord = None
                self.meld(t, 3.5 if ok else 15)
            self.stem.update()
            self.teken()
        pygame.quit()


def main():
    App().run()


if __name__ == "__main__":
    main()
