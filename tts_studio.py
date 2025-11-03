#!/usr/bin/env python3
# tts_studio.py — Offline Text-to-Speech Studio (Windows SAPI5)
# Features: dark theme, colored buttons, voice discovery (pyttsx3 + SAPI fallback),
# Save/Load text, Export to WAV. No auto-installer.

import sys, os, json, threading, time, traceback, queue
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# ------------------ Dependency check (no auto-install) ------------------
MISSING = []
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import Qt
except Exception:
    MISSING.append("PyQt6")
try:
    import pyttsx3
except Exception:
    MISSING.append("pyttsx3")
try:
    import keyboard  # optional
    KEYBOARD_OK = True
except Exception:
    KEYBOARD_OK = False

if MISSING:
    msg = (
        "Missing required packages:\n  - "
        + "\n  - ".join(MISSING)
        + "\n\nInstall them with:\n"
        + f"{sys.executable} -m pip install " + " ".join(MISSING)
    )
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb
        r = _tk.Tk(); r.withdraw()
        _mb.showerror("Dependencies Missing", msg)
        r.destroy()
    except Exception:
        pass
    print(msg, file=sys.stderr)
    sys.exit(1)

# ------------------ Paths & storage ------------------
APP_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
DATA_DIR = APP_DIR / "tts_data"
DATA_DIR.mkdir(exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
DEFAULTS = {
    "geometry": None,
    "voice_id": None,
    "rate": 180,
    "volume": 0.9,
    "last_text": "",
    "mini_transport": {"x": None, "y": None}
}

def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return json.loads(json.dumps(default))

def save_json(path: Path, obj):
    try:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

# ------------------ TTS Worker ------------------
@dataclass
class TTSItem:
    text: str
    voice_id: Optional[str] = None
    rate: Optional[int] = None
    volume: Optional[float] = None
    label: Optional[str] = None
    export_wav_path: Optional[str] = None

class TTSWorker(QtCore.QObject):
    started = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._q = queue.Queue()
        self._stop_flag = threading.Event()
        self._busy = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, item: TTSItem):
        self._q.put(item)

    def stop_current(self):
        self._stop_flag.set()

    def _run(self):
        while True:
            item: TTSItem = self._q.get()
            if item is None:
                break
            try:
                self._busy.set()
                self._stop_flag.clear()
                self.started.emit(item.label or "Speaking")

                engine = pyttsx3.init('sapi5')  # Windows SAPI5
                if item.voice_id:
                    try:
                        engine.setProperty('voice', item.voice_id)
                    except Exception:
                        pass
                if item.rate is not None:
                    engine.setProperty('rate', int(item.rate))
                if item.volume is not None:
                    engine.setProperty('volume', float(item.volume))

                text = item.text or ""
                if item.export_wav_path:
                    engine.save_to_file(text, item.export_wav_path)
                    engine.runAndWait()
                else:
                    CHUNK = 800
                    for i in range(0, max(1, len(text)), CHUNK):
                        if self._stop_flag.is_set():
                            break
                        engine.say(text[i:i+CHUNK] if text else " ")
                        engine.runAndWait()

                try: engine.stop()
                except Exception: pass
                self.finished.emit("Stopped" if self._stop_flag.is_set() else "Done")
            except Exception as e:
                self.error.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            finally:
                self._busy.clear()

# ------------------ Mini Transport (optional) ------------------
class MiniTransport(QtWidgets.QWidget):
    playClicked = QtCore.pyqtSignal()
    stopClicked = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        btnPlay = QtWidgets.QPushButton("▶"); btnPlay.setFixedSize(38,38)
        btnStop = QtWidgets.QPushButton("■"); btnStop.setFixedSize(38,38)
        for b in (btnPlay, btnStop):
            b.setStyleSheet("QPushButton{border-radius:10px; padding:6px;}")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8,8,8,8)
        lay.addWidget(btnPlay); lay.addWidget(btnStop)
        self.setStyleSheet("background:rgba(24,24,24,0.88); color:white;")

        btnPlay.clicked.connect(self.playClicked.emit)
        btnStop.clicked.connect(self.stopClicked.emit)

        self._drag = None

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if self._drag:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        self._drag = None

# ------------------ Main Window ------------------
class TTSStudio(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TTS Studio — Offline Text-to-Speech")
        self.setMinimumSize(980, 640)

        self.config = load_json(CONFIG_FILE, DEFAULTS)

        # Worker
        self.worker = TTSWorker()
        self.worker.started.connect(self.onWorkerStarted)
        self.worker.finished.connect(self.onWorkerFinished)
        self.worker.error.connect(self.onWorkerError)

        # Status bar first
        self.status = self.statusBar()
        self.status.showMessage("Ready")

        # Editor
        self.editor = QtWidgets.QTextEdit()
        self.editor.setPlaceholderText("Type or paste text here…")
        self.editor.setPlainText(self.config.get("last_text", ""))

        # Controls
        self.voiceCombo = QtWidgets.QComboBox()
        self.rateSlider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.rateSlider.setRange(80, 300)
        self.rateSlider.setValue(int(self.config.get("rate", 180)))
        self.rateValue = QtWidgets.QLabel(str(self.rateSlider.value()))
        self.rateSlider.valueChanged.connect(lambda v: self.rateValue.setText(str(v)))

        self.volSlider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.volSlider.setRange(0, 100)
        self.volSlider.setValue(int(self.config.get("volume", 0.9)*100))
        self.volValue = QtWidgets.QLabel(f"{self.volSlider.value()}%")
        self.volSlider.valueChanged.connect(lambda v: self.volValue.setText(f"{v}%"))

        # Buttons
        btnSpeak = QtWidgets.QPushButton("▶ Speak")
        btnStop  = QtWidgets.QPushButton("■ Stop"); btnStop.setProperty("class", "secondary")
        btnSave  = QtWidgets.QPushButton("Save Text…")
        btnLoad  = QtWidgets.QPushButton("Load Text…"); btnLoad.setProperty("class", "secondary")
        btnWav   = QtWidgets.QPushButton("Export to WAV")
        btnClear = QtWidgets.QPushButton("Clear"); btnClear.setProperty("class", "secondary")

        # Layout (left panel)
        left = QtWidgets.QFrame(); left.setMaximumWidth(360)
        leftLay = QtWidgets.QVBoxLayout(left); leftLay.setSpacing(10)

        vForm = QtWidgets.QFormLayout()
        vForm.addRow("Voice", self.voiceCombo)
        rateRow = QtWidgets.QHBoxLayout(); rateRow.addWidget(self.rateSlider); rateRow.addWidget(self.rateValue)
        volRow  = QtWidgets.QHBoxLayout(); volRow.addWidget(self.volSlider);  volRow.addWidget(self.volValue)
        vForm.addRow("Rate", rateRow); vForm.addRow("Volume", volRow)

        leftLay.addLayout(vForm)

        ctrlBox = QtWidgets.QGroupBox("Controls")
        ctrlLay = QtWidgets.QGridLayout(ctrlBox)
        ctrlLay.addWidget(btnSpeak, 0, 0)
        ctrlLay.addWidget(btnStop,  0, 1)
        ctrlLay.addWidget(btnSave,  1, 0)
        ctrlLay.addWidget(btnLoad,  1, 1)
        ctrlLay.addWidget(btnWav,   2, 0)
        ctrlLay.addWidget(btnClear, 2, 1)

        leftLay.addWidget(ctrlBox)
        leftLay.addStretch(1)

        # Splitter
        splitter = QtWidgets.QSplitter()
        splitter.addWidget(left)
        editorBox = QtWidgets.QGroupBox("Editor"); eLay = QtWidgets.QVBoxLayout(editorBox); eLay.addWidget(self.editor)
        splitter.addWidget(editorBox)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        # Menus / shortcuts
        self._makeMenus()

        # Style + voices
        self._applyDarkTheme()
        self.refreshVoices()

        # Wire actions
        btnSpeak.clicked.connect(self.speakEditor)
        btnStop.clicked.connect(self.stopSpeaking)
        btnSave.clicked.connect(self.saveTextFile)
        btnLoad.clicked.connect(self.loadTextFile)
        btnWav.clicked.connect(self.exportToWav)
        btnClear.clicked.connect(self.editor.clear)

        # Mini transport (optional)
        self.mini = MiniTransport()
        self.mini.playClicked.connect(self.speakEditor)
        self.mini.stopClicked.connect(self.stopSpeaking)
        self.mini.show()
        mt = self.config.get("mini_transport", {})
        if mt.get("x") is not None and mt.get("y") is not None:
            self.mini.move(mt["x"], mt["y"])

        # Hotkeys
        if KEYBOARD_OK:
            try:
                keyboard.add_hotkey("ctrl+alt+p", lambda: self.speakEditor())
                keyboard.add_hotkey("ctrl+alt+s", lambda: self.stopSpeaking())
            except Exception:
                pass

    # ------------------ Menus ------------------
    def _makeMenus(self):
        fileMenu = self.menuBar().addMenu("&File")
        actSave = fileMenu.addAction("Save Text…"); actSave.setShortcut("Ctrl+S"); actSave.triggered.connect(self.saveTextFile)
        actLoad = fileMenu.addAction("Load Text…"); actLoad.setShortcut("Ctrl+O"); actLoad.triggered.connect(self.loadTextFile)
        actExport = fileMenu.addAction("Export to WAV…"); actExport.setShortcut("Ctrl+E"); actExport.triggered.connect(self.exportToWav)
        fileMenu.addSeparator()
        actQuit = fileMenu.addAction("Quit"); actQuit.setShortcut("Ctrl+Q"); actQuit.triggered.connect(self.close)

        viewMenu = self.menuBar().addMenu("&View")
        actRefresh = viewMenu.addAction("Refresh Voices"); actRefresh.triggered.connect(self.refreshVoices)
        actMini = viewMenu.addAction("Toggle Mini Transport"); actMini.setCheckable(True); actMini.setChecked(True)
        actMini.triggered.connect(lambda checked: self.mini.setVisible(checked))

        helpMenu = self.menuBar().addMenu("&Help")
        helpMenu.addAction("About").triggered.connect(lambda: QtWidgets.QMessageBox.information(
            self, "About",
            "TTS Studio\n\nOffline text-to-speech using Windows SAPI5 via pyttsx3.\n"
            "Buttons are color-styled; voices are discovered via pyttsx3 with a SAPI fallback.\n"
            "Use Save/Load to manage text and Export to WAV to render audio."
        ))

    # ------------------ Theming ------------------
    def _applyDarkTheme(self):
        pal = self.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(24,24,24))
        pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(28,28,28))
        pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(230,230,230))
        pal.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(40,40,40))
        pal.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(230,230,230))
        pal.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(64,128,255))
        pal.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(255,255,255))
        self.setPalette(pal)

        self.setStyleSheet("""
            QWidget { color: #E6E6E6; }
            QGroupBox{
                border:1px solid #333; border-radius:10px; margin-top:12px;
            }
            QGroupBox::title{
                subcontrol-origin: margin; left:10px; padding:0 6px; color:#BBB;
            }
            QTextEdit, QComboBox {
                border:1px solid #333; border-radius:8px; background:#1E1E1E;
            }
            /* ---- Buttons (custom colors) ---- */
            QPushButton {
                background:#3B82F6;            /* primary blue */
                border: none;
                color: white;
                padding: 8px 12px;
                border-radius: 10px;
                font-weight: 600;
            }
            QPushButton:hover { background:#2563EB; }   /* darker on hover */
            QPushButton:pressed { background:#1D4ED8; } /* even darker on press */
            QPushButton[class="secondary"] {
                background:#4B5563;
            }
            QPushButton[class="secondary"]:hover { background:#374151; }
            QPushButton[class="secondary"]:pressed { background:#1F2937; }
            /* Sliders */
            QSlider::groove:horizontal { height:6px; background:#333; border-radius:3px; }
            QSlider::handle:horizontal { width:14px; background:#888; margin:-6px 0; border-radius:7px; }
        """)

    # ------------------ Voice discovery ------------------
    def refreshVoices(self):
        self.voiceCombo.clear()
        found = 0

        # 1) Normal pyttsx3 discovery
        try:
            engine = pyttsx3.init('sapi5')
            voices = engine.getProperty('voices') or []
            for v in voices:
                name = getattr(v, "name", None) or "Voice"
                vid  = getattr(v, "id", None)
                if vid:
                    self.voiceCombo.addItem(name, vid)
                    found += 1
            try: engine.stop()
            except Exception: pass
        except Exception as e:
            self.status.showMessage(f"pyttsx3 voice load failed, trying fallback: {e}", 6000)

        # 2) Fallback: direct SAPI probe via comtypes (covers edge cases)
        if found == 0:
            try:
                import comtypes.client
                spvoice = comtypes.client.CreateObject("SAPI.SpVoice")
                tokens = spvoice.GetVoices()  # ISpeechObjectTokens
                count = tokens.Count
                for i in range(count):
                    tok = tokens.Item(i)
                    name = tok.GetAttribute("Name") or f"Voice {i+1}"
                    vid  = tok.Id  # token ID string
                    self.voiceCombo.addItem(name, vid)
                    found += 1
            except Exception as e:
                self.status.showMessage(f"SAPI fallback failed: {e}", 8000)

        if found == 0:
            self.status.showMessage("No Windows voices installed.", 8000)
            QtWidgets.QMessageBox.information(
                self, "No Voices Found",
                "No SAPI5 voices were found.\n\n"
                "Install voices via:\n"
                "  Settings → Time & Language → Speech → Manage voices → Add voices\n"
                "Then sign out/in and click View → Refresh Voices."
            )
        else:
            # Select saved voice if available
            vid = self.config.get("voice_id")
            if vid:
                idx = self.voiceCombo.findData(vid)
                if idx >= 0:
                    self.voiceCombo.setCurrentIndex(idx)

    def currentVoiceId(self) -> Optional[str]:
        return self.voiceCombo.currentData()

    # ------------------ Actions ------------------
    def speakEditor(self):
        text = self.editor.toPlainText().strip()
        if not text:
            self.status.showMessage("Nothing to speak.", 3000); return
        item = TTSItem(
            text=text,
            voice_id=self.currentVoiceId(),
            rate=int(self.rateSlider.value()),
            volume=float(self.volSlider.value()/100.0),
            label="Editor"
        )
        self.worker.enqueue(item)

    def stopSpeaking(self):
        self.worker.stop_current()
        self.status.showMessage("Stopped")

    def exportToWav(self):
        text = self.editor.toPlainText().strip()
        if not text:
            self.status.showMessage("Nothing to export.", 3000); return
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export to WAV", str(APP_DIR / "output.wav"), "WAV files (*.wav)")
        if not fn: return
        item = TTSItem(
            text=text,
            voice_id=self.currentVoiceId(),
            rate=int(self.rateSlider.value()),
            volume=float(self.volSlider.value()/100.0),
            label=f"Export -> {Path(fn).name}",
            export_wav_path=fn
        )
        self.worker.enqueue(item)
        self.status.showMessage(f"Exporting to {fn}")

    def saveTextFile(self):
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Text", str(APP_DIR / "text.txt"), "Text files (*.txt)")
        if fn:
            Path(fn).write_text(self.editor.toPlainText(), encoding="utf-8")
            self.status.showMessage(f"Saved {fn}")

    def loadTextFile(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load Text", str(APP_DIR), "Text files (*.txt *.md)")
        if fn:
            txt = Path(fn).read_text(encoding="utf-8", errors="ignore")
            self.editor.setPlainText(txt)
            self.status.showMessage(f"Loaded {fn}")

    # ------------------ Worker callbacks ------------------
    def onWorkerStarted(self, label: str):
        self.status.showMessage(f"Speaking: {label}", 3000)

    def onWorkerFinished(self, status: str):
        self.status.showMessage(status, 3000)
        # persist config
        self.config["voice_id"] = self.currentVoiceId()
        self.config["rate"] = int(self.rateSlider.value())
        self.config["volume"] = float(self.volSlider.value()/100.0)
        self.config["last_text"] = self.editor.toPlainText()
        self._saveConfig()

    def onWorkerError(self, msg: str):
        self.status.showMessage("Error — see console", 8000)
        print(msg)

    # ------------------ Persistence ------------------
    def closeEvent(self, e: QtGui.QCloseEvent):
        self.config["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.config["voice_id"] = self.currentVoiceId()
        self.config["rate"] = int(self.rateSlider.value())
        self.config["volume"] = float(self.volSlider.value()/100.0)
        mt = self.config["mini_transport"]
        mt["x"], mt["y"] = self.mini.x(), self.mini.y()
        self.config["last_text"] = self.editor.toPlainText()
        self._saveConfig()
        if KEYBOARD_OK:
            try: keyboard.unhook_all_hotkeys()
            except Exception: pass
        super().closeEvent(e)

    def showEvent(self, e: QtGui.QShowEvent):
        super().showEvent(e)
        geo = self.config.get("geometry")
        if geo:
            try: self.restoreGeometry(QtCore.QByteArray.fromBase64(geo.encode()))
            except Exception: pass

    def _saveConfig(self):
        try:
            save_json(CONFIG_FILE, self.config)
        except Exception:
            pass

# ------------------ main ------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    w = TTSStudio()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
