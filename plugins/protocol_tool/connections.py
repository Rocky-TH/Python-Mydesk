# -*- coding: utf-8 -*-
"""协议测试工具连接实现。

包含串口、TCP 客户端、TCP 服务端三种连接类型。所有连接基于 QThread 异步读取
数据，通过 pyqtSignal 将接收到的原始字节传递给主线程。每个连接类均提供
send_cmd 接口用于发送数据；recv_cmd 作为接口占位返回空字节，实际接收数据通过
data_received 信号异步推送（即“等效方法”）。
"""

import socket

from PyQt6.QtCore import QThread, pyqtSignal

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


def list_serial_ports():
    """列出系统可用的串口设备名列表。"""
    if not HAS_SERIAL:
        return []
    ports = []
    try:
        for port in serial.tools.list_ports.comports():
            ports.append(port.device)
    except Exception:
        pass
    return ports


def crc16_modbus(data):
    """计算 CRC-16/MODBUS 校验值（多项式 0xA001，初始值 0xFFFF）。

    Args:
        data: 待校验的字节串。

    Returns:
        16 位无符号整数 CRC 值。
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc16_modbus(data):
    """在数据末尾追加 CRC-16/MODBUS 校验码（低字节在前）。"""
    crc = crc16_modbus(data)
    return data + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class BaseConnection(QThread):
    """连接基类：定义统一的信号与接口。

    信号:
        data_received(bytes): 收到原始数据
        status_changed(str, bool): 状态文本与是否处于可用连接状态
        error_occurred(str): 致命错误信息
    """

    data_received = pyqtSignal(bytes)
    status_changed = pyqtSignal(str, bool)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._rx_bytes = 0
        self._tx_bytes = 0

    # 子类必须实现
    def open_connection(self, config):
        raise NotImplementedError

    def close_connection(self):
        raise NotImplementedError

    def send_cmd(self, data):
        """发送原始字节。子类应实现，返回是否成功。"""
        return False

    def recv_cmd(self):
        """接收数据接口（等效方法）。

        实际数据通过 data_received 信号异步推送，此处返回空字节以保证接口完整。
        """
        return b''

    def is_connected(self):
        return self._running

    def get_rx_bytes(self):
        return self._rx_bytes

    def get_tx_bytes(self):
        return self._tx_bytes


class SerialConnection(BaseConnection):
    """串口连接（基于 pyserial）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial = None
        self._port = ''
        self._baud = 115200

    def open_connection(self, config):
        if not HAS_SERIAL:
            self.error_occurred.emit("未安装 pyserial 库，无法使用串口")
            return False
        self._port = config.get('port', '')
        self._baud = int(config.get('baud', 115200))
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1,
                write_timeout=1,
            )
        except Exception as e:
            self.error_occurred.emit(f"串口打开失败: {e}")
            self._serial = None
            return False
        self._running = True
        self._rx_bytes = 0
        self._tx_bytes = 0
        # 启动读取线程（QThread.run）
        self.start()
        self.status_changed.emit(f"串口 {self._port} @ {self._baud} 已连接", True)
        return True

    def run(self):
        """串口读取循环：轮询 in_waiting 并发送数据。"""
        while self._running and self._serial:
            try:
                waiting = self._serial.in_waiting
                if waiting > 0:
                    data = self._serial.read(waiting)
                    if data:
                        self._rx_bytes += len(data)
                        self.data_received.emit(bytes(data))
                else:
                    self.msleep(10)
            except Exception as e:
                if self._running:
                    self.error_occurred.emit(f"串口读取错误: {e}")
                    self.status_changed.emit(f"串口读取错误: {e}", False)
                self._running = False
                break

    def send_cmd(self, data):
        if not self._serial or not self._serial.is_open:
            return False
        try:
            self._serial.write(data)
            self._tx_bytes += len(data)
            return True
        except Exception as e:
            self.error_occurred.emit(f"串口发送失败: {e}")
            return False

    def close_connection(self):
        self._running = False
        self.wait(2000)
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.status_changed.emit("串口已断开", False)

    def is_connected(self):
        return self._serial is not None and self._serial.is_open


class TCPClientConnection(BaseConnection):
    """TCP 客户端连接：主动连接远端 IP:Port。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = None
        self._host = ''
        self._port = 0

    def open_connection(self, config):
        self._host = config.get('host', '127.0.0.1')
        self._port = int(config.get('port', 8080))
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(2)
            self._sock.connect((self._host, self._port))
            # 连接成功后设置较短超时，便于读取循环及时退出
            self._sock.settimeout(0.2)
        except Exception as e:
            self.error_occurred.emit(f"TCP 连接失败: {e}")
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
            self._sock = None
            return False
        self._running = True
        self._rx_bytes = 0
        self._tx_bytes = 0
        self.start()
        self.status_changed.emit(f"TCP 客户端 {self._host}:{self._port} 已连接", True)
        return True

    def run(self):
        """读取循环：recv 收到空数据表示对端关闭。"""
        while self._running and self._sock:
            try:
                data = self._sock.recv(4096)
                if not data:
                    if self._running:
                        self.error_occurred.emit("服务器已断开连接")
                        self.status_changed.emit("服务器已断开连接", False)
                    self._running = False
                    break
                self._rx_bytes += len(data)
                self.data_received.emit(bytes(data))
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.error_occurred.emit(f"TCP 读取错误: {e}")
                    self.status_changed.emit(f"TCP 读取错误: {e}", False)
                self._running = False
                break

    def send_cmd(self, data):
        if not self._sock:
            return False
        try:
            self._sock.sendall(data)
            self._tx_bytes += len(data)
            return True
        except Exception as e:
            self.error_occurred.emit(f"TCP 发送失败: {e}")
            return False

    def close_connection(self):
        self._running = False
        self.wait(2000)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self.status_changed.emit("TCP 客户端已断开", False)

    def is_connected(self):
        return self._sock is not None


class TCPServerConnection(BaseConnection):
    """TCP 服务端连接：监听本地端口，接受单个客户端连接。

    客户端断开后继续等待新客户端，仅当主动 close_connection 时才停止。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self._client = None
        self._client_addr = None
        self._port = 0

    def open_connection(self, config):
        self._port = int(config.get('port', 8080))
        host = config.get('host', '0.0.0.0')
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((host, self._port))
            self._server.listen(1)
            # accept 使用短超时，便于循环检查 _running
            self._server.settimeout(0.5)
        except Exception as e:
            self.error_occurred.emit(f"TCP 服务端启动失败: {e}")
            if self._server:
                try:
                    self._server.close()
                except Exception:
                    pass
            self._server = None
            return False
        self._running = True
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._client = None
        self.start()
        self.status_changed.emit(f"TCP 服务端监听 :{self._port}，等待客户端...", True)
        return True

    def run(self):
        """服务端循环：accept -> 读取；客户端断开后回到 accept 阶段。"""
        while self._running and self._server:
            if self._client is None:
                try:
                    self._client, self._client_addr = self._server.accept()
                    self._client.settimeout(0.2)
                    self.status_changed.emit(
                        f"客户端 {self._client_addr[0]}:{self._client_addr[1]} 已连接", True)
                except socket.timeout:
                    continue
                except Exception:
                    if not self._running:
                        break
                    continue
            try:
                data = self._client.recv(4096)
                if not data:
                    # 客户端主动断开，回到等待状态
                    self.status_changed.emit("客户端已断开，等待重连...", True)
                    try:
                        self._client.close()
                    except Exception:
                        pass
                    self._client = None
                    continue
                self._rx_bytes += len(data)
                self.data_received.emit(bytes(data))
            except socket.timeout:
                continue
            except Exception:
                # 客户端异常断开，回到等待状态
                self.status_changed.emit("客户端异常断开，等待重连...", True)
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None
                continue

    def send_cmd(self, data):
        if not self._client:
            self.error_occurred.emit("无客户端连接，无法发送")
            return False
        try:
            self._client.sendall(data)
            self._tx_bytes += len(data)
            return True
        except Exception as e:
            self.error_occurred.emit(f"TCP 发送失败: {e}")
            return False

    def close_connection(self):
        self._running = False
        self.wait(2000)
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        self.status_changed.emit("TCP 服务端已关闭", False)

    def is_connected(self):
        return self._server is not None
