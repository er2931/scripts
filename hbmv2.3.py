# Function labels are provided throughout the file for clarity

import sys
import os
import json
import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Dict, Tuple, Set, Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath, QKeySequence, QShortcut
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
    QAbstractItemView,
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
    panel_field_bg: str = "#10121F"  # background for panel boxes
    function_line_override: str = ""  # optional override color for trig lines


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

    # small niceties (optional)
    if expr.startswith("="):
        expr = expr[1:].strip()
    expr = expr.replace("π", "pi").replace("^", "**")

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
# DEFAULT FUNCTIONS (fallback, with crescent + your special set)
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
        # Crescent sine (minimums & maximums grow then shrink)
        FunctionDef(
            name="crescent_soft",
            label="Crescent Sine (soft)",
            expr_str="sin(pi*(t-floor(t))) * sin(2*pi*(t-floor(t)))",
            func=make_func_from_expr("sin(pi*(t-floor(t))) * sin(2*pi*(t-floor(t)))"),
            color="#40FFD0",
        ),
        # Your special rectification & pattern set
        FunctionDef(
            name="lro",
            label="Limit Rectification (LRO)",
            expr_str="(t/0.6 if t < 0.6 else 1.0) + 0.06*sin(10*pi*t)",
            func=make_func_from_expr("(t/0.6 if t < 0.6 else 1.0) + 0.06*sin(10*pi*t)"),
            color="#40e9ff",
        ),
        FunctionDef(
            name="tro",
            label="Trigonometrical Rectification (TRO)",
            expr_str="0.0 if (t < 0.2 or t > 0.8) else (sin(pi*((t-0.2)/0.6)) + 0.35*sin(2*pi*((t-0.2)/0.6)))",
            func=make_func_from_expr(
                "0.0 if (t < 0.2 or t > 0.8) else (sin(pi*((t-0.2)/0.6)) + 0.35*sin(2*pi*((t-0.2)/0.6)))"
            ),
            color="#ff3bbf",
        ),
        FunctionDef(
            name="lin_rect",
            label="Linear Rectification",
            expr_str="(t/0.2 if t < 0.2 else (1.0 if t < 0.8 else ((1.0 - (t-0.8)/0.2) if (1.0 - (t-0.8)/0.2) > 0.0 else 0.0)))",
            func=make_func_from_expr(
                "(t/0.2 if t < 0.2 else (1.0 if t < 0.8 else ((1.0 - (t-0.8)/0.2) if (1.0 - (t-0.8)/0.2) > 0.0 else 0.0)))"
            ),
            color="#ffb347",
        ),
        FunctionDef(
            name="res_plateau",
            label="Resonant Plateau",
            expr_str="0.5*(1 - cos(2*pi*t))*(0.5 + 0.4*sin(16*pi*t))",
            func=make_func_from_expr(
                "0.5*(1 - cos(2*pi*t))*(0.5 + 0.4*sin(16*pi*t))"
            ),
            color="#25f0c1",
        ),
        FunctionDef(
            name="hollow_void",
            label="Hollow Void",
            expr_str="(0.6*sin(4*pi*t) if not (0.4 < t and t < 0.6) else (0.6*sin(4*pi*t)*((1.0 - abs(t-0.5)/0.1) if (1.0 - abs(t-0.5)/0.1) > 0.0 else 0.0)))",
            func=make_func_from_expr(
                "(0.6*sin(4*pi*t) if not (0.4 < t and t < 0.6) else (0.6*sin(4*pi*t)*((1.0 - abs(t-0.5)/0.1) if (1.0 - abs(t-0.5)/0.1) > 0.0 else 0.0)))"
            ),
            color="#66ccff",
        ),
        FunctionDef(
            name="fractal_echo",
            label="Fractal Echo",
            expr_str="((1.0*sin(2*pi*1*t + 1*0.4) + (1.0/2.0)*sin(2*pi*2*t + 2*0.4) + (1.0/3.0)*sin(2*pi*3*t + 3*0.4) + (1.0/4.0)*sin(2*pi*4*t + 4*0.4))/2.5)",
            func=make_func_from_expr(
                "((1.0*sin(2*pi*1*t + 1*0.4) + (1.0/2.0)*sin(2*pi*2*t + 2*0.4) + (1.0/3.0)*sin(2*pi*3*t + 3*0.4) + (1.0/4.0)*sin(2*pi*4*t + 4*0.4))/2.5)"
            ),
            color="#aa7bff",
        ),
        FunctionDef(
            name="photon_veins",
            label="Photon Veins",
            expr_str="0.4*sin(2*pi*t) - 1.2*exp(-((abs(t-0.5)*40.0)**2))",
            func=make_func_from_expr(
                "0.4*sin(2*pi*t) - 1.2*exp(-((abs(t-0.5)*40.0)**2))"
            ),
            color="#ff944d",
        ),
        FunctionDef(
            name="pattern_pulse_00",
            label="Pattern Pulse 00",
            expr_str="0.7*sin(2*pi*t) + 0.4*sin(4*pi*t + 0.7) + 0.25*sin(14*pi*t + 0.3)",
            func=make_func_from_expr(
                "0.7*sin(2*pi*t) + 0.4*sin(4*pi*t + 0.7) + 0.25*sin(14*pi*t + 0.3)"
            ),
            color="#ff5cf0",
        ),
        FunctionDef(
            name="pattern_pulse_22",
            label="Pattern Pulse 22",
            expr_str="((0.0 if (t < 0.15 or t > 0.85) else (1.4*exp(-((t-0.35)*40.0)**2))) + 0.25*sin(2*pi*2*t))",
            func=make_func_from_expr(
                "((0.0 if (t < 0.15 or t > 0.85) else (1.4*exp(-((t-0.35)*40.0)**2))) + 0.25*sin(2*pi*2*t))"
            ),
            color="#40ffb0",
        ),
        FunctionDef(
            name="pattern_cascade_5037",
            label="Entropy Cascade 5037",
            expr_str="0.4*sin(2*pi*t) + 0.3*sin(6*pi*t + 0.5) + 0.2*sin(10*pi*t + 1.1)",
            func=make_func_from_expr(
                "0.4*sin(2*pi*t) + 0.3*sin(6*pi*t + 0.5) + 0.2*sin(10*pi*t + 1.1)"
            ),
            color="#ffcf40",
        ),
        FunctionDef(
            name="pattern_glitch_n7z9",
            label="Glitched Glyph n7z9",
            expr_str="0.6*sin(2*pi*(3*t*t + 0.2)) + 0.3*sin(2*pi*(9*t + 0.4))",
            func=make_func_from_expr(
                "0.6*sin(2*pi*(3*t*t + 0.2)) + 0.3*sin(2*pi*(9*t + 0.4))"
            ),
            color="#7d7dff",
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
        panel_field_bg=data.get("panel_field_bg", "#10121F"),
        function_line_override=data.get("function_line_override", ""),
    )


def save_theme_config(base_dir: str, theme: ThemeConfig):
    path = os.path.join(base_dir, "theme_config.json")
    data = {
        "canvas_bg": theme.canvas_bg,
        "canvas_midline": theme.canvas_midline,
        "panel_bg": theme.panel_bg,
        "panel_text": theme.panel_text,
        "pointer_ring": theme.pointer_ring,
        "panel_field_bg": theme.panel_field_bg,
        "function_line_override": theme.function_line_override,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# -------------------------------------------------
# 67-PROGRESS SET GENERATOR (design → real functions)
# -------------------------------------------------

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def make_progress67_function_def(n: int) -> FunctionDef:
    """
    Build one of the 67-progress functions (n in [0,66]).
    Uses the design: crescent envelope + evolving carrier + harmonics + Gaussian spike.
    """
    if n < 0:
        n = 0
    if n > 66:
        n = 66
    p = n / 66.0  # progress parameter [0,1]

    def func(t: float, p=p) -> float:
        u = t - math.floor(t)

        # Envelope: crescent with exponent growing with p
        env_amp = 0.15 + 0.65 * p
        env = env_amp * (math.sin(math.pi * u) ** (1.0 + 2.0 * p))

        # Carrier: frequency increases slightly with p, with phase shift
        carrier = math.sin(2.0 * math.pi * (1.0 + 2.0 * p) * u + math.pi * p)

        # Harmonic 2 appears after p >= 1/3
        h2 = 0.0
        if p >= (1.0 / 3.0):
            alpha = (p - (1.0 / 3.0)) / (2.0 / 3.0)
            if alpha < 0.0:
                alpha = 0.0
            if alpha > 1.0:
                alpha = 1.0
            h2 = 0.25 * alpha * math.sin(4.0 * math.pi * u + 2.0 * math.pi * p)

        # Harmonic 3 appears after p >= 2/3
        h3 = 0.0
        if p >= (2.0 / 3.0):
            beta = (p - (2.0 / 3.0)) / (1.0 / 3.0)
            if beta < 0.0:
                beta = 0.0
            if beta > 1.0:
                beta = 1.0
            h3 = 0.18 * beta * math.sin(6.0 * math.pi * u + 3.0 * math.pi * p)

        # Gaussian spike around u0=0.2 with p-dependent strength
        # g(p): fade in (0.25→0.5), plateau, fade out (0.75→1)
        if p < 0.25:
            g_strength = 0.0
        elif p < 0.5:
            g_strength = 1.2 * ((p - 0.25) / 0.25)
        elif p < 0.75:
            g_strength = 1.2
        elif p <= 1.0:
            g_strength = 1.2 * (1.0 - (p - 0.75) / 0.25)
        else:
            g_strength = 0.0

        sharpness = 30.0 + 20.0 * p
        spike = 0.0
        if g_strength > 0.0:
            spike = g_strength * math.exp(-((u - 0.2) * sharpness) ** 2)

        return env * carrier + h2 + h3 + spike

    # Color gradient from teal → magenta-ish
    r = int(_lerp(64.0, 255.0, p))
    g = int(_lerp(200.0, 64.0, p))
    b = int(_lerp(255.0, 128.0, p))
    color = f"#{r:02x}{g:02x}{b:02x}"

    label = f"Progress 67 – step {n:02d}/66"
    expr_str = f"67-progress param n={n} (procedural)"

    return FunctionDef(
        name=f"progress67_{n:02d}",
        label=label,
        expr_str=expr_str,
        func=func,
        color=color,
    )


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

        line_color_hex = self.theme.function_line_override or self.color
        color = QColor(line_color_hex)
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
            QMessageBox.warning(self, "Expression tester", "Expression is empty.")
            return

        try:
            fn_callable = make_func_from_expr(expr)
        except Exception as e:
            QMessageBox.critical(self, "Expression tester", f"Invalid expression:\n{e}")
            self.preview_canvas.set_function(None, color)
            return

        self.preview_canvas.set_function(fn_callable, color)

    def _build_function_from_fields(self) -> Optional[FunctionDef]:
        name = self.edit_name.text().strip()
        label = self.edit_label.text().strip()
        expr = self.edit_expr.text().strip()
        color = self.edit_color.text().strip() or "#FFFFFF"

        if not name or not expr:
            QMessageBox.warning(self, "Function editor", "Name and expression are required.")
            return None

        if not label:
            label = name

        try:
            fn_callable = make_func_from_expr(expr)
        except Exception as e:
            QMessageBox.critical(self, "Expression error", f"Invalid expression:\n{e}")
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
# Pitch depends ONLY on Tone + y_amp at center dot
# -------------------------------------------------

class AudioEngine:
    """
    func_provider() -> (func, freq_factor, visual_time, amplitude)
    """

    def __init__(self, func_provider):
        if not HAVE_AUDIO:
            raise RuntimeError("sounddevice not available")

        self.func_provider = func_provider
        self.samplerate = 44100

        # master fader + tone
        self.volume = 0.2
        self.tone = 0.5
        self.phase = 0.0  # oscillator phase

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
        self.current_y_at_dot = 0.0  # y_amp at center dot

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

        # Clamp amplitude safely
        amplitude = max(0.0, min(1.5, amplitude))

        # ---- y_amp: use the SAME point as the canvas center dot ----
        # canvas & audio dot:
        # base_center = pi
        # t_center = freq_factor * (base_center + visual_time)
        base_center = math.pi
        t_center = freq_factor * (base_center + visual_time)
        y_raw = func(t_center)
        y_amp = amplitude * y_raw
        self.current_y_at_dot = y_amp  # this is the controlling y_amp

        # ---- PITCH: ONLY Tone (base pitch) and y_amp ----
        # Map y_amp in [-1,1] to a deviation around a Tone-defined base.
        span = max(1.0, self.pitch_max_hz - self.pitch_min_hz)
        base_center = self.pitch_min_hz + self.tone * span  # base pitch from Tone

        # normalized y_amp, strong effect on pitch (clearly up and down)
        y_norm = max(-1.0, min(1.0, y_amp))
        # allow up to +/- 50% of span around base
        deviation = 0.5 * span * y_norm

        freq_hz = base_center + deviation
        if freq_hz < 20.0:
            freq_hz = 20.0
        self.current_pitch_hz = freq_hz

        # Oscillator phase step for this pitch
        phase_step = 2.0 * math.pi * freq_hz / self.samplerate

        alpha_low = self.eq_alpha_low
        alpha_high = self.eq_alpha_high
        lp_low = self.eq_lp_low_state
        lp_high = self.eq_lp_high_state

        for i in range(frames):
            self.phase += phase_step
            if self.phase > 1e6:
                self.phase -= 1e6

            # Audio oscillator time – free-running phase, shape only.
            t = self.phase

            # gain + drive shaping
            x = amplitude * func(t)
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
        row6, self.edit_panel_field_bg, btn_panel_field_bg = make_color_row(
            "Panel fields (boxes)", self.theme.panel_field_bg
        )
        layout.addLayout(row6)
        row7, self.edit_func_line, btn_func_line = make_color_row(
            "Function line override (optional)", self.theme.function_line_override or ""
        )
        layout.addLayout(row7)

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
        connect_btn(btn_panel_field_bg, self.edit_panel_field_bg)
        connect_btn(btn_func_line, self.edit_func_line)

        box = QDialogButtonBox()
        ok_btn = box.addButton("OK", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self._on_ok)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self.resize(420, 340)

    def _on_ok(self):
        self.result_theme = ThemeConfig(
            canvas_bg=self.edit_canvas_bg.text().strip() or "#05060A",
            canvas_midline=self.edit_canvas_mid.text().strip() or "#1E1E28",
            panel_bg=self.edit_panel_bg.text().strip() or "#0B0D18",
            panel_text=self.edit_panel_text.text().strip() or "#FFFFFF",
            pointer_ring=self.edit_pointer_ring.text().strip() or "#FFFFFF",
            panel_field_bg=self.edit_panel_field_bg.text().strip() or "#10121F",
            function_line_override=self.edit_func_line.text().strip(),
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
        dt = 0.016 * self.time_speed
        self.time += dt
        win = self.window()
        if hasattr(win, "on_canvas_tick"):
            win.on_canvas_tick(dt)
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

        line_color_hex = self.theme.function_line_override or fn.color
        color = QColor(line_color_hex)
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
        painter.setBrush(color)
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
        self.live_y_amp_path = os.path.join(self.base_dir, "y_amp_live.json")

        self.setWindowTitle("Live Pattern Lab")
        self.setMinimumSize(1150, 600)

        # full dark mode background for root window
        self.setStyleSheet("background-color: #05060A; color: #FFFFFF;")

        self.audio_engine: Optional[AudioEngine] = None
        if HAVE_AUDIO:
            try:
                self.audio_engine = AudioEngine(self._get_audio_state)
            except Exception:
                self.audio_engine = None

        # sequence state
        self.sequence: List[Dict[str, Any]] = []
        self.sequence_playing: bool = False
        self.sequence_index: int = 0
        self.sequence_segment_elapsed: float = 0.0

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

        # Hidden shortcut for exporting live y_amp reader .py
        self._export_shortcut = QShortcut(QKeySequence("Ctrl+E"), self)
        self._export_shortcut.activated.connect(self._export_y_amp_py)

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

    # ---- live y_amp writer ---- #

    def _write_live_y_amp(self, fn: FunctionDef, y_raw: float, y_amp: float):
        data = {
            "pattern_name": fn.name,
            "pattern_label": fn.label,
            "expr": fn.expr_str,
            "y_raw": y_raw,
            "y_amp": y_amp,
        }
        if self.audio_engine is not None:
            data["pitch_hz"] = self.audio_engine.current_pitch_hz
        else:
            data["pitch_hz"] = None

        try:
            with open(self.live_y_amp_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    # ---- UI BUILD ---- #

    def _build_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        panel.setMinimumWidth(400)
        self._apply_panel_theme(panel)

        # pattern selection
        layout.addWidget(self._make_label("Pattern (combo)"))
        self.func_combo = QComboBox()
        layout.addWidget(self.func_combo)

        layout.addWidget(self._make_label("Functions list"))
        self.func_list = QListWidget()
        self.func_list.setMinimumHeight(120)
        self.func_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.func_list)

        self.func_combo.currentIndexChanged.connect(self._on_combo_changed)
        self.func_list.currentRowChanged.connect(self._on_list_changed)

        # expression
        layout.addWidget(self._make_label("Expression"))
        self.expr_label = QLabel()
        self.expr_label.setWordWrap(True)
        layout.addWidget(self.expr_label)

        # current dot
        layout.addWidget(self._make_label("Current y_amp (audio-linked)"))
        self.y_value_label = QLabel("y_amp = 0.0")
        self.y_value_label.setStyleSheet(f"font-size: 12px; color: {self.theme.panel_text};")
        layout.addWidget(self.y_value_label)

        layout.addSpacing(4)

        # sliders
        layout.addWidget(self._make_label("Amplitude (visual + sound)"))
        amp_slider = QSlider(Qt.Orientation.Horizontal)
        amp_slider.setRange(0, 150)
        amp_slider.setValue(int(self.canvas.amplitude * 100))
        amp_slider.valueChanged.connect(self.canvas.set_amplitude_from_slider)
        layout.addWidget(amp_slider)

        layout.addWidget(self._make_label("Frequency (visual only)"))
        freq_slider = QSlider(Qt.Orientation.Horizontal)
        freq_slider.setRange(1, 100)
        freq_slider.setValue(int(self.canvas.frequency * 10))
        freq_slider.valueChanged.connect(self.canvas.set_frequency_from_slider)
        layout.addWidget(freq_slider)

        layout.addWidget(self._make_label("Speed (visual scroll only)"))
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

        # audio controls
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

            layout.addWidget(QLabel("Tone (base pitch)"))
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

        # function editor + JSON lists
        editor_btn = QPushButton("Function editor…")
        editor_btn.clicked.connect(self._open_function_editor)
        layout.addWidget(editor_btn)

        json_mgr_btn = QPushButton("Lists…")
        json_mgr_btn.clicked.connect(self._open_json_list_manager)
        layout.addWidget(json_mgr_btn)

        # Combine selected functions mathematically (sum)
        comb_btn = QPushButton("Combine selected (sum)")
        comb_btn.clicked.connect(self._combine_selected_functions)
        layout.addWidget(comb_btn)

        # 67-progress generator
        build67_btn = QPushButton("Build 67-progress set")
        build67_btn.clicked.connect(self._build_67_progress_set)
        layout.addWidget(build67_btn)

        # mixer + theme
        if self.audio_engine is not None:
            mixer_btn = QPushButton("Mixer…")
            mixer_btn.clicked.connect(self._open_mixer)
            layout.addWidget(mixer_btn)

        theme_btn = QPushButton("Theme…")
        theme_btn.clicked.connect(self._open_theme)
        layout.addWidget(theme_btn)

        # JSON preview
        layout.addWidget(self._make_label("JSON preview (selected)"))
        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setMaximumHeight(120)
        layout.addWidget(self.json_preview)

        save_btn = QPushButton("Save functions as…")
        save_btn.clicked.connect(self._save_functions_to_file)
        layout.addWidget(save_btn)

        load_file_btn = QPushButton("Load functions from file…")
        load_file_btn.clicked.connect(self._load_functions_from_file)
        layout.addWidget(load_file_btn)

        reload_btn = QPushButton("Reload ALL tri*.json functions")
        reload_btn.clicked.connect(self._reload_tri_functions)
        layout.addWidget(reload_btn)

        layout.addSpacing(10)

        # SEQUENCE BUILDER (time-based function chain)
        layout.addWidget(self._make_label("Sequence builder (by time)"))

        row_seq = QHBoxLayout()
        self.sequence_func_combo = QComboBox()
        row_seq.addWidget(self.sequence_func_combo)

        self.sequence_time_spin = QDoubleSpinBox()
        self.sequence_time_spin.setRange(0.1, 9999.0)
        self.sequence_time_spin.setDecimals(2)
        self.sequence_time_spin.setValue(5.0)
        self.sequence_time_spin.setSuffix(" s")
        row_seq.addWidget(self.sequence_time_spin)

        add_seg_btn = QPushButton("Add")
        add_seg_btn.clicked.connect(self._add_sequence_segment)
        row_seq.addWidget(add_seg_btn)

        layout.addLayout(row_seq)

        self.sequence_list = QListWidget()
        self.sequence_list.setMinimumHeight(120)
        layout.addWidget(self.sequence_list)

        seq_btn_row1 = QHBoxLayout()
        rm_seg_btn = QPushButton("Remove selected")
        rm_seg_btn.clicked.connect(self._remove_sequence_segment)
        seq_btn_row1.addWidget(rm_seg_btn)

        clear_seq_btn = QPushButton("Clear sequence")
        clear_seq_btn.clicked.connect(self._clear_sequence)
        seq_btn_row1.addWidget(clear_seq_btn)

        play_seq_btn = QPushButton("Play / Stop")
        play_seq_btn.clicked.connect(self._toggle_sequence_play)
        seq_btn_row1.addWidget(play_seq_btn)

        layout.addLayout(seq_btn_row1)

        seq_btn_row2 = QHBoxLayout()
        save_seq_btn = QPushButton("Save sequence…")
        save_seq_btn.clicked.connect(self._save_sequence)
        seq_btn_row2.addWidget(save_seq_btn)

        load_seq_btn = QPushButton("Load sequence…")
        load_seq_btn.clicked.connect(self._load_sequence)
        seq_btn_row2.addWidget(load_seq_btn)

        layout.addLayout(seq_btn_row2)

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
QLabel {{
  font-size: 9pt;
  color: {self.theme.panel_text};
  background-color: transparent;
}}
QLineEdit, QPlainTextEdit, QListWidget, QComboBox {{
  font-size: 9pt;
  color: {self.theme.panel_text};
  background-color: {self.theme.panel_field_bg};
  border: 1px solid #23263A;
  border-radius: 6px;
  padding: 3px 5px;
}}
QListWidget::item:selected {{
  background-color: #2d3250;
  color: {self.theme.panel_text};
}}
QComboBox::drop-down {{
  border: none;
}}
QComboBox QAbstractItemView {{
  background-color: #141726;
  selection-background-color: #2d3250;
  color: {self.theme.panel_text};
}}
QPlainTextEdit {{
  background-color: {self.theme.panel_field_bg};
  border-radius: 6px;
}}
QPushButton {{
  font-size: 9pt;
  color: {self.theme.panel_text};
  background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 #2A2E45, stop:1 #3F4365);
  border: 1px solid #50538A;
  border-radius: 8px;
  padding: 6px 10px;
}}
QPushButton:hover {{
  background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 #343957, stop:1 #4C5280);
}}
QPushButton:pressed {{
  background-color: #22263A;
}}
QSlider::groove:horizontal {{
  border: 1px solid #202435;
  height: 6px;
  background: #181B2A;
  border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
  background: #5B8CFF;
  border-radius: 3px;
}}
QSlider::add-page:horizontal {{
  background: #101320;
  border-radius: 3px;
}}
QSlider::handle:horizontal {{
  background: #F6F7FF;
  border: 2px solid #5B8CFF;
  width: 14px;
  margin: -6px 0;
  border-radius: 9px;
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
            self._select_function_index(idx)
        else:
            self.expr_label.setText("—")
            self.json_preview.setPlainText("")

        self.func_combo.blockSignals(False)
        self.func_list.blockSignals(False)

        # keep sequence combo in sync
        if hasattr(self, "sequence_func_combo"):
            self.sequence_func_combo.blockSignals(True)
            self.sequence_func_combo.clear()
            for fn in self.functions:
                self.sequence_func_combo.addItem(fn.label)
            self.sequence_func_combo.blockSignals(False)

    def _select_function_index(self, index: int):
        if not (0 <= index < len(self.functions)):
            return
        self.func_combo.blockSignals(True)
        self.func_list.blockSignals(True)
        self.func_combo.setCurrentIndex(index)
        self.func_list.setCurrentRow(index)
        self.func_combo.blockSignals(False)
        self.func_list.blockSignals(False)

        self.canvas.set_function_index(index)
        self._update_expr_label(index)
        self._update_json_preview(index)
        self.update_y_display()

    def _on_combo_changed(self, index: int):
        if index < 0 or index >= len(self.functions):
            return
        self._select_function_index(index)

    def _on_list_changed(self, row: int):
        if row < 0 or row >= len(self.functions):
            return
        self._select_function_index(row)

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

    # ---- amplitude-scaled y & pitch display ---- #

    def update_y_display(self):
        if not self.functions:
            self.y_value_label.setText("—")
            return

        idx = self.canvas.current_index
        if idx < 0 or idx >= len(self.functions):
            self.y_value_label.setText("—")
            return

        fn = self.functions[idx]

        # Use the SAME t_center as canvas & audio engine:
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

        # write live value for external readers
        self._write_live_y_amp(fn, y_raw, y_amp)

    # ---- canvas tick hook (for sequence + y display) ---- #

    def on_canvas_tick(self, dt: float):
        # update sequence playback
        if self.sequence_playing and self.sequence:
            self._advance_sequence(dt)
        # update label + live json
        self.update_y_display()

    # ---- function combiner ---- #

    def _combine_selected_functions(self):
        selected = self.func_list.selectedIndexes()
        if len(selected) < 2:
            QMessageBox.information(
                self,
                "Combine functions",
                "Select at least two functions in the list (Ctrl+click / Shift+click).",
            )
            return

        indices = sorted({idx.row() for idx in selected if 0 <= idx.row() < len(self.functions)})
        if len(indices) < 2:
            return

        exprs = [self.functions[i].expr_str for i in indices]
        names = [self.functions[i].name for i in indices]
        labels = [self.functions[i].label for i in indices]

        combined_expr = " + ".join(f"({e})" for e in exprs)
        base_name = "combo_" + "_".join(names)
        new_name = base_name[:60]

        try:
            fn_callable = make_func_from_expr(combined_expr)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Combine functions",
                f"Failed to combine expressions:\n{e}",
            )
            return

        fn = FunctionDef(
            name=new_name,
            label="Combo: " + " + ".join(labels),
            expr_str=combined_expr,
            func=fn_callable,
            color="#FFFFFF",
        )
        self.functions.append(fn)
        self.canvas.functions = self.functions
        self._rebuild_function_views(select_index=len(self.functions) - 1)
        self._append_history("add_combo", fn)

    # ---- 67-progress set builder ---- #

    def _build_67_progress_set(self):
        funcs = [make_progress67_function_def(n) for n in range(67)]
        self.functions = funcs
        self.canvas.functions = funcs
        self._rebuild_function_views(select_index=0)
        QMessageBox.information(
            self,
            "67-progress set",
            "Generated 67-step progress set.\nUse 'Save functions as…' to store it into a tri_*.json file.",
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

    # ---- save current functions (choose file name) ---- #

    def _save_functions_to_file(self):
        default_path = os.path.join(self.base_dir, "tri_custom.json")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save functions as",
            default_path,
            "JSON files (*.json);;All files (*)",
        )
        if not out_path:
            return

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

    # ---- load functions from single file ---- #

    def _load_functions_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load functions from file",
            self.base_dir,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load functions", f"Failed to load:\n{e}")
            return

        if not isinstance(data, list):
            QMessageBox.critical(self, "Load functions", "Selected JSON is not a list.")
            return

        new_funcs: List[FunctionDef] = []
        for item in data:
            try:
                name = str(item.get("name", "unnamed"))
                label = str(item.get("label", name))
                expr = str(item.get("expr", "sin(t)"))
                color = str(item.get("color", "#FFFFFF"))
                fn = make_func_from_expr(expr)
                new_funcs.append(
                    FunctionDef(
                        name=name,
                        label=label,
                        expr_str=expr,
                        func=fn,
                        color=color,
                    )
                )
            except Exception:
                continue

        if not new_funcs:
            QMessageBox.warning(
                self,
                "Load functions",
                "No valid functions found in the selected file.",
            )
            return

        self.functions = new_funcs
        self.canvas.functions = new_funcs
        self._rebuild_function_views(select_index=0)

        QMessageBox.information(
            self,
            "Load functions",
            f"Loaded {len(new_funcs)} functions from:\n{os.path.basename(path)}",
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

    # ---- sequence helpers ---- #

    def _find_function_index_by_name(self, name: str) -> int:
        for i, fn in enumerate(self.functions):
            if fn.name == name:
                return i
        return -1

    def _add_sequence_segment(self):
        if not self.functions:
            return
        idx = self.sequence_func_combo.currentIndex()
        if idx < 0 or idx >= len(self.functions):
            return
        fn = self.functions[idx]
        dur = float(self.sequence_time_spin.value())
        if dur <= 0.0:
            return
        seg = {"name": fn.name, "label": fn.label, "duration": dur}
        self.sequence.append(seg)
        self.sequence_list.addItem(f"{fn.label} – {dur:.2f}s")

    def _remove_sequence_segment(self):
        row = self.sequence_list.currentRow()
        if row < 0 or row >= len(self.sequence):
            return
        self.sequence_list.takeItem(row)
        del self.sequence[row]
        if self.sequence_index >= len(self.sequence):
            self.sequence_index = max(0, len(self.sequence) - 1)
        if not self.sequence:
            self.sequence_playing = False
            self.sequence_segment_elapsed = 0.0

    def _clear_sequence(self):
        self.sequence = []
        self.sequence_list.clear()
        self.sequence_playing = False
        self.sequence_index = 0
        self.sequence_segment_elapsed = 0.0

    def _toggle_sequence_play(self):
        if not self.sequence:
            QMessageBox.information(self, "Sequence", "Sequence is empty.")
            return
        if not self.sequence_playing:
            # start from first segment
            self.sequence_playing = True
            self.sequence_index = 0
            self.sequence_segment_elapsed = 0.0
            # jump to first valid function
            for _ in range(len(self.sequence)):
                seg = self.sequence[self.sequence_index]
                idx = self._find_function_index_by_name(seg["name"])
                if idx != -1:
                    self._select_function_index(idx)
                    break
                else:
                    self.sequence_index = (self.sequence_index + 1) % len(self.sequence)
        else:
            self.sequence_playing = False

    def _advance_sequence(self, dt: float):
        if not self.sequence:
            return
        if self.sequence_index < 0 or self.sequence_index >= len(self.sequence):
            self.sequence_index = 0
            self.sequence_segment_elapsed = 0.0

        self.sequence_segment_elapsed += dt

        safety = 0
        while safety < len(self.sequence):
            seg = self.sequence[self.sequence_index]
            dur = max(0.001, float(seg.get("duration", 0.0)))
            if self.sequence_segment_elapsed < dur:
                break
            self.sequence_segment_elapsed -= dur
            self.sequence_index = (self.sequence_index + 1) % len(self.sequence)
            safety += 1

        # ensure current segment uses an existing function
        for _ in range(len(self.sequence)):
            seg = self.sequence[self.sequence_index]
            idx = self._find_function_index_by_name(seg["name"])
            if idx != -1:
                self._select_function_index(idx)
                break
            else:
                self.sequence_index = (self.sequence_index + 1) % len(self.sequence)

    def _save_sequence(self):
        if not self.sequence:
            QMessageBox.information(self, "Save sequence", "Sequence is empty.")
            return

        default_path = os.path.join(self.base_dir, "tri_sequence.json")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save sequence",
            default_path,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        data = {"sequence": self.sequence}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(
                self,
                "Save sequence",
                f"Saved {len(self.sequence)} segments to:\n{path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Save sequence", f"Failed to save:\n{e}")

    def _load_sequence(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load sequence",
            self.base_dir,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load sequence", f"Failed to load:\n{e}")
            return

        seq = data.get("sequence")
        if not isinstance(seq, list):
            QMessageBox.critical(self, "Load sequence", "Invalid sequence format.")
            return

        self.sequence = []
        self.sequence_list.clear()
        for item in seq:
            try:
                name = str(item["name"])
                label = str(item.get("label", name))
                dur = float(item["duration"])
                self.sequence.append({"name": name, "label": label, "duration": dur})
                self.sequence_list.addItem(f"{label} – {dur:.2f}s")
            except Exception:
                continue

        self.sequence_playing = False
        self.sequence_index = 0
        self.sequence_segment_elapsed = 0.0

    # ---- hidden export of live y_amp reader ---- #

    def _export_y_amp_py(self):
        if not self.functions:
            QMessageBox.warning(self, "Export y_amp", "No functions available to export.")
            return

        idx = self.canvas.current_index
        if idx < 0 or idx >= len(self.functions):
            QMessageBox.warning(self, "Export y_amp", "No valid selection to export.")
            return

        fn = self.functions[idx]
        safe_name = fn.name or "pattern"
        default_path = os.path.join(self.base_dir, f"y_amp_live_{safe_name}.py")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export live y_amp reader .py",
            default_path,
            "Python files (*.py);;All files (*)",
        )
        if not path:
            return

        code = '''"""
Auto-generated live y_amp reader.

This module does NOT reveal the underlying function or math.
It only reads the live value written by the main application.

API:
    get_live_y_amp()   -> float or None
    get_live_data()    -> dict or None
"""

import json
import os

# File updated continuously by the main application
LIVE_JSON = os.path.join(os.path.dirname(__file__), "y_amp_live.json")

def get_live_data():
    """Return the full live state dictionary, or None if unavailable."""
    try:
        with open(LIVE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_live_y_amp():
    """Return the current y_amp value, or None if unavailable."""
    data = get_live_data()
    if not data:
        return None
    return data.get("y_amp")
'''

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            QMessageBox.information(
                self,
                "Export y_amp",
                f"Exported live y_amp reader for '{fn.label}' to:\n{path}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export y_amp",
                f"Failed to write file:\n{e}",
            )

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
