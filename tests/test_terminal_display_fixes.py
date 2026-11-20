# -*- coding: utf-8 -*-
"""终端显示/交互修复回归测试

覆盖四个用户反馈问题：
1. nano 等全屏程序显示与输入错乱 —— 终端已按列宽插入硬换行，QTextEdit 若再按
   像素宽度软换行，全屏程序按行号定位的 CUP 会与视觉行错位；
2. cat 长文本出现多余换行 —— 同一根因，一行被逻辑换行 + 软换行拆成两行；
3. 向上翻页后双击文本，视图跳回最底部 —— setTextCursor 会滚动到文档末尾光标；
4. 按钮栏右键菜单出现在左上角 —— 坐标系用了父控件坐标而非全局坐标。
"""
import sys
import os
import time

sys.path.insert(0, '.')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

results = []


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

import plugins.terminal.terminal_widget as tw
from utils.config_manager import ConfigManager

app = QApplication.instance() or QApplication(sys.argv)
_config_manager = ConfigManager()


def new_tab(tag, width=420, height=500):
    tab = tw.SessionTab(session_id=tag, session_name=tag, config_manager=_config_manager)
    tab.resize(width, height)
    tab.terminal_display.resize(width - 20, height - 120)
    tab.show()
    app.processEvents()
    return tab


def visual_line_count(display):
    """文档实际占据的视觉行数（含 QTextEdit 软换行产生的行）"""
    doc = display.document()
    total = 0
    for i in range(doc.blockCount()):
        block = doc.findBlockByNumber(i)
        layout = block.layout()
        total += layout.lineCount() if layout else 1
    return total


def close_tab(tab):
    tab.deleteLater()
    app.processEvents()


# ===== 1. cat 文本：一行就是一行，不因软换行拆成两行 =====
print('\n========== 1. cat 输出换行 ==========')
tab = new_tab('cat')
try:
    tab._last_pty_size = (100, 24)  # 列宽 100，但控件只有约 50 个字符宽
    check('1.1 终端关闭 QTextEdit 软换行',
          tab.terminal_display.lineWrapMode() == tw.QTextEdit.LineWrapMode.NoWrap)

    tab.write_output('a' * 60 + '\r\n')
    app.processEvents()
    first_block = tab.terminal_display.document().firstBlock()
    layout = first_block.layout()
    check('1.2 未达列宽的长行只占一个视觉行',
          (layout.lineCount() if layout else 1) == 1,
          f'lineCount={layout.lineCount() if layout else 1}')

    tab.terminal_display.clear()
    tab._output_history.clear()
    src_lines = 12
    src = ''.join(f'line {i:02d} ' + 'y' * 40 + '\r\n' for i in range(src_lines))
    tab.write_output(src)
    app.processEvents()
    doc = tab.terminal_display.document()
    plain = tab.terminal_display.toPlainText()
    check('1.3 cat 12 行 → 12 个内容行（不含多余空行）',
          doc.blockCount() == src_lines + 1 and plain.count('\n') == src_lines,
          f'blocks={doc.blockCount()} newlines={plain.count(chr(10))}')
    check('1.4 每行宽度未超过列宽时不会被拆成多行',
          visual_line_count(tab.terminal_display) == src_lines + 1,
          f'visual={visual_line_count(tab.terminal_display)}')
    check('1.5 行内容完整未丢失',
          all(f'line {i:02d} ' in plain for i in range(src_lines)))

    tab.terminal_display.clear()
    tab._output_history.clear()
    tab.write_output('z' * 250 + '\r\n')
    app.processEvents()
    check('1.6 250 列内容按 100 列折成 3 行（100/100/50）',
          visual_line_count(tab.terminal_display) == 4,  # 3 个内容行 + 末尾空行
          f'visual={visual_line_count(tab.terminal_display)}')

    # 没有 PTY 尺寸（串口/连接前）时按控件宽度估算，不能固定 80 列
    narrow = new_tab('narrow', width=420)
    wide = new_tab('wide', width=1400)
    narrow_cols = narrow._get_screen_cols()
    wide_cols = wide._get_screen_cols()
    check('1.7 无 PTY 尺寸时按控件宽度估算列数',
          wide_cols > narrow_cols >= 20, f'narrow={narrow_cols} wide={wide_cols}')
    close_tab(narrow)
    close_tab(wide)
finally:
    close_tab(tab)


# ===== 2. nano 全屏程序：行列定位与输入光标 =====
print('\n========== 2. nano 全屏程序 ==========')
tab = new_tab('nano')
try:
    tab._last_pty_size = (40, 24)
    # 进入备用屏幕并定位到第 2 行
    tab.write_output('\x1b[?1049h\x1b[2;1H')
    app.processEvents()
    check('2.1 已进入备用屏幕', tab._alt_screen_active is True)

    # nano 会整行重绘（写满列宽），软换行会让后续 CUP 行号整体下移
    tab.write_output('n' * 40)
    app.processEvents()
    block = tab.terminal_display.document().findBlockByNumber(1)
    layout = block.layout()
    check('2.2 写满列宽的行只占一个视觉行',
          (layout.lineCount() if layout else 1) == 1,
          f'lineCount={layout.lineCount() if layout else 1}')

    # 在第 4 行输入并触发自动折行：40 列后应换到下一行行首
    tab.write_output('\x1b[4;1H' + 'a' * 39 + 'bcd')
    app.processEvents()
    doc = tab.terminal_display.document()
    row4 = doc.findBlockByNumber(3).text()
    row5 = doc.findBlockByNumber(4).text()
    cur = tab.terminal_display.textCursor()
    check('2.3 折行后第 4 行保留前 40 个字符', row4 == 'a' * 39 + 'b', repr(row4))
    check('2.4 折行后余下字符落在下一行行首', row5.startswith('cd'), repr(row5))
    check('2.5 输入光标位于折行后的正确位置',
          cur.block().blockNumber() == 4 and tab._cursor_display_col(cur) == 3,
          f'block={cur.block().blockNumber()} col={tab._cursor_display_col(cur)}')

    # 宽字符（中文）输入后的光标列按单元格计
    tab.write_output('\x1b[6;1H' + '中文')
    app.processEvents()
    cur = tab.terminal_display.textCursor()
    check('2.6 中文输入后光标列按单元格计算',
          cur.block().blockNumber() == 5 and tab._cursor_display_col(cur) == 5,
          f'block={cur.block().blockNumber()} col={tab._cursor_display_col(cur)}')
finally:
    close_tab(tab)


# ===== 3. 向上翻页后点击/双击不跳到底部 =====
print('\n========== 3. 滚动后点击/双击 ==========')
tab = new_tab('scroll')
try:
    tab._last_pty_size = (80, 24)
    for i in range(200):
        tab.write_output(f'line {i:03d} ' + 'z' * 20 + '\r\n')
    app.processEvents()
    scrollbar = tab.terminal_display.verticalScrollBar()
    check('3.1 测试数据足以产生滚动条', scrollbar.maximum() > 0,
          f'max={scrollbar.maximum()}')
    scrollbar.setValue(0)
    app.processEvents()

    viewport = tab.terminal_display.viewport()
    point = QPoint(60, 40)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    app.processEvents()
    check('3.2 向上翻页后单击不会跳回底部', scrollbar.value() == 0,
          f'value={scrollbar.value()}')
    check('3.3 单击不产生选区', not tab.terminal_display.textCursor().hasSelection())

    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    app.processEvents()
    selected = tab.terminal_display.textCursor().selectedText()
    check('3.4 双击后视图仍停在原位置', scrollbar.value() == 0,
          f'value={scrollbar.value()}')
    check('3.5 双击选中了鼠标下的词', bool(selected) and set(selected) == {'z'},
          repr(selected[:30]))

    # 有选区时新输出到达：选区与滚动位置都不能被重置
    tab.write_output('new output arrives\r\n')
    app.processEvents()
    check('3.6 新输出到达后选区保持', tab.terminal_display.textCursor().hasSelection())
    check('3.7 新输出到达后滚动位置保持', scrollbar.value() == 0,
          f'value={scrollbar.value()}')
finally:
    close_tab(tab)


# ===== 4. 按钮栏右键菜单在鼠标位置弹出 =====
print('\n========== 4. 按钮栏右键菜单 ==========')
from unittest import mock

bar = tw.TerminalButtonToolbar(config_manager=_config_manager)
bar.resize(400, 30)
bar.show()
app.processEvents()
bar.add_button({'id': 'btn-test', 'name': '测试', 'type': 'command', 'command': 'ls'})
app.processEvents()
try:
    button = bar._button_widgets['btn-test']
    captured = []

    def fake_exec(menu_self, pos=None, *args, **kwargs):
        captured.append(pos)
        return None

    local_pos = QPoint(5, 5)
    with mock.patch.object(tw.QMenu, 'exec', fake_exec):
        button.customContextMenuRequested.emit(local_pos)
    expected = button.mapToGlobal(local_pos)
    check('4.1 右键菜单坐标使用全局坐标',
          captured and captured[-1] == expected,
          f'got={captured[-1] if captured else None} expected={expected}')

    # 右键按钮工具栏空白处仍应能弹出“添加按钮”菜单
    captured.clear()
    with mock.patch.object(tw.QMenu, 'exec', fake_exec):
        bar._show_toolbar_context_menu(QPoint(10, 10))
    check('4.3 工具栏空白处右键使用工具栏坐标系',
          captured and captured[-1] == bar.mapToGlobal(QPoint(10, 10)),
          f'got={captured[-1] if captured else None}')
finally:
    bar.deleteLater()
    app.processEvents()


print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
