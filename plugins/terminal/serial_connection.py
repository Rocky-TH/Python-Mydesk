import threading
import time

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from .connection_base import ConnectionBase


class SerialConnection(ConnectionBase):
    """串口连接策略"""

    def __init__(self):
        super().__init__()
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
            self.serial_conn.write(command.encode('utf-8') + b"\r\n")
            time.sleep(0.3)
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
