# -*- coding: utf-8 -*-
# DraveAgenda - een grote, duidelijke agenda met herinneringen die ook worden voorgelezen.
# Copyright (C) 2026 Dravenlock (Roger & Claudio). Vrije software onder de GNU GPL v3.0.
"""DraveAgenda: dag-, week- en maandoverzicht met grote letters, herinneringen (venster + geluid + stem),
herhalingen (ook verjaardagen met leeftijd), voorlezen van je dag, .ics in- en uitvoer. Alles blijft op je pc."""
import datetime as dt
import os
import queue
import re
import sys
import threading
import time

from PyQt6.QtCore import Qt, QTimer, QDate, QTime, QLocale
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut, QColor, QFont, QTextCharFormat
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                             QListWidget, QListWidgetItem, QDialog, QFormLayout, QLineEdit, QDateEdit, QTimeEdit,
                             QCheckBox, QComboBox, QPlainTextEdit, QSpinBox, QMessageBox, QFileDialog, QGridLayout,
                             QCalendarWidget, QSystemTrayIcon, QMenu, QStackedWidget)

import model as M
import agenda_sync as S

APP_NAAM = "DraveAgenda"
APP_VERSION = "1.1.1"
BG, PANEL, VAK, ZILVER, GRIJS, ACCENT, GOUD = "#0e0e11", "#16161b", "#121216", "#e6e6ea", "#8a8a94", "#6fa3d6", "#ffb347"
HERINNER = [(-1, "Geen herinnering"), (0, "Op het moment zelf"), (5, "5 minuten van tevoren"), (15, "15 minuten van tevoren"),
            (30, "30 minuten van tevoren"), (60, "1 uur van tevoren"), (120, "2 uur van tevoren"),
            (1440, "1 dag van tevoren (om 9 uur bij hele dag)"), (2880, "2 dagen van tevoren")]


def app_map():
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))


def bron(naam):
    for b in (getattr(sys, "_MEIPASS", None), app_map()):
        if b and os.path.exists(os.path.join(b, naam)):
            return os.path.join(b, naam)
    return os.path.join(app_map(), naam)


def data_map():
    p = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "DraveAgenda")
    os.makedirs(p, exist_ok=True)
    return p


def instellingen():
    import json
    c = dict(letter=20, stem="Cole", snelheid=0.85, voorlezen=True, geluid=True, opstarten=False, verborgen=False)
    try:
        with open(os.path.join(data_map(), "instellingen.json"), encoding="utf-8-sig") as f:
            c.update(json.load(f))
    except Exception:
        pass
    return c


def bewaar_instellingen(c):
    import json
    try:
        with open(os.path.join(data_map(), "instellingen.json"), "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def opstartmap():
    return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")


def zet_opstarten(aan):
    """Snelkoppeling in de Opstarten-map (met --verborgen: dan start hij in het systeemvak)."""
    lnk = os.path.join(opstartmap(), "DraveAgenda.lnk")
    try:
        if aan:
            exe = sys.executable if getattr(sys, "frozen", False) else None
            if not exe:
                return False
            import subprocess
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.Arguments='--verborgen';"
                  "$s.WorkingDirectory='%s';$s.Save()" % (lnk, exe, os.path.dirname(exe)))
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, creationflags=0x08000000)
        elif os.path.exists(lnk):
            os.remove(lnk)
        return True
    except Exception:
        return False


def uitspreekbaar(t):
    """Tijden en afkortingen netjes voor de stem."""
    t = re.sub(r"\b(\d{1,2}):00\b", lambda m: "%s uur" % int(m.group(1)), t)
    t = re.sub(r"\b(\d{1,2}):30\b", lambda m: "half %s" % ((int(m.group(1)) % 12) + 1), t)
    t = re.sub(r"\b(\d{1,2}):15\b", lambda m: "kwart over %s" % (int(m.group(1)) % 12 or 12), t)
    t = re.sub(r"\b(\d{1,2}):45\b", lambda m: "kwart voor %s" % ((int(m.group(1)) % 12) + 1), t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: "%s uur %s" % (int(m.group(1)), int(m.group(2))), t)
    return t.replace("–", " tot ")


# ------------------------------------------------------------------ afspraak bewerken
class Bewerk(QDialog):
    def __init__(self, ouder, a, nieuw=False):
        super().__init__(ouder)
        self.a = dict(a)
        self.setWindowTitle("Nieuwe afspraak" if nieuw else "Afspraak bewerken")
        self.resize(760, 720)
        f = QFormLayout(self)
        f.setVerticalSpacing(12)
        self.titel = QLineEdit(a.get("titel", ""))
        self.titel.setPlaceholderText("Wat is het? Bijvoorbeeld: Kapper, Verjaardag oma...")
        f.addRow("Wat", self.titel)
        self.soort = QComboBox()
        for k, (naam, _) in M.SOORTEN.items():
            self.soort.addItem(naam, k)
        self.soort.setCurrentIndex(list(M.SOORTEN).index(a.get("soort", "afspraak")))
        f.addRow("Soort", self.soort)
        self.datum = QDateEdit(QDate.fromString(a["datum"], "yyyy-MM-dd"))
        self.datum.setCalendarPopup(True)
        self.datum.setDisplayFormat("dddd d MMMM yyyy")
        f.addRow("Datum", self.datum)
        self.hele_dag = QCheckBox("De hele dag (geen tijd)")
        self.hele_dag.setChecked(bool(a.get("hele_dag")))
        f.addRow("", self.hele_dag)
        rij = QHBoxLayout()
        self.begin = QTimeEdit(QTime.fromString(a.get("begin") or "09:00", "HH:mm"))
        self.begin.setDisplayFormat("HH:mm")
        self.eind_aan = QCheckBox("tot")
        self.eind_aan.setChecked(bool(a.get("eind")))
        self.eind = QTimeEdit(QTime.fromString(a.get("eind") or "10:00", "HH:mm"))
        self.eind.setDisplayFormat("HH:mm")
        rij.addWidget(self.begin)
        rij.addWidget(self.eind_aan)
        rij.addWidget(self.eind)
        rij.addStretch(1)
        f.addRow("Tijd", rij)
        self.plaats = QLineEdit(a.get("plaats", ""))
        f.addRow("Waar", self.plaats)
        self.herhaal = QComboBox()
        for k, naam in M.HERHAAL.items():
            self.herhaal.addItem(naam, k)
        self.herhaal.setCurrentIndex(list(M.HERHAAL).index(a.get("herhaal", "geen")))
        f.addRow("Herhalen", self.herhaal)
        self.geboorte = QSpinBox()
        self.geboorte.setRange(0, dt.date.today().year)
        self.geboorte.setSpecialValueText("onbekend")
        self.geboorte.setValue(int(a.get("geboortejaar") or 0))
        self.geb_lbl = QLabel("Geboortejaar")
        f.addRow(self.geb_lbl, self.geboorte)
        self.herinner = QComboBox()
        for m, naam in HERINNER:
            self.herinner.addItem(naam, m)
        waarden = [m for m, _ in HERINNER]
        self.herinner.setCurrentIndex(waarden.index(a.get("herinner", 15)) if a.get("herinner", 15) in waarden else 3)
        f.addRow("Herinnering", self.herinner)
        self.notitie = QPlainTextEdit(a.get("notitie", ""))
        self.notitie.setMaximumHeight(120)
        f.addRow("Notitie", self.notitie)
        knoppen = QHBoxLayout()
        if not nieuw:
            weg = QPushButton("🗑  Verwijderen")
            weg.clicked.connect(lambda: self.done(2))
            knoppen.addWidget(weg)
        knoppen.addStretch(1)
        n = QPushButton("Annuleren")
        n.clicked.connect(self.reject)
        j = QPushButton("Bewaren")
        j.setObjectName("hoofd")
        j.setDefault(True)
        j.clicked.connect(self._ok)
        knoppen.addWidget(n)
        knoppen.addWidget(j)
        f.addRow(knoppen)
        self.hele_dag.toggled.connect(self._ververs)
        self.eind_aan.toggled.connect(self._ververs)
        self.soort.currentIndexChanged.connect(self._soort)
        self._ververs()
        self._soort(first=True)

    def _ververs(self):
        aan = not self.hele_dag.isChecked()
        self.begin.setEnabled(aan)
        self.eind_aan.setEnabled(aan)
        self.eind.setEnabled(aan and self.eind_aan.isChecked())

    def _soort(self, *_, first=False):
        verj = self.soort.currentData() == "verjaardag"
        self.geboorte.setVisible(verj)
        self.geb_lbl.setVisible(verj)
        if verj and not first:
            self.hele_dag.setChecked(True)
            self.herhaal.setCurrentIndex(list(M.HERHAAL).index("jaar"))
            self.herinner.setCurrentIndex([m for m, _ in HERINNER].index(1440))

    def _ok(self):
        if not self.titel.text().strip():
            QMessageBox.information(self, APP_NAAM, "Vul even in wat het is.")
            return
        a = self.a
        a.update(titel=self.titel.text().strip(), soort=self.soort.currentData(),
                 datum=self.datum.date().toString("yyyy-MM-dd"), hele_dag=self.hele_dag.isChecked(),
                 begin="" if self.hele_dag.isChecked() else self.begin.time().toString("HH:mm"),
                 eind=self.eind.time().toString("HH:mm") if (self.eind_aan.isChecked() and not self.hele_dag.isChecked()) else "",
                 plaats=self.plaats.text().strip(), herhaal=self.herhaal.currentData(),
                 geboortejaar=(self.geboorte.value() or None) if self.soort.currentData() == "verjaardag" else None,
                 herinner=self.herinner.currentData(), notitie=self.notitie.toPlainText().strip())
        self.a = a
        self.accept()


# ------------------------------------------------------------------ herinnering (groot venster, bovenop)
class Herinnering(QDialog):
    def __init__(self, ouder, a, dag, start):
        super().__init__(ouder, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setWindowTitle("⏰ Herinnering")
        self.resize(720, 380)
        l = QVBoxLayout(self)
        l.setContentsMargins(36, 30, 36, 30)
        minuten = int(round((start - dt.datetime.now()).total_seconds() / 60))
        wanneer = "vandaag" if a.get("hele_dag") and dag == dt.date.today() else \
            ("morgen" if a.get("hele_dag") and dag == dt.date.today() + dt.timedelta(days=1) else M.wanneer_tekst(minuten))
        self.zin = "%s: %s" % (wanneer[0].upper() + wanneer[1:], M.omschrijving(a, dag, met_tijd=False))
        kop = QLabel("⏰  " + self.zin)
        kop.setWordWrap(True)
        kop.setObjectName("herinnerkop")
        l.addWidget(kop)
        details = []
        if not a.get("hele_dag") and a.get("begin"):
            details.append("Om %s%s" % (a["begin"], (" tot " + a["eind"]) if a.get("eind") else ""))
        details.append(M.lange_datum(dag))
        if a.get("plaats"):
            details.append("📍 " + a["plaats"])
        if a.get("notitie"):
            details.append(a["notitie"])
        d = QLabel("\n".join(details))
        d.setWordWrap(True)
        d.setObjectName("herinnerdetail")
        l.addWidget(d, 1)
        rij = QHBoxLayout()
        self.snooze = QPushButton("⏱  Over 5 minuten nog eens")
        self.snooze.clicked.connect(lambda: self.done(5))
        ok = QPushButton("✓  Oké")
        ok.setObjectName("hoofd")
        ok.clicked.connect(self.accept)
        rij.addWidget(self.snooze)
        rij.addStretch(1)
        rij.addWidget(ok)
        l.addLayout(rij)


# ------------------------------------------------------------------ hoofdvenster
class Agenda(QMainWindow):
    def __init__(self, verborgen=False):
        super().__init__()
        self.cfg = instellingen()
        self.agenda = M.Agenda(data_map())
        self.dag = dt.date.today()
        self.weergave = "dag"
        self.stem = None
        self.laatste_check = dt.datetime.now()
        self.uitgesteld = []      # [(moment, afspraak, dag, start)]
        self.setWindowTitle(APP_NAAM)
        self.setWindowIcon(QIcon(bron(os.path.join("assets", "icon.ico"))))
        self.resize(1400, 900)
        self._bouw()
        self._stijl()
        self._tray()
        self.ververs()
        self.klok = QTimer(self)
        self.klok.timeout.connect(self._tik)
        self.klok.start(15000)
        self._start_kluis()
        self._datum_nu = dt.date.today()
        if not verborgen:
            self.show()

    # ---- de telefoon: de pc is de kluis
    def _start_kluis(self):
        self._tel_veranderd = False
        self._clip_rij = queue.Queue()
        self._clip_bezig = set()
        self.clipmap = os.path.join(data_map(), "leon_telefoon")
        os.makedirs(self.clipmap, exist_ok=True)
        try:      # zinnetjes die 30 dagen niet nodig waren: opruimen
            grens = time.time() - 30 * 86400
            for f in os.listdir(self.clipmap):
                p = os.path.join(self.clipmap, f)
                if os.path.getmtime(p) < grens:
                    os.remove(p)
        except Exception:
            pass
        self.kluis = S.Kluis(self.agenda, clips=self.clipmap, maak_clips=self._maak_clips,
                             bij_wijziging=lambda: setattr(self, "_tel_veranderd", True))
        try:
            self.kluis.start()
        except Exception as e:
            self.kluis = None
            self.statusBar().showMessage("Koppelen met de telefoon lukt niet: %s" % e, 10000)
        threading.Thread(target=self._clip_werker, daemon=True).start()
        self._tel_klok = QTimer(self)
        self._tel_klok.timeout.connect(self._tel_check)
        self._tel_klok.start(1500)

    def _tel_check(self):
        if self._tel_veranderd:
            self._tel_veranderd = False
            self.ververs()
            self.statusBar().showMessage("📱  Bijgewerkt vanaf je telefoon.", 6000)

    def _maak_clips(self, wil):
        for k, tekst in wil.items():
            if k not in self._clip_bezig:
                self._clip_bezig.add(k)
                self._clip_rij.put((k, tekst))

    def _clip_werker(self):
        """Leon spreekt de zinnetjes in voor de telefoon (in de achtergrond)."""
        tts = stijl = None
        sr = 44100
        while True:
            k, tekst = self._clip_rij.get()
            try:
                import numpy as np
                import wave
                if tts is None:
                    if self.stem is None:
                        from stem import Stem
                        self.stem = Stem(self.cfg["stem"], "nl", float(self.cfg["snelheid"]))
                    if not self.stem or not self.stem._laad():
                        continue
                    tts = self.stem._tts
                    namen = list(getattr(tts, "voice_style_names", []) or [])
                    stijl = tts.get_voice_style("Leon" if "Leon" in namen else (namen[0] if namen else None))
                    sr = int(getattr(tts, "sample_rate", 44100) or 44100)
                from stem import spreekbaar, _uitspraak
                with self.stem._lock:
                    wav, _ = tts.synthesize(_uitspraak(spreekbaar(tekst), "nl"), voice_style=stijl, total_steps=8,
                                            speed=0.9, lang="nl")
                x = np.asarray(wav, dtype=np.float32).flatten()
                drempel = 0.01 * (float(np.max(np.abs(x))) or 1)
                waar = np.where(np.abs(x) > drempel)[0]
                if len(waar):
                    x = x[max(0, waar[0] - int(sr * 0.015)): waar[-1] + int(sr * 0.05)]
                x = np.concatenate([np.zeros(int(sr * 0.03), np.float32), x, np.zeros(int(sr * 0.05), np.float32)])
                n = int(len(x) * 22050 / sr)
                x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
                x = x / (float(np.max(np.abs(x))) or 1) * 0.9
                tmp = os.path.join(self.clipmap, k + ".tmp")
                with wave.open(tmp, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(22050)
                    w.writeframes((x * 32767).astype("<i2").tobytes())
                os.replace(tmp, os.path.join(self.clipmap, k + ".wav"))
            except Exception:
                pass
            finally:
                self._clip_bezig.discard(k)

    def telefoon(self):
        d = QDialog(self)
        d.setWindowTitle("Telefoon koppelen")
        d.resize(780, 560)
        l = QVBoxLayout(d)
        l.setContentsMargins(30, 24, 30, 24)
        uitleg = QLabel("Op je telefoon: open DraveAgenda, tik op Menu en dan op Koppelen met de pc. Typ deze code:")
        uitleg.setWordWrap(True)
        l.addWidget(uitleg)
        code = QLabel(self.agenda.code)
        code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code.setStyleSheet("font-size:%dpx; font-weight:800; color:%s; letter-spacing:14px; padding:10px;"
                           % (int(self.cfg["letter"]) * 3, GOUD))
        l.addWidget(code)
        regels = ["Vindt de telefoon de pc niet vanzelf? Typ dan dit adres:   %s" % S.eigen_ip()]
        ts = S.tailscale_ip()
        if ts:
            regels.append("Met Tailscale (thuis én onderweg):   %s" % ts)
        else:
            regels.append("Onderweg ook bijwerken? Zet Tailscale aan op de pc en de telefoon.")
        if self.kluis is None:
            regels.append("Let op: het koppelen werkt nu niet (de pc kon niet luisteren).")
        elif self.kluis.laatst:
            t, n = self.kluis.laatst
            regels.append("Laatst bijgewerkt met je telefoon: %s (%d veranderd)." % (time.strftime("%d-%m %H:%M", time.localtime(t)), n))
        regels.append("De pc moet aan staan met DraveAgenda (mag in het systeemvak). Alles blijft thuis: geen cloud.")
        for r in regels:
            q = QLabel(r)
            q.setWordWrap(True)
            q.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            l.addWidget(q)
        l.addStretch(1)
        ok = QPushButton("Sluiten")
        ok.setObjectName("hoofd")
        ok.clicked.connect(d.accept)
        l.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        d.exec()

    # ---- opbouw
    def _bouw(self):
        w = QWidget()
        self.setCentralWidget(w)
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        balk = QWidget()
        balk.setObjectName("balk")
        b = QHBoxLayout(balk)
        b.setContentsMargins(12, 8, 12, 8)
        for tekst, fn in (("◀", lambda: self.ga(-1)), ("Vandaag", self.vandaag), ("▶", lambda: self.ga(1))):
            k = QPushButton(tekst)
            k.clicked.connect(fn)
            b.addWidget(k)
        self.kop = QLabel()
        self.kop.setObjectName("kop")
        b.addWidget(self.kop, 1)
        self.knoppen = {}
        for code, tekst in (("dag", "Dag"), ("week", "Week"), ("maand", "Maand")):
            k = QPushButton(tekst)
            k.setCheckable(True)
            k.clicked.connect(lambda _=False, c=code: self.zet_weergave(c))
            b.addWidget(k)
            self.knoppen[code] = k
        for tekst, fn, hoofd in (("＋  Nieuw", self.nieuw, True), ("🔊  Wat staat er?", self.lees_voor, False),
                                 ("⋯  Meer", self.meer, False), ("?  Snelgids", self.snelgids, False)):
            k = QPushButton(tekst)
            if hoofd:
                k.setObjectName("hoofd")
            k.clicked.connect(fn)
            b.addWidget(k)
        l.addWidget(balk)
        midden = QHBoxLayout()
        midden.setContentsMargins(12, 12, 12, 12)
        links = QVBoxLayout()
        self.kalender = QCalendarWidget()
        self.kalender.setGridVisible(False)
        self.kalender.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.kalender.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.kalender.clicked.connect(lambda q: self.ga_naar(dt.date(q.year(), q.month(), q.day())))
        self.kalender.currentPageChanged.connect(lambda *_: self._kleur_kalender())
        self.kalender.setFixedWidth(420)
        self.kalender.setLocale(QLocale(QLocale.Language.Dutch, QLocale.Country.Netherlands))
        links.addWidget(self.kalender)
        self.komend_kop = QLabel("Binnenkort")
        self.komend_kop.setObjectName("kopje")
        links.addWidget(self.komend_kop)
        self.komend = QListWidget()
        self.komend.setFixedWidth(420)
        self.komend.setWordWrap(True)
        self.komend.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.komend.itemActivated.connect(self._open_item)
        links.addWidget(self.komend, 1)
        midden.addLayout(links)
        self.stapel = QStackedWidget()
        # dag
        self.daglijst = QListWidget()
        self.daglijst.setObjectName("daglijst")
        self.daglijst.itemActivated.connect(self._open_item)
        self.stapel.addWidget(self.daglijst)
        # week
        weekw = QWidget()
        wl = QHBoxLayout(weekw)
        wl.setContentsMargins(0, 0, 0, 0)
        self.weekkop, self.weeklijst = [], []
        for i in range(7):
            kol = QVBoxLayout()
            kop = QPushButton()
            kop.setObjectName("dagkop")
            kop.clicked.connect(lambda _=False, i=i: self._week_dag(i))
            lijst = QListWidget()
            lijst.setObjectName("weeklijst")
            lijst.setWordWrap(True)
            lijst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            lijst.itemActivated.connect(self._open_item)
            kol.addWidget(kop)
            kol.addWidget(lijst, 1)
            wl.addLayout(kol)
            self.weekkop.append(kop)
            self.weeklijst.append(lijst)
        self.stapel.addWidget(weekw)
        # maand
        maandw = QWidget()
        self.maandgrid = QGridLayout(maandw)
        self.maandgrid.setSpacing(4)
        for i, d in enumerate(["ma", "di", "wo", "do", "vr", "za", "zo"]):
            lbl = QLabel(d)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setObjectName("grijs")
            self.maandgrid.addWidget(lbl, 0, i)
        self.maandvak = []
        for r in range(6):
            for c in range(7):
                k = QPushButton()
                k.setObjectName("maandvak")
                k.setMinimumHeight(96)
                k.clicked.connect(lambda _=False, i=r * 7 + c: self._maand_dag(i))
                self.maandgrid.addWidget(k, r + 1, c)
                self.maandvak.append(k)
        self.maandgrid.setRowStretch(0, 0)
        for r in range(1, 7):
            self.maandgrid.setRowStretch(r, 1)
        self.stapel.addWidget(maandw)
        midden.addWidget(self.stapel, 1)
        l.addLayout(midden, 1)
        self.statusBar().addPermanentWidget(QLabel("v" + APP_VERSION))
        for toets, fn in (("Ctrl+N", self.nieuw), ("Left", lambda: self.ga(-1)), ("Right", lambda: self.ga(1)),
                          ("Home", self.vandaag), ("T", self.vandaag), ("D", lambda: self.zet_weergave("dag")),
                          ("W", lambda: self.zet_weergave("week")), ("M", lambda: self.zet_weergave("maand")),
                          ("F5", self.lees_voor), ("Escape", self.stil), ("Ctrl+=", lambda: self.letter(2)),
                          ("Ctrl++", lambda: self.letter(2)), ("Ctrl+-", lambda: self.letter(-2))):
            QShortcut(QKeySequence(toets), self, activated=fn)

    def _stijl(self):
        L = int(self.cfg["letter"])
        self.setStyleSheet("""
            QMainWindow, QDialog { background:%(BG)s; } QWidget { color:%(Z)s; font-size:%(L)dpx; }
            QWidget#balk { background:%(P)s; border-bottom:1px solid #26262e; }
            QLabel#kop { font-size:%(K)dpx; font-weight:700; color:white; padding-left:14px; }
            QLabel#kopje { font-size:%(L)dpx; font-weight:700; color:%(GO)s; padding-top:8px; }
            QLabel#grijs { color:%(G)s; }
            QLabel#herinnerkop { font-size:%(K)dpx; font-weight:700; color:%(GO)s; }
            QLabel#herinnerdetail { font-size:%(L)dpx; }
            QPushButton { background:#24242c; border:1px solid #3a3a44; border-radius:8px; padding:8px 14px; }
            QPushButton:hover { border-color:%(A)s; } QPushButton:checked { background:#2a3a52; border-color:%(A)s; }
            QPushButton#hoofd { background:%(A)s; color:#0e0e11; font-weight:700; border:0; }
            QPushButton#dagkop { font-weight:700; } QPushButton#maandvak { text-align:left; padding:6px; font-size:%(S)dpx; }
            QListWidget { background:%(V)s; border:1px solid #26262e; border-radius:8px; }
            QListWidget::item { padding:10px 8px; border-bottom:1px solid #1e1e26; }
            QListWidget::item:selected { background:#2a3a52; color:white; }
            QListWidget#daglijst { font-size:%(K2)dpx; } QListWidget#weeklijst { font-size:%(S)dpx; }
            QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QPlainTextEdit { background:%(V)s; border:1px solid #3a3a44;
                border-radius:6px; padding:6px; }
            QCalendarWidget QWidget { alternate-background-color:%(P)s; }
            QCalendarWidget QAbstractItemView { background:%(V)s; selection-background-color:%(A)s; selection-color:#0e0e11; }
            QCalendarWidget QToolButton { color:white; font-weight:700; background:transparent; }
            QStatusBar { background:%(P)s; color:%(G)s; }
            QMenu { background:%(P)s; border:1px solid #3a3a44; } QMenu::item:selected { background:#2a3a52; }
        """ % dict(BG=BG, P=PANEL, V=VAK, Z=ZILVER, G=GRIJS, A=ACCENT, GO=GOUD, L=L, K=L + 8, K2=L + 4, S=max(13, L - 4)))

    def _tray(self):
        self.tray = QSystemTrayIcon(QIcon(bron(os.path.join("assets", "icon.ico"))), self)
        m = QMenu()
        m.addAction("📅  Agenda openen", self.toon)
        m.addAction("🔊  Wat staat er vandaag?", self.lees_voor)
        m.addSeparator()
        m.addAction("Afsluiten", self.afsluiten)
        self.tray.setContextMenu(m)
        self.tray.setToolTip("DraveAgenda - herinneringen staan aan")
        self.tray.activated.connect(lambda r: self.toon() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    # ---- navigeren
    def zet_weergave(self, w):
        self.weergave = w
        self.ververs()

    def ga(self, d):
        stap = {"dag": 1, "week": 7}.get(self.weergave)
        if stap:
            self.dag += dt.timedelta(days=d * stap)
        else:
            j, m = self.dag.year, self.dag.month + d
            j, m = (j + (m - 1) // 12), ((m - 1) % 12) + 1
            self.dag = dt.date(j, m, min(self.dag.day, 28))
        self.ververs()

    def ga_naar(self, d):
        self.dag = d
        self.ververs()

    def vandaag(self):
        self.dag = dt.date.today()
        self.ververs()

    def _week_dag(self, i):
        self.dag = self.dag - dt.timedelta(days=self.dag.weekday()) + dt.timedelta(days=i)
        self.zet_weergave("dag")

    def _maand_dag(self, i):
        d = self._maand_dagen[i]
        self.dag = d
        self.zet_weergave("dag")

    # ---- tonen
    def _item(self, a, d, groot=True):
        lft = M.leeftijd(a, d)
        tekst = M.omschrijving(a, d)
        if a.get("hele_dag"):
            tekst = "Hele dag   " + tekst if groot else tekst
        if groot and a.get("plaats"):
            tekst += "     📍 " + a["plaats"]
        if groot and a.get("herhaal", "geen") != "geen":
            tekst += "     🔁"
        it = QListWidgetItem(("🎂 " if a.get("soort") == "verjaardag" else "") + tekst)
        r, g, b = M.SOORTEN.get(a.get("soort"), M.SOORTEN["overig"])[1]
        it.setForeground(QColor(r, g, b) if a.get("soort") != "afspraak" else QColor(ZILVER))
        it.setData(Qt.ItemDataRole.UserRole, (a["id"], d.isoformat()))
        it.setToolTip(M.lange_datum(d) + ("\n" + a["notitie"] if a.get("notitie") else ""))
        del lft
        return it

    def ververs(self):
        for c, k in self.knoppen.items():
            k.setChecked(c == self.weergave)
        A = self.agenda.afspraken
        vandaag = dt.date.today()
        if self.weergave == "dag":
            self.stapel.setCurrentIndex(0)
            extra = "  ·  vandaag" if self.dag == vandaag else "  ·  morgen" if self.dag == vandaag + dt.timedelta(days=1) else ""
            self.kop.setText(M.lange_datum(self.dag).capitalize() + extra)
            self.daglijst.clear()
            lijst = M.op_dag(A, self.dag)
            for a in lijst:
                self.daglijst.addItem(self._item(a, self.dag))
            if not lijst:
                it = QListWidgetItem("Niets gepland.  Klik op ＋ Nieuw om iets toe te voegen.")
                it.setForeground(QColor(GRIJS))
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                self.daglijst.addItem(it)
        elif self.weergave == "week":
            self.stapel.setCurrentIndex(1)
            ma = self.dag - dt.timedelta(days=self.dag.weekday())
            zo = ma + dt.timedelta(days=6)
            self.kop.setText("Week %d   ·   %d %s – %d %s %d" % (ma.isocalendar()[1], ma.day, M.MAANDEN[ma.month - 1][:3],
                                                                  zo.day, M.MAANDEN[zo.month - 1][:3], zo.year))
            for i in range(7):
                d = ma + dt.timedelta(days=i)
                self.weekkop[i].setText("%s %d%s" % (M.DAGEN[i][:2].capitalize(), d.day, "  ●" if d == vandaag else ""))
                self.weekkop[i].setStyleSheet("color:%s;" % (GOUD if d == vandaag else ZILVER))
                self.weeklijst[i].clear()
                for a in M.op_dag(A, d):
                    self.weeklijst[i].addItem(self._item(a, d, groot=False))
        else:
            self.stapel.setCurrentIndex(2)
            eerste = self.dag.replace(day=1)
            start = eerste - dt.timedelta(days=eerste.weekday())
            self.kop.setText("%s %d" % (M.MAANDEN[self.dag.month - 1].capitalize(), self.dag.year))
            self._maand_dagen = [start + dt.timedelta(days=i) for i in range(42)]
            for i, d in enumerate(self._maand_dagen):
                lijst = M.op_dag(A, d)
                regels = ["%d%s" % (d.day, "  (vandaag)" if d == vandaag else "")] + \
                    [("🎂 " if a.get("soort") == "verjaardag" else "") + M.omschrijving(a, d, met_tijd=False)[:22] for a in lijst[:3]]
                if len(lijst) > 3:
                    regels.append("+ nog %d" % (len(lijst) - 3))
                k = self.maandvak[i]
                k.setText("\n".join(regels))
                k.setStyleSheet("color:%s; %s" % (ZILVER if d.month == self.dag.month else "#55555e",
                                                  "border:2px solid %s;" % GOUD if d == vandaag else ""))
        self.kalender.setSelectedDate(QDate(self.dag.year, self.dag.month, self.dag.day))
        self._kleur_kalender()
        self._vul_komend()

    def _kleur_kalender(self):
        jaar, maand = self.kalender.yearShown(), self.kalender.monthShown()
        leeg = QTextCharFormat()
        vet = QTextCharFormat()
        vet.setFontWeight(QFont.Weight.Bold)
        vet.setForeground(QColor(GOUD))
        d = dt.date(jaar, maand, 1) - dt.timedelta(days=7)
        for _ in range(49):
            self.kalender.setDateTextFormat(QDate(d.year, d.month, d.day), vet if M.op_dag(self.agenda.afspraken, d) else leeg)
            d += dt.timedelta(days=1)

    def _vul_komend(self):
        self.komend.clear()
        d = dt.date.today()
        n = 0
        for i in range(0, 30):
            dag = d + dt.timedelta(days=i)
            for a in M.op_dag(self.agenda.afspraken, dag):
                wanneer = "Vandaag" if i == 0 else "Morgen" if i == 1 else "%s %d %s" % (M.DAGEN[dag.weekday()][:2].capitalize(),
                                                                                       dag.day, M.MAANDEN[dag.month - 1][:3])
                it = self._item(a, dag, groot=False)
                it.setText(wanneer + ":  " + it.text())
                self.komend.addItem(it)
                n += 1
                if n >= 25:
                    return
        if n == 0:
            it = QListWidgetItem("De komende 30 dagen staat er niets.")
            it.setForeground(QColor(GRIJS))
            self.komend.addItem(it)

    # ---- afspraken
    def _zoek(self, id_):
        return next((a for a in self.agenda.afspraken if a["id"] == id_), None)

    def nieuw(self):
        d = Bewerk(self, M.nieuw(datum=self.dag.isoformat()), nieuw=True)
        if d.exec() == 1:
            self.agenda.zet(d.a)
            self.dag = M.datum(d.a["datum"]) if d.a.get("herhaal") == "geen" else self.dag
            self.ververs()
            self.statusBar().showMessage("Bewaard: " + d.a["titel"], 4000)

    def _open_item(self, it):
        data = it.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        a = self._zoek(data[0])
        if not a:
            return
        dag = M.datum(data[1])
        d = Bewerk(self, a)
        r = d.exec()
        if r == 1:
            self.agenda.zet(d.a)
        elif r == 2:
            if a.get("herhaal", "geen") != "geen":
                k = QMessageBox.question(self, "Verwijderen", "'%s' komt vaker terug.\n\nJa = alleen op %s weghalen\n"
                                         "Nee = helemaal weghalen (alle keren)" % (a["titel"], M.lange_datum(dag)),
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                         QMessageBox.StandardButton.Cancel)
                if k == QMessageBox.StandardButton.Yes:
                    self.agenda.weg(a, dag)
                elif k == QMessageBox.StandardButton.No:
                    self.agenda.weg(a)
            elif QMessageBox.question(self, "Verwijderen", "'%s' verwijderen?" % a["titel"]) == QMessageBox.StandardButton.Yes:
                self.agenda.weg(a)
        self.ververs()

    # ---- herinneringen
    def _tik(self):
        nu = dt.datetime.now()
        if dt.date.today() != self._datum_nu:        # middernacht voorbij: overzichten bijwerken
            self._datum_nu = dt.date.today()
            self.ververs()
        lijst = M.herinneringen(self.agenda.afspraken, self.laatste_check, nu)
        self.laatste_check = nu
        for moment, a, dag, start in list(self.uitgesteld):
            if moment <= nu:
                self.uitgesteld.remove((moment, a, dag, start))
                lijst.append((a, dag, start))
        for a, dag, start in lijst:
            self._herinner(a, dag, start)

    def _herinner(self, a, dag, start):
        if self.cfg.get("geluid", True):
            try:
                import winsound
                for f in (880, 1175, 880):
                    winsound.Beep(f, 180)
            except Exception:
                QApplication.beep()
        h = Herinnering(self, a, dag, start)
        if self.cfg.get("voorlezen", True):
            self.zeg("Herinnering. " + h.zin + ".")
        self.tray.showMessage("DraveAgenda", h.zin, QSystemTrayIcon.MessageIcon.Information, 8000)
        h.show()
        h.raise_()
        h.activateWindow()
        r = h.exec()
        self.stil()
        if r == 5:
            self.uitgesteld.append((dt.datetime.now() + dt.timedelta(minutes=5), a, dag, start))

    # ---- voorlezen
    def zeg(self, tekst):
        if self.stem is None:
            try:
                from stem import Stem
                self.stem = Stem(self.cfg["stem"], "nl", float(self.cfg["snelheid"]))
                self.stem.warm_op()
            except Exception as e:
                self.statusBar().showMessage("Voorlezen is niet beschikbaar: %s" % e, 8000)
                self.stem = False
        if self.stem:
            self.stem.snelheid = float(self.cfg["snelheid"])
            for zin in re.split(r"(?<=[.!?])\s+", uitspreekbaar(tekst)):
                if zin.strip():
                    self.stem.zeg(zin.strip())

    def stil(self):
        if self.stem:
            self.stem.stil()

    def lees_voor(self):
        self.stil()
        d = self.dag if self.weergave == "dag" else dt.date.today()
        naam = "Vandaag" if d == dt.date.today() else "Morgen" if d == dt.date.today() + dt.timedelta(days=1) else \
            "Op " + M.lange_datum(d)
        lijst = M.op_dag(self.agenda.afspraken, d)
        if not lijst:
            self.zeg("%s staat er niets in je agenda." % naam)
            return
        delen = ["%s, %s. Je hebt %s." % (naam, M.lange_datum(d), "één ding" if len(lijst) == 1 else "%d dingen" % len(lijst))]
        for a in lijst:
            t = M.omschrijving(a, d, met_tijd=False)
            if a.get("hele_dag") or not a.get("begin"):
                delen.append("De hele dag: %s." % t)
            else:
                delen.append("Om %s: %s%s." % (a["begin"], t, (", in " + a["plaats"]) if a.get("plaats") else ""))
        self.zeg(" ".join(delen))

    # ---- meer
    def meer(self):
        m = QMenu(self)
        a = m.addAction("🔊  Herinneringen voorlezen")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("voorlezen", True)))
        a.toggled.connect(lambda v: self._zet("voorlezen", v))
        a = m.addAction("🔔  Piepje bij een herinnering")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("geluid", True)))
        a.toggled.connect(lambda v: self._zet("geluid", v))
        a = m.addAction("🚀  Starten met Windows (in het systeemvak)")
        a.setCheckable(True)
        a.setChecked(os.path.exists(os.path.join(opstartmap(), "DraveAgenda.lnk")))
        a.toggled.connect(self._opstarten)
        m.addAction("🐢  Voorleessnelheid...", self.kies_snelheid)
        m.addSeparator()
        m.addAction("📱  Telefoon koppelen...", self.telefoon)
        m.addSeparator()
        m.addAction("📥  Agenda inlezen (.ics, bv. uit Google Agenda)...", self.importeer)
        m.addAction("📤  Agenda opslaan als .ics...", self.exporteer)
        m.addAction("🗂  Map met reservekopieën openen", lambda: os.startfile(os.path.join(data_map(), "reservekopie")))
        m.addSeparator()
        m.addAction("Afsluiten (geen herinneringen meer)", self.afsluiten)
        m.exec(self.cursor().pos())

    def _zet(self, k, v):
        self.cfg[k] = v
        bewaar_instellingen(self.cfg)

    def _opstarten(self, aan):
        if zet_opstarten(aan):
            self.statusBar().showMessage("Start nu %s met Windows." % ("mee" if aan else "niet meer"), 5000)
        else:
            QMessageBox.information(self, APP_NAAM, "Dat lukt alleen vanuit DraveAgenda.exe.")

    def kies_snelheid(self):
        from PyQt6.QtWidgets import QInputDialog
        keuzes = ["Heel rustig (70%)", "Rustig (80%)", "Normaal (90%)", "Vlot (100%)"]
        waarden = [0.7, 0.8, 0.9, 1.0]
        nu = min(range(4), key=lambda i: abs(waarden[i] - float(self.cfg["snelheid"])))
        s, ok = QInputDialog.getItem(self, "Voorleessnelheid", "Hoe snel mag ik voorlezen?", keuzes, nu, False)
        if ok:
            self._zet("snelheid", waarden[keuzes.index(s)])
            self.zeg("Zo lees ik voor. Om half tien: koffie.")

    def importeer(self):
        p, _ = QFileDialog.getOpenFileName(self, "Agenda inlezen", os.path.expanduser("~"), "Agenda (*.ics)")
        if not p:
            return
        try:
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                nieuw = M.van_ics(f.read())
        except Exception as e:
            QMessageBox.warning(self, APP_NAAM, "Inlezen lukt niet:\n%s" % e)
            return
        bestaand = {(a["titel"], a["datum"], a.get("begin")) for a in self.agenda.afspraken}
        nieuw = [a for a in nieuw if (a["titel"], a["datum"], a.get("begin")) not in bestaand]
        if QMessageBox.question(self, "Inlezen", "%d nieuwe afspraken gevonden. Toevoegen?" % len(nieuw)) \
                == QMessageBox.StandardButton.Yes:
            self.agenda.voeg_toe(nieuw)
            self.ververs()

    def exporteer(self):
        p, _ = QFileDialog.getSaveFileName(self, "Agenda opslaan", os.path.join(os.path.expanduser("~"), "DraveAgenda.ics"),
                                           "Agenda (*.ics)")
        if p:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(M.naar_ics(self.agenda.afspraken))
            self.statusBar().showMessage("Opgeslagen: " + p, 6000)

    def letter(self, d):
        self.cfg["letter"] = max(14, min(36, int(self.cfg["letter"]) + d))
        bewaar_instellingen(self.cfg)
        self._stijl()

    def snelgids(self):
        p = bron("DraveAgenda-Snelgids.pdf")
        if os.path.exists(p):
            os.startfile(p)
        else:
            QMessageBox.information(self, "Snelgids", "＋ Nieuw = afspraak toevoegen. Dubbelklik = bewerken.")

    def toon(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.ververs()

    def afsluiten(self):
        self.agenda.bewaar()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, ev):
        # sluiten = naar het systeemvak, zodat herinneringen blijven werken
        ev.ignore()
        self.hide()
        if not getattr(self, "_gemeld", False):
            self.tray.showMessage("DraveAgenda", "Ik blijf in het systeemvak voor je herinneringen. "
                                  "Echt stoppen: rechtsklik op mijn pictogram → Afsluiten.",
                                  QSystemTrayIcon.MessageIcon.Information, 6000)
            self._gemeld = True


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAAM)
    app.setQuitOnLastWindowClosed(False)
    QLocale.setDefault(QLocale(QLocale.Language.Dutch, QLocale.Country.Netherlands))   # maanden en dagen in het Nederlands
    w = Agenda(verborgen="--verborgen" in sys.argv)
    try:
        import drave_doneer
        drave_doneer.voeg_toe(w)
    except Exception:
        pass
    try:  # Dravenlock: stille update-check (uit te zetten; Ctrl+Shift+U = met de hand)
        import drave_update
        drave_update.start(w, "DraveAgenda", APP_VERSION)
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
