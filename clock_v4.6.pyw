import sys
import json
import os
from dataclasses import dataclass, asdict

from PyQt6.QtCore import QTimer, QTime, Qt, QRectF
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QComboBox,
    QGraphicsDropShadowEffect,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
)
from PyQt6.QtGui import QFont, QColor, QPainter, QPainterPath


CONFIG_FILE = os.path.join(os.path.dirname(__file__), "clock_config.json")

# 🎨 Base preset colors (built-in)
PRESET_COLORS = {
    "Cyan Neon": "#6ad9ff",
    "Magenta Pulse": "#ff6adf",
    "Void Gold": "#f5d26a",
    "Luminara Pink": "#ff9ad9",
    "Abyss Blue": "#4c6dff",
    "Inferno Orange": "#ff9750",
    "Emerald Glow": "#6affb4",
    "Soft White": "#f5f7ff",
    "Glitch Green": "#7bff6a",
}

# Preset fonts
PRESET_FONTS = [
    "Segoe UI",
    "Consolas",
    "Calibri",
    "Arial",
    "Courier New",
    "Lucida Console",
]

# 🧬 Meta-themed presets
THEME_PRESETS = {
    "Void Sigil": {
        "color": "#f5d26a",         # Void gold
        "font_family": "Consolas",
        "font_size": 46,
        "glow_radius": 70,
        "show_panel": True,
        "time_format": "HH:mm:ss",
        "always_on_top": True,
    },
    "Luminara Bloom": {
        "color": "#ff9ad9",         # soft pink
        "font_family": "Segoe UI",
        "font_size": 50,
        "glow_radius": 80,
        "show_panel": True,
        "time_format": "HH:mm:ss",
        "always_on_top": True,
    },
    "Presence HUD": {
        "color": "#6ad9ff",         # cyan neon
        "font_family": "Consolas",
        "font_size": 40,
        "glow_radius": 45,
        "show_panel": False,
        "time_format": "HH:mm:ss",
        "always_on_top": True,
    },
    "Architect Grid": {
        "color": "#7bff6a",         # glitch green
        "font_family": "Lucida Console",
        "font_size": 38,
        "glow_radius": 55,
        "show_panel": False,
        "time_format": "HH:mm:ss",
        "always_on_top": True,
    },
    "Abyss Station": {
        "color": "#4c6dff",         # deep blue
        "font_family": "Segoe UI",
        "font_size": 44,
        "glow_radius": 60,
        "show_panel": True,
        "time_format": "HH:mm:ss",
        "always_on_top": True,
    },
}


@dataclass
class Alarm:
    time: str = "07:00"          # "HH:mm"
    label: str = "Alarm"
    action: str = "sound"        # "sound" or "startfile"
    file_path: str = ""
    enabled: bool = True

    @staticmethod
    def from_dict(data: dict) -> "Alarm":
        # allow old key "path" for compatibility
        file_path = data.get("file_path", data.get("path", ""))
        return Alarm(
            time=data.get("time", "07:00"),
            label=data.get("label", "Alarm"),
            action=data.get("action", "sound"),
            file_path=file_path,
            enabled=bool(data.get("enabled", True)),
        )


def load_config():
    default = {
        "time_format": "HH:mm:ss",   # or "hh:mm:ss AP"
        "color": "#6ad9ff",
        "font_size": 48,
        "always_on_top": True,
        "font_family": "Segoe UI",
        "alarms": [],               # list of alarm dicts
        "glow_radius": 48,
        "show_panel": False,
        "theme_name": "Custom",     # remember last theme preset
        "custom_colors": [],        # [{ "name": str, "hex": str }]
        "custom_fonts": [],         # [ "Font Name", ... ]
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            default.update(data)
        except Exception:
            pass
    # normalize alarms to list[Alarm]
    alarms = []
    for a in default.get("alarms", []):
        try:
            alarms.append(Alarm.from_dict(a))
        except Exception:
            continue
    default["alarms"] = alarms
    return default


def save_config(cfg):
    cfg_to_save = dict(cfg)
    cfg_to_save["alarms"] = [asdict(a) for a in cfg.get("alarms", [])]
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg_to_save, f, indent=2)
    except Exception:
        pass


class FloatingClock(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.alarms = config.get("alarms", [])

        # Window flags
        flags = Qt.WindowType.FramelessWindowHint
        if self.config.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.show_panel = bool(self.config.get("show_panel", False))
        self.color = QColor(self.config.get("color", "#6ad9ff"))
        self.glow_radius = int(self.config.get("glow_radius", 48))

        # 🔹 add padding so glow never hits window edges
        glow_pad = self.glow_radius // 2

        layout = QVBoxLayout()
        layout.setContentsMargins(glow_pad, glow_pad, glow_pad, glow_pad)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        font_size = int(self.config.get("font_size", 48))
        font_family = self.config.get("font_family", "Segoe UI")
        font = QFont(font_family, font_size, QFont.Weight.Bold)
        self.label.setFont(font)

        # Text only – no background, panel is drawn by paintEvent
        self.label.setStyleSheet(f"color: {self.color.name()}; background: transparent;")

        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(self.glow_radius)
        glow.setColor(self.color)
        glow.setOffset(0, 0)
        self.label.setGraphicsEffect(glow)

        # ⬇️ Ensure the label itself is centered in the widget
        layout.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.update_time()

        # Size relative to font
        self.resize(font_size * 7, font_size * 2)
        self.drag_pos = None

        # For alarm firing dedupe per minute
        self.current_minute = ""
        self.fired_this_minute = set()  # alarm indices fired in this minute

    # 🔷 Draw rounded panel here – no corners, no mask hacks
    def paintEvent(self, event):
        if not self.show_panel:
            return

        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )

        rect = self.rect()
        if rect.isNull():
            return

        # margin based on glow so panel stays inside it
        glow_pad = self.glow_radius // 2
        panel_margin = glow_pad // 2 if glow_pad > 0 else 8

        r = QRectF(
            panel_margin,
            panel_margin,
            rect.width() - panel_margin * 2,
            rect.height() - panel_margin * 2,
        )

        path = QPainterPath()
        radius = 20.0
        path.addRoundedRect(r, radius, radius)

        # Panel fill (dark, slightly translucent)
        panel_color = QColor(5, 7, 18, 190)  # a bit softer alpha
        painter.fillPath(path, panel_color)

        # Border using a softened version of the main color
        border_color = QColor(self.color)
        border_color.setAlpha(150)
        painter.setPen(border_color)
        painter.drawPath(path)

    # Dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.drag_pos:
            diff = event.globalPosition().toPoint() - self.drag_pos
            self.move(self.x() + diff.x(), self.y() + diff.y())
            self.drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def _tick(self):
        self.update_time()
        self.check_alarms()

    def update_time(self):
        fmt = self.config.get("time_format", "HH:mm:ss")
        self.label.setText(QTime.currentTime().toString(fmt))

    def check_alarms(self):
        now = QTime.currentTime()
        minute_str = now.toString("HH:mm")

        # reset dedupe when minute changes
        if minute_str != self.current_minute:
            self.current_minute = minute_str
            self.fired_this_minute.clear()

        for idx, alarm in enumerate(self.alarms):
            if not alarm.enabled:
                continue
            if alarm.time != minute_str:
                continue
            if idx in self.fired_this_minute:
                continue

            self.fired_this_minute.add(idx)
            self.fire_alarm(alarm)

    def fire_alarm(self, alarm: Alarm):
        label = alarm.label or "Alarm"
        try:
            msg = QMessageBox(self)
            msg.setWindowTitle("Alarm")
            msg.setText(f"{alarm.time}  –  {label}")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.setWindowModality(Qt.WindowModality.NonModal)
            msg.show()
        except Exception:
            pass

        if alarm.file_path:
            if hasattr(os, "startfile"):
                try:
                    os.startfile(alarm.file_path)
                except Exception:
                    pass


class AlarmDialog(QDialog):
    def __init__(self, parent=None, alarm: Alarm | None = None):
        super().__init__(parent)
        self.setWindowTitle("Alarm")
        self.setModal(True)

        self.setStyleSheet("""
            QDialog {
                background-color: #050712;
                color: #e0e4ff;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QLabel {
                color: #a8b0ff;
            }
            QLineEdit, QComboBox {
                background-color: #0e1220;
                border: 1px solid #272f4a;
                border-radius: 6px;
                padding: 4px 6px;
                color: #e0e4ff;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #6ad9ff;
            }
            QPushButton {
                background-color: #1b2340;
                border-radius: 8px;
                padding: 6px 10px;
                border: 1px solid #3b4c8a;
                color: #e0e4ff;
            }
            QPushButton:hover {
                background-color: #243060;
            }
            QPushButton:pressed {
                background-color: #141a36;
            }
            QCheckBox {
                spacing: 6px;
            }
        """)

        self.alarm = alarm or Alarm()

        layout = QVBoxLayout()
        form = QFormLayout()

        self.time_edit = QLineEdit(self.alarm.time)
        form.addRow("Time (HH:mm):", self.time_edit)

        self.label_edit = QLineEdit(self.alarm.label)
        form.addRow("Label:", self.label_edit)

        self.action_combo = QComboBox()
        self.action_combo.addItem("Play sound", "sound")
        self.action_combo.addItem("Open file/program", "startfile")
        if self.alarm.action == "startfile":
            self.action_combo.setCurrentIndex(1)
        else:
            self.action_combo.setCurrentIndex(0)
        form.addRow("Action:", self.action_combo)

        # file path + browse
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self.alarm.file_path)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(browse_btn)
        form.addRow("File path:", path_layout)

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(self.alarm.enabled)
        form.addRow("", self.enabled_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self.resize(460, 220)

    def browse_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file", "", "All files (*.*)")
        if path:
            self.path_edit.setText(path)

    def get_alarm(self) -> Alarm | None:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None

        time_str = self.time_edit.text().strip()
        if len(time_str) != 5 or time_str[2] != ":":
            QMessageBox.warning(self, "Invalid time", "Time must be in HH:mm format.")
            return None

        action = self.action_combo.currentData()
        label = self.label_edit.text().strip()
        enabled = self.enabled_check.isChecked()
        file_path = self.path_edit.text().strip()

        return Alarm(
            time=time_str,
            label=label or "Alarm",
            action=action,
            file_path=file_path,
            enabled=enabled,
        )


class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clock Settings")
        self.config = load_config()

        # load custom things from config
        self.custom_colors = self.config.get("custom_colors", [])
        self.custom_fonts = self.config.get("custom_fonts", [])

        # build combined color map (built-ins + custom)
        self.color_map = dict(PRESET_COLORS)
        for c in self.custom_colors:
            name = c.get("name", "").strip() or "Custom"
            hex_code = c.get("hex", "#ffffff")
            label = f"* {name}"
            self.color_map[label] = hex_code

        self.setStyleSheet("""
            QWidget {
                background-color: #050712;
                color: #e0e4ff;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QLabel {
                color: #a8b0ff;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #0e1220;
                border: 1px solid #272f4a;
                border-radius: 6px;
                padding: 4px 6px;
                color: #e0e4ff;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #6ad9ff;
            }
            QPushButton {
                background-color: #1b2340;
                border-radius: 8px;
                padding: 8px 14px;
                border: 1px solid #3b4c8a;
                color: #e0e4ff;
            }
            QPushButton:hover {
                background-color: #243060;
            }
            QPushButton:pressed {
                background-color: #141a36;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #3b4c8a;
                background: #0e1220;
            }
            QCheckBox::indicator:checked {
                background: #6ad9ff;
                border: 1px solid #6ad9ff;
            }
            QComboBox QAbstractItemView {
                background-color: #0e1220;
                selection-background-color: #243060;
                selection-color: #e0e4ff;
            }
        """)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # 🔹 Theme preset
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Custom / Manual")
        for name in THEME_PRESETS.keys():
            self.theme_combo.addItem(name)

        # restore last theme if any
        saved_theme = self.config.get("theme_name", "Custom")
        idx_theme = self.theme_combo.findText(saved_theme)
        if idx_theme >= 0:
            self.theme_combo.setCurrentIndex(idx_theme)
        else:
            self.theme_combo.setCurrentIndex(0)

        self.theme_combo.currentIndexChanged.connect(self.apply_theme_preset)

        form.addRow("Theme preset:", self.theme_combo)

        # Time format
        self.format_combo = QComboBox()
        self.format_combo.addItem("24-hour (HH:mm:ss)", "HH:mm:ss")
        self.format_combo.addItem("12-hour (hh:mm:ss AP)", "hh:mm:ss AP")
        current_fmt = self.config.get("time_format", "HH:mm:ss")
        if current_fmt.startswith("HH"):
            self.format_combo.setCurrentIndex(0)
        else:
            self.format_combo.setCurrentIndex(1)
        form.addRow("Time format:", self.format_combo)

        # Color preset dropdown (built-ins + custom)
        self.color_combo = QComboBox()
        for name in self.color_map.keys():
            self.color_combo.addItem(name)
        self.color_combo.addItem("Custom")

        self.color_edit = QLineEdit(self.config.get("color", "#6ad9ff"))

        # find which entry matches the saved color
        saved_color = self.config.get("color", "#6ad9ff").lower()
        match_index = -1
        for i in range(self.color_combo.count()):
            text = self.color_combo.itemText(i)
            if text == "Custom":
                continue
            hex_code = self.color_map.get(text, "").lower()
            if hex_code == saved_color:
                match_index = i
                break

        if match_index >= 0:
            self.color_combo.setCurrentIndex(match_index)
            self.color_edit.setEnabled(False)
            self.color_edit.setText(self.color_map[self.color_combo.currentText()])
        else:
            # no matching preset, treat as manual
            idx_custom = self.color_combo.findText("Custom")
            if idx_custom >= 0:
                self.color_combo.setCurrentIndex(idx_custom)
            self.color_edit.setEnabled(True)

        self.color_combo.currentIndexChanged.connect(self.on_color_combo_changed)

        form.addRow("Color preset:", self.color_combo)
        form.addRow("Custom color (hex):", self.color_edit)

        # Controls to add new color preset
        color_add_layout = QHBoxLayout()
        self.new_color_name_edit = QLineEdit()
        self.new_color_name_edit.setPlaceholderText("Name")
        self.new_color_value_edit = QLineEdit()
        self.new_color_value_edit.setPlaceholderText("#rrggbb (optional)")
        self.add_color_btn = QPushButton("Save color")
        self.add_color_btn.clicked.connect(self.add_color_preset)
        color_add_layout.addWidget(self.new_color_name_edit)
        color_add_layout.addWidget(self.new_color_value_edit)
        color_add_layout.addWidget(self.add_color_btn)
        form.addRow("Add color preset:", color_add_layout)

        # Font dropdown (built-ins + custom)
        self.font_combo = QComboBox()
        for fam in PRESET_FONTS:
            self.font_combo.addItem(fam)
        for fam in self.custom_fonts:
            if self.font_combo.findText(fam) == -1:
                self.font_combo.addItem(fam)

        saved_font = self.config.get("font_family", "Segoe UI")
        idx = self.font_combo.findText(saved_font)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        form.addRow("Font:", self.font_combo)

        # Controls to add custom font name
        font_add_layout = QHBoxLayout()
        self.new_font_edit = QLineEdit()
        self.new_font_edit.setPlaceholderText("Font family name")
        self.add_font_btn = QPushButton("Save font")
        self.add_font_btn.clicked.connect(self.add_font_preset)
        font_add_layout.addWidget(self.new_font_edit)
        font_add_layout.addWidget(self.add_font_btn)
        form.addRow("Add font to list:", font_add_layout)

        # Font size
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 200)
        self.font_spin.setValue(int(self.config.get("font_size", 48)))
        form.addRow("Font size:", self.font_spin)

        # Glow radius
        self.glow_spin = QSpinBox()
        self.glow_spin.setRange(5, 120)
        self.glow_spin.setValue(int(self.config.get("glow_radius", 48)))
        form.addRow("Glow radius:", self.glow_spin)

        # Show panel
        self.panel_check = QCheckBox("Show soft background panel")
        self.panel_check.setChecked(bool(self.config.get("show_panel", False)))
        form.addRow("", self.panel_check)

        # Always on top
        self.always_check = QCheckBox("Keep clock always on top")
        self.always_check.setChecked(self.config.get("always_on_top", True))
        form.addRow("", self.always_check)

        main_layout.addLayout(form)

        # Alarms section
        alarms_label = QLabel("Alarms")
        alarms_label.setStyleSheet("color: #e0e4ff; font-weight: bold;")
        main_layout.addWidget(alarms_label)

        alarms_layout = QHBoxLayout()
        self.alarm_list = QListWidget()
        self.alarm_list.setMinimumHeight(130)

        self.refresh_alarm_list()

        btn_col = QVBoxLayout()
        add_btn = QPushButton("Add")
        edit_btn = QPushButton("Edit")
        del_btn = QPushButton("Delete")

        add_btn.clicked.connect(self.add_alarm)
        edit_btn.clicked.connect(self.edit_alarm)
        del_btn.clicked.connect(self.delete_alarm)

        btn_col.addWidget(add_btn)
        btn_col.addWidget(edit_btn)
        btn_col.addWidget(del_btn)
        btn_col.addStretch(1)

        alarms_layout.addWidget(self.alarm_list)
        alarms_layout.addLayout(btn_col)
        main_layout.addLayout(alarms_layout)

        # Start button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.start_btn = QPushButton("Start Clock")
        self.start_btn.clicked.connect(self.start_clock)
        btn_layout.addWidget(self.start_btn)

        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

        self.resize(620, 520)

        # apply saved theme preset (if not Custom) once fields exist
        if self.theme_combo.currentIndex() > 0:
            self.apply_theme_preset(self.theme_combo.currentIndex())

    # ---------- helpers for saving config ----------

    def collect_config_from_ui(self):
        """Read all widgets into self.config (so saving/closing is consistent)."""
        time_format = self.format_combo.currentData()

        name = self.color_combo.currentText()
        if name == "Custom":
            color = self.color_edit.text().strip() or "#6ad9ff"
        else:
            color = self.color_map.get(name, "#6ad9ff")

        font_family = self.font_combo.currentText()

        self.config["time_format"] = time_format
        self.config["color"] = color
        self.config["font_size"] = int(self.font_spin.value())
        self.config["always_on_top"] = bool(self.always_check.isChecked())
        self.config["font_family"] = font_family
        self.config["glow_radius"] = int(self.glow_spin.value())
        self.config["show_panel"] = bool(self.panel_check.isChecked())
        self.config["theme_name"] = self.theme_combo.currentText()
        self.config["custom_colors"] = self.custom_colors
        self.config["custom_fonts"] = self.custom_fonts

    # ---------- UI callbacks ----------

    def on_color_combo_changed(self, index):
        name = self.color_combo.currentText()
        if name == "Custom":
            self.color_edit.setEnabled(True)
        else:
            self.color_edit.setEnabled(False)
            hex_code = self.color_map.get(name, "#6ad9ff")
            self.color_edit.setText(hex_code)

    def add_color_preset(self):
        name = self.new_color_name_edit.text().strip()
        hex_code = self.new_color_value_edit.text().strip() or self.color_edit.text().strip()
        if not name or not hex_code:
            return

        label = f"* {name}"

        # Avoid duplicates
        for c in self.custom_colors:
            if c.get("name") == name and c.get("hex") == hex_code:
                break
        else:
            self.custom_colors.append({"name": name, "hex": hex_code})

        self.color_map[label] = hex_code

        # Insert before "Custom" entry
        idx_custom = self.color_combo.findText("Custom")
        if self.color_combo.findText(label) == -1:
            if idx_custom == -1:
                self.color_combo.addItem(label)
            else:
                self.color_combo.insertItem(idx_custom, label)

        idx_label = self.color_combo.findText(label)
        if idx_label >= 0:
            self.color_combo.setCurrentIndex(idx_label)
            self.color_edit.setEnabled(False)
            self.color_edit.setText(hex_code)

        self.new_color_name_edit.clear()
        self.new_color_value_edit.clear()

    def add_font_preset(self):
        fam = self.new_font_edit.text().strip()
        if not fam:
            return
        if fam not in self.custom_fonts:
            self.custom_fonts.append(fam)
        if self.font_combo.findText(fam) == -1:
            self.font_combo.addItem(fam)
        idx = self.font_combo.findText(fam)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.new_font_edit.clear()

    def apply_theme_preset(self, index: int):
        # index 0 = Custom/manual
        if index <= 0:
            return
        theme_name = self.theme_combo.currentText()
        preset = THEME_PRESETS.get(theme_name)
        if not preset:
            return

        # Apply preset values to controls
        color = preset.get("color", "#6ad9ff")
        font_family = preset.get("font_family", "Segoe UI")
        font_size = preset.get("font_size", 48)
        glow_radius = preset.get("glow_radius", 48)
        show_panel = preset.get("show_panel", False)
        time_format = preset.get("time_format", "HH:mm:ss")
        always_on_top = preset.get("always_on_top", True)

        # Color → force to custom (manual hex)
        idx_custom = self.color_combo.findText("Custom")
        if idx_custom >= 0:
            self.color_combo.setCurrentIndex(idx_custom)
        self.color_edit.setEnabled(True)
        self.color_edit.setText(color)

        # Font
        idx = self.font_combo.findText(font_family)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_spin.setValue(font_size)

        # Glow + panel
        self.glow_spin.setValue(glow_radius)
        self.panel_check.setChecked(show_panel)

        # Time format
        if time_format.startswith("HH"):
            self.format_combo.setCurrentIndex(0)
        else:
            self.format_combo.setCurrentIndex(1)

        # Always on top
        self.always_check.setChecked(always_on_top)

    # Alarm helpers
    def refresh_alarm_list(self):
        self.alarm_list.clear()
        for alarm in self.config.get("alarms", []):
            status = "✓" if alarm.enabled else "✕"
            action_text = "sound" if alarm.action == "sound" else "startfile"
            fp = os.path.basename(alarm.file_path) if alarm.file_path else ""
            suffix = f" [{fp}]" if fp else ""
            text = f"[{status}] {alarm.time} – {alarm.label} ({action_text}){suffix}"
            item = QListWidgetItem(text)
            self.alarm_list.addItem(item)

    def add_alarm(self):
        dlg = AlarmDialog(self)
        new_alarm = dlg.get_alarm()
        if new_alarm:
            self.config["alarms"].append(new_alarm)
            self.refresh_alarm_list()

    def edit_alarm(self):
        row = self.alarm_list.currentRow()
        if row < 0:
            return
        cur_alarm = self.config["alarms"][row]
        dlg = AlarmDialog(self, cur_alarm)
        new_alarm = dlg.get_alarm()
        if new_alarm:
            self.config["alarms"][row] = new_alarm
            self.refresh_alarm_list()

    def delete_alarm(self):
        row = self.alarm_list.currentRow()
        if row < 0:
            return
        del self.config["alarms"][row]
        self.refresh_alarm_list()

    def start_clock(self):
        # read widgets → config, then save
        self.collect_config_from_ui()
        save_config(self.config)

        self.clock = FloatingClock(self.config)
        self.clock.show()

        # Center the clock window on the primary screen
        app = QApplication.instance()
        if app is not None:
            screen_geo = app.primaryScreen().availableGeometry()
            frame_geo = self.clock.frameGeometry()
            frame_geo.moveCenter(screen_geo.center())
            self.clock.move(frame_geo.topLeft())

        # 🔹 keep settings window minimized instead of closing
        self.showMinimized()

    def closeEvent(self, event):
        # when you close the settings window, also persist current values
        self.collect_config_from_ui()
        save_config(self.config)
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    settings = SettingsWindow()
    settings.show()
    sys.exit(app.exec())
