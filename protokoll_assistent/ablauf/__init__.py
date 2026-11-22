"""Ablaufsteuerung ohne Oberflaeche.

Hier entscheidet sich, *was als Naechstes geschieht*: welche Aufnahme als
naechste verarbeitet wird, welcher Weg (lokal oder API) gilt, wann nach der
Transkription die Auswertung startet, was ein Aufnahmegeraet erfahren soll.

Frueher steckte das im Hauptfenster (``gui/main_window.py``) und las seine
Eingaben aus Knoepfen und Auswahllisten. Dieses Paket kennt weder Qt noch
HTTP: Die Programmschnittstelle (``api/``) und der Servermodus benutzen es
gleichermassen, und es laesst sich mit einfachem pytest pruefen.

Regel: Kein Modul hier importiert ``PySide6``, ``fastapi`` oder ``gui``.
"""
