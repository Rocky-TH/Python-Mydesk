# -*- coding: utf-8 -*-
"""终端连接选项卡拖动重排测试

- QTabWidget 可拖动（movable）
- 拖动连接标签可自由调整顺序，会话映射/关闭/当前选中不依赖固定索引
- 欢迎页固定首位，被拖动时自动归位
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

import plugins.terminal.terminal_widget as tw

app = QApplication.instance() or QApplication(sys.argv)

plugin = tw.TerminalPlugin({'name': 'Terminal', 'display_name': '终端'})
w = plugin.get_widget()
tabs = w.session_tabs

# ===== 1. 可拖动属性 =====
check('1.1 session_tabs 已开启 movable（支持拖动调整位置）', tabs.isMovable() is True)
check('1.2 拖动处理槽 _on_session_tab_moved 已定义',
      callable(getattr(w, '_on_session_tab_moved', None)))

# ===== 2. 初始顺序：a / b（首个会话创建时欢迎页自动移除） =====
tab_a = w.create_session({'name': 'srv-a', 'type': 'unknown-type', 'config': {}})
tab_b = w.create_session({'name': 'srv-b', 'type': 'unknown-type', 'config': {}})

names_initial = [tabs.tabText(i) for i in range(tabs.count())]
check('2.1 初始标签顺序 srv-a/srv-b（欢迎页在有会话时隐藏）',
      names_initial == ['srv-a', 'srv-b'], str(names_initial))

# ===== 3. 拖动：a 移到 b 后面 → b/a =====
tabs.tabBar().moveTab(0, 1)
names_moved = [tabs.tabText(i) for i in range(tabs.count())]
check('3.1 拖动后顺序 srv-b/srv-a',
      names_moved == ['srv-b', 'srv-a'], str(names_moved))
check('3.2 widget 位置与顺序一致（srv-b 在 index0、srv-a 在 index1）',
      tabs.widget(0) is tab_b and tabs.widget(1) is tab_a)

# ===== 4. 拖动后会话映射仍正确（sessions id → tab） =====
mapped = {sess['tab'] for sess in w.sessions.values()}
check('4.1 两个会话的 tab 引用均保留在 sessions 映射中',
      len(w.sessions) == 2 and tab_a in mapped and tab_b in mapped)

# ===== 5. 当前选中会话与 currentWidget 一致（自动选中最新创建的 a） =====
cur = w.get_current_session()
check('5.1 拖动后 get_current_session 仍返回当前标签对应会话',
      cur is tabs.currentWidget())

# ===== 6. 拖动后关闭标签，关闭的是正确会话 =====
id_a = [sid for sid, s in w.sessions.items() if s['tab'] is tab_a][0]
w.close_session(tabs.indexOf(tab_a))
check('6.1 关闭重排后的 srv-a 标签，对应会话被移除',
      id_a not in w.sessions)
check('6.2 剩余标签 srv-b',
      [tabs.tabText(i) for i in range(tabs.count())] == ['srv-b'])

# ===== 7. 全部关闭后欢迎页重建在首位，拖动槽对欢迎页场景安全 =====
w.close_session(tabs.indexOf(tab_b))
check('7.1 全部会话关闭后欢迎页重建在首位',
      tabs.count() == 1 and tabs.indexOf(w.empty_page) == 0)
# 直接触发拖动槽（防御性：欢迎页固定归位逻辑不报错、不移动）
w._on_session_tab_moved(0, 0)
check('7.2 欢迎页场景下拖动槽执行安全，欢迎页仍在首位',
      tabs.indexOf(w.empty_page) == 0)

# ===== 8. 连接标签之间再次重排正常 =====
tab_b2 = w.create_session({'name': 'srv-b', 'type': 'unknown-type', 'config': {}})
tab_c = w.create_session({'name': 'srv-c', 'type': 'unknown-type', 'config': {}})
# 重建后: srv-b(0) srv-c(1)，把 srv-c 移到 srv-b 前
tabs.tabBar().moveTab(1, 0)
check('8.1 多标签重排 srv-c/srv-b',
      [tabs.tabText(i) for i in range(tabs.count())] == ['srv-c', 'srv-b'])

w.deleteLater()

print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
