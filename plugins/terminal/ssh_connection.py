import os
import threading
import time

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

from .connection_base import ConnectionBase


class SSHConnection(ConnectionBase):
    """SSH连接策略"""

    def __init__(self):
        super().__init__()
        self.port = 22
        self.key_file = ""
        self.client = None
        self.transport = None
        self.shell = None

    def connect(self, config):
        if not HAS_PARAMIKO:
            return False
            
        self.host = config.get('host', '')
        self.port = config.get('port', 22)
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.key_file = config.get('key_file', '')
        
        result = [False]
        error_msg = [None]
        
        def connect_task():
            try:
                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                connect_args = {
                    'hostname': self.host,
                    'port': self.port,
                    'username': self.username,
                    'timeout': 10,
                    'allow_agent': False,
                    'look_for_keys': False
                }
                
                # 优先使用密钥文件登录
                if self.key_file and os.path.exists(self.key_file):
                    try:
                        pkey = paramiko.RSAKey.from_private_key_file(self.key_file)
                        connect_args['pkey'] = pkey
                    except Exception as e:
                        error_msg[0] = f"加载密钥失败: {str(e)}"
                        result[0] = False
                        return
                elif self.password:
                    connect_args['password'] = self.password
                else:
                    error_msg[0] = "请提供密码或密钥文件"
                    result[0] = False
                    return
                
                self.client.connect(**connect_args)
                
                self.transport = self.client.get_transport()
                if self.transport:
                    self.transport.open_channel("session")
                    self.shell = self.transport.open_session()
                    self.shell.get_pty(width=80, height=24)
                    self.shell.invoke_shell()
                    self.connected = True
                    result[0] = True
            except Exception as e:
                error_msg[0] = str(e)
                result[0] = False
        
        thread = threading.Thread(target=connect_task)
        thread.daemon = True
        thread.start()
        thread.join(timeout=15)
        
        if not result[0] and error_msg[0]:
            print(f"SSH连接错误: {error_msg[0]}")
            
        return result[0]

    def disconnect(self):
        self.connected = False
        try:
            if self.shell:
                self.shell.close()
            if self.client:
                self.client.close()
        except:
            pass
        self.shell = None
        self.client = None

    def send_command(self, command, timeout=5.0):
        """发送命令并等待响应
        
        Args:
            command: 要发送的命令
            timeout: 等待响应的超时时间（秒）
            
        Returns:
            str: 响应内容
        """
        if not self.connected or not self.shell:
            return "[错误: 未连接]\n"
        
        try:
            self.shell.send(command + "\n")
            
            # 使用timeout参数控制等待时间
            wait_time = min(timeout, 0.5)  # 初始等待时间
            time.sleep(wait_time)
            
            response = ""
            end_time = time.time() + timeout
            
            while time.time() < end_time:
                if self.shell.recv_ready():
                    data = self.shell.recv(4096).decode('utf-8', errors='replace')
                    response += data
                    time.sleep(0.1)
                else:
                    # 如果没有更多数据，稍微等待后退出
                    time.sleep(0.05)
                    if not self.shell.recv_ready():
                        break
            
            return response if response else ""
        except Exception as e:
            return f"[错误: {str(e)}]\n"

    def send_raw(self, data):
        """发送原始数据到shell（用于交互式终端）"""
        if self.connected and self.shell:
            try:
                # 确保数据被完整发送
                if isinstance(data, str):
                    data = data.encode('utf-8')
                self.shell.send(data)
            except Exception as e:
                print(f"发送数据失败: {e}")
                pass

    def read_output(self, timeout=0.05):
        """读取远程输出（非阻塞），优化性能"""
        if not self.connected or not self.shell:
            return ""

        response = ""
        try:
            # 使用更短的等待时间，提高响应速度
            start_time = time.time()
            
            # 读取所有可用数据，不阻塞
            while self.shell.recv_ready():
                data = self.shell.recv(8192).decode('utf-8', errors='replace')
                response += data
                
                # 避免无限循环，设置超时
                if time.time() - start_time > timeout:
                    break
                
                # 短暂等待更多数据
                time.sleep(0.01)
                
        except Exception as e:
            return ""
            
        return response

    def is_connected(self):
        if self.connected and self.transport and self.transport.is_active():
            return True
        self.connected = False
        return False

    def get_name(self):
        return "SSH"
