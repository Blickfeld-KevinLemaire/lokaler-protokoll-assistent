"""Die FastAPI-Anwendung: Router, Zugangspruefung, erlaubte Hosts, Oberflaeche als statische Dateien."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from protokoll_assistent.api import (
    routen_auftraege,
    routen_besprechungen,
    routen_chat,
    routen_dateien,
    routen_einstellungen,
    routen_geraete,
    routen_geraete_usb,
    routen_nutzer,
    routen_ollama,
    routen_system,
)
from protokoll_assistent.api.kontext import Dienste
from protokoll_assistent.version import VERSION

# Herkunft des Desktop-Fensters (Tauri 2 unter Windows bzw. andere Plattformen).
TAURI_URSPRUENGE = ("http://tauri.localhost", "https://tauri.localhost", "tauri://localhost")
# Endpunkte ohne Anmeldung. Jeder andere ist ueber die Abhaengigkeit am Router geschuetzt; ein Test prueft das.
OEFFENTLICHE_PFADE = frozenset({"/api/gesundheit", "/api/anmelden", "/api/abmelden"})


def _zugang_pruefen(request: Request) -> str:
    dienste: Dienste = request.app.state.dienste
    return dienste.zugang.pruefen(request)


class Oberflaeche(StaticFiles):
    """Die gebaute Oberflaeche. Unbekannte Pfade ausserhalb von ``/api`` liefern ``index.html`` (die Seite
    entscheidet dann selbst, was sie zeigt)."""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        try:
            antwort = await super().get_response(path, scope)
        except StarletteHTTPException as fehler:
            # Neuere Starlette-Fassungen werfen bei fehlenden Dateien, statt 404 zurueckzugeben.
            if fehler.status_code != 404 or path.startswith("api"):
                raise
            return FileResponse(Path(str(self.directory)) / "index.html")
        if antwort.status_code == 404 and not path.startswith("api"):
            return FileResponse(Path(str(self.directory)) / "index.html")
        return antwort


def app_erstellen(
    dienste: Dienste,
    *,
    erlaubte_hosts: Iterable[str] = ("127.0.0.1", "localhost"),
    cors_urspruenge: Iterable[str] = TAURI_URSPRUENGE,
    oberflaeche: Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="VERMERK",
        version=VERSION,
        description="Programmschnittstelle der Protokoll-Software (Windows-Anwendung und Servermodus).",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.dienste = dienste

    geschuetzt = APIRouter(dependencies=[Depends(_zugang_pruefen)])
    for router in (
        routen_system.geschuetzt,
        routen_auftraege.router,
        routen_besprechungen.router,
        routen_dateien.router,
        routen_einstellungen.router,
        # Literale Pfade (/api/geraete/usb/...) vor denen mit Platzhalter (/api/geraete/{name}).
        routen_geraete_usb.router,
        routen_geraete.router,
        routen_chat.router,
        routen_ollama.router,
        routen_nutzer.router,
    ):
        geschuetzt.include_router(router)
    app.include_router(routen_system.oeffentlich)
    app.include_router(geschuetzt)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unbekannt(rest: str) -> JSONResponse:
        # Ein unbekannter API-Pfad ist ein 404 als JSON -- nicht die Oberflaeche (das verwirrte Clients).
        return JSONResponse(status_code=404, content={"detail": "Unbekannter Endpunkt."})

    hosts = list(erlaubte_hosts)
    if hosts and "*" not in hosts:
        # Schutz gegen DNS-Rebinding: Eine fremde Webseite, deren Name auf 127.0.0.1 zeigt, bekommt keine Antwort.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    urspruenge = list(cors_urspruenge)
    if urspruenge:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=urspruenge,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Vermerk-Anfrage"],
        )
    if oberflaeche is not None and (oberflaeche / "index.html").is_file():
        app.mount("/", Oberflaeche(directory=oberflaeche, html=True), name="oberflaeche")
    return app
