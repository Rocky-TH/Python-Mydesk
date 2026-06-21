import threading
import time
import json
import re

from plugins.terminal.connection_factory import ConnectionFactory


class RemoteCmdPlugin:
    """远程命令执行插件 - 无UI，用于远程连接设备执行命令并解析结果"""

    def __init__(self, config, config_manager=None):
        self.config = config
        self._config_manager = config_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None
        self._connections = {}
        self._results = {}
        self._lock = threading.Lock()

    def get_widget(self):
        """此插件无UI，返回None"""
        return None

    def activate(self):
        """插件激活时初始化"""
        print(f"RemoteCmdPlugin activated: {self.name}")

    def deactivate(self):
        """插件停用，断开所有连接"""
        self.disconnect_all()
        print(f"RemoteCmdPlugin deactivated: {self.name}")

    def get_compile_environments(self):
        """获取编译环境配置（包含远程连接信息）"""
        if self._config_manager:
            plugin_config = self._config_manager.get_plugin_config("QuicklyCmd")
            if plugin_config and 'compile' in plugin_config:
                return plugin_config['compile'].get('compile_environments', [])
        return []

    def connect(self, env_name, timeout=15):
        """根据编译环境名称连接设备
        
        Args:
            env_name: 编译环境名称（对应配置中的name字段）
            timeout: 连接超时时间（秒）
            
        Returns:
            (bool, str): (是否成功, 错误信息或连接信息)
        """
        environments = self.get_compile_environments()
        
        for env in environments:
            if env['name'] == env_name:
                conn_config = env.get('connection')
                if not conn_config:
                    return (False, f"环境 {env_name} 没有配置连接信息")
                
                return self._connect_with_config(conn_config, timeout)
        
        return (False, f"未找到编译环境: {env_name}")

    def _connect_with_config(self, conn_config, timeout=15):
        """使用连接配置创建连接"""
        conn_type = conn_config.get('type')
        
        if not conn_type:
            return (False, "连接配置中缺少 type 字段")
        
        conn = ConnectionFactory.create_connection(conn_type)
        if not conn:
            return (False, f"不支持的连接类型: {conn_type}")
        
        # 提取配置
        config = {}
        if conn_type == 'ssh':
            config['host'] = conn_config.get('host', '')
            config['port'] = conn_config.get('port', 22)
            config['username'] = conn_config.get('username', '')
            config['password'] = conn_config.get('password', '')
            config['key_file'] = conn_config.get('key_file', '')
        elif conn_type == 'serial':
            config['port'] = conn_config.get('port', '')
            config['baud'] = conn_config.get('baud', 115200)
            config['bytesize'] = conn_config.get('bytesize', 8)
            config['parity'] = conn_config.get('parity', 'N')
            config['stopbits'] = conn_config.get('stopbits', 1)
        elif conn_type == 'telnet':
            config['host'] = conn_config.get('host', '')
            config['port'] = conn_config.get('port', 23)
            config['username'] = conn_config.get('username', '')
            config['password'] = conn_config.get('password', '')
        else:
            return (False, f"不支持的连接类型: {conn_type}")
        
        # 连接
        result = conn.connect(config)
        
        if result:
            conn_id = f"{conn_type}_{config.get('host', config.get('port', ''))}"
            with self._lock:
                self._connections[conn_id] = conn
            return (True, f"连接成功 [{conn.get_name()}]: {conn_id}")
        else:
            return (False, f"连接失败")

    def disconnect(self, env_name):
        """断开指定环境的连接"""
        environments = self.get_compile_environments()
        
        for env in environments:
            if env['name'] == env_name:
                conn_config = env.get('connection')
                if conn_config:
                    conn_type = conn_config.get('type')
                    conn_id = f"{conn_type}_{conn_config.get('host', conn_config.get('port', ''))}"
                    with self._lock:
                        if conn_id in self._connections:
                            self._connections[conn_id].disconnect()
                            del self._connections[conn_id]
                            return True
        return False

    def disconnect_all(self):
        """断开所有连接"""
        with self._lock:
            for conn_id, conn in self._connections.items():
                try:
                    conn.disconnect()
                except:
                    pass
            self._connections.clear()

    def execute_command(self, env_name, commands, timeout=30):
        """在指定环境上执行命令
        
        Args:
            env_name: 编译环境名称
            commands: 命令列表或单个命令字符串
            timeout: 执行超时时间（秒）
            
        Returns:
            dict: 执行结果
                {
                    'success': bool,
                    'env_name': str,
                    'commands': list,
                    'results': list,
                    'error': str
                }
        """
        result = {
            'success': False,
            'env_name': env_name,
            'commands': [],
            'results': [],
            'error': ''
        }
        
        # 获取连接
        environments = self.get_compile_environments()
        conn = None
        conn_config = None
        
        for env in environments:
            if env['name'] == env_name:
                conn_config = env.get('connection')
                if not conn_config:
                    result['error'] = f"环境 {env_name} 没有配置连接信息"
                    return result
                
                conn_type = conn_config.get('type')
                conn_id = f"{conn_type}_{conn_config.get('host', conn_config.get('port', ''))}"
                
                with self._lock:
                    conn = self._connections.get(conn_id)
                
                if not conn:
                    # 尝试自动连接
                    success, msg = self.connect(env_name, timeout=15)
                    if not success:
                        result['error'] = msg
                        return result
                    with self._lock:
                        conn = self._connections.get(conn_id)
        
        if not conn:
            result['error'] = f"未找到连接: {env_name}"
            return result
        
        # 确保连接状态
        if not conn.is_connected():
            result['error'] = "连接已断开"
            return result
        
        # 处理命令
        if isinstance(commands, str):
            commands = [commands]
        
        result['commands'] = commands
        
        # 执行命令
        for cmd in commands:
            try:
                output = conn.send_command(cmd, timeout=timeout / len(commands))
                parsed = self.parse_output(output)
                result['results'].append({
                    'command': cmd,
                    'output': output,
                    'parsed': parsed
                })
            except Exception as e:
                result['error'] = str(e)
                result['results'].append({
                    'command': cmd,
                    'output': '',
                    'parsed': {'error': str(e)},
                    'exception': str(e)
                })
        
        result['success'] = not result['error']
        
        with self._lock:
            self._results[env_name] = result
        
        return result

    def parse_output(self, output):
        """解析命令输出，提取关键字段
        
        Args:
            output: 原始输出字符串
            
        Returns:
            dict: 解析后的结果
        """
        if not output:
            return {'raw': '', 'lines': [], 'parsed': {}}
        
        result = {
            'raw': output,
            'lines': [],
            'parsed': {}
        }
        
        # 分割行
        lines = output.strip().split('\n')
        result['lines'] = lines
        
        # 尝试解析常见格式
        for line in lines:
            line = line.strip()
            
            # 键值对格式: key=value 或 key: value
            key_value_match = re.match(r'^(\w[\w\s-]*[\w]):\s*(.+)$', line)
            if key_value_match:
                key = key_value_match.group(1).strip().lower().replace(' ', '_')
                value = key_value_match.group(2).strip()
                result['parsed'][key] = value
                continue
            
            # 等号格式: key=value
            eq_match = re.match(r'^(\w[\w-]*)\s*=\s*(.+)$', line)
            if eq_match:
                key = eq_match.group(1).strip().lower()
                value = eq_match.group(2).strip()
                result['parsed'][key] = value
                continue
            
            # 数字格式: 尝试提取数字
            num_match = re.search(r'(\d+\.?\d*)', line)
            if num_match:
                try:
                    num_value = float(num_match.group(1))
                    if num_value.is_integer():
                        num_value = int(num_value)
                    # 使用行开头作为键
                    key_start = re.match(r'^([\w\s-]{1,20})', line)
                    if key_start:
                        key = key_start.group(1).strip().lower().replace(' ', '_')
                        result['parsed'][key] = num_value
                except:
                    pass
        
        return result

    def execute_commands_on_all(self, commands, timeout=30):
        """在所有配置了连接的环境上执行命令
        
        Args:
            commands: 命令列表或单个命令字符串
            timeout: 每个环境的执行超时时间
            
        Returns:
            dict: 所有环境的执行结果
        """
        results = {}
        environments = self.get_compile_environments()
        
        for env in environments:
            conn_config = env.get('connection')
            if conn_config:
                env_name = env['name']
                results[env_name] = self.execute_command(env_name, commands, timeout)
        
        return results

    def get_result(self, env_name):
        """获取指定环境的执行结果"""
        with self._lock:
            return self._results.get(env_name, None)

    def get_all_results(self):
        """获取所有环境的执行结果"""
        with self._lock:
            return dict(self._results)

    def is_connected(self, env_name):
        """检查指定环境是否已连接"""
        environments = self.get_compile_environments()
        
        for env in environments:
            if env['name'] == env_name:
                conn_config = env.get('connection')
                if conn_config:
                    conn_type = conn_config.get('type')
                    conn_id = f"{conn_type}_{conn_config.get('host', conn_config.get('port', ''))}"
                    with self._lock:
                        if conn_id in self._connections:
                            return self._connections[conn_id].is_connected()
        return False

    def get_connected_environments(self):
        """获取所有已连接的环境名称"""
        connected = []
        environments = self.get_compile_environments()
        
        for env in environments:
            if self.is_connected(env['name']):
                connected.append(env['name'])
        
        return connected

    def execute_with_retry(self, env_name, commands, max_retries=3, timeout=30):
        """带重试的命令执行
        
        Args:
            env_name: 环境名称
            commands: 命令列表
            max_retries: 最大重试次数
            timeout: 单次执行超时时间
            
        Returns:
            dict: 执行结果
        """
        last_error = ""
        
        for attempt in range(max_retries):
            result = self.execute_command(env_name, commands, timeout)
            if result['success']:
                result['retry_attempts'] = attempt + 1
                return result
            last_error = result.get('error', '未知错误')
            time.sleep(2)
        
        return {
            'success': False,
            'env_name': env_name,
            'commands': commands,
            'results': [],
            'error': f"重试 {max_retries} 次后仍失败: {last_error}",
            'retry_attempts': max_retries
        }

    def run_shell_script(self, env_name, script_content, timeout=60):
        """在远程设备上执行shell脚本内容
        
        Args:
            env_name: 环境名称
            script_content: shell脚本内容（多行字符串）
            timeout: 执行超时时间
            
        Returns:
            dict: 执行结果
        """
        # 将脚本内容转换为命令列表
        commands = []
        for line in script_content.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                commands.append(line)
        
        return self.execute_command(env_name, commands, timeout)

    def send_raw_data(self, env_name, data):
        """发送原始数据到指定环境
        
        Args:
            env_name: 环境名称
            data: 要发送的原始数据
            
        Returns:
            bool: 是否成功
        """
        environments = self.get_compile_environments()
        
        for env in environments:
            if env['name'] == env_name:
                conn_config = env.get('connection')
                if conn_config:
                    conn_type = conn_config.get('type')
                    conn_id = f"{conn_type}_{conn_config.get('host', conn_config.get('port', ''))}"
                    with self._lock:
                        conn = self._connections.get(conn_id)
                    if conn and conn.is_connected():
                        conn.send_raw(data)
                        return True
        return False

    def read_output(self, env_name, timeout=0.1):
        """读取指定环境的输出（非阻塞）
        
        Args:
            env_name: 环境名称
            timeout: 读取超时时间
            
        Returns:
            str: 读取到的数据
        """
        environments = self.get_compile_environments()
        
        for env in environments:
            if env['name'] == env_name:
                conn_config = env.get('connection')
                if conn_config:
                    conn_type = conn_config.get('type')
                    conn_id = f"{conn_type}_{conn_config.get('host', conn_config.get('port', ''))}"
                    with self._lock:
                        conn = self._connections.get(conn_id)
                    if conn and conn.is_connected():
                        return conn.read_output(timeout)
        return ""
