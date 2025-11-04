import sys, os, json
from datetime import datetime, timezone
from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QLineEdit, QListWidget, QListWidgetItem,
    QFileDialog, QSpinBox, QMessageBox, QGroupBox, QComboBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

# ---------- Selenium (Edge) ----------
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, JavascriptException
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager

DEFAULT_LOG = "presence_log.json"
APP_CFG = "ui_config.json"

# ---------- Themes ----------
THEMES = {
    # Minimal / OS-ish
    "Classic": """
        QWidget { background: palette(base); color: palette(text); }
        QGroupBox { border: 1px solid palette(mid); border-radius: 6px; margin-top: 10px; }
        QGroupBox::title { left: 8px; padding: 0 4px; }
        QPushButton { padding: 6px 10px; }
        QLineEdit, QSpinBox, QListWidget, QTableWidget { padding: 6px; }
    """,

    # From earlier set (kept so you can keep using them)
    "Dark": """
        QWidget { background: #121212; color: #EAEAEA; }
        QGroupBox { border: 1px solid #2a2a2a; border-radius: 10px; margin-top: 10px; }
        QGroupBox::title { left: 10px; padding: 0 4px; color: #bdbdbd; }
        QPushButton {
            background: #1e1e1e; border: 1px solid #333; border-radius: 10px; padding: 8px 12px;
        }
        QPushButton:hover { background: #242424; }
        QPushButton:disabled { color:#777; border-color:#2a2a2a; }
        QLineEdit, QSpinBox {
            background: #1a1a1a; border: 1px solid #2f2f2f; border-radius: 8px; padding: 6px 8px; color:#eaeaea;
        }
        QListWidget, QTableWidget {
            background: #151515; border: 1px solid #2a2a2a; border-radius: 8px;
        }
        QHeaderView::section {
            background: #1f1f1f; color:#cfcfcf; border: 0; padding: 6px;
        }
        QScrollBar:vertical { background:#161616; width:12px; }
        QScrollBar::handle:vertical { background:#2d2d2d; border-radius:6px; min-height:24px; }
    """,

    "Lewd – Neon": """
        QWidget { background:#0a0b10; color:#E8F6FF; }
        QGroupBox { border:1px solid #2a2f47; border-radius:12px; margin-top:10px; }
        QGroupBox::title { left: 10px; padding:0 6px; color:#8ab4ff; }
        QPushButton {
            background:#111425; color:#e8f6ff; border:1px solid #28305a; border-radius:12px; padding:10px 14px;
        }
        QPushButton:hover { border-color:#6a7dff; box-shadow: 0 0 8px rgba(80,110,255,0.6); }
        QPushButton:pressed { background:#0d1020; }
        QLineEdit, QSpinBox {
            background:#0f1328; color:#ebf3ff; border:1px solid #2b3262; border-radius:10px; padding:8px 10px;
        }
        QListWidget, QTableWidget {
            background:#0c1022; border:1px solid #232949; border-radius:10px;
        }
        QHeaderView::section { background:#121637; color:#a2b6ff; border:0; padding:8px; }
        QScrollBar:vertical { background:#0d1125; width:12px; }
        QScrollBar::handle:vertical { background:#2b3a7a; border-radius:6px; min-height:24px; }
        QTableWidget::item:selected { background:#1b2147; }
    """,

    "Lewd – Velvet": """
        QWidget { background:#12060d; color:#ffeef7; }
        QGroupBox { border:1px solid #3a0d1f; border-radius:12px; margin-top:10px; }
        QGroupBox::title { left:10px; padding:0 6px; color:#ff6fa6; }
        QPushButton {
            background:#1a0a12; color:#ffeef7; border:1px solid #4d1530; border-radius:14px; padding:10px 14px;
        }
        QPushButton:hover { background:#220d18; border-color:#ff5c93; }
        QLineEdit, QSpinBox {
            background:#170812; color:#ffedf7; border:1px solid #48142d; border-radius:10px; padding:8px 10px;
        }
        QListWidget, QTableWidget {
            background:#160811; border:1px solid #3b1024; border-radius:10px;
        }
        QHeaderView::section { background:#1f0c16; color:#ff97bd; border:0; padding:8px; }
        QScrollBar:vertical { background:#14070f; width:12px; }
        QScrollBar::handle:vertical { background:#6b2443; border-radius:6px; min-height:24px; }
        QTableWidget::item:selected { background:#2a0f1f; }
        QLineEdit:focus, QSpinBox:focus { border-color:#ff5c93; }
    """,

    # Your new ones
    "Purple on Black": """
        QWidget { background:#0b0b0f; color:#e9e2ff; }
        QGroupBox { border:1px solid #2a1f3f; border-radius:12px; margin-top:10px; }
        QGroupBox::title { left:10px; padding:0 6px; color:#bda7ff; }
        QPushButton {
            background:#13111a; color:#efe8ff; border:1px solid #3a2a63; border-radius:12px; padding:10px 14px;
        }
        QPushButton:hover { background:#171424; border-color:#7b5bf0; }
        QPushButton:pressed { background:#110f1a; }
        QLineEdit, QSpinBox {
            background:#100f17; color:#f3ecff; border:1px solid #35285c; border-radius:10px; padding:8px 10px;
        }
        QListWidget, QTableWidget {
            background:#0e0d15; border:1px solid #2a1f3f; border-radius:10px;
        }
        QHeaderView::section { background:#151127; color:#c8b9ff; border:0; padding:8px; }
        QScrollBar:vertical { background:#0f0e18; width:12px; }
        QScrollBar::handle:vertical { background:#3e3070; border-radius:6px; min-height:24px; }
        QTableWidget::item:selected { background:#20183c; }
        QLineEdit:focus, QSpinBox:focus { border-color:#7b5bf0; }
    """,

    "Red/Black + Blue": """
        QWidget { background:#0a0a0a; color:#f7f7f7; }
        QGroupBox { border:1px solid #2a2a2a; border-radius:12px; margin-top:10px; }
        QGroupBox::title { left:10px; padding:0 6px; color:#d8d8d8; }
        QPushButton {
            background:#111; color:#f2f2f2; border:1px solid #3a3a3a; border-radius:12px; padding:10px 14px;
        }
        QPushButton:hover { background:#151515; border-color:#e84141; }
        QPushButton:pressed { background:#0d0d0d; }
        QLineEdit, QSpinBox {
            background:#101010; color:#f4f4f4; border:1px solid #333; border-radius:10px; padding:8px 10px;
        }
        QListWidget, QTableWidget {
            background:#0e0e0e; border:1px solid #262626; border-radius:10px;
        }
        QHeaderView::section { background:#151515; color:#e8e8e8; border:0; padding:8px; }
        QTableWidget::item:selected { background:#102031; }
        QLineEdit:focus, QSpinBox:focus { border-color:#3a7bd5; }
        QScrollBar:vertical { background:#0c0c0c; width:12px; }
        QScrollBar::handle:vertical { background:#7a1717; border-radius:6px; min-height:24px; }
        QScrollBar::handle:vertical:hover { background:#9d1f1f; box-shadow: 0 0 8px rgba(58,123,213,0.45); }
    """,
}

def apply_theme(app, theme_name: str):
    css = THEMES.get(theme_name, "")
    app.setStyleSheet(css)

# ---------- Simple UI cfg ----------
def load_ui_cfg():
    try:
        with open(APP_CFG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_ui_cfg(d):
    try:
        with open(APP_CFG, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

# ---------- Helpers ----------
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def append_json(path: str, entry: dict):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([entry], f, indent=2)
        return
    with open(path, "r+", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
        data.append(entry)
        f.seek(0)
        json.dump(data, f, indent=2)
        f.truncate()

# ---------- Selenium controller ----------
class DiscordScanner:
    def __init__(self, driver: Optional[webdriver.Edge] = None):
        self.driver = driver

    def launch(self):
        if self.driver:
            return
        opts = webdriver.EdgeOptions()
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--start-maximized")
        # Optional: reuse your Edge profile to stay logged in
        # opts.add_argument(f'--user-data-dir={os.path.expanduser("~")}/AppData/Local/Microsoft/Edge/User Data')
        # opts.add_argument('--profile-directory=Default')

        self.driver = webdriver.Edge(
            service=EdgeService(EdgeChromiumDriverManager().install()),
            options=opts
        )
        self.driver.get("https://discord.com/login")

    def quit(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None

    def _probe_member_list(self) -> List[Dict]:
        if not self.driver:
            return []
        js = r"""
        const results = [];
        const root = document.querySelector('[class*="membersWrap"]') || document.body;
        if (!root) return results;

        const memberRows = root.querySelectorAll('[class*="member-"], [class*="memberRow-"]');
        memberRows.forEach(row => {
            let name = null;
            const nameEl = row.querySelector('[class*="name-"], [class*="username"]');
            if (nameEl && nameEl.textContent && nameEl.textContent.trim().length > 0) {
                name = nameEl.textContent.trim();
            } else {
                const aria = row.getAttribute('aria-label') || '';
                if (aria) name = aria.split(',')[0].trim();
            }
            if (!name) return;

            let status = 'unknown';
            const statusNode = row.querySelector('[aria-label*="Online"], [aria-label*="Idle"], [aria-label*="Do Not Disturb"], [aria-label*="Offline"]');
            if (statusNode) {
                const s = (statusNode.getAttribute('aria-label') || '').toLowerCase();
                if (s.includes('online')) status = 'online';
                else if (s.includes('idle')) status = 'idle';
                else if (s.includes('do not disturb') || s.includes('dnd')) status = 'dnd';
                else if (s.includes('offline')) status = 'offline';
            } else {
                const titleNode = row.querySelector('svg[aria-label], svg[title]');
                if (titleNode) {
                    const t = (titleNode.getAttribute('aria-label') || titleNode.getAttribute('title') || '').toLowerCase();
                    if (t.includes('online')) status = 'online';
                    else if (t.includes('idle')) status = 'idle';
                    else if (t.includes('disturb')) status = 'dnd';
                    else if (t.includes('offline')) status = 'offline';
                }
            }

            const client = {mobile:false, desktop:false, web:false};
            const clientIcon = row.querySelector('[aria-label*="mobile"], [aria-label*="phone"], [aria-label*="web"], [aria-label*="browser"], [aria-label*="desktop"], [aria-label*="computer"]');
            if (clientIcon) {
                const ci = (clientIcon.getAttribute('aria-label') || '').toLowerCase();
                if (ci.includes('mobile') || ci.includes('phone')) client.mobile = true;
                if (ci.includes('web') || ci.includes('browser')) client.web = true;
                if (ci.includes('desktop') || ci.includes('computer')) client.desktop = true;
            } else {
                const mobileIcon = row.querySelector('[class*="iconMobile"]');
                if (mobileIcon) client.mobile = true;
            }

            results.push({display_name: name, status, client});
        });
        return results;
        """
        try:
            return self.driver.execute_script(js) or []
        except JavascriptException:
            return []

    def scan(self) -> List[Dict]:
        return self._probe_member_list()

# ---------- Main Window ----------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Discord Presence Scanner (Selenium + PyQt6) — Edge")
        self.setMinimumWidth(980)

        # UI state
        self.driver: Optional[DiscordScanner] = None
        self.scanning = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.scan_interval_sec = 20
        self.log_path = DEFAULT_LOG
        self.whitelist: List[str] = []

        # Load UI cfg (theme, etc.)
        self.ui_cfg = load_ui_cfg()
        self.theme_name = self.ui_cfg.get("theme", "Classic")

        # Build UI
        self._build_ui()

        # Apply theme
        self.cmb_theme.setCurrentText(self.theme_name)
        apply_theme(QApplication.instance(), self.theme_name)

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Controls
        ctrl_box = QGroupBox("Controls")
        ctrl_layout = QHBoxLayout()
        btn_launch = QPushButton("Launch Discord in Edge")
        btn_launch.clicked.connect(self.launch_selenium)
        self.btn_start = QPushButton("Start Scanning")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.toggle_scanning)
        self.btn_quit_driver = QPushButton("Close Browser")
        self.btn_quit_driver.setEnabled(False)
        self.btn_quit_driver.clicked.connect(self.close_browser)
        ctrl_layout.addWidget(btn_launch)
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_quit_driver)
        ctrl_box.setLayout(ctrl_layout)
        root.addWidget(ctrl_box)

        # Settings
        config_box = QGroupBox("Settings")
        cfg = QHBoxLayout()
        cfg.addWidget(QLabel("Scan interval (s):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(5, 600)
        self.spin_interval.setValue(self.scan_interval_sec)
        self.spin_interval.valueChanged.connect(lambda v: setattr(self, "scan_interval_sec", v))
        cfg.addWidget(self.spin_interval)

        # Theme
        cfg.addWidget(QLabel("Theme:"))
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(list(THEMES.keys()))
        self.cmb_theme.currentTextChanged.connect(self.on_theme_change)
        cfg.addWidget(self.cmb_theme)

        # Log path
        self.lbl_log = QLineEdit(self.log_path)
        self.lbl_log.setReadOnly(True)
        btn_browse = QPushButton("Log file…")
        btn_browse.clicked.connect(self.choose_log)
        cfg.addWidget(QLabel("Log:"))
        cfg.addWidget(self.lbl_log)
        cfg.addWidget(btn_browse)

        config_box.setLayout(cfg)
        root.addWidget(config_box)

        # Whitelist
        wl_box = QGroupBox("Whitelist (only these display names will be logged)")
        wl = QHBoxLayout()
        self.list_wl = QListWidget()
        wl_controls = QVBoxLayout()
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("Exact display name from member list")
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self.add_whitelist)
        btn_del = QPushButton("Remove Selected")
        btn_del.clicked.connect(self.remove_selected_whitelist)
        wl_controls.addWidget(self.inp_name)
        wl_controls.addWidget(btn_add)
        wl_controls.addWidget(btn_del)
        wl.addWidget(self.list_wl, 1)
        wl.addLayout(wl_controls)
        wl_box.setLayout(wl)
        root.addWidget(wl_box)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Timestamp (UTC)", "Display Name", "Status", "Mobile", "Desktop/Web"])
        root.addWidget(self.table, 1)

        hint = QLabel("In Edge (Selenium), log in to Discord Web, open a server, show the Member List, then Start Scanning.")
        hint.setWordWrap(True)
        root.addWidget(hint)

    # Theme change
    def on_theme_change(self, name: str):
        self.theme_name = name
        apply_theme(QApplication.instance(), name)
        self.ui_cfg["theme"] = name
        save_ui_cfg(self.ui_cfg)

    # UI handlers
    def choose_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Choose log file", self.log_path, "JSON (*.json);;All files (*.*)")
        if path:
            self.log_path = path
            self.lbl_log.setText(path)

    def add_whitelist(self):
        name = self.inp_name.text().strip()
        if not name:
            return
        if name not in self.whitelist:
            self.whitelist.append(name)
            self.list_wl.addItem(QListWidgetItem(name))
        self.inp_name.clear()

    def remove_selected_whitelist(self):
        for item in self.list_wl.selectedItems():
            name = item.text()
            self.whitelist = [n for n in self.whitelist if n != name]
            row = self.list_wl.row(item)
            self.list_wl.takeItem(row)

    def launch_selenium(self):
        if self.driver:
            QMessageBox.information(self, "Already running", "Edge is already launched.")
            return
        try:
            self.driver = DiscordScanner()
            self.driver.launch()
            self.btn_start.setEnabled(True)
            self.btn_quit_driver.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "Launch failed", str(e))

    def close_browser(self):
        if self.scanning:
            self.toggle_scanning()
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.btn_start.setEnabled(False)
            self.btn_quit_driver.setEnabled(False)

    def toggle_scanning(self):
        if not self.driver:
            QMessageBox.warning(self, "No browser", "Launch Edge first.")
            return
        self.scanning = not self.scanning
        if self.scanning:
            self.btn_start.setText("Stop Scanning")
            self._tick()
            self.timer.start(self.scan_interval_sec * 1000)
        else:
            self.btn_start.setText("Start Scanning")
            self.timer.stop()

    def _tick(self):
        if not self.driver:
            return
        try:
            members = self.driver.scan()
        except WebDriverException:
            self._append_row([now_iso(), "Driver error", "—", "—", "—"])
            return

        ts = now_iso()
        for m in members:
            name = (m.get("display_name") or "").strip()
            if self.whitelist and (name not in self.whitelist):
                continue
            status = m.get("status", "unknown")
            client = m.get("client", {}) or {}
            mobile = "yes" if client.get("mobile") else "no"
            deskweb = "desktop" if client.get("desktop") else ("web" if client.get("web") else "unknown")

            # Row coloring based on status
            self._append_row([ts, name, status, mobile, deskweb], status=status)

            # Persist JSON
            entry = {"timestamp": ts, "display_name": name, "status": status, "client": client}
            try:
                append_json(self.log_path, entry)
            except Exception as e:
                self._append_row([now_iso(), "Log write error", str(e), "", ""], status="error")

    def _append_row(self, cols: List[str], status: str = "unknown"):
        r = self.table.rowCount()
        self.table.insertRow(r)

        # Choose a subtle dark-friendly background per status
        bg = None
        status_l = (status or "").lower()
        if status_l == "online":
            bg = QColor(20, 60, 28)      # deep green-ish
        elif status_l == "idle":
            bg = QColor(70, 55, 15)      # amber-ish
        elif status_l in ("dnd", "do not disturb"):
            bg = QColor(70, 20, 28)      # muted red
        elif status_l == "offline":
            bg = QColor(30, 30, 30)      # dark gray
        elif status_l == "error":
            bg = QColor(70, 20, 20)      # error red
        else:
            bg = QColor(25, 25, 35)      # unknown bluish-dark

        for c, val in enumerate(cols):
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
            item.setBackground(bg)
            self.table.setItem(r, c, item)

        self.table.scrollToBottom()

# ---------- Entrypoint ----------
def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    ret = app.exec()
    if w.driver:
        w.driver.quit()
    sys.exit(ret)

if __name__ == "__main__":
    main()
