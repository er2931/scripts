import sys
import os
import json
import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Dict, Tuple, Set

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QSlider,
    QMessageBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QFileDialog,
    QDoubleSpinBox,
)

# -------------------------------------------------
# OPTIONAL AUDIO IMPORT
# -------------------------------------------------

try:
    import sounddevice as sd  # pip install sounddevice
    HAVE_AUDIO = True
except ImportError:
    sd = None
    HAVE_AUDIO = False


# -------------------------------------------------
# DATA CLASSES
# -------------------------------------------------

@dataclass
class FunctionDef:
    name: str
    label: str
    expr_str: str
    func: Callable[[float], float]
    color: str  # "#RRGGBB"


@dataclass
class ThemeConfig:
    canvas_bg: str = "#05060A"
    canvas_midline: str = "#1E1E28"
    panel_bg: str = "#0B0D18"
    panel_text: str = "#FFFFFF"
    pointer_ring: str = "#FFFFFF"


# -------------------------------------------------
# SAFE EXPRESSION ENGINE
# -------------------------------------------------

SAFE_MATH_NAMESPACE: Dict[str, object] = {
    "pi": math.pi,
    "e": math.e,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
}


def make_func_from_expr(expression: str) -> Callable[[float], float]:
    expr = expression.strip()
    if not expr:
        raise ValueError("Empty expression")

    try:
        code = compile(expr, "<function_expr>", "eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid expression syntax: {e}") from e

    def f(t: float) -> float:
        local_ns = {"t": t}
        try:
            return float(
                eval(
                    code,
                    {"__builtins__": {}},
                    {**SAFE_MATH_NAMESPACE, **local_ns},
                )
            )
        except Exception:
            return 0.0

    return f


# -------------------------------------------------
# DEFAULT FUNCTIONS (fallback)
# -------------------------------------------------

def get_default_functions() -> List[FunctionDef]:
    return [
        FunctionDef(
            name="sine",
            label="Sine wave",
            expr_str="sin(t)",
            func=make_func_from_expr("sin(t)"),
            color="#33AADD",
        ),
        FunctionDef(
            name="cosine",
            label="Cosine wave",
            expr_str="cos(t)",
            func=make_func_from_expr("cos(t)"),
            color="#FF8844",
        ),
        FunctionDef(
            name="lissajous_like",
            label="Lissajous-like (sin * cos)",
            expr_str="sin(t) * cos(3*t)",
            func=make_func_from_expr("sin(t) * cos(3*t)"),
            color="#AA55FF",
        ),
        FunctionDef(
            name="beat",
            label="Beat pattern (sin + sin)",
            expr_str="sin(t) + 0.5*sin(1.7*t)",
            func=make_func_from_expr("sin(t) + 0.5*sin(1.7*t)"),
            color="#66CC66",
        ),
        FunctionDef(
            name="decay",
            label="Damped wave (exp * sin)",
            expr_str="exp(-0.2*t) * sin(5*t)",
            func=make_func_from_expr("exp(-0.2*t) * sin(5*t)"),
            color="#DD3366",
        ),
    ]


# -------------------------------------------------
# LOAD ALL FUNCTIONS FROM tri*.json
# -------------------------------------------------

def load_all_tri_functions(
    base_dir: str, prefix: str = "tri", ext: str = ".json"
) -> Optional[List[FunctionDef]]:
    all_funcs: List[FunctionDef] = []
    seen: Set[Tuple[str, str]] = set()

    try:
        files = os.listdir(base_dir)
    except Exception:
        return None

    for fname in files:
        if not fname.lower().endswith(ext):
            continue
        if not fname.startswith(prefix):
            continue

        path = os.path.join(base_dir, fname)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        if not isinstance(data, list):
            continue

        for item in data:
            try:
                name = str(item.get("name", "unnamed"))
                label = str(item.get("label", name))
                expr = str(item.get("expr", "sin(t)"))
                color = str(item.get("color", "#FFFFFF"))

                key = (name, expr)
                if key in seen:
                    continue

                fn = make_func_from_expr(expr)
                all_funcs.append(
                    FunctionDef(
                        name=name,
                        label=label,
                        expr_str=expr,
                        func=fn,
                        color=color,
                    )
                )
                seen.add(key)
            except Exception:
                continue

    return all_funcs or None


# -------------------------------------------------
# THEME LOAD/SAVE
# -------------------------------------------------

def load_theme_config(base_dir: str) -> ThemeConfig:
    path = os.path.join(base_dir, "theme_config.json")
    if not os.path.exists(path):
        return ThemeConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ThemeConfig()

    return ThemeConfig(
        canvas_bg=data.get("canvas_bg", "#05060A"),
        canvas_midline=data.get("canvas_midline", "#1E1E28"),
        panel_bg=data.get("panel_bg", "#0B0D18"),
        panel_text=data.get("panel_text", "#FFFFFF"),
        pointer_ring=data.get("pointer_ring", "#FFFFFF"),
    )


def save_theme_config(base_dir: str, theme: ThemeConfig):
    path = os.path.join(base_dir, "theme_config.json")
    data = {
        "canvas_bg": theme.canvas_bg,
        "canvas_midline": theme.canvas_midline,
        "panel_bg": theme.panel_bg,
        "panel_text": theme.panel_text,
        "pointer_ring": theme.pointer_ring,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# -------------------------------------------------
# EXPRESSION PREVIEW CANVAS (used in popups)
# -------------------------------------------------

class ExpressionPreviewCanvas(QWidget):
    def __init__(self, theme: Optional[ThemeConfig] = None, parent=None):
        super().__init__(parent)
        self.func: Optional[Callable[[float], float]] = None
        self.color = "#8888FF"
        self.time = 0.0
        self.time_speed = 1.0
        self.amplitude = 0.8
        self.frequency = 1.0
        self.line_width = 2
        self.theme = theme or ThemeConfig()

        self.setMinimumHeight(120)
        self.setAutoFillBackground(True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(16)

    def set_theme(self, theme: ThemeConfig):
        self.theme = theme
        self.update()

    def set_function(self, func: Optional[Callable[[float], float]], color: str):
        self.func = func
        self.color = color or "#8888FF"
        self.update()

    def on_tick(self):
        self.time += 0.016 * self.time_speed
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self.theme.canvas_bg))

        if self.func is None:
            painter.setPen(QColor("#555555"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No preview")
            painter.end()
            return

        w = self.width()
        h = self.height()

        color = QColor(self.color)
        pen = QPen(color)
        pen.setWidth(self.line_width)
        painter.setPen(pen)

        center_y = h / 2.0
        scale_y = (h / 2.0)

        path = QPainterPath()
        samples = max(200, w)
        started = False

        for i in range(samples):
            x = w * i / (samples - 1)
            base = 2.0 * math.pi * (i / (samples - 1))
            t = self.frequency * (base + self.time)
            y_raw = self.func(t)
            y_val = self.amplitude * y_raw
            y = center_y - y_val * scale_y

            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)

        painter.drawPath(path)
        painter.end()


# -------------------------------------------------
# FUNCTION EDITOR POPUP (single function)
# -------------------------------------------------

class FunctionEditorDialog(QDialog):
    """
    Popup editor for creating/updating/removing a function.
    result_action: "save", "remove", or None
    result_function: FunctionDef when action == "save"
    """

    def __init__(self, parent=None, fn: Optional[FunctionDef] = None, theme: Optional[ThemeConfig] = None):
        super().__init__(parent)
        self.setWindowTitle("Function editor")
        self.result_action: Optional[str] = None
        self.result_function: Optional[FunctionDef] = None
        self.theme = theme or ThemeConfig()

        layout = QVBoxLayout(self)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("internal name (e.g. meta_behavior)")
        layout.addWidget(QLabel("Name"))
        layout.addWidget(self.edit_name)

        self.edit_label = QLineEdit()
        self.edit_label.setPlaceholderText("label (dropdown text)")
        layout.addWidget(QLabel("Label"))
        layout.addWidget(self.edit_label)

        self.edit_expr = QLineEdit()
        self.edit_expr.setPlaceholderText("expression, e.g. sin(7*t)*0.7 + 0.3*cos(15*t)")
        layout.addWidget(QLabel("Expression"))
        layout.addWidget(self.edit_expr)

        color_row = QHBoxLayout()
        self.edit_color = QLineEdit()
        self.edit_color.setPlaceholderText("color hex, e.g. #33AADD")
        color_row.addWidget(self.edit_color)
        pick_btn = QPushButton("Pick color")
        pick_btn.clicked.connect(self._pick_color)
        color_row.addWidget(pick_btn)
        layout.addLayout(color_row)

        layout.addWidget(QLabel("Expression tester preview"))
        self.preview_canvas = ExpressionPreviewCanvas(theme=self.theme)
        layout.addWidget(self.preview_canvas)

        test_btn = QPushButton("Test expression")
        test_btn.clicked.connect(self._test_expression_preview)
        layout.addWidget(test_btn)

        btn_box = QDialogButtonBox()
        self.btn_save = btn_box.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_cancel = btn_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_remove = btn_box.addButton("Remove", QDialogButtonBox.ButtonRole.DestructiveRole)

        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        self.btn_remove.clicked.connect(self._on_remove)

        layout.addWidget(btn_box)

        if fn is not None:
            self.edit_name.setText(fn.name)
            self.edit_label.setText(fn.label)
            self.edit_expr.setText(fn.expr_str)
            self.edit_color.setText(fn.color)
            try:
                f = make_func_from_expr(fn.expr_str)
                self.preview_canvas.set_function(f, fn.color)
            except Exception:
                pass

        self.resize(500, 400)

    def _pick_color(self):
        initial = QColor(self.edit_color.text() or "#FFFFFF")
        color = QColorDialog.getColor(initial, self, "Pick color")
        if color.isValid():
            self.edit_color.setText(color.name())

    def _test_expression_preview(self):
        expr = self.edit_expr.text().strip()
        color = self.edit_color.text().strip() or "#8888FF"

        if not expr:
            QMessageBox.warning(self, "Expression tester", "Expression is empty.", parent=self)
            return

        try:
            fn_callable = make_func_from_expr(expr)
        except Exception as e:
            QMessageBox.critical(self, "Expression tester", f"Invalid expression:\n{e}", parent=self)
            self.preview_canvas.set_function(None, color)
            return

        self.preview_canvas.set_function(fn_callable, color)

    def _build_function_from_fields(self) -> Optional[FunctionDef]:
        name = self.edit_name.text().strip()
        label = self.edit_label.text().strip()
        expr = self.edit_expr.text().strip()
        color = self.edit_color.text().strip() or "#FFFFFF"

        if not name or not expr:
            QMessageBox.warning(self, "Function editor", "Name and expression are required.", parent=self)
            return None

        if not label:
            label = name

        try:
            fn_callable = make_func_from_expr(expr)
        except Exception as e:
            QMessageBox.critical(self, "Expression error", f"Invalid expression:\n{e}", parent=self)
            return None

        return FunctionDef(
            name=name,
            label=label,
            expr_str=expr,
            func=fn_callable,
            color=color,
        )

    def _on_save(self):
        fn = self._build_function_from_fields()
        if fn is None:
            return
        self.result_action = "save"
        self.result_function = fn
        self.accept()

    def _on_remove(self):
        if not self.edit_name.text().strip() and not self.edit_expr.text().strip():
            self.reject()
            return
        self.result_action = "remove"
        self.result_function = None
        self.accept()


# -------------------------------------------------
# JSON LIST MANAGER POPUP (tri*.json files)
# -------------------------------------------------

class JsonListManagerDialog(QDialog):
    """
    Manage tri*.json files as lists.
    """

    def __init__(self, base_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lists")
        self.base_dir = base_dir
        self.files: List[str] = []
        self.current_file: Optional[str] = None
        self.current_functions: List[FunctionDef] = []

        layout = QHBoxLayout(self)

        # left: file list
        left = QVBoxLayout()
        left.addWidget(QLabel("tri*.json files"))

        self.file_list = QListWidget()
        left.addWidget(self.file_list)

        file_btn_row = QHBoxLayout()
        btn_new = QPushButton("New list")
        btn_new.clicked.connect(self._new_list)
        file_btn_row.addWidget(btn_new)

        btn_delete = QPushButton("Delete list")
        btn_delete.clicked.connect(self._delete_list)
        file_btn_row.addWidget(btn_delete)
        left.addLayout(file_btn_row)

        btn_reload = QPushButton("Reload files")
        btn_reload.clicked.connect(self._scan_files)
        left.addWidget(btn_reload)

        layout.addLayout(left, 1)

        # right: functions in selected file
        right = QVBoxLayout()
        right.addWidget(QLabel("Functions in selected list"))

        self.func_list = QListWidget()
        self.func_list.setMinimumHeight(120)
        right.addWidget(self.func_list)

        func_btn_row = QHBoxLayout()
        btn_edit = QPushButton("Add / Edit function…")
        btn_edit.clicked.connect(self._edit_function)
        func_btn_row.addWidget(btn_edit)

        btn_remove_fn = QPushButton("Remove function")
        btn_remove_fn.clicked.connect(self._remove_function)
        func_btn_row.addWidget(btn_remove_fn)
        right.addLayout(func_btn_row)

        right.addWidget(QLabel("JSON preview (selected function)"))
        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setMaximumHeight(150)
        right.addWidget(self.json_preview)

        btn_save = QPushButton("Save list")
        btn_save.clicked.connect(self._save_current_list)
        right.addWidget(btn_save)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        right.addWidget(close_box)

        layout.addLayout(right, 2)

        self.file_list.currentRowChanged.connect(self._on_file_selected)
        self.func_list.currentRowChanged.connect(self._on_func_selected)

        self.resize(800, 450)
        self._scan_files()

    # ----- file ops -----

    def _scan_files(self):
        self.files = []
        self.file_list.clear()
        try:
            for fname in sorted(os.listdir(self.base_dir)):
                if fname.startswith("tri") and fname.lower().endswith(".json"):
                    self.files.append(fname)
                    self.file_list.addItem(fname)
        except Exception:
            pass

        if self.files:
            self.file_list.setCurrentRow(0)
        else:
            self.current_file = None
            self.current_functions = []
            self.func_list.clear()
            self.json_preview.setPlainText("")

    def _new_list(self):
        name, ok = QInputDialog.getText(
            self,
            "New list",
            "Enter list name (will create tri_<name>.json):",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        fname = f"tri_{name}.json"
        path = os.path.join(self.base_dir, fname)
        if os.path.exists(path):
            QMessageBox.warning(self, "New list", f"File already exists:\n{fname}")
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "New list", f"Failed to create file:\n{e}")
            return

        self._scan_files()
        idx = self.files.index(fname)
        self.file_list.setCurrentRow(idx)

    def _delete_list(self):
        row = self.file_list.currentRow()
        if row < 0 or row >= len(self.files):
            return
        fname = self.files[row]
        path = os.path.join(self.base_dir, fname)

        res = QMessageBox.question(
            self,
            "Delete list",
            f"Delete file '{fname}' from disk?\nThis cannot be undone.",
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            os.remove(path)
        except Exception as e:
            QMessageBox.critical(self, "Delete list", f"Failed to delete:\n{e}")
            return

        self._scan_files()

    def _on_file_selected(self, row: int):
        if row < 0 or row >= len(self.files):
            self.current_file = None
            self.current_functions = []
            self.func_list.clear()
            self.json_preview.setPlainText("")
            return

        fname = self.files[row]
        path = os.path.join(self.base_dir, fname)
        self.current_file = path
        self._load_current_file()

    def _load_current_file(self):
        self.current_functions = []
        self.func_list.clear()
        self.json_preview.setPlainText("")
        if not self.current_file:
            return

        try:
            with open(self.current_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load list", f"Failed to load:\n{e}")
            return

        if not isinstance(data, list):
            QMessageBox.warning(self, "Load list", "JSON is not a list.")
            return

        for item in data:
            try:
                name = str(item.get("name", "unnamed"))
                label = str(item.get("label", name))
                expr = str(item.get("expr", "sin(t)"))
                color = str(item.get("color", "#FFFFFF"))
                fn = make_func_from_expr(expr)
                self.current_functions.append(
                    FunctionDef(name=name, label=label, expr_str=expr, func=fn, color=color)
                )
                self.func_list.addItem(label)
            except Exception:
                continue

        if self.current_functions:
            self.func_list.setCurrentRow(0)

    # ----- function ops inside file -----

    def _on_func_selected(self, row: int):
        if 0 <= row < len(self.current_functions):
            fn = self.current_functions[row]
            data = {
                "name": fn.name,
                "label": fn.label,
                "expr": fn.expr_str,
                "color": fn.color,
            }
            self.json_preview.setPlainText(json.dumps(data, indent=2))
        else:
            self.json_preview.setPlainText("")

    def _edit_function(self):
        row = self.func_list.currentRow()
        fn_existing = self.current_functions[row] if 0 <= row < len(self.current_functions) else None

        dlg = FunctionEditorDialog(self, fn=fn_existing)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if dlg.result_action == "save" and dlg.result_function is not None:
            fn_new = dlg.result_function
            if fn_existing is not None:
                self.current_functions[row] = fn_new
                self.func_list.item(row).setText(fn_new.label)
                self.func_list.setCurrentRow(row)
            else:
                self.current_functions.append(fn_new)
                self.func_list.addItem(fn_new.label)
                self.func_list.setCurrentRow(len(self.current_functions) - 1)

        elif dlg.result_action == "remove":
            if fn_existing is not None:
                self._remove_function()

    def _remove_function(self):
        row = self.func_list.currentRow()
        if row < 0 or row >= len(self.current_functions):
            return
        del self.current_functions[row]
        self.func_list.takeItem(row)
        if self.current_functions:
            self.func_list.setCurrentRow(min(row, len(self.current_functions) - 1))
        else:
            self.json_preview.setPlainText("")

    def _save_current_list(self):
        if not self.current_file:
            QMessageBox.warning(self, "Save list", "No file selected.")
            return

        data = []
        for fn in self.current_functions:
            data.append(
                {
                    "name": fn.name,
                    "label": fn.label,
                    "expr": fn.expr_str,
                    "color": fn.color,
                }
            )

        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(
                self,
                "Save list",
                f"Saved {len(self.current_functions)} functions to:\n{os.path.basename(self.current_file)}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Save list", f"Failed to save:\n{e}")


# -------------------------------------------------
# AUDIO ENGINE – oscillator + gain + EQ
# -------------------------------------------------

class AudioEngine:
    """
    func_provider() -> (func, frequency_factor, visual_time, amplitude)
    """

    def __init__(self, func_provider):
        if not HAVE_AUDIO:
            raise RuntimeError("sounddevice not available")

        self.func_provider = func_provider
        self.samplerate = 44100

        # master fader + tone
        self.volume = 0.2
        self.tone = 0.5
        self.phase = 0.0

        # mixer parameters
        self.pitch_min_hz = 80.0
        self.pitch_max_hz = 880.0

        self.gain = 1.0          # pre-shaper gain
        self.drive = 1.0         # shaper drive

        self.eq_low_gain = 1.0
        self.eq_mid_gain = 1.0
        self.eq_high_gain = 1.0

        self.eq_low_fc = 200.0
        self.eq_high_fc = 4000.0
        self.eq_alpha_low = 1 - math.exp(-2 * math.pi * self.eq_low_fc / self.samplerate)
        self.eq_alpha_high = 1 - math.exp(-2 * math.pi * self.eq_high_fc / self.samplerate)
        self.eq_lp_low_state = 0.0
        self.eq_lp_high_state = 0.0

        self.current_pitch_hz = 0.0
        self.current_y_at_dot = 0.0

        self.stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def set_volume(self, v: float):
        self.volume = max(0.0, min(1.0, v))

    def set_tone(self, t: float):
        self.tone = max(0.0, min(1.0, t))

    def _callback(self, outdata, frames, time_info, status):
        if status:
            pass

        func, freq_factor, visual_time, amplitude = self.func_provider()
        if func is None:
            outdata[:] = 0.0
            return

        freq_factor = max(0.1, min(4.0, freq_factor))
        amplitude = max(0.0, min(1.5, amplitude))

        # sample dot just for info
        t_dot = freq_factor * (math.pi + visual_time)
        y_at_dot = amplitude * func(t_dot)
        self.current_y_at_dot = y_at_dot

        # pitch only from tone slider
        span = max(1.0, self.pitch_max_hz - self.pitch_min_hz)
        freq_hz = self.pitch_min_hz + self.tone * span
        self.current_pitch_hz = freq_hz

        phase_step = 2.0 * math.pi * freq_hz / self.samplerate

        alpha_low = self.eq_alpha_low
        alpha_high = self.eq_alpha_high
        lp_low = self.eq_lp_low_state
        lp_high = self.eq_lp_high_state

        for i in range(frames):
            self.phase += phase_step
            if self.phase > 1e6:
                self.phase -= 1e6

            # gain + drive
            x = amplitude * func(self.phase)
            x *= self.gain
            shaped = math.tanh(self.drive * x)

            # low band
            lp_low = lp_low + alpha_low * (shaped - lp_low)
            low = lp_low

            # highcut band
            lp_high = lp_high + alpha_high * (shaped - lp_high)
            high = shaped - lp_high
            mid = shaped - low - high

            y_low = self.eq_low_gain * low
            y_mid = self.eq_mid_gain * mid
            y_high = self.eq_high_gain * high

            eq_out = y_low + y_mid + y_high

            sample = eq_out * self.volume
            outdata[i, 0] = sample

        self.eq_lp_low_state = lp_low
        self.eq_lp_high_state = lp_high

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


# -------------------------------------------------
# MIXER DIALOG
# -------------------------------------------------

class MixerDialog(QDialog):
    """
    Mixer for audio parameters + load/save JSON configs.
    """

    def __init__(self, base_dir: str, audio_engine: AudioEngine, volume_slider: Optional[QSlider] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mixer")
        self.base_dir = base_dir
        self.engine = audio_engine
        self.volume_slider = volume_slider

        layout = QVBoxLayout(self)

        # Pitch range
        layout.addWidget(QLabel("Pitch range (Hz)"))
        row_pitch = QHBoxLayout()
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(20.0, 5000.0)
        self.spin_min.setDecimals(1)
        self.spin_min.setValue(self.engine.pitch_min_hz)
        self.spin_min.setSuffix(" Hz")
        row_pitch.addWidget(QLabel("Min"))
        row_pitch.addWidget(self.spin_min)

        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(20.0, 5000.0)
        self.spin_max.setDecimals(1)
        self.spin_max.setValue(self.engine.pitch_max_hz)
        self.spin_max.setSuffix(" Hz")
        row_pitch.addWidget(QLabel("Max"))
        row_pitch.addWidget(self.spin_max)

        layout.addLayout(row_pitch)

        # Drive
        layout.addWidget(QLabel("Drive (waveshaper)"))
        self.spin_drive = QDoubleSpinBox()
        self.spin_drive.setRange(0.1, 5.0)
        self.spin_drive.setDecimals(2)
        self.spin_drive.setSingleStep(0.1)
        self.spin_drive.setValue(self.engine.drive)
        layout.addWidget(self.spin_drive)

        # Gain
        layout.addWidget(QLabel("Gain (pre-shaper, affects tone)"))
        self.spin_gain = QDoubleSpinBox()
        self.spin_gain.setRange(0.1, 5.0)
        self.spin_gain.setDecimals(2)
        self.spin_gain.setSingleStep(0.1)
        self.spin_gain.setValue(self.engine.gain)
        layout.addWidget(self.spin_gain)

        # EQ
        layout.addWidget(QLabel("EQ (Low / Mid / High)"))
        row_eq = QHBoxLayout()

        self.spin_eq_low = QDoubleSpinBox()
        self.spin_eq_low.setRange(0.0, 3.0)
        self.spin_eq_low.setDecimals(2)
        self.spin_eq_low.setSingleStep(0.1)
        self.spin_eq_low.setValue(self.engine.eq_low_gain)
        row_eq.addWidget(QLabel("Low"))
        row_eq.addWidget(self.spin_eq_low)

        self.spin_eq_mid = QDoubleSpinBox()
        self.spin_eq_mid.setRange(0.0, 3.0)
        self.spin_eq_mid.setDecimals(2)
        self.spin_eq_mid.setSingleStep(0.1)
        self.spin_eq_mid.setValue(self.engine.eq_mid_gain)
        row_eq.addWidget(QLabel("Mid"))
        row_eq.addWidget(self.spin_eq_mid)

        self.spin_eq_high = QDoubleSpinBox()
        self.spin_eq_high.setRange(0.0, 3.0)
        self.spin_eq_high.setDecimals(2)
        self.spin_eq_high.setSingleStep(0.1)
        self.spin_eq_high.setValue(self.engine.eq_high_gain)
        row_eq.addWidget(QLabel("High"))
        row_eq.addWidget(self.spin_eq_high)

        layout.addLayout(row_eq)

        # Master volume
        layout.addWidget(QLabel("Master volume (fader)"))
        self.spin_vol = QDoubleSpinBox()
        self.spin_vol.setRange(0.0, 1.0)
        self.spin_vol.setDecimals(2)
        self.spin_vol.setSingleStep(0.05)
        self.spin_vol.setValue(self.engine.volume)
        layout.addWidget(self.spin_vol)

        # Config buttons
        btn_row = QHBoxLayout()
        btn_load = QPushButton("Load config…")
        btn_save = QPushButton("Save config as…")
        btn_row.addWidget(btn_load)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        # signals
        self.spin_min.valueChanged.connect(self._apply_to_engine)
        self.spin_max.valueChanged.connect(self._apply_to_engine)
        self.spin_drive.valueChanged.connect(self._apply_to_engine)
        self.spin_gain.valueChanged.connect(self._apply_to_engine)
        self.spin_eq_low.valueChanged.connect(self._apply_to_engine)
        self.spin_eq_mid.valueChanged.connect(self._apply_to_engine)
        self.spin_eq_high.valueChanged.connect(self._apply_to_engine)
        self.spin_vol.valueChanged.connect(self._apply_to_engine)

        btn_load.clicked.connect(self._load_config)
        btn_save.clicked.connect(self._save_config)

        self.resize(340, 320)

    def _apply_to_engine(self):
        self.engine.pitch_min_hz = float(self.spin_min.value())
        self.engine.pitch_max_hz = float(self.spin_max.value())
        if self.engine.pitch_max_hz < self.engine.pitch_min_hz:
            self.engine.pitch_max_hz = self.engine.pitch_min_hz
            self.spin_max.setValue(self.engine.pitch_max_hz)

        self.engine.drive = float(self.spin_drive.value())
        self.engine.gain = float(self.spin_gain.value())

        self.engine.eq_low_gain = float(self.spin_eq_low.value())
        self.engine.eq_mid_gain = float(self.spin_eq_mid.value())
        self.engine.eq_high_gain = float(self.spin_eq_high.value())

        vol = float(self.spin_vol.value())
        self.engine.set_volume(vol)
        if self.volume_slider is not None:
            self.volume_slider.setValue(int(self.engine.volume * 100))

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load mixer config",
            self.base_dir,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load config", f"Failed to load:\n{e}")
            return

        try:
            if "pitch_min_hz" in data:
                self.spin_min.setValue(float(data["pitch_min_hz"]))
            if "pitch_max_hz" in data:
                self.spin_max.setValue(float(data["pitch_max_hz"]))
            if "drive" in data:
                self.spin_drive.setValue(float(data["drive"]))
            if "gain" in data:
                self.spin_gain.setValue(float(data["gain"]))
            if "eq_low" in data:
                self.spin_eq_low.setValue(float(data["eq_low"]))
            if "eq_mid" in data:
                self.spin_eq_mid.setValue(float(data["eq_mid"]))
            if "eq_high" in data:
                self.spin_eq_high.setValue(float(data["eq_high"]))
            if "volume" in data:
                self.spin_vol.setValue(float(data["volume"]))
            self._apply_to_engine()
        except Exception as e:
            QMessageBox.critical(self, "Load config", f"Invalid config:\n{e}")

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save mixer config",
            os.path.join(self.base_dir, "mixer_config.json"),
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        data = {
            "pitch_min_hz": float(self.spin_min.value()),
            "pitch_max_hz": float(self.spin_max.value()),
            "drive": float(self.spin_drive.value()),
            "gain": float(self.spin_gain.value()),
            "eq_low": float(self.spin_eq_low.value()),
            "eq_mid": float(self.spin_eq_mid.value()),
            "eq_high": float(self.spin_eq_high.value()),
            "volume": float(self.spin_vol.value()),
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Save config", f"Failed to save:\n{e}")


# -------------------------------------------------
# THEME DIALOG
# -------------------------------------------------

class ThemeDialog(QDialog):
    """
    Configures ThemeConfig and returns it.
    """

    def __init__(self, base_dir: str, theme: ThemeConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Theme")
        self.base_dir = base_dir
        self.theme = theme
        self.result_theme: Optional[ThemeConfig] = None

        layout = QVBoxLayout(self)

        def make_color_row(label_text: str, initial_value: str):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            edit = QLineEdit(initial_value)
            btn = QPushButton("Pick…")
            row.addWidget(lbl)
            row.addWidget(edit)
            row.addWidget(btn)
            return row, edit, btn

        row1, self.edit_canvas_bg, btn_canvas_bg = make_color_row(
            "Canvas background", self.theme.canvas_bg
        )
        layout.addLayout(row1)
        row2, self.edit_canvas_mid, btn_canvas_mid = make_color_row(
            "Canvas midline", self.theme.canvas_midline
        )
        layout.addLayout(row2)
        row3, self.edit_panel_bg, btn_panel_bg = make_color_row(
            "Panel background", self.theme.panel_bg
        )
        layout.addLayout(row3)
        row4, self.edit_panel_text, btn_panel_text = make_color_row(
            "Panel text", self.theme.panel_text
        )
        layout.addLayout(row4)
        row5, self.edit_pointer_ring, btn_pointer_ring = make_color_row(
            "Pointer ring", self.theme.pointer_ring
        )
        layout.addLayout(row5)

        def connect_btn(btn: QPushButton, edit: QLineEdit):
            def pick():
                initial = QColor(edit.text() or "#FFFFFF")
                color = QColorDialog.getColor(initial, self, "Pick color")
                if color.isValid():
                    edit.setText(color.name())
            btn.clicked.connect(pick)

        connect_btn(btn_canvas_bg, self.edit_canvas_bg)
        connect_btn(btn_canvas_mid, self.edit_canvas_mid)
        connect_btn(btn_panel_bg, self.edit_panel_bg)
        connect_btn(btn_panel_text, self.edit_panel_text)
        connect_btn(btn_pointer_ring, self.edit_pointer_ring)

        box = QDialogButtonBox()
        ok_btn = box.addButton("OK", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self._on_ok)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self.resize(400, 260)

    def _on_ok(self):
        self.result_theme = ThemeConfig(
            canvas_bg=self.edit_canvas_bg.text().strip() or "#05060A",
            canvas_midline=self.edit_canvas_mid.text().strip() or "#1E1E28",
            panel_bg=self.edit_panel_bg.text().strip() or "#0B0D18",
            panel_text=self.edit_panel_text.text().strip() or "#FFFFFF",
            pointer_ring=self.edit_pointer_ring.text().strip() or "#FFFFFF",
        )
        self.accept()


# -------------------------------------------------
# MAIN CANVAS – amplitude affects true y, theme-based colors
# -------------------------------------------------

class PatternCanvas(QWidget):
    def __init__(self, functions: List[FunctionDef], theme: ThemeConfig, parent=None):
        super().__init__(parent)
        self.functions = functions
        self.current_index = 0

        self.time = 0.0
        self.time_speed = 1.0
        self.amplitude = 0.8
        self.frequency = 1.0
        self.line_width = 2
        self.theme = theme

        self.setMinimumSize(600, 400)
        self.setAutoFillBackground(True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(16)

    def set_theme(self, theme: ThemeConfig):
        self.theme = theme
        self.update()

    def set_function_index(self, index: int):
        if 0 <= index < len(self.functions):
            self.current_index = index
            self.update()

    def set_amplitude_from_slider(self, value: int):
        self.amplitude = max(0.0, min(1.5, value / 100.0))
        self.update()

    def set_frequency_from_slider(self, value: int):
        self.frequency = max(0.1, value / 10.0)
        self.update()

    def set_speed_from_slider(self, value: int):
        self.time_speed = value / 20.0
        self.update()

    def set_line_width_from_slider(self, value: int):
        self.line_width = max(1, value)
        self.update()

    def on_tick(self):
        self.time += 0.016 * self.time_speed
        win = self.window()
        if hasattr(win, "update_y_display"):
            win.update_y_display()
        self.update()

    def paintEvent(self, event):
        if not self.functions:
            return

        fn = self.functions[self.current_index]
        w = self.width()
        h = self.height()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self.theme.canvas_bg))

        color = QColor(fn.color)
        pen = QPen(color)
        pen.setWidth(self.line_width)
        painter.setPen(pen)

        center_y = h / 2.0
        scale_y = (h / 2.0)

        path = QPainterPath()
        samples = max(200, w)
        started = False

        for i in range(samples):
            x = w * i / (samples - 1)
            base = 2.0 * math.pi * (i / (samples - 1))
            t = self.frequency * (base + self.time)
            y_raw = fn.func(t)
            y_val = self.amplitude * y_raw
            y = center_y - y_val * scale_y

            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)

        painter.drawPath(path)

        # pointer at center
        center_x = w / 2.0
        base_center = math.pi
        t_center = self.frequency * (base_center + self.time)
        y_raw_center = fn.func(t_center)
        y_val_center = self.amplitude * y_raw_center
        y_center = center_y - y_val_center * scale_y

        pointer_radius = 5
        pointer_pen = QPen(QColor(self.theme.pointer_ring))
        pointer_pen.setWidth(2)
        painter.setPen(pointer_pen)
        painter.setBrush(QColor(fn.color))
        painter.drawEllipse(
            int(center_x - pointer_radius),
            int(y_center - pointer_radius),
            pointer_radius * 2,
            pointer_radius * 2,
        )

        mid_pen = QPen(QColor(self.theme.canvas_midline))
        mid_pen.setWidth(1)
        painter.setPen(mid_pen)
        painter.drawLine(0, int(center_y), w, int(center_y))

        painter.end()


# -------------------------------------------------
# MAIN WINDOW
# -------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, functions: List[FunctionDef], base_dir: str):
        super().__init__()

        self.functions = functions
        self.base_dir = base_dir
        self.theme = load_theme_config(base_dir)
        self.history_path = os.path.join(self.base_dir, "tri_history_backup.jsonl")

        self.setWindowTitle("Live Pattern Lab")
        self.setMinimumSize(1150, 600)

        self.audio_engine: Optional[AudioEngine] = None
        if HAVE_AUDIO:
            try:
                self.audio_engine = AudioEngine(self._get_audio_state)
            except Exception:
                self.audio_engine = None

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        self.canvas = PatternCanvas(self.functions, self.theme)
        main_layout.addWidget(self.canvas, 1)

        self.control_panel = self._build_control_panel()
        main_layout.addWidget(self.control_panel)

        self.update_y_display()

    # ---- audio state provider ---- #

    def _get_audio_state(self):
        if not self.functions:
            return (lambda t: 0.0, 1.0, 0.0, 1.0)

        idx = self.canvas.current_index
        if idx < 0 or idx >= len(self.functions):
            return (lambda t: 0.0, 1.0, self.canvas.time, self.canvas.amplitude)

        fn = self.functions[idx]
        return fn.func, self.canvas.frequency, self.canvas.time, self.canvas.amplitude

    # ---- history backup ---- #

    def _append_history(self, action: str, fn: FunctionDef):
        try:
            import datetime as _dt
            entry = {
                "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
                "action": action,
                "name": fn.name,
                "label": fn.label,
                "expr": fn.expr_str,
                "color": fn.color,
            }
            with open(self.history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ---- UI BUILD ---- #

    def _build_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        panel.setMinimumWidth(360)
        self._apply_panel_theme(panel)

        layout.addWidget(self._make_label("Pattern (combo)"))
        self.func_combo = QComboBox()
        layout.addWidget(self.func_combo)

        layout.addWidget(self._make_label("Functions list"))
        self.func_list = QListWidget()
        self.func_list.setMinimumHeight(120)
        layout.addWidget(self.func_list)

        self.func_combo.currentIndexChanged.connect(self._on_combo_changed)
        self.func_list.currentRowChanged.connect(self._on_list_changed)

        layout.addWidget(self._make_label("Expression"))
        self.expr_label = QLabel()
        self.expr_label.setWordWrap(True)
        layout.addWidget(self.expr_label)

        layout.addWidget(self._make_label("Current dot (amplitude-scaled)"))
        self.y_value_label = QLabel("y = 0.0")
        self.y_value_label.setStyleSheet(f"font-size: 12px; color: {self.theme.panel_text};")
        layout.addWidget(self.y_value_label)

        layout.addSpacing(4)

        layout.addWidget(self._make_label("Amplitude (visual + sound)"))
        amp_slider = QSlider(Qt.Orientation.Horizontal)
        amp_slider.setRange(0, 150)
        amp_slider.setValue(int(self.canvas.amplitude * 100))
        amp_slider.valueChanged.connect(self.canvas.set_amplitude_from_slider)
        layout.addWidget(amp_slider)

        layout.addWidget(self._make_label("Frequency (visual)"))
        freq_slider = QSlider(Qt.Orientation.Horizontal)
        freq_slider.setRange(1, 100)
        freq_slider.setValue(int(self.canvas.frequency * 10))
        freq_slider.valueChanged.connect(self.canvas.set_frequency_from_slider)
        layout.addWidget(freq_slider)

        layout.addWidget(self._make_label("Speed (scroll)"))
        speed_slider = QSlider(Qt.Orientation.Horizontal)
        speed_slider.setRange(0, 100)
        speed_slider.setValue(int(self.canvas.time_speed * 20))
        speed_slider.valueChanged.connect(self.canvas.set_speed_from_slider)
        layout.addWidget(speed_slider)

        layout.addWidget(self._make_label("Line width"))
        lw_slider = QSlider(Qt.Orientation.Horizontal)
        lw_slider.setRange(1, 10)
        lw_slider.setValue(self.canvas.line_width)
        lw_slider.valueChanged.connect(self.canvas.set_line_width_from_slider)
        layout.addWidget(lw_slider)

        layout.addSpacing(8)

        self.vol_slider = None

        if self.audio_engine is not None:
            layout.addWidget(self._make_label("Audio hum"))
            layout.addWidget(QLabel("Volume"))
            vol_slider = QSlider(Qt.Orientation.Horizontal)
            vol_slider.setRange(0, 100)
            vol_slider.setValue(int(self.audio_engine.volume * 100))
            vol_slider.valueChanged.connect(
                lambda v: self.audio_engine.set_volume(v / 100.0)
            )
            layout.addWidget(vol_slider)
            self.vol_slider = vol_slider

            layout.addWidget(QLabel("Tone (pitch)"))
            tone_slider = QSlider(Qt.Orientation.Horizontal)
            tone_slider.setRange(0, 100)
            tone_slider.setValue(int(self.audio_engine.tone * 100))
            tone_slider.valueChanged.connect(
                lambda v: self.audio_engine.set_tone(v / 100.0)
            )
            layout.addWidget(tone_slider)
        else:
            layout.addWidget(self._make_label("Audio hum"))
            note = QLabel(
                "Audio disabled.\nInstall 'sounddevice' to enable:\n"
                "  pip install sounddevice"
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        layout.addSpacing(8)

        editor_btn = QPushButton("Function editor…")
        editor_btn.clicked.connect(self._open_function_editor)
        layout.addWidget(editor_btn)

        json_mgr_btn = QPushButton("Lists…")
        json_mgr_btn.clicked.connect(self._open_json_list_manager)
        layout.addWidget(json_mgr_btn)

        if self.audio_engine is not None:
            mixer_btn = QPushButton("Mixer…")
            mixer_btn.clicked.connect(self._open_mixer)
            layout.addWidget(mixer_btn)

        theme_btn = QPushButton("Theme…")
        theme_btn.clicked.connect(self._open_theme)
        layout.addWidget(theme_btn)

        layout.addWidget(self._make_label("JSON preview (selected)"))
        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setMaximumHeight(120)
        layout.addWidget(self.json_preview)

        save_btn = QPushButton("Save functions to tri_custom.json")
        save_btn.clicked.connect(self._save_functions_to_file)
        layout.addWidget(save_btn)

        reload_btn = QPushButton("Reload tri*.json functions")
        reload_btn.clicked.connect(self._reload_tri_functions)
        layout.addWidget(reload_btn)

        layout.addStretch(1)

        self._rebuild_function_views(select_index=0)

        return panel

    def _apply_panel_theme(self, panel: QFrame):
        panel.setStyleSheet(
            f"""
QFrame {{
  background-color: {self.theme.panel_bg};
  color: {self.theme.panel_text};
}}
QLabel, QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QPushButton {{
  font-size: 9pt;
  color: {self.theme.panel_text};
  background-color: transparent;
}}
QListWidget, QPlainTextEdit, QLineEdit {{
  background-color: #10121F;
}}
"""
        )

    def _make_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold;")
        return lbl

    # ---- view sync ---- #

    def _rebuild_function_views(self, select_index: int = 0):
        self.func_combo.blockSignals(True)
        self.func_list.blockSignals(True)

        self.func_combo.clear()
        self.func_list.clear()

        for fn in self.functions:
            self.func_combo.addItem(fn.label)
            self.func_list.addItem(QListWidgetItem(fn.label))

        if self.functions:
            idx = max(0, min(select_index, len(self.functions) - 1))
            self.func_combo.setCurrentIndex(idx)
            self.func_list.setCurrentRow(idx)
            self.canvas.functions = self.functions
            self.canvas.set_function_index(idx)
            self._update_expr_label(idx)
            self._update_json_preview(idx)
        else:
            self.expr_label.setText("—")
            self.json_preview.setPlainText("")

        self.func_combo.blockSignals(False)
        self.func_list.blockSignals(False)

    def _on_combo_changed(self, index: int):
        if index < 0 or index >= len(self.functions):
            return
        self.func_list.blockSignals(True)
        self.func_list.setCurrentRow(index)
        self.func_list.blockSignals(False)
        self.canvas.set_function_index(index)
        self._update_expr_label(index)
        self._update_json_preview(index)
        self.update_y_display()

    def _on_list_changed(self, row: int):
        if row < 0 or row >= len(self.functions):
            return
        self.func_combo.blockSignals(True)
        self.func_combo.setCurrentIndex(row)
        self.func_combo.blockSignals(False)
        self.canvas.set_function_index(row)
        self._update_expr_label(row)
        self._update_json_preview(row)
        self.update_y_display()

    def _update_expr_label(self, index: int):
        if 0 <= index < len(self.functions):
            fn = self.functions[index]
            self.expr_label.setText(fn.expr_str)
        else:
            self.expr_label.setText("—")

    def _update_json_preview(self, index: int):
        if 0 <= index < len(self.functions):
            fn = self.functions[index]
            data = {
                "name": fn.name,
                "label": fn.label,
                "expr": fn.expr_str,
                "color": fn.color,
            }
            self.json_preview.setPlainText(json.dumps(data, indent=2))
        else:
            self.json_preview.setPlainText("")

    # ---- amplitude-scaled y & pitch ---- #

    def update_y_display(self):
        if not self.functions:
            self.y_value_label.setText("—")
            return

        idx = self.canvas.current_index
        if idx < 0 or idx >= len(self.functions):
            self.y_value_label.setText("—")
            return

        fn = self.functions[idx]
        base_center = math.pi
        t_center = self.canvas.frequency * (base_center + self.canvas.time)
        y_raw = fn.func(t_center)
        y_amp = self.canvas.amplitude * y_raw

        pitch_txt = ""
        if self.audio_engine is not None and self.audio_engine.current_pitch_hz > 0:
            pitch_txt = f", f ≈ {self.audio_engine.current_pitch_hz:.1f} Hz"

        self.y_value_label.setText(
            f"y_raw = {y_raw:.4f}, y_amp = {y_amp:.4f}{pitch_txt}"
        )

    # ---- popup function editor ---- #

    def _open_function_editor(self):
        current_fn: Optional[FunctionDef] = None
        idx = self.canvas.current_index
        if 0 <= idx < len(self.functions):
            current_fn = self.functions[idx]

        dlg = FunctionEditorDialog(self, fn=current_fn, theme=self.theme)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        action = dlg.result_action
        fn_result = dlg.result_function

        if action == "save" and fn_result is not None:
            existing_index = None
            for i, f in enumerate(self.functions):
                if f.name == fn_result.name and f.expr_str == fn_result.expr_str:
                    existing_index = i
                    break

            if existing_index is not None:
                self.functions[existing_index] = fn_result
                target = existing_index
            else:
                self.functions.append(fn_result)
                target = len(self.functions) - 1

            self.canvas.functions = self.functions
            self._rebuild_function_views(select_index=target)
            self._append_history("add", fn_result)

        elif action == "remove":
            if not self.functions:
                return
            if len(self.functions) == 1:
                QMessageBox.warning(
                    self,
                    "Remove function",
                    "Cannot remove the last remaining function.",
                )
                return
            if 0 <= idx < len(self.functions):
                fn = self.functions[idx]
                del self.functions[idx]
                self.canvas.functions = self.functions
                self._rebuild_function_views(select_index=min(idx, len(self.functions) - 1))
                self._append_history("remove", fn)

    # ---- popup JSON list manager ---- #

    def _open_json_list_manager(self):
        dlg = JsonListManagerDialog(self.base_dir, self)
        dlg.exec()
        self._reload_tri_functions()

    # ---- mixer ---- #

    def _open_mixer(self):
        if self.audio_engine is None:
            QMessageBox.information(self, "Mixer", "Audio is disabled.")
            return
        dlg = MixerDialog(self.base_dir, self.audio_engine, self.vol_slider, self)
        dlg.exec()

    # ---- theme ---- #

    def _open_theme(self):
        dlg = ThemeDialog(self.base_dir, self.theme, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.result_theme is None:
            return
        self.theme = dlg.result_theme
        save_theme_config(self.base_dir, self.theme)
        self.canvas.set_theme(self.theme)
        self._apply_panel_theme(self.control_panel)
        self.y_value_label.setStyleSheet(f"font-size: 12px; color: {self.theme.panel_text};")

    # ---- save current functions to tri_custom.json ---- #

    def _save_functions_to_file(self):
        out_path = os.path.join(self.base_dir, "tri_custom.json")
        data = []
        for fn in self.functions:
            data.append(
                {
                    "name": fn.name,
                    "label": fn.label,
                    "expr": fn.expr_str,
                    "color": fn.color,
                }
            )

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(
                self,
                "Save functions",
                f"Saved {len(self.functions)} functions to:\n{out_path}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save functions",
                f"Failed to save functions:\n{e}",
            )

    # ---- reload tri*.json ---- #

    def _reload_tri_functions(self):
        funcs = load_all_tri_functions(self.base_dir)
        if funcs is None:
            QMessageBox.warning(
                self,
                "Reload",
                "No valid tri*.json functions found.\n"
                "Using current list (or defaults).",
            )
            return

        self.functions = funcs
        self.canvas.functions = funcs
        self._rebuild_function_views(select_index=0)

    def closeEvent(self, event):
        if self.audio_engine is not None:
            self.audio_engine.close()
        super().closeEvent(event)


# -------------------------------------------------
# ENTRY POINT
# -------------------------------------------------

def main():
    app = QApplication(sys.argv)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    functions = load_all_tri_functions(base_dir)
    if functions is None:
        functions = get_default_functions()

    window = MainWindow(functions, base_dir)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
