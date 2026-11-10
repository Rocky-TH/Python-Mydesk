# -*- coding: utf-8 -*-
"""全屏程序（vi / nano）渲染回归测试

数据来源：用 ConPTY 录制 Git for Windows 自带 vim / nano 的真实输出字节流
（含 CSI 光标定位、擦行、备用屏切换、UTF-8 中文），保存在
tests/fixtures/terminal_fullscreen/*.json，按
SessionTab.write_output -> ANSIParser.parse -> _insert_text_with_cr
与真实会话完全相同的路径回放。

覆盖点：
1. vi 底部命令行：:w / :q(E37) / :wq / :q!，/搜索 + n 跳转，gg/G，dd/o，
   反复 13 次进出命令行模式不残留、不堆积
2. nano 顶部标题栏、底部双行快捷键栏、^O 保存、^X 退出提示
3. 中文（双宽字符）输入后的光标定位与行内覆盖
4. 窄终端（40 / 30 列）下快捷键栏折行与中文长行换行
"""
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, '.')

results = []


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
from plugins.terminal.terminal_widget import SessionTab  # noqa: E402
from utils.config_manager import ConfigManager  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'fixtures', 'terminal_fullscreen')
_cm = ConfigManager()


def replay(name, rows, cols):
    """回放录制文件，返回 (tab, 每一步的快照)"""
    tab = SessionTab(session_id='rec', session_name='rec', config_manager=_cm)
    tab._last_pty_size = (cols, rows)
    with open(os.path.join(FIXTURE_DIR, f'rec_{name}.json'), encoding='utf-8') as f:
        rec = json.load(f)
    snapshots = {}
    for step in rec['steps']:
        tab.write_output(step['data'])
        cur = tab.terminal_display.textCursor()
        snapshots[step['label']] = {
            'lines': tab.terminal_display.toPlainText().split('\n'),
            'alt': tab._alt_screen_active,
            'cursor': (cur.block().blockNumber() + 1, tab._cursor_display_col(cur)),
        }
    return tab, snapshots


# ===== 1. vi：底部命令行与编辑动作 =====
print('\n========== 1. vi 全屏输出回放 ==========')
vim_tab, vim_snap = replay('vim', 24, 80)
vim_lines = {k: v['lines'] for k, v in vim_snap.items()}

check('1.1 全屏期间屏幕始终 24 行（未撑破/未堆积）',
      all(len(v['lines']) == 24 for k, v in vim_snap.items() if k != ':wq 保存退出'))
check('1.2 :w 后底行显示写入结果',
      'written' in vim_lines[':w 保存'][23], vim_lines[':w 保存'][23].strip())
check('1.3 :q 未保存提示 E37',
      'No write since last change' in vim_lines[':q 未保存提示(E37)'][23],
      vim_lines[':q 未保存提示(E37)'][23].strip())
check('1.4 /line 搜索回车后光标落在匹配行',
      'line' in vim_lines['/line 搜索回车'][2],
      str(vim_snap['/line 搜索回车']['cursor']))
check('1.5 n 跳到下一个匹配',
      vim_snap['n 下一个匹配']['cursor'][0] == 4,
      str(vim_snap['n 下一个匹配']['cursor']))
check('1.6 Esc 退出搜索后光标不动',
      vim_snap['Esc 退出搜索']['cursor'] == vim_snap['n 下一个匹配']['cursor'],
      str(vim_snap['Esc 退出搜索']['cursor']))
check('1.7 gg 回到首行', vim_snap['gg 回到首行']['cursor'][0] == 1,
      str(vim_snap['gg 回到首行']['cursor']))
check('1.8 G 跳到末行', vim_snap['G 跳到末行']['cursor'][0] == 5,
      str(vim_snap['G 跳到末行']['cursor']))
check('1.9 dd 删除末行后屏幕仍为 24 行',
      'delta line four' not in '\n'.join(vim_lines['dd 删除当前行'])
      and len(vim_lines['dd 删除当前行']) == 24)
check('1.10 o 插入新行',
      any('inserted by o' in ln for ln in vim_lines['o 插入新行']))

rep = vim_lines['多次进出命令行模式']
check('1.11 反复 13 次进入/退出命令行模式后仍为 24 行', len(rep) == 24, f'{len(rep)} 行')
check('1.12 反复进出后底行只有单个冒号（无残留/堆积）',
      rep[23].strip() == ':', repr(rep[23]))
check('1.13 反复进出后正文区无命令行残留',
      not any(ln.strip().startswith(':') for ln in rep[:23]))

check('1.14 :wq 后退出备用屏', not vim_snap[':wq 保存退出']['alt'])
check('1.15 :wq 后主屏无 vi 残影',
      '\n'.join(vim_lines[':wq 保存退出']).strip() == '')

qbang_tab, qbang_snap = replay('vim_qbang', 24, 80)
check('1.16 :q! 放弃修改后退出备用屏',
      not qbang_snap[':q! 放弃退出']['alt'])

# 退出全屏后，进入前的主屏内容必须原样还原
restore_tab = SessionTab(session_id='rs', session_name='rs', config_manager=_cm)
restore_tab._last_pty_size = (80, 24)
shell_echo = 'user@host:~$ ls\r\nfile1  file2\r\nuser@host:~$ vim demo.txt\r\n'
restore_tab.write_output(shell_echo)
before = restore_tab.terminal_display.toPlainText()
restore_tab.write_output('\x1b[?1049h\x1b[2J\x1b[H\x1b[1;1Hhello vi\x1b[24;1H:q\r\n')
restore_tab.write_output('\x1b[?1049l')
check('1.17 退出全屏后主屏内容还原', restore_tab.terminal_display.toPlainText() == before)

# ===== 2. nano：标题栏、快捷键栏、^O / ^X =====
print('\n========== 2. nano 全屏输出回放 ==========')
nano_tab, nano_snap = replay('nano', 24, 80)
nano_start = nano_snap['启动']['lines']

check('2.1 顶部标题栏含文件名', 'nano_demo.txt' in nano_start[0],
      nano_start[0].strip()[-32:])
check('2.2 底部快捷键栏第 1 行完整显示',
      '^G Help' in nano_start[22] and '^O Write Out' in nano_start[22],
      nano_start[22][:56])
check('2.3 底部快捷键栏第 2 行完整显示',
      '^X Exit' in nano_start[23] and '^R Read File' in nano_start[23],
      nano_start[23][:56])
check('2.4 ^O 弹出文件名确认行',
      any('File Name to Write' in ln or 'Write to File' in ln
          for ln in nano_snap['^O 保存']['lines']))
check('2.5 确认保存后提示 Wrote',
      'Wrote' in '\n'.join(nano_snap['确认文件名回车']['lines']))
check('2.6 中文输入后继续输入 xyz 光标位置正确',
      nano_snap['再输入字母']['lines'][1] == '中文测试abcxyznano first line',
      repr(nano_snap['再输入字母']['lines'][1]))
quit_prompt = nano_snap['^X 退出(有修改提示)']
check('2.7 ^X 弹出保存修改提示',
      any('Save modified buffer' in ln for ln in quit_prompt['lines']))
check('2.8 提示含 Y Yes / N No 选项',
      any('Yes' in ln for ln in quit_prompt['lines'])
      and any('No' in ln for ln in quit_prompt['lines']))
check('2.9 提示期间仍在备用屏（未提前退出）', quit_prompt['alt'])
check('2.10 选择 N 不保存后退出备用屏', not nano_snap['不保存 N']['alt'])

# ===== 3. nano：窄窗口 =====
print('\n========== 3. nano 窄窗口 ==========')
for idx, (name, rows, cols, tag) in enumerate([('nano_narrow', 12, 40, '40 列'),
                                               ('nano_tiny', 10, 30, '30 列')]):
    tab, snap = replay(name, rows, cols)
    lines = snap['启动']['lines']
    n = idx * 4 + 1
    check(f'3.{n} {tag} 行数严格为 {rows}', len(lines) == rows, f'{len(lines)}')
    check(f'3.{n + 1} {tag} 标题栏完整', 'nano_demo.txt' in lines[0], lines[0].strip()[-30:])
    check(f'3.{n + 2} {tag} 快捷键栏折行后仍完整位于底部两行',
          any('^G Help' in r for r in lines[rows - 2:])
          and any('^X Exit' in r for r in lines[rows - 2:]),
          repr(lines[rows - 2:]))
    body = lines[:rows - 2]
    check(f'3.{n + 3} {tag} 正文每行不超过 {cols} 单元格（无越界）',
          all(tab._text_width(x) <= cols for x in body),
          f'max={max(tab._text_width(x) for x in body)}')

# ===== 4. 宽字符列换算（CJK 占 2 单元格） =====
print('\n========== 4. 宽字符列换算 ==========')
probe = SessionTab(session_id='w', session_name='w', config_manager=_cm)
check('4.1 中文按 2 单元格计宽', probe._text_width('中文测试abc') == 11,
      str(probe._text_width('中文测试abc')))
check('4.2 显示列 12 对应中文行内字符下标 7',
      probe._col_to_offset('中文测试abc', 12) == 7,
      str(probe._col_to_offset('中文测试abc', 12)))
check('4.3 字符下标 7 反算显示列 12',
      probe._offset_to_col('中文测试abc', 7) == 12,
      str(probe._offset_to_col('中文测试abc', 7)))
check('4.4 纯 ASCII 列与字符下标一致',
      probe._col_to_offset('abcdef', 4) == 3 and probe._text_width('abcdef') == 6)

# ===== 汇总 =====
print('\n' + '=' * 60)
passed = sum(1 for _, s in results if s == 'PASS')
failed = sum(1 for _, s in results if s == 'FAIL')
print(f'测试结果: {passed} 通过, {failed} 失败, 共 {len(results)} 项')
if failed:
    print('\n失败项:')
    for name, status in results:
        if status == 'FAIL':
            print(f'  - {name}')
    print('=' * 60)
    sys.exit(1)
else:
    print('All tests passed!')
    print('=' * 60)
