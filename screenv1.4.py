import os
import time
import threading
from dataclasses import dataclass, field

import cv2
import mss
import numpy as np
import ffmpeg

# Optional audio
try:
    import soundcard as sc
    import soundfile as sf
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False
    print("[!] soundcard/soundfile not available. Audio disabled.")

import tkinter as tk
from tkinter import ttk

# ================== CONFIG ==================

MONITOR_INDEX = 1      # 1 = primary monitor
TARGET_FPS = 60

LIVE_WINDOW = "Monitor Live View"

BASE_VIDEO_FILE = "monitor_video.mp4"
BASE_AUDIO_FILE = "monitor_audio.wav"
BASE_FINAL_FILE = "monitor_with_audio.mp4"

AUDIO_SAMPLE_RATE = 44100
AUDIO_BLOCKSIZE = 2048

ROTATION_PRESETS = [deg for deg in range(0, 360, 30)]  # 0,30,...,330

MODE_NAMES = [
    "Just Live",
    "Video only",
    "Audio only",
    "Audio + Video",
]

CAPTURE_NAMES = ["Full screen", "Region"]

COLOR_PRESETS = [
    "Custom",
    "Neutral",
    "Default warm",
    "Cold blue",
    "Warm pink/gold",
    "Dark mood",
    "Only black",
    "Black & white",
    "Only white",
]

# ================== HELPERS ==================


def unique_filename(base_name: str) -> str:
    """If file exists, create filename_1.ext, filename_2.ext, etc."""
    if not os.path.exists(base_name):
        return base_name
    name, ext = os.path.splitext(base_name)
    i = 1
    while True:
        candidate = f"{name}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def apply_color_shift(frame, hue_shift, sat_mult, val_mult, show_black):
    if show_black:
        return np.zeros_like(frame)

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    h, s, v = cv2.split(hsv)

    h = (h + hue_shift) % 180
    s = np.clip(s * sat_mult, 0, 255)
    v = np.clip(v * val_mult, 0, 255)

    hsv = cv2.merge([h, s, v])
    hsv = np.clip(hsv, 0, 255).astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def apply_rotation(frame, angle_deg):
    angle_deg = angle_deg % 360
    if angle_deg == 0:
        return frame
    h, w = frame.shape[:2]
    center = (w // 2, h // 2)
    m = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    return cv2.warpAffine(frame, m, (w, h), borderMode=cv2.BORDER_REPLICATE)


def find_loopback_device():
    mics = sc.all_microphones(include_loopback=True)
    loopbacks = [m for m in mics if m.isloopback]
    if not loopbacks:
        print("[!] No loopback devices found.")
        return None

    default_speaker = sc.default_speaker()
    base_name = default_speaker.name.split("(")[0].strip()

    for m in loopbacks:
        if base_name and base_name in m.name:
            print("[🎧] Using loopback matching default speaker:", m.name)
            return m

    print("[🎧] Using first available loopback device:", loopbacks[0].name)
    return loopbacks[0]


def save_audio(frames_container, audio_path, samplerate):
    frames = frames_container.get("frames", [])
    if not frames:
        print("[!] No audio frames captured, not saving.")
        return False
    audio = np.concatenate(frames, axis=0)
    sf.write(audio_path, audio, samplerate)
    print("[+] Audio saved to", audio_path)
    return True


def audio_record_thread(stop_event, frames_container, device, samplerate, blocksize):
    print("[🎙] Audio recording started.")
    frames = []
    try:
        with device.recorder(samplerate=samplerate, blocksize=blocksize) as rec:
            while not stop_event.is_set():
                data = rec.record(numframes=blocksize)
                frames.append(data)
    except Exception as e:  # noqa: BLE001
        print("[!] Audio error:", e)
    frames_container["frames"] = frames
    print("[🎙] Audio recording stopped.")


def merge_audio_video(video_path, audio_path, base_output):
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print("[!] Missing video or audio; skipping merge.")
        return
    out_path = unique_filename(base_output)
    print(f"[🔗] Merging into {out_path}")
    (
        ffmpeg
        .input(video_path)
        .input(audio_path)
        .output(out_path, vcodec="libx264", acodec="aac")
        .overwrite_output()
        .run()
    )
    print("[+] Merge complete:", out_path)


# ================== SHARED STATE ==================

@dataclass
class SharedState:
    # from GUI
    mode_index: int = 0              # 0..3
    capture_index: int = 0           # 0 full, 1 region
    rot_preset_index: int = 0        # 0..11
    rot_custom: float = 0.0
    use_custom_rot: bool = False

    color_preset_index: int = 2      # default warm
    hue: int = 40
    sat: float = 1.15
    val: float = 1.02
    show_black: bool = False

    # recording commands from GUI
    start_record_request: bool = False
    stop_record_request: bool = False
    select_region_request: bool = False
    exit_request: bool = False

    # capture region
    roi_rect: dict | None = None

    # recording status (set by capture thread)
    is_recording: bool = False
    recording_mode_active: int = 0
    capture_mode_active: int = 0

    # paths (for status label)
    current_video_path: str | None = None
    current_audio_path: str | None = None

    # internal lock
    lock: threading.Lock = field(default_factory=threading.Lock)


# ================== GUI (Tkinter) ==================

class ControlWindow:
    def __init__(self, state: SharedState):
        self.state = state
        self.root = tk.Tk()
        self.root.title("Monitor Control Panel")

        # Tk variables
        self.mode_var = tk.StringVar(value=MODE_NAMES[state.mode_index])
        self.capture_var = tk.StringVar(value=CAPTURE_NAMES[state.capture_index])

        self.rot_preset_var = tk.StringVar(value="Preset: 0°")
        self.rot_mode_var = tk.StringVar(value="Preset")  # "Preset" or "Custom"
        self.rot_custom_var = tk.StringVar(value="0")

        self.color_preset_var = tk.StringVar(value=COLOR_PRESETS[state.color_preset_index])

        self.hue_var = tk.DoubleVar(value=state.hue)
        self.sat_var = tk.DoubleVar(value=state.sat)
        self.val_var = tk.DoubleVar(value=state.val)
        self.black_var = tk.BooleanVar(value=state.show_black)

        self.status_var = tk.StringVar(value="Status: Live only")
        self.file_var = tk.StringVar(value="File: -")

        self._build()

        # periodic update of status label from state
        self._poll_status()

    # ---- building layout ----

    def _build(self):
        pad = {'padx': 5, 'pady': 2}

        # Mode & capture
        frm_top = ttk.Frame(self.root)
        frm_top.pack(fill="x", **pad)

        ttk.Label(frm_top, text="Mode:").grid(row=0, column=0, sticky="w")
        ttk.OptionMenu(frm_top, self.mode_var, self.mode_var.get(), *MODE_NAMES,
                       command=self.on_mode_change).grid(row=0, column=1, sticky="ew")

        ttk.Label(frm_top, text="Capture:").grid(row=1, column=0, sticky="w")
        ttk.OptionMenu(frm_top, self.capture_var, self.capture_var.get(), *CAPTURE_NAMES,
                       command=self.on_capture_change).grid(row=1, column=1, sticky="ew")

        # Rotation controls
        frm_rot = ttk.LabelFrame(self.root, text="Rotation")
        frm_rot.pack(fill="x", **pad)

        ttk.Label(frm_rot, text="Mode:").grid(row=0, column=0, sticky="w")
        ttk.OptionMenu(frm_rot, self.rot_mode_var, self.rot_mode_var.get(),
                       "Preset", "Custom", command=self.on_rot_mode_change
                       ).grid(row=0, column=1, sticky="ew")

        ttk.Label(frm_rot, text="Preset:").grid(row=1, column=0, sticky="w")
        preset_labels = [f"{deg}°" for deg in ROTATION_PRESETS]
        ttk.OptionMenu(frm_rot, self.rot_preset_var, self.rot_preset_var.get(),
                       *["Preset: " + lbl for lbl in preset_labels],
                       command=self.on_rot_preset_change
                       ).grid(row=1, column=1, sticky="ew")

        ttk.Label(frm_rot, text="Custom (deg):").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm_rot, textvariable=self.rot_custom_var, width=8).grid(row=2, column=1, sticky="w")

        # Color preset
        frm_color = ttk.LabelFrame(self.root, text="Color preset")
        frm_color.pack(fill="x", **pad)

        ttk.Label(frm_color, text="Preset:").grid(row=0, column=0, sticky="w")
        ttk.OptionMenu(frm_color, self.color_preset_var, self.color_preset_var.get(),
                       *COLOR_PRESETS, command=self.on_color_preset_change
                       ).grid(row=0, column=1, sticky="ew")

        # HSV sliders
        frm_hsv = ttk.LabelFrame(self.root, text="HSV fine tune")
        frm_hsv.pack(fill="x", **pad)

        ttk.Label(frm_hsv, text="Hue (0–179)").grid(row=0, column=0, sticky="w")
        ttk.Scale(frm_hsv, from_=0, to=179, variable=self.hue_var,
                  orient="horizontal", command=lambda e: self.on_hsv_change()
                  ).grid(row=0, column=1, sticky="ew")

        ttk.Label(frm_hsv, text="Sat x").grid(row=1, column=0, sticky="w")
        ttk.Scale(frm_hsv, from_=0.0, to=3.0, variable=self.sat_var,
                  orient="horizontal", command=lambda e: self.on_hsv_change()
                  ).grid(row=1, column=1, sticky="ew")

        ttk.Label(frm_hsv, text="Val x").grid(row=2, column=0, sticky="w")
        ttk.Scale(frm_hsv, from_=0.0, to=3.0, variable=self.val_var,
                  orient="horizontal", command=lambda e: self.on_hsv_change()
                  ).grid(row=2, column=1, sticky="ew")

        ttk.Checkbutton(frm_hsv, text="Show only black",
                        variable=self.black_var,
                        command=self.on_black_change).grid(row=3, column=0, columnspan=2, sticky="w")

        # Buttons
        frm_btn = ttk.Frame(self.root)
        frm_btn.pack(fill="x", **pad)

        ttk.Button(frm_btn, text="Select region",
                   command=self.on_select_region).grid(row=0, column=0, sticky="ew", **pad)
        ttk.Button(frm_btn, text="Start recording",
                   command=self.on_start).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm_btn, text="Stop recording",
                   command=self.on_stop).grid(row=0, column=2, sticky="ew", **pad)

        # Status labels
        frm_status = ttk.Frame(self.root)
        frm_status.pack(fill="x", **pad)

        ttk.Label(frm_status, textvariable=self.status_var).pack(anchor="w")
        ttk.Label(frm_status, textvariable=self.file_var).pack(anchor="w")

        # When window closed
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- callbacks: update SharedState ----

    def _with_lock(self, fn):
        with self.state.lock:
            fn()

    def on_mode_change(self, *_):
        idx = MODE_NAMES.index(self.mode_var.get())
        self._with_lock(lambda: setattr(self.state, "mode_index", idx))

    def on_capture_change(self, *_):
        idx = CAPTURE_NAMES.index(self.capture_var.get())
        self._with_lock(lambda: setattr(self.state, "capture_index", idx))

    def on_rot_mode_change(self, *_):
        mode = self.rot_mode_var.get()
        use_custom = (mode == "Custom")
        self._with_lock(lambda: setattr(self.state, "use_custom_rot", use_custom))

    def on_rot_preset_change(self, *_):
        text = self.rot_preset_var.get()  # like "Preset: 90°"
        try:
            deg = int(text.split(":")[1].replace("°", "").strip())
        except Exception:
            deg = 0
        idx = ROTATION_PRESETS.index(deg)
        def update():
            self.state.rot_preset_index = idx
            if not self.state.use_custom_rot:
                # keep custom = preset for convenience
                self.state.rot_custom = float(deg)
                self.rot_custom_var.set(str(deg))
        self._with_lock(update)

    def on_color_preset_change(self, *_):
        name = self.color_preset_var.get()
        idx = COLOR_PRESETS.index(name)

        def apply():
            self.state.color_preset_index = idx

            # Apply preset to HSV/black; 0 = Custom, others modify
            if idx == 0:
                return
            if idx == 1:       # Neutral
                h, s, v, b = 0, 1.0, 1.0, False
            elif idx == 2:     # Default warm
                h, s, v, b = 40, 1.15, 1.02, False
            elif idx == 3:     # Cold blue
                h, s, v, b = 100, 1.10, 0.95, False
            elif idx == 4:     # Warm pink/gold
                h, s, v, b = 150, 1.20, 1.05, False
            elif idx == 5:     # Dark mood
                h, s, v, b = 0, 0.80, 0.70, False
            elif idx == 6:     # Only black
                h, s, v, b = 0, 1.0, 1.0, True
            elif idx == 7:     # B&W
                h, s, v, b = 0, 0.0, 1.0, False
            elif idx == 8:     # Only white
                h, s, v, b = 0, 0.0, 3.0, False
            else:
                return

            self.state.hue = h
            self.state.sat = s
            self.state.val = v
            self.state.show_black = b

            # Sync sliders
            self.hue_var.set(h)
            self.sat_var.set(s)
            self.val_var.set(v)
            self.black_var.set(b)

        self._with_lock(apply)

    def on_hsv_change(self):
        def update():
            self.state.hue = int(self.hue_var.get())
            self.state.sat = float(self.sat_var.get())
            self.state.val = float(self.val_var.get())
        self._with_lock(update)

    def on_black_change(self):
        self._with_lock(lambda: setattr(self.state, "show_black", bool(self.black_var.get())))

    def on_select_region(self):
        self._with_lock(lambda: setattr(self.state, "select_region_request", True))

    def on_start(self):
        self._with_lock(lambda: setattr(self.state, "start_record_request", True))

    def on_stop(self):
        self._with_lock(lambda: setattr(self.state, "stop_record_request", True))

    def on_close(self):
        self._with_lock(lambda: setattr(self.state, "exit_request", True))
        self.root.destroy()

    # ---- status polling ----

    def _poll_status(self):
        with self.state.lock:
            if self.state.is_recording:
                mode_name = MODE_NAMES[self.state.recording_mode_active]
                self.status_var.set(f"Status: RECORDING ({mode_name})")
            else:
                self.status_var.set("Status: Live only")

            v = self.state.current_video_path or "-"
            a = self.state.current_audio_path or "-"
            self.file_var.set(f"Video: {v} | Audio: {a}")

        # poll again
        if self.root.winfo_exists():
            self.root.after(250, self._poll_status)

    def run(self):
        self.root.mainloop()


# ================== CAPTURE THREAD ==================

def select_region_cv(sct, base_mon):
    print("[🖼] Region selection: drag + ENTER, ESC to cancel.")
    shot = sct.grab(base_mon)
    frame = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)

    cv2.namedWindow("Select Region", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Select Region", 800, 450)
    roi = cv2.selectROI("Select Region", frame, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("Select Region")

    x, y, w, h = roi
    if w == 0 or h == 0:
        print("[ℹ] No region selected.")
        return None

    rect = {
        "top": base_mon["top"] + int(y),
        "left": base_mon["left"] + int(x),
        "width": int(w),
        "height": int(h),
    }
    print("[✔] Region:", rect)
    return rect


def capture_loop(state: SharedState):
    with mss.mss() as sct:
        base_mon = sct.monitors[MONITOR_INDEX]
        roi_rect = None

        cv2.namedWindow(LIVE_WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(LIVE_WINDOW, 1280, 720)

        # recording stuff
        video_writer = None
        audio_thread = None
        audio_stop_event = None
        audio_frames = {"frames": []}
        video_path = None
        audio_path = None

        fps = 0.0
        prev_time = time.perf_counter()
        frame_time = 1.0 / TARGET_FPS

        try:
            while True:
                # --- read state + handle commands ---
                with state.lock:
                    if state.exit_request:
                        break

                    # selection request
                    sel_req = state.select_region_request
                    if sel_req:
                        state.select_region_request = False

                    start_req = state.start_record_request
                    if start_req:
                        state.start_record_request = False

                    stop_req = state.stop_record_request
                    if stop_req:
                        state.stop_record_request = False

                    mode_index = state.mode_index
                    capture_index = state.capture_index
                    rot_preset_index = state.rot_preset_index
                    rot_custom = state.rot_custom
                    use_custom_rot = state.use_custom_rot
                    hue = state.hue
                    sat = state.sat
                    val = state.val
                    show_black = state.show_black

                # region selection
                if sel_req and not state.is_recording:
                    new_roi = select_region_cv(sct, base_mon)
                    with state.lock:
                        state.roi_rect = new_roi
                    roi_rect = new_roi

                # pick capture rect
                with state.lock:
                    rect = state.roi_rect if (capture_index == 1 and state.roi_rect) else base_mon

                # start recording
                if start_req and not state.is_recording and mode_index != 0:
                    # prepare video
                    if mode_index in (1, 3):
                        video_path = unique_filename(BASE_VIDEO_FILE)
                        print("[📹] Recording video to:", video_path)
                        state.current_video_path = video_path
                    else:
                        video_path = None
                        state.current_video_path = None

                    # prepare audio
                    if mode_index in (2, 3) and HAS_AUDIO:
                        loopback = find_loopback_device()
                        if loopback is None:
                            print("[!] No loopback; audio disabled for this run.")
                            if mode_index == 2:
                                mode_index = 0  # cancel
                        else:
                            audio_path = unique_filename(BASE_AUDIO_FILE)
                            print("[🎧] Recording audio to:", audio_path)
                            state.current_audio_path = audio_path
                            audio_stop_event = threading.Event()
                            audio_frames = {"frames": []}
                            audio_thread = threading.Thread(
                                target=audio_record_thread,
                                args=(audio_stop_event, audio_frames, loopback,
                                      AUDIO_SAMPLE_RATE, AUDIO_BLOCKSIZE),
                                daemon=True
                            )
                            audio_thread.start()
                    else:
                        audio_path = None
                        state.current_audio_path = None

                    if mode_index != 0 and video_path:
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        # frame size will be defined after first frame
                        video_writer = None  # init on first frame
                    with state.lock:
                        state.is_recording = (mode_index in (1, 2, 3))
                        state.recording_mode_active = mode_index
                        state.capture_mode_active = capture_index

                # stop recording
                if stop_req and state.is_recording:
                    print("[⏹] Stopping recording.")
                    # stop video
                    if video_writer is not None:
                        video_writer.release()
                        video_writer = None
                    # stop audio
                    if audio_thread is not None and audio_stop_event is not None:
                        audio_stop_event.set()
                        audio_thread.join()
                        if audio_path:
                            if not save_audio(audio_frames, audio_path, AUDIO_SAMPLE_RATE):
                                audio_path = None

                    # merge if needed
                    with state.lock:
                        mode_active = state.recording_mode_active
                    if mode_active == 3 and video_path and audio_path:
                        merge_audio_video(video_path, audio_path, BASE_FINAL_FILE)
                    elif mode_active == 1 and video_path:
                        print("[ℹ] Video saved to", video_path)
                    elif mode_active == 2 and audio_path:
                        print("[ℹ] Audio saved to", audio_path)

                    video_path = None
                    audio_path = None
                    audio_thread = None
                    audio_stop_event = None
                    audio_frames = {"frames": []}
                    with state.lock:
                        state.is_recording = False
                        state.current_video_path = None
                        state.current_audio_path = None

                # --- capture frame ---
                shot = sct.grab(rect)
                frame = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)

                # color + rotation
                filtered = apply_color_shift(frame, hue, sat, val, show_black)
                if use_custom_rot:
                    try:
                        with state.lock:
                            # update custom from text box (string) once in a while
                            rot_custom = float(state.rot_custom)
                    except Exception:
                        rot_custom = 0.0
                    angle = rot_custom
                else:
                    angle = ROTATION_PRESETS[rot_preset_index]

                filtered = apply_rotation(filtered, angle)

                # FPS overlay
                now = time.perf_counter()
                dt = now - prev_time
                prev_time = now
                fps = fps * 0.9 + (1.0 / dt) * 0.1 if fps > 0 else (1.0 / dt)
                cv2.putText(filtered, f"{fps:.1f} FPS", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

                # show live
                cv2.imshow(LIVE_WINDOW, filtered)

                # video write
                with state.lock:
                    rec_active = state.is_recording
                    mode_active = state.recording_mode_active

                if rec_active and mode_active in (1, 3) and video_path:
                    if video_writer is None:
                        h, w = filtered.shape[:2]
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        video_writer = cv2.VideoWriter(video_path, fourcc, TARGET_FPS, (w, h))
                        print("[📹] Video writer started.")
                    video_writer.write(filtered)

                # keyboard
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC
                    with state.lock:
                        state.exit_request = True
                    break

                # fps pacing
                elapsed = time.perf_counter() - now
                if elapsed < frame_time:
                    time.sleep(frame_time - elapsed)

        finally:
            cv2.destroyAllWindows()
            # make sure to stop recording if still on
            with state.lock:
                still_recording = state.is_recording
            if still_recording:
                print("[⏹] Stopping recording on exit.")
                if video_writer is not None:
                    video_writer.release()
                if audio_thread is not None and audio_stop_event is not None:
                    audio_stop_event.set()
                    audio_thread.join()
                    if audio_path:
                        save_audio(audio_frames, audio_path, AUDIO_SAMPLE_RATE)


# ================== MAIN ==================

def main():
    state = SharedState()

    # GUI in main thread, capture in background
    t = threading.Thread(target=capture_loop, args=(state,), daemon=True)
    t.start()

    gui = ControlWindow(state)
    gui.run()

    # when GUI closes, wait for capture thread
    t.join()
    print("[✔] Exited cleanly.")


if __name__ == "__main__":
    main()
