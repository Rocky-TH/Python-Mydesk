# -*- coding: utf-8 -*-
"""终端 Tabby 风格视觉预览：会话标签 + 控件形状 + ANSI 颜色渲染
用法: python tests/visual_tab_preview.py <output.png>
"""
import sys
import os

sys.path.insert(0, '.')
os.environ.pop('QT_QPA_PLATFORM', None)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

import plugins.terminal.terminal_widget as tw

# ANSI 样例：模拟服务器返回的彩色信息（ls 彩色输出、状态、提示等）
ANSI = '\x1b'
SAMPLE = (
    f"{ANSI}[32mdemo@test{ANSI}[0m:{ANSI}[34m~{ANSI}[0m$ ls --color=auto\n"
    f"{ANSI}[0;34mdocs{ANSI}[0m  {ANSI}[1;32mbuild.sh{ANSI}[0m  "
    f"{ANSI}[0;33mnotes.txt{ANSI}[0m  {ANSI}[0;35massets{ANSI}[0m\n"
    f"{ANSI}[31m[ERROR]{ANSI}[0m connect timeout after 30s\n"
    f"{ANSI}[32m[ OK ]{ANSI}[0m service started (pid 1024)\n"
    f"{ANSI}[33m[WARN]{ANSI}[0m config deprecated: use yaml\n"
    f"{ANSI}[36minfo:{ANSI}[0m 3 files changed, "
    f"{ANSI}[32m2 insertions(+){ANSI}[0m, {ANSI}[31m1 deletion(-){ANSI}[0m\n"
    f"{ANSI}[90mdim/path/info{ANSI}[0m  {ANSI}[97mbright white{ANSI}[0m  "
    f"{ANSI}[95mmagenta bg:{ANSI}[0m {ANSI}[45m 42% {ANSI}[0m done\n"
)

app = QApplication(sys.argv)
plugin = tw.TerminalPlugin({'name': 'Terminal', 'display_name': '终端'})
w = plugin.get_widget()
w.resize(900, 480)

# 两个模拟会话（unknown 类型不会发起网络连接）
w.create_session({'name': 'demo@test', 'type': 'unknown-type', 'config': {}})
w.create_session({'name': 'build-server', 'type': 'unknown-type', 'config': {}})
w.show()


def shot():
    # 向当前会话注入彩色样例（在渲染截图前）
    cur = w.get_current_session()
    if cur is not None:
        cur.write_output(SAMPLE)
    QTimer.singleShot(300, _grab)


def _grab():
    pix = w.grab()
    pix.save(sys.argv[1])
    print('saved:', sys.argv[1])
    app.quit()


QTimer.singleShot(900, shot)
app.exec()
