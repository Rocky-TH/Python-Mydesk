# -*- coding: utf-8 -*-
"""终端功能键序列测试

验证：Home/End/Insert/Ctrl+方向键发送正确的键序；
DECCKM 应用光标模式（\\x1b[?1h）下 Home/End 自动切换为 SS3 形式；
SSH PTY 终端类型声明为 xterm-256color（Ubuntu 兼容性根因修复）。
"""
import sys
import os
import inspect

sys.path.insert(0, '.')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

results = []

def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import Qt, QEvent

import plugins.terminal.terminal_widget as tw
from plugins.terminal import ssh_connection

app = QApplication.instance() or QApplication(sys.argv)

# ===== 1. SSH PTY 终端类型（Ubuntu 兼容性根因） =====
src_connect = inspect.getsource(ssh_connection.SSHConnection.connect)
check('1.1 get_pty 显式声明 term=xterm-256color（修复 paramiko 默认 vt100）',
      "term='xterm-256color'" in src_connect)

# ===== 2. 功能键序列（普通模式） =====
plugin = tw.TerminalPlugin({'name': 'Terminal', 'display_name': '终端'})
w = plugin.get_widget()
conn = {'name': 't1', 'type': 'ssh', 'config': {'host': 'x', 'port': 22}}
tab = w.create_session(conn)

sent = []

class FakeStrategy:
    def send_raw(self, data):
        sent.append(data)
    def read_output(self, timeout=0.05):
        return ''
    def is_connected(self):
        return True
    def get_name(self):
        return 'ssh'
    def connected(self):
        return True
    def disconnect(self):
        pass

fake = FakeStrategy()
tab.connection_context.set_strategy(fake)
tab.interactive_mode = True


def press(key, modifiers=Qt.KeyboardModifier.NoModifier, text=''):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)
    tab.handle_key_press(ev)


sent.clear()
press(Qt.Key.Key_Home)
check('2.1 Home 发送 \\x1b[1~（普通模式）', sent == ["\x1b[1~"], repr(sent))

sent.clear()
press(Qt.Key.Key_End)
check('2.2 End 发送 \\x1b[4~（普通模式）', sent == ["\x1b[4~"], repr(sent))

sent.clear()
press(Qt.Key.Key_Insert)
check('2.3 Insert 发送 \\x1b[2~', sent == ["\x1b[2~"], repr(sent))

sent.clear()
press(Qt.Key.Key_Left)
press(Qt.Key.Key_Right)
check('2.4 普通方向键发送 \\x1b[D / \\x1b[C',
      sent == ["\x1b[D", "\x1b[C"], repr(sent))

sent.clear()
press(Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
press(Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
check('2.5 Ctrl+方向键发送按词跳转序列 \\x1b[1;5D / \\x1b[1;5C',
      sent == ["\x1b[1;5D", "\x1b[1;5C"], repr(sent))

sent.clear()
press(Qt.Key.Key_Return)
check('2.6 回车键发送 \\r（PTY 标准）', sent == ["\r"], repr(sent))

# ===== 3. DECCKM 应用光标模式切换 =====
sent.clear()
tab.write_output('\x1b[?1h\x1b[?2004h')  # vim/less/bash 等开启应用光标模式
check('3.1 收到 \\x1b[?1h 后应用光标模式置位', tab._application_cursor_mode is True)

press(Qt.Key.Key_Home)
press(Qt.Key.Key_End)
check('3.2 应用模式下 Home/End 发送 SS3 形式',
      sent == ["\x1bOH", "\x1bOF"], repr(sent))

sent.clear()
tab.write_output('\x1b[?1l')  # 关闭应用光标模式
check('3.3 收到 \\x1b[?1l 后应用光标模式复位', tab._application_cursor_mode is False)

press(Qt.Key.Key_Home)
check('3.4 复位后 Home 恢复 \\x1b[1~', sent == ["\x1b[1~"], repr(sent))

# ===== 4. Shift+Insert 仍为粘贴（不被 Ins 键序覆盖） =====
from PyQt6.QtWidgets import QApplication as QApp
QApp.clipboard().setText('pasted')
sent.clear()
press(Qt.Key.Key_Insert, Qt.KeyboardModifier.ShiftModifier)
check('4.1 Shift+Insert 走粘贴路径（不发送 Ins 键序）',
      len(sent) == 1 and 'pasted' in sent[0]
      and sent[0] not in ("\x1b[2~",), repr(sent))

# ===== 5. 重连后模式标志复位 =====
tab._application_cursor_mode = True
tab.connect_with_config({'name': 't2', 'type': 'unknown-type', 'config': {}})
check('5.1 重新连接后应用光标模式标志复位', tab._application_cursor_mode is False)

w.deleteLater()

print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
