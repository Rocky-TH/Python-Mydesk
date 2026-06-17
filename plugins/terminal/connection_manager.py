import uuid
from datetime import datetime
from typing import List, Dict, Optional


class ConnectionManager:
    """会话连接管理器，管理 SSH/Telnet/Serial 连接配置的增删改查"""
    
    def __init__(self, config_manager=None):
        self._config_manager = config_manager
        self._connections: List[Dict] = []
        self._data_key = "connections"
        self._plugin_name = "Terminal"
        self.load()

    def load(self) -> bool:
        """加载连接配置"""
        if self._config_manager:
            data = self._config_manager.get_plugin_data(self._plugin_name, self._data_key)
            if data:
                self._connections = data if isinstance(data, list) else []
                return True
        self._connections = []
        return False

    def save(self) -> bool:
        """保存连接配置"""
        if self._config_manager:
            self._config_manager.set_plugin_data(self._plugin_name, self._data_key, self._connections)
            return self._config_manager.save_plugin_data(self._plugin_name, self._data_key)
        return False

    def get_connections(self) -> List[Dict]:
        """获取所有连接"""
        return self._connections

    def get_connection(self, conn_id: str) -> Optional[Dict]:
        """根据ID获取连接"""
        for conn in self._connections:
            if conn.get('id') == conn_id:
                return conn
        return None

    def add_connection(self, connection: Dict) -> bool:
        """添加新连接"""
        # 生成唯一ID
        import uuid
        connection['id'] = str(uuid.uuid4())[:8]
        connection['created_at'] = connection.get('created_at') or self._get_timestamp()
        self._connections.append(connection)
        return self.save()

    def update_connection(self, conn_id: str, updates: Dict) -> bool:
        """更新连接配置"""
        for conn in self._connections:
            if conn.get('id') == conn_id:
                conn.update(updates)
                conn['updated_at'] = self._get_timestamp()
                return self.save()
        return False

    def delete_connection(self, conn_id: str) -> bool:
        """删除连接"""
        for i, conn in enumerate(self._connections):
            if conn.get('id') == conn_id:
                self._connections.pop(i)
                return self.save()
        return False

    def filter_by_type(self, conn_type: str) -> List[Dict]:
        """按类型筛选连接"""
        return [conn for conn in self._connections if conn.get('type') == conn_type]

    def _get_timestamp(self) -> str:
        """获取当前时间戳字符串"""
        from datetime import datetime
        return datetime.now().isoformat()

    def create_connection(self, name: str, conn_type: str, config: Dict) -> bool:
        """创建新连接"""
        connection = {
            'name': name,
            'type': conn_type,
            'config': config,
            'created_at': self._get_timestamp(),
            'updated_at': self._get_timestamp()
        }
        return self.add_connection(connection)