# -*- coding: utf-8 -*-
"""终端交互模式回显机制系统性测试用例

测试目标：
1. 验证交互模式下不进行本地回显（消除首字母重复的根因）
2. 验证回车键发送 \r 而非 \n（PTY 标准）
3. 验证退格键发送 \x7f（DEL，PTY 标准）
4. 验证 _echo_suppress / _local_echo_sent 已彻底移除
5. 验证 _flush_output_buffer 直接输出服务器数据（无消重逻辑）
6. 验证非交互模式仍正常工作（本地回显不变）
7. 验证输入法和粘贴在交互模式下不做本地回显
8. 验证协议测试发送报文显示在接收区
"""
import sys
import os
import inspect

sys.path.insert(0, '.')

results = []

def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))

# ===== 1. 代码结构验证 =====
print('\n========== 1. 代码结构验证 ==========')

from plugins.terminal import terminal_widget as tw

# 1.1 _echo_suppress 方法已移除
check('1.1 _echo_suppress 方法已移除',
      not hasattr(tw.SessionTab, '_echo_suppress'),
      '_echo_suppress 不应存在')

# 1.2 _local_echo_sent 初始化已移除
src_init = inspect.getsource(tw.SessionTab.__init__)
check('1.2 _local_echo_sent 初始化已移除',
      '_local_echo_sent' not in src_init,
      '__init__ 中不应有 _local_echo_sent')

# 1.3 _flush_output_buffer 不调用 _echo_suppress
src_flush = inspect.getsource(tw.SessionTab._flush_output_buffer)
check('1.3 _flush_output_buffer 不调用 _echo_suppress',
      '_echo_suppress' not in src_flush,
      '_flush_output_buffer 中不应调用 _echo_suppress')

# 1.4 _flush_output_buffer 直接调用 write_output
check('1.4 _flush_output_buffer 直接调用 write_output',
      'self.write_output(complete_data)' in src_flush,
      '应直接输出 complete_data')

# ===== 2. 交互模式键盘处理验证 =====
print('\n========== 2. 交互模式键盘处理验证 ==========')

src_key = inspect.getsource(tw.SessionTab.handle_key_press)

# 2.1 回车键发送 \r（不是 \n）
check('2.1 回车键发送 \\r（PTY 标准）',
      'send_raw("\\r")' in src_key,
      '应发送 \\r 而非 \\n')

# 2.2 回车键不做本地回显
# 提取回车处理块
enter_block = ''
in_enter = False
for line in src_key.split('\n'):
    if 'Key_Return' in line or 'Key_Enter' in line:
        in_enter = True
    if in_enter:
        enter_block += line + '\n'
        if 'return' in line and 'Key_Return' not in line:
            break
check('2.2 回车键不做本地回显',
      'write_output' not in enter_block or "write_output" not in enter_block.split('send_raw')[1] if 'send_raw' in enter_block else True,
      '回车块中不应有 write_output 调用')

# 2.3 退格键发送 \x7f（DEL）
backspace_block = ''
in_bs = False
for line in src_key.split('\n'):
    if 'Key_Backspace' in line:
        in_bs = True
    if in_bs:
        backspace_block += line + '\n'
        if 'return' in line and 'Key_Backspace' not in line and 'Key_Delete' not in line:
            break
check('2.3 退格键发送 \\x7f（DEL，PTY 标准）',
      '\\x7f' in backspace_block,
      '应发送 \\x7f')

# 2.4 退格键不做本地回显（无 write_output('\b \b')）
check('2.4 退格键不做本地回显',
      "'\\b \\b'" not in backspace_block,
      '不应有 write_output(\\b \\b) 本地退格回显')

# 2.5 普通字符在交互模式下不做本地回显
char_block = ''
in_char = False
for line in src_key.split('\n'):
    if '普通字符' in line:
        in_char = True
    if in_char:
        char_block += line + '\n'
# 交互模式分支中不应有 write_output
if_split = char_block.split('has_raw')
if len(if_split) >= 2:
    interactive_part = if_split[1].split('else')[0] if 'else' in if_split[1] else if_split[1]
    check('2.5 普通字符交互模式下不做本地回显',
          'write_output' not in interactive_part,
          '交互模式分支不应有 write_output')

# 2.6 普通字符交互模式下不追加 _local_echo_sent
check('2.6 普通字符不追加 _local_echo_sent',
      '_local_echo_sent' not in char_block,
      '不应有 _local_echo_sent += text')

# ===== 3. 输入法和粘贴验证 =====
print('\n========== 3. 输入法和粘贴验证 ==========')

src_im = inspect.getsource(tw.SessionTab.handle_input_method_text)
check('3.1 输入法交互模式不做本地回显',
      'write_output' not in src_im.split('has_raw')[1].split('else')[0] if 'has_raw' in src_im and 'else' in src_im.split('has_raw')[1] else True,
      '交互模式分支不应有 write_output')

src_paste = inspect.getsource(tw.SessionTab.handle_paste_text)
check('3.2 粘贴交互模式不做本地回显',
      '_local_echo_sent' not in src_paste,
      '不应有 _local_echo_sent')

# ===== 4. 非交互模式验证（保持不变） =====
print('\n========== 4. 非交互模式验证 ==========')

# 4.1 非交互模式普通字符仍做本地回显
check('4.1 非交互模式普通字符仍做本地回显',
      "self.current_input += text\n                self.write_output(text, 'text')" in src_key,
      '非交互模式应保留 write_output')

# 4.2 非交互模式回车执行 execute_command
check('4.2 非交互模式回车执行 execute_command',
      'self.execute_command()' in enter_block,
      '应调用 execute_command()')

# ===== 5. 协议测试发送报文显示验证 =====
print('\n========== 5. 协议测试发送报文显示验证 ==========')

from plugins.protocol_tool import protocol_tool_widget as ptw
src_send = inspect.getsource(ptw.ProtocolToolWidget._on_send)
check('5.1 发送成功后显示 SEND 日志',
      '_format_send' in src_send and 'recv_text' in src_send,
      '_on_send 应调用 _format_send 并写入 recv_text')

check('5.2 发送后更新光标到末尾',
      'moveCursor' in src_send and 'End' in src_send,
      '应移动光标到末尾')

# ===== 6. GUI 初始化验证 =====
print('\n========== 6. GUI 初始化验证 ==========')

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from core.plugin_manager import PluginManager
from core.main_window import MainWindow
window = MainWindow(PluginManager())
window.show()
check('6.1 MainWindow 初始化成功', True, window.windowTitle())

# ===== 总结 =====
print('\n' + '=' * 60)
passed = sum(1 for _, s, _ in results if s == 'PASS')
failed = sum(1 for _, s, _ in results if s == 'FAIL')
print(f'测试结果: {passed} 通过, {failed} 失败, 共 {len(results)} 项')
if failed:
    print('\n失败项:')
    for name, status, detail in results:
        if status == 'FAIL':
            print(f'  - {name}: {detail}')
    print('=' * 60)
    sys.exit(1)
else:
    print('All tests passed!')
    print('=' * 60)
