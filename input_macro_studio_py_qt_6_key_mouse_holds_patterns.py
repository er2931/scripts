"""
Input Macro Studio — PyQt6

Features
- Build sequences of actions (keyboard/mouse) with precise timing.
- Supports holds (keyDown/keyUp, mouseDown/mouseUp), clicks, moves, text typing, waits, and repeats.
- Start/Stop playback; shows running highlight.
- Save/Load configurations to JSON.
- Optional global hotkeys to start/stop (requires `keyboard` library; app works without it).

Dependencies
    pip install PyQt6 pyautogui keyboard

Notes & Safety
- On macOS, give the terminal/app Accessibility permissions for input control.
- Be mindful of app/site/game terms of service. Rapid automation can be detected; use responsibly.
- ESC key in the app window will stop playback.

Run
    python input_macro_studio.py
"""
from __future__ import annotations
import json, os, threading, time, sys
from dataclasses import dataclass, asdict
from typing import List, Optional

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QFileDialog, QComboBox, QDoubleSpinBox, QSpinBox, QTableView,
    QMessageBox, QToolBar, QStatusBar, QDialog, QFormLayout, QCheckBox
)

# Optional global hotkeys
try:
    import keyboard  # pip install keyboard
    KEYBOARD_AVAILABLE = True
except Exception:
    KEYBOARD_AVAILABLE = False

import pyautogui  # pip install pyautogui
pyautogui.FAILSAFE = True  # Move mouse to a corner to abort

ACTIONS = [
    "key_down",      # args: key
    "key_up",        # args: key
    "key_tap",       # args: key, count
    "type_text",     # args: text
    "mouse_down",    # args: button
    "mouse_up",      # args: button
    "mouse_click",   # args: button, count
    "mouse_move",    # args: x, y, duration
    "mouse_scroll",  # args: clicks (int), horizontal(bool)
    "wait"           # args: seconds (float)
]

MOUSE_BUTTONS = ["left", "middle", "right"]

DEFAULT_CONFIG_PATH = "macro_config.json"

@dataclass
class Step:
    action: str = "wait"
    arg1: str | float | int | None = None
    arg2: str | float | int | None = None
    arg3: str | float | int | None = None
    delay_after: float = 0.05  # seconds to wait after executing this step
    repeat: int = 1

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Step":
        s = Step()
        s.action = d.get("action", "wait")
        s.arg1   = d.get("arg1")
        s.arg2   = d.get("arg2")
        s.arg3   = d.get("arg3")
        s.delay_after = float(d.get("delay_after", 0.05))
        s.repeat = int(d.get("repeat", 1))
        return s

class StepsModel(QAbstractTableModel):
    headers = ["#", "Action", "Arg1", "Arg2", "Arg3", "Delay After (s)", "Repeat"]

    def __init__(self, steps: List[Step]):
        super().__init__()
        self.steps = steps

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.steps)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.headers)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        step = self.steps[index.row()]
        col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return index.row() + 1
            elif col == 1:
                return step.action
            elif col == 2:
                return "" if step.arg1 is None else str(step.arg1)
            elif col == 3:
                return "" if step.arg2 is None else str(step.arg2)
            elif col == 4:
                return "" if step.arg3 is None else str(step.arg3)
            elif col == 5:
                return step.delay_after
            elif col == 6:
                return step.repeat
        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return QVariant()
        if orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return section + 1

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        step = self.steps[index.row()]
        col = index.column()
        try:
            if col == 1:
                if value in ACTIONS:
                    step.action = value
            elif col == 2:
                step.arg1 = self._coerce(value)
            elif col == 3:
                step.arg2 = self._coerce(value)
            elif col == 4:
                step.arg3 = self._coerce(value)
            elif col == 5:
                step.delay_after = float(value)
            elif col == 6:
                step.repeat = int(value)
            else:
                return False
            self.dataChanged.emit(index, index, [])
            return True
        except Exception:
            return False

    def insert_step(self, pos: Optional[int] = None, step: Optional[Step] = None):
        if step is None:
            step = Step()
        if pos is None:
            pos = len(self.steps)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self.steps.insert(pos, step)
        self.endInsertRows()

    def remove_step(self, row: int):
        if 0 <= row < len(self.steps):
            self.beginRemoveRows(QModelIndex(), row, row)
            self.steps.pop(row)
            self.endRemoveRows()

    def move_step(self, src: int, dst: int):
        if src == dst or not (0 <= src < len(self.steps)) or not (0 <= dst < len(self.steps)):
            return
        self.beginMoveRows(QModelIndex(), src, src, QModelIndex(), dst + (1 if dst > src else 0))
        self.steps.insert(dst, self.steps.pop(src))
        self.endMoveRows()

    def _coerce(self, v):
        if v is None:
            return None
        s = str(v).strip()
        if s == "":
            return None
        # try int, then float, else string
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return s

class Player(QObject):
    started = pyqtSignal()
    finished = pyqtSignal()
    step_started = pyqtSignal(int)

    def __init__(self, steps: List[Step]):
        super().__init__()
        self.steps = steps
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.started.emit()

    def stop(self):
        self._stop_flag.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        try:
            for idx, step in enumerate(self.steps):
                if self._stop_flag.is_set():
                    break
                self.step_started.emit(idx)
                for _ in range(max(1, int(step.repeat))):
                    if self._stop_flag.is_set():
                        break
                    self._execute(step)
                    # delay after
                    total_wait = float(step.delay_after or 0)
                    t0 = time.time()
                    while time.time() - t0 < total_wait:
                        if self._stop_flag.is_set():
                            break
                        time.sleep(0.005)
                if self._stop_flag.is_set():
                    break
        finally:
            self.finished.emit()

    # --- executor ---
    def _execute(self, s: Step):
        try:
            if s.action == "key_down" and s.arg1:
                pyautogui.keyDown(str(s.arg1))
            elif s.action == "key_up" and s.arg1:
                pyautogui.keyUp(str(s.arg1))
            elif s.action == "key_tap" and s.arg1:
                count = int(s.arg2 or 1)
                for _ in range(max(1, count)):
                    pyautogui.press(str(s.arg1))
            elif s.action == "type_text" and s.arg1 is not None:
                pyautogui.typewrite(str(s.arg1))
            elif s.action == "mouse_down" and s.arg1 in MOUSE_BUTTONS:
                pyautogui.mouseDown(button=str(s.arg1))
            elif s.action == "mouse_up" and s.arg1 in MOUSE_BUTTONS:
                pyautogui.mouseUp(button=str(s.arg1))
            elif s.action == "mouse_click" and s.arg1 in MOUSE_BUTTONS:
                clicks = int(s.arg2 or 1)
                pyautogui.click(button=str(s.arg1), clicks=clicks)
            elif s.action == "mouse_move":
                # arg1=x, arg2=y, arg3=duration
                x = int(s.arg1 if s.arg1 is not None else 0)
                y = int(s.arg2 if s.arg2 is not None else 0)
                dur = float(s.arg3 if s.arg3 is not None else 0)
                pyautogui.moveTo(x, y, duration=max(0.0, dur))
            elif s.action == "mouse_scroll":
                # arg1=clicks, arg2=horizontal(bool)
                clicks = int(s.arg1 or 0)
                horizontal = bool(s.arg2) if s.arg2 is not None else False
                if horizontal:
                    pyautogui.hscroll(clicks)
                else:
                    pyautogui.scroll(clicks)
            elif s.action == "wait":
                time.sleep(float(s.arg1 or 0))
        except Exception as e:
            print(f"Step error: {e}")

class StepEditor(QDialog):
    def __init__(self, parent=None, step: Optional[Step]=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Step")
        self.setModal(True)
        self.step = step or Step()

        form = QFormLayout(self)

        self.action = QComboBox(); self.action.addItems(ACTIONS)
        self.action.setCurrentText(self.step.action)
        self.arg1  = QLineEdit(); self.arg2 = QLineEdit(); self.arg3 = QLineEdit()
        self.delay = QDoubleSpinBox(); self.delay.setRange(0, 3600); self.delay.setDecimals(3); self.delay.setSingleStep(0.05)
        self.delay.setValue(self.step.delay_after)
        self.repeat = QSpinBox(); self.repeat.setRange(1, 100000); self.repeat.setValue(self.step.repeat)

        form.addRow("Action", self.action)
        form.addRow("Arg1", self.arg1)
        form.addRow("Arg2", self.arg2)
        form.addRow("Arg3", self.arg3)
        form.addRow("Delay After", self.delay)
        form.addRow("Repeat", self.repeat)

        # helper label
        self.hint = QLabel(self._hint_text(self.step.action)); self.hint.setWordWrap(True)
        form.addRow(QLabel("Hint"), self.hint)

        btns = QHBoxLayout()
        save = QPushButton("Save"); cancel = QPushButton("Cancel")
        btns.addWidget(save); btns.addWidget(cancel)
        container = QWidget(); container.setLayout(btns)
        form.addRow(container)

        self.action.currentTextChanged.connect(lambda a: self.hint.setText(self._hint_text(a)))
        save.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

    def _hint_text(self, a: str) -> str:
        hints = {
            "key_down": "Arg1=key (e.g., 'a', 'ctrl', 'enter'). Holds key down.",
            "key_up": "Arg1=key. Releases key.",
            "key_tap": "Arg1=key, Arg2=count.",
            "type_text": "Arg1=text to type.",
            "mouse_down": "Arg1=left|middle|right.",
            "mouse_up": "Arg1=left|middle|right.",
            "mouse_click": "Arg1=left|middle|right, Arg2=count.",
            "mouse_move": "Arg1=x, Arg2=y, Arg3=duration(s).",
            "mouse_scroll": "Arg1=clicks (+/-), Arg2=1 for horizontal.",
            "wait": "Arg1=seconds to wait before continuing."
        }
        return hints.get(a, "")

    def get_step(self) -> Step:
        s = Step()
        s.action = self.action.currentText()
        s.arg1 = self._coerce(self.arg1.text())
        s.arg2 = self._coerce(self.arg2.text())
        s.arg3 = self._coerce(self.arg3.text())
        s.delay_after = self.delay.value()
        s.repeat = self.repeat.value()
        return s

    def _coerce(self, v: str):
        v = v.strip()
        if v == "":
            return None
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Input Macro Studio — Key/Mouse Patterns")
        self.resize(1000, 600)

        self.steps: List[Step] = []
        self.model = StepsModel(self.steps)
        self.player = Player(self.steps)

        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Toolbar
        tb = QToolBar("Toolbar"); self.addToolBar(tb)

        act_add = QAction("Add", self); tb.addAction(act_add)
        act_edit = QAction("Edit", self); tb.addAction(act_edit)
        act_del = QAction("Delete", self); tb.addAction(act_del)
        tb.addSeparator()
        act_up = QAction("Up", self); tb.addAction(act_up)
        act_down = QAction("Down", self); tb.addAction(act_down)
        tb.addSeparator()
        act_play = QAction("Play", self); tb.addAction(act_play)
        act_stop = QAction("Stop", self); tb.addAction(act_stop)
        tb.addSeparator()
        act_save = QAction("Save", self); tb.addAction(act_save)
        act_load = QAction("Load", self); tb.addAction(act_load)

        # Global hotkeys box
        gh_box = QHBoxLayout()
        gh_label = QLabel("Global Hotkeys (optional): Start:")
        self.hk_start = QLineEdit("ctrl+alt+\"\\")  # default unusual combo
        gh_label2 = QLabel("Stop:")
        self.hk_stop = QLineEdit("ctrl+alt+\"/\"")
        self.hk_enable = QCheckBox("Enable")
        self.hk_enable.setChecked(False)
        gh_box.addWidget(gh_label); gh_box.addWidget(self.hk_start)
        gh_box.addWidget(gh_label2); gh_box.addWidget(self.hk_stop)
        gh_box.addWidget(self.hk_enable)

        layout.addLayout(gh_box)

        # Table
        self.table = QTableView(); self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        # Quick add row
        quick = QHBoxLayout()
        self.cbAction = QComboBox(); self.cbAction.addItems(ACTIONS)
        self.inArg1 = QLineEdit(); self.inArg1.setPlaceholderText("Arg1")
        self.inArg2 = QLineEdit(); self.inArg2.setPlaceholderText("Arg2")
        self.inArg3 = QLineEdit(); self.inArg3.setPlaceholderText("Arg3")
        self.spDelay = QDoubleSpinBox(); self.spDelay.setRange(0, 3600); self.spDelay.setDecimals(3); self.spDelay.setSingleStep(0.05); self.spDelay.setValue(0.05)
        self.spRepeat = QSpinBox(); self.spRepeat.setRange(1, 100000); self.spRepeat.setValue(1)
        btnAdd = QPushButton("Add Step")
        quick.addWidget(QLabel("Action")); quick.addWidget(self.cbAction)
        quick.addWidget(self.inArg1); quick.addWidget(self.inArg2); quick.addWidget(self.inArg3)
        quick.addWidget(QLabel("Delay After")); quick.addWidget(self.spDelay)
        quick.addWidget(QLabel("Repeat")); quick.addWidget(self.spRepeat)
        quick.addWidget(btnAdd)
        layout.addLayout(quick)

        # Status
        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Ready. Press Play to run the sequence.")

        # Connections
        act_add.triggered.connect(self.add_step_dialog)
        act_edit.triggered.connect(self.edit_selected)
        act_del.triggered.connect(self.delete_selected)
        act_up.triggered.connect(lambda: self.move_selected(-1))
        act_down.triggered.connect(lambda: self.move_selected(+1))
        act_play.triggered.connect(self.play)
        act_stop.triggered.connect(self.stop)
        act_save.triggered.connect(self.save_config)
        act_load.triggered.connect(self.load_config)
        btnAdd.clicked.connect(self.add_quick)

        self.player.started.connect(lambda: self.status.showMessage("Running… (press ESC in window or your Stop hotkey)"))
        self.player.finished.connect(lambda: self.status.showMessage("Finished or Stopped."))
        self.player.step_started.connect(self.highlight_row)

        # ESC to stop
        self._esc_filter_installed = False
        self.installEventFilter(self)

        # optional hotkeys
        self._hotkeys_registered = False
        self.hotkey_timer = QTimer(self)
        self.hotkey_timer.setInterval(600)
        self.hotkey_timer.timeout.connect(self._apply_hotkeys)
        self.hotkey_timer.start()

    # --------- UI helpers ---------
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.stop()
            return True
        return super().eventFilter(obj, event)

    def current_row(self) -> int:
        sel = self.table.selectionModel().selectedRows()
        return sel[0].row() if sel else -1

    def add_quick(self):
        step = Step(
            action=self.cbAction.currentText(),
            arg1=self._coerce(self.inArg1.text()),
            arg2=self._coerce(self.inArg2.text()),
            arg3=self._coerce(self.inArg3.text()),
            delay_after=self.spDelay.value(),
            repeat=self.spRepeat.value()
        )
        self.model.insert_step(step=step)

    def add_step_dialog(self):
        dlg = StepEditor(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.model.insert_step(step=dlg.get_step())

    def edit_selected(self):
        row = self.current_row()
        if row < 0:
            return
        dlg = StepEditor(self, step=self.steps[row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.steps[row] = dlg.get_step()
            self.model.dataChanged.emit(self.model.index(row,0), self.model.index(row, self.model.columnCount()-1))

    def delete_selected(self):
        row = self.current_row()
        if row >= 0:
            self.model.remove_step(row)

    def move_selected(self, delta: int):
        row = self.current_row()
        if row < 0:
            return
        dst = max(0, min(len(self.steps)-1, row + delta))
        self.model.move_step(row, dst)
        self.table.selectRow(dst)

    def highlight_row(self, idx: int):
        self.table.selectRow(idx)
        self.table.scrollTo(self.model.index(idx, 0))

    def play(self):
        if not self.steps:
            QMessageBox.warning(self, "No steps", "Add steps to play.")
            return
        # confirm focus
        QMessageBox.information(self, "Starting in 2s", "Switch to the target app. Playback starts in 2 seconds.")
        QApplication.processEvents()
        time.sleep(2)
        self.player.start()

    def stop(self):
        self.player.stop()

    # ---------- Save/Load ----------
    def save_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Config", DEFAULT_CONFIG_PATH, "JSON (*.json)")
        if not path:
            return
        data = {
            "steps": [s.to_dict() for s in self.steps],
            "hotkeys": {
                "enabled": self.hk_enable.isChecked(),
                "start": self.hk_start.text(),
                "stop": self.hk_stop.text()
            }
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.status.showMessage(f"Saved to {path}")

    def load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Config", DEFAULT_CONFIG_PATH, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))
            return
        steps = [Step.from_dict(d) for d in data.get("steps", [])]
        self.model.beginResetModel()
        self.steps.clear(); self.steps.extend(steps)
        self.model.endResetModel()
        hk = data.get("hotkeys", {})
        self.hk_enable.setChecked(bool(hk.get("enabled", False)))
        self.hk_start.setText(str(hk.get("start", "")))
        self.hk_stop.setText(str(hk.get("stop", "")))
        self.status.showMessage(f"Loaded {len(steps)} steps from {path}")

    # ---------- global hotkeys mgmt ----------
    def _apply_hotkeys(self):
        if not KEYBOARD_AVAILABLE:
            return
        want = self.hk_enable.isChecked()
        if want and not self._hotkeys_registered:
            try:
                keyboard.add_hotkey(self.hk_start.text().strip(), self.play)
                keyboard.add_hotkey(self.hk_stop.text().strip(), self.stop)
                self._hotkeys_registered = True
                self.status.showMessage("Global hotkeys registered.")
            except Exception as e:
                self.status.showMessage(f"Hotkey error: {e}")
        elif (not want) and self._hotkeys_registered:
            try:
                keyboard.remove_hotkey(self.hk_start.text().strip())
                keyboard.remove_hotkey(self.hk_stop.text().strip())
            except Exception:
                pass
            self._hotkeys_registered = False
            self.status.showMessage("Global hotkeys unregistered.")

    # utility
    def _coerce(self, v: str):
        v = v.strip()
        if v == "":
            return None
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
