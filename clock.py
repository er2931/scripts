import sys
from PyQt6.QtCore import QTimer, QTime
from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtGui import QFont

app = QApplication(sys.argv)

label = QLabel()
label.setFont(QFont("Segoe UI", 40))
label.setStyleSheet("color: white; background-color: black; padding: 20px;")
label.setWindowTitle("Clock")
label.show()

def update_time():
    label.setText(QTime.currentTime().toString("HH:mm:ss"))

timer = QTimer()
timer.timeout.connect(update_time)
timer.start(1000)

update_time()

sys.exit(app.exec())
