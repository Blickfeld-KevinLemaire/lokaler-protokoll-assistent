"""Programmschnittstelle (HTTP) fuer die Oberflaeche -- Windows-Fenster und Browser gleichermassen.

Zwei Rollen, ein Programm:

* ``desktop``: lauscht nur auf 127.0.0.1. Zugang mit einem Schluessel, den das
  Desktop-Fenster (Tauri) bei jedem Start neu erzeugt und in der Umgebung
  uebergibt (``VERMERK_API_SCHLUESSEL``), nie auf der Befehlszeile.
* ``server``: lauscht im Netz. Zugang mit Zugangsschluesseln (gespeichert nur
  als SHA-256), angemeldet wird im Browser; danach traegt ein Sitzungs-Cookie.

Die Logik steckt in ``ablauf/``; hier wird nur uebersetzt. Lang laufende
Arbeit laeuft nie in der Ereignisschleife des Servers, sondern in der
Auftragswarteschlange -- Endpunkte, die auf Platte oder Netz zugreifen, sind
deshalb gewoehnliche (synchrone) Funktionen, die FastAPI in Faeden ausfuehrt.
"""
