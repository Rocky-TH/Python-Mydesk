import threading
import time

try:
    import telnetlib
    HAS_TELNETLIB = True
except ImportError:
    HAS_TELNETLIB = False

from .connection_base import ConnectionBase


class TelnetConnection(ConnectionBase):
    """Telnet连接策略"""

    def __init__(self):
        super().__init__()
        self.port = 23
        self.tn = None
        self._lock = threading.Lock()

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
        except:
            pass
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
            except:
                pass

    def read_output(self, timeout=0.1):
        """读取Telnet响应数据（非阻塞）"""
        if not self.connected or not self.tn:
            return ""
        
        try:
            # 使用 read_until 超时读取
            import socket
            self.tn.sock.setblocking(False)
            try:
                data = self.tn.read_very_eager()
                if data:
                    return data.decode('utf-8', errors='replace')
            except:
                pass
            self.tn.sock.setblocking(True)
            
            # 尝试非阻塞读取
            return self.tn.read_very_eager().decode('utf-8', errors='replace')
        except:
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
            except:
                break
        
        return (-1, "", buffer)
