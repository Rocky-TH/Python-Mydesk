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
        self.bytesize = 8
        self.parity = 'N'
        self.stopbits = 1
        self.serial_conn = None
        self.read_thread = None
        self._running = False
        self._lock = threading.Lock()

    def connect(self, config):
        if not HAS_SERIAL:
            return False
            
        self.port = config.get('port', '')
        self.baud = int(config.get('baud', 115200))
        self.bytesize = config.get('bytesize', 8)
        self.parity = config.get('parity', 'N')
        self.stopbits = config.get('stopbits', 1)
        
        result = [False]
        error_msg = [None]
        
        def connect_task():
            try:
                parity_map = {'N': serial.PARITY_NONE, 'E': serial.PARITY_EVEN, 'O': serial.PARITY_ODD}
                stopbits_map = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}
                
                self.serial_conn = serial.Serial(
                    port=self.port,
                    baudrate=self.baud,
                    bytesize=self.bytesize,
                    parity=parity_map.get(self.parity, serial.PARITY_NONE),
                    stopbits=stopbits_map.get(self.stopbits, serial.STOPBITS_ONE),
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
        """后台读取串口数据到缓冲区"""
        while self._running and self.serial_conn:
            try:
                if self.serial_conn.in_waiting > 0:
                    data = self.serial_conn.read(self.serial_conn.in_waiting)
                    decoded = data.decode('utf-8', errors='replace')
                    with self._lock:
                        self._buffer += decoded
                time.sleep(0.01)  # 减少CPU占用
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

    def send_command(self, command, timeout=1.0):
        """发送命令并等待响应"""
        if not self.connected or not self.serial_conn:
            return "[错误: 未连接]\n"
        
        try:
            with self._lock:
                self._buffer = ""  # 清空缓冲区
                
            self.serial_conn.write(command.encode('utf-8') + b"\r\n")
            
            # 等待响应
            time.sleep(timeout)
            
            with self._lock:
                response = self._buffer
                self._buffer = ""
            
            return response if response else ""
        except Exception as e:
            return f"[错误: {str(e)}]\n"

    def send_raw(self, data):
        """发送原始数据到串口"""
        if self.connected and self.serial_conn:
            try:
                if isinstance(data, str):
                    self.serial_conn.write(data.encode('utf-8'))
                else:
                    self.serial_conn.write(data)
            except:
                pass

    def read_output(self, timeout=0.1):
        """读取串口缓冲区数据（非阻塞）"""
        if not self.connected:
            return ""
        
        with self._lock:
            if self._buffer:
                data = self._buffer
                self._buffer = ""
                return data
        
        # 短暂等待更多数据
        time.sleep(timeout)
        
        with self._lock:
            data = self._buffer
            self._buffer = ""
            return data

    def is_connected(self):
        if self.connected and self.serial_conn and self.serial_conn.is_open:
            return True
        self.connected = False
        return False

    def get_name(self):
        return "Serial"

    def get_info(self):
        """获取串口连接信息"""
        info = super().get_info()
        info.update({
            "baud": self.baud,
            "bytesize": self.bytesize,
            "parity": self.parity,
            "stopbits": self.stopbits
        })
        return info

    @staticmethod
    def list_ports():
        """列出所有可用的串口"""
        if not HAS_SERIAL:
            return []
        ports = []
        for port in serial.tools.list_ports.comports():
            ports.append({
                "name": port.device,
                "description": port.description,
                "hwid": port.hwid
            })
        return ports
