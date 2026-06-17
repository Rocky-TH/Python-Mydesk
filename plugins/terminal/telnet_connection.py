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

    def send_command(self, command):
        if not self.connected or not self.tn:
            return "[错误: 未连接]\n"
        
        try:
            self.tn.write(command.encode('utf-8') + b"\n")
            time.sleep(0.5)
            response = self.tn.read_very_eager().decode('utf-8', errors='replace')
            return response
        except Exception as e:
            return f"[错误: {str(e)}]\n"

    def is_connected(self):
        return self.connected

    def get_name(self):
        return "Telnet"
