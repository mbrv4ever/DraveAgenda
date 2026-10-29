# -*- coding: utf-8 -*-
# DraveAgenda - Copyright (C) 2026 Dravenlock (Roger & Claudio).
"""wekker.py - zet de herinneringen klaar in Android (AlarmManager), zodat ze ook komen als de app dicht is."""
import os

MAX = 60            # zoveel herinneringen tegelijk klaarzetten (de komende 2 weken)


def _ctx():
    from jnius import autoclass, cast
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    return cast("android.content.Context", act), autoclass("nl.dravenlock.draveagenda.Wekker")


def vraag_toestemming():
    """Android 13 en nieuwer: toestemming voor meldingen vragen."""
    try:
        from jnius import autoclass
        if autoclass("android.os.Build$VERSION").SDK_INT >= 33:
            from android.permissions import request_permissions
            request_permissions(["android.permission.POST_NOTIFICATIONS"])
    except Exception:
        pass


def plan(data_map, lijst):
    """lijst = [(wanneer_in_seconden, titel, tekst)]. Oude herinneringen gaan eraf, deze worden klaargezet.
    Geeft het aantal klaargezette terug (of -1 als het niet op Android is)."""
    lijst = sorted(lijst)[:MAX]
    pad = os.path.join(data_map, "wekkers.txt")
    oud = 0
    try:
        oud = sum(1 for _ in open(pad, encoding="utf-8"))
    except Exception:
        pass
    try:
        with open(pad, "w", encoding="utf-8") as f:
            for t, titel, tekst in lijst:
                f.write("%d\t%s\t%s\n" % (int(t * 1000), titel.replace("\t", " ").replace("\n", " "),
                                          tekst.replace("\t", " ").replace("\n", " ")))
    except Exception:
        pass
    try:
        ctx, W = _ctx()
    except Exception:
        return -1
    for nr in range(max(oud, MAX)):
        try:
            W.weg(ctx, nr)
        except Exception:
            pass
    for nr, (t, titel, tekst) in enumerate(lijst):
        try:
            W.zet(ctx, nr, int(t * 1000), titel, tekst)
        except Exception:
            pass
    return len(lijst)


def test(titel, tekst):
    try:
        ctx, W = _ctx()
        W.toon(ctx, 99, titel, tekst)
        return True
    except Exception:
        return False
