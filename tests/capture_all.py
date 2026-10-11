# -*- coding: utf-8 -*-
"""MyDesk 各功能页整窗截图脚本（同步版）
用法: python tests/capture_all.py <输出目录>
逐页同步切换到每个插件页签并整窗截图（含菜单栏/工具栏/状态栏）。
对计算工具自动切到程序员模式并输入示例。
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

outdir = sys.argv[1] if len(sys.argv) > 1 else '.'
os.makedirs(outdir, exist_ok=True)

app = QApplication(sys.argv)
pm = PluginManager()
win = MainWindow(pm)
win.resize(1320, 840)
win.show()
app.processEvents()


def settle(sec=0.35):
    app.processEvents()
    time.sleep(sec)
    app.processEvents()


def capture():
    count = win.plugin_tabs.count()
    for i in range(count):
        w = win.plugin_tabs.widget(i)
        tab_name = win.plugin_tabs.tabText(i).replace('/', '_')
        win.plugin_tabs.setCurrentIndex(i)
        app.processEvents()
        # 计算工具：切到程序员模式，输入 255 演示
        if w.__class__.__name__ == 'CalcToolWidget':
            try:
                w.calc_mode_combo.setCurrentIndex(1)   # 程序员模式
                w.prog_width_combo.setCurrentIndex(0)  # 8 位
                w.prog_sign_combo.setCurrentIndex(1)   # 有符号
                for ch in '255':
                    w._on_calc_input(ch)
            except Exception as e:
                print('calc setup err:', e)
        settle()
        pix = win.grab()
        path = os.path.join(outdir, f'MyDesk_{tab_name}.png')
        pix.save(path)
        print('saved:', path, flush=True)

    # 调测工具默认不显示 tab，单独抓取
    debug_w = win.plugin_widgets.get('DebugTool')
    if debug_w is not None:
        settle()
        pix = debug_w.grab()
        path = os.path.join(outdir, 'MyDesk_DebugTool.png')
        pix.save(path)
        print('saved:', path, flush=True)
    app.quit()


QTimer.singleShot(500, capture)
app.exec()
