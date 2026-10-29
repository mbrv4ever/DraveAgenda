# -*- coding: utf-8 -*-
# Copyright (C) 2026 Dravenlock (Roger & Claudio). Licensed under the GNU GPL v3.0 or later - see LICENSE.
"""drave_doneer.py - de knop '♥ Doneren' voor de Drave-apps (donationware).

Gebruik:  import drave_doneer;  drave_doneer.voeg_toe(hoofdvenster)
- QMainWindow: de knop komt rechtsonder in de statusbalk.
- Gewoon QWidget: de knop komt onderaan rechts in het venster.
Gaat er iets mis, dan start de app gewoon zonder knop.
"""
DONEER_URL = "https://paypal.me/roger076"


def _qt():
    """Gebruik dezelfde Qt als de app zelf (PyQt6 of PySide6)."""
    # bewust via importlib: zo ziet PyInstaller/Nuitka geen tweede Qt-pakket (dat breekt de bouw)
    import importlib
    import sys
    naam = "PySide6" if ("PySide6.QtWidgets" in sys.modules and "PyQt6.QtWidgets" not in sys.modules) else "PyQt6"
    return tuple(importlib.import_module("%s.%s" % (naam, m)) for m in ("QtCore", "QtGui", "QtWidgets"))


def knop(parent=None, taal="nl"):
    QtCore, QtGui, QtWidgets = _qt()
    Qt, QUrl, QDesktopServices = QtCore.Qt, QtCore.QUrl, QtGui.QDesktopServices
    b = QtWidgets.QPushButton("♥ Doneren" if taal == "nl" else "♥ Donate", parent)
    b.setObjectName("draveDoneer")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setToolTip("Deze app is gratis. Vind je hem fijn? Een kleine gift via PayPal helpt ons verder."
                 if taal == "nl" else "This app is free. Like it? A small PayPal gift helps us keep going.")
    b.setStyleSheet("QPushButton#draveDoneer{background:#5b2a86;color:#ffffff;border:1px solid #a77bff;"
                    "border-radius:8px;padding:5px 16px;font-weight:bold;font-size:15px;}"
                    "QPushButton#draveDoneer:hover{background:#7a3db3;}")
    b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONEER_URL)))
    return b


def voeg_toe(venster, taal="nl"):
    try:
        if getattr(venster, "_drave_doneer", None) is not None:
            return venster._drave_doneer
        _c, _g, W = _qt()
        QBoxLayout, QGridLayout, QHBoxLayout, QMainWindow = W.QBoxLayout, W.QGridLayout, W.QHBoxLayout, W.QMainWindow
        b = knop(venster, taal)
        if isinstance(venster, QMainWindow):
            venster.statusBar().addPermanentWidget(b)
        else:
            lay = venster.layout()
            rij = QHBoxLayout()
            rij.addStretch(1)
            rij.addWidget(b)
            if isinstance(lay, QBoxLayout):
                lay.addLayout(rij)
            elif isinstance(lay, QGridLayout):
                lay.addLayout(rij, lay.rowCount(), 0, 1, max(1, lay.columnCount()))
            else:
                b.adjustSize()
                b.move(max(0, venster.width() - b.width() - 12), max(0, venster.height() - b.height() - 12))
        venster._drave_doneer = b
        return b
    except Exception:
        return None
