# -*- coding: utf-8 -*-
"""计算器程序员模式视觉预览：位宽/符号设置 + 结果区
用法: python tests/visual_calc_preview.py <output.png>
"""
import sys
import os

sys.path.insert(0, '.')
os.environ.pop('QT_QPA_PLATFORM', None)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from plugins.calc_tool.calc_tool_widget import CalcToolWidget

app = QApplication(sys.argv)
w = CalcToolWidget({'name': 'calc'})
w.resize(900, 640)
w.show()
w.calc_mode_combo.setCurrentIndex(1)  # 程序员模式
# 字节 + 有符号，输入 255 → 十进制 -1，二进制 11111111
w.prog_width_combo.setCurrentIndex(0)
w.prog_sign_combo.setCurrentIndex(1)
for ch in '255':
    w._on_calc_input(ch)


def shot():
    pix = w.grab()
    pix.save(sys.argv[1])
    print('saved:', sys.argv[1])
    app.quit()


QTimer.singleShot(700, shot)
app.exec()
