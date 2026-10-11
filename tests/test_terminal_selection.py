# -*- coding: utf-8 -*-
"""终端鼠标选中保护功能测试

场景：终端内容很多且有持续输出时，
- 拖选/双击选中的内容不被输出渲染打断（选区保持准确）
- 光标不再跳转到最新内容处
- 按键或纯点击后恢复正常渲染与光标跟踪
"""
import sys
import os

sys.path.insert(0, '.')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

results = []

def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QKeyEvent, QTextCursor
from PyQt6.QtCore import Qt, QEvent

import plugins.terminal.terminal_widget as tw

app = QApplication.instance() or QApplication(sys.argv)

plugin = tw.TerminalPlugin({'name': 'Terminal', 'display_name': '终端'})
w = plugin.get_widget()
conn = {'name': 't1', 'type': 'unknown-type', 'config': {}}
tab = w.create_session(conn)
td = tab.terminal_display
td.setPlainText('line1\nline2\nline3\nprompt$ ')

# ===== 1. 选中状态下新输出不破坏选区 =====
cur = td.textCursor()
cur.setPosition(6)
cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)  # 选中 line2
td.setTextCursor(cur)

pos_before = td.textCursor().position()
tab.write_output('server echo data xxx\r\n')

check('1.1 选中状态下输出到达后选区保留', td.textCursor().hasSelection())
check('1.2 选区内容不变（line2）',
      td.textCursor().selectedText() == 'line2')
check('1.3 显示光标未被移动（不跳到最新内容处）',
      td.textCursor().position() == pos_before)
check('1.4 新输出已追加到文档', 'server echo data' in td.toPlainText())

# ===== 2. 拖选进行中（鼠标按下）渲染不触碰光标 =====
td.setTextCursor(td.textCursor())  # 清除选区：光标位置不变
cur = td.textCursor()
cur.setPosition(6)
cur.setPosition(11, QTextCursor.MoveMode.KeepAnchor)
td.setTextCursor(cur)
td._mouse_down = True
pos_down = td.textCursor().position()
tab.write_output('more output while dragging\r\n')
check('2.1 拖选进行中光标位置不受输出影响',
      td.textCursor().position() == pos_down)
check('2.2 拖选进行中选区保留', td.textCursor().selectedText() == 'line2')
td._mouse_down = False

# ===== 3. 按键清除选区并恢复渲染 =====
key_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                   Qt.KeyboardModifier.NoModifier, 'a')
td.keyPressEvent(key_ev)
check('3.1 按键后选区被清除（终端标准行为）',
      not td.textCursor().hasSelection())

pos_after_key = td.textCursor().position()
tab.write_output('normal rendering resumed\r\n')
check('3.2 选区清除后恢复正常渲染（光标跟随输出）',
      'normal rendering resumed' in td.toPlainText()
      and td.textCursor().position() != pos_after_key
      and td.textCursor().block() == td.document().lastBlock())

# ===== 4. 无选区正常路径不受影响（光标续写语义） =====
td.clear()
td.setPlainText('demo@test:~$ ')
cur = td.textCursor()
cur.movePosition(QTextCursor.MoveOperation.End)
td.setTextCursor(cur)
tab.write_output('ls -al\r\n')
check('4.1 正常路径：输出后光标位于文档末尾',
      td.textCursor().atEnd())

# ===== 5. 选中状态下系统提示文本（color 分支）也不破坏选区 =====
cur = td.textCursor()
cur.setPosition(0)
cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
td.setTextCursor(cur)
tab.write_output('⚠ 系统提示消息\n', 'text-warning')
check('5.1 color 分支输出后选区保留',
      td.textCursor().hasSelection()
      and td.textCursor().selectedText() == 'demo@')
check('5.2 系统提示已追加', '系统提示消息' in td.toPlainText())

w.deleteLater()

print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
