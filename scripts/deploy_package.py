# 部署软件包
log('开始部署软件包...')

# 上传文件
session.send_line('scp package.tar.gz user@host:/tmp/')
output = session.recv(timeout=2)
log(f'上传结果: {output}')
