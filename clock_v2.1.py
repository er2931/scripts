import sys
import json
import os

from PyQt6.QtCore import QTimer, QTime, Qt
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
)
from PyQt6.QtGui import QFont, QColor


CONFIG_FILE = os.path.join(os.path.dirname(__file__), "clock_config.json")

# Preset colors
PRESET_COLORS = {
    "Cyan Neon": "#6ad9ff",
    "Magenta Pulse": "#ff6adf",
    "Void Gold": "#f5d26a",
    "Emerald Glow": "#6affb4",
    "Soft White": "#f5f7ff",
}

# Preset fonts (they’ll use whatever is available on your system)
PRESET_FONTS = [
    "Segoe UI",
    "Consolas",
    "Calibri",
    "Arial",
    "Courier New",
    "Lucida Console",
]


def load_config():
    default = {
        "time_format": "HH:mm:ss",   # or "hh:mm:ss AP"
        "color": "#6ad9ff",
        "font_size": 48,
        "always_on_top": True,
        "font_family": "Segoe UI",
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            default.update(data)
        except Exception:
            pass
    return default


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


class FloatingClock(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config

        # Window flags
        flags = Qt.WindowType.FramelessWindowHint
        if self.config.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        font_size = int(self.config.get("font_size", 48))
        font_family = self.config.get("font_family", "Segoe UI")
        font = QFont(font_family, font_size, QFont.Weight.Bold)
        self.label.setFont(font)

        color = self.config.get("color", "#6ad9ff")
        self.label.setStyleSheet(f"color: {color}; background: transparent;")

        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(40)
        glow.setColor(QColor(color))
        glow.setOffset(0, 0)
        self.label.setGraphicsEffect(glow)

        layout.addWidget(self.label)
        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
        self.update_time()

        # Size relative to font
        self.resize(font_size * 7, font_size * 2)
        self.drag_pos = None

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

    def update_time(self):
        fmt = self.config.get("time_format", "HH:mm:ss")
        self.label.setText(QTime.currentTime().toString(fmt))


class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clock Settings")
        self.config = load_config()

        # 💠 Cool dark sci-fi style for the settings window
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

        # Color preset dropdown
        self.color_combo = QComboBox()
        for name in PRESET_COLORS.keys():
            self.color_combo.addItem(name)
        self.color_combo.addItem("Custom")

        # Custom color line edit
        self.color_edit = QLineEdit(self.config.get("color", "#6ad9ff"))

        # Decide which option to select based on saved color
        saved_color = self.config.get("color", "#6ad9ff").lower()
        preset_index = -1
        for i, (name, hex_code) in enumerate(PRESET_COLORS.items()):
            if hex_code.lower() == saved_color:
                preset_index = i
                break

        if preset_index >= 0:
            self.color_combo.setCurrentIndex(preset_index)
            self.color_edit.setEnabled(False)
            self.color_edit.setText(PRESET_COLORS[self.color_combo.currentText()])
        else:
            self.color_combo.setCurrentText("Custom")
            self.color_edit.setEnabled(True)

        self.color_combo.currentIndexChanged.connect(self.on_color_combo_changed)

        form.addRow("Color preset:", self.color_combo)
        form.addRow("Custom color (hex):", self.color_edit)

        # Font dropdown
        self.font_combo = QComboBox()
        for fam in PRESET_FONTS:
            self.font_combo.addItem(fam)
        # try to pre-select saved font if present, otherwise default
        saved_font = self.config.get("font_family", "Segoe UI")
        idx = self.font_combo.findText(saved_font)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        form.addRow("Font:", self.font_combo)

        # Font size
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 200)
        self.font_spin.setValue(int(self.config.get("font_size", 48)))
        form.addRow("Font size:", self.font_spin)

        # Always on top
        self.always_check = QCheckBox("Keep clock always on top")
        self.always_check.setChecked(self.config.get("always_on_top", True))
        form.addRow("", self.always_check)

        main_layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        self.start_btn = QPushButton("Start Clock")
        self.start_btn.clicked.connect(self.start_clock)
        btn_layout.addWidget(self.start_btn)

        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

        self.resize(450, 260)

    def on_color_combo_changed(self, index):
        name = self.color_combo.currentText()
        if name == "Custom":
            self.color_edit.setEnabled(True)
        else:
            self.color_edit.setEnabled(False)
            hex_code = PRESET_COLORS.get(name, "#6ad9ff")
            self.color_edit.setText(hex_code)

    def start_clock(self):
        time_format = self.format_combo.currentData()

        # Resolve color based on combo
        name = self.color_combo.currentText()
        if name == "Custom":
            color = self.color_edit.text().strip() or "#6ad9ff"
        else:
            color = PRESET_COLORS.get(name, "#6ad9ff")

        font_family = self.font_combo.currentText()

        config = {
            "time_format": time_format,
            "color": color,
            "font_size": int(self.font_spin.value()),
            "always_on_top": bool(self.always_check.isChecked()),
            "font_family": font_family,
        }

        save_config(config)

        self.clock = FloatingClock(config)
        self.clock.show()
        self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    settings = SettingsWindow()
    settings.show()
    sys.exit(app.exec())
