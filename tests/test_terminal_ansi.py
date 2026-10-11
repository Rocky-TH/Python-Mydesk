# -*- coding: utf-8 -*-
"""终端 ANSI 序列处理和回车发送系统性测试

测试目标：
1. _flush_output_buffer 正确处理各种 ANSI 序列（CSI/OSC/SS3）
2. 不完整序列不会导致数据滞留
3. 颜色输出后的文本不会被误判为不完整序列
4. 回车键发送 \r（PTY 标准）
5. 交互模式下不做本地回显
6. _insert_text_with_cr 正确处理 OSC 序列和 CSI 问号参数
"""
import sys
import os

sys.path.insert(0, '.')

results = []

def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


# ===== 1. _parse_ansi_seq 单元测试 =====
print('\n========== 1. _parse_ansi_seq 单元测试 ==========')

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from plugins.terminal.terminal_widget import SessionTab
from utils.config_manager import ConfigManager
cm = ConfigManager()
tab = SessionTab(session_id='test', session_name='test', config_manager=cm)

# 1.1 完整 CSI 序列
data = '\x1b[32m'
end = tab._parse_ansi_seq(data, 0)
check('1.1 完整 CSI \\x1b[32m', end == len(data), f'期望 {len(data)}, 得到 {end}')

# 1.2 不完整 CSI 序列（缺结尾字母）
data = '\x1b[32'
end = tab._parse_ansi_seq(data, 0)
check('1.2 不完整 CSI \\x1b[32', end == 0, f'期望 0, 得到 {end}')

# 1.3 CSI 问号参数（如 \x1b[?25h 显示光标）
data = '\x1b[?25h'
end = tab._parse_ansi_seq(data, 0)
check('1.3 CSI 问号参数 \\x1b[?25h', end == len(data), f'期望 {len(data)}, 得到 {end}')

# 1.4 完整 OSC 序列（BEL 结尾）
data = '\x1b]0;title\x07'
end = tab._parse_ansi_seq(data, 0)
check('1.4 完整 OSC (BEL) \\x1b]0;title\\x07', end == len(data), f'期望 {len(data)}, 得到 {end}')

# 1.5 完整 OSC 序列（ST 结尾）
data = '\x1b]0;title\x1b\\'
end = tab._parse_ansi_seq(data, 0)
check('1.5 完整 OSC (ST) \\x1b]0;title\\x1b\\\\', end == len(data), f'期望 {len(data)}, 得到 {end}')

# 1.6 不完整 OSC 序列（缺 BEL）
data = '\x1b]0;title'
end = tab._parse_ansi_seq(data, 0)
check('1.6 不完整 OSC \\x1b]0;title', end == 0, f'期望 0, 得到 {end}')

# 1.7 SS3 序列
data = '\x1bOP'
end = tab._parse_ansi_seq(data, 0)
check('1.7 SS3 \\x1bOP', end == len(data), f'期望 {len(data)}, 得到 {end}')

# 1.8 简单 ESC + 字符
data = '\x1b='
end = tab._parse_ansi_seq(data, 0)
check('1.8 简单 ESC = \\x1b=', end == 2, f'期望 2, 得到 {end}')

# 1.9 单独 ESC（不完整）
data = '\x1b'
end = tab._parse_ansi_seq(data, 0)
check('1.9 单独 ESC (不完整)', end == 0, f'期望 0, 得到 {end}')

# ===== 2. _flush_output_buffer 集成测试 =====
print('\n========== 2. _flush_output_buffer 集成测试 ==========')

# 2.1 完整颜色输出 + 普通文本
tab._output_buffer = '\x1b[32mhello\x1b[0m world'
output_captured = []
orig_write = tab.write_output
tab.write_output = lambda text, color=None: output_captured.append(text)
tab._flush_output_buffer()
check('2.1 完整颜色+文本被输出', len(output_captured) == 1 and 'hello' in output_captured[0],
      f'output={output_captured}')
check('2.2 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

# 2.2 不完整 CSI 序列保留在缓冲区
tab._output_buffer = 'hello\x1b[32'
output_captured.clear()
tab._flush_output_buffer()
check('2.3 完整部分已输出', 'hello' in output_captured[0] if output_captured else False,
      f'output={output_captured}')
check('2.4 不完整序列保留在缓冲区', tab._output_buffer == '\x1b[32',
      f'buffer={repr(tab._output_buffer)}')

# 2.3 不完整序列补全后输出
tab._output_buffer += 'm colored'
output_captured.clear()
tab._flush_output_buffer()
check('2.5 补全后序列正确输出', len(output_captured) == 1 and 'colored' in output_captured[0],
      f'output={output_captured}')
check('2.6 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

# 2.4 颜色输出 + 提示符（关键场景：颜色输出后继续输入）
tab._output_buffer = '\x1b[01;32muser@host\x1b[00m:\x1b[01;34m~\x1b[00m$ '
output_captured.clear()
tab._flush_output_buffer()
check('2.7 颜色提示符完整输出', len(output_captured) == 1 and '$ ' in output_captured[0],
      f'output={output_captured}')
check('2.8 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

# 2.5 OSC 序列 + 颜色输出
tab._output_buffer = '\x1b]0;user@host:~\x07\x1b[32m$ \x1b[0m'
output_captured.clear()
tab._flush_output_buffer()
check('2.9 OSC+颜色完整输出', len(output_captured) == 1 and '$ ' in output_captured[0],
      f'output={output_captured}')
check('2.10 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

# 2.6 不完整 OSC 序列
tab._output_buffer = 'output\x1b]0;title'
output_captured.clear()
tab._flush_output_buffer()
check('2.11 完整部分已输出', 'output' in output_captured[0] if output_captured else False,
      f'output={output_captured}')
check('2.12 不完整OSC保留在缓冲区', tab._output_buffer == '\x1b]0;title',
      f'buffer={repr(tab._output_buffer)}')

# 2.7 修复旧版 bug：CSI 后跟文本，末尾不是字母
tab._output_buffer = '\x1b[32m$ \x1b[0m'
output_captured.clear()
tab._flush_output_buffer()
check('2.13 CSI+文本+CSI 完整输出', len(output_captured) == 1 and '$ ' in output_captured[0],
      f'output={output_captured}')
check('2.14 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

# 2.8 字符回显 + 不完整序列
tab._output_buffer = 'l'
output_captured.clear()
tab._flush_output_buffer()
check('2.15 单个字符 l 完整输出', len(output_captured) == 1 and output_captured[0] == 'l',
      f'output={output_captured}')
check('2.16 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

# 恢复
tab.write_output = orig_write

# ===== 3. 交互模式键盘处理验证 =====
print('\n========== 3. 交互模式键盘处理验证 ==========')

import inspect
src = inspect.getsource(tab.handle_key_press)

check('3.1 回车键发送 \\r', 'send_raw("\\r")' in src, '应发送 \\r')
check('3.2 退格键发送 \\x7f', '\\x7f' in src, '应发送 \\x7f')
check('3.3 无 _local_echo_sent', '_local_echo_sent' not in src, '不应有本地回显追踪')

# ===== 4. _insert_text_with_cr ANSI 处理验证 =====
print('\n========== 4. _insert_text_with_cr ANSI 处理验证 ==========')

src_insert = inspect.getsource(tab._insert_text_with_cr)
check('4.1 _insert_text_with_cr 支持 OSC 序列', "']'" in src_insert, '应处理 ] 序列')
check('4.2 _insert_text_with_cr 支持 CSI 问号参数', "'?'" in src_insert or '?<>' in src_insert,
      '应支持问号参数')
check('4.3 _insert_text_with_cr 支持 SS3 序列', "'O'" in src_insert, '应处理 SS3 序列')

# ===== 5. 旧版 bug 场景验证 =====
print('\n========== 5. 旧版 bug 场景验证 ==========')

# 旧版 bug：\x1b[0m$ \x1b[0m 被误判为不完整（因为 $ 后的 \x1b[0m 末尾 m 是字母，
# 但 rfind 找到的是最后一个 \x1b，而 after_esc[-1] 是空格不是字母）
# 新版应正确输出
tab._output_buffer = '\x1b[0m$ \x1b[0m'
output_captured = []
tab.write_output = lambda text, color=None: output_captured.append(text)
tab._flush_output_buffer()
check('5.1 颜色+提示符+颜色 完整输出', len(output_captured) == 1,
      f'output={output_captured}')
check('5.2 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

# 旧版 bug：CSI 序列后跟空格和文本，末尾不是字母被误判
tab._output_buffer = '\x1b[32mtext \x1b[0m more text'
output_captured.clear()
tab._flush_output_buffer()
check('5.3 多段CSI+文本完整输出', len(output_captured) == 1 and 'more text' in output_captured[0],
      f'output={output_captured}')
check('5.4 缓冲区已清空', tab._output_buffer == '', f'buffer={repr(tab._output_buffer)}')

tab.write_output = orig_write

# ===== 总结 =====
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
