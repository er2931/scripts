# discord_online_monitor_lite_colored.py
#
# Minimal Discord presence watcher:
#   • Two Chrome windows (top + bottom) using same profile
#   • Shows CURRENT visible users (merged from both windows):
#         001 username — status
#     (001, 002, 003… are persistent ranks per username)
#   • Rank rules:
#       - Guild leader (configured by name) is always rank 001
#       - Every other user gets the next available rank
#       - Ranks NEVER shift when someone goes offline
#   • Logs EVENTS:
#         2025-11-28 10:18:20 — 003 username: offline → online
#   • If a user already has a rank (seen in JSON before), do NOT log "first seen":
#       - Use offline → status instead
#   • Per-user custom colors for NAME:
#       - Double-click user:
#           - If they already have a custom color → reset to default (status tint)
#           - Else → open color picker and save that color
#   • Status words ALWAYS use their own status tint
#   • Only username + statuses are colored; timestamps/arrows/numbers stay default
#   • Ranks + user colors + basic settings are stored in JSON.
#
# Educational use only; scraping Discord's UI may break and may violate ToS.
# For production, use the official Discord API instead.

import os
import sys
import time
import json
import datetime
from typing import List, Tuple, Dict, Optional

import pytz

# ---------- CONFIG ----------
DEFAULT_WAIT_SECS = 40.0      # wait after opening Discord so it fully loads
DEFAULT_POLL_SECS = 2         # default poll interval (seconds)
MAX_EVENTS = 500              # keep last N events in memory/UI
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

# ---------- STATUS COLORS ----------
STATUS_COLORS = {
    "online":  QColor("#22c55e"),  # green
    "idle":    QColor("#eab308"),  # yellow
    "dnd":     QColor("#ef4444"),  # red
    "offline": QColor("#6b7280"),  # gray
    "mobile":  QColor("#3b82f6"),  # blue
    "unknown": QColor("#6366f1"),  # blurple
}


def status_to_color(status: str) -> QColor:
    return STATUS_COLORS.get(status or "unknown", STATUS_COLORS["unknown"])


# Common keywords we’ll search for in aria-labels (English + Spanish variants)
_STATUS_KEYWORDS = [
    "online", "en línea", "en linea",
    "idle", "away", "ausente", "inactivo",
    "do not disturb", "dnd", "busy", "no molestar", "ocupado",
    "offline", "invisible", "desconectado", "sin conexión", "sin conexion",
    "mobile", "móvil", "movil",
]

# ==================== SCRAPING HELPERS ====================

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
    If the members panel isn't visible, try to toggle it.
    (Discord default hotkey is usually 'U' while focused in chat.)
    """
    try:
        if not _find_member_root(driver):
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys("u")
            time.sleep(0.8)
    except Exception:
        pass


def _status_from_text(t: str) -> str:
    """
    Infer a presence status keyword from a label string.
    Supports English + common Spanish Discord translations.
    """
    s = (t or "").lower()

    # MOBILE
    if "mobile" in s or "móvil" in s or "movil" in s:
        return "mobile"

    # ONLINE
    if "online" in s or "en línea" in s or "en linea" in s:
        return "online"

    # IDLE
    if ("idle" in s or "away" in s or
        "ausente" in s or "inactivo" in s):
        return "idle"

    # DND
    if ("do not disturb" in s or "dnd" in s or "busy" in s or
        "no molestar" in s or "ocupado" in s):
        return "dnd"

    # OFFLINE
    if ("offline" in s or "invisible" in s or
        "desconectado" in s or "sin conexión" in s or "sin conexion" in s):
        return "offline"

    return "unknown"


def _find_status_inside_item(elem) -> Optional[str]:
    """
    Look inside a member row for a child element whose aria-label
    clearly contains a status keyword.
    """
    try:
        status_elems = elem.find_elements(By.CSS_SELECTOR, '[aria-label]')
    except Exception:
        status_elems = []

    for se in status_elems:
        try:
            lab = se.get_attribute("aria-label") or ""
        except Exception:
            continue
        low = lab.lower()
        if any(kw in low for kw in _STATUS_KEYWORDS):
            return lab
    return None


def parse_visible_users_with_status(driver) -> List[Tuple[str, str]]:
    """
    Read the Members panel and return [(username, status), ...]
    for all visible users in the given window.
    """
    _ensure_members_panel(driver)
    root = _find_member_root(driver)
    if not root:
        return []

    users: List[Tuple[str, str]] = []
    try:
        items = root.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
    except Exception:
        items = []

    for e in items:
        try:
            main_label = (e.get_attribute("aria-label") or e.text or "").strip()
            if not main_label:
                continue

            # First line is usually "username – status" or "username"
            name = main_label.split("\n")[0]
            if " - " in name:
                name = name.split(" - ", 1)[0]
            name = name.strip()
            if not name:
                continue

            # Try to find a specific status aria-label inside the row
            inner_status_label = _find_status_inside_item(e)
            raw_for_status = inner_status_label or main_label
            status = _status_from_text(raw_for_status)

            users.append((name, status))
        except Exception:
            continue

    # Deduplicate by name, first occurrence wins
    out: List[Tuple[str, str]] = []
    seen = set()
    for n, st in users:
        if n and n not in seen:
            seen.add(n)
            out.append((n, st))
    return out

# ==================== MAIN APP ====================

class App(QWidget):
    log_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # Two separate Chrome instances
        self.driver_top: Optional[webdriver.Chrome] = None
        self.driver_bottom: Optional[webdriver.Chrome] = None
        self.bottom_synced: bool = False

        # persistent config
        self.user_order: Dict[str, int] = {}     # username -> rank
        self.user_colors: Dict[str, QColor] = {} # username -> QColor
        self.settings: Dict[str, object] = {}
        self.next_rank: int = 1
        self.config_path = CONFIG_FILE

        # transient state
        self.prev_users: Dict[str, str] = {}  # last snapshot of users {name: status}
        # events: (timestamp, rank, username, old_status, new_status)
        self.event_sequence: List[Tuple[str, int, str, Optional[str], str]] = []
        self.last_rows: List[Tuple[str, str]] = []   # [(name, status), ...]

        # load config first (so settings are ready)
        self._load_config()

        # timezone
        tz_name = self.settings.get("timezone", DEFAULT_TIMEZONE)
        try:
            self.tz = pytz.timezone(str(tz_name))
        except Exception:
            self.tz = pytz.timezone(DEFAULT_TIMEZONE)

        # poll timer
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_once)

        # build UI and apply settings
        self._build_ui()
        self._apply_dark_theme()
        self._apply_settings_to_ui()

    # ---------- CONFIG PERSISTENCE ----------

    def _recompute_next_rank(self):
        self.next_rank = (max(self.user_order.values()) + 1) if self.user_order else 1

    def _load_config(self):
        if not os.path.exists(self.config_path):
            self.user_order = {}
            self.user_colors = {}
            self.settings = {}
            self.next_rank = 1
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.user_order = {}
            self.user_colors = {}
            self.settings = {}
            self.next_rank = 1
            return

        self.user_order = {str(k): int(v) for k, v in data.get("user_order", {}).items()}
        self.settings = data.get("settings", {})

        # restore colors
        self.user_colors = {}
        for name, hexcol in data.get("user_colors", {}).items():
            try:
                self.user_colors[str(name)] = QColor(str(hexcol))
            except Exception:
                continue

        self._recompute_next_rank()

    def _save_config(self):
        # settings taken from widgets if they exist
        settings = dict(self.settings)  # start with existing to preserve unknown keys
        if hasattr(self, "url_edit"):
            settings["url"] = self.url_edit.text().strip()
        if hasattr(self, "user_data_edit"):
            settings["user_data_dir"] = self.user_data_edit.text().strip()
        if hasattr(self, "profile_edit"):
            settings["profile_dir"] = self.profile_edit.text().strip()
        if hasattr(self, "poll_spin"):
            settings["poll_secs"] = int(self.poll_spin.value())
        if hasattr(self, "leader_edit"):
            settings["guild_leader_name"] = self.leader_edit.text().strip()
        settings["timezone"] = self.tz.zone

        # serialize colors as hex
        color_map = {name: col.name() for name, col in self.user_colors.items()}

        data = {
            "user_order": self.user_order,
            "user_colors": color_map,
            "settings": settings,
        }

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        self.settings = settings

    def _apply_settings_to_ui(self):
        s = self.settings
        # URL
        if "url" in s:
            self.url_edit.setText(str(s["url"]))
        # chrome user data dir
        if "user_data_dir" in s:
            self.user_data_edit.setText(str(s["user_data_dir"]))
        # profile dir
        if "profile_dir" in s:
            self.profile_edit.setText(str(s["profile_dir"]))
        # poll
        if "poll_secs" in s:
            try:
                val = int(s["poll_secs"])
                if val >= 2:
                    self.poll_spin.setValue(val)
            except Exception:
                pass
        # guild leader name
        if "guild_leader_name" in s:
            self.leader_edit.setText(str(s["guild_leader_name"]))

    def _ensure_rank(self, user: str) -> int:
        """
        Assign a persistent rank to a user if they don't have one yet.
        Guild leader (if configured) is forced to rank 001.
        """
        if user in self.user_order:
            return self.user_order[user]

        leader = str(self.settings.get("guild_leader_name", "") or "").strip()

        # If this is the configured guild leader, enforce rank 1
        if leader and user == leader:
            current_leader_name = None
            for uname, r in self.user_order.items():
                if r == 1:
                    current_leader_name = uname
                    break

            if current_leader_name is None:
                # nobody has rank 1 yet
                self.user_order[user] = 1
            else:
                if current_leader_name != user:
                    # move existing rank 1 to the next available slot
                    self._recompute_next_rank()
                    self.user_order[current_leader_name] = self.next_rank
                    self.user_order[user] = 1

            self._recompute_next_rank()
            self._save_config()
            return 1

        # normal user: just give the next rank
        self._recompute_next_rank()
        rank = self.next_rank
        self.user_order[user] = rank
        self._recompute_next_rank()
        self._save_config()
        return rank

    # ---------- UI BUILD ----------

    def _build_ui(self):
        self.setWindowTitle("Discord Presence Monitor — Lite")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- HEADER / CONFIG ---
        header = QVBoxLayout()
        title = QLabel("Discord Presence Monitor (Lite)")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        header.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        row = 0
        # URL
        self.url_edit = QLineEdit("https://discord.com/app")
        grid.addWidget(QLabel("Discord URL:"), row, 0)
        grid.addWidget(self.url_edit, row, 1, 1, 3)
        row += 1

        # user-data dir
        self.user_data_edit = QLineEdit("")
        pick_user_btn = QPushButton("Browse…")
        pick_user_btn.clicked.connect(lambda: self._pick_folder(self.user_data_edit))
        grid.addWidget(QLabel("Chrome user-data dir:"), row, 0)
        grid.addWidget(self.user_data_edit, row, 1, 1, 2)
        grid.addWidget(pick_user_btn, row, 3)
        row += 1

        # profile name
        self.profile_edit = QLineEdit("Default")
        grid.addWidget(QLabel("Chrome profile dir:"), row, 0)
        grid.addWidget(self.profile_edit, row, 1, 1, 3)
        row += 1

        # guild leader name
        self.leader_edit = QLineEdit("")
        grid.addWidget(QLabel("Guild leader name:"), row, 0)
        grid.addWidget(self.leader_edit, row, 1, 1, 3)
        row += 1

        # poll + buttons in one row
        row_box = QHBoxLayout()
        row_box.addWidget(QLabel("Poll (s):"))
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(2, 3600)  # min 2s
        self.poll_spin.setValue(DEFAULT_POLL_SECS)
        row_box.addWidget(self.poll_spin)
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

        # --- MAIN BODY: USERS + EVENTS ---
        body = QHBoxLayout()

        # current users
        users_box = QGroupBox("Current Visible Users (double-click: set/reset color)")
        users_layout = QVBoxLayout(users_box)
        self.users_list = QListWidget()
        users_layout.addWidget(self.users_list)
        body.addWidget(users_box, 1)

        # events
        events_box = QGroupBox("Events (first seen + status changes)")
        events_layout = QVBoxLayout(events_box)
        self.events_list = QListWidget()
        events_layout.addWidget(self.events_list)
        body.addWidget(events_box, 1)

        root.addLayout(body)

        # --- FOOTER status text ---
        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet("font-size: 11px; color: #a0a4ad;")
        root.addWidget(self.status_label)

        # signals
        self.log_sig.connect(self._set_status_text)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.poll_spin.valueChanged.connect(self._update_poll_interval)
        self.poll_spin.valueChanged.connect(lambda _v: self._save_config())

        self.url_edit.editingFinished.connect(self._save_config)
        self.user_data_edit.editingFinished.connect(self._save_config)
        self.profile_edit.editingFinished.connect(self._save_config)
        self.leader_edit.editingFinished.connect(self._save_config)

        # user color editing (per-user reset / assign)
        self.users_list.itemDoubleClicked.connect(self._edit_user_color)

    def _apply_dark_theme(self):
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
            QSpinBox {
                background-color: #111318;
                border: 1px solid #30333b;
                border-radius: 4px;
                padding: 1px 4px;
            }
            QLabel {
                color: #D1D5DB;
            }
        """)

    # ---------- small helpers ----------

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
        """Color for NAME: per-user override > status tint."""
        if user in self.user_colors:
            return self.user_colors[user]
        return status_to_color(status)

    # ---------- ROW WIDGET BUILDERS ----------

    def _make_user_row_widget(self, rank: int, user: str, status: str) -> QWidget:
        """Widget row for the left list: 001 Name — status."""
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        lbl_rank = QLabel(f"{rank:03d}")
        lbl_rank.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        lbl_name = QLabel(user)
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl_name.setStyleSheet(f"color: {self._name_color_for_user(user, status).name()};")

        lbl_sep = QLabel(" — ")
        lbl_sep.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        lbl_status = QLabel(status)
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl_status.setStyleSheet(f"color: {status_to_color(status).name()};")

        layout.addWidget(lbl_rank)
        layout.addWidget(lbl_name)
        layout.addWidget(lbl_sep)
        layout.addWidget(lbl_status)
        layout.addStretch(1)

        return w

    def _make_event_row_widget(self, ts: str, rank: int, user: str,
                               old: Optional[str], new: str) -> QWidget:
        """Widget row for the events list: ts — 003 Name: old → new."""
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        lbl_ts = QLabel(f"{ts} —")
        lbl_ts.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        lbl_rank = QLabel(f"{rank:03d}" if rank > 0 else "---")
        lbl_rank.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if old is None:
            # first seen
            base_status = new or "unknown"
            name_color = self._name_color_for_user(user, base_status).name()
            lbl_name = QLabel(user)
            lbl_name.setStyleSheet(f"color: {name_color};")
            lbl_text = QLabel("first seen")

            layout.addWidget(lbl_ts)
            layout.addWidget(lbl_rank)
            layout.addWidget(lbl_name)
            layout.addWidget(lbl_text)
            layout.addStretch(1)
            return w

        old_s = old or "unknown"
        new_s = new or "unknown"

        name_color = self._name_color_for_user(user, new_s).name()
        old_color = status_to_color(old_s).name()
        new_color = status_to_color(new_s).name()

        lbl_name = QLabel(user)
        lbl_name.setStyleSheet(f"color: {name_color};")
        lbl_colon = QLabel(":")
        lbl_old = QLabel(old_s)
        lbl_old.setStyleSheet(f"color: {old_color};")
        lbl_arrow = QLabel("→")
        lbl_new = QLabel(new_s)
        lbl_new.setStyleSheet(f"color: {new_color};")

        layout.addWidget(lbl_ts)
        layout.addWidget(lbl_rank)
        layout.addWidget(lbl_name)
        layout.addWidget(lbl_colon)
        layout.addWidget(lbl_old)
        layout.addWidget(lbl_arrow)
        layout.addWidget(lbl_new)
        layout.addStretch(1)
        return w

    # ---------- REBUILD / RECOLOR ----------

    def _rebuild_users_list(self):
        """Rebuild users_list from last_rows using persistent ranks, sorted by rank."""
        self.users_list.clear()
        # sort visible users by persistent rank
        rows_sorted = sorted(
            self.last_rows,
            key=lambda ns: self.user_order.get(ns[0], 999999)
        )
        for name, st in rows_sorted:
            rank = self._ensure_rank(name)
            widget = self._make_user_row_widget(rank, name, st)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.users_list.addItem(item)
            self.users_list.setItemWidget(item, widget)

    def _rebuild_events_list(self):
        """Rebuild events_list from event_sequence."""
        self.events_list.clear()
        for ts, rank, user, old, new in self.event_sequence:
            widget = self._make_event_row_widget(ts, rank, user, old, new)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.events_list.addItem(item)
            self.events_list.setItemWidget(item, widget)

    def _recolor_all_items(self):
        """Re-apply per-user colors after changes."""
        self._rebuild_users_list()
        self._rebuild_events_list()

    # ---------- COLOR EDIT (double-click) ----------

    def _edit_user_color(self, item: QListWidgetItem):
        """
        Double-click handler:
        - If user already has a custom color, reset to default (status tint).
        - Otherwise, open color picker and set a custom color.
        """
        row = self.users_list.row(item)
        if row < 0:
            return

        # Figure out which user this row represents (based on current sorted view)
        rows_sorted = sorted(
            self.last_rows,
            key=lambda ns: self.user_order.get(ns[0], 999999)
        )
        if row >= len(rows_sorted):
            return

        name, status = rows_sorted[row]

        if name in self.user_colors:
            # reset to default
            del self.user_colors[name]
            self._save_config()
            self._recolor_all_items()
        else:
            # assign new custom color
            current_color = self._name_color_for_user(name, status)
            color = QColorDialog.getColor(current_color, self, f"Pick color for {name}")
            if color.isValid():
                self.user_colors[name] = color
                self._save_config()
                self._recolor_all_items()

    # ==================== START / STOP ====================

    def start(self):
        if self.driver_top is not None or self.driver_bottom is not None:
            QMessageBox.information(self, "Running", "Already running.")
            return

        # launch Chrome instances
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

            # top window
            self.driver_top = webdriver.Chrome(options=opts)

            # bottom window (second instance)
            self.driver_bottom = webdriver.Chrome(options=opts)

        except Exception as e:
            self.log_sig.emit(f"ERROR launching Chrome: {e}")
            # clean up partially created drivers
            try:
                if self.driver_top:
                    self.driver_top.quit()
            except Exception:
                pass
            try:
                if self.driver_bottom:
                    self.driver_bottom.quit()
            except Exception:
                pass
            self.driver_top = None
            self.driver_bottom = None
            return

        # open Discord and wait for it to load
        url = self.url_edit.text().strip() or "https://discord.com/app"
        for drv in (self.driver_top, self.driver_bottom):
            if drv:
                drv.get(url)
        self.log_sig.emit(f"Opened {url} in 2 windows — waiting {DEFAULT_WAIT_SECS}s to stabilize…")
        QApplication.processEvents()
        time.sleep(max(0.0, DEFAULT_WAIT_SECS))

        # reset state / UI (config persists)
        self.prev_users = {}
        self.event_sequence.clear()
        self.last_rows = []
        self.users_list.clear()
        self.events_list.clear()
        self.bottom_synced = False

        # start timer
        self._update_poll_interval()
        self.poll_timer.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_sig.emit("Monitoring started (top + bottom windows).")

    def stop(self):
        try:
            self.poll_timer.stop()
        except Exception:
            pass

        for drv_attr in ("driver_top", "driver_bottom"):
            drv = getattr(self, drv_attr)
            try:
                if drv:
                    drv.quit()
            except Exception:
                pass
            setattr(self, drv_attr, None)

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log_sig.emit("Stopped.")

    # ---------- poll interval ----------

    def _update_poll_interval(self):
        secs = max(2, int(self.poll_spin.value()))
        self.poll_timer.setInterval(secs * 1000)
        if self.driver_top:
            self.log_sig.emit(f"Poll interval set to {secs}s")

    # ---------- bottom window sync (once) ----------

    def _sync_bottom_window(self, rows_top: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """
        Try once to make the last visible user in the TOP window
        become the first visible user in the BOTTOM window by scrolling.
        """
        if not self.driver_bottom:
            return []

        if not rows_top:
            # if top is empty, just read bottom as-is
            return parse_visible_users_with_status(self.driver_bottom)

        last_name = rows_top[-1][0]

        rows = parse_visible_users_with_status(self.driver_bottom)
        if not rows:
            return []

        for _ in range(10):  # small bounded number of scroll attempts
            first_name = rows[0][0]
            if first_name == last_name:
                return rows
            try:
                body = self.driver_bottom.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.PAGE_DOWN)
            except Exception:
                break
            time.sleep(0.4)
            rows = parse_visible_users_with_status(self.driver_bottom)
            if not rows:
                break

        return rows

    # ==================== EVENT LOGIC ====================

    def _record_first_seen(self, rank: int, user: str, status: str,
                           now_dt: Optional[datetime.datetime] = None):
        """
        Log a 'first seen' event — NO status word in the text,
        but we still color the name (based on status or user color).
        Only used for users who had no rank before this run.
        """
        if now_dt is None:
            now_dt = datetime.datetime.now(self.tz)
        ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        self.event_sequence.append((ts, rank, user, None, status))
        if len(self.event_sequence) > MAX_EVENTS:
            self.event_sequence = self.event_sequence[-MAX_EVENTS:]

        self._rebuild_events_list()
        self.events_list.scrollToBottom()

    def _record_status_change(self, rank: int, user: str, old: str, new: str,
                              now_dt: Optional[datetime.datetime] = None):
        """
        Log a normal status-change event (old → new).
        """
        if now_dt is None:
            now_dt = datetime.datetime.now(self.tz)
        ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        self.event_sequence.append((ts, rank, user, old, new))
        if len(self.event_sequence) > MAX_EVENTS:
            self.event_sequence = self.event_sequence[-MAX_EVENTS:]

        self._rebuild_events_list()
        self.events_list.scrollToBottom()

    # ==================== POLLING ====================

    def _poll_once(self):
        if not self.driver_top:
            return

        now_dt = datetime.datetime.now(self.tz)

        # --- read from top window ---
        try:
            rows_top = parse_visible_users_with_status(self.driver_top)
        except Exception as e:
            self.log_sig.emit(f"Poll error (top): {e}")
            rows_top = []

        # --- read from bottom window ---
        rows_bottom: List[Tuple[str, str]] = []
        if self.driver_bottom:
            try:
                if not self.bottom_synced:
                    rows_bottom = self._sync_bottom_window(rows_top)
                    self.bottom_synced = True
                else:
                    rows_bottom = parse_visible_users_with_status(self.driver_bottom)
            except Exception as e:
                self.log_sig.emit(f"Poll error (bottom): {e}")
                rows_bottom = []

        # merge, keeping first occurrence of each name
        merged: List[Tuple[str, str]] = []
        seen = set()
        for n, st in rows_top + rows_bottom:
            if n not in seen:
                seen.add(n)
                merged.append((n, st))

        current_map: Dict[str, str] = {n: st for n, st in merged}
        prev_map: Dict[str, str] = self.prev_users

        # --- handle users currently visible ---
        for n, st in current_map.items():
            had_rank_before = n in self.user_order
            rank = self._ensure_rank(n)

            if n in prev_map:
                # visible in both snapshots: check for status change
                old_st = prev_map[n]
                if (st or "unknown") != (old_st or "unknown"):
                    self._record_status_change(rank, n, old_st, st, now_dt)
            else:
                # newly visible this poll
                if had_rank_before:
                    # known user returning: offline -> current status
                    self._record_status_change(rank, n, "offline", st, now_dt)
                else:
                    # brand new user: true first seen
                    self._record_first_seen(rank, n, st, now_dt)

        # --- users who disappeared -> treat as going offline ---
        for n, old_st in prev_map.items():
            if n not in current_map:
                rank = self._ensure_rank(n)
                self._record_status_change(rank, n, old_st, "offline", now_dt)

        self.prev_users = current_map

        # update current users list with persistent ranks + colored name/status
        # last_rows: raw merged (unsorted), we sort by rank when building the UI
        self.last_rows = merged[:]
        self._rebuild_users_list()

        self.log_sig.emit(
            f"Poll {now_dt.strftime('%H:%M:%S')} — visible={len(merged)}, "
            f"events={len(self.event_sequence)}"
        )

# ==================== MAIN ====================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = App()
    ui.resize(1000, 550)
    ui.show()
    sys.exit(app.exec())
