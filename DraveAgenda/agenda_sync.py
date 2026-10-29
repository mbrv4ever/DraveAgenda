# -*- coding: utf-8 -*-
# DraveAgenda - Copyright (C) 2026 Dravenlock (Roger & Claudio). Vrije software onder de GNU GPL v3.0.
"""agenda_sync.py - uitwisselen tussen de pc (de 'kluis') en de telefoon. Alleen standaard-Python.

De telefoon stuurt zijn afspraken en wat hij weggehaald heeft, de pc voegt samen en stuurt alles terug.
De nieuwste versie wint. De pc maakt ook de Leon-zinnetjes voor de telefoon (de telefoon vraagt welke hij nodig heeft).
Thuis vindt de telefoon de pc vanzelf op de wifi; anders (of onderweg via Tailscale) met het adres van de pc.
"""
import base64
import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import model as M

POORTEN = [37875, 41875, 43875, 45875, 39875]   # http: de eerste die vrij is (Windows houdt soms poorten vast)
ZOEKPOORT = 37876                                # udp: de telefoon zoekt de pc op de wifi
MAX_CLIPS = 4_000_000                            # zoveel bytes aan Leon-zinnetjes per keer


# ------------------------------------------------------------------ wat Leon zegt
def uitspreekbaar(t):
    """Tijden en tekens netjes voor de stem (zelfde als op de pc)."""
    t = re.sub(r"\b(\d{1,2}):00\b", lambda m: "%s uur" % int(m.group(1)), t)
    t = re.sub(r"\b(\d{1,2}):30\b", lambda m: "half %s" % ((int(m.group(1)) % 12) + 1), t)
    t = re.sub(r"\b(\d{1,2}):15\b", lambda m: "kwart over %s" % (int(m.group(1)) % 12 or 12), t)
    t = re.sub(r"\b(\d{1,2}):45\b", lambda m: "kwart voor %s" % ((int(m.group(1)) % 12) + 1), t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: "%s uur %s" % (int(m.group(1)), int(m.group(2))), t)
    return t.replace("–", " tot ")


def zin(a, d):
    """De zin die Leon zegt voor afspraak a op dag d."""
    t = M.omschrijving(a, d, met_tijd=False)
    if a.get("hele_dag") or not a.get("begin"):
        z = "De hele dag: %s." % t
    else:
        z = "Om %s: %s%s." % (a["begin"], t, (", in " + a["plaats"]) if a.get("plaats") else "")
    return uitspreekbaar(z)


def sleutel(tekst):
    return "z" + hashlib.sha1(tekst.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ adressen
def eigen_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def tailscale_ip():
    """Het vaste Tailscale-adres (100.x.x.x) als Tailscale aan staat, anders None."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("100.100.100.100", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip.startswith("100."):
            return ip
    except OSError:
        pass
    return None


# ------------------------------------------------------------------ de kluis (op de pc)
class Kluis:
    """Kleine server op de pc. bij_wijziging() wordt aangeroepen als de telefoon iets veranderd heeft.
    clips = map met Leon-zinnetjes (<sleutel>.wav); maak_clips(dict sleutel->tekst) laat de pc ze maken."""

    def __init__(self, agenda, clips=None, maak_clips=None, bij_wijziging=None):
        self.agenda, self.clips, self.maak_clips, self.bij_wijziging = agenda, clips, maak_clips, bij_wijziging
        self.poort = None
        self.laatst = None           # (tijd, aantal veranderingen)
        self.httpd = None

    def start(self):
        kluis = self
        ag = self.agenda

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _stuur(self, code, obj):
                b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path.startswith("/hallo"):
                    self._stuur(200, dict(app="DraveAgenda"))
                else:
                    self._stuur(404, dict(fout="onbekend"))

            def do_POST(self):
                if not self.path.startswith("/uitwisselen"):
                    return self._stuur(404, dict(fout="onbekend"))
                if self.headers.get("X-Agenda-Code", "") != ag.code:
                    return self._stuur(403, dict(fout="verkeerde code"))
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 30_000_000:
                        return self._stuur(413, dict(fout="te groot"))
                    binnen = json.loads(self.rfile.read(n).decode("utf-8"))
                    veranderd = ag.samenvoegen(binnen.get("afspraken", []), binnen.get("weggehaald", {}))
                    kluis.laatst = (time.time(), veranderd)
                    if veranderd and kluis.bij_wijziging:
                        kluis.bij_wijziging()
                    with ag.lock:
                        terug = dict(afspraken=list(ag.afspraken), weggehaald=dict(ag.weggehaald))
                    terug["clips"] = kluis._clips_voor(binnen.get("wil_clips", {}), set(binnen.get("heb_clips", [])))
                    self._stuur(200, terug)
                except Exception as e:
                    self._stuur(400, dict(fout=str(e)[:200]))

        fout = None
        for p in POORTEN:
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", p), H)
                self.poort = p
                break
            except OSError as e:
                fout = e
        if not self.httpd:
            raise fout
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        threading.Thread(target=self._antwoord_zoekers, daemon=True).start()

    def _clips_voor(self, wil, heb):
        uit, maak, totaal = {}, {}, 0
        if not self.clips or not isinstance(wil, dict):
            return uit
        for k, tekst in wil.items():
            if k in heb or not re.fullmatch(r"z[0-9a-f]{16}", k):
                continue
            p = os.path.join(self.clips, k + ".wav")
            if os.path.exists(p):
                b = open(p, "rb").read()
                if totaal + len(b) <= MAX_CLIPS:
                    uit[k] = base64.b64encode(b).decode("ascii")
                    totaal += len(b)
            elif isinstance(tekst, str) and len(tekst) < 400:
                maak[k] = tekst
        if maak and self.maak_clips:
            self.maak_clips(maak)            # de pc maakt ze in de achtergrond; de volgende keer gaan ze mee
        return uit

    def _antwoord_zoekers(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", ZOEKPOORT))
        except OSError:
            return
        while True:
            try:
                data, adres = s.recvfrom(256)
                if data.startswith(b"DRAVEAGENDA?"):
                    s.sendto(b"DRAVEAGENDA!%d" % self.poort, adres)
            except OSError:
                time.sleep(1)


# ------------------------------------------------------------------ de telefoon
def zoek_kluis(wacht=1.5):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(wacht)
        s.sendto(b"DRAVEAGENDA?", ("255.255.255.255", ZOEKPOORT))
        data, adres = s.recvfrom(256)
        s.close()
        if data.startswith(b"DRAVEAGENDA!"):
            return "http://%s:%s" % (adres[0], int(data[12:]))
    except (OSError, ValueError):
        return None
    return None


def uitwisselen(agenda, adres, code, wil_clips=None, clipmap=None, tijd=8):
    """Stuur alles naar de pc en voeg terug wat die heeft. Leon-zinnetjes die meekomen gaan in clipmap.
    Geeft (ok, tekst) terug."""
    adres = adres.rstrip("/")
    if not adres.startswith("http"):
        adres = "http://" + adres
    if adres.count(":") < 2:                      # geen poort: de gewone poorten proberen
        laatste = (False, "De pc is niet te vinden.")
        for p in POORTEN:
            laatste = uitwisselen(agenda, "%s:%d" % (adres, p), code, wil_clips, clipmap, tijd=min(tijd, 4))
            if laatste[0] or "code" in laatste[1]:
                return laatste
        return laatste
    heb = []
    if clipmap and os.path.isdir(clipmap):
        heb = [f[:-4] for f in os.listdir(clipmap) if f.endswith(".wav")]
    with agenda.lock:
        body = dict(afspraken=list(agenda.afspraken), weggehaald=dict(agenda.weggehaald),
                    wil_clips=wil_clips or {}, heb_clips=heb)
    req = urllib.request.Request(adres + "/uitwisselen", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json", "X-Agenda-Code": code,
                                                         "User-Agent": "DraveAgenda/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=tijd) as r:
            terug = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return False, "De code klopt niet." if e.code == 403 else "Fout %d bij de pc." % e.code
    except Exception:
        return False, "De pc is niet te vinden. Staat DraveAgenda aan op de pc?"
    n = agenda.samenvoegen(terug.get("afspraken", []), terug.get("weggehaald", {}))
    if clipmap:
        os.makedirs(clipmap, exist_ok=True)
        for k, b64 in (terug.get("clips") or {}).items():
            if re.fullmatch(r"z[0-9a-f]{16}", k):
                try:
                    with open(os.path.join(clipmap, k + ".wav"), "wb") as f:
                        f.write(base64.b64decode(b64))
                except Exception:
                    pass
    return True, ("Bijgewerkt: %d veranderd." % n) if n else "Alles is bijgewerkt."
