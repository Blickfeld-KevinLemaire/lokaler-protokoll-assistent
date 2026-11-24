"""PDF und OpenDocument ohne Qt -- aus dem Dokumentmodell des Exportdienstes.

Frueher schrieb Qt beides aus dem HTML-Text (``gui/dokument_qt.py``). Die
Programmschnittstelle und der Servermodus haben kein Qt; deshalb:

* PDF mit ``reportlab`` (BSD-Lizenz). Schrift: Arial bzw. DejaVu Sans, wenn
  vorhanden (volle Unicode-Abdeckung), sonst die eingebaute Helvetica --
  Zeichen ausserhalb von deren Zeichensatz werden dann ersetzt statt den
  Export scheitern zu lassen.
* OpenDocument (.odt) als ZIP mit den vier Pflichtdateien, ohne weitere
  Bibliothek.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from protokoll_assistent.services.dokument_export_service import (
    ABSATZ,
    LISTE,
    SEITENUMBRUCH,
    UEBERSCHRIFT,
    Dokument,
    ExportFehler,
)

SCHRIFT_KANDIDATEN = (
    (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
)


def schreibe(format_id: str, dokument: Dokument, ziel: Path) -> None:
    if format_id == "pdf":
        schreibe_pdf(dokument, ziel)
    elif format_id == "odt":
        schreibe_odt(dokument, ziel)
    else:
        raise ExportFehler(f"Unbekanntes Format: {format_id}")


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def _schriften() -> tuple[str, str, bool]:
    """(normal, fett, unicode) -- registriert eine TrueType-Schrift, wenn eine da ist."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for normal, fett in SCHRIFT_KANDIDATEN:
        if normal.is_file() and fett.is_file():
            try:
                pdfmetrics.registerFont(TTFont("VermerkNormal", str(normal)))
                pdfmetrics.registerFont(TTFont("VermerkFett", str(fett)))
            except Exception:  # noqa: S112 -- kaputte Schriftdatei: naechsten Kandidaten versuchen
                continue
            return "VermerkNormal", "VermerkFett", True
    return "Helvetica", "Helvetica-Bold", False


def _fuer_pdf(text: str, unicode: bool) -> str:
    """Text fuer einen reportlab-Absatz: XML-sicher, ohne Zeichen, die die Schrift nicht kennt."""
    if not unicode:
        text = text.encode("cp1252", errors="replace").decode("cp1252")
    return escape(text)


def schreibe_pdf(dokument: Dokument, ziel: Path) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as fehler:
        raise ExportFehler("Für PDF-Dateien wird das Paket reportlab benötigt.") from fehler

    normal, fett, unicode = _schriften()
    stil_text = ParagraphStyle("text", fontName=normal, fontSize=10.5, leading=14.5, spaceAfter=5)
    stil_kopf = ParagraphStyle("kopf", parent=stil_text, textColor="#555555", spaceAfter=1)
    stil_titel = ParagraphStyle("titel", fontName=fett, fontSize=18, leading=22, spaceAfter=8)
    stil_h2 = ParagraphStyle("h2", fontName=fett, fontSize=13.5, leading=17, spaceBefore=10, spaceAfter=4)
    stil_h3 = ParagraphStyle("h3", fontName=fett, fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=3)

    def t(text: str) -> str:
        return _fuer_pdf(text, unicode)

    teile: list[object] = [Paragraph(t(dokument.titel), stil_titel)]
    teile += [Paragraph(t(kopf), stil_kopf) for kopf in dokument.kopfzeilen]
    if dokument.kopfzeilen:
        teile.append(Spacer(1, 4 * mm))
    for a in dokument.abschnitte:
        if a.art == UEBERSCHRIFT:
            teile.append(Paragraph(t(a.text), stil_titel if a.stufe <= 1 else stil_h2 if a.stufe == 2 else stil_h3))
        elif a.art == ABSATZ:
            vorn = f'<font name="{fett}">{t(a.betont)}</font>' if a.betont else ""
            teile.append(Paragraph(vorn + t(a.text), stil_text))
        elif a.art == LISTE:
            teile.append(
                ListFlowable(
                    [ListItem(Paragraph(t(punkt), stil_text), leftIndent=12) for punkt in a.punkte],
                    bulletType="bullet",
                    start="•",
                    leftIndent=12,
                )
            )
        elif a.art == SEITENUMBRUCH:
            teile.append(PageBreak())
    pdf = SimpleDocTemplate(
        str(ziel),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=dokument.titel[:255],
    )
    try:
        pdf.build(teile)
    except (ValueError, OSError) as fehler:
        raise ExportFehler(f"Die PDF-Datei konnte nicht erzeugt werden: {fehler}") from fehler


# --------------------------------------------------------------------------
# OpenDocument
# --------------------------------------------------------------------------
_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""

_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" office:version="1.2"'
)

_STILE = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {_NS}>
 <office:styles>
  <style:style style:name="Standard" style:family="paragraph">
   <style:paragraph-properties fo:margin-bottom="0.15cm"/>
   <style:text-properties style:font-name="Arial" fo:font-family="Arial" fo:font-size="10.5pt"/>
  </style:style>
  <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph" style:parent-style-name="Standard">
   <style:text-properties fo:font-size="18pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="Heading_20_2" style:display-name="Heading 2" style:family="paragraph" style:parent-style-name="Standard">
   <style:paragraph-properties fo:margin-top="0.35cm"/>
   <style:text-properties fo:font-size="13.5pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="Kopf" style:family="paragraph" style:parent-style-name="Standard">
   <style:text-properties fo:color="#555555"/>
  </style:style>
  <style:style style:name="Fett" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>
 </office:styles>
 <office:automatic-styles>
  <style:style style:name="Umbruch" style:family="paragraph" style:parent-style-name="Standard">
   <style:paragraph-properties fo:break-before="page"/>
  </style:style>
 </office:automatic-styles>
</office:document-styles>
"""


def _x(text: str) -> str:
    # Steuerzeichen sind in XML verboten (ein Sprachmodell liefert selten, aber doch so etwas).
    return escape("".join(z for z in text if z in "\t\n" or ord(z) >= 32))


def odt_inhalt(dokument: Dokument) -> str:
    teile = [f'<text:h text:style-name="Heading_20_1" text:outline-level="1">{_x(dokument.titel)}</text:h>']
    teile += [f'<text:p text:style-name="Kopf">{_x(kopf)}</text:p>' for kopf in dokument.kopfzeilen]
    umbruch = False
    for a in dokument.abschnitte:
        if a.art == SEITENUMBRUCH:
            umbruch = True
            continue
        stil_absatz = "Umbruch" if umbruch else "Standard"
        umbruch = False
        if a.art == UEBERSCHRIFT:
            stufe = max(1, min(a.stufe, 2))
            teile.append(f'<text:h text:style-name="Heading_20_{stufe}" text:outline-level="{stufe}">{_x(a.text)}</text:h>')
        elif a.art == ABSATZ:
            vorn = f'<text:span text:style-name="Fett">{_x(a.betont)}</text:span>' if a.betont else ""
            teile.append(f'<text:p text:style-name="{stil_absatz}">{vorn}{_x(a.text)}</text:p>')
        elif a.art == LISTE:
            punkte = "".join(f"<text:list-item><text:p>{_x(p)}</text:p></text:list-item>" for p in a.punkte)
            teile.append(f"<text:list>{punkte}</text:list>")
    koerper = "\n".join(teile)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {_NS}>\n<office:body><office:text>\n{koerper}\n</office:text></office:body>\n</office:document-content>\n'


def schreibe_odt(dokument: Dokument, ziel: Path) -> None:
    meta = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-meta {_NS}><office:meta>'
        f"<dc:title>{_x(dokument.titel)}</dc:title><meta:generator>VERMERK</meta:generator>"
        "</office:meta></office:document-meta>\n"
    )
    with zipfile.ZipFile(ziel, "w") as odt:
        # Die Kennung muss als erste Datei und unkomprimiert drinstehen (OpenDocument-Vorgabe).
        odt.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        odt.writestr("META-INF/manifest.xml", _MANIFEST, compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr("content.xml", odt_inhalt(dokument), compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr("styles.xml", _STILE, compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr("meta.xml", meta, compress_type=zipfile.ZIP_DEFLATED)
