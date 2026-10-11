# -*- coding: utf-8 -*-
"""终端 UI 增强冒烟测试（4 项需求）

1. Tab 右键菜单+快捷键增加「关闭连接」功能
2. 连接选项卡 Tabby 风格样式（圆角浮起标签片）
3. 复制/重连/新建连接后自动选中会话并聚焦终端
4. 主窗口工具栏与菜单栏之间加分隔符，高度与菜单栏一致
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


# ===== 1. 静态结构验证 =====
print('\n========== 1. 关闭连接：右键菜单/快捷键 ==========')

import plugins.terminal.terminal_widget as tw
from core import main_window as mw

src_actions = inspect.getsource(tw.TerminalWidget._init_tab_context_actions)
check('1.1 act_tab_close 动作已创建（关闭连接）',
      'act_tab_close' in src_actions and '关闭连接' in src_actions)
check('1.2 关闭连接快捷键 Ctrl+Shift+W',
      'Ctrl+Shift+W' in src_actions)
check('1.3 Ctrl+Shift+W 注册为 QShortcut（终端内随时可用）',
      'QShortcut' in src_actions and '_action_tab_close' in src_actions)
check('1.7 QAction 不设置快捷键（右键菜单不显示快捷键提示）',
      'setShortcut' not in src_actions)

src_close = inspect.getsource(tw.TerminalWidget._action_tab_close)
check('1.4 _action_tab_close 复用 close_session 关闭当前会话',
      'close_session' in src_close and 'indexOf' in src_close)

src_menu = inspect.getsource(tw.TerminalWidget.show_tab_context_menu)
check('1.5 右键菜单包含关闭连接项',
      'act_tab_close' in src_menu and '关闭连接' in src_menu)

check('1.6 欢迎页快捷键面板含 Ctrl+Shift+W 条目',
      any(k == 'Ctrl+Shift+W' and v == '关闭连接'
          for k, v in tw.TerminalWidget._WELCOME_SHORTCUTS))

print('\n========== 2. Tabby 风格标签样式 ==========')

check('2.1 _tab_bar_qss 方法存在（统一样式源）',
      hasattr(tw.TerminalWidget, '_tab_bar_qss'))
qss_src = inspect.getsource(tw.TerminalWidget._tab_bar_qss)
check('2.2 全圆角标签片（border-radius: 6px）',
      "border-radius: 6px" in qss_src)
check('2.3 无生硬边框（border: none）',
      'border: none' in qss_src)
check('2.4 标签栏透明浮起（QTabBar background: transparent）',
      'QTabBar {' in qss_src and 'transparent' in qss_src)
check('2.5 选中态与悬停态颜色区分（独立选中色）',
      "tab_sel_bg" in qss_src and "'#454545'" in qss_src)

src_refresh = inspect.getsource(tw.TerminalWidget.refresh_theme_styles)
check('2.6 主题切换时复用 _tab_bar_qss',
      'self._tab_bar_qss()' in src_refresh)

print('\n========== 3. 操作后自动选中/聚焦 ==========')

src_create = inspect.getsource(tw.TerminalWidget.create_session)
check('3.1 create_session 新建后选中新标签',
      'setCurrentIndex(index)' in src_create)
check('3.2 create_session 焦点交给终端输入区',
      'terminal_display.setFocus()' in src_create)

src_async = inspect.getsource(tw.SessionTab._on_async_connection_result)
check('3.3 连接成功后焦点交给终端输入区（重连/复制均生效）',
      'terminal_display.setFocus()' in src_async)

print('\n========== 4. 主窗口工具栏分隔与高度 ==========')

src_toolbar = inspect.getsource(mw.MainWindow.create_tool_bar)
check('4.1 工具栏顶部加分隔线（border-top，与菜单栏隔开）',
      'border-top: 1px solid' in src_toolbar)
check('4.2 工具栏高度与菜单栏一致（setFixedHeight + sizeHint）',
      'setFixedHeight' in src_toolbar and 'sizeHint().height()' in src_toolbar)
check('4.3 按钮内边距收紧以适配菜单栏高度',
      'padding: 3px 10px' in src_toolbar)


# ===== 2. 运行时验证 =====
print('\n========== 5. 运行时验证 ==========')

from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtCore import QPoint

app = QApplication.instance() or QApplication(sys.argv)

plugin = tw.TerminalPlugin({'name': 'Terminal', 'display_name': '终端'})
widget = plugin.get_widget()
widget.resize(1000, 600)

# 5.1 动作与快捷键属性
from PyQt6.QtGui import QShortcut
check('5.1 act_tab_close 运行时存在且文本正确',
      getattr(widget, 'act_tab_close', None) is not None
      and widget.act_tab_close.text() == '关闭连接')
qshortcut_keys = [s.key().toString() for s in widget.findChildren(QShortcut)]
check('5.2 快捷键 Ctrl+Shift+W 由 QShortcut 提供',
      'Ctrl+Shift+W' in qshortcut_keys)

# 5.3 Tabby QSS 实际生成
qss = widget._tab_bar_qss()
check('5.3 实际生成的 QSS 含圆角/透明/选中色',
      'border-radius: 6px' in qss and 'QTabBar {' in qss and 'tab:selected' in qss)

# 5.4 create_session 自动选中新标签并请求焦点（type 未知 → 不启动网络线程）
focus_calls = []
_orig_set_focus = tw.TerminalEdit.setFocus
def _spy_set_focus(self, *a, **k):
    focus_calls.append(self)
    return _orig_set_focus(self, *a, **k)
tw.TerminalEdit.setFocus = _spy_set_focus

conn = {'name': 't1', 'type': 'unknown-type', 'config': {'host': 'x', 'port': 1}}
tab = widget.create_session(conn)
check('5.4 create_session 后新会话标签被选中',
      widget.session_tabs.currentIndex() == widget.session_tabs.indexOf(tab))
check('5.5 create_session 后终端输入区收到 setFocus 请求',
      any(c is tab.terminal_display for c in focus_calls))
tw.TerminalEdit.setFocus = _orig_set_focus

# 5.5 右键菜单包含关闭连接（拦截 exec 防阻塞）
captured = {}
_orig_exec = QMenu.exec
def _fake_exec(self, *a, **k):
    captured['actions'] = [(act.text(), act.isEnabled()) for act in self.actions()]
    return None
QMenu.exec = _fake_exec
try:
    widget.show_tab_context_menu(QPoint(5, 5))
finally:
    QMenu.exec = _orig_exec

acts = captured.get('actions', [])
names = [a[0] for a in acts]
check('5.6 右键菜单含 关闭连接 且可用',
      '关闭连接' in names and dict(acts).get('关闭连接') is True)
check('5.7 未连接时 断开连接 置灰、复制/重连可用',
      dict(acts).get('断开连接') is False
      and dict(acts).get('复制连接') is True
      and dict(acts).get('重新连接') is True)

# 5.6 关闭连接动作实际关闭会话标签
widget._action_tab_close()
check('5.8 _action_tab_close 后会话被移除',
      len(widget.sessions) == 0 and widget.current_session_id is None)
check('5.9 关闭全部会话后恢复欢迎页',
      widget.session_tabs.count() == 1
      and widget.session_tabs.tabText(0) == '欢迎')

# 5.7 QAction 无快捷键 → 右键菜单仅显示功能名
from PyQt6.QtGui import QKeySequence
check('5.10 右键菜单动作不带快捷键提示',
      widget.act_tab_close.shortcut().toString() == ''
      and widget.act_tab_duplicate.shortcut().toString() == '')

widget.deleteLater()

# ===== 汇总 =====
print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
