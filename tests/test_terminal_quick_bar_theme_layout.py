# -*- coding: utf-8 -*-
"""终端快速连接栏：下拉主题化 + Telnet 布局回归测试

覆盖两处界面问题：
1. 深色主题下串口号/波特率（可编辑下拉）的编辑区、箭头、下拉面板要使用主题令牌；
2. Telnet 模式下主机/端口/用户名宽度分配与间距合理，切换连接类型不跳动。
"""
import os
import sys

sys.path.insert(0, '.')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QLabel

import plugins.terminal.terminal_widget as tw
from utils.config_manager import ConfigManager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

results = []


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


app = QApplication.instance() or QApplication(sys.argv)
config_manager = ConfigManager(os.path.join(ROOT, 'config'))
widget = tw.TerminalWidget({}, config_manager)
widget.resize(1200, 800)
widget.show()
app.processEvents()


def apply_theme(theme):
    config_manager._style_config['current_theme'] = theme
    widget.refresh_theme_styles()
    app.processEvents()


def switch_type(conn_type):
    widget.qc_type_combo.setCurrentText(conn_type)
    app.processEvents()


def abs_x(target):
    return target.mapTo(widget.quick_bar, QPoint(0, 0)).x()


def bar_gaps(fields):
    """相邻字段之间的水平空隙"""
    return [abs_x(b) - (abs_x(a) + a.width()) for a, b in zip(fields, fields[1:])]


def baud_label():
    page = widget.qc_stack.widget(1)
    for label in page.findChildren(QLabel):
        if label.text() == '波特率':
            return label
    return None


def arrow_token(combo):
    """主题化下拉的箭头色（普通 QComboBox 无此属性时返回 None）"""
    color = getattr(combo, '_arrow_color', None)
    return color.name().lower() if color is not None else None


def arrow_color(combo):
    """读取组合框箭头中心的实际像素颜色"""
    image = combo.grab().toImage()
    ratio = image.devicePixelRatio() or 1.0
    x = min(image.width() - 1, int(image.width() - 11 * ratio))
    y = image.height() // 2
    return image.pixelColor(x, y)


print('\n========== 1. 快速连接栏控件类型 ==========')
check('1.1 连接类型下拉使用主题化下拉（_ThemedComboBox）',
      isinstance(widget.qc_type_combo, tw._ThemedComboBox))
check('1.2 串口号下拉使用主题化下拉（_ThemedComboBox）',
      isinstance(widget.qc_serial_combo, tw._ThemedComboBox),
      type(widget.qc_serial_combo).__name__)
check('1.3 波特率下拉使用主题化下拉（_ThemedComboBox）',
      isinstance(widget.qc_baud_combo, tw._ThemedComboBox),
      type(widget.qc_baud_combo).__name__)
check('1.4 两个串口下拉保持可编辑（允许手填 COM30/256000）',
      widget.qc_serial_combo.isEditable() and widget.qc_baud_combo.isEditable())


print('\n========== 2. 深色主题：编辑区/标签/箭头/面板 ==========')
apply_theme('dark')
qss_dark = widget._quick_bar_qss()
check('2.1 QSS 显式约束可编辑下拉的内部编辑区（QComboBox QLineEdit）',
      'QComboBox QLineEdit {' in qss_dark and 'background: transparent' in qss_dark)
check('2.2 内部编辑区聚焦态不再叠加第二层边框/底色',
      'QComboBox QLineEdit:focus' in qss_dark)
check('2.3 下拉聚焦态与其它输入框一致（QComboBox:focus）',
      'QComboBox:focus' in qss_dark)
check('2.4 屏蔽原生/图片箭头，改由主题色自绘',
      'QComboBox::down-arrow { image: none; }' in qss_dark)

label = baud_label()
dark_text = config_manager.get_color('text')
check('2.5 「波特率」标签文字使用主题 text 色（深色下不再是系统黑色）',
      label is not None
      and label.palette().color(label.foregroundRole()).name().lower()
      == dark_text.lower(),
      f'label={label.palette().color(label.foregroundRole()).name() if label else None}, '
      f'text={dark_text}')

baud_edit = widget.qc_baud_combo.lineEdit()
serial_edit = widget.qc_serial_combo.lineEdit()
dark_bg_input = config_manager.get_color('bg-input')
check('2.6 波特率编辑区底色 = 主题 bg-input（深色下不露系统浅色底）',
      baud_edit.palette().color(baud_edit.backgroundRole()).name().lower()
      == dark_bg_input.lower(),
      f'{baud_edit.palette().color(baud_edit.backgroundRole()).name()} vs {dark_bg_input}')
check('2.7 串口号编辑区底色 = 主题 bg-input',
      serial_edit.palette().color(serial_edit.backgroundRole()).name().lower()
      == dark_bg_input.lower(),
      serial_edit.palette().color(serial_edit.backgroundRole()).name())
check('2.8 编辑区文字色 = 主题 text',
      baud_edit.palette().color(baud_edit.foregroundRole()).name().lower()
      == dark_text.lower(),
      baud_edit.palette().color(baud_edit.foregroundRole()).name())

dark_secondary = config_manager.get_color('text-secondary')
check('2.9 三个下拉的箭头色都取主题 text-secondary',
      arrow_token(widget.qc_type_combo) == dark_secondary.lower()
      and arrow_token(widget.qc_serial_combo) == dark_secondary.lower()
      and arrow_token(widget.qc_baud_combo) == dark_secondary.lower(),
      f'type={arrow_token(widget.qc_type_combo)}, '
      f'baud={arrow_token(widget.qc_baud_combo)}, token={dark_secondary}')

arrow_dark = arrow_color(widget.qc_baud_combo)
bg_dark = arrow_color(widget.qc_serial_combo)  # 同底色的参考点
check('2.10 深色下箭头实际渲染为可见的主题色像素',
      arrow_dark.name().lower() != dark_bg_input.lower()
      and arrow_dark.red() > 120 and abs(arrow_dark.red() - arrow_dark.blue()) < 30,
      f'arrow={arrow_dark.name()}, bg={dark_bg_input}')

view_dark = widget.qc_serial_combo.view()
check('2.11 下拉面板背景/文字取主题令牌（深色）',
      view_dark.palette().base().color().name().lower()
      == config_manager.get_color('bg-tertiary').lower()
      and view_dark.palette().text().color().name().lower() == dark_text.lower(),
      f'base={view_dark.palette().base().color().name()}')


print('\n========== 3. 浅色主题：与深色同源同令牌 ==========')
apply_theme('light')
qss_light = widget._quick_bar_qss()
check('3.1 浅色主题 QSS 同样约束内部编辑区',
      'QComboBox QLineEdit {' in qss_light and 'background: transparent' in qss_light)
light_text = config_manager.get_color('text')
light_bg_input = config_manager.get_color('bg-input')
light_secondary = config_manager.get_color('text-secondary')
label = baud_label()
check('3.2 「波特率」标签颜色跟随浅色主题 text',
      label is not None
      and label.palette().color(label.foregroundRole()).name().lower()
      == light_text.lower(),
      label.palette().color(label.foregroundRole()).name() if label else None)
check('3.3 波特率编辑区底色 = 浅色主题 bg-input',
      baud_edit.palette().color(baud_edit.backgroundRole()).name().lower()
      == light_bg_input.lower(),
      baud_edit.palette().color(baud_edit.backgroundRole()).name())
check('3.4 主题切换后箭头颜色同步为浅色 text-secondary',
      arrow_token(widget.qc_baud_combo) == light_secondary.lower(),
      str(arrow_token(widget.qc_baud_combo)))
arrow_light = arrow_color(widget.qc_baud_combo)
check('3.5 浅色下箭头实际渲染为深色可见像素',
      arrow_light.name().lower() != light_bg_input.lower()
      and arrow_light.red() < 140,
      f'arrow={arrow_light.name()}, bg={light_bg_input}')


print('\n========== 4. Telnet 字段宽度与间距 ==========')
apply_theme('dark')
switch_type('telnet')
net_layout = widget.qc_stack.widget(0).layout()
spacing = net_layout.spacing()
telnet_fields = [widget.qc_host_input, widget.qc_port_input, widget.qc_user_input]
check('4.1 Telnet 字段之间间距 = 布局统一 spacing（无均摊留白）',
      bar_gaps(telnet_fields) == [spacing, spacing],
      f'gaps={bar_gaps(telnet_fields)}, spacing={spacing}')
check('4.2 主机框弹性填充剩余宽度（不再固定 195px）',
      widget.qc_host_input.minimumWidth() == 160
      and widget.qc_host_input.width() > 250,
      f'min={widget.qc_host_input.minimumWidth()}, w={widget.qc_host_input.width()}')
check('4.3 端口框宽度固定 64（5 位端口刚好）',
      widget.qc_port_input.minimumWidth() == 64
      and widget.qc_port_input.width() == 64)
check('4.4 用户名/密码框等宽 110（SSH 下也一致）',
      widget.qc_user_input.width() == 110
      and widget.qc_password_input.width() == 110)
check('4.5 最后一个字段紧贴保存按钮（gap = spacing，对齐不突兀）',
      abs_x(widget.qc_save_btn) - (abs_x(widget.qc_user_input)
                                   + widget.qc_user_input.width()) == spacing,
      f'gap={abs_x(widget.qc_save_btn) - (abs_x(widget.qc_user_input) + widget.qc_user_input.width())}')


print('\n========== 5. SSH / 串口布局一致、切换不跳动 ==========')
switch_type('ssh')
ssh_fields = [widget.qc_host_input, widget.qc_port_input, widget.qc_user_input,
              widget.qc_password_input, widget.qc_keyfile_widget]
check('5.1 SSH 各字段间距均为统一 spacing',
      bar_gaps(ssh_fields) == [spacing] * 4,
      f'gaps={bar_gaps(ssh_fields)}')
check('5.2 SSH 下主机与密钥框平分弹性宽度（宽度相等）',
      widget.qc_host_input.width() == widget.qc_keyfile_widget.width(),
      f'{widget.qc_host_input.width()} vs {widget.qc_keyfile_widget.width()}')
check('5.3 SSH 最后一个字段同样紧贴保存按钮',
      abs_x(widget.qc_save_btn) - (abs_x(widget.qc_keyfile_widget)
                                   + widget.qc_keyfile_widget.width()) == spacing)

switch_type('serial')
serial_page = widget.qc_stack.widget(1).layout()
serial_gap = serial_page.spacing()
check('5.4 串口页：串口下拉→刷新→波特率标签→波特率框间距统一',
      bar_gaps([widget.qc_serial_combo, widget.qc_serial_refresh_btn]) == [serial_gap]
      and abs_x(widget.qc_baud_combo) - (abs_x(widget.qc_serial_refresh_btn)
                                         + widget.qc_serial_refresh_btn.width())
      == serial_gap + baud_label().width() + serial_gap,
      f'spacing={serial_gap}')
check('5.5 波特率框宽度固定 96，不随串口号变宽变窄',
      widget.qc_baud_combo.width() == 96)
check('5.6 串口最后一个字段紧贴保存按钮',
      abs_x(widget.qc_save_btn) - (abs_x(widget.qc_baud_combo)
                                   + widget.qc_baud_combo.width()) == spacing)

positions = {}
for conn_type in ('ssh', 'telnet', 'serial'):
    switch_type(conn_type)
    positions[conn_type] = (abs_x(widget.qc_stack), widget.qc_stack.width(),
                            abs_x(widget.qc_save_btn), widget.qc_save_btn.width(),
                            abs_x(widget.qc_connect_btn), widget.qc_connect_btn.width(),
                            widget.quick_bar.height())
check('5.7 三种类型切换时参数区/保存/连接按钮位置与高度完全不变',
      len(set(positions.values())) == 1,
      str(positions))
check('5.8 快速连接栏高度固定 38（切换类型不抖动）',
      widget.quick_bar.height() == 38, widget.quick_bar.height())

widget.close()
widget.deleteLater()

print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
