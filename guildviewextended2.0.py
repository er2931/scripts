# discord_online_monitor_lite_colored.py
# Full version with:
# - Persistent ranks
# - Guild leader rank 001
# - Visible-order (not rank-order)
# - Scroll preserved
# - Multi-window chain anchors
# - Per-user color toggle (double click)
# - JSON persistence

import os
import sys
import time
import json
import datetime
from typing import List, Tuple, Dict, Optional
import pytz

# ---------- Config ----------
DEFAULT_WAIT_SECS = 40.0
DEFAULT_POLL_SECS = 2
MAX_EVENTS = 500
DEFAULT_TIMEZONE = "America/Costa_Rica"
CONFIG_FILE = "discord_presence_config.json"

# ---------- Qt ----------
from PyQt6.QtCore import QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QListWidget,
    QListWidgetItem, QMessageBox, QGroupBox, QSpinBox, QColorDialog
)

# ---------- Selenium ----------
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys

# ---------- Status Colors ----------
STATUS_COLORS = {
    "online":  QColor("#22c55e"),
    "idle":    QColor("#eab308"),
    "dnd":     QColor("#ef4444"),
    "offline": QColor("#6b7280"),
    "mobile":  QColor("#3b82f6"),
    "unknown": QColor("#6366f1"),
}

def status_to_color(status: str) -> QColor:
    return STATUS_COLORS.get(status or "unknown", STATUS_COLORS["unknown"])

_STATUS_KEYWORDS = [
    "online", "en línea", "en linea",
    "idle", "away", "ausente", "inactivo",
    "do not disturb", "dnd", "busy", "no molestar", "ocupado",
    "offline", "invisible", "desconectado", "sin conexión", "sin conexion",
    "mobile", "móvil", "movil",
]

# ---------- Scraping ----------
def _find_member_root(driver):
    try:
        roots = driver.find_elements(By.CSS_SELECTOR, '[aria-label="Members"]')
        roots = [r for r in roots if r.is_displayed()]
        return roots[0] if roots else None
    except:
        return None

def _ensure_members_panel(driver):
    try:
        if not _find_member_root(driver):
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys("u")
            time.sleep(0.8)
    except:
        pass

def _status_from_text(t: str) -> str:
    s = (t or "").lower()
    if "mobile" in s or "móvil" in s or "movil" in s:
        return "mobile"
    if "online" in s or "en línea" in s or "en linea" in s:
        return "online"
    if "idle" in s or "away" in s or "ausente" in s or "inactivo" in s:
        return "idle"
    if "do not disturb" in s or "dnd" in s or "busy" in s or "no molestar" in s or "ocupado" in s:
        return "dnd"
    if "offline" in s or "invisible" in s or "desconectado" in s or "sin conexión" in s or "sin conexion" in s:
        return "offline"
    return "unknown"

def _find_status_inside_item(elem):
    try:
        status_elems = elem.find_elements(By.CSS_SELECTOR, '[aria-label]')
    except:
        return None
    for se in status_elems:
        try:
            lab = se.get_attribute("aria-label") or ""
        except:
            continue
        if any(kw in lab.lower() for kw in _STATUS_KEYWORDS):
            return lab
    return None

def parse_visible_users_with_status(driver) -> List[Tuple[str, str]]:
    _ensure_members_panel(driver)
    root = _find_member_root(driver)
    if not root:
        return []
    try:
        items = root.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
    except:
        items = []

    out = []
    seen = set()
    for e in items:
        try:
            main_label = (e.get_attribute("aria-label") or e.text or "").strip()
            if not main_label:
                continue
            name = main_label.split("\n")[0]
            if " - " in name:
                name = name.split(" - ", 1)[0]
            name = name.strip()
            if not name:
                continue

            inner = _find_status_inside_item(e)
            raw = inner or main_label
            st = _status_from_text(raw)

            if name not in seen:
                seen.add(name)
                out.append((name, st))
        except:
            continue
    return out

# ---------- Main App ----------
class App(QWidget):
    log_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        self.drivers: List[webdriver.Chrome] = []
        self.window_anchors: List[Optional[str]] = []
        self.top_scrolled_once = False

        # persistent
        self.user_order: Dict[str, int] = {}
        self.user_colors: Dict[str, QColor] = {}
        self.settings: Dict[str, object] = {}
        self.next_rank = 1

        # transient
        self.prev_users: Dict[str, str] = {}
        self.event_sequence: List[Tuple[str, int, str, Optional[str], str]] = []
        self.last_rows: List[Tuple[str, str]] = []

        self._load_config()

        tz_name = self.settings.get("timezone", DEFAULT_TIMEZONE)
        try:
            self.tz = pytz.timezone(tz_name)
        except:
            self.tz = pytz.timezone(DEFAULT_TIMEZONE)

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_once)

        self._build_ui()
        self._apply_theme()
        self._apply_settings_to_ui()

    # ---------- Config ----------
    def _recompute_next_rank(self):
        self.next_rank = max(self.user_order.values(), default=0) + 1

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            self.user_order = {}
            self.user_colors = {}
            self.settings = {}
            self.next_rank = 1
            return

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            self.user_order = {}
            self.user_colors = {}
            self.settings = {}
            self.next_rank = 1
            return

        self.user_order = {str(k): int(v) for k, v in data.get("user_order", {}).items()}
        self.settings = data.get("settings", {})

        self.user_colors = {}
        for name, hexcol in data.get("user_colors", {}).items():
            try:
                self.user_colors[name] = QColor(hexcol)
            except:
                pass

        self._recompute_next_rank()

    def _save_config(self):
        s = dict(self.settings)
        if hasattr(self, "url_edit"): s["url"] = self.url_edit.text().strip()
        if hasattr(self, "user_data_edit"): s["user_data_dir"] = self.user_data_edit.text().strip()
        if hasattr(self, "profile_edit"): s["profile_dir"] = self.profile_edit.text().strip()
        if hasattr(self, "poll_spin"): s["poll_secs"] = int(self.poll_spin.value())
        if hasattr(self, "leader_edit"): s["guild_leader_name"] = self.leader_edit.text().strip()
        if hasattr(self, "windows_spin"): s["num_windows"] = int(self.windows_spin.value())
        s["timezone"] = self.tz.zone

        color_map = {name: col.name() for name, col in self.user_colors.items()}

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "user_order": self.user_order,
                "user_colors": color_map,
                "settings": s
            }, f, indent=2, ensure_ascii=False)

        self.settings = s

    # ---------- Rank Logic ----------
    def _ensure_rank(self, user: str) -> int:
        if user in self.user_order:
            return self.user_order[user]

        leader = self.settings.get("guild_leader_name", "").strip()
        if leader and user == leader:
            for uname, r in self.user_order.items():
                if r == 1:
                    self._recompute_next_rank()
                    self.user_order[uname] = self.next_rank
                    break
            self.user_order[user] = 1
            self._recompute_next_rank()
            self._save_config()
            return 1

        self._recompute_next_rank()
        r = self.next_rank
        self.user_order[user] = r
        self._recompute_next_rank()
        self._save_config()
        return r

    # ---------- UI ----------
    def _build_ui(self):
        self.setWindowTitle("Discord Presence Monitor — Lite")

        root = QVBoxLayout(self)
        header = QVBoxLayout()
        t = QLabel("Discord Presence Monitor (Lite)")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("font-size:16px;font-weight:600;")
        header.addWidget(t)

        grid = QGridLayout()
        row = 0

        self.url_edit = QLineEdit("https://discord.com/app")
        grid.addWidget(QLabel("Discord URL:"), row, 0)
        grid.addWidget(self.url_edit, row, 1, 1, 3)
        row+=1

        self.user_data_edit = QLineEdit("")
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._pick_folder(self.user_data_edit))
        grid.addWidget(QLabel("Chrome user-data dir:"), row, 0)
        grid.addWidget(self.user_data_edit, row, 1, 1, 2)
        grid.addWidget(btn, row, 3)
        row+=1

        self.profile_edit = QLineEdit("Default")
        grid.addWidget(QLabel("Chrome profile dir:"), row, 0)
        grid.addWidget(self.profile_edit, row, 1, 1, 3)
        row+=1

        self.leader_edit = QLineEdit("")
        grid.addWidget(QLabel("Guild leader name:"), row, 0)
        grid.addWidget(self.leader_edit, row, 1, 1, 3)
        row+=1

        row_box = QHBoxLayout()
        row_box.addWidget(QLabel("Poll (s):"))
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(2, 3600)
        self.poll_spin.setValue(DEFAULT_POLL_SECS)
        row_box.addWidget(self.poll_spin)

        row_box.addSpacing(10)
        row_box.addWidget(QLabel("Windows:"))
        self.windows_spin = QSpinBox()
        self.windows_spin.setRange(1, 6)
        self.windows_spin.setValue(2)
        row_box.addWidget(self.windows_spin)
        row_box.addSpacing(12)

        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        row_box.addWidget(self.start_btn)
        row_box.addWidget(self.stop_btn)
        row_box.addStretch(1)

        grid.addLayout(row_box, row, 0, 1, 4)
        row+=1

        header.addLayout(grid)
        root.addLayout(header)

        body = QHBoxLayout()

        users_box = QGroupBox("Current Visible Users (double-click to recolor/reset)")
        v = QVBoxLayout(users_box)
        self.users_list = QListWidget()
        v.addWidget(self.users_list)
        body.addWidget(users_box, 1)

        events_box = QGroupBox("Events")
        v2 = QVBoxLayout(events_box)
        self.events_list = QListWidget()
        v2.addWidget(self.events_list)
        body.addWidget(events_box, 1)

        root.addLayout(body)

        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet("font-size:11px;color:#aaa;")
        root.addWidget(self.status_label)

        self.log_sig.connect(self._set_status_text)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.poll_spin.valueChanged.connect(self._update_poll_interval)
        self.poll_spin.valueChanged.connect(lambda _: self._save_config())
        self.windows_spin.valueChanged.connect(lambda _: self._save_config())
        self.url_edit.editingFinished.connect(self._save_config)
        self.user_data_edit.editingFinished.connect(self._save_config)
        self.profile_edit.editingFinished.connect(self._save_config)
        self.leader_edit.editingFinished.connect(self._save_config)

        self.users_list.itemDoubleClicked.connect(self._edit_user_color)

    def _apply_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color:#181A20;
                color:#E5E7EB;
                font-family:Segoe UI, sans-serif;
                font-size:12px;
            }
            QLineEdit,QListWidget {
                background-color:#111318;
                border:1px solid #30333b;
                border-radius:4px;
                padding:2px 4px;
            }
            QGroupBox {
                border:1px solid #30333b;
                border-radius:6px;
                margin-top:8px;
            }
            QGroupBox::title {
                subcontrol-origin:margin; left:6px;
                color:#c7ccd8; font-weight:500;
            }
            QPushButton {
                background-color:#2563EB; border-radius:4px;
                padding:4px 10px; border:none;
                color:#E5E7EB; font-weight:500;
            }
            QPushButton:hover { background-color:#1D4ED8; }
            QPushButton:disabled {
                background-color:#374151; color:#9CA3AF;
            }
        """)

    def _apply_settings_to_ui(self):
        s = self.settings
        if "url" in s: self.url_edit.setText(str(s["url"]))
        if "user_data_dir" in s: self.user_data_edit.setText(str(s["user_data_dir"]))
        if "profile_dir" in s: self.profile_edit.setText(str(s["profile_dir"]))
        if "poll_secs" in s:
            try: self.poll_spin.setValue(int(s["poll_secs"]))
            except: pass
        if "guild_leader_name" in s: self.leader_edit.setText(str(s["guild_leader_name"]))
        if "num_windows" in s:
            try: self.windows_spin.setValue(int(s["num_windows"]))
            except: pass

    # ---------- Helpers ----------
    def _pick_folder(self, line):
        path = QFileDialog.getExistingDirectory(self, "Select folder", line.text() or os.getcwd())
        if path:
            line.setText(path)
            self._save_config()

    def _name_color_for_user(self, user: str, status: str) -> QColor:
        if user in self.user_colors:
            return self.user_colors[user]
        return status_to_color(status)

    # ---------- Row Builders ----------
    def _make_user_row_widget(self, rank, user, st):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2,0,2,0)
        h.setSpacing(4)

        r = QLabel(f"{rank:03d}")
        n = QLabel(user)
        n.setStyleSheet(f"color:{self._name_color_for_user(user, st).name()};")
        sep = QLabel(" — ")
        s = QLabel(st)
        s.setStyleSheet(f"color:{status_to_color(st).name()};")

        h.addWidget(r)
        h.addWidget(n)
        h.addWidget(sep)
        h.addWidget(s)
        h.addStretch(1)
        return w

    def _make_event_row_widget(self, ts, rank, user, old, new):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2,0,2,0)
        h.setSpacing(4)

        lbl_ts = QLabel(f"{ts} —")
        lbl_rank = QLabel(f"{rank:03d}")

        if old is None:
            name_color = self._name_color_for_user(user, new).name()
            l_name = QLabel(user); l_name.setStyleSheet(f"color:{name_color};")
            l_txt = QLabel("first seen")
            h.addWidget(lbl_ts); h.addWidget(lbl_rank); h.addWidget(l_name); h.addWidget(l_txt); h.addStretch(1)
            return w

        old_s = old or "unknown"
        new_s = new or "unknown"
        name_color = self._name_color_for_user(user, new_s).name()
        old_color = status_to_color(old_s).name()
        new_color = status_to_color(new_s).name()

        l_name = QLabel(user); l_name.setStyleSheet(f"color:{name_color};")
        l_old = QLabel(old_s); l_old.setStyleSheet(f"color:{old_color};")
        l_new = QLabel(new_s); l_new.setStyleSheet(f"color:{new_color};")

        h.addWidget(lbl_ts)
        h.addWidget(lbl_rank)
        h.addWidget(l_name)
        h.addWidget(QLabel(":"))
        h.addWidget(l_old)
        h.addWidget(QLabel("→"))
        h.addWidget(l_new)
        h.addStretch(1)
        return w

    # ---------- Rebuild Lists ----------
    def _rebuild_users_list(self):
        sb = self.users_list.verticalScrollBar()
        old = sb.value()

        self.users_list.clear()
        for name, st in self.last_rows:
            rank = self._ensure_rank(name)
            w = self._make_user_row_widget(rank, name, st)
            item = QListWidgetItem()
            item.setSizeHint(w.sizeHint())
            self.users_list.addItem(item)
            self.users_list.setItemWidget(item, w)

        sb = self.users_list.verticalScrollBar()
        sb.setValue(min(old, sb.maximum()))

    def _rebuild_events_list(self):
        self.events_list.clear()
        for ts, rank, user, old, new in self.event_sequence:
            w = self._make_event_row_widget(ts, rank, user, old, new)
            item = QListWidgetItem()
            item.setSizeHint(w.sizeHint())
            self.events_list.addItem(item)
            self.events_list.setItemWidget(item, w)

    def _recolor_all_items(self):
        self._rebuild_users_list()
        self._rebuild_events_list()

    # ---------- Double Click Coloring ----------
    def _edit_user_color(self, item):
        row = self.users_list.row(item)
        if row < 0 or row >= len(self.last_rows):
            return

        name, st = self.last_rows[row]

        if name in self.user_colors:
            del self.user_colors[name]
            self._save_config()
            self._recolor_all_items()
        else:
            cur = self._name_color_for_user(name, st)
            col = QColorDialog.getColor(currentColor=cur, parent=self, title=f"Pick color for {name}")
            if col.isValid():
                self.user_colors[name] = col
                self._save_config()
                self._recolor_all_items()

    # ---------- Start / Stop ----------
    def start(self):
        if self.drivers:
            QMessageBox.information(self, "Running", "Already running.")
            return

        n = max(1, int(self.windows_spin.value()))
        opts = Options()
        opts.add_argument("--window-size=1400,900")
        opts.add_argument("--disable-notifications")
        opts.add_experimental_option("excludeSwitches", ["enable-logging"])

        ud = self.user_data_edit.text().strip()
        prof = self.profile_edit.text().strip()
        if ud:
            opts.add_argument(f"--user-data-dir={ud}")
            if prof:
                opts.add_argument(f"--profile-directory={prof}")

        url = self.url_edit.text().strip() or "https://discord.com/app"

        try:
            drv0 = webdriver.Chrome(options=opts)
            self.drivers.append(drv0)
            drv0.get(url)
        except Exception as e:
            self.log_sig.emit(f"Error launching first window: {e}")
            return

        QMessageBox.information(self, "Login Required",
            "Log in & open the guild in the first window.\nClick OK when ready to open remaining windows.")

        for _ in range(n-1):
            try:
                drv = webdriver.Chrome(options=opts)
                drv.get(url)
                self.drivers.append(drv)
            except Exception as e:
                self.log_sig.emit(f"Error launching extra window: {e}")
                break

        self.window_anchors = [None]*len(self.drivers)
        self.top_scrolled_once = False

        self.prev_users = {}
        self.event_sequence.clear()
        self.last_rows = []
        self.users_list.clear()
        self.events_list.clear()

        self._update_poll_interval()
        self.poll_timer.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_sig.emit(f"Monitoring {len(self.drivers)} windows...")

    def stop(self):
        try: self.poll_timer.stop()
        except: pass

        for d in self.drivers:
            try: d.quit()
            except: pass

        self.drivers = []
        self.window_anchors = []
        self.top_scrolled_once = False

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log_sig.emit("Stopped.")

    def _update_poll_interval(self):
        secs = max(2, int(self.poll_spin.value()))
        self.poll_timer.setInterval(secs*1000)
        if self.drivers:
            self.log_sig.emit(f"Poll every {secs}s")

    # ---------- Scroll Helpers ----------
    def _scroll_to_top(self, driver):
        try:
            body = driver.find_element(By.TAG_NAME,"body")
            for _ in range(3):
                body.send_keys(Keys.HOME)
                time.sleep(0.1)
        except:
            pass

    def _scroll_window_to_anchor(self, driver, anchor_name, max_steps=10):
        if not anchor_name:
            return
        for _ in range(max_steps):
            rows = parse_visible_users_with_status(driver)
            if not rows:
                return
            first = rows[0][0]
            if first == anchor_name:
                return
            names = [n for n,_ in rows]
            try:
                idx = names.index(anchor_name)
            except:
                idx = -1
            try:
                body = driver.find_element(By.TAG_NAME,"body")
            except:
                return
            if idx == -1:
                body.send_keys(Keys.PAGE_DOWN)
            else:
                if idx > 0:
                    body.send_keys(Keys.PAGE_DOWN)
                else:
                    return
            time.sleep(0.2)

    # ---------- Poll ----------
    def _poll_once(self):
        if not self.drivers:
            return

        now = datetime.datetime.now(self.tz)

        if not self.top_scrolled_once:
            try: self._scroll_to_top(self.drivers[0])
            except: pass
            self.top_scrolled_once = True

        for i in range(1, len(self.drivers)):
            a = self.window_anchors[i] if i < len(self.window_anchors) else None
            if a:
                try: self._scroll_window_to_anchor(self.drivers[i], a)
                except: pass

        per_window = []
        merged=[]
        seen=set()

        for d in self.drivers:
            try:
                rows = parse_visible_users_with_status(d)
            except Exception as e:
                self.log_sig.emit(f"Poll error: {e}")
                rows=[]
            per_window.append(rows)
            for n,st in rows:
                if n not in seen:
                    seen.add(n)
                    merged.append((n,st))

        if len(self.window_anchors)!=len(self.drivers):
            self.window_anchors=[None]*len(self.drivers)
        self.window_anchors[0]=None
        for i in range(1,len(self.drivers)):
            prev_rows = per_window[i-1] if i-1<len(per_window) else []
            if prev_rows:
                self.window_anchors[i]=prev_rows[-1][0]

        curr = {n:st for n,st in merged}
        prev = self.prev_users

        for n,st in curr.items():
            had_rank = n in self.user_order
            r = self._ensure_rank(n)

            if n in prev:
                old = prev[n]
                if (st or "unknown")!=(old or "unknown"):
                    self._record_status_change(r,n,old,st,now)
            else:
                if had_rank:
                    self._record_status_change(r,n,"offline",st,now)
                else:
                    self._record_first_seen(r,n,st,now)

        for n,old in prev.items():
            if n not in curr:
                r=self._ensure_rank(n)
                self._record_status_change(r,n,old,"offline",now)

        self.prev_users=curr

        self.last_rows = merged
        self._rebuild_users_list()

        self.log_sig.emit(f"Poll {now.strftime('%H:%M:%S')} — visible={len(merged)}, events={len(self.event_sequence)}")

    # ---------- Record Events ----------
    def _record_first_seen(self, rank,user,st,now):
        ts=now.strftime("%Y-%m-%d %H:%M:%S")
        self.event_sequence.append((ts,rank,user,None,st))
        if len(self.event_sequence)>MAX_EVENTS:
            self.event_sequence=self.event_sequence[-MAX_EVENTS:]
        self._rebuild_events_list()
        self.events_list.scrollToBottom()

    def _record_status_change(self, rank,user,old,new,now):
        ts=now.strftime("%Y-%m-%d %H:%M:%S")
        self.event_sequence.append((ts,rank,user,old,new))
        if len(self.event_sequence)>MAX_EVENTS:
            self.event_sequence=self.event_sequence[-MAX_EVENTS:]
        self._rebuild_events_list()
        self.events_list.scrollToBottom()

    # ----------
    def _set_status_text(self, s):
        self.status_label.setText(s)

# ---------- MAIN ----------
if __name__=="__main__":
    app = QApplication(sys.argv)
    ui = App()
    ui.resize(1000,550)
    ui.show()
    sys.exit(app.exec())
