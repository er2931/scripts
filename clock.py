# ================================================================
# presence_clock_qt_pro_fkeys_pause.py — Pause + F-key mode switch
# Hardened member scraping (incl. mobile), heartbeat/backoff watcher,
# guaranteed token flow (cycle + keepalive).
# ================================================================

import os, sys, time, random, hashlib, threading
from typing import Dict, Optional, List

# --------------- MOUSE/KEY IO (adminless default via pyautogui) ---------------
import pyautogui
pyautogui.FAILSAFE = False

try:
    import keyboard as kb_mod  # optional elevated keyboard
except Exception:
    kb_mod = None

# ----------------------------- SELENIUM (Edge) ------------------------------
from selenium.webdriver import Edge
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

# --------------------------------- Qt UI ------------------------------------
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSlider, QDialog, QFormLayout,
    QSpinBox, QDoubleSpinBox, QCheckBox
)

# ------------------- CONFIG -------------------
CYCLE_BITS_DEFAULT             = 120
TOKEN_DRIFT_RANGE_DEFAULT      = 0.002
RESET_TOKEN                    = "§RESET§"
RESET_PROBABILITY_DEFAULT      = 0.02
ACTION_PERIOD_SEC_DEFAULT      = 1.0
PRESENCE_POLL_INTERVAL_DEFAULT = 0.25
ACTIVE_STATES                  = {"online", "idle", "dnd", "mobile"}
OFFLINE_GRACE_SECONDS          = 4.0
MOUSE_STEP_DEFAULT             = 24
MOUSE_ACCEL_DEFAULT            = 4
MOUSE_MAX_STEP_DEFAULT         = 96
USE_ADMINLESS_KEYS_DEFAULT     = True
KEY_DELAY_DEFAULT              = 0.03
MOUSE_DOMINANCE_DEFAULT        = 60
KEY_DOMINANCE_DEFAULT          = 40
RANDOMIZE_TOKEN_TABLE_ON_START = True

# ------------------- TOKEN TABLE -------------------
def make_token_table() -> List[str]:
    base = (
        list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") +
        list("abcdefghijklmnopqrstuvwxyz") +
        list("0123456789") +
        list("!@#$%^&*()-_=+[]{};:,<.>/?")
    )
    while len(base) < 64:
        base += base
    base = base[:64]
    if RESET_TOKEN not in base:
        base[0] = RESET_TOKEN
    if RANDOMIZE_TOKEN_TABLE_ON_START:
        r = random.Random()
        r.shuffle(base)
        if RESET_TOKEN not in base:
            base[0] = RESET_TOKEN
    return base

TOKENS = make_token_table()

# ------------------- DISCORD SELECTORS (HARDENED) -------------------
SERVERS_SIDEBAR='nav[role="navigation"]'
CHANNELS_PANEL='div[role="tree"], nav[role="tree"]'
MEMBERS_PANEL='aside [role="list"], div[aria-label][role="list"], div[role="list"]'
MEMBER_ITEM=f'{MEMBERS_PANEL} [role="listitem"]'

# presence often lives in aria-label/title on svg badges or tooltips
CANDIDATE_STATUS_SELECTORS = [
    '[role="img"][aria-label],[role="img"][title]',
    '[aria-label*="Online" i],[title*="Online" i]',
    '[aria-label*="Idle" i],[title*="Idle" i]',
    '[aria-label*="Do Not Disturb" i],[title*="Do Not Disturb" i],[aria-label*="DND" i],[title*="DND" i]',
    '[aria-label*="Mobile" i],[title*="Mobile" i]'
]

def normalize_name(name:str)->str:
    return " ".join((name or "").strip().lower().split())

def open_discord() -> Edge:
    opts = EdgeOptions()
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = EdgeService()
    drv = Edge(options=opts, service=service)
    drv.get("https://discord.com/app")
    WebDriverWait(drv, 180).until(EC.any_of(
        EC.presence_of_element_located((By.CSS_SELECTOR, SERVERS_SIDEBAR)),
        EC.presence_of_element_located((By.CSS_SELECTOR, CHANNELS_PANEL)),
        EC.url_contains("/channels/"), EC.url_contains("/app")
    ))
    print("✅ Discord loaded. Open a guild and the Members list (right-side people icon).")
    return drv

def _presence_from_element(el) -> str:
    try:
        a = ((el.get_attribute("aria-label") or "") + " " + (el.get_attribute("title") or "")).lower()
    except Exception:
        a = ""
    if "mobile" in a: return "mobile"
    if "do not disturb" in a or "dnd" in a: return "dnd"
    if "idle" in a: return "idle"
    if "online" in a: return "online"
    return ""

def _presence_from_row(row) -> str:
    # direct attributes
    for attr in ("aria-label","title"):
        try:
            val=(row.get_attribute(attr) or "").lower()
            if "mobile" in val: return "mobile"
            if "do not disturb" in val or "dnd" in val: return "dnd"
            if "idle" in val: return "idle"
            if "online" in val: return "online"
        except Exception:
            pass
    # nested icons/badges
    for sel in CANDIDATE_STATUS_SELECTORS:
        try:
            for el in row.find_elements(By.CSS_SELECTOR, sel):
                st = _presence_from_element(el)
                if st: return st
        except Exception:
            continue
    return "offline"

def _try_scroll_members_panel(driver, step=720, max_scrolls=36):
    try:
        panel = driver.find_element(By.CSS_SELECTOR, MEMBERS_PANEL)
    except Exception:
        return False
    # bounce top → bottom → partial up to trigger lazy load
    try: driver.execute_script("arguments[0].scrollTop = 0;", panel)
    except Exception: return False
    time.sleep(0.05)
    for _ in range(max_scrolls):
        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollTop + arguments[1];", panel, step)
        except Exception:
            break
        time.sleep(0.02)
    for _ in range(max_scrolls//3):
        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollTop - arguments[1];", panel, step)
        except Exception:
            break
        time.sleep(0.02)
    return True

def get_visible_members(driver: Edge) -> Dict[str,str]:
    try:
        WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, MEMBERS_PANEL)))
    except Exception:
        return {}
    seen={}
    try:
        rows=driver.find_elements(By.CSS_SELECTOR, MEMBER_ITEM)
    except Exception:
        rows=[]
    for r in rows:
        try:
            txt=(r.text or "").strip().splitlines()
            name = (txt[0].strip() if txt else "")
            if not name: continue
            pres=_presence_from_row(r)
            seen.setdefault(name, pres)
        except StaleElementReferenceException:
            continue
    if len(seen) < 5:
        _try_scroll_members_panel(driver)
        time.sleep(0.15)
        try:
            rows=driver.find_elements(By.CSS_SELECTOR, MEMBER_ITEM)
        except Exception:
            rows=[]
        for r in rows:
            try:
                txt=(r.text or "").strip().splitlines()
                name = (txt[0].strip() if txt else "")
                if not name: continue
                pres=_presence_from_row(r)
                seen[name]=pres
            except StaleElementReferenceException:
                continue
    return seen

# ------------------- IO (mouse/keyboard) -------------------
SAFE_KEYS = (
    [str(i) for i in range(10)]
    + [chr(c) for c in range(ord("a"), ord("z")+1)]
    + [f"f{i}" for i in range(1,13)]
    + ["esc","tab","caps lock","shift","ctrl","alt","space","enter","backspace",
       "left","right","up","down","home","end","page up","page down",
       "insert","delete","-","=","[","]","\\",";","'",",",".","/"]
)

def key_press(key: str, key_delay: float, adminless: bool) -> str:
    try:
        if adminless or kb_mod is None:
            mapping = {
                "page up": "pageup", "page down": "pagedown", "caps lock": "capslock",
                "left": "left", "right": "right", "up": "up", "down": "down",
                "ctrl": "ctrl", "alt": "alt", "shift": "shift", "enter": "enter",
                "backspace": "backspace", "tab": "tab", "home": "home", "end": "end",
                "insert": "insert", "delete": "delete", "space": "space", "esc": "esc"
            }
            k = mapping.get(key, key)
            known = {
                "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12",
                "pageup","pagedown","home","end","insert","delete","space",
                "left","right","up","down","enter","tab","backspace","capslock",
                "ctrl","alt","shift","esc","-","=","[","]","\\",";","'",",",".","/"
            }
            if len(k) == 1 and k.isprintable() and k not in known:
                pyautogui.write(k)
            elif k in known:
                pyautogui.press(k)
            else:
                pyautogui.write(k)
            time.sleep(max(0.0, key_delay))
            return f"key:{k}"
        else:
            kb_mod.press_and_release(key)
            time.sleep(max(0.0, key_delay))
            return f"key:{key}"
    except Exception as e:
        return f"key-skip:{key}:{e.__class__.__name__}"

def mouse_move(dx:int, dy:int) -> str:
    x, y = pyautogui.position()
    pyautogui.moveTo(x+dx, y+dy, duration=0)
    return f"move({dx},{dy})"

def mouse_click(left=True, dbl=False) -> str:
    if dbl and left:
        pyautogui.click(); time.sleep(0.05); pyautogui.click()
        return "dblclick"
    if left:
        pyautogui.click(); return "click"
    else:
        pyautogui.rightClick(); return "rclick"

def mouse_wheel(v=0, h=0) -> str:
    if v: pyautogui.scroll(int(v)); return f"scroll_v:{v}"
    if h: pyautogui.hscroll(int(h)); return f"scroll_h:{h}"
    return "wheel:noop"

def mouse_drag(start=True) -> str:
    if start:
        pyautogui.mouseDown(); return "drag_start"
    else:
        pyautogui.mouseUp(); return "drag_end"

MOUSE_DIR = {
    "up": (0,-1), "down": (0,1), "left": (-1,0), "right": (1,0),
    "up_left": (-1,-1), "up_right": (1,-1), "down_left": (-1,1), "down_right": (1,1),
    "upward": (0,-1),
}
MOUSE_TOKENS_CLICKS = {"click": "L", "rclick": "R", "dblclick": "D"}
MOUSE_TOKENS_SCROLL = {"scroll_up":+1, "scroll_down":-1, "scroll_left":-1, "scroll_right":+1}
MOUSE_TOKENS_DRAG   = {"drag_start": "S", "drag_end": "E"}

KEY_ACTIONS = [
    "w","a","s","d","space","enter","tab","backspace",
    "left","right","up","down","ctrl","alt","shift","esc"
]

# ------------------- CLOCK -------------------
def sha_index(bits: List[int]) -> int:
    return hashlib.sha256(bytes(int(b) for b in bits)).digest()[0] & 0b111111

class DriftClock:
    def __init__(self, cycle_bits:int, drift_range:float, reset_prob:float):
        self.bits: List[int] = []
        self.cycle_bits = max(1, int(cycle_bits))
        self.drift_range = float(drift_range)
        self.reset_prob = float(reset_prob)
        self.drift = 0.0
        self.window_counter = 0

    def reset_params(self, cycle_bits:int, drift_range:float, reset_prob:float):
        self.cycle_bits = max(1, int(cycle_bits))
        self.drift_range = float(drift_range)
        self.reset_prob = float(reset_prob)

    def add_bit(self, b:int):
        self.bits.append(1 if b else 0)

    def full(self)->bool:
        return len(self.bits) >= self.cycle_bits

    def emit(self) -> str:
        out = self.bits[:self.cycle_bits]
        self.bits = self.bits[self.cycle_bits:]
        idx = sha_index(out)
        token = TOKENS[idx % 64]
        # drift & rare reset
        self.drift += random.uniform(-self.drift_range, self.drift_range)
        self.drift = max(min(self.drift, self.drift_range*8), -self.drift_range*8)
        if token == RESET_TOKEN and random.random() < self.reset_prob:
            print("⚙️  Clock reset event triggered by RESET token.")
            self.bits.clear(); self.drift = 0.0
        self.window_counter += 1
        return token

# ------------------- PRESENCE -------------------
class PresenceWatcher(threading.Thread):
    def __init__(self, driver: Edge, target_name: str, poll_interval: float):
        super().__init__(daemon=True)
        self.driver = driver
        self.target_norm = normalize_name(target_name)
        self.state = "offline"
        self.last_seen_ts = 0.0
        self.poll_interval = float(poll_interval)
        self._running = True

    def stop(self):
        self._running = False

    def set_poll_interval(self, sec: float):
        self.poll_interval = float(sec)

    def run(self):
        backoff = 0.0  # small backoff if DOM temporarily missing
        while self._running:
            t0 = time.time()
            try:
                members = get_visible_members(self.driver)
            except Exception:
                members = {}

            if members:
                nmap = {normalize_name(k): v for k, v in members.items()}
                st = nmap.get(self.target_norm)
                if st:
                    self.state = st
                    self.last_seen_ts = t0
                else:
                    if (t0 - self.last_seen_ts) >= OFFLINE_GRACE_SECONDS:
                        self.state = "offline"
                backoff = 0.0
            else:
                if (t0 - self.last_seen_ts) >= OFFLINE_GRACE_SECONDS:
                    self.state = "offline"
                backoff = min(1.0, backoff + 0.1)

            # heartbeat: never let UI go stale
            time.sleep(max(0.05, self.poll_interval + backoff))

# ------------------- SETTINGS DIALOG -------------------
class SettingsDialog(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.state = state

        form = QFormLayout(self)

        self.spCycle = QSpinBox(); self.spCycle.setRange(1, 4096); self.spCycle.setValue(state["cycle_bits"])
        self.spPeriod = QDoubleSpinBox(); self.spPeriod.setRange(0.05, 10.0); self.spPeriod.setSingleStep(0.05); self.spPeriod.setValue(state["action_period"])
        self.spDrift = QDoubleSpinBox(); self.spDrift.setRange(0.0, 0.05); self.spDrift.setSingleStep(0.0005); self.spDrift.setDecimals(5); self.spDrift.setValue(state["drift_range"])
        self.spReset = QDoubleSpinBox(); self.spReset.setRange(0.0, 1.0); self.spReset.setSingleStep(0.01); self.spReset.setDecimals(3); self.spReset.setValue(state["reset_prob"])
        self.spPoll = QDoubleSpinBox(); self.spPoll.setRange(0.05, 5.0); self.spPoll.setSingleStep(0.05); self.spPoll.setValue(state["presence_poll"])

        self.spStep = QSpinBox(); self.spStep.setRange(1, 1024); self.spStep.setValue(state["mouse_step"])
        self.spAccel= QSpinBox(); self.spAccel.setRange(0, 1024); self.spAccel.setValue(state["mouse_accel"])
        self.spMax  = QSpinBox(); self.spMax.setRange(1, 4096); self.spMax.setValue(state["mouse_max"])

        self.spKeyDelay = QDoubleSpinBox(); self.spKeyDelay.setRange(0.0, 1.0); self.spKeyDelay.setSingleStep(0.005); self.spKeyDelay.setDecimals(3); self.spKeyDelay.setValue(state["key_delay"])
        self.cbAdminless= QCheckBox("Adminless keys (pyautogui)"); self.cbAdminless.setChecked(state["adminless"])

        self.spMouseDom = QSpinBox(); self.spMouseDom.setRange(0,100); self.spMouseDom.setValue(state["mouse_dom"])
        self.spKeyDom   = QSpinBox(); self.spKeyDom.setRange(0,100); self.spKeyDom.setValue(state["key_dom"])

        form.addRow("Cycle bits:", self.spCycle)
        form.addRow("Action period (sec):", self.spPeriod)
        form.addRow("Drift range (sec):", self.spDrift)
        form.addRow("Reset probability:", self.spReset)
        form.addRow("Presence poll (sec):", self.spPoll)
        form.addRow("Mouse step (px):", self.spStep)
        form.addRow("Mouse accel (px/tick):", self.spAccel)
        form.addRow("Mouse max step (px):", self.spMax)
        form.addRow("Key delay (sec):", self.spKeyDelay)
        form.addRow(self.cbAdminless)
        form.addRow("Mouse dominance (%):", self.spMouseDom)
        form.addRow("Key dominance (%):", self.spKeyDom)

        btns = QHBoxLayout()
        btnOK = QPushButton("Apply"); btnClose = QPushButton("Close")
        btns.addWidget(btnOK); btns.addWidget(btnClose)
        form.addRow(btns)

        btnOK.clicked.connect(self.apply)
        btnClose.clicked.connect(self.close)

    def apply(self):
        m = self.spMouseDom.value()
        k = 100 - m
        self.spKeyDom.setValue(k)

        self.state.update({
            "cycle_bits"   : self.spCycle.value(),
            "action_period": float(self.spPeriod.value()),
            "drift_range"  : float(self.spDrift.value()),
            "reset_prob"   : float(self.spReset.value()),
            "presence_poll": float(self.spPoll.value()),
            "mouse_step"   : self.spStep.value(),
            "mouse_accel"  : self.spAccel.value(),
            "mouse_max"    : self.spMax.value(),
            "key_delay"    : float(self.spKeyDelay.value()),
            "adminless"    : bool(self.cbAdminless.isChecked()),
            "mouse_dom"    : m,
            "key_dom"      : k,
        })
        self.accept()

# ------------------- UI -------------------
class Signals(QObject):
    presence = pyqtSignal(str)
    token    = pyqtSignal(str)
    drift    = pyqtSignal(float)
    mode     = pyqtSignal(str)

class MiniUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Presence Clock")
        self.setFixedSize(520, 280)
        self.setStyleSheet("""
            QWidget { background: #0f1319; color: #e6edf3; font-size: 13px; }
            QLabel  { color: #dbe7ff; }
            QSlider::groove:horizontal { background: #1f2733; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #4c8bf5; width: 12px; margin: -6px 0; border-radius: 6px; }
            QPushButton { background:#1e2a3a; border:1px solid #32445a; padding:6px 10px; border-radius:6px; }
            QPushButton:hover { background:#263449; }
        """)

        self.state = {
            "cycle_bits"   : CYCLE_BITS_DEFAULT,
            "action_period": ACTION_PERIOD_SEC_DEFAULT,
            "drift_range"  : TOKEN_DRIFT_RANGE_DEFAULT,
            "reset_prob"   : RESET_PROBABILITY_DEFAULT,
            "presence_poll": PRESENCE_POLL_INTERVAL_DEFAULT,
            "mouse_step"   : MOUSE_STEP_DEFAULT,
            "mouse_accel"  : MOUSE_ACCEL_DEFAULT,
            "mouse_max"    : MOUSE_MAX_STEP_DEFAULT,
            "key_delay"    : KEY_DELAY_DEFAULT,
            "adminless"    : USE_ADMINLESS_KEYS_DEFAULT,
            "mouse_dom"    : MOUSE_DOMINANCE_DEFAULT,
            "key_dom"      : KEY_DOMINANCE_DEFAULT,
        }

        v = QVBoxLayout(self); v.setContentsMargins(10,10,10,10)
        top = QHBoxLayout()
        top.addWidget(QLabel("User:"))
        self.editUser = QLineEdit(); self.editUser.setPlaceholderText("Discord display name")
        top.addWidget(self.editUser, 1)
        self.btnStart = QPushButton("Start")
        self.btnPause = QPushButton("Pause")
        self.btnSettings = QPushButton("Settings")
        top.addWidget(self.btnStart); top.addWidget(self.btnPause); top.addWidget(self.btnSettings)
        v.addLayout(top)

        self.lblMode = QLabel("Mode: Auto (F1=Mouse, F2=Keyboard, F3=Auto)")
        v.addWidget(self.lblMode)

        self.lblMouse = QLabel(f"Mouse dom: {self.state['mouse_dom']}%")
        self.sldMouse = QSlider(Qt.Orientation.Horizontal); self.sldMouse.setRange(0,100); self.sldMouse.setValue(self.state["mouse_dom"])
        self.lblKey   = QLabel(f"Key dom: {self.state['key_dom']}%")
        self.sldKey   = QSlider(Qt.Orientation.Horizontal); self.sldKey.setRange(0,100); self.sldKey.setValue(self.state["key_dom"]); self.sldKey.setEnabled(False)
        v.addWidget(self.lblMouse); v.addWidget(self.sldMouse)
        v.addWidget(self.lblKey);   v.addWidget(self.sldKey)

        self.lblPresence = QLabel("Presence: —")
        self.lblToken = QLabel("Token: —")
        self.lblDrift = QLabel("Drift: +0.00000")
        for w in (self.lblPresence, self.lblToken, self.lblDrift):
            v.addWidget(w)

        self.signals = Signals()
        self.signals.presence.connect(lambda s: self.lblPresence.setText(f"Presence: {s}"))
        self.signals.token.connect(lambda s: self.lblToken.setText(f"Token: {s}"))
        self.signals.drift.connect(lambda d: self.lblDrift.setText(f"Drift: {d:+.5f}"))
        self.signals.mode.connect(lambda m: self.lblMode.setText(f"Mode: {m} (F1=Mouse, F2=Keyboard, F3=Auto)"))

        self.sldMouse.valueChanged.connect(self._mouse_dom_changed)
        self.btnStart.clicked.connect(self.on_start_clicked)
        self.btnPause.clicked.connect(self.on_pause_clicked)
        self.btnSettings.clicked.connect(self.on_settings_clicked)

        self.driver: Optional[Edge] = None
        self.watcher: Optional[PresenceWatcher] = None
        self.clock: Optional[DriftClock] = None
        self._run_flag = False
        self._paused = False

        self.timer_cycle = QTimer(self);  self.timer_cycle.timeout.connect(self._on_cycle_tick)   # 1 Hz ingest
        self.timer_action = QTimer(self); self.timer_action.timeout.connect(self._on_action_tick) # periodic action

        self.mode_index = 2  # 0=Mouse, 1=Keyboard, 2=Auto
        self.mode_names = ["Mouse", "Keyboard", "Auto"]
        self.signals.mode.emit(self.mode_names[self.mode_index])

        self.last_bits: List[int] = []
        self.cur_step = self.state["mouse_step"]
        self.last_emit_ts = 0.0         # keepalive timer
        self.keepalive_seconds = 12.0   # keep UI flowing

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ---- key events (F1/F2/F3 switch modes; TAB does nothing) ----
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_F1:
            self.mode_index = 0
            self.signals.mode.emit(self.mode_names[self.mode_index])
            e.accept(); return
        if e.key() == Qt.Key.Key_F2:
            self.mode_index = 1
            self.signals.mode.emit(self.mode_names[self.mode_index])
            e.accept(); return
        if e.key() == Qt.Key.Key_F3:
            self.mode_index = 2
            self.signals.mode.emit(self.mode_names[self.mode_index])
            e.accept(); return
        super().keyPressEvent(e)

    # ---- dominance sync ----
    def _mouse_dom_changed(self, val:int):
        val = max(0, min(100, val))
        self.state["mouse_dom"] = val
        self.state["key_dom"] = 100 - val
        self.lblMouse.setText(f"Mouse dom: {val}%")
        self.lblKey.setText(f"Key dom: {self.state['key_dom']}%")
        self.sldKey.blockSignals(True)
        self.sldKey.setValue(self.state["key_dom"])
        self.sldKey.blockSignals(False)

    # ---- settings ----
    def on_settings_clicked(self):
        dlg = SettingsDialog(self, dict(self.state))
        if dlg.exec():
            self.state.update(dlg.state)
            self.sldMouse.blockSignals(True); self.sldMouse.setValue(self.state["mouse_dom"]); self.sldMouse.blockSignals(False)
            self.sldKey.blockSignals(True);   self.sldKey.setValue(self.state["key_dom"]);     self.sldKey.blockSignals(False)
            self.lblMouse.setText(f"Mouse dom: {self.state['mouse_dom']}%")
            self.lblKey.setText(f"Key dom: {self.state['key_dom']}%")
            if self.clock:
                self.clock.reset_params(self.state["cycle_bits"], self.state["drift_range"], self.state["reset_prob"])
            if self.watcher:
                self.watcher.set_poll_interval(self.state["presence_poll"])
            if self.timer_action.isActive():
                self.timer_action.stop()
                self.timer_action.start(int(max(1, self.state["action_period"]*1000)))

    # ---- start/stop/pause ----
    def on_start_clicked(self):
        if self._run_flag:
            self._stop()
            return

        user = (self.editUser.text() or "").strip()
        if not user:
            self.lblPresence.setText("Presence: enter a user first.")
            return

        if self.driver is None:
            try:
                self.driver = open_discord()
            except Exception as e:
                self.lblPresence.setText(f"Presence: Edge error: {e}")
                return

        self.watcher = PresenceWatcher(self.driver, user, self.state["presence_poll"])
        self.watcher.start()
        self.clock = DriftClock(self.state["cycle_bits"], self.state["drift_range"], self.state["reset_prob"])

        self._run_flag = True
        self._paused = False
        self.btnStart.setText("Stop")
        self.btnPause.setText("Pause")
        self.signals.mode.emit(self.mode_names[self.mode_index])

        self.timer_cycle.start(1000)  # presence bit ingestion (1 Hz)
        self.timer_action.start(int(max(1, self.state["action_period"]*1000)))  # guaranteed action cadence
        print("➡️  Log in, open a guild, and show the Members list (people icon).")

    def _stop(self):
        self._run_flag = False
        self._paused = False
        self.btnStart.setText("Start")
        self.btnPause.setText("Pause")
        try:
            if self.watcher: self.watcher.stop()
        except Exception:
            pass
        self.timer_cycle.stop()
        self.timer_action.stop()

    def on_pause_clicked(self):
        if not self._run_flag:
            return
        self._paused = not self._paused
        self.btnPause.setText("Resume" if self._paused else "Pause")

    # ---- cycle bit ingestion (1 Hz) + keepalive emission ----
    def _on_cycle_tick(self):
        if not (self._run_flag and self.clock and self.watcher):
            return

        # presence always updates (UI heartbeat)
        bit = 1 if (self.watcher.state in ACTIVE_STATES) else 0
        self.signals.presence.emit(self.watcher.state)

        if not self._paused:
            self.clock.add_bit(bit)

        self.last_bits.append(bit)
        if len(self.last_bits) > 64: self.last_bits.pop(0)

        now = time.time()
        emitted = False
        if not self._paused and self.clock.full():
            token = self.clock.emit()
            self.signals.drift.emit(self.clock.drift)
            self.signals.token.emit(f"[cycle] {token}")
            self.last_emit_ts = now
            emitted = True

        # keepalive so UI never appears frozen
        if not emitted and (now - self.last_emit_ts) >= self.keepalive_seconds:
            seed = (self.last_bits if len(self.last_bits) >= 8 else [0]*8) + [1,0,1,0,0,1,0,1]
            token = TOKENS[sha_index(seed) % 64]
            self.signals.token.emit(f"[keepalive] {token}")
            self.last_emit_ts = now

    # ---- guaranteed periodic action (mouse/keyboard) ----
    def _on_action_tick(self):
        if not (self._run_flag and self.clock and self.watcher):
            return
        if self._paused:
            return

        if len(self.last_bits) < 8:
            seed_bits = ([1] * 8) if (self.watcher.state in ACTIVE_STATES) else ([0] * 8)
        else:
            seed_bits = self.last_bits[:]

        idx = sha_index(seed_bits + [1,0,1,0,0,1,0,1])
        token = TOKENS[idx % 64]

        # Choose domain by mode
        mode = self.mode_names[self.mode_index]
        if mode == "Mouse":
            action_domain = "Mouse"
        elif mode == "Keyboard":
            action_domain = "Keyboard"
        else:
            m_dom = self.state["mouse_dom"]; k_dom = self.state["key_dom"]
            if m_dom == 0 and k_dom == 0: action_domain = "Mouse"
            elif m_dom == 0: action_domain = "Keyboard"
            elif k_dom == 0: action_domain = "Mouse"
            else:
                choice = random.uniform(0, m_dom + k_dom)
                action_domain = "Mouse" if choice < m_dom else "Keyboard"

        if action_domain == "Mouse":
            action_token = self._choose_mouse_action(token)
            result = self._perform_mouse(action_token)
        else:
            action_token = self._choose_key_action(token)
            result = self._perform_key(action_token)

        self.signals.token.emit(f"{token} → {action_token} [{result}]")
        self.signals.drift.emit(self.clock.drift)

    # ---- domain choosers ----
    def _choose_mouse_action(self, token:str) -> str:
        r = random.random()
        if r < 0.60:
            return random.choice(list(MOUSE_DIR.keys()))
        elif r < 0.85:
            return random.choice(list(MOUSE_TOKENS_CLICKS.keys()))
        elif r < 0.95:
            return random.choice(list(MOUSE_TOKENS_SCROLL.keys()))
        else:
            return random.choice(list(MOUSE_TOKENS_DRAG.keys()))

    def _choose_key_action(self, token:str) -> str:
        if random.random() < 0.85:
            return random.choice(KEY_ACTIONS)
        return token if (len(token) == 1 and token.isprintable()) else "space"

    # ---- action performers ----
    def _perform_mouse(self, action_token: str) -> str:
        ms, accel, mmax = self.state["mouse_step"], self.state["mouse_accel"], self.state["mouse_max"]
        if action_token in MOUSE_DIR:
            dx, dy = MOUSE_DIR[action_token]
            self.cur_step = min(mmax, max(ms, self.cur_step + accel))
            return mouse_move(dx * self.cur_step, dy * self.cur_step)

        self.cur_step = ms  # reset accel for non-move actions

        if action_token in MOUSE_TOKENS_CLICKS:
            kind = MOUSE_TOKENS_CLICKS[action_token]
            if kind == "L":  return mouse_click(True)
            if kind == "R":  return mouse_click(False)
            if kind == "D":  return mouse_click(True, dbl=True)

        if action_token in MOUSE_TOKENS_SCROLL:
            d = MOUSE_TOKENS_SCROLL[action_token]
            if action_token in ("scroll_up","scroll_down"):
                return mouse_wheel(v=d*400)
            else:
                return mouse_wheel(h=d*400)

        if action_token in MOUSE_TOKENS_DRAG:
            return mouse_drag(start=(action_token == "drag_start"))

        return "noop"

    def _perform_key(self, action_token: str) -> str:
        kd, adminless = self.state["key_delay"], self.state["adminless"]
        name_map = {
            "space":"space", "enter":"enter", "tab":"tab", "backspace":"backspace",
            "left":"left", "right":"right", "up":"up", "down":"down",
            "ctrl":"ctrl", "alt":"alt", "shift":"shift", "esc":"esc"
        }
        key = action_token
        if key in name_map:
            return key_press(name_map[key], kd, adminless)
        if len(key) == 1 and key.isprintable():
            return key_press(key, kd, adminless)
        return key_press("space", kd, adminless)

# ------------------- MAIN -------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MiniUI()
    w.show()
    sys.exit(app.exec())
