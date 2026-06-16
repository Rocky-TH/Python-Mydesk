import threading
import socket
import time
from .connection_strategy import ConnectionStrategy

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

try:
    import telnetlib
    HAS_TELNETLIB = True
except ImportError:
    HAS_TELNETLIB = False

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


class SSHStrategy(ConnectionStrategy):
    """SSH连接策略"""

    def __init__(self):
        self.connected = False
        self.host = ""
        self.port = 22
        self.username = ""
        self.password = ""
        self.client = None
        self.transport = None
        self.shell = None

    def connect(self, config):
        if not HAS_PARAMIKO:
            return False
            
        self.host = config.get('host', '')
        self.port = config.get('port', 22)
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        
        result = [False]
        error_msg = [None]
        
        def connect_task():
            try:
                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # 尝试连接
                self.client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=10,
                    allow_agent=False,
                    look_for_keys=False
                )
                
                # 开启transport
                self.transport = self.client.get_transport()
                if self.transport:
                    self.transport.open_channel("session")
                    self.shell = self.transport.open_session()
                    self.shell.get_pty(width=80, height=24)
                    self.shell.invoke_shell()
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
            print(f"SSH连接错误: {error_msg[0]}")
            
        return result[0]

    def disconnect(self):
        self.connected = False
        try:
            if self.shell:
                self.shell.close()
            if self.client:
                self.client.close()
        except:
            pass
        self.shell = None
        self.client = None

    def send_command(self, command):
        if not self.connected or not self.shell:
            return "[错误: 未连接]\n"
        
        try:
            # 发送命令
            self.shell.send(command + "\n")
            
            # 等待数据准备好
            time.sleep(0.3)
            
            # 读取响应
            response = ""
            while self.shell.recv_ready():
                data = self.shell.recv(4096).decode('utf-8', errors='replace')
                response += data
                time.sleep(0.1)
            
            return response if response else ""
        except Exception as e:
            return f"[错误: {str(e)}]\n"

    def send_raw(self, data):
        """发送原始数据到shell（用于交互式终端）"""
        if self.connected and self.shell:
            try:
                self.shell.send(data)
            except:
                pass

    def read_output(self, timeout=0.1):
        """读取远程输出（非阻塞）"""
        if not self.connected or not self.shell:
            return ""
        
        response = ""
        try:
            while self.shell.recv_ready():
                data = self.shell.recv(4096).decode('utf-8', errors='replace')
                response += data
        except:
            pass
        return response

    def is_connected(self):
        if self.connected and self.transport and self.transport.is_active():
            return True
        self.connected = False
        return False

    def get_name(self):
        return "SSH"


class TelnetStrategy(ConnectionStrategy):
    """Telnet连接策略"""

    def __init__(self):
        self.connected = False
        self.host = ""
        self.port = 23
        self.username = ""
        self.password = ""
        self.tn = None

    def connect(self, config):
        if not HAS_TELNETLIB:
            return False
            
        self.host = config.get('host', '')
        self.port = config.get('port', 23)
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        
        result = [False]
        error_msg = [None]
        
        def connect_task():
            try:
                self.tn = telnetlib.Telnet(self.host, self.port, timeout=10)
                
                # 等待登录提示
                time.sleep(1)
                
                # 发送用户名
                if self.username:
                    self.tn.write(self.username.encode('utf-8') + b"\n")
                    time.sleep(0.5)
                
                # 发送密码
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
        except:
            pass
        self.tn = None

    def send_command(self, command):
        if not self.connected or not self.tn:
            return "[错误: 未连接]\n"
        
        try:
            # 发送命令
            self.tn.write(command.encode('utf-8') + b"\n")
            
            # 等待响应
            time.sleep(0.5)
            
            # 读取响应
            response = self.tn.read_very_eager().decode('utf-8', errors='replace')
            return response
        except Exception as e:
            return f"[错误: {str(e)}]\n"

    def is_connected(self):
        return self.connected

    def get_name(self):
        return "Telnet"


class SerialStrategy(ConnectionStrategy):
    """串口连接策略"""

    def __init__(self):
        self.connected = False
        self.port = ""
        self.baud = 115200
        self.serial_conn = None
        self.read_thread = None
        self._running = False
        self._buffer = ""

    def connect(self, config):
        if not HAS_SERIAL:
            return False
            
        self.port = config.get('port', '')
        self.baud = int(config.get('baud', 115200))
        
        result = [False]
        error_msg = [None]
        
        def connect_task():
            try:
                self.serial_conn = serial.Serial(
                    port=self.port,
                    baudrate=self.baud,
                    timeout=1,
                    write_timeout=1
                )
                self._running = True
                self.connected = True
                result[0] = True
                
                # 启动读取线程
                self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
                self.read_thread.start()
            except Exception as e:
                error_msg[0] = str(e)
                result[0] = False
        
        thread = threading.Thread(target=connect_task)
        thread.daemon = True
        thread.start()
        thread.join(timeout=5)
        
        if not result[0] and error_msg[0]:
            print(f"串口连接错误: {error_msg[0]}")
            
        return result[0]

    def _read_loop(self):
        """后台读取串口数据"""
        while self._running and self.serial_conn:
            try:
                if self.serial_conn.in_waiting > 0:
                    data = self.serial_conn.read(self.serial_conn.in_waiting)
                    self._buffer += data.decode('utf-8', errors='replace')
            except:
                break

    def disconnect(self):
        self._running = False
        self.connected = False
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
        except:
            pass
        self.serial_conn = None

    def send_command(self, command):
        if not self.connected or not self.serial_conn:
            return "[错误: 未连接]\n"
        
        try:
            # 发送命令
            self.serial_conn.write(command.encode('utf-8') + b"\r\n")
            
            # 等待响应
            time.sleep(0.3)
            
            # 读取缓冲区数据
            response = self._buffer
            self._buffer = ""
            return response if response else ""
        except Exception as e:
            return f"[错误: {str(e)}]\n"

    def is_connected(self):
        if self.connected and self.serial_conn and self.serial_conn.is_open:
            return True
        self.connected = False
        return False

    def get_name(self):
        return "Serial"


class ConnectionContext:
    """连接上下文，管理策略切换"""

    def __init__(self, strategy=None):
        self._strategy = strategy

    def set_strategy(self, strategy):
        """设置连接策略"""
        if self._strategy and self._strategy.is_connected():
            self._strategy.disconnect()
        self._strategy = strategy

    def connect(self, config):
        """使用当前策略建立连接"""
        if self._strategy:
            return self._strategy.connect(config)
        return False

    def disconnect(self):
        """断开连接"""
        if self._strategy:
            self._strategy.disconnect()

    def send_command(self, command):
        """发送命令"""
        if self._strategy:
            return self._strategy.send_command(command)
        return "[错误: 未设置连接策略]\n"

    def is_connected(self):
        """检查连接状态"""
        return self._strategy.is_connected() if self._strategy else False

    def get_strategy_name(self):
        """获取当前策略名称"""
        return self._strategy.get_name() if self._strategy else "Unknown"
