"""Einstieg fuer den gebauten Dienst (``vermerk_dienst.spec`` -> ``vermerk-dienst.exe``).

Das Desktop-Fenster (``oberflaeche/src-tauri``) startet ihn mit
``--rolle desktop --port 0 --port-datei <datei>``; siehe ``protokoll_assistent/api/__main__.py``.
"""

from protokoll_assistent.api.__main__ import main

raise SystemExit(main())
