import select
import socket
import threading
import time

from .connection_base import ConnectionBase
from utils.logger import Logger

# Telnet 协议常量（RFC 854/855/857/858/1073/1091/1096）
IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240

OPT_BINARY = 0
OPT_ECHO = 1
OPT_SUPPRESS_GO_AHEAD = 3
OPT_TERMINAL_TYPE = 24
OPT_NAWS = 31

# 子协商命令：TERMINAL-TYPE SEND/IS
_TTYPE_SEND = 1
_TTYPE_IS = 0

# 本端愿意开启的选项（收到 DO 时回 WILL）
_LOCAL_OPTIONS = {OPT_BINARY, OPT_SUPPRESS_GO_AHEAD, OPT_TERMINAL_TYPE, OPT_NAWS}
# 允许服务端开启的选项（收到 WILL 时回 DO）
_REMOTE_OPTIONS = {OPT_BINARY, OPT_ECHO, OPT_SUPPRESS_GO_AHEAD}


class _TelnetClient:
    """最小可用的 Telnet 客户端（命令流过滤 + 基础选项协商）

    Python 3.13 移除了标准库 telnetlib，此处用 socket 自实现交互式终端所需
    的最小协议子集，不引入新依赖：

    - 过滤/转义 IAC 命令字节，只把应用数据交给上层渲染；
    - WILL/WONT/DO/DONT 协商：只接受终端会话必需的选项（ECHO、SGA、
      BINARY、TERMINAL-TYPE、NAWS），其余一律拒绝，避免与服务端反复协商；
    - 应答 TERMINAL-TYPE SEND 并声明 xterm-256color，回应窗口大小 NAWS。

    登录用户名/密码的交互依赖这些协商：服务端通常先协商 ECHO/SGA 再发
    登录提示符，若不应答，部分 telnetd 会等待超时才输出 login 提示。
    """

    TERM_TYPE = 'xterm-256color'

    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            Logger.get_instance().debug(f"Telnet 设置 TCP_NODELAY 失败: {exc}")
        # 解析状态：0 普通数据 / 1 收到 IAC / 2 收到 IAC+命令待选项 / 3 SB 内容 / 4 SB 内收到 IAC
        self._state = 0
        self._verb = 0
        self._sb = bytearray()
        self._local_state = {}
        self._remote_state = {}
        self._width, self._height = 80, 24

    # ---------- 发送 ----------
    def _send(self, data):
        if not data:
            return
        try:
            self.sock.sendall(data)
        except OSError as exc:
            Logger.get_instance().warning(f"Telnet 发送失败: {exc}")

    def _send_command(self, verb, option):
        self._send(bytes([IAC, verb, option]))

    def _send_subnegotiation(self, payload):
        escaped = payload.replace(b'\xff', b'\xff\xff')
        self._send(bytes([IAC, SB]) + escaped + bytes([IAC, SE]))

    def write(self, data):
        """写入应用数据（IAC 字节按协议双写转义）"""
        if isinstance(data, str):
            data = data.encode('utf-8')
        self._send(data.replace(b'\xff', b'\xff\xff'))

    # ---------- 接收 ----------
    def read_very_eager(self):
        """非阻塞读取，返回过滤掉 telnet 命令后的应用数据"""
        chunks = []
        while True:
            try:
                ready, _, _ = select.select([self.sock], [], [], 0)
            except (OSError, ValueError):
                break
            if not ready:
                break
            try:
                data = self.sock.recv(4096)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            if not data:
                break
            chunks.append(self._feed(data))
        return b''.join(chunks)

    def _feed(self, data):
        """按状态机拆解 telnet 命令流，返回其中的应用数据"""
        out = bytearray()
        for byte in data:
            if self._state == 0:
                if byte == IAC:
                    self._state = 1
                else:
                    out.append(byte)
            elif self._state == 1:
                if byte == IAC:
                    # IAC IAC：数据中的 0xFF 字面量
                    out.append(IAC)
                    self._state = 0
                elif byte in (WILL, WONT, DO, DONT):
                    self._verb = byte
                    self._state = 2
                elif byte == SB:
                    self._sb = bytearray()
                    self._state = 3
                else:
                    # NOP/GA/DM/BRK/IP/AO/AYT 等：无显示效果，直接忽略
                    self._state = 0
            elif self._state == 2:
                self._handle_negotiation(self._verb, byte)
                self._state = 0
            elif self._state == 3:
                if byte == IAC:
                    self._state = 4
                else:
                    self._sb.append(byte)
            else:  # 子协商内遇到 IAC
                if byte == SE:
                    self._handle_subnegotiation(bytes(self._sb))
                    self._sb = bytearray()
                    self._state = 0
                elif byte == IAC:
                    self._sb.append(IAC)
                    self._state = 3
                else:
                    self._sb.extend((IAC, byte))
                    self._state = 3
        return bytes(out)

    def _handle_negotiation(self, verb, option):
        """应答选项协商；重复的拒绝不再回包，避免与服务端来回死循环"""
        if verb == DO:
            if option in _LOCAL_OPTIONS:
                if self._local_state.get(option) != WILL:
                    self._local_state[option] = WILL
                    self._send_command(WILL, option)
                    if option == OPT_NAWS:
                        self._send_naws()
            elif self._local_state.get(option) != WONT:
                self._local_state[option] = WONT
                self._send_command(WONT, option)
        elif verb == DONT:
            if self._local_state.get(option) == WILL:
                self._local_state[option] = WONT
                self._send_command(WONT, option)
            else:
                self._local_state.setdefault(option, WONT)
        elif verb == WILL:
            if option in _REMOTE_OPTIONS:
                if self._remote_state.get(option) != DO:
                    self._remote_state[option] = DO
                    self._send_command(DO, option)
            elif self._remote_state.get(option) != DONT:
                self._remote_state[option] = DONT
                self._send_command(DONT, option)
        else:  # WONT：服务端关闭，无需再回 DONT
            self._remote_state[option] = DONT

    def _handle_subnegotiation(self, body):
        if len(body) >= 2 and body[0] == OPT_TERMINAL_TYPE and body[1] == _TTYPE_SEND:
            payload = bytes([OPT_TERMINAL_TYPE, _TTYPE_IS]) + self.TERM_TYPE.encode()
            self._send_subnegotiation(payload)

    def _send_naws(self):
        w, h = self._width, self._height
        payload = bytes([OPT_NAWS, (w >> 8) & 0xFF, w & 0xFF, (h >> 8) & 0xFF, h & 0xFF])
        self._send_subnegotiation(payload)

    def close(self):
        try:
            self.sock.close()
        except OSError as exc:
            Logger.get_instance().debug(f"关闭 Telnet 套接字失败: {exc}")


class TelnetConnection(ConnectionBase):
    """Telnet连接策略"""

    def __init__(self):
        super().__init__()
        self.port = 23
        self.tn = None
        self._lock = threading.Lock()

    def connect(self, config):
        self.host = config.get('host', '')
        self.port = config.get('port', 23)
        self.username = config.get('username', '')
        self.password = config.get('password', '')

        result = [False]
        error_msg = [None]

        def connect_task():
            try:
                self.tn = _TelnetClient(self.host, self.port, timeout=10)

                time.sleep(1)
                
                if self.username:
                    self.tn.write(self.username.encode('utf-8') + b"\n")
                    time.sleep(0.5)
                
                if self.password:
                    self.tn.write(self.password.encode('utf-8') + b"\n")
                    time.sleep(1)
                
                self.connected = True
                result[0] = True
            except Exception as e:
                error_msg[0] = str(e)
                result[0] = False
        
        thread = threading.Thread(target=connect_task)
        thread.daemon = True
        thread.start()
        thread.join(timeout=15)
        
        if not result[0] and error_msg[0]:
            print(f"Telnet连接错误: {error_msg[0]}")
            
        return result[0]

    def disconnect(self):
        self.connected = False
        try:
            if self.tn:
                self.tn.close()
        except Exception as exc:
            Logger.get_instance().debug(f"关闭 Telnet 连接失败: {exc}")
        self.tn = None

    def send_command(self, command, timeout=1.0):
        """发送命令并等待响应"""
        if not self.connected or not self.tn:
            return "[错误: 未连接]\n"
        
        try:
            self.tn.write(command.encode('utf-8') + b"\n")
            time.sleep(timeout)
            response = self.tn.read_very_eager().decode('utf-8', errors='replace')
            return response
        except Exception as e:
            return f"[错误: {str(e)}]\n"

    def send_raw(self, data):
        """发送原始数据到Telnet会话"""
        if self.connected and self.tn:
            try:
                if isinstance(data, str):
                    self.tn.write(data.encode('utf-8'))
                else:
                    self.tn.write(data)
            except Exception as exc:
                Logger.get_instance().warning(f"Telnet 发送数据失败: {exc}")

    def read_output(self, timeout=0.1):
        """读取Telnet响应数据（非阻塞，已过滤 telnet 命令字节）"""
        if not self.connected or not self.tn:
            return ""

        try:
            return self.tn.read_very_eager().decode('utf-8', errors='replace')
        except Exception as exc:
            Logger.get_instance().debug(f"Telnet 读取输出失败: {exc}")
            return ""

    def read_all(self, timeout=0.5):
        """读取所有可用数据"""
        result = ""
        start = time.time()
        while time.time() - start < timeout:
            data = self.read_output(0.1)
            if data:
                result += data
            elif result:
                # 如果已有数据且没有更多数据，退出
                break
        return result

    def enable_keepalive(self, interval=30):
        """开启 TCP 保活，防止空闲连接被 NAT/防火墙超时断开

        Telnet 无应用层心跳，依赖 TCP SO_KEEPALIVE（Windows/Linux 均支持）。
        """
        interval = max(5, int(interval))
        try:
            import socket as _socket
            if self.tn and getattr(self.tn, 'sock', None):
                s = self.tn.sock
                s.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
                # 精细参数在部分平台可用；Windows 上 TCP_KEEPIDLE/INTVL 也可能存在
                if hasattr(_socket, 'TCP_KEEPIDLE'):
                    s.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, interval)
                if hasattr(_socket, 'TCP_KEEPINTVL'):
                    s.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL,
                                 max(1, interval // 3))
        except Exception as exc:
            Logger.get_instance().warning(f"Telnet 保活设置失败: {exc}")

    def get_endpoints(self):
        """返回 (本地地址, 远程地址) 字符串元组，供连接成功 banner 展示"""
        local, remote = "", ""
        try:
            if self.tn and getattr(self.tn, 'sock', None):
                laddr = self.tn.sock.getsockname()
                raddr = self.tn.sock.getpeername()
                if isinstance(laddr, tuple) and len(laddr) >= 2:
                    local = f"{laddr[0]}:{laddr[1]}"
                if isinstance(raddr, tuple) and len(raddr) >= 2:
                    remote = f"{raddr[0]}:{raddr[1]}"
        except Exception as exc:
            Logger.get_instance().debug(f"读取 Telnet 端点信息失败: {exc}")
        return local, remote

    def is_connected(self):
        return self.connected

    def get_name(self):
        return "Telnet"

    def get_info(self):
        """获取Telnet连接信息"""
        info = super().get_info()
        return info

    def expect(self, patterns, timeout=1.0):
        """等待匹配指定模式之一（Telnet特定实现）"""
        if not self.connected or not self.tn:
            return (-1, "", "")
        
        import socket
        start_time = time.time()
        buffer = ""
        
        while time.time() - start_time < timeout:
            try:
                # 尝试读取
                data = self.tn.read_very_eager()
                if data:
                    decoded = data.decode('utf-8', errors='replace')
                    buffer += decoded
                    
                    # 检查是否匹配模式
                    for i, pattern in enumerate(patterns):
                        if pattern in buffer:
                            return (i, pattern, buffer)
                
                time.sleep(0.05)
            except Exception as exc:
                Logger.get_instance().warning(f"Telnet expect 读取中断: {exc}")
                break
        
        return (-1, "", buffer)
