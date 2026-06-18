from .ssh_connection import SSHConnection
from .telnet_connection import TelnetConnection
from .serial_connection import SerialConnection


class ConnectionFactory:
    """连接工厂类，用于创建不同类型的连接"""

    _connection_classes = {
        'ssh': SSHConnection,
        'telnet': TelnetConnection,
        'serial': SerialConnection
    }

    @classmethod
    def create_connection(cls, conn_type: str):
        """
        创建指定类型的连接

        Args:
            conn_type: 连接类型 ('ssh', 'telnet', 'serial')

        Returns:
            连接实例，如果类型不支持则返回 None
        """
        connection_class = cls._connection_classes.get(conn_type.lower())
        if connection_class:
            return connection_class()
        return None

    @classmethod
    def get_supported_types(cls):
        """获取支持的连接类型列表"""
        return list(cls._connection_classes.keys())

    @classmethod
    def register_connection_type(cls, conn_type: str, connection_class):
        """
        注册新的连接类型

        Args:
            conn_type: 连接类型名称
            connection_class: 连接类
        """
        cls._connection_classes[conn_type.lower()] = connection_class