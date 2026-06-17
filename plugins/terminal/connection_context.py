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
