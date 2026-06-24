import time
import json
import re
import io
import ast
import threading
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime


class CommandLog:
    """命令日志记录器"""
    
    def __init__(self):
        self._logs = []
        self._lock = threading.Lock()
    
    def add(self, command, response, success=True, duration=0):
        """添加命令日志
        
        Args:
            command: 发送的命令
            response: 接收的响应
            success: 是否成功
            duration: 执行时长（秒）
        """
        with self._lock:
            self._logs.append({
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'command': command,
                'response': response,
                'success': success,
                'duration': duration
            })
    
    def get_all(self):
        """获取所有日志"""
        with self._lock:
            return list(self._logs)
    
    def get_last(self, n=10):
        """获取最近n条日志"""
        with self._lock:
            return self._logs[-n:] if self._logs else []
    
    def clear(self):
        """清空日志"""
        with self._lock:
            self._logs.clear()
    
    def to_string(self):
        """转换为字符串格式"""
        with self._lock:
            lines = []
            for log in self._logs:
                status = "成功" if log['success'] else "失败"
                lines.append(f"[{log['time']}] [{status}] 命令: {log['command']}")
                if log['response']:
                    lines.append(f"  响应: {log['response'][:200]}...")
                lines.append(f"  耗时: {log['duration']:.2f}s")
            return "\n".join(lines)


class Session:
    """会话对象 - 提供给脚本使用的API接口"""
    
    def __init__(self, connection, env_name, env_config):
        self._conn = connection
        self._env_name = env_name
        self._env_config = env_config
        self._result = None
        self._command_log = CommandLog()
        self._last_response = ""
    
    @property
    def env_name(self):
        """获取环境名称"""
        return self._env_name
    
    @property
    def env_config(self):
        """获取环境配置"""
        return self._env_config.copy()
    
    @property
    def connected(self):
        """检查是否已连接"""
        return self._conn and self._conn.is_connected()
    
    @property
    def last_response(self):
        """获取最后一次响应"""
        return self._last_response
    
    @property
    def command_log(self):
        """获取命令日志记录器"""
        return self._command_log
    
    def send(self, data):
        """发送原始数据
        
        Args:
            data: 要发送的原始数据
            
        Returns:
            bool: 是否成功
        """
        if self._conn:
            self._conn.send_raw(data)
            self._command_log.add(data, "", success=True)
            return True
        self._command_log.add(data, "", success=False)
        return False
    
    def recv(self, timeout=0.1):
        """接收响应数据
        
        Args:
            timeout: 读取超时时间（秒）
            
        Returns:
            str: 接收到的数据
        """
        if self._conn:
            data = self._conn.read_output(timeout)
            self._last_response = data
            return data
        return ""
    
    def send_cmd(self, command, timeout=5.0):
        """发送命令并获取响应
        
        Args:
            command: 要发送的命令
            timeout: 等待响应的超时时间
            
        Returns:
            str: 命令执行结果
        """
        start_time = time.time()
        if self._conn:
            response = self._conn.send_command(command, timeout)
            duration = time.time() - start_time
            self._last_response = response
            self._command_log.add(command, response, success=True, duration=duration)
            return response
        
        duration = time.time() - start_time
        self._command_log.add(command, "", success=False, duration=duration)
        return ""
    
    def recv_cmd(self, timeout=0.1):
        """接收响应数据（recv的别名）
        
        Args:
            timeout: 读取超时时间
            
        Returns:
            str: 接收到的数据
        """
        return self.recv(timeout)
    
    def send_line(self, line):
        """发送一行数据（自动添加换行符）
        
        Args:
            line: 要发送的行
        """
        self.send(line + "\n")
    
    def read_all(self, timeout=0.5):
        """读取所有可用数据
        
        Args:
            timeout: 读取超时时间
            
        Returns:
            str: 所有读取到的数据
        """
        if self._conn and hasattr(self._conn, 'read_all'):
            data = self._conn.read_all(timeout)
            self._last_response = data
            return data
        
        result = ""
        end_time = time.time() + timeout
        while time.time() < end_time:
            data = self.recv(0.05)
            if data:
                result += data
        self._last_response = result
        return result
    
    def expect(self, patterns, timeout=5.0):
        """等待匹配指定模式之一
        
        Args:
            patterns: 要匹配的模式列表（可以是字符串或正则表达式）
            timeout: 超时时间
            
        Returns:
            tuple: (matched_index, matched_text, before_text, full_buffer)
        """
        buffer = ""
        end_time = time.time() + timeout
        
        while time.time() < end_time:
            data = self.recv(0.1)
            if data:
                buffer += data
                for i, pattern in enumerate(patterns):
                    if isinstance(pattern, str):
                        if pattern in buffer:
                            self._last_response = buffer
                            return (i, pattern, buffer[:buffer.find(pattern)], buffer)
                    else:
                        match = pattern.search(buffer)
                        if match:
                            self._last_response = buffer
                            return (i, match.group(), buffer[:match.start()], buffer)
        
        self._last_response = buffer
        return (-1, "", buffer, buffer)
    
    def contains(self, text, response=None):
        """判断响应中是否存在预期内容
        
        Args:
            text: 要查找的文本
            response: 要检查的响应，如果为None则使用最后一次响应
            
        Returns:
            bool: 是否包含指定文本
        """
        check_text = response if response is not None else self._last_response
        return text in check_text
    
    def contains_pattern(self, pattern, response=None):
        """判断响应中是否存在匹配正则表达式的内容
        
        Args:
            pattern: 正则表达式（字符串或re.Pattern对象）
            response: 要检查的响应，如果为None则使用最后一次响应
            
        Returns:
            bool: 是否匹配
        """
        check_text = response if response is not None else self._last_response
        if isinstance(pattern, str):
            return bool(re.search(pattern, check_text))
        return bool(pattern.search(check_text))
    
    def wait_for(self, text, timeout=5.0):
        """等待响应中出现指定文本
        
        Args:
            text: 要等待的文本
            timeout: 超时时间
            
        Returns:
            bool: 是否在超时前找到
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.contains(text):
                return True
            self.recv(0.1)
        return False
    
    def wait_for_pattern(self, pattern, timeout=5.0):
        """等待响应中出现匹配正则表达式的内容
        
        Args:
            pattern: 正则表达式
            timeout: 超时时间
            
        Returns:
            bool: 是否在超时前匹配
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.contains_pattern(pattern):
                return True
            self.recv(0.1)
        return False
    
    def log(self, message, level='INFO'):
        """输出日志
        
        Args:
            message: 日志消息
            level: 日志级别 (INFO, DEBUG, ERROR, WARNING)
        """
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] [{level}] [{self._env_name}] {message}")
    
    def log_debug(self, message):
        """输出调试日志"""
        self.log(message, 'DEBUG')
    
    def log_error(self, message):
        """输出错误日志"""
        self.log(message, 'ERROR')
    
    def log_warning(self, message):
        """输出警告日志"""
        self.log(message, 'WARNING')
    
    def set_result(self, key, value):
        """设置脚本执行结果，供后续使用
        
        Args:
            key: 结果键名
            value: 结果值
        """
        if self._result is None:
            self._result = {}
        self._result[key] = value
    
    def get_result(self, key=None):
        """获取脚本执行结果
        
        Args:
            key: 结果键名，如果为None则返回所有结果
            
        Returns:
            结果值或所有结果字典
        """
        if key is None:
            return self._result
        if self._result:
            return self._result.get(key)
        return None
    
    def clear_result(self):
        """清空结果"""
        self._result = None
    
    def get_command_history(self, n=10):
        """获取命令历史
        
        Args:
            n: 获取最近n条
            
        Returns:
            list: 命令历史列表
        """
        return self._command_log.get_last(n)
    
    def print_command_history(self):
        """打印命令历史"""
        print(self._command_log.to_string())
    
    @property
    def connection_info(self):
        """获取连接信息"""
        if self._conn and hasattr(self._conn, 'get_info'):
            return self._conn.get_info()
        return {}
    
    def disconnect(self):
        """断开连接"""
        if self._conn and hasattr(self._conn, 'disconnect'):
            self._conn.disconnect()
    
    def reconnect(self, timeout=10):
        """重新连接
        
        Args:
            timeout: 连接超时时间
            
        Returns:
            tuple: (success, message)
        """
        if self._conn and hasattr(self._conn, 'reconnect'):
            return self._conn.reconnect(timeout)
        return (False, "不支持重连")


class ScriptRunner:
    """Python脚本执行器"""
    
    def __init__(self, globals_dict=None):
        self._globals = globals_dict or {}
        self._output_buffer = io.StringIO()
    
    def execute(self, script_content, session):
        """执行Python脚本
        
        Args:
            script_content: Python脚本内容
            session: Session对象
            
        Returns:
            dict: 执行结果 {
                'success': bool,
                'output': str,
                'error': str,
                'result': any,
                'session_result': dict,
                'command_log': list
            }
        """
        result = {
            'success': False,
            'output': '',
            'error': '',
            'result': None,
            'session_result': None,
            'command_log': []
        }
        
        exec_globals = {
            '__name__': '__script__',
            'session': session,
            'log': session.log,
            'log_debug': session.log_debug,
            'log_error': session.log_error,
            'log_warning': session.log_warning,
            'time': time,
            'json': json,
            're': re,
        }
        exec_globals.update(self._globals)
        
        exec_locals = {}
        output_buffer = io.StringIO()
        
        try:
            with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                exec(script_content, exec_globals, exec_locals)
            
            result['success'] = True
            result['output'] = output_buffer.getvalue()
            result['session_result'] = session.get_result()
            result['command_log'] = session.get_command_history()
            
            if '__result__' in exec_locals:
                result['result'] = exec_locals['__result__']
            elif exec_locals:
                result['result'] = list(exec_locals.values())[-1] if exec_locals else None
                
        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
            result['output'] = output_buffer.getvalue()
            result['command_log'] = session.get_command_history()
        
        return result
    
    @staticmethod
    def validate(script_content):
        """验证Python脚本语法
        
        Args:
            script_content: Python脚本内容
            
        Returns:
            dict: 验证结果 {
                'valid': bool,
                'error': str,
                'line': int,
                'column': int
            }
        """
        result = {
            'valid': False,
            'error': '',
            'line': 0,
            'column': 0
        }
        
        try:
            ast.parse(script_content)
            result['valid'] = True
        except SyntaxError as e:
            result['error'] = str(e)
            result['line'] = e.lineno or 0
            result['column'] = e.offset or 0
        except Exception as e:
            result['error'] = str(e)
        
        return result