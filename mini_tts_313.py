import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading
import asyncio
import tempfile
import os

# --- Optional offline engine (pyttsx3). May fail on Win+Py3.13 due to pywin32 ---
ENGINE_OFFLINE = None
try:
    import pyttsx3
    try:
        ENGINE_OFFLINE = pyttsx3.init('sapi5')  # Windows SAPI5 (best if available)
    except Exception:
        # Try default driver (mac/Linux or other)
        try:
            ENGINE_OFFLINE = pyttsx3.init()
        except Exception:
            ENGINE_OFFLINE = None
except Exception:
    ENGINE_OFFLINE = None

# --- Online engine (edge-tts) + player (playsound) ---
EDGE_OK = False
PLAYSOUND_OK = False
try:
    import edge_tts
    EDGE_OK = True
except Exception:
    EDGE_OK = False

try:
    from playsound import playsound
    PLAYSOUND_OK = True
except Exception:
    PLAYSOUND_OK = False


def list_offline_voices(engine):
    if not engine:
        return []
    try:
        out = []
        for v in engine.getProperty("voices") or []:
            name = getattr(v, "name", None) or "Voice"
            vid = getattr(v, "id", None)
            out.append((name, vid))
        return out
    except Exception:
        return []


class MiniTTS(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mini TTS (works with Python 3.13)")
        self.geometry("660x420")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- Text box
        self.txt = tk.Text(self, wrap="word", height=12)
        self.txt.pack(fill="both", expand=True, padx=10, pady=(10, 6))

        # --- Controls row
        controls = ttk.Frame(self); controls.pack(fill="x", padx=10, pady=6)

        ttk.Label(controls, text="Voice:").grid(row=0, column=0, sticky="w")
        self.voice_var = tk.StringVar()
        self.voice_combo = ttk.Combobox(controls, textvariable=self.voice_var, state="readonly", width=32)
        self.voice_combo.grid(row=0, column=1, sticky="w", padx=(6, 18))

        ttk.Label(controls, text="Rate:").grid(row=0, column=2, sticky="e")
        self.rate = tk.IntVar(value=180)
        self.rate_scale = ttk.Scale(controls, from_=80, to=300, orient="horizontal",
                                    command=lambda v: self.rate.set(int(float(v))))
        self.rate_scale.set(180)
        self.rate_scale.grid(row=0, column=3, sticky="we", padx=(6, 18))

        ttk.Label(controls, text="Volume:").grid(row=0, column=4, sticky="e")
        self.vol = tk.DoubleVar(value=0.9)
        self.vol_scale = ttk.Scale(controls, from_=0, to=1, orient="horizontal",
                                   command=lambda v: self.vol.set(float(v)))
        self.vol_scale.set(0.9)
        self.vol_scale.grid(row=0, column=5, sticky="we", padx=(6, 0))

        controls.columnconfigure(3, weight=1)
        controls.columnconfigure(5, weight=1)

        # --- Buttons row
        btns = ttk.Frame(self); btns.pack(fill="x", padx=10, pady=(0, 10))
        self.btn_speak = ttk.Button(btns, text="▶ Speak", command=self.speak)
        self.btn_stop  = ttk.Button(btns, text="■ Stop", command=self.stop)
        self.btn_save  = ttk.Button(btns, text="Save Text…", command=self.save_text)
        self.btn_load  = ttk.Button(btns, text="Load Text…", command=self.load_text)
        self.btn_speak.pack(side="left")
        self.btn_stop.pack(side="left", padx=(6, 0))
        self.btn_save.pack(side="right")
        self.btn_load.pack(side="right", padx=(0, 6))

        # State
        self._stop_flag = False
        self._speak_thread = None

        # Populate voices (offline first, then a few online names)
        self.populate_voices()

    # ---------- Voices ----------
    def populate_voices(self):
        items = []
        self.voice_ids = []

        # Offline voices if available
        if ENGINE_OFFLINE:
            for name, vid in list_offline_voices(ENGINE_OFFLINE):
                items.append(f"(Offline) {name}")
                self.voice_ids.append(("offline", vid))

        # Online voice options if available
        if EDGE_OK:
            online_defaults = [
                ("(Online) en-US-AriaNeural", "en-US-AriaNeural"),
                ("(Online) en-US-GuyNeural",  "en-US-GuyNeural"),
                ("(Online) es-ES-ElviraNeural","es-ES-ElviraNeural"),
            ]
            for disp, vid in online_defaults:
                items.append(disp)
                self.voice_ids.append(("online", vid))

        if not items:
            items = ["(No TTS engines available)"]
            self.voice_ids = [("none", None)]

        self.voice_combo["values"] = items
        self.voice_combo.current(0)

    # ---------- Speak / Stop ----------
    def speak(self):
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Mini TTS", "Type or paste some text first.")
            return

        if not self.voice_ids or self.voice_ids[0][0] == "none":
            messagebox.showerror(
                "Mini TTS",
                "No TTS engine available.\n\nInstall either:\n"
                "  pip install pyttsx3   (offline)\n"
                "  pip install edge-tts playsound==1.2.2  (online)\n"
            )
            return

        # Stop any previous run
        self._stop_flag = False

        # Background thread to keep UI responsive
        if self._speak_thread and self._speak_thread.is_alive():
            return
        self._speak_thread = threading.Thread(target=self._speak_worker, args=(text,), daemon=True)
        self._speak_thread.start()

    def stop(self):
        self._stop_flag = True
        try:
            if ENGINE_OFFLINE:
                ENGINE_OFFLINE.stop()
        except Exception:
            pass

    def _speak_worker(self, text):
        kind, vid = self.voice_ids[self.voice_combo.current()]
        rate = int(self.rate.get())
        vol  = float(self.vol.get())

        if kind == "offline" and ENGINE_OFFLINE:
            try:
                if vid:
                    ENGINE_OFFLINE.setProperty("voice", vid)
                ENGINE_OFFLINE.setProperty("rate", rate)
                ENGINE_OFFLINE.setProperty("volume", vol)
                ENGINE_OFFLINE.stop()
                ENGINE_OFFLINE.say(text)
                ENGINE_OFFLINE.runAndWait()  # blocking until done
            except Exception as e:
                # On Py3.13 this may fail; fall back to online if available
                if EDGE_OK and PLAYSOUND_OK:
                    self._edge_tts_play(text, voice="en-US-AriaNeural", rate=rate, vol=vol)
                else:
                    self._show_err(f"Offline TTS failed: {e}")
        elif kind == "online" and EDGE_OK and PLAYSOUND_OK:
            self._edge_tts_play(text, voice=vid, rate=rate, vol=vol)
        else:
            self._show_err("No working TTS engine. Install pyttsx3 or edge-tts + playsound.")

    # ---------- Online path: render to MP3, then play ----------
    def _edge_tts_play(self, text, voice="en-US-AriaNeural", rate=180, vol=0.9):
        # Map sliders to edge-tts strings
        rate_pct = int(rate - 180)         # 180 ~ neutral baseline
        vol_pct  = int(vol * 100 - 100)    # 0.9 -> -10%
        rate_str = f"{rate_pct:+d}%"
        vol_str  = f"{vol_pct:+d}%"

        async def _render_to_file(mp3_path):
            communicate = edge_tts.Communicate(text or " ", voice=voice, rate=rate_str, volume=vol_str)
            with open(mp3_path, "wb") as f:
                async for chunk in communicate.stream():
                    if self._stop_flag:
                        return
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])

        # Render MP3 then play it
        try:
            with tempfile.TemporaryDirectory() as td:
                out_mp3 = os.path.join(td, "tts.mp3")
                # Run the async render
                try:
                    asyncio.run(_render_to_file(out_mp3))
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(_render_to_file(out_mp3))
                    loop.close()

                if not self._stop_flag:
                    # Play synchronously; playsound blocks until finished
                    playsound(out_mp3)
        except Exception as e:
            self._show_err(f"Online TTS playback failed: {e}")

    # ---------- File ops ----------
    def save_text(self):
        fn = filedialog.asksaveasfilename(defaultextension=".txt",
                                          filetypes=[("Text files","*.txt"),("All files","*.*")],
                                          initialfile="text.txt")
        if not fn: return
        try:
            Path(fn).write_text(self.txt.get("1.0", "end"), encoding="utf-8")
        except Exception as e:
            self._show_err(f"Could not save file:\n{e}")

    def load_text(self):
        fn = filedialog.askopenfilename(filetypes=[("Text files","*.txt *.md"),("All files","*.*")])
        if not fn: return
        try:
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", Path(fn).read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            self._show_err(f"Could not load file:\n{e}")

    # ---------- Utils ----------
    def _show_err(self, msg):
        self.after(0, lambda: messagebox.showerror("Mini TTS", msg))

    def on_close(self):
        self._stop_flag = True
        try:
            if ENGINE_OFFLINE:
                ENGINE_OFFLINE.stop()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = MiniTTS()
    app.mainloop()
