from abc import ABC, abstractmethod


class ConnectionStrategy(ABC):
    """连接策略接口"""

    @abstractmethod
    def connect(self, config):
        """建立连接"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def send_command(self, command):
        """发送命令"""
        pass

    @abstractmethod
    def is_connected(self):
        """检查是否已连接"""
        pass

    @abstractmethod
    def get_name(self):
        """获取策略名称"""
        pass