"""Grafische Oberflaeche fuer den Protokoll-Assistenten.

Nutzt die bestehende Konsolen-Logik aus protokoll_assistent_v2.py als
Bibliothek (diese Datei bleibt unveraendert und weiterhin eigenstaendig
lauffaehig). Ergaenzt wird eine zweite Stufe: ein lokales KI-Modell
(z. B. ueber Ollama) verarbeitet das fertige Transkript gemaess einem
frei formulierbaren Systemprompt (Zusammenfassung, Agenda, Prioritaeten
usw.), ohne dass dafuer weitere Daten das Geraet verlassen.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import sys
import subprocess
import tempfile
import threading
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protokoll_assistent_v2 as kern  # Konsolenversion wird als Bibliothek wiederverwendet

APP_DIR = kern.APP_DIR
INPUT_DIR = kern.INPUT_DIR
OUTPUT_DIR = kern.OUTPUT_DIR
CHECKPOINT_DIR = kern.CHECKPOINT_DIR
SETTINGS_DIR = kern.SETTINGS_DIR

LOCAL_MODEL_URL = os.environ.get(
    "PROTOKOLL_LOKALES_MODELL_URL", "http://localhost:11434/api/generate"
)
DEFAULT_LOCAL_MODEL = os.environ.get("PROTOKOLL_LOKALES_MODELL", "llama3.1")
LOCAL_MODEL_TIMEOUT_SECONDS = 1800

DEFAULT_SYSTEMPROMPT = (
    "Fasse das folgende Besprechungstranskript in klarer, gut strukturierter "
    "Form zusammen. Nenne die wichtigsten Themen, getroffene Entscheidungen "
    "und offene Aufgaben mit Verantwortlichen, falls erkennbar."
)

SYSTEMPROMPT_VORLAGEN = {
    "Zusammenfassung": DEFAULT_SYSTEMPROMPT,
    "Agenda": (
        "Erstelle aus dem folgenden Besprechungstranskript eine strukturierte "
        "Agenda im Nachhinein: Liste die behandelten Themen in der besprochenen "
        "Reihenfolge auf, mit je 1-2 Saetzen Inhalt."
    ),
    "Prioritaetenliste": (
        "Erstelle aus dem folgenden Besprechungstranskript eine priorisierte "
        "Aufgabenliste. Sortiere nach Dringlichkeit, nenne wenn moeglich "
        "Verantwortliche und Termine."
    ),
}

FFMPEG_SUCHPFADE = [
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/snap/bin/ffmpeg",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
]


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    env_path = os.environ.get("FFMPEG_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path
    for candidate in FFMPEG_SUCHPFADE:
        if Path(candidate).is_file():
            return candidate
    return None


def ensure_ffmpeg_on_path() -> str | None:
    """Findet FFmpeg auch ausserhalb von PATH, ohne protokoll_assistent_v2.py zu aendern."""
    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path and not shutil.which("ffmpeg"):
        ffmpeg_dir = str(Path(ffmpeg_path).resolve().parent)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    return ffmpeg_path


def scan_audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in kern.SUPPORTED_EXTENSIONS
    )


def open_in_file_manager(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        pass


def call_local_model(
    transcript_text: str, system_prompt: str, model_name: str, log: Callable[[str], None]
) -> str:
    payload = {
        "model": model_name,
        "system": system_prompt,
        "prompt": transcript_text,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        LOCAL_MODEL_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    log(f"Lokales Modell '{model_name}' wird angefragt ({LOCAL_MODEL_URL}) ...")
    try:
        with urllib.request.urlopen(request, timeout=LOCAL_MODEL_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"Das lokale Modell '{model_name}' meldet HTTP {error.code}: {details}\n"
            f"Ist das Modell installiert? Ggf. mit 'ollama pull {model_name}' nachladen."
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            "Das lokale KI-Modell ist nicht erreichbar. Bitte pruefen, ob Ollama "
            f"laeuft (https://ollama.com) und unter {LOCAL_MODEL_URL} erreichbar ist. "
            f"Technische Details: {error}"
        ) from error

    if not isinstance(result, dict):
        raise RuntimeError("Das lokale Modell hat kein JSON-Objekt geliefert.")
    text = str(result.get("response", "")).strip()
    if not text:
        raise RuntimeError("Das lokale Modell hat keine Antwort geliefert.")
    return text


def save_processed_result(
    source: Path, system_prompt: str, model_name: str, result_text: str
) -> tuple[Path, Path]:
    output_txt = OUTPUT_DIR / f"{source.stem}_protokoll.txt"
    output_json = OUTPUT_DIR / f"{source.stem}_protokoll.json"

    header = [
        "PROTOKOLL-ASSISTENT - ERGEBNIS DER LOKALEN VERARBEITUNG",
        f"Quelldatei: {source.name}",
        f"Erstellt: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Lokales Modell: {model_name}",
        "",
        "Verwendeter Systemprompt:",
        system_prompt.strip(),
        "",
        "-" * 72,
        "",
    ]
    output_txt.write_text("\n".join(header) + result_text.strip() + "\n", encoding="utf-8")

    payload = {
        "quelldatei": source.name,
        "erstellt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "lokales_modell": model_name,
        "systemprompt": system_prompt.strip(),
        "ergebnis": result_text.strip(),
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_txt, output_json


class ProtokollGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Protokoll-Assistent")
        root.geometry("960x780")
        root.minsize(760, 620)

        self.selected_folder: Path | None = None
        self.audio_files: list[Path] = []
        self.message_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.confirm_event = threading.Event()
        self.confirm_result = False
        self.worker_thread: threading.Thread | None = None
        self.last_output_paths: list[Path] = []

        for directory in (INPUT_DIR, OUTPUT_DIR, CHECKPOINT_DIR, SETTINGS_DIR):
            directory.mkdir(parents=True, exist_ok=True)

        self._build_widgets()
        self._poll_queue()

    # ------------------------------------------------------------------ UI

    def _build_widgets(self) -> None:
        padding = {"padx": 10, "pady": 6}

        folder_frame = ttk.LabelFrame(self.root, text="1. Aufnahme auswaehlen")
        folder_frame.pack(fill="x", **padding)

        row1 = ttk.Frame(folder_frame)
        row1.pack(fill="x", padx=8, pady=6)
        ttk.Button(row1, text="Ordner auswaehlen ...", command=self.choose_folder).pack(
            side="left"
        )
        self.folder_label_var = tk.StringVar(value="Kein Ordner ausgewaehlt")
        ttk.Label(row1, textvariable=self.folder_label_var).pack(side="left", padx=10)

        row2 = ttk.Frame(folder_frame)
        row2.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(row2, text="Datei:").pack(side="left")
        self.file_var = tk.StringVar()
        self.file_combo = ttk.Combobox(
            row2, textvariable=self.file_var, state="readonly", width=60
        )
        self.file_combo.pack(side="left", padx=8, fill="x", expand=True)

        api_frame = ttk.LabelFrame(self.root, text="2. OpenRouter API-Schluessel")
        api_frame.pack(fill="x", **padding)
        row3 = ttk.Frame(api_frame)
        row3.pack(fill="x", padx=8, pady=6)
        ttk.Label(row3, text="API-Schluessel:").pack(side="left")
        self.api_key_var = tk.StringVar(value=os.environ.get("OPENROUTER_API_KEY", ""))
        self.api_key_entry = ttk.Entry(row3, textvariable=self.api_key_var, show="*", width=50)
        self.api_key_entry.pack(side="left", padx=8, fill="x", expand=True)
        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row3, text="anzeigen", variable=self.show_key_var, command=self._toggle_key_visibility
        ).pack(side="left")
        ttk.Label(
            api_frame,
            text=(
                "Der Schluessel wird nur im Arbeitsspeicher dieser Sitzung gehalten, "
                "niemals in eine Datei oder in den Code geschrieben."
            ),
            foreground="#555555",
            wraplength=880,
            justify="left",
        ).pack(fill="x", padx=8, pady=(0, 6))

        model_frame = ttk.LabelFrame(self.root, text="3. Lokales Modell fuer die Nachbearbeitung")
        model_frame.pack(fill="x", **padding)
        row4 = ttk.Frame(model_frame)
        row4.pack(fill="x", padx=8, pady=6)
        ttk.Label(row4, text="Modellname (z. B. Ollama):").pack(side="left")
        self.model_var = tk.StringVar(value=DEFAULT_LOCAL_MODEL)
        ttk.Entry(row4, textvariable=self.model_var, width=30).pack(side="left", padx=8)
        ttk.Label(
            model_frame,
            text=(
                "Das Modell laeuft lokal (z. B. via Ollama, https://ollama.com) und "
                "verarbeitet nur Daten, die bereits auf diesem Geraet liegen."
            ),
            foreground="#555555",
            wraplength=880,
            justify="left",
        ).pack(fill="x", padx=8, pady=(0, 6))

        prompt_frame = ttk.LabelFrame(
            self.root, text="4. Was soll mit dem Transkript geschehen? (Systemprompt)"
        )
        prompt_frame.pack(fill="both", expand=False, **padding)
        row5 = ttk.Frame(prompt_frame)
        row5.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(row5, text="Vorlage:").pack(side="left")
        self.template_var = tk.StringVar()
        template_combo = ttk.Combobox(
            row5,
            textvariable=self.template_var,
            state="readonly",
            values=list(SYSTEMPROMPT_VORLAGEN.keys()),
            width=25,
        )
        template_combo.pack(side="left", padx=8)
        template_combo.bind("<<ComboboxSelected>>", self._apply_template)

        self.systemprompt_text = tk.Text(prompt_frame, height=5, wrap="word")
        self.systemprompt_text.pack(fill="x", padx=8, pady=6)
        self.systemprompt_text.insert("1.0", DEFAULT_SYSTEMPROMPT)

        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", **padding)
        self.start_button = ttk.Button(
            action_frame, text="Transkription starten", command=self.start
        )
        self.start_button.pack(side="left")
        self.open_output_button = ttk.Button(
            action_frame,
            text="Ausgabeordner oeffnen",
            command=lambda: open_in_file_manager(OUTPUT_DIR),
        )
        self.open_output_button.pack(side="left", padx=8)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            self.root, maximum=1.0, variable=self.progress_var
        )
        self.progress_bar.pack(fill="x", padx=10, pady=(0, 2))
        self.progress_label_var = tk.StringVar(value="Bereit.")
        ttk.Label(self.root, textvariable=self.progress_label_var).pack(
            anchor="w", padx=10, pady=(0, 6)
        )

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_tab = ttk.Frame(notebook)
        notebook.add(log_tab, text="Ablauf / Protokoll")
        self.log_text = scrolledtext.ScrolledText(log_tab, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        result_tab = ttk.Frame(notebook)
        notebook.add(result_tab, text="Ergebnis")
        self.result_text = scrolledtext.ScrolledText(result_tab, wrap="word", state="disabled")
        self.result_text.pack(fill="both", expand=True)

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.config(show="" if self.show_key_var.get() else "*")

    def _apply_template(self, _event: object = None) -> None:
        template = SYSTEMPROMPT_VORLAGEN.get(self.template_var.get())
        if template:
            self.systemprompt_text.delete("1.0", "end")
            self.systemprompt_text.insert("1.0", template)

    # ------------------------------------------------------------ Auswahl

    def choose_folder(self) -> None:
        start_dir = str(INPUT_DIR) if INPUT_DIR.exists() else str(APP_DIR)
        folder = filedialog.askdirectory(
            title="Ordner mit der Aufnahme auswaehlen", initialdir=start_dir
        )
        if not folder:
            return
        self.selected_folder = Path(folder)
        self.audio_files = scan_audio_files(self.selected_folder)

        if not self.audio_files:
            self.folder_label_var.set(f"{self.selected_folder} (keine unterstuetzte Datei gefunden)")
            self.file_combo["values"] = []
            self.file_var.set("")
            return

        self.folder_label_var.set(str(self.selected_folder))
        self.file_combo["values"] = [path.name for path in self.audio_files]
        self.file_var.set(self.audio_files[0].name)

    # -------------------------------------------------------------- Start

    def start(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        if not self.audio_files or not self.file_var.get():
            messagebox.showwarning(
                "Keine Datei ausgewaehlt",
                "Bitte zuerst einen Ordner mit einer Audio- oder Videodatei auswaehlen.",
            )
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning(
                "API-Schluessel fehlt", "Bitte den OpenRouter API-Schluessel eingeben."
            )
            return

        systemprompt = self.systemprompt_text.get("1.0", "end").strip()
        if not systemprompt:
            messagebox.showwarning(
                "Systemprompt fehlt",
                "Bitte beschreiben, was mit dem Transkript geschehen soll.",
            )
            return

        model_name = self.model_var.get().strip() or DEFAULT_LOCAL_MODEL
        source = self.selected_folder / self.file_var.get()  # type: ignore[operator]

        self.start_button.config(state="disabled")
        self.progress_var.set(0.0)
        self.progress_label_var.set("Start ...")
        self._set_text_widget(self.log_text, "")
        self._set_text_widget(self.result_text, "")

        self.worker_thread = threading.Thread(
            target=self._run_pipeline,
            args=(source, api_key, systemprompt, model_name),
            daemon=True,
        )
        self.worker_thread.start()

    # ---------------------------------------------------------- Pipeline

    def _log(self, message: str) -> None:
        self.message_queue.put(("log", message))

    def _progress(self, fraction: float, text: str) -> None:
        self.message_queue.put(("progress", (fraction, text)))

    def _ask_confirmation(self, source: "Path") -> bool:
        self.confirm_event.clear()
        self.message_queue.put(("confirm", source))
        self.confirm_event.wait()
        return self.confirm_result

    def _run_pipeline(
        self, source: Path, api_key: str, systemprompt: str, model_name: str
    ) -> None:
        try:
            os.environ["OPENROUTER_API_KEY"] = api_key
            self._log(f"Eingabedatei: {source.name}")
            self._log(f"Transkriptionsmodell: {kern.MODEL_NAME} (Sprechertrennung aktiviert)")

            self._progress(0.05, "Datenschutzabfrage ...")
            if not self._ask_confirmation(source):
                self._log("Abbruch: Uebertragung wurde nicht bestaetigt. Es wurden keine Daten gesendet.")
                return

            ffmpeg_path = ensure_ffmpeg_on_path()
            if ffmpeg_path:
                self._log(f"FFmpeg gefunden: {ffmpeg_path}")
            else:
                self._log(
                    "Hinweis: FFmpeg wurde nicht gefunden. Fuer Video- oder grosse "
                    "Audiodateien bitte FFmpeg installieren (https://ffmpeg.org)."
                )

            checkpoint = CHECKPOINT_DIR / f"{source.stem}_mai_transcribe_2_rohantwort.json"
            if checkpoint.exists():
                self._log("Vorhandene Modellantwort wird weiterverarbeitet (kein neuer Upload).")
                api_result = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
            else:
                self._progress(0.15, "Audio wird vorbereitet ...")
                terms = kern.load_terms()
                with tempfile.TemporaryDirectory(prefix="protokoll_audio_") as temp_name:
                    audio_path, audio_format = kern.prepare_audio(source, Path(temp_name))
                    request_data = kern.build_request(audio_path, audio_format, terms)
                    self._progress(0.35, "Uebertragung an OpenRouter / Azure ...")
                    self._log("Cloud-Transkription mit Sprechertrennung gestartet ...")
                    api_result = kern.call_openrouter(request_data, api_key)
                checkpoint.write_text(
                    json.dumps(api_result, ensure_ascii=False, indent=2), encoding="utf-8"
                )

            self._progress(0.6, "Transkript wird gespeichert ...")
            output_txt, output_json = kern.save_transcript(source, api_result)
            checkpoint.unlink(missing_ok=True)
            self._log(f"Transkript gespeichert: {output_txt.name}")
            self._log(f"Transkript (JSON) gespeichert: {output_json.name}")

            self._progress(0.75, "Lokale Verarbeitung gemaess Systemprompt ...")
            self._log(
                "Transkript wird lokal verarbeitet - hierfuer werden keine weiteren "
                "Daten an Dritte uebertragen."
            )
            transcript_text = output_txt.read_text(encoding="utf-8")
            result_text = call_local_model(transcript_text, systemprompt, model_name, self._log)
            protokoll_txt, protokoll_json = save_processed_result(
                source, systemprompt, model_name, result_text
            )
            self._log(f"Ergebnis gespeichert: {protokoll_txt.name}")
            self._log(f"Ergebnis (JSON) gespeichert: {protokoll_json.name}")

            self._progress(1.0, "Fertig.")
            self.message_queue.put(
                (
                    "result",
                    (result_text, [output_txt, output_json, protokoll_txt, protokoll_json]),
                )
            )
        except KeyboardInterrupt:
            self._log("Abbruch durch Benutzer.")
        except Exception as error:  # noqa: BLE001 - Fehler sollen sichtbar in der GUI landen
            self._log(f"FEHLER: {error}")
            self.message_queue.put(("error", str(error)))
        finally:
            os.environ.pop("OPENROUTER_API_KEY", None)
            self.message_queue.put(("done", None))

    # -------------------------------------------------------------- Queue

    def _set_text_widget(self, widget: tk.Text, content: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.config(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _show_confirm_dialog(self, source: Path) -> None:
        answer = messagebox.askyesno(
            "Datenschutzhinweis",
            (
                f"Die Aufnahme '{source.name}' wird zur Transkription an OpenRouter "
                "und den Modellanbieter (Microsoft Azure) uebertragen.\n\n"
                "Die anschliessende Zusammenfassung/Auswertung erfolgt danach lokal "
                "auf diesem Geraet.\n\nUebertragung jetzt starten?"
            ),
        )
        self.confirm_result = bool(answer)
        self.confirm_event.set()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    fraction, text = payload
                    self.progress_var.set(fraction)
                    self.progress_label_var.set(text)
                elif kind == "confirm":
                    self._show_confirm_dialog(payload)
                elif kind == "result":
                    result_text, paths = payload
                    self._set_text_widget(self.result_text, result_text)
                    self.last_output_paths = paths
                elif kind == "error":
                    messagebox.showerror("Fehler", payload)
                elif kind == "done":
                    self.start_button.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


def main() -> int:
    root = tk.Tk()
    ProtokollGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
