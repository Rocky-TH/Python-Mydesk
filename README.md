# MyDesk · 工程师桌面工具箱

MyDesk 是一款基于 **Python + PyQt6** 的插件化桌面工具箱，面向嵌入式开发、设备调试、服务器运维等场景，把日常工作中高频使用的**远程终端、串口/网络协议调试、远程编译部署、自动化脚本、进制计算、日志调测**等工具整合到一个可换肤、可扩展的桌面应用中。

- 纯 Python 实现，跨平台界面框架（Windows / macOS / Linux）
- 插件化架构，每个工具独立目录，按需加载、互不影响
- JSON 驱动的深色 / 浅色主题，运行时一键切换
- 所有连接、配置自动持久化，重启不丢失

---

## 功能一览

### 🔌 终端（Terminal）

核心模块，一台机器上的所有远程/本地会话统一管理。

| 能力 | 说明 |
| --- | --- |
| 多协议连接 | 支持 **SSH / Telnet / 串口（Serial）**，基于 paramiko、pyserial |
| 多标签会话 | 多连接以标签页并行管理，支持拖拽排序、右键菜单（复制连接 / 重新连接 / 断开 / 关闭） |
| 快速连接栏 | 顶部直接填写参数一键连接，也可一键**保存**到连接列表，配置自动记忆 |
| 连接管理 | 连接配置增删改查、按名称排序、持久化到 `config/connections.json` |
| 全屏程序支持 | 自研 ANSI 渲染引擎，支持备用屏幕（`1049`）、行列定位、滚动区域、插删行，**可正常使用 vi/vim、top 等全屏程序** |
| ANSI 彩色 | 支持 256 色、加粗 / 下划线 / 反色等 SGR 属性，颜色可按主题映射，可一键开关 |
| 快捷键 | `Ctrl+Tab` / `Ctrl+Shift+Tab` 循环切换连接，`Ctrl+1~9` 直达指定连接，`Ctrl+Shift+D/R/K/W` 复制 / 重连 / 断开 / 关闭，`F5` 刷新列表 |
| 连接保活 | 保活间隔可配置（1 / 3 / 5 / 10 / 30 分钟，默认 5 分钟），修改即时应用到所有已连接会话，避免空闲被防火墙断开 |
| SFTP | 内置 SFTP 文件传输对话框，支持上传 / 下载，并可保存常用远程路径快捷入口 |
| 会话日志 | 可按连接开关终端输出日志，自动写入 `logs/terminal/` |
| 自定义命令按钮 | 可配置常用命令按钮，一键下发，减少重复输入 |
| 外观 | 8 档字体大小可调，深色 / 浅色主题完整适配，当前标签主色高亮指示 |

### 📡 协议测试（ProtocolTool）

面向嵌入式通信联调的收发调试工具。

- 三种链路：**串口、TCP 客户端、TCP 服务端**，QThread 异步收发不卡界面
- 发送 / 接收区分离，支持**十六进制 / 字符串**双向切换
- 内置 **CRC-16/MODBUS** 校验自动计算与追加
- 支持**定时循环发送**、收发日志记录
- 完整的 **Modbus RTU / TCP** 报文构造与解析，覆盖功能码：
  `0x01` 读线圈、`0x02` 读离散输入、`0x03` 读保持寄存器、`0x04` 读输入寄存器、
  `0x05` 写单线圈、`0x06` 写单寄存器、`0x0F` 写多线圈、`0x10` 写多寄存器
- 基于 XML 配置的 **Modbus 从站模拟器**，无真实设备也可调试主站程序

### 🔧 编译工具（CompileTool）

面向"本地编辑、远程编译"的研发流程。

- 管理多个**编译环境**（本地 / 远程服务器 / Docker）、**编译组件**与**测试环境**
- 界面一键开始编译、运行测试，输出实时回显
- 底层通过远程命令插件在目标环境执行编译 / 测试脚本
- 附带部署脚本示例，可将产物包上传到远程主机

### 📜 脚本管理（ScriptManager）

- 内置 Python 脚本编辑器，可维护脚本名称、ID、描述与内容
- 脚本运行在内置执行环境中，可直接对终端会话操作：
  `session.send_cmd()` / `session.send()` / `session.recv()` / `log()` / `session.set_result()`
- 适合沉淀设备初始化、批量配置、自动化巡检等重复性操作

### 🧮 计算工具（CalcTool）

- **标准模式 / 程序员模式**一键切换
- 支持 8 / 16 / 32 / 64 位位宽、有符号 / 无符号设置
- 二 / 十 / 十六进制实时换算与位运算
- 完整键盘映射，支持小键盘直接输入

### 🐚 远程命令（RemoteCmd）

- 无独立界面的基础服务插件，为编译工具、脚本管理提供统一远程执行入口
- 复用终端的 SSH / Telnet / 串口连接配置，按环境名称连接并批量执行命令

### 🩺 调测工具（DebugTool）

- 实时查看应用运行日志（数据来自全局 Logger 单例）
- 按 DEBUG / INFO / WARNING / ERROR / CRITICAL **级别过滤**、关键词搜索
- 自动刷新、一键清空、直接打开日志文件目录
- 不同级别彩色区分，问题定位一目了然

---

## 技术栈

| 分类 | 技术 |
| --- | --- |
| 语言 | Python 3.10+（开发环境 3.13） |
| GUI | PyQt6（QWidget / QTabWidget / QThread / 样式表 QSS） |
| SSH / SFTP | paramiko |
| 串口 | pyserial |
| 配置 | JSON（ConfigManager 统一读写 `config/` 目录） |
| 日志 | 自研 Logger 单例，按天滚动 `logs/mydesk_debug_YYYYMMDD.log` |
| 协议 | Modbus RTU/TCP（struct 打包，CRC16 校验，XML 寄存器配置） |

---

## 工程结构

```
MyDesk/
├── main.py                  # 应用入口：异常钩子、Qt 消息过滤、启动主窗口
├── requirements.txt         # 第三方依赖
├── core/                    # 框架核心
│   ├── main_window.py       # 主窗口、插件容器、主题切换、菜单构建
│   ├── plugin_manager.py    # 插件动态加载与生命周期管理
│   └── menu_registry.py     # 结构化菜单注册器（支持子菜单/互斥组/快捷键）
├── plugins/                 # 工具插件（每个目录一个独立插件）
│   ├── terminal/            # 终端：SSH/Telnet/串口、ANSI 渲染、SFTP
│   ├── protocol_tool/       # 协议测试：串口/TCP、Modbus RTU/TCP、从站模拟
│   ├── compile_tool/        # 编译工具：远程编译与测试
│   ├── script_manager/      # 脚本管理与执行
│   ├── calc_tool/           # 标准/程序员计算器
│   ├── remote_cmd/          # 远程命令执行（基础服务）
│   ├── debug_tool/          # 日志调测查看器
│   └── quickly_cmd/         # 快捷面板（内嵌编译/计算入口）
├── utils/
│   ├── config_manager.py    # 配置与插件数据持久化
│   ├── logger.py            # 全局日志单例
│   └── icon_generator.py    # 图标生成工具
├── config/                  # 运行时配置（自动生成，可随需修改）
│   ├── plugin.json          # 插件注册清单与应用信息
│   ├── theme/dark.json      # 深色主题配色
│   ├── theme/light.json     # 浅色主题配色
│   └── *.json / *.xml       # 各插件的配置与数据
├── scripts/                 # 远程执行示例脚本（自动化测试/状态检查/部署）
├── tests/                   # 终端 ANSI、选区、拖拽等测试与可视化预览脚本
└── assets/                  # 图标等静态资源
```

---

## 快速开始

### 1. 环境要求

- Python 3.10 及以上
- Windows / macOS / Linux 桌面环境

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖清单：

```text
PyQt6>=6.0.0      # 桌面界面
paramiko>=2.10.0  # SSH / SFTP
pyserial>=3.5     # 串口通信
```

### 3. 运行

```bash
python main.py
```

启动后在左侧 / 顶部切换「终端、协议测试、编译工具、脚本管理、计算工具、调测工具」等页签即可使用。

### 4. 添加连接

1. 打开「终端」页签；
2. 在顶部快速连接栏选择 `ssh / telnet / serial`，填写地址、端口、账号等；
3. 点击「连接」立即会话，或点击「保存」沉淀到左侧连接列表，以后双击即可连接。

---

## 主题与配置

- **切换主题**：主菜单「设置 → 主题」选择深色 / 浅色，即时生效并持久化；
- **主题配色**：编辑 `config/theme/dark.json`、`config/theme/light.json` 可自定义颜色；
- **插件配置**：各工具配置独立保存在 `config/<plugin>_config.json`，连接数据在 `config/connections.json`；
- **日志位置**：应用日志 `logs/mydesk_debug_YYYYMMDD.log`，终端会话日志 `logs/terminal/`。

---

## 插件化架构说明

- 插件在 `config/plugin.json` 中注册，声明 `name / module / main_class`，由 `PluginManager` 动态导入实例化；
- 插件只需提供 `get_widget()` 返回界面，并可通过 `register_menus(registry)` 声明自己的菜单（普通项、勾选项、子菜单、互斥单选组、快捷键均支持）；
- 插件之间通过 `plugin_manager.get_plugin(name)` 协作，例如编译工具与脚本管理复用远程命令插件；
- 新增工具时：在 `plugins/` 下新建目录 → 实现插件类 → 在 `plugin.json` 注册，无需改动框架代码。

最小插件示例：

```python
class MyToolPlugin:
    def __init__(self, config, config_manager=None, plugin_manager=None):
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.name = config['name']
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = MyToolWidget(self.config, self._config_manager, self._plugin_manager)
        return self.widget
```

---

## 开发与测试

- 终端相关单元测试与可视化预览位于 `tests/`（ANSI 解析、按键、文本选择、标签拖拽等）；
- 修改界面后建议运行 `python -m py_compile` 校验，并启动应用实际确认双主题效果；
- `scripts/` 内为可配合远程命令 / 脚本管理使用的运维脚本示例。

---

## 适用场景

- 嵌入式工程师：串口日志、Modbus 主从调试、一键烧录编译、寄存器换算
- 运维 / 后端：多台 Linux 主机 SSH 会话、SFTP 传文件、保活防断连、命令按钮批量操作
- 测试 / 技术支持：快速复现协议问题、定时发包、会话日志留痕、自动化脚本巡检

## 许可证

本项目仅用于内部团队效率工具，请在获得授权的范围内使用与分发。
