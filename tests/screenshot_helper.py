# -*- coding: utf-8 -*-
"""全屏截图辅助脚本：python tools_screenshot.py <output.png>"""
import ctypes
import sys

ctypes.windll.shcore.SetProcessDpiAwareness(2)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv)
screen = app.primaryScreen()


def shoot():
    pix = screen.grabWindow(0)
    pix.save(sys.argv[1])
    app.quit()


QTimer.singleShot(800, shoot)
app.exec()
