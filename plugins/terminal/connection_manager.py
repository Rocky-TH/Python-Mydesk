import os
import json
from typing import List, Dict, Optional


class ConnectionManager:
    """会话连接管理器，管理 SSH/Telnet/Serial 连接配置的增删改查"""
    
    def __init__(self, config_path: str = None):
        self._config_path = config_path or self._get_default_path()
        self._connections: List[Dict] = []
        self.load()

    def _get_default_path(self) -> str:
        """获取默认连接配置文件路径"""
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "connections.json"
        )

    def load(self) -> bool:
        """加载连接配置"""
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._connections = json.load(f)
                return True
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载连接配置失败: {e}")
                self._connections = []
        return False

    def save(self) -> bool:
        """保存连接配置"""
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(self._connections, f, indent=4, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"保存连接配置失败: {e}")
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