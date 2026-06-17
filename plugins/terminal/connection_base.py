class ConnectionBase:
    """连接基类，提供公共属性和方法"""

    def __init__(self):
        self.connected = False
        self.host = ""
        self.port = 0
        self.username = ""
        self.password = ""

    def _get_timestamp(self):
        """获取当前时间戳字符串"""
        from datetime import datetime
        return datetime.now().isoformat()
