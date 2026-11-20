# -*- coding: utf-8 -*-
"""「刷新列表」从菜单迁移到侧边栏按钮的回归测试

需求：
1. 「设置 → 终端」里不再有「刷新列表」菜单项（避免重复入口，且不留空分隔线）；
2. 左侧边栏「新建连接」旁新增「刷新」按钮，功能与旧菜单项一致；
3. F5 快捷键保留并仍能刷新连接列表；
4. 按钮沿用「新建连接」的主题令牌，主题刷新/侧边栏收起展开后布局正常；
5. 刷新不改变当前会话（只重建已保存连接列表）。

本套件不触发真实网络连接，也不写入用户连接配置（连接数据源用桩替换）。
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
from PyQt6.QtGui import QShortcut

import plugins.terminal.terminal_widget as tw
from core.menu_registry import MenuRegistry
from utils.config_manager import ConfigManager

app = QApplication.instance() or QApplication(sys.argv)
_config_manager = ConfigManager()


def flatten_labels(items):
    """递归收集菜单项文字（跳过分隔符）"""
    labels = []
    for item in items:
        if item.get('type') == 'submenu':
            labels.append(item.get('label', ''))
            labels.extend(flatten_labels(item.get('items', [])))
        elif item.get('type') == 'action':
            labels.append(item.get('label', ''))
    return labels


def collect_shortcuts(items):
    """递归收集菜单项声明的快捷键"""
    shortcuts = []
    for item in items:
        if item.get('type') == 'submenu':
            shortcuts.extend(collect_shortcuts(item.get('items', [])))
        elif item.get('type') == 'action' and item.get('shortcut'):
            shortcuts.append(item['shortcut'])
    return shortcuts


def has_bad_separator(items):
    """菜单首项/末项为分隔符，或出现连续分隔符（空分隔线）"""
    if not items:
        return False
    if items[0].get('type') == 'separator' or items[-1].get('type') == 'separator':
        return True
    for prev, cur in zip(items, items[1:]):
        if prev.get('type') == 'separator' and cur.get('type') == 'separator':
            return True
    return False


# ===== 1. 菜单定义：刷新列表已移除 =====
print('\n========== 1. 菜单定义 ==========')
plugin = tw.TerminalPlugin({'name': 'Terminal', 'display_name': '终端'},
                           config_manager=_config_manager)
widget = plugin.get_widget()

registry = MenuRegistry()
registry.add_settings_menu(plugin.name, plugin.display_name)


class _Proxy:
    """与 terminal_plugin 中 _SettingsRegistryProxy 等价：复用设置分组"""

    def add_menu(self, *_args, **_kwargs):
        return registry


tw.TerminalPlugin.register_menus(plugin, _Proxy())
settings = registry.get_settings()
items = settings[0]['items'] if settings else []
labels = flatten_labels(items)

check('1.1 菜单中不再包含「刷新列表」', '刷新列表' not in labels, repr(labels))
check('1.2 菜单中不再声明 F5 快捷键',
      'F5' not in collect_shortcuts(items), repr(collect_shortcuts(items)))
check('1.3 菜单首项不是分隔符（没有残留空分隔线）',
      bool(items) and items[0].get('type') != 'separator',
      f'first={items[0].get("type") if items else None}')
check('1.4 菜单中没有连续/尾部分隔符',
      not has_bad_separator(items), repr([i.get('type') for i in items]))
for expected in ('字体大小', '保活时间', '颜色显示', '按钮工具栏', '日志记录', '侧边栏'):
    check(f'1.5 原有设置项仍保留：{expected}', expected in labels)


# ===== 2. 侧边栏按钮 =====
print('\n========== 2. 侧边栏按钮 ==========')
widget.resize(1000, 600)
widget.show()
app.processEvents()

btn = getattr(widget, 'refresh_conn_btn', None)
check('2.1 侧边栏存在「刷新」按钮', btn is not None and btn.text() == '刷新',
      btn.text() if btn is not None else 'missing')
check('2.2 按钮提示包含 F5', btn is not None and 'F5' in btn.toolTip(),
      btn.toolTip() if btn is not None else '')

row = widget.quick_actions.layout().itemAt(0).layout()
row2 = widget.quick_actions.layout().itemAt(1).layout()
check('2.3 与「新建连接」同级并排（同一行、紧随其后）',
      row is not None
      and row.indexOf(widget.new_conn_btn) == 0
      and row.indexOf(btn) == 1,
      f'indexes={row.indexOf(widget.new_conn_btn)}/{row.indexOf(btn)}'
      if row is not None else 'no row')
check('2.4 按钮与「新建连接」使用同一套主题样式',
      btn.styleSheet() == widget.new_conn_btn.styleSheet()
      and 'QPushButton' in btn.styleSheet())
# 侧边栏最小宽度 180，减去左右边距后一行必须放得下两个按钮，否则会裁字
_row1_hint = row.sizeHint().width()
check('2.5 最小侧边栏宽度下按钮行不溢出',
      _row1_hint <= 180 - 16, f'row={_row1_hint}')
check('2.6 SFTP 按钮保留在独立的下一行',
      row2 is not None and row2.indexOf(widget.sftp_btn) == 0)

# 主题切换：refresh_theme_styles 必须把新主题 CSS 应用到刷新按钮
_sentinel = 'QPushButton { color: rgb(1, 2, 3); }'
_orig_button_css = widget._get_button_css
widget._get_button_css = lambda _type='button': _sentinel
try:
    widget.refresh_theme_styles()
finally:
    widget._get_button_css = _orig_button_css
check('2.7 主题刷新后刷新按钮同步新样式',
      btn.styleSheet() == _sentinel and widget.new_conn_btn.styleSheet() == _sentinel,
      btn.styleSheet())


# ===== 3. 点击/F5 刷新行为 =====
print('\n========== 3. 刷新行为 ==========')
_orig_get_connections = widget.connection_manager.get_connections
widget.connection_manager.get_connections = lambda: [
    {'id': 'refresh-test', 'name': 'zz-refresh', 'type': 'ssh', 'config': {}}
]
try:
    widget.connection_list.clear()
    widget.refresh_conn_btn.click()
    app.processEvents()
    text = widget.connection_list.item(0).text() if widget.connection_list.count() else ''
    check('3.1 点击按钮后从连接数据源重建列表',
          widget.connection_list.count() == 1 and text == '[SSH] zz-refresh',
          f'count={widget.connection_list.count()} text={text!r}')

    sessions_before = (len(widget.sessions), widget.session_tabs.currentIndex())
    widget.connection_list.clear()
    widget.refresh_conn_btn.click()
    app.processEvents()
    sessions_after = (len(widget.sessions), widget.session_tabs.currentIndex())
    check('3.2 刷新不改变当前会话与选中标签',
          sessions_before == sessions_after, f'{sessions_before} -> {sessions_after}')

    shortcut = getattr(widget, 'refresh_connections_shortcut', None)
    check('3.3 F5 快捷键仍注册为 QShortcut',
          shortcut is not None and isinstance(shortcut, QShortcut)
          and shortcut.key().toString() == 'F5',
          shortcut.key().toString() if shortcut is not None else 'missing')

    widget.connection_list.clear()
    if shortcut is not None:
        shortcut.activated.emit()
    app.processEvents()
    check('3.4 F5 快捷键触发连接列表刷新',
          widget.connection_list.count() == 1
          and widget.connection_list.item(0).text() == '[SSH] zz-refresh',
          f'count={widget.connection_list.count()}')
finally:
    widget.connection_manager.get_connections = _orig_get_connections


# ===== 4. 侧边栏收起/展开布局 =====
print('\n========== 4. 侧边栏收起/展开 ==========')
widget.sidebar.hide()
app.processEvents()
check('4.1 侧边栏收起时布局索引不变',
      row.indexOf(widget.new_conn_btn) == 0 and row.indexOf(btn) == 1
      and row2.indexOf(widget.sftp_btn) == 0)
widget.sidebar.show()
app.processEvents()
check('4.2 侧边栏展开后刷新按钮恢复可见且位置不变',
      widget.sidebar.isVisible() and btn.isVisible()
      and row.indexOf(btn) == 1)

widget.close()
app.processEvents()

print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
