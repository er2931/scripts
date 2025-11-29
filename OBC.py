# discord_bit_control_clock.py
#
# Single script that:
#   - Opens Discord in Chrome via Selenium
#   - Shows a PyQt6 UI listing members + presence status:
#       Online / Idle / Dnd / Mobile / Offline
#   - Lets you double-click a member to SELECT them
#   - Shows that member's Discord avatar or full profile card
#     on the RIGHT side of the window
#   - Feeds the selected user's bit field into a temporal
#     clock engine that controls mouse + keyboard (gaming/full modes).
#
# Hotkeys:
#   F5 → toggle clicks ON / OFF (master)
#   F6 → toggle between GAMING and FULL modes
#   F7 → pause / resume controller
#   F8 → cycle sensitivity profile [1..9]
#         1 = mouse only
#         ...
#         9 = full control (mouse + scroll + drag + strong keyboard + clicks)
#
# Failsafe: move mouse to TOP-LEFT corner to trigger pyautogui.FAILSAFE.

import sys
import time
import math
from dataclasses import dataclass
from typing import List, Tuple, Optional

import urllib.request
import os

import pyautogui
pyautogui.FAILSAFE = True  # move mouse to top-left to abort

# Optional keyboard hotkeys (F5/F6/F7/F8)
try:
    import keyboard  # for global hotkeys
    HAS_KEYBOARD_LIB = True
except ImportError:
    HAS_KEYBOARD_LIB = False
    print("WARNING: 'keyboard' library not found. "
          "Mode switching (F5/F6/F7/F8) will be disabled.")

# -------------------- PyQt / Selenium imports --------------------

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QListWidget,
    QGroupBox, QSpinBox, QMessageBox, QListWidgetItem,
    QDialog, QFormLayout, QDoubleSpinBox, QColorDialog
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options


# ==================== CONTROL + DISPLAY SETTINGS ====================

@dataclass
class ControlSettings:
    """
    Live-tuned intensity levels for IO:
      - mouse_level    : affects mouse movement & scroll intensity
      - click_level    : affects how easily clicks trigger
      - keyboard_level : affects how easily key presses / holds trigger
      - selected_color : color for selected user row in status list
      - guild_url      : stored guild/channel URL for auto-focus
    """
    mouse_level: float = 1.0
    click_level: float = 1.0
    keyboard_level: float = 1.0
    selected_color: str = "#fbbf24"  # amber
    guild_url: str = ""


# ==================== DISCORD STATUS EXTRACTION ====================

DEFAULT_WAIT_SECS = 30.0    # wait after opening Discord so it loads
DEFAULT_POLL_SECS = 5       # seconds between scans

STATUS_ORDER = ["online", "idle", "dnd", "mobile", "offline"]
STATUS_INDEX = {name: idx for idx, name in enumerate(STATUS_ORDER)}

# Status → color map for list items
STATUS_COLORS = {
    "online":  "#4ade80",  # green
    "idle":    "#facc15",  # yellow
    "dnd":     "#f97373",  # red
    "mobile":  "#38bdf8",  # cyan
    "offline": "#6b7280",  # gray
    "unknown": "#9CA3AF",  # muted gray
}


def _find_member_root(driver):
    """Try to locate the Discord 'Members' panel container."""
    try:
        roots = driver.find_elements(By.CSS_SELECTOR, '[aria-label="Members"]')
        roots = [r for r in roots if r.is_displayed()]
        return roots[0] if roots else None
    except Exception:
        return None


def _ensure_members_panel(driver):
    """
    Ensure the members panel is visible.
    1) If already visible, do nothing.
    2) Else try clicking any button with an aria-label mentioning 'Member'.
    3) Fallback to sending 'u' hotkey.
    """
    try:
        root = _find_member_root(driver)
        if root and root.is_displayed():
            return

        # Try clicking a button that opens the member list
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, '[aria-label]')
            for b in buttons:
                label = (b.get_attribute("aria-label") or "").lower()
                if "member" in label and b.is_displayed():
                    b.click()
                    time.sleep(0.8)
                    if _find_member_root(driver):
                        return
        except Exception:
            pass

        # Fallback: press 'u'
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys("u")
            time.sleep(0.8)
        except Exception:
            pass
    except Exception:
        pass


def _detect_status_and_stream(e) -> Tuple[str, bool]:
    """
    Try to detect presence status + whether the user is streaming,
    based on aria-labels and text content.
    Returns (status_name, streaming_flag).
    status_name is one of: 'online', 'idle', 'dnd', 'mobile', 'offline', 'unknown'.
    """
    blobs: List[str] = []

    try:
        aria = e.get_attribute("aria-label") or ""
        if aria:
            blobs.append(aria)
    except Exception:
        pass

    try:
        sub_with_label = e.find_elements(By.CSS_SELECTOR, "[aria-label]")
        for sub in sub_with_label:
            lab = sub.get_attribute("aria-label") or ""
            if lab:
                blobs.append(lab)
    except Exception:
        pass

    try:
        txt = e.text or ""
        if txt:
            blobs.append(txt)
    except Exception:
        pass

    blob = " | ".join(blobs).lower()
    streaming = False
    status = "unknown"

    # Streaming / transmitiendo / etc.
    if "streaming" in blob or "transmitiendo" in blob:
        streaming = True

    # Status detection (heuristic; adjust as needed for your locale)
    if ("do not disturb" in blob or "no molestar" in blob or "dnd" in blob):
        status = "dnd"
    elif "idle" in blob or "ausente" in blob:
        status = "idle"
    elif "offline" in blob or "desconectado" in blob:
        status = "offline"
    elif "mobile" in blob or "celular" in blob:
        status = "mobile"
    elif "online" in blob or "en línea" in blob or "en linea" in blob:
        status = "online"

    return status, streaming


def _extract_avatar_url(e) -> str:
    """
    Try to extract avatar image URL from the member list item element.
    Prefer <img> where 'alt' or class hints about avatar.
    """
    try:
        imgs = e.find_elements(By.TAG_NAME, "img")
        candidate = ""
        for img in imgs:
            src = img.get_attribute("src") or ""
            alt = (img.get_attribute("alt") or "").lower()
            cls = (img.get_attribute("class") or "").lower()
            if not src.startswith("http"):
                continue
            if "avatar" in alt or "avatar" in cls:
                return src
            if not candidate:
                candidate = src
        if candidate:
            return candidate
    except Exception:
        pass

    # Fallback: sometimes avatar is in a div with background-image style
    try:
        divs = e.find_elements(By.CSS_SELECTOR, "div")
        for d in divs:
            style = d.get_attribute("style") or ""
            if "background-image" in style and "url(" in style:
                start = style.find("url(")
                end = style.find(")", start + 4)
                if start != -1 and end != -1:
                    url = style[start + 4:end].strip('\'" ')
                    if url.startswith("http"):
                        return url
    except Exception:
        pass

    return ""


def collect_member_status_bits(driver) -> Tuple[List[Tuple[str, str, str, str]], int, bool]:
    """
    Scan the Members panel and collect:
      - rows: [(username, status_name, bit_string, avatar_url), ...]
      - total_members_scanned
      - any_streaming_flag

    bit_string is 5 bits in the order:
        [online, idle, dnd, mobile, offline]
    """
    rows: List[Tuple[str, str, str, str]] = []
    total_members = 0
    any_streaming = False

    if not driver:
        return rows, total_members, any_streaming

    try:
        _ensure_members_panel(driver)
        root = _find_member_root(driver)
        if not root:
            return rows, total_members, any_streaming

        items = root.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
    except Exception:
        return rows, total_members, any_streaming

    seen_names = set()

    for e in items:
        try:
            total_members += 1

            txt = (e.text or "").strip()
            if not txt:
                continue

            lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
            if not lines:
                continue

            name = lines[0]
            if not name:
                continue

            if name in seen_names:
                continue
            seen_names.add(name)

            status_name, streaming = _detect_status_and_stream(e)
            if streaming:
                any_streaming = True

            # Build 5-bit pattern
            bits = ["0"] * len(STATUS_ORDER)
            if status_name in STATUS_INDEX:
                bits[STATUS_INDEX[status_name]] = "1"
            bit_str = "".join(bits)

            avatar_url = _extract_avatar_url(e)

            rows.append((name, status_name, bit_str, avatar_url))
        except Exception:
            continue

    return rows, total_members, any_streaming


# ==================== CLOCK / CONTROLLER ENGINE ====================

@dataclass
class VariantProfile:
    amp: float
    freq: float
    phase: float
    nonlin: float
    feedback_gain: float


VARIANT_PROFILES: List[VariantProfile] = []
for i in range(60):
    VARIANT_PROFILES.append(
        VariantProfile(
            amp=0.5 + i / 120.0,
            freq=0.3 + (i % 10) * 0.07,
            phase=(i / 60.0) * math.tau,
            nonlin=0.2 + (i % 5) * 0.2,
            feedback_gain=0.1 + (i / 60.0) * 0.4
        )
    )


@dataclass
class ClockState:
    t0: float
    internal_time: float
    last_state: Optional[list]


@dataclass
class ClockParams:
    time_rate: float = 1.0
    global_amp: float = 1.0
    bias: float = 0.0
    smoothness: float = 0.1  # how fast params adapt


def generator_step(
    t: float,
    variant: VariantProfile,
    state_prev,
    params: ClockParams
) -> list[float]:
    x = params.global_amp * variant.amp * math.sin(variant.freq * t + variant.phase)
    y = params.global_amp * math.cos(variant.freq * t * 0.7 + variant.phase * 0.5)
    z = params.global_amp * math.tanh(variant.nonlin * math.sin(t))
    w = params.global_amp * math.sin(variant.freq * t) * math.cos(variant.freq * t * 0.3)

    if state_prev is not None:
        fx = variant.feedback_gain * state_prev[0]
        fy = variant.feedback_gain * state_prev[1]
        fz = variant.feedback_gain * state_prev[2]
        fw = variant.feedback_gain * state_prev[3]
        x += fx
        y += fy
        z += fz
        w += fw

    return [x, y, z, w]


def normalize_vector(vec, lo=-3.0, hi=3.0):
    out = []
    for v in vec:
        v_clamped = max(lo, min(hi, v))
        out.append((v_clamped - lo) / (hi - lo))
    return out


def update_clock_params(params: ClockParams, C_norm):
    while len(C_norm) < 4:
        C_norm.append(0.5)

    r1, r2, r3, r4 = C_norm[:4]

    target_time_rate = 0.5 + r1 * 1.5
    target_amp       = 0.2 + r2 * 1.8
    target_bias      = (r3 - 0.5) * 2.0
    target_smooth    = 0.05 + r4 * 0.45

    alpha = params.smoothness
    params.time_rate  = (1 - alpha) * params.time_rate + alpha * target_time_rate
    params.global_amp = (1 - alpha) * params.global_amp + alpha * target_amp
    params.bias       = (1 - alpha) * params.bias + alpha * target_bias
    params.smoothness = (1 - alpha) * params.smoothness + alpha * target_smooth

    return params


# ---------- Input Controller (mouse + keyboard) ----------

KEY_GROUPS = {
    "letters": list("abcdefghijklmnopqrstuvwxyz"),
    "numbers": list("0123456789"),
    "nav": ["up", "down", "left", "right", "home", "end", "pageup", "pagedown"],
    "modifiers": ["shift", "ctrl", "alt"],
    "control": ["enter", "esc", "backspace", "tab", "space"],
    "function": [f"f{i}" for i in range(1, 13)],
}

KEY_GROUP_ORDER = list(KEY_GROUPS.keys())
GAMING_KEYS = ["w", "a", "s", "d", "space", "shift", "ctrl"]


class InputController:
    """
    Manages mouse & keyboard actions in two modes:
    - 'gaming'  : constrained, focused, gentler
    - 'full'    : full feature mapping (scroll, drag, wide key set)

    Uses ControlSettings + enable flags to tune intensities / scope.
    """

    def __init__(self, settings: ControlSettings):
        self.dragging = False
        self.drag_button = "left"
        self.held_key = None
        self.settings = settings

        # Feature flags controlled by sensitivity profile + F5
        self.enable_mouse = True
        self.enable_clicks = True
        self.enable_scroll = True
        self.enable_drag = True
        self.enable_keyboard = True

        # Master click toggle (F5)
        self.master_click_enabled = True

    # --- threshold helper ---

    def _thresh(self, base: float, level: float, min_val: float = 0.05, max_val: float = 0.99) -> float:
        """
        Adjust a base threshold using level (0.1–2.0).
        level = 1.0 → base
        level > 1.0 → lower threshold (more likely to trigger)
        level < 1.0 → higher threshold (less likely)
        """
        adj = base - (level - 1.0) * 0.3
        adj = max(min_val, min(max_val, adj))
        return adj

    def _pick_full_key(self, g_val: float, k_val: float) -> Optional[str]:
        if not KEY_GROUP_ORDER:
            return None

        # Nonlinear key-group selection: bias towards extremes a bit
        g_val_nl = (g_val ** 1.5 + g_val * 0.3) / 1.3
        group_index = int(g_val_nl * len(KEY_GROUP_ORDER))
        if group_index >= len(KEY_GROUP_ORDER):
            group_index = len(KEY_GROUP_ORDER) - 1

        group_name = KEY_GROUP_ORDER[group_index]
        keys_in_group = KEY_GROUPS[group_name]
        if not keys_in_group:
            return None

        # Nonlinear key index selection
        k_val_nl = math.sqrt(k_val)
        key_index = int(k_val_nl * len(keys_in_group))
        if key_index >= len(keys_in_group):
            key_index = len(keys_in_group) - 1

        return keys_in_group[key_index]

    def _pick_gaming_key(self, selector: float) -> str:
        # Slight bias towards WASD vs others
        sel = (selector ** 2 + selector * 0.5) / 1.5
        idx = int(sel * len(GAMING_KEYS))
        if idx >= len(GAMING_KEYS):
            idx = len(GAMING_KEYS) - 1
        return GAMING_KEYS[idx]

    def apply(self, C_norm, mode: str):
        if mode == "gaming":
            self._apply_gaming(C_norm)
        else:
            self._apply_full(C_norm)

    def _apply_gaming(self, C_norm):
        """
        Gaming mode:
        - mouse movement constrained towards center region
        - simple left-clicks (if enabled)
        - keyboard limited to WASD/space/shift/ctrl (if enabled)
        - no scroll / drag chaos unless enabled by profile
        """
        while len(C_norm) < 6:
            C_norm.append(0.5)

        c0, c1, c2, c3, c4, c5 = C_norm[:6]

        # Mouse near center (0.25–0.75 region), with mouse_level
        if self.enable_mouse:
            screen_w, screen_h = pyautogui.size()
            ml = max(0.1, min(2.0, self.settings.mouse_level))
            span = 0.5 * (ml / 2.0)  # 0.25 at level=1, 0.5 at level=2, 0.125 at 0.5
            center = 0.5
            x_norm = center + (c0 - 0.5) * 2 * span
            y_norm = center + (c1 - 0.5) * 2 * span
            x_norm = max(0.0, min(1.0, x_norm))
            y_norm = max(0.0, min(1.0, y_norm))

            x = int(x_norm * screen_w)
            y = int(y_norm * screen_h)
            pyautogui.moveTo(x, y, duration=0.01)

        # Click threshold tuned by click_level
        if self.enable_clicks and self.master_click_enabled:
            base_click_thresh = 0.7  # lower than before to be more active
            click_thresh = self._thresh(base_click_thresh, self.settings.click_level)
            if c2 > click_thresh:
                print("[CLICK] gaming left")
                pyautogui.click(button="left")

        # Keyboard thresholds tuned by keyboard_level
        if self.enable_keyboard:
            kl = self.settings.keyboard_level
            hold_base = 0.8
            tap_base = 0.6
            hold_thresh = self._thresh(hold_base, kl)
            tap_thresh = self._thresh(tap_base, kl)

            key = self._pick_gaming_key(c3)

            # c4: intensity -> hold vs tap
            # c5: randomness / gating
            if c4 > hold_thresh and c5 > 0.3:
                # hold key
                if self.held_key is None:
                    pyautogui.keyDown(key)
                    self.held_key = key
                elif self.held_key != key:
                    pyautogui.keyUp(self.held_key)
                    pyautogui.keyDown(key)
                    self.held_key = key
            elif c4 > tap_thresh and c5 > 0.4:
                # short tap
                pyautogui.press(key)
                if self.held_key is not None:
                    pyautogui.keyUp(self.held_key)
                    self.held_key = None
            else:
                # release if held
                if self.held_key is not None:
                    pyautogui.keyUp(self.held_key)
                    self.held_key = None
        else:
            # ensure no stuck keys
            if self.held_key is not None:
                pyautogui.keyUp(self.held_key)
                self.held_key = None

        # Ensure no dragging in gaming mode (unless explicitly enabled)
        if self.dragging and not self.enable_drag:
            pyautogui.mouseUp(button=self.drag_button)
            self.dragging = False

    def _apply_full(self, C_norm):
        """
        Full mode:
        - full-screen mouse (if enabled)
        - scroll up/down (scaled by mouse_level, if enabled)
        - click & drag (left or right, scaled by click_level, if enabled)
        - wide keyboard groups + holds (scaled by keyboard_level, if enabled)
        """
        while len(C_norm) < 8:
            C_norm.append(0.5)

        c0, c1, c2, c3, c4, c5, c6, c7 = C_norm[:8]

        # Mouse position
        if self.enable_mouse:
            screen_w, screen_h = pyautogui.size()
            x = int(c0 * screen_w)
            y = int(c1 * screen_h)
            pyautogui.moveTo(x, y, duration=0.01)

        # Scroll scaled by mouse_level
        if self.enable_scroll:
            ml = max(0.1, min(2.0, self.settings.mouse_level))
            scroll_strength = (c2 - 0.5) * 20 * ml  # -20..+20 at ml=2
            if abs(scroll_strength) > 1.0:
                pyautogui.scroll(int(scroll_strength))

        # Click / drag behavior thresholds tuned by click_level
        cl = self.settings.click_level
        mode_val = c3
        fire_val = c4

        click_left_base = 0.7
        click_right_base = 0.55
        drag_start_base = 0.6
        drag_stop_base = 0.35

        click_left_thresh = self._thresh(click_left_base, cl)
        click_right_thresh = self._thresh(click_right_base, cl)
        drag_start_thresh = self._thresh(drag_start_base, cl)
        drag_stop_thresh = self._thresh(drag_stop_base, cl, min_val=0.05, max_val=0.8)

        if (self.enable_clicks or self.enable_drag):
            if mode_val < 0.33:
                # click mode
                if self.enable_clicks and self.master_click_enabled:
                    if fire_val > click_left_thresh:
                        print("[CLICK] full left")
                        pyautogui.click(button="left")
                    elif fire_val > click_right_thresh:
                        print("[CLICK] full right")
                        pyautogui.click(button="right")

                if self.dragging:
                    pyautogui.mouseUp(button=self.drag_button)
                    self.dragging = False

            elif mode_val < 0.66 and self.enable_drag:
                # drag with left
                if fire_val > drag_start_thresh and not self.dragging:
                    pyautogui.mouseDown(button="left")
                    self.dragging = True
                    self.drag_button = "left"
                elif fire_val < drag_stop_thresh and self.dragging and self.drag_button == "left":
                    pyautogui.mouseUp(button="left")
                    self.dragging = False
            elif self.enable_drag:
                # drag with right
                if fire_val > drag_start_thresh and not self.dragging:
                    pyautogui.mouseDown(button="right")
                    self.dragging = True
                    self.drag_button = "right"
                elif fire_val < drag_stop_thresh and self.dragging and self.drag_button == "right":
                    pyautogui.mouseUp(button="right")
                    self.dragging = False
        else:
            if self.dragging:
                pyautogui.mouseUp(self.drag_button)
                self.dragging = False

        # Keyboard thresholds tuned by keyboard_level
        if self.enable_keyboard:
            kl = self.settings.keyboard_level
            hold_base = 0.8
            tap_base = 0.5
            hold_thresh = self._thresh(hold_base, kl)
            tap_thresh = self._thresh(tap_base, kl)

            key = self._pick_full_key(c5, c6)

            if key is None:
                if self.held_key is not None and c7 < 0.4:
                    pyautogui.keyUp(self.held_key)
                    self.held_key = None
                return

            # mix c7 with a bit of c2 for gating → less linear
            gate = 0.7 * c7 + 0.3 * (0.5 + (c2 - 0.5) * 0.8)

            if gate > hold_thresh:
                # hold
                if self.held_key is None:
                    pyautogui.keyDown(key)
                    self.held_key = key
                elif self.held_key != key:
                    pyautogui.keyUp(self.held_key)
                    pyautogui.keyDown(key)
                    self.held_key = key
            elif gate > tap_thresh:
                # tap
                pyautogui.press(key)
                if self.held_key is not None:
                    pyautogui.keyUp(self.held_key)
                    self.held_key = None
            else:
                # release
                if self.held_key is not None:
                    pyautogui.keyUp(self.held_key)
                    self.held_key = None
        else:
            if self.held_key is not None:
                pyautogui.keyUp(self.held_key)
                self.held_key = None


# ---------- Temporal controller wrapped for Qt timer ----------

class TemporalControllerEngine:
    """
    Clock + generator + IO controller, stepped by a Qt timer.

    It takes a 5-bit string "10100" (online/idle/dnd/mobile/offline)
    plus user name/status, and blends those bits into C_norm so that
    the selected Discord user literally shapes the output.

    Also supports sensitivity profiles 1..9 via F8 and click toggle via F5.
    """

    def __init__(self, settings: ControlSettings):
        self.params = ClockParams()
        self.clock = ClockState(t0=time.time(), internal_time=0.0, last_state=None)
        self.io = InputController(settings)

        self.mode = "gaming"   # "gaming" or "full"
        self.paused = False
        self.last_toggle_clicks = 0.0
        self.last_toggle_mode = 0.0
        self.last_toggle_pause = 0.0
        self.last_toggle_profile = 0.0
        self.toggle_cooldown = 0.4  # seconds

        self.sensitivity_profile = 1  # 1..9
        self.settings = settings
        self._apply_profile()

        self.last_print_user = 0.0
        self.current_user_name: Optional[str] = None
        self.current_user_status: Optional[str] = None

    def _apply_profile(self):
        """
        Map sensitivity_profile 1..9 to settings + feature flags.
        1 = mouse only, 9 = full unlocked & intense.
        """
        p = self.sensitivity_profile
        s = self.settings
        io = self.io

        # defaults: everything on, neutral levels
        s.mouse_level = 1.0
        s.click_level = 1.0
        s.keyboard_level = 1.0
        io.enable_mouse = True
        io.enable_clicks = True
        io.enable_scroll = True
        io.enable_drag = True
        io.enable_keyboard = True

        if p == 1:
            # Mouse only, gentle
            s.mouse_level = 0.7
            s.click_level = 0.1
            s.keyboard_level = 0.1
            io.enable_mouse = True
            io.enable_clicks = False
            io.enable_scroll = False
            io.enable_drag = False
            io.enable_keyboard = False
        elif p == 2:
            # Mouse + rare clicks
            s.mouse_level = 0.9
            s.click_level = 0.6
            s.keyboard_level = 0.2
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = False
            io.enable_drag = False
            io.enable_keyboard = False
        elif p == 3:
            # Mouse + more clicks
            s.mouse_level = 1.0
            s.click_level = 1.0
            s.keyboard_level = 0.3
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = False
            io.enable_drag = False
            io.enable_keyboard = False
        elif p == 4:
            # Mouse + clicks + light scroll
            s.mouse_level = 1.0
            s.click_level = 1.0
            s.keyboard_level = 0.6
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = True
            io.enable_drag = False
            io.enable_keyboard = True  # light
        elif p == 5:
            # Balanced
            s.mouse_level = 1.0
            s.click_level = 1.0
            s.keyboard_level = 1.0
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = True
            io.enable_drag = False
            io.enable_keyboard = True
        elif p == 6:
            # More keyboard + clicks, still no drag
            s.mouse_level = 1.1
            s.click_level = 1.2
            s.keyboard_level = 1.3
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = True
            io.enable_drag = False
            io.enable_keyboard = True
        elif p == 7:
            # Add left drag
            s.mouse_level = 1.1
            s.click_level = 1.4
            s.keyboard_level = 1.4
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = True
            io.enable_drag = True
            io.enable_keyboard = True
        elif p == 8:
            # Drag + stronger keyboard
            s.mouse_level = 1.2
            s.click_level = 1.6
            s.keyboard_level = 1.6
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = True
            io.enable_drag = True
            io.enable_keyboard = True
        elif p == 9:
            # Full chaos unlocked
            s.mouse_level = 1.4
            s.click_level = 1.8
            s.keyboard_level = 1.8
            io.enable_mouse = True
            io.enable_clicks = True
            io.enable_scroll = True
            io.enable_drag = True
            io.enable_keyboard = True

        print(f"[PROFILE] Sensitivity profile set to {p} "
              f"(mouse={s.mouse_level:.2f}, click={s.click_level:.2f}, "
              f"keyboard={s.keyboard_level:.2f})")

    def _cycle_profile(self):
        self.sensitivity_profile += 1
        if self.sensitivity_profile > 9:
            self.sensitivity_profile = 1
        self._apply_profile()

    def step(self, bits_str: str, user_name: str, user_status: str):
        """
        One step of the controller; called at ~50Hz by a QTimer.
        bits_str: '10100'
        """
        now = time.time()

        # --- Hotkeys (if library available) ---
        if HAS_KEYBOARD_LIB:
            if keyboard.is_pressed("F5") and (now - self.last_toggle_clicks) > self.toggle_cooldown:
                self.last_toggle_clicks = now
                self.io.master_click_enabled = not self.io.master_click_enabled
                print(f"[CLICKS] Master clicks: {'ON' if self.io.master_click_enabled else 'OFF'}")

            if keyboard.is_pressed("F6") and (now - self.last_toggle_mode) > self.toggle_cooldown:
                self.mode = "full" if self.mode == "gaming" else "gaming"
                self.last_toggle_mode = now
                print(f"[MODE] Switched to: {self.mode.upper()}")

            if keyboard.is_pressed("F7") and (now - self.last_toggle_pause) > self.toggle_cooldown:
                self.paused = not self.paused
                self.last_toggle_pause = now
                print(f"[STATE] {'Paused' if self.paused else 'Resumed'} controller")

            if keyboard.is_pressed("F8") and (now - self.last_toggle_profile) > self.toggle_cooldown:
                self.last_toggle_profile = now
                self._cycle_profile()

        if self.paused:
            return

        if not user_name or not bits_str or len(bits_str) != 5:
            return

        t_real = now - self.clock.t0
        t_in_loop = t_real % 60.0
        second_index = int(t_in_loop)

        variant_profile = VARIANT_PROFILES[second_index]

        self.clock.internal_time += self.params.time_rate * 0.02  # ~50 steps/sec

        S = generator_step(
            self.clock.internal_time + self.params.bias,
            variant_profile,
            self.clock.last_state,
            self.params
        )

        x, y, z, w = S
        extended = [
            x,
            y,
            z,
            w,
            x + y,
            y + z,
            z + w,
            x - z,
        ]

        C_norm = normalize_vector(extended, lo=-3.0, hi=3.0)

        # Inject bit field into the first 5 components
        bits = [1.0 if c == "1" else 0.0 for c in bits_str]
        for i, b in enumerate(bits):
            if i < len(C_norm):
                C_norm[i] = 0.6 * C_norm[i] + 0.4 * b

        if user_name != self.current_user_name or user_status != self.current_user_status:
            self.current_user_name = user_name
            self.current_user_status = user_status

        if now - self.last_print_user > 1.0 and self.current_user_name:
            self.last_print_user = now
            print(f"[USER] {self.current_user_name} ({self.current_user_status}) "
                  f"bits={bits_str} | mode={self.mode} | "
                  f"profile={self.sensitivity_profile} | "
                  f"clicks={'ON' if self.io.master_click_enabled else 'OFF'}")

        self.io.apply(C_norm, self.mode)

        self.params = update_clock_params(self.params, C_norm)
        self.clock.last_state = S


# ==================== SETTINGS DIALOGS ====================

class GuildUrlDialog(QDialog):
    """
    Simple popup to edit the guild URL stored in ControlSettings.
    """

    def __init__(self, settings: ControlSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Guild URL")
        layout = QVBoxLayout(self)

        label = QLabel("Enter full Discord guild/channel URL:\n"
                       "Example: https://discord.com/channels/<guild_id>/<channel_id>")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.edit = QLineEdit(self.settings.guild_url)
        layout.addWidget(self.edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_ok = QPushButton("Save")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def accept(self):
        self.settings.guild_url = self.edit.text().strip()
        super().accept()


class SettingsDialog(QDialog):
    """
    Dialog to adjust ControlSettings (mouse / click / keyboard levels
    and selected-user display color, plus guild URL editor).
    """

    def __init__(self, settings: ControlSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Control Settings")
        self.setModal(True)

        form = QFormLayout(self)

        self.mouse_spin = QDoubleSpinBox()
        self.mouse_spin.setRange(0.1, 2.0)
        self.mouse_spin.setSingleStep(0.1)
        self.mouse_spin.setValue(self.settings.mouse_level)
        form.addRow("Mouse level:", self.mouse_spin)

        self.click_spin = QDoubleSpinBox()
        self.click_spin.setRange(0.1, 2.0)
        self.click_spin.setSingleStep(0.1)
        self.click_spin.setValue(self.settings.click_level)
        form.addRow("Click level:", self.click_spin)

        self.key_spin = QDoubleSpinBox()
        self.key_spin.setRange(0.1, 2.0)
        self.key_spin.setSingleStep(0.1)
        self.key_spin.setValue(self.settings.keyboard_level)
        form.addRow("Keyboard level:", self.key_spin)

        # Selected user color (for status list)
        color_row = QHBoxLayout()
        self.selected_color_preview = QLabel("   ")
        self.selected_color_preview.setFixedWidth(40)
        self._update_color_preview()
        color_btn = QPushButton("Change…")
        color_btn.clicked.connect(self._choose_color)
        color_row.addWidget(self.selected_color_preview)
        color_row.addWidget(color_btn)
        color_row.addStretch(1)
        form.addRow("Selected user color:", color_row)

        # Guild URL button
        guild_btn = QPushButton("Set Guild URL…")
        guild_btn.clicked.connect(self._edit_guild_url)
        form.addRow("Guild URL:", guild_btn)

        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        form.addRow(btn_close)

        # Connect signals
        self.mouse_spin.valueChanged.connect(self._on_mouse_changed)
        self.click_spin.valueChanged.connect(self._on_click_changed)
        self.key_spin.valueChanged.connect(self._on_key_changed)

    def _on_mouse_changed(self, val: float):
        self.settings.mouse_level = float(val)

    def _on_click_changed(self, val: float):
        self.settings.click_level = float(val)

    def _on_key_changed(self, val: float):
        self.settings.keyboard_level = float(val)

    def _update_color_preview(self):
        self.selected_color_preview.setStyleSheet(
            f"background-color: {self.settings.selected_color}; "
            "border: 1px solid #444; border-radius: 3px;"
        )

    def _choose_color(self):
        initial = QColor(self.settings.selected_color)
        color = QColorDialog.getColor(initial, self, "Select selected-user color")
        if color.isValid():
            self.settings.selected_color = color.name()
            self._update_color_preview()

    def _edit_guild_url(self):
        dlg = GuildUrlDialog(self.settings, self)
        dlg.exec()


# ==================== MAIN QT APP ====================

class StatusBitApp(QWidget):
    def __init__(self):
        super().__init__()

        self.driver: Optional[webdriver.Chrome] = None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_once)

        self.was_streaming = False

        # Control settings (shared with controller)
        self.settings = ControlSettings()

        # Status data
        self.selected_member_name: Optional[str] = None
        # (name, status, bits, avatar_url)
        self.current_rows: List[Tuple[str, str, str, str]] = []

        # Controller engine
        self.ctrl_engine = TemporalControllerEngine(self.settings)
        self.ctrl_timer = QTimer(self)
        self.ctrl_timer.timeout.connect(self._control_step)
        self.ctrl_timer.start(20)  # ~50 Hz

        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("Discord Bit-Control Clock")
        self.resize(1080, 640)

        # main root: left column (controls) + right column (avatar)
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(6)
        right = QVBoxLayout()
        right.setSpacing(6)

        # --- HEADER CONFIG (left) ---
        header = QGridLayout()
        header.setHorizontalSpacing(6)
        header.setVerticalSpacing(4)

        row = 0
        self.url_edit = QLineEdit("https://discord.com/app")
        header.addWidget(QLabel("Discord URL:"), row, 0)
        header.addWidget(self.url_edit, row, 1, 1, 3)
        row += 1

        self.user_data_edit = QLineEdit("")
        pick_user_btn = QPushButton("Browse…")
        pick_user_btn.clicked.connect(self._pick_user_dir)
        header.addWidget(QLabel("Chrome user-data dir:"), row, 0)
        header.addWidget(self.user_data_edit, row, 1, 1, 2)
        header.addWidget(pick_user_btn, row, 3)
        row += 1

        self.profile_edit = QLineEdit("Default")
        header.addWidget(QLabel("Chrome profile dir:"), row, 0)
        header.addWidget(self.profile_edit, row, 1, 1, 3)
        row += 1

        # Streaming trigger file
        self.stream_file_edit = QLineEdit("")
        pick_stream_btn = QPushButton("Browse…")
        pick_stream_btn.clicked.connect(self._pick_stream_file)
        header.addWidget(QLabel("Streaming trigger file:"), row, 0)
        header.addWidget(self.stream_file_edit, row, 1, 1, 2)
        header.addWidget(pick_stream_btn, row, 3)
        row += 1

        # Poll + start/stop
        row_box = QHBoxLayout()
        row_box.addWidget(QLabel("Poll (s):"))
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(2, 3600)
        self.poll_spin.setValue(DEFAULT_POLL_SECS)
        row_box.addWidget(self.poll_spin)
        row_box.addSpacing(12)

        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        row_box.addWidget(self.start_btn)
        row_box.addWidget(self.stop_btn)
        row_box.addStretch(1)

        header.addLayout(row_box, row, 0, 1, 4)
        row += 1

        left.addLayout(header)

        # --- VISIBLE MEMBERS FIELD (left) ---
        member_bar = QHBoxLayout()
        member_bar.addWidget(QLabel("Visible members (with bits):"))
        self.visible_members_edit = QLineEdit("0")
        self.visible_members_edit.setReadOnly(True)
        self.visible_members_edit.setFixedWidth(60)
        member_bar.addWidget(self.visible_members_edit)
        member_bar.addStretch(1)
        left.addLayout(member_bar)

        # --- SELECTED MEMBER + BITS (left) ---
        select_bar = QHBoxLayout()
        select_bar.addWidget(QLabel("Selected member:"))
        self.selected_member_edit = QLineEdit("")
        self.selected_member_edit.setReadOnly(True)
        self.selected_member_edit.setMinimumWidth(220)
        select_bar.addWidget(self.selected_member_edit)

        select_bar.addSpacing(12)
        select_bar.addWidget(QLabel("Bits:"))
        self.selected_bits_edit = QLineEdit("")
        self.selected_bits_edit.setReadOnly(True)
        self.selected_bits_edit.setFixedWidth(80)
        select_bar.addWidget(self.selected_bits_edit)

        select_bar.addStretch(1)
        left.addLayout(select_bar)

        # --- STATUS LIST (left) ---
        box_status = QGroupBox("Status (double-click a member to select controller)")
        lay_status = QVBoxLayout(box_status)
        self.list_status = QListWidget()
        lay_status.addWidget(self.list_status)
        left.addWidget(box_status, 1)

        # Status label
        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet("font-size: 11px; color: #a0a4ad;")
        left.addWidget(self.status_label)

        # LEGEND for F5/F6/F7/F8
        self.legend_label = QLabel(
            "Legend: F5 → toggle clicks · "
            "F6 → toggle GAMING / FULL · F7 → pause / resume · "
            "F8 → cycle sensitivity 1–9 (1=mouse only → 9=full) · "
            "Move mouse to top-left corner to abort (pyautogui FAILSAFE)."
        )
        self.legend_label.setStyleSheet("font-size: 10px; color: #9CA3AF;")
        left.addWidget(self.legend_label)

        # Push status + legend up so bottom roughly lines with avatar column
        left.addStretch(1)

        # --- AVATAR COLUMN (right) ---
        avatar_box = QGroupBox("Controller Avatar")
        avatar_layout = QVBoxLayout(avatar_box)

        self.avatar_label = QLabel("No avatar")
        self.avatar_label.setFixedSize(112, 112)  # slightly larger, less blur
        self.avatar_label.setStyleSheet(
            "border: 1px solid #30333b; border-radius: 8px; background-color: #111318;"
        )
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_layout.addWidget(self.avatar_label, alignment=Qt.AlignmentFlag.AlignTop)

        # small info label for profile / mode / clicks
        self.profile_label = QLabel("Profile: 1  |  Mode: GAMING  |  Clicks: ON")
        self.profile_label.setStyleSheet("font-size: 10px; color: #c7ccd8;")
        avatar_layout.addWidget(self.profile_label)

        avatar_layout.addStretch(1)
        right.addWidget(avatar_box)

        # --- Settings button at global bottom-right (inside RIGHT column) ---
        settings_bar = QHBoxLayout()
        self.settings_btn = QPushButton("Settings…")
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        settings_bar.addStretch(1)
        settings_bar.addWidget(self.settings_btn)
        right.addLayout(settings_bar)

        # Add left and right to root
        root.addLayout(left, 4)
        root.addLayout(right, 1)

        # Connections
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.poll_spin.valueChanged.connect(self._update_poll_interval)
        self.list_status.itemDoubleClicked.connect(self._select_member_for_field)

        # Simple dark-ish theme
        self.setStyleSheet("""
            QWidget {
                background-color: #181A20;
                color: #E5E7EB;
                font-family: Segoe UI, sans-serif;
                font-size: 12px;
            }
            QLineEdit, QListWidget {
                background-color: #111318;
                border: 1px solid #30333b;
                border-radius: 4px;
                padding: 2px 4px;
            }
            QGroupBox {
                border: 1px solid #30333b;
                border-radius: 6px;
                margin-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 3px 0 3px;
                color: #c7ccd8;
                font-weight: 500;
            }
            QPushButton {
                background-color: #2563EB;
                border-radius: 4px;
                padding: 4px 10px;
                border: none;
                color: #E5E7EB;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9CA3AF;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #111318;
                border: 1px solid #30333b;
                border-radius: 4px;
                padding: 1px 4px;
            }
        """)

    # ---------- helpers ----------

    def _open_settings_dialog(self):
        dlg = SettingsDialog(self.settings, self)
        dlg.exec()

    def _pick_user_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Chrome user-data dir", self.user_data_edit.text() or ""
        )
        if path:
            self.user_data_edit.setText(path)

    def _pick_stream_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select file to trigger on streaming", "", "All Files (*.*)"
        )
        if path:
            self.stream_file_edit.setText(path)

    def _log(self, text: str):
        self.status_label.setText(text)

    def _get_appdata_dir(self) -> str:
        """
        Returns a local 'appdata' folder next to this script,
        creating it if necessary.
        """
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        appdata_dir = os.path.join(base_dir, "appdata")
        os.makedirs(appdata_dir, exist_ok=True)
        return appdata_dir

    def _download_avatar_to_appdata(self, url: str) -> Optional[str]:
        """
        Downloads the avatar file to appdata/ and returns the local path.
        Overwrites the file each time for now.
        """
        if not url:
            return None

        try:
            appdata_dir = self._get_appdata_dir()

            # Try to derive a nice filename from the URL
            name_part = url.split("/")[-1].split("?")[0] or "avatar"
            if not any(name_part.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
                name_part += ".png"

            local_path = os.path.join(appdata_dir, name_part)

            # Download with a browser-like UA (Discord CDN can be picky)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp, open(local_path, "wb") as f:
                f.write(resp.read())

            print(f"[AVATAR] saved {url} -> {local_path}")
            return local_path

        except Exception as e:
            print(f"[AVATAR] download failed: {e}")
            return None

    def _set_avatar_from_file(self, local_path: str):
        """
        Load an image file into the avatar_label (scaled).
        """
        if not local_path or not os.path.exists(local_path):
            self.avatar_label.setText("No avatar")
            self.avatar_label.setPixmap(QPixmap())
            return

        pix = QPixmap(local_path)
        if pix.isNull():
            print(f"[AVATAR] could not load pixmap from {local_path}")
            self.avatar_label.setText("No avatar")
            self.avatar_label.setPixmap(QPixmap())
            return

        pix = pix.scaled(
            self.avatar_label.width(),
            self.avatar_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.avatar_label.setPixmap(pix)
        self.avatar_label.setText("")

    def _update_avatar_label(self, url: str):
        """
        Download avatar into appdata/ and load from local file.
        """
        if not url:
            self.avatar_label.setText("No avatar")
            self.avatar_label.setPixmap(QPixmap())
            return

        local_path = self._download_avatar_to_appdata(url)
        if not local_path:
            self.avatar_label.setText("No avatar")
            self.avatar_label.setPixmap(QPixmap())
            return

        self._set_avatar_from_file(local_path)

    def _capture_profile_card(self, member_name: str):
        """
        Try to open the Discord profile popout for member_name and
        screenshot the full card into appdata/, then show it in the avatar box.

        Best-effort; if anything fails we silently fall back to avatar.
        """
        if not self.driver:
            return

        try:
            # Make sure member panel is visible
            _ensure_members_panel(self.driver)
            root = _find_member_root(self.driver)
            if not root:
                return

            items = root.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
            target_el = None

            for e in items:
                txt = (e.text or "").strip()
                if not txt:
                    continue
                lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
                if not lines:
                    continue
                name = lines[0]
                if name == member_name:
                    target_el = e
                    break

            if not target_el:
                return

            # Scroll into view and click to open profile popout
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_el)
            time.sleep(0.2)
            target_el.click()
            time.sleep(0.6)  # let popout render

            # Find dialog (profile card) that contains the member name
            dialogs = self.driver.find_elements(By.CSS_SELECTOR, '[role="dialog"]')
            pop = None
            for d in dialogs:
                if not d.is_displayed():
                    continue
                text = (d.text or "")
                if member_name in text:
                    pop = d
                    break

            if not pop:
                return

            # Screenshot to appdata
            appdata_dir = self._get_appdata_dir()
            safe_name = "".join(c if c.isalnum() else "_" for c in member_name)
            local_path = os.path.join(appdata_dir, f"profile_{safe_name}.png")
            pop.screenshot(local_path)
            print(f"[PROFILE] captured profile card for {member_name} -> {local_path}")

            # Show in avatar box
            self._set_avatar_from_file(local_path)

        except Exception as e:
            print(f"[PROFILE] capture failed for {member_name}: {e}")

    def _update_profile_label(self):
        self.profile_label.setText(
            f"Profile: {self.ctrl_engine.sensitivity_profile}  |  "
            f"Mode: {self.ctrl_engine.mode.upper()}  |  "
            f"Clicks: {'ON' if self.ctrl_engine.io.master_click_enabled else 'OFF'}"
        )

    def _ensure_guild_view(self):
        """
        If a guild URL is stored and current_url doesn't match it,
        auto-navigate to that guild/channel.
        """
        if not self.driver:
            return
        g = (self.settings.guild_url or "").strip()
        if not g:
            return
        try:
            cur = self.driver.current_url
            # Use prefix match so we tolerate different #fragments or small variations
            if not cur.startswith(g):
                print(f"[GUILD] Navigating to stored guild URL: {g}")
                self.driver.get(g)
                time.sleep(3.0)
        except Exception:
            pass

    # ==================== START / STOP ====================

    def start(self):
        if self.driver is not None:
            QMessageBox.information(self, "Running", "Already running.")
            return

        try:
            opts = Options()
            opts.add_argument("--window-size=1400,900")
            opts.add_argument("--disable-notifications")
            opts.add_experimental_option("excludeSwitches", ["enable-logging"])

            user_data = self.user_data_edit.text().strip()
            profile = self.profile_edit.text().strip()
            if user_data:
                opts.add_argument(f"--user-data-dir={user_data}")
                if profile:
                    opts.add_argument(f"--profile-directory={profile}")

            self.driver = webdriver.Chrome(options=opts)
        except Exception as e:
            self._log(f"ERROR launching Chrome: {e}")
            return

        url = self.url_edit.text().strip() or "https://discord.com/app"
        try:
            self.driver.get(url)
        except Exception as e:
            self._log(f"ERROR opening URL: {e}")
            return

        self._log(f"Opened {url} — waiting {DEFAULT_WAIT_SECS:.0f}s…")
        QApplication.processEvents()
        time.sleep(max(0.0, DEFAULT_WAIT_SECS))

        self._update_poll_interval()
        self.poll_timer.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._log("Monitoring member statuses…")

    def stop(self):
        try:
            self.poll_timer.stop()
        except Exception:
            pass

        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass

        self.driver = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.was_streaming = False
        self._log("Stopped (controller still armed; no Discord input).")

    def _update_poll_interval(self):
        secs = max(2, int(self.poll_spin.value()))
        self.poll_timer.setInterval(secs * 1000)
        if self.driver:
            self._log(f"Poll interval: {secs}s")

    # ==================== MEMBER SELECTION ====================

    def _select_member_for_field(self, item: QListWidgetItem):
        text = item.text()
        parts = text.split("—", 1)
        if len(parts) == 2:
            name = parts[1].strip()
        else:
            name = text.strip()

        self.selected_member_name = name
        self.selected_member_edit.setText(name)

        bits = ""
        avatar_url = ""
        for row_name, s_name, bit_str, av_url in self.current_rows:
            if row_name == name:
                bits = bit_str
                avatar_url = av_url
                break

        self.selected_bits_edit.setText(bits)
        if avatar_url:
            print(f"[AVATAR] {name}: {avatar_url}")
        self._update_avatar_label(avatar_url)

        # Capture full profile card (best-effort)
        self._capture_profile_card(name)

        # Recolor list so selected row uses selected_color
        self._recolor_status_list()

    # ==================== CONTROLLER STEP ====================

    def _control_step(self):
        if not self.selected_member_name:
            self._update_profile_label()
            return

        bits = None
        status = "unknown"
        for name, status_name, bit_str, av_url in self.current_rows:
            if name == self.selected_member_name:
                bits = bit_str
                status = status_name
                break

        if bits is None:
            bits = self.selected_bits_edit.text().strip()

        if not bits or len(bits) != 5:
            self._update_profile_label()
            return

        self.selected_bits_edit.setText(bits)
        self.ctrl_engine.step(bits, self.selected_member_name, status)
        self._update_profile_label()

    # ==================== POLLING (DISCORD) ====================

    def _recolor_status_list(self):
        """
        Apply colors to all items:
          - selected user's row → settings.selected_color
          - others → per-status color from STATUS_COLORS
        """
        for i in range(self.list_status.count()):
            item = self.list_status.item(i)
            text = item.text()
            parts = text.split("—", 1)
            name = parts[1].strip() if len(parts) == 2 else text.strip()

            status_part = parts[0].strip() if len(parts) == 2 else ""
            status_name = status_part.lower()

            if self.selected_member_name and name == self.selected_member_name:
                item.setForeground(QColor(self.settings.selected_color))
            else:
                col_hex = STATUS_COLORS.get(status_name, STATUS_COLORS["unknown"])
                item.setForeground(QColor(col_hex))

    def _poll_once(self):
        if not self.driver:
            return

        # Make sure we're on the stored guild, if provided
        self._ensure_guild_view()

        rows, total, any_streaming = collect_member_status_bits(self.driver)
        self.current_rows = rows

        self.visible_members_edit.setText(str(len(rows)))

        self.list_status.clear()
        for name, status_name, bit_str, avatar_url in rows:
            disp_status = status_name.capitalize()
            item = QListWidgetItem(f"{disp_status} — {name}")

            if self.selected_member_name and name == self.selected_member_name:
                item.setForeground(QColor(self.settings.selected_color))
            else:
                col_hex = STATUS_COLORS.get(status_name, STATUS_COLORS["unknown"])
                item.setForeground(QColor(col_hex))

            self.list_status.addItem(item)

        # Ensure selected user's bits + avatar stay fresh
        if self.selected_member_name:
            avatar_url = ""
            for name, status_name, bit_str, av_url in rows:
                if name == self.selected_member_name:
                    self.selected_member_edit.setText(name)
                    self.selected_bits_edit.setText(bit_str)
                    avatar_url = av_url
                    break
            if avatar_url:
                self._update_avatar_label(avatar_url)

        try:
            if any_streaming and not self.was_streaming:
                path = self.stream_file_edit.text().strip()
                if path:
                    if sys.platform.startswith("win"):
                        os.startfile(path)
                    else:
                        self._log("Streaming detected, but os.startfile is Windows-only.")
        except Exception as e:
            self._log(f"Streaming trigger failed: {e}")

        self.was_streaming = any_streaming

        self._log(
            f"Members={total} | With status bits={len(rows)} | "
            f"Streaming={'YES' if any_streaming else 'no'}"
        )


# ==================== MAIN ====================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = StatusBitApp()
    ui.show()
    sys.exit(app.exec())
