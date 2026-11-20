# -*- coding: utf-8 -*-
"""终端大量输出性能回归测试

性能瓶颈实测（4.3MB / 5 万行、120x30 窗口）：耗时集中在逐行插入与
逐字符宽度换算。修复后「可打印字符 + 换行」按整块批量插入，ASCII
宽度走 C 实现快速路径，非 ASCII 字符宽度按字符缓存。

本套件不依赖机器绝对速度，只校验与性能直接相关的结构性质：
- 一次 write_output 的大量文本只触发极少量 QTextDocument 变更
  （contentsChange 次数与行数/字符数解耦）；
- 批量写入不改变终端语义：硬换行、中文宽字符、ANSI 颜色、
  清屏预置空白行消耗、备用屏幕行列、选区与滚动位置保持。
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
from PyQt6.QtGui import QTextCursor

import plugins.terminal.terminal_widget as tw
from utils.config_manager import ConfigManager

app = QApplication.instance() or QApplication(sys.argv)
_config_manager = ConfigManager()


def new_tab(tag, cols=40, rows=24, width=620, height=520):
    tab = tw.SessionTab(session_id=tag, session_name=tag,
                        config_manager=_config_manager)
    tab.resize(width, height)
    tab.terminal_display.resize(width - 20, height - 60)
    tab.show()
    app.processEvents()
    tab._last_pty_size = (cols, rows)
    tab.terminal_display.clear()
    tab._output_history.clear()
    app.processEvents()
    return tab


def close_tab(tab):
    tab.deleteLater()
    app.processEvents()


def count_changes(tab, action):
    """执行 action 并统计 QTextDocument 内容变更次数（机器无关）"""
    counter = [0]
    doc = tab.terminal_display.document()
    doc.contentsChange.connect(lambda *args: counter.__setitem__(0, counter[0] + 1))
    action()
    app.processEvents()
    return counter[0]


# ===== 1. 宽度换算快速路径与缓存 =====
print('\n========== 1. 字符宽度换算 ==========')
tab = new_tab('width')
try:
    check('1.1 ASCII 文本宽度等于字符数',
          tab._text_width('hello world') == 11)
    check('1.2 中文按 2 单元格计宽',
          tab._text_width('中文') == 4)
    check('1.3 ASCII 与中文混排按单元格累加',
          tab._text_width('a中b文c') == 7)
    check('1.4 组合符占 0 格',
          tab._text_width('e\u0301') == 1)
    # 缓存命中前后结果一致（同一字符多次换算）
    first = [tab._text_width('中A文') for _ in range(5)]
    check('1.5 宽度缓存命中后结果一致', len(set(first)) == 1, repr(set(first)))
finally:
    close_tab(tab)


# ===== 2. 大量文本整块插入（核心性能性质） =====
print('\n========== 2. 批量插入 ==========')
tab = new_tab('batch')
try:
    lines = 500
    src = ''.join(f'line {i:04d} ' + 'x' * 20 + '\r\n' for i in range(lines))
    changes = count_changes(tab, lambda: tab.write_output(src))
    doc = tab.terminal_display.document()
    check('2.1 500 行文本插入次数与行数解耦（≤ 3 次文档变更）',
          changes <= 3, f'changes={changes}')
    check('2.2 文本块数量正确（500 行 + 末尾空行）',
          doc.blockCount() == lines + 1, f'blocks={doc.blockCount()}')
    plain = tab.terminal_display.toPlainText()
    check('2.3 行内容完整无丢失',
          plain.startswith('line 0000') and 'line 0499' in plain
          and plain.count('\n') == lines)

    # 分块写入（模拟 PTY 4KB 读取）时，插入次数仍应远小于行数
    tab.terminal_display.clear()
    tab._output_history.clear()
    app.processEvents()
    payload = ''.join(f'chunk {i:04d} ' + 'y' * 20 + '\r\n' for i in range(500))
    chunks = [payload[i:i + 4096] for i in range(0, len(payload), 4096)]
    changes = count_changes(tab, lambda: [tab.write_output(c) for c in chunks])
    check('2.4 4KB 分块写入时插入次数 ≈ 分块数（每块 1 次）',
          changes <= len(chunks) + 2,
          f'changes={changes} chunks={len(chunks)}')
finally:
    close_tab(tab)


# ===== 3. 长行硬换行仍按列宽切分 =====
print('\n========== 3. 长行硬换行 ==========')
tab = new_tab('wrap', cols=40)
try:
    chars = 4000
    changes = count_changes(tab, lambda: tab.write_output('a' * chars + '\r\n'))
    doc = tab.terminal_display.document()
    expected_lines = chars // 40
    widths = [tab._text_width(doc.findBlockByNumber(i).text())
              for i in range(expected_lines)]
    check('3.1 每行宽度等于列宽（硬换行正确）',
          set(widths) == {40}, f'widths={set(widths)}')
    check('3.2 行数 = 字符数 / 列宽',
          doc.blockCount() == expected_lines + 1,
          f'blocks={doc.blockCount()} expected={expected_lines + 1}')
    # 插入次数随换行行数增长，而不是随字符数增长
    check('3.3 插入次数随行数而非字符数增长',
          changes <= expected_lines * 2 + 4,
          f'changes={changes} lines={expected_lines}')
finally:
    close_tab(tab)


# ===== 4. 清屏后的预置空白行仍被批量写入消耗 =====
print('\n========== 4. 清屏空白行消耗 ==========')
tab = new_tab('clear', cols=40, rows=10)
try:
    tab.write_output('\x1b[2J')
    app.processEvents()
    before = tab.terminal_display.document().blockCount()
    tab.write_output('aaa\r\nbbb\r\nccc\r\n')
    app.processEvents()
    after = tab.terminal_display.document().blockCount()
    check('4.1 清屏后写入多行不新增文本块',
          after == before, f'before={before} after={after}')
    doc = tab.terminal_display.document()
    texts = [doc.findBlockByNumber(i).text() for i in range(4)]
    check('4.2 清屏后内容从新屏幕首行开始逐行写下',
          texts == ['', 'aaa', 'bbb', 'ccc'], repr(texts))
finally:
    close_tab(tab)


# ===== 5. 中文宽字符批量写入 =====
print('\n========== 5. 中文宽字符 ==========')
tab = new_tab('cjk', cols=20)
try:
    changes = count_changes(tab, lambda: tab.write_output('中文abc\r\n' * 30))
    doc = tab.terminal_display.document()
    widths = {tab._text_width(doc.findBlockByNumber(i).text()) for i in range(30)}
    check('5.1 中文行宽度按单元格计（中文abc = 7 格）',
          widths == {7}, f'widths={widths}')
    check('5.2 30 行中文整块写入块数正确',
          doc.blockCount() == 31, f'blocks={doc.blockCount()}')
    check('5.3 中文内容未被拆散',
          doc.firstBlock().text() == '中文abc', repr(doc.firstBlock().text()))
    check('5.4 中文行批量插入次数与行数解耦', changes <= 3, f'changes={changes}')
finally:
    close_tab(tab)


# ===== 6. ANSI 颜色在批量插入中保持 =====
print('\n========== 6. ANSI 颜色 ==========')
tab = new_tab('ansi')
try:
    tab.ansi_parser.enable_color = True
    tab.write_output('\x1b[31m' + 'red line\r\n' * 10 + '\x1b[32mgreen\r\n\x1b[0m')
    app.processEvents()
    doc = tab.terminal_display.document()
    red = doc.findBlockByNumber(0).begin().fragment().charFormat().foreground().color()
    red5 = doc.findBlockByNumber(5).begin().fragment().charFormat().foreground().color()
    green = doc.findBlockByNumber(10).begin().fragment().charFormat().foreground().color()
    check('6.1 批量写入的每一行都保留红色', red == red5 and red.name() == '#ff5370',
          f'{red.name()} / {red5.name()}')
    check('6.2 后续绿色片段独立生效', green.name() == '#c3e88d', green.name())
finally:
    close_tab(tab)


# ===== 7. 备用屏幕定位与中文 =====
print('\n========== 7. 备用屏幕 ==========')
tab = new_tab('alt', cols=40, rows=12)
try:
    tab.write_output('\x1b[?1049h')
    app.processEvents()
    changes = count_changes(tab, lambda: tab.write_output('\x1b[3;5H中文测试'))
    doc = tab.terminal_display.document()
    cur = tab.terminal_display.textCursor()
    check('7.1 备用屏幕保持固定行数（批量路径不撑破屏幕）',
          doc.blockCount() == 12, f'blocks={doc.blockCount()}')
    check('7.2 CUP 定位到第 3 行第 5 列（中文按字符定位）',
          cur.block().blockNumber() == 2
          and doc.findBlockByNumber(2).text() == '    中文测试',
          repr(doc.findBlockByNumber(2).text()))
    check('7.3 定位写入的文档变更次数很少', changes <= 2, f'changes={changes}')
finally:
    close_tab(tab)


# ===== 8. 行中覆盖语义不受批量路径影响 =====
print('\n========== 8. 行中覆盖 ==========')
tab = new_tab('overwrite', cols=40, rows=12)
try:
    tab.write_output('\x1b[?1049h\x1b[3;1Habcdef')
    app.processEvents()
    tab.write_output('\x1b[3;3HXY')
    app.processEvents()
    row3 = tab.terminal_display.document().findBlockByNumber(2).text()
    check('8.1 行中写入按终端单元格覆盖（不后移旧字符）',
          row3 == 'abXYef', repr(row3))

    tab.write_output('\x1b[4;1Habc')
    tab.write_output('\x1b[4;2HXY\n')
    app.processEvents()
    doc = tab.terminal_display.document()
    row4 = doc.findBlockByNumber(3).text()
    row5 = doc.findBlockByNumber(4).text()
    check('8.2 行中覆盖后换行落到下一行行首',
          row4 == 'aXY' and row5 == '', f'row4={row4!r} row5={row5!r}')
finally:
    close_tab(tab)


# ===== 9. 大量输出时选区与滚动位置保持 =====
print('\n========== 9. 选区与滚动保持 ==========')
tab = new_tab('keep', cols=40, rows=6)
try:
    for i in range(120):
        tab.write_output(f'line {i:03d}\r\n')
    app.processEvents()
    bar = tab.terminal_display.verticalScrollBar()
    check('9.1 测试数据足以产生滚动条', bar.maximum() > 0, f'max={bar.maximum()}')
    bar.setValue(0)
    cur = tab.terminal_display.textCursor()
    cur.setPosition(0)
    cur.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
    tab.terminal_display.setTextCursor(cur)
    app.processEvents()

    # 一次写入约 16KB（200 行），走批量路径
    big = ''.join('payload ' + 'z' * 30 + '\r\n' for _ in range(200))
    changes = count_changes(tab, lambda: tab.write_output(big))
    check('9.2 大量输出后选区保持',
          tab.terminal_display.textCursor().hasSelection()
          and tab.terminal_display.textCursor().selectedText() == 'line')
    check('9.3 大量输出后滚动位置保持', bar.value() == 0, f'value={bar.value()}')
    check('9.4 追加内容完整', 'payload' in tab.terminal_display.toPlainText())
    check('9.5 大批量输出插入次数很少', changes <= 3, f'changes={changes}')
finally:
    close_tab(tab)


# ===== 10. 大规模输出（结构断言，不测绝对耗时） =====
print('\n========== 10. 大规模输出 ==========')
tab = new_tab('large', cols=120, rows=30, width=1100, height=700)
try:
    lines = 20000
    src = ''.join(f'{i:06d} the quick brown fox jumps over the lazy dog\r\n'
                  for i in range(lines))
    changes = count_changes(tab, lambda: tab.write_output(src))
    doc = tab.terminal_display.document()
    check('10.1 2 万行一次写入块数正确',
          doc.blockCount() == lines + 1, f'blocks={doc.blockCount()}')
    check('10.2 2 万行只触发 1 次文档变更（远小于行数 20000）',
          changes == 1, f'changes={changes}')
    check('10.3 首尾内容完整',
          doc.findBlockByNumber(0).text().startswith('000000')
          and doc.findBlockByNumber(lines - 1).text().startswith('019999'))
finally:
    close_tab(tab)


print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
