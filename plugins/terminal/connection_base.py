from abc import ABC, abstractmethod
from datetime import datetime


class ConnectionBase(ABC):
    """连接基类，提供公共属性和接口定义"""

    def __init__(self):
        self.connected = False
        self.host = ""
        self.port = 0
        self.username = ""
        self.password = ""
        self._buffer = ""  # 通用缓冲区

    def _get_timestamp(self):
        """获取当前时间戳字符串"""
        return datetime.now().isoformat()

    @abstractmethod
    def connect(self, config):
        """连接服务器/设备，config 为配置字典"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def is_connected(self):
        """检查是否已连接"""
        pass

    @abstractmethod
    def get_name(self):
        """获取连接类型名称"""
        pass

    @abstractmethod
    def send_command(self, command, timeout=1.0):
        """发送命令并等待响应（同步方式）
        
        Args:
            command: 要发送的命令
            timeout: 等待响应的超时时间（秒）
            
        Returns:
            命令执行结果（字符串）
        """
        pass

    @abstractmethod
    def send_raw(self, data):
        """发送原始数据（用于交互式终端）
        
        Args:
            data: 要发送的原始数据
        """
        pass

    @abstractmethod
    def read_output(self, timeout=0.1):
        """读取远程输出（非阻塞）
        
        Args:
            timeout: 读取超时时间（秒）
            
        Returns:
            读取到的数据（字符串），无数据时返回空字符串
        """
        pass

    def send_cmd(self, command, timeout=1.0):
        """发送命令并获取响应（send_command 的别名）
        
        Args:
            command: 要发送的命令
            timeout: 等待响应的超时时间（秒）
            
        Returns:
            命令执行结果（字符串）
        """
        return self.send_command(command, timeout)

    def recv_cmd(self, timeout=0.1):
        """接收响应数据（read_output 的别名）
        
        Args:
            timeout: 读取超时时间（秒）
            
        Returns:
            接收到的数据（字符串）
        """
        return self.read_output(timeout)

    def expect(self, patterns, timeout=1.0):
        """等待匹配指定模式之一
        
        Args:
            patterns: 要匹配的模式列表（字符串或正则表达式）
            timeout: 超时时间（秒）
            
        Returns:
            (matched_index, matched_text, before_text)
            - matched_index: 匹配的模式索引，未匹配返回 -1
            - matched_text: 匹配的文本
            - before_text: 匹配前的所有文本
        """
        import time
        start_time = time.time()
        
        buffer = ""
        while time.time() - start_time < timeout:
            data = self.read_output(0.1)
            if data:
                buffer += data
                for i, pattern in enumerate(patterns):
                    if pattern in buffer:
                        return (i, pattern, buffer)
        
        return (-1, "", buffer)

    def write(self, data):
        """发送数据（send_raw 的别名）"""
        self.send_raw(data)

    def read(self, timeout=0.1):
        """读取数据（read_output 的别名）"""
        return self.read_output(timeout)

    def read_all(self, timeout=0.5):
        """读取所有可用数据直到超时
        
        Args:
            timeout: 读取超时时间（秒）
            
        Returns:
            所有读取到的数据
        """
        import time
        result = ""
        start_time = time.time()
        while time.time() - start_time < timeout:
            data = self.read_output(0.05)
            if data:
                result += data
            elif time.time() - start_time > 0.1:
                # 如果有一定间隔的数据流，等待一小段时间后退出
                time.sleep(0.05)
                if not self.read_output(0.05):
                    break
        return result

    def send_line(self, line):
        """发送一行数据（自动添加换行符）"""
        self.send_raw(line + "\n")

    def get_info(self):
        """获取连接信息"""
        return {
            "type": self.get_name(),
            "host": self.host,
            "port": self.port,
            "connected": self.connected
        }
