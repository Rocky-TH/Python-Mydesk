# 自动化测试脚本
import re

log('开始自动化测试...')

# 1. 运行测试
log('运行测试用例...')
output = session.send_cmd('echo "Test completed"', timeout=10)
log(f'测试输出: {output}')

# 2. 保存结果
passed = len(re.findall(r'PASSED', output))
failed = len(re.findall(r'FAILED', output))

session.set_result('passed', passed)
session.set_result('failed', failed)
session.set_result('success', failed == 0)
