import sys
from PyQt6.QtCore import QTimer, QTime, Qt
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtGui import QFont, QColor


class FloatingClock(QWidget):
    def __init__(self):
        super().__init__()

        # Remove window frame + enable transparency
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Neon font
        font = QFont("Segoe UI", 48, QFont.Weight.Bold)
        self.label.setFont(font)

        # Transparent background, neon text
        self.label.setStyleSheet("color: #6ad9ff; background: transparent;")

        # Glow effect
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(40)
        glow.setColor(QColor(80, 200, 255))
        glow.setOffset(0, 0)
        self.label.setGraphicsEffect(glow)

        layout.addWidget(self.label)
        self.setLayout(layout)

        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
        self.update_time()

        self.resize(330, 100)

        # allow dragging
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
        self.label.setText(QTime.currentTime().toString("HH:mm:ss"))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    clock = FloatingClock()
    clock.show()
    sys.exit(app.exec())
