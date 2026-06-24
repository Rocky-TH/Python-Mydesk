# 检查服务器状态
import json

log('检查服务器状态...')
output = session.send_cmd('uptime')
log(f'服务器运行时间: {output}')

mem_output = session.send_cmd('free -h')
log(f'内存使用: {mem_output}')

session.set_result('status', 'ok')
session.set_result('uptime', output)
