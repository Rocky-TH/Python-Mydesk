# -*- coding: utf-8 -*-
"""终端连接回调与 Telnet 协议测试

覆盖两处回归点：

1. SessionTab._on_async_connection_result（桩策略走完整连接回调链路）
   连接成功后必须输出连接 banner、渲染会话初始输出并启动输出轮询。
   该用例用于挡住 “SessionTab 误调 TerminalWidget 专属方法导致回调中途抛异常、
   状态显示已连接但界面毫无输出” 这类跨类回归。

2. Telnet 最小协议实现（Python 3.13 起标准库 telnetlib 已移除）
   IAC 过滤/转义、WILL/WONT/DO/DONT 协商、TERMINAL-TYPE/NAWS 子协商、
   跨 TCP 分片的命令解析，以及真实 TCP 下的登录交互端到端。
"""
import sys
import os
import time
import socket
import threading
import traceback

sys.path.insert(0, '.')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

results = []

# 捕获 Qt 槽函数里的未处理异常：PyQt 默认会用 qFatal 终止进程，
# 换成自定义 hook 后可以记录异常并继续跑完测试（复现回归时更易定位）
slot_errors = []


def _slot_excepthook(exc_type, exc_value, tb):
    slot_errors.append(''.join(traceback.format_exception(exc_type, exc_value, tb)))
    traceback.print_exception(exc_type, exc_value, tb)


sys.excepthook = _slot_excepthook


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


from PyQt6.QtWidgets import QApplication

import plugins.terminal.terminal_widget as tw
import plugins.terminal.telnet_connection as telnet_mod
from utils.config_manager import ConfigManager

app = QApplication.instance() or QApplication(sys.argv)

_ORIG_FACTORY = tw.ConnectionFactory.__dict__['create_connection']
_config_manager = ConfigManager()


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    return False


def install_stub(stub):
    tw.ConnectionFactory.create_connection = classmethod(lambda cls, conn_type: stub)


def restore_factory():
    tw.ConnectionFactory.create_connection = _ORIG_FACTORY


def new_tab(tag):
    return tw.SessionTab(session_id=tag, session_name=tag, config_manager=_config_manager)


def close_tab(tab):
    tab.disconnect()
    tab.deleteLater()
    pump(0.15)


class BaseStrategy:
    """桩连接策略的公共部分（不含 send_raw）"""

    def __init__(self, initial_output='', connect_ok=True, keepalive_error=None):
        self.initial_output = initial_output
        self.connect_ok = connect_ok
        self.keepalive_error = keepalive_error
        self.keepalive_calls = []
        self.connected = False

    def connect(self, config):
        self.connected = self.connect_ok
        return self.connect_ok

    def read_output(self, timeout=0.05):
        return self.initial_output

    def enable_keepalive(self, interval=30):
        self.keepalive_calls.append(interval)
        if self.keepalive_error:
            raise RuntimeError(self.keepalive_error)

    def get_endpoints(self):
        return '127.0.0.1:12345', '10.0.0.1:22'

    def is_connected(self):
        return self.connected

    def get_name(self):
        return 'SSH'

    def disconnect(self):
        self.connected = False


class StubStrategy(BaseStrategy):
    """可交互的桩连接策略（SSH 语义）"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent = []

    def send_raw(self, data):
        self.sent.append(data)


class NonInteractiveStrategy(BaseStrategy):
    """缺少 send_raw 的策略：走非交互分支"""


SSH_CONN = {'name': 'demo', 'type': 'ssh',
            'config': {'host': '10.0.0.1', 'port': 22, 'username': 'tester',
                       'password': 'p'}}


# ===== 1. 连接成功回调：banner / 初始输出 / 输出轮询 =====
print('\n========== 1. 连接成功回调 ==========')
stub = StubStrategy(initial_output='Welcome to test shell\r\n$ ')
install_stub(stub)
tab = new_tab('conn-ok')
try:
    tab.connect_with_config(dict(SSH_CONN))
    ok = wait_for(lambda: '✔ 连接成功' in tab.terminal_display.toPlainText(), 8)
    text = tab.terminal_display.toPlainText()
    check('1.0 连接回调无未捕获异常', not slot_errors,
          slot_errors[0].strip().splitlines()[-1] if slot_errors else '')
    check('1.1 成功回调执行到 banner 输出', ok and '✔ 连接成功' in text, repr(text[-120:]))
    check('1.2 banner 包含协议与登录用户',
          '协议类型 : SSH' in text and '登录用户 : tester' in text)
    check('1.3 会话初始输出已渲染', 'Welcome to test shell' in text)
    check('1.4 输出轮询已启动', tab.output_timer.isActive())
    check('1.5 交互模式已开启', tab.interactive_mode is True)
    check('1.6 状态为已连接', tab._status_text == '已连接')
    check('1.7 连接工作线程已释放', wait_for(lambda: tab._connection_worker is None, 3))
    check('1.8 保活已应用到策略', stub.keepalive_calls == [300],
          repr(stub.keepalive_calls))
finally:
    close_tab(tab)
    restore_factory()


# ===== 2. 保活设置抛异常时不中断连接流程 =====
print('\n========== 2. 保活失败不阻断连接 ==========')
stub = StubStrategy(initial_output='shell ready\r\n$ ', keepalive_error='boom')
install_stub(stub)
tab = new_tab('conn-keepalive-fail')
try:
    tab.connect_with_config(dict(SSH_CONN))
    ok = wait_for(lambda: 'shell ready' in tab.terminal_display.toPlainText(), 8)
    text = tab.terminal_display.toPlainText()
    check('2.1 保活异常后仍输出 banner', '✔ 连接成功' in text)
    check('2.2 banner 标明保活应用失败', '应用失败' in text and 'boom' in text)
    check('2.3 初始输出仍渲染', ok and 'shell ready' in text)
    check('2.4 输出轮询仍启动', tab.output_timer.isActive())
finally:
    close_tab(tab)
    restore_factory()


# ===== 3. 非交互策略分支 =====
print('\n========== 3. 非交互连接分支 ==========')
stub = NonInteractiveStrategy()
install_stub(stub)
tab = new_tab('conn-noninteractive')
try:
    tab.connect_with_config(dict(SSH_CONN))
    ok = wait_for(lambda: '✔ 连接成功' in tab.terminal_display.toPlainText(), 8)
    text = tab.terminal_display.toPlainText()
    check('3.1 非交互分支输出 banner', ok)
    check('3.2 非交互分支显示输入提示符', text.rstrip().endswith('SSH>'), repr(text[-40:]))
    check('3.3 非交互分支不启动轮询', not tab.output_timer.isActive())
    check('3.4 交互模式保持关闭', tab.interactive_mode is False)
finally:
    close_tab(tab)
    restore_factory()


# ===== 4. 连接失败分支 =====
print('\n========== 4. 连接失败分支 ==========')
stub = StubStrategy(connect_ok=False)
install_stub(stub)
tab = new_tab('conn-fail')
try:
    tab.connect_with_config(dict(SSH_CONN))
    ok = wait_for(lambda: '连接失败!' in tab.terminal_display.toPlainText(), 8)
    text = tab.terminal_display.toPlainText()
    check('4.1 失败分支输出失败提示', ok and '连接失败!' in text)
    check('4.2 失败分支状态为连接失败', tab._status_text == '连接失败')
    check('4.3 失败分支不启动轮询', not tab.output_timer.isActive())
finally:
    close_tab(tab)
    restore_factory()


# ===== 5. 保活能力表 =====
print('\n========== 5. 保活能力表 ==========')


class _KeepaliveProbe:
    def __init__(self):
        self.calls = []

    def enable_keepalive(self, interval):
        self.calls.append(interval)


probe = _KeepaliveProbe()
state, err = tw._apply_keepalive_to(probe, 'ssh', 60)
check('5.1 ssh 应用保活', state == 'applied' and probe.calls == [60], f'{state} {probe.calls}')
probe = _KeepaliveProbe()
state, err = tw._apply_keepalive_to(probe, 'telnet', 60)
check('5.2 telnet 应用保活', state == 'applied' and probe.calls == [60], f'{state} {probe.calls}')
probe = _KeepaliveProbe()
state, err = tw._apply_keepalive_to(probe, 'serial', 60)
check('5.3 serial 不支持保活', state == 'unsupported' and probe.calls == [], f'{state}')
state, err = tw._apply_keepalive_to(None, 'ssh', 60)
check('5.4 策略为空时视为不支持', state == 'unsupported', f'{state}')


# ===== 6. Telnet 协议解析（IAC 过滤/转义/协商/子协商） =====
print('\n========== 6. Telnet 协议解析 ==========')


def bare_client():
    client = telnet_mod._TelnetClient.__new__(telnet_mod._TelnetClient)
    client._state = 0
    client._verb = 0
    client._sb = bytearray()
    client._local_state = {}
    client._remote_state = {}
    client._width, client._height = 80, 24
    client.sent = []
    client._send = lambda data: client.sent.append(data)
    return client


IAC, WILL, WONT, DO, DONT = (telnet_mod.IAC, telnet_mod.WILL, telnet_mod.WONT,
                             telnet_mod.DO, telnet_mod.DONT)
SB, SE = telnet_mod.SB, telnet_mod.SE

c = bare_client()
check('6.1 普通数据原样返回', c._feed(b'hello') == b'hello')

c = bare_client()
out = c._feed(bytes([IAC, 241]) + b'ok' + bytes([IAC, IAC]))
check('6.2 命令字节不进入显示数据', out == b'ok\xff', repr(out))

c = bare_client()
out = c._feed(b'A' + bytes([IAC, IAC]) + b'B')
check('6.3 IAC IAC 还原为 0xFF', out == b'A\xffB', repr(out))

c = bare_client()
c._feed(bytes([IAC, WILL, telnet_mod.OPT_ECHO]))
check('6.4 服务端 WILL ECHO → DO ECHO',
      c.sent == [bytes([IAC, DO, telnet_mod.OPT_ECHO])], repr(c.sent))

c = bare_client()
c._feed(bytes([IAC, DO, telnet_mod.OPT_TERMINAL_TYPE]))
check('6.5 服务端 DO TERMINAL-TYPE → WILL',
      bytes([IAC, WILL, telnet_mod.OPT_TERMINAL_TYPE]) in c.sent, repr(c.sent))

c = bare_client()
c._feed(bytes([IAC, DO, 39]))
check('6.6 未支持选项回 WONT（避免反复协商）',
      c.sent == [bytes([IAC, WONT, 39])], repr(c.sent))
c._feed(bytes([IAC, DO, 39]))
check('6.7 重复请求不重复回包', len(c.sent) == 1, repr(c.sent))

# 子协商跨 TCP 分片
c = bare_client()
out1 = c._feed(bytes([IAC, SB, telnet_mod.OPT_TERMINAL_TYPE,
                      telnet_mod._TTYPE_SEND, IAC]))
out2 = c._feed(bytes([SE]))
expected = (bytes([IAC, SB, telnet_mod.OPT_TERMINAL_TYPE,
                   telnet_mod._TTYPE_IS]) + b'xterm-256color' + bytes([IAC, SE]))
check('6.8 跨分片的 TERMINAL-TYPE SEND 被完整识别',
      out1 == b'' and out2 == b'' and expected in c.sent, repr(c.sent))

c = bare_client()
c._feed(bytes([IAC, DO, telnet_mod.OPT_NAWS]))
naws_ok = (bytes([IAC, WILL, telnet_mod.OPT_NAWS]) in c.sent
           and any(p.startswith(bytes([IAC, SB, telnet_mod.OPT_NAWS])) for p in c.sent))
check('6.9 同意 NAWS 并上报窗口大小', naws_ok, repr(c.sent))


# ===== 7. Telnet 真实 TCP 端到端（含登录交互） =====
print('\n========== 7. Telnet 真实 TCP 端到端 ==========')


class TelnetTestServer:
    """最小 telnet 服务端：选项协商 + 登录提示 + 用户名/密码交互"""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.received = bytearray()
        self.error = None
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
            conn.settimeout(0.05)
            conn.sendall(bytes([IAC, WILL, telnet_mod.OPT_ECHO]))
            conn.sendall(bytes([IAC, DO, telnet_mod.OPT_SUPPRESS_GO_AHEAD]))
            conn.sendall(bytes([IAC, DO, telnet_mod.OPT_TERMINAL_TYPE])
                         + bytes([IAC, SB, telnet_mod.OPT_TERMINAL_TYPE,
                                  telnet_mod._TTYPE_SEND, IAC, SE]))
            conn.sendall(bytes([IAC, DO, telnet_mod.OPT_NAWS]))
            conn.sendall(b'login: ')
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                self.received.extend(data)
                if b'admin' in data:
                    conn.sendall(b'\r\nPassword: ')
                elif b'secret123' in data:
                    conn.sendall(b'\r\nWelcome to telnet lab\r\n$ ')
                elif b'\xff' not in data:
                    conn.sendall(b'\r\n$ ')
            conn.close()
        except Exception as exc:  # 测试辅助：记录而不是抛出到线程外
            self.error = repr(exc)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


server = TelnetTestServer()
telnet_conn = telnet_mod.TelnetConnection()
connected = telnet_conn.connect({'host': '127.0.0.1', 'port': server.port,
                                 'username': 'admin', 'password': 'secret123'})
check('7.1 Python 3.13 下 telnet 连接成功（不再依赖 telnetlib）', connected is True)

text = ''
end = time.time() + 8
while time.time() < end and 'Welcome to telnet lab' not in text:
    text += telnet_conn.read_output(0.05)
    time.sleep(0.02)
check('7.2 登录提示符已显示', 'login:' in text, repr(text))
check('7.3 密码提示已显示', 'Password:' in text, repr(text))
check('7.4 登录成功后的欢迎语已显示', 'Welcome to telnet lab' in text, repr(text))

wait_for(lambda: len(server.received) > 0, 3)
recv = bytes(server.received)
check('7.5 客户端应答 WILL TERMINAL-TYPE',
      bytes([IAC, WILL, telnet_mod.OPT_TERMINAL_TYPE]) in recv)
check('7.6 客户端应答 TERMINAL-TYPE IS xterm-256color',
      bytes([IAC, SB, telnet_mod.OPT_TERMINAL_TYPE, telnet_mod._TTYPE_IS])
      + b'xterm-256color' + bytes([IAC, SE]) in recv)
check('7.7 客户端应答 DO ECHO 与 WILL NAWS',
      bytes([IAC, DO, telnet_mod.OPT_ECHO]) in recv
      and bytes([IAC, WILL, telnet_mod.OPT_NAWS]) in recv)
check('7.8 用户名/密码以明文应用数据送达',
      b'admin' in recv and b'secret123' in recv)
telnet_conn.disconnect()
server.close()


# ===== 8. Telnet 走完整会话链路（banner + 轮询） =====
print('\n========== 8. Telnet 会话链路 ==========')
server = TelnetTestServer()
tab = new_tab('telnet-session')
try:
    tab.connect_with_config({'name': 'telnet-lab', 'type': 'telnet',
                             'config': {'host': '127.0.0.1', 'port': server.port,
                                        'username': '', 'password': ''}})
    ok = wait_for(lambda: '✔ 连接成功' in tab.terminal_display.toPlainText(), 12)
    text = tab.terminal_display.toPlainText()
    check('8.1 Telnet 成功回调输出 banner', ok and '协议类型 : TELNET' in text, repr(text[-120:]))
    check('8.2 Telnet 登录提示已渲染', 'login:' in text)
    check('8.3 Telnet 输出轮询已启动', tab.output_timer.isActive())
finally:
    close_tab(tab)
    server.close()


print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
