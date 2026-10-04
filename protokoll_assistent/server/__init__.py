"""Servermodus: automatische Verarbeitung ohne Oberflaeche (fuer den Container).

Eine Aufnahme landet im Eingangsordner (vom Aufnahmegeraet oder per Freigabe),
wird in Chunks verarbeitet, transkribiert und zusammengefasst; die Ergebnisse
liegen danach im Ausgangsordner. Die eigentliche Arbeit macht dieselbe
Verarbeitungskette wie die Windows-Anwendung (``services/pipeline_service``);
dieses Paket kennt kein Qt und braucht keinen Bildschirm.

* ``einstellungen`` -- liest die Einstellungen aus Umgebungsvariablen.
* ``warteschlange`` -- erkennt fertig geschriebene Dateien im Eingangsordner.
* ``verarbeitung``  -- verarbeitet eine Datei und legt die Ergebnisse ab.
* ``dienst``        -- die Schleife, die das alles zusammenhaelt.
"""
