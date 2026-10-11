# -*- coding: utf-8 -*-
"""深色主题截图：python tests/shot_dark.py <输出目录>
先切换到深色主题，再抓取终端页与计算工具页的整窗截图，用于展示双主题能力。
"""
import ctypes
import sys
import os
import time

ctypes.windll.shcore.SetProcessDpiAwareness(2)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from core.plugin_manager import PluginManager
from core.main_window import MainWindow
from utils.config_manager import ConfigManager

outdir = sys.argv[1] if len(sys.argv) > 1 else '.'
os.makedirs(outdir, exist_ok=True)

app = QApplication(sys.argv)
cm = ConfigManager(ConfigManager.get_default_config_dir())
for t in cm.get_theme_list():
    if t['id'] == 'dark' or t['name'] == '深色':
        cm.set_current_theme(t['id'])
        print('切到主题:', t['name'], t['id'], flush=True)

pm = PluginManager()
win = MainWindow(pm, cm)
win.resize(1320, 840)
win.show()
app.processEvents()


def settle(sec=0.35):
    app.processEvents()
    time.sleep(sec)
    app.processEvents()


def shoot(name):
    pix = win.grab()
    path = os.path.join(outdir, name)
    pix.save(path)
    print('saved:', path, flush=True)


def capture():
    # 终端页（深色）
    for i in range(win.plugin_tabs.count()):
        if win.plugin_tabs.tabText(i) == '终端':
            win.plugin_tabs.setCurrentIndex(i)
            settle()
            shoot('MyDesk_终端_深色.png')
    # 计算工具页（深色 + 程序员模式示例）
    for i in range(win.plugin_tabs.count()):
        if win.plugin_tabs.tabText(i) == '计算工具':
            win.plugin_tabs.setCurrentIndex(i)
            app.processEvents()
            w = win.plugin_tabs.widget(i)
            try:
                w.calc_mode_combo.setCurrentIndex(1)
                w.prog_width_combo.setCurrentIndex(0)
                w.prog_sign_combo.setCurrentIndex(1)
                for ch in '255':
                    w._on_calc_input(ch)
            except Exception as e:
                print('calc err:', e)
            settle()
            shoot('MyDesk_计算工具_深色.png')
    app.quit()


QTimer.singleShot(500, capture)
app.exec()
