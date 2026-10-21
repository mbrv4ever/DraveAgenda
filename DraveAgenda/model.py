# -*- coding: utf-8 -*-
# DraveAgenda - de kern: afspraken bewaren, herhalingen uitrekenen, herinneringen, .ics in en uit.
# Copyright (C) 2026 Dravenlock (Roger & Claudio). Vrije software onder de GNU GPL v3.0.
import calendar
import datetime as dt
import json
import os
import re
import shutil
import uuid

HERHAAL = {"geen": "Niet herhalen", "dag": "Elke dag", "week": "Elke week", "maand": "Elke maand", "jaar": "Elk jaar"}
SOORTEN = {"afspraak": ("Afspraak", (111, 163, 214)), "verjaardag": ("Verjaardag", (255, 179, 71)),
           "familie": ("Familie", (240, 120, 170)), "werk": ("Werk", (120, 200, 140)),
           "huishouden": ("Huishouden", (170, 150, 230)), "vrije_tijd": ("Vrije tijd", (90, 210, 210)),
           "overig": ("Overig", (180, 180, 190))}
DAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"]


def datum(s):
    return dt.date.fromisoformat(s) if isinstance(s, str) else s


def tijd(s):
    if not s:
        return None
    u, m = s.split(":")
    return dt.time(int(u), int(m))


def nieuw(**kw):
    a = dict(id=uuid.uuid4().hex[:12], titel="", datum=dt.date.today().isoformat(), hele_dag=False, begin="09:00",
             eind="", plaats="", notitie="", herhaal="geen", tot="", herinner=15, soort="afspraak", geboortejaar=None,
             uitzonderingen=[])
    a.update(kw)
    return a


def lange_datum(d):
    d = datum(d)
    return "%s %d %s %d" % (DAGEN[d.weekday()], d.day, MAANDEN[d.month - 1], d.year)


# ------------------------------------------------------------------ herhalingen
def _dag_in_maand(jaar, maand, dag):
    laatste = calendar.monthrange(jaar, maand)[1]
    return dt.date(jaar, maand, min(dag, laatste)) if dag <= laatste or (maand == 2 and dag == 29) else None


def valt_op(a, d):
    """Valt afspraak a op datum d?"""
    start = datum(a["datum"])
    d = datum(d)
    if d < start:
        return False
    if a.get("tot") and d > datum(a["tot"]):
        return False
    if d.isoformat() in a.get("uitzonderingen", []):
        return False
    h = a.get("herhaal", "geen")
    if h == "geen":
        return d == start
    if h == "dag":
        return True
    if h == "week":
        return (d - start).days % 7 == 0
    if h == "maand":
        if start.day <= calendar.monthrange(d.year, d.month)[1]:
            return d.day == start.day
        return False            # bv. de 31e in een maand van 30 dagen: die maand niet
    if h == "jaar":
        if start.month == 2 and start.day == 29 and not calendar.isleap(d.year):
            return d.month == 2 and d.day == 28   # 29 februari valt in een gewoon jaar op 28 februari
        return d.month == start.month and d.day == start.day
    return False


def op_dag(afspraken, d):
    d = datum(d)
    lijst = [a for a in afspraken if valt_op(a, d)]
    return sorted(lijst, key=lambda a: (not a.get("hele_dag"), a.get("begin") or "00:00", a.get("titel", "").lower()))


def leeftijd(a, d):
    """Bij een verjaardag met geboortejaar: hoe oud wordt iemand op datum d?"""
    if a.get("soort") == "verjaardag" and a.get("geboortejaar"):
        try:
            return datum(d).year - int(a["geboortejaar"])
        except Exception:
            return None
    return None


def omschrijving(a, d=None, met_tijd=True):
    t = a.get("titel") or "(geen titel)"
    if d is not None:
        lft = leeftijd(a, d)
        if lft:
            t += " (wordt %d)" % lft
    if met_tijd and not a.get("hele_dag") and a.get("begin"):
        t = a["begin"] + ("–" + a["eind"] if a.get("eind") else "") + "   " + t
    return t


def start_moment(a, d):
    d = datum(d)
    if a.get("hele_dag") or not a.get("begin"):
        return dt.datetime.combine(d, dt.time(9, 0))      # hele dag: herinnering om 9 uur 's ochtends
    return dt.datetime.combine(d, tijd(a["begin"]))


def herinneringen(afspraken, van, tot):
    """Alle herinneringen met een moment in (van, tot]. Geeft [(afspraak, datum, startmoment)]."""
    uit = []
    for dag in {van.date() - dt.timedelta(days=1), van.date(), tot.date(), tot.date() + dt.timedelta(days=1),
                tot.date() + dt.timedelta(days=2)}:
        for a in afspraken:
            m = a.get("herinner", -1)
            if m is None or m < 0 or not valt_op(a, dag):
                continue
            s = start_moment(a, dag)
            wanneer = s - dt.timedelta(minutes=m)
            if van < wanneer <= tot:
                uit.append((a, dag, s))
    return sorted(uit, key=lambda x: x[2])


def wanneer_tekst(minuten):
    if minuten <= 0:
        return "nu"
    if minuten < 60:
        return "over %d minuten" % minuten
    if minuten < 120:
        return "over een uur" if minuten == 60 else "over %d minuten" % minuten
    if minuten < 1440:
        return "over %d uur" % (minuten // 60)
    return "morgen" if minuten < 2880 else "over %d dagen" % (minuten // 1440)


# ------------------------------------------------------------------ opslag
class Agenda:
    def __init__(self, map_):
        self.map = map_
        os.makedirs(map_, exist_ok=True)
        self.pad = os.path.join(map_, "agenda.json")
        self.afspraken = []
        try:
            with open(self.pad, encoding="utf-8-sig") as f:
                self.afspraken = json.load(f).get("afspraken", [])
        except Exception:
            pass
        self.reservekopie()

    def bewaar(self):
        tmp = self.pad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(versie=1, afspraken=self.afspraken), f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.pad)

    def reservekopie(self):
        """Elke dag een kopie, de laatste 30 dagen blijven bewaard."""
        if not os.path.exists(self.pad):
            return
        try:
            rk = os.path.join(self.map, "reservekopie")
            os.makedirs(rk, exist_ok=True)
            doel = os.path.join(rk, "agenda_%s.json" % dt.date.today().isoformat())
            if not os.path.exists(doel):
                shutil.copy2(self.pad, doel)
            for f in sorted(os.listdir(rk))[:-30]:
                os.remove(os.path.join(rk, f))
        except Exception:
            pass

    def zet(self, a):
        for i, b in enumerate(self.afspraken):
            if b["id"] == a["id"]:
                self.afspraken[i] = a
                break
        else:
            self.afspraken.append(a)
        self.bewaar()

    def weg(self, a, alleen_datum=None):
        if alleen_datum and a.get("herhaal", "geen") != "geen":
            a.setdefault("uitzonderingen", []).append(datum(alleen_datum).isoformat())
            self.zet(a)
        else:
            self.afspraken = [b for b in self.afspraken if b["id"] != a["id"]]
            self.bewaar()


# ------------------------------------------------------------------ .ics (iCalendar), om uit te wisselen met andere agenda's
FREQ = {"dag": "DAILY", "week": "WEEKLY", "maand": "MONTHLY", "jaar": "YEARLY"}
FREQ_TERUG = {v: k for k, v in FREQ.items()}


def _ics_tekst(s):
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_terug(s):
    return s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def naar_ics(afspraken):
    r = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Dravenlock//DraveAgenda//NL", "CALSCALE:GREGORIAN"]
    nu = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for a in afspraken:
        d = datum(a["datum"])
        r += ["BEGIN:VEVENT", "UID:%s@dravenlock.nl" % a["id"], "DTSTAMP:" + nu, "SUMMARY:" + _ics_tekst(a.get("titel"))]
        if a.get("hele_dag") or not a.get("begin"):
            r += ["DTSTART;VALUE=DATE:" + d.strftime("%Y%m%d"),
                  "DTEND;VALUE=DATE:" + (d + dt.timedelta(days=1)).strftime("%Y%m%d")]
        else:
            b = dt.datetime.combine(d, tijd(a["begin"]))
            e = dt.datetime.combine(d, tijd(a["eind"])) if a.get("eind") else b + dt.timedelta(hours=1)
            r += ["DTSTART:" + b.strftime("%Y%m%dT%H%M%S"), "DTEND:" + e.strftime("%Y%m%dT%H%M%S")]
        if a.get("plaats"):
            r.append("LOCATION:" + _ics_tekst(a["plaats"]))
        if a.get("notitie"):
            r.append("DESCRIPTION:" + _ics_tekst(a["notitie"]))
        if a.get("herhaal", "geen") in FREQ:
            regel = "RRULE:FREQ=" + FREQ[a["herhaal"]]
            if a.get("tot"):
                regel += ";UNTIL=" + datum(a["tot"]).strftime("%Y%m%d")
            r.append(regel)
        for u in a.get("uitzonderingen", []):
            r.append("EXDATE;VALUE=DATE:" + datum(u).strftime("%Y%m%d"))
        if a.get("herinner", -1) is not None and a.get("herinner", -1) >= 0:
            r += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + _ics_tekst(a.get("titel")),
                  "TRIGGER:-PT%dM" % a["herinner"], "END:VALARM"]
        r.append("END:VEVENT")
    r.append("END:VCALENDAR")
    return "\r\n".join(r) + "\r\n"


def van_ics(tekst):
    """Leest afspraken uit een .ics-bestand (de gewone onderdelen; ingewikkelde herhalingen worden 'geen')."""
    regels = []
    for r in tekst.replace("\r\n", "\n").split("\n"):
        if r.startswith((" ", "\t")) and regels:
            regels[-1] += r[1:]
        else:
            regels.append(r)
    uit, cur, in_alarm = [], None, False
    for r in regels:
        if r == "BEGIN:VEVENT":
            cur = nieuw(herinner=-1)
        elif r == "END:VEVENT" and cur is not None:
            if cur.get("titel") or cur.get("datum"):
                uit.append(cur)
            cur = None
        elif cur is None:
            continue
        elif r == "BEGIN:VALARM":
            in_alarm = True
        elif r == "END:VALARM":
            in_alarm = False
        elif ":" in r:
            sleutel, waarde = r.split(":", 1)
            naam = sleutel.split(";")[0].upper()
            if in_alarm:
                if naam == "TRIGGER":
                    m = re.match(r"-P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", waarde)
                    if m:
                        d_, h_, m_ = (int(x or 0) for x in m.groups())
                        cur["herinner"] = d_ * 1440 + h_ * 60 + m_
                continue
            if naam == "SUMMARY":
                cur["titel"] = _ics_terug(waarde)
            elif naam == "LOCATION":
                cur["plaats"] = _ics_terug(waarde)
            elif naam == "DESCRIPTION":
                cur["notitie"] = _ics_terug(waarde)
            elif naam in ("DTSTART", "DTEND") and waarde.strip().endswith("Z") and "T" in waarde:
                # UTC-tijd (bv. van Google): omzetten naar de tijd op deze pc
                u = dt.datetime.strptime(waarde.strip()[:15], "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc).astimezone()
                if naam == "DTSTART":
                    cur["datum"], cur["begin"], cur["hele_dag"] = u.date().isoformat(), u.strftime("%H:%M"), False
                else:
                    cur["eind"] = u.strftime("%H:%M")
            elif naam == "DTSTART":
                w = waarde.strip().rstrip("Z")
                cur["datum"] = "%s-%s-%s" % (w[0:4], w[4:6], w[6:8])
                if "T" in w and len(w) >= 13:
                    cur["begin"] = "%s:%s" % (w[9:11], w[11:13])
                    cur["hele_dag"] = False
                else:
                    cur["hele_dag"] = True
                    cur["begin"] = ""
            elif naam == "DTEND":
                w = waarde.strip().rstrip("Z")
                if "T" in w and len(w) >= 13:
                    cur["eind"] = "%s:%s" % (w[9:11], w[11:13])
            elif naam == "RRULE":
                delen = dict(x.split("=", 1) for x in waarde.split(";") if "=" in x)
                cur["herhaal"] = FREQ_TERUG.get(delen.get("FREQ", ""), "geen")
                if "INTERVAL" in delen and delen["INTERVAL"] != "1":
                    cur["herhaal"] = "geen"
                if "UNTIL" in delen:
                    u = delen["UNTIL"]
                    cur["tot"] = "%s-%s-%s" % (u[0:4], u[4:6], u[6:8])
            elif naam == "EXDATE":
                for w in waarde.split(","):
                    w = w.strip()
                    cur["uitzonderingen"].append("%s-%s-%s" % (w[0:4], w[4:6], w[6:8]))
    return uit
