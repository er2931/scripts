# discord_online_monitor_lite_colored.py
#
# Features:
#   - Multi-window Discord presence monitor (1–6 windows)
#   - Persistent ranks per username (grand order, never shifts)
#   - Guild leader always rank 001 (set by name in UI)
#   - Left list shows CURRENT visible users in Discord order (not sorted by rank)
#   - Rank is shown but does not affect ordering
#   - Scroll position preserved between updates
#   - Per-user custom color for NAME (double-click to set/reset)
#   - Status text always uses status-tint color
#   - Anchored scrolling tries to "chain" windows (slice member list)
#   - Config (ranks, colors, settings) stored in discord_presence_config.json
#   - Snapshot of full state (members + events) every poll in
#       discord_presence_snapshot.json
#
# Educational use only; UI scraping may break & may violate ToS.
# For production, use the official Discord API.

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
SNAPSHOT_FILE = "discord_presence_snapshot.json"


def guess_default_chrome_user_data_dir() -> str:
    """
    Best-effort guess for the default Chrome user-data directory.
    Only used if no user_data_dir is already stored in settings.
    """
    try:
        if sys.platform.startswith("win"):
            base = os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Google", "Chrome", "User Data"
            )
        elif sys.platform == "darwin":
            base = os.path.expanduser(
                "~/Library/Application Support/Google/Chrome"
            )
        else:
            # Linux and others
            base = os.path.expanduser("~/.config/google-chrome")

        if base and os.path.isdir(base):
            return base
    except Exception:
        pass
    return ""


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

# ---------- Scraping helpers ----------


def _find_member_root(driver):
    try:
        roots = driver.find_elements(By.CSS_SELECTOR, '[aria-label="Members"]')
        roots = [r for r in roots if r.is_displayed()]
        return roots[0] if roots else None
    except Exception:
        return None


def _ensure_members_panel(driver):
    try:
        if not _find_member_root(driver):
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys("u")
            time.sleep(0.8)
    except Exception:
        pass


def _status_from_text(t: str) -> str:
    s = (t or "").lower()

    if "mobile" in s or "móvil" in s or "movil" in s:
        return "mobile"
    if "online" in s or "en línea" in s or "en linea" in s:
        return "online"
    if "idle" in s or "away" in s or "ausente" in s or "inactivo" in s:
        return "idle"
    if ("do not disturb" in s or "dnd" in s or "busy" in s or
            "no molestar" in s or "ocupado" in s):
        return "dnd"
    if ("offline" in s or "invisible" in s or
            "desconectado" in s or "sin conexión" in s or "sin conexion" in s):
        return "offline"
    return "unknown"


def _find_status_inside_item(elem):
    try:
        status_elems = elem.find_elements(By.CSS_SELECTOR, '[aria-label]')
    except Exception:
        return None

    for se in status_elems:
        try:
            lab = se.get_attribute("aria-label") or ""
        except Exception:
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
    except Exception:
        items = []

    out: List[Tuple[str, str]] = []
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
        except Exception:
            continue

    return out


# ---------- Main App ----------

class App(QWidget):
    log_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # multiple Chrome windows
        self.drivers: List[webdriver.Chrome] = []
        self.window_anchors: List[Optional[str]] = []
        self.top_scrolled_once: bool = False

        # persistent data
        self.user_order: Dict[str, int] = {}
        self.user_colors: Dict[str, QColor] = {}
        self.settings: Dict[str, object] = {}
        self.next_rank: int = 1

        # transient state
        self.prev_users: Dict[str, str] = {}
        self.event_sequence: List[Tuple[str, int, str, Optional[str], str]] = []
        self.last_rows: List[Tuple[str, str]] = []

        self._load_config()

        tz_name = self.settings.get("timezone", DEFAULT_TIMEZONE)
        try:
            self.tz = pytz.timezone(tz_name)
        except Exception:
            self.tz = pytz.timezone(DEFAULT_TIMEZONE)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_once)

        self._build_ui()
        self._apply_theme()
        self._apply_settings_to_ui()

    # ----- config persistence -----

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
        except Exception:
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
            except Exception:
                pass

        self._recompute_next_rank()

    def _save_config(self):
        s = dict(self.settings)
        if hasattr(self, "url_edit"):
            s["url"] = self.url_edit.text().strip()
        if hasattr(self, "user_data_edit"):
            s["user_data_dir"] = self.user_data_edit.text().strip()
        if hasattr(self, "profile_edit"):
            s["profile_dir"] = self.profile_edit.text().strip()
        if hasattr(self, "poll_spin"):
            s["poll_secs"] = int(self.poll_spin.value())
        if hasattr(self, "leader_edit"):
            s["guild_leader_name"] = self.leader_edit.text().strip()
        if hasattr(self, "windows_spin"):
            s["num_windows"] = int(self.windows_spin.value())
        s["timezone"] = self.tz.zone

        color_map = {name: col.name() for name, col in self.user_colors.items()}

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "user_order": self.user_order,
                        "user_colors": color_map,
                        "settings": s,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            pass

        self.settings = s

    # ----- rank logic -----

    def _ensure_rank(self, user: str) -> int:
        if user in self.user_order:
            return self.user_order[user]

        leader = self.settings.get("guild_leader_name", "").strip()
        if leader and user == leader:
            # move existing rank 1 (if any) to next slot
            for uname, r in list(self.user_order.items()):
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

    # ----- UI build / theme -----

    def _build_ui(self):
        self.setWindowTitle("Discord Presence Monitor — Lite")

        root = QVBoxLayout(self)

        header = QVBoxLayout()
        t = QLabel("Discord Presence Monitor (Lite)")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("font-size:16px;font-weight:600;")
        header.addWidget(t)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        row = 0

        self.url_edit = QLineEdit("https://discord.com/app")
        grid.addWidget(QLabel("Discord URL:"), row, 0)
        grid.addWidget(self.url_edit, row, 1, 1, 3)
        row += 1

        self.user_data_edit = QLineEdit("")
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._pick_folder(self.user_data_edit))
        grid.addWidget(QLabel("Chrome user-data dir:"), row, 0)
        grid.addWidget(self.user_data_edit, row, 1, 1, 2)
        grid.addWidget(btn, row, 3)
        row += 1

        self.profile_edit = QLineEdit("Default")
        grid.addWidget(QLabel("Chrome profile dir:"), row, 0)
        grid.addWidget(self.profile_edit, row, 1, 1, 3)
        row += 1

        self.leader_edit = QLineEdit("")
        grid.addWidget(QLabel("Guild leader name:"), row, 0)
        grid.addWidget(self.leader_edit, row, 1, 1, 3)
        row += 1

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
        row += 1

        header.addLayout(grid)
        root.addLayout(header)

        body = QHBoxLayout()

        users_box = QGroupBox("Current Visible Users (double-click: recolor/reset)")
        vb = QVBoxLayout(users_box)
        self.users_list = QListWidget()
        vb.addWidget(self.users_list)
        body.addWidget(users_box, 1)

        events_box = QGroupBox("Events")
        vb2 = QVBoxLayout(events_box)
        self.events_list = QListWidget()
        vb2.addWidget(self.events_list)
        body.addWidget(events_box, 1)

        root.addLayout(body)

        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet("font-size:11px;color:#a0a4ad;")
        root.addWidget(self.status_label)

        # signals
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
                subcontrol-origin:margin;
                left:6px;
                color:#c7ccd8;
                font-weight:500;
            }
            QPushButton {
                background-color:#2563EB;
                border-radius:4px;
                padding:4px 10px;
                border:none;
                color:#E5E7EB;
                font-weight:500;
            }
            QPushButton:hover { background-color:#1D4ED8; }
            QPushButton:disabled {
                background-color:#374151;
                color:#9CA3AF;
            }
        """)

    def _apply_settings_to_ui(self):
        s = self.settings

        if "url" in s:
            self.url_edit.setText(str(s["url"]))

        # auto-guess user-data dir if not set
        ud = s.get("user_data_dir", "")
        if ud:
            self.user_data_edit.setText(str(ud))
        else:
            guessed = guess_default_chrome_user_data_dir()
            if guessed:
                self.user_data_edit.setText(guessed)
                self.settings["user_data_dir"] = guessed
                self._save_config()

        if "profile_dir" in s:
            self.profile_edit.setText(str(s["profile_dir"]))

        if "poll_secs" in s:
            try:
                self.poll_spin.setValue(int(s["poll_secs"]))
            except Exception:
                pass

        if "guild_leader_name" in s:
            self.leader_edit.setText(str(s["guild_leader_name"]))

        if "num_windows" in s:
            try:
                self.windows_spin.setValue(int(s["num_windows"]))
            except Exception:
                pass

    # ----- small helpers -----

    def _set_status_text(self, text: str):
        self.status_label.setText(text)

    def _pick_folder(self, line: QLineEdit):
        path = QFileDialog.getExistingDirectory(
            self, "Select folder", line.text() or os.getcwd()
        )
        if path:
            line.setText(path)
            self._save_config()

    def _name_color_for_user(self, user: str, status: str) -> QColor:
        if user in self.user_colors:
            return self.user_colors[user]
        return status_to_color(status)

    # ----- row builders -----

    def _make_user_row_widget(self, rank: int, user: str, st: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(4)

        r_lbl = QLabel(f"{rank:03d}")
        name_lbl = QLabel(user)
        name_lbl.setStyleSheet(f"color:{self._name_color_for_user(user, st).name()};")
        sep_lbl = QLabel(" — ")
        status_lbl = QLabel(st)
        status_lbl.setStyleSheet(f"color:{status_to_color(st).name()};")

        h.addWidget(r_lbl)
        h.addWidget(name_lbl)
        h.addWidget(sep_lbl)
        h.addWidget(status_lbl)
        h.addStretch(1)
        return w

    def _make_event_row_widget(
        self,
        ts: str,
        rank: int,
        user: str,
        old: Optional[str],
        new: str,
    ) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(4)

        ts_lbl = QLabel(f"{ts} —")
        r_lbl = QLabel(f"{rank:03d}")

        if old is None:
            base_status = new or "unknown"
            name_color = self._name_color_for_user(user, base_status).name()
            name_lbl = QLabel(user)
            name_lbl.setStyleSheet(f"color:{name_color};")
            txt_lbl = QLabel("first seen")

            h.addWidget(ts_lbl)
            h.addWidget(r_lbl)
            h.addWidget(name_lbl)
            h.addWidget(txt_lbl)
            h.addStretch(1)
            return w

        old_s = old or "unknown"
        new_s = new or "unknown"
        name_color = self._name_color_for_user(user, new_s).name()
        old_color = status_to_color(old_s).name()
        new_color = status_to_color(new_s).name()

        name_lbl = QLabel(user)
        name_lbl.setStyleSheet(f"color:{name_color};")
        old_lbl = QLabel(old_s)
        old_lbl.setStyleSheet(f"color:{old_color};")
        new_lbl = QLabel(new_s)
        new_lbl.setStyleSheet(f"color:{new_color};")

        h.addWidget(ts_lbl)
        h.addWidget(r_lbl)
        h.addWidget(name_lbl)
        h.addWidget(QLabel(":"))
        h.addWidget(old_lbl)
        h.addWidget(QLabel("→"))
        h.addWidget(new_lbl)
        h.addStretch(1)
        return w

    # ----- rebuild lists -----

    def _rebuild_users_list(self):
        sb = self.users_list.verticalScrollBar()
        old_val = sb.value()

        self.users_list.clear()
        # last_rows is already in merged visible order
        for name, st in self.last_rows:
            rank = self._ensure_rank(name)
            w = self._make_user_row_widget(rank, name, st)
            item = QListWidgetItem()
            item.setSizeHint(w.sizeHint())
            self.users_list.addItem(item)
            self.users_list.setItemWidget(item, w)

        sb = self.users_list.verticalScrollBar()
        sb.setValue(min(old_val, sb.maximum()))

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

    # ----- color editing -----

    def _edit_user_color(self, item: QListWidgetItem):
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
            col = QColorDialog.getColor(
                currentColor=cur,
                parent=self,
                title=f"Pick color for {name}",
            )
            if col.isValid():
                self.user_colors[name] = col
                self._save_config()
                self._recolor_all_items()

    # ----- start / stop -----

    def start(self):
        if self.drivers:
            QMessageBox.information(self, "Running", "Already running.")
            return

        num_windows = max(1, int(self.windows_spin.value()))

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

        QMessageBox.information(
            self,
            "Login Required",
            "Use the first Chrome window to log in to Discord and open the guild/channel\n"
            "you want to monitor. When you're ready, click OK and the remaining windows\n"
            "will be opened at the same location.",
        )

        # use actual URL chosen in first window
        try:
            guild_url = self.drivers[0].current_url
        except Exception:
            guild_url = url

        for _ in range(num_windows - 1):
            try:
                drv = webdriver.Chrome(options=opts)
                drv.get(guild_url)
                self.drivers.append(drv)
            except Exception as e:
                self.log_sig.emit(f"Error launching extra window: {e}")
                break

        self.window_anchors = [None] * len(self.drivers)
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
        self.log_sig.emit(f"Monitoring {len(self.drivers)} windows…")

    def stop(self):
        try:
            self.poll_timer.stop()
        except Exception:
            pass

        for d in self.drivers:
            try:
                d.quit()
            except Exception:
                pass

        self.drivers = []
        self.window_anchors = []
        self.top_scrolled_once = False

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log_sig.emit("Stopped.")

    def _update_poll_interval(self):
        secs = max(2, int(self.poll_spin.value()))
        self.poll_timer.setInterval(secs * 1000)
        if self.drivers:
            self.log_sig.emit(f"Poll every {secs}s")

    # ----- scroll helpers -----

    def _scroll_to_top(self, driver: webdriver.Chrome):
        try:
            body = driver.find_element(By.TAG_NAME, "body")
        except Exception:
            return
        for _ in range(3):
            try:
                body.send_keys(Keys.HOME)
            except Exception:
                break
            time.sleep(0.1)

    def _scroll_window_to_anchor(
        self,
        driver: webdriver.Chrome,
        anchor_name: str,
        max_steps: int = 10,
    ):
        if not anchor_name:
            return

        for _ in range(max_steps):
            rows = parse_visible_users_with_status(driver)
            if not rows:
                return

            first_name = rows[0][0]
            if first_name == anchor_name:
                return

            names = [n for n, _ in rows]
            try:
                idx = names.index(anchor_name)
            except ValueError:
                idx = -1

            try:
                body = driver.find_element(By.TAG_NAME, "body")
            except Exception:
                return

            if idx == -1:
                body.send_keys(Keys.PAGE_DOWN)
            else:
                if idx > 0:
                    body.send_keys(Keys.PAGE_DOWN)
                else:
                    return

            time.sleep(0.2)

    # ----- event recording -----

    def _record_first_seen(
        self,
        rank: int,
        user: str,
        status: str,
        now_dt: datetime.datetime,
    ):
        ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        self.event_sequence.append((ts, rank, user, None, status))
        if len(self.event_sequence) > MAX_EVENTS:
            self.event_sequence = self.event_sequence[-MAX_EVENTS:]
        self._rebuild_events_list()
        self.events_list.scrollToBottom()

    def _record_status_change(
        self,
        rank: int,
        user: str,
        old: str,
        new: str,
        now_dt: datetime.datetime,
    ):
        ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        self.event_sequence.append((ts, rank, user, old, new))
        if len(self.event_sequence) > MAX_EVENTS:
            self.event_sequence = self.event_sequence[-MAX_EVENTS:]
        self._rebuild_events_list()
        self.events_list.scrollToBottom()

    # ----- snapshot writer -----

    def _write_snapshot(self, now: datetime.datetime):
        """
        Overwrite SNAPSHOT_FILE with:
          - all known members (rank, status, optional color)
          - all current events (timestamp, rank, user, old, new)
        """
        members = []
        for name, rank in sorted(self.user_order.items(), key=lambda kv: kv[1]):
            status = self.prev_users.get(name, "offline")
            entry = {
                "name": name,
                "rank": rank,
                "status": status,
            }
            if name in self.user_colors:
                entry["color"] = self.user_colors[name].name()
            members.append(entry)

        events = []
        for ts, erank, user, old, new in self.event_sequence:
            events.append(
                {
                    "timestamp": ts,
                    "rank": erank,
                    "user": user,
                    "old": old,
                    "new": new,
                }
            )

        payload = {
            "generated_at": now.isoformat(),
            "members": members,
            "events": events,
        }

        try:
            with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_sig.emit(f"Snapshot write error: {e}")

    # ----- polling -----

    def _poll_once(self):
        if not self.drivers:
            return

        now_dt = datetime.datetime.now(self.tz)

        # anchor-based scroll
        if not self.top_scrolled_once and self.drivers:
            try:
                self._scroll_to_top(self.drivers[0])
            except Exception:
                pass
            self.top_scrolled_once = True

        for i in range(1, len(self.drivers)):
            anchor = self.window_anchors[i] if i < len(self.window_anchors) else None
            if anchor:
                try:
                    self._scroll_window_to_anchor(self.drivers[i], anchor)
                except Exception:
                    pass

        per_window_rows: List[List[Tuple[str, str]]] = []
        merged: List[Tuple[str, str]] = []
        seen = set()

        for drv in self.drivers:
            try:
                rows = parse_visible_users_with_status(drv)
            except Exception as e:
                self.log_sig.emit(f"Poll error: {e}")
                rows = []

            per_window_rows.append(rows)
            for n, st in rows:
                if n not in seen:
                    seen.add(n)
                    merged.append((n, st))

        if len(self.window_anchors) != len(self.drivers):
            self.window_anchors = [None] * len(self.drivers)
        if self.drivers:
            self.window_anchors[0] = None
        for i in range(1, len(self.drivers)):
            prev_rows = per_window_rows[i - 1] if i - 1 < len(per_window_rows) else []
            if prev_rows:
                self.window_anchors[i] = prev_rows[-1][0]

        current_map: Dict[str, str] = {n: st for n, st in merged}
        prev_map: Dict[str, str] = self.prev_users

        for n, st in current_map.items():
            had_rank_before = n in self.user_order
            rank = self._ensure_rank(n)

            if n in prev_map:
                old_st = prev_map[n]
                if (st or "unknown") != (old_st or "unknown"):
                    self._record_status_change(rank, n, old_st, st, now_dt)
            else:
                if had_rank_before:
                    self._record_status_change(rank, n, "offline", st, now_dt)
                else:
                    self._record_first_seen(rank, n, st, now_dt)

        for n, old_st in prev_map.items():
            if n not in current_map:
                rank = self._ensure_rank(n)
                self._record_status_change(rank, n, old_st, "offline", now_dt)

        self.prev_users = current_map

        self.last_rows = merged
        self._rebuild_users_list()

        self.log_sig.emit(
            f"Poll {now_dt.strftime('%H:%M:%S')} — visible={len(merged)}, "
            f"events={len(self.event_sequence)}"
        )

        # snapshot to JSON every poll
        self._write_snapshot(now_dt)


# ---------- main ----------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = App()
    ui.resize(1000, 550)
    ui.show()
    sys.exit(app.exec())
