# -*- coding: utf-8 -*-
"""把 MyDesk 主窗口移动到前台指定位置并截图
用法: python tests/activate_and_shot.py <output.png>
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

ctypes.windll.shcore.SetProcessDpiAwareness(2)

user32 = ctypes.windll.user32
target = []

ENUMProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _cb(hwnd, lparam):
    if user32.IsWindowVisible(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if 'MyDesk' in buf.value:
                target.append((hwnd, buf.value))
    return True


user32.EnumWindows(ENUMProc(_cb), 0)
print('found:', target)
if not target:
    print('MyDesk window not found')
    sys.exit(1)

hwnd, title = target[0]
rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
w = rect.right - rect.left
h = rect.bottom - rect.top
# 移到屏幕左上区域并置前
user32.MoveWindow(hwnd, 20, 20, w, h, True)
user32.SetForegroundWindow(hwnd)
time.sleep(1.0)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv)
screen = app.primaryScreen()


def shoot():
    pix = screen.grabWindow(0)
    pix.save(sys.argv[1])
    print('saved:', sys.argv[1])
    app.quit()


QTimer.singleShot(500, shoot)
app.exec()
