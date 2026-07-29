# 终端工具自定义按钮工具栏实现计划

## Context

用户需要在终端工具底部增加一个自定义按钮功能栏，支持右键新增按钮。按钮可关联 shell 命令或 Python 脚本，点击后在当前会话上下文中执行，发送内容和回显显示在当前会话的输出框中。执行中按钮变蓝，完成后恢复深灰色。必须复用现有的 ScriptRunner、Session、ConnectionContext 等模块，不重复实现。

## 数据模型

按钮配置持久化到 `config_manager` 插件数据（plugin_name='Terminal', data_key='terminal_buttons'）：

```python
# 单个按钮
{
    "id": "uuid4 hex",          # 唯一标识
    "name": "查看磁盘",          # 显示名称
    "type": "command",          # "command" | "script"
    "command": "df -h",         # type=command 时的命令
    "script_path": "/abs/path/script.py",  # type=script 时脚本路径
    "created_at": 1690000000    # 时间戳，用于排序
}
# 持久化结构
{"buttons": [<btn_dict>, ...]}
```

## 文件改动

仅改动 **1 个文件**：`d:\Project\MyDesk\MyDesk\plugins\terminal\terminal_widget.py`

### 1. 顶部 import 补充
- `import uuid`（生成按钮 id）
- `from plugins.script_runner import Session, ScriptRunner`（复用脚本执行，绝对导入路径，符合项目约定）

### 2. 新增 `ButtonExecutionWorker(QThread)` 类
放在 `ConnectionWorker` 之后（约 L177），聚集 worker 类。

- 信号：`finished = pyqtSignal(str, dict)` — (btn_id, result)
- `run()` 方法根据 `btn_data['type']` 分派：
  - **command**：调用 `session_tab.connection_context.send_command(cmd)` → 返回 output
  - **script**：读取脚本文件 → `Session(strategy, "terminal", {})` → `ScriptRunner().execute(content, session)` → 返回 result dict
- `strategy = session_tab.connection_context._strategy`（兼容 Session 的 connection 参数接口）

### 3. 新增 `TerminalButtonToolbar(QWidget)` 类
放在 `TerminalWidget` 类之前。

**布局**：QHBoxLayout，左对齐按钮，空列表时显示"右键添加按钮"提示

**右键菜单**：
- 工具栏空白处：「添加按钮」
- 单个按钮上：「编辑」「删除」（删除前二次确认）

**按钮样式**（property 选择器）：
- `executing="false"`：深灰背景 `bg-input`，白色字体
- `executing="true"`：蓝色背景 `primary`，白色字体

**关键方法**：
- `_load_buttons()` / `_save_buttons()`：读写 config_manager 插件数据
- `_build_toolbar()`：按数据重建按钮 UI
- `add_button()` / `edit_button(btn_id)` / `delete_button(btn_id)`
- `set_button_executing(btn_id, bool)`：切换按钮执行态
- `get_button_data(btn_id)`：返回指定按钮数据
- `refresh_theme_styles()`：主题切换时刷新所有按钮样式

**对外信号**：`button_triggered = pyqtSignal(str)` — 发出 btn_id，执行逻辑由 TerminalWidget 处理

### 4. 新增 `ButtonEditDialog(QDialog)` 类
放在文件末尾对话框区域（`SFTPDialog` 之后）。

**控件布局**：
```
名称:    [QLineEdit]
类型:    [QComboBox: 命令 / 脚本]
--- 动态参数区（根据类型切换）---
命令型:  [QPlainTextEdit 多行命令] + 超时 [QSpinBox 1..60 默认5]
脚本型:  [QLineEdit 路径 + 浏览按钮] + [QComboBox 脚本下拉] + [QPlainTextEdit 只读预览]
--- 底部 ---
         [确定] [取消]
```

**校验**：名称非空；命令型命令非空；脚本型路径存在且以 .py 结尾

**脚本选择**：浏览按钮弹出 `QFileDialog`（默认目录 SCRIPTS_DIR），同时下拉列表扫描 SCRIPTS_DIR 下 .py 文件

### 5. 修改 `TerminalWidget`

**布局改造**（`init_ui` ~L1177）：
```
原: main_layout = QHBoxLayout(self) → splitter
改: outer_layout = QVBoxLayout(self)
    ├── content_widget (stretch=1) → main_layout = QHBoxLayout(content_widget) → splitter
    └── button_toolbar (stretch=0)
```
包一层 content_widget，原 main_layout 所有引用不变。

**新增成员**：`self._executing_workers = {}`（btn_id → worker，防 GC）

**新增方法**：
- `_execute_button(btn_id)`：校验会话/连接 → 暂停 `session_tab.output_timer`（避免读缓冲争抢）→ 置按钮蓝色 → 启动 worker
- `_on_button_execution_finished(btn_id, result)`：写输出 → 清理 worker → 恢复按钮灰色 → 恢复 `output_timer`

**`refresh_theme_styles`** 末尾追加：`self.button_toolbar.refresh_theme_styles()`

## 关键实现细节

### 线程安全
- 执行前**必须 `stop()` output_timer**（30ms 轮询会争抢同一连接的 `read_output`），完成后 `start(30)` 恢复
- `write_output` 只在主线程调用（通过 `finished` 信号回调）
- `_executing_workers` dict 持有 worker 引防 GC

### 模块复用（不重复实现）
- 命令执行：`ConnectionContext.send_command(command)` — 直接复用
- 脚本执行：`Session(strategy, ...)` + `ScriptRunner().execute()` — 直接复用
- 配置持久化：`config_manager.set_plugin_data` / `save_plugin_data` / `get_plugin_data` — 直接复用

## 验证方式

1. 启动应用，终端工具底部应显示按钮工具栏，空列表时显示"右键添加按钮"提示
2. 右键 → 添加按钮 → 弹窗中填写名称、选择类型（命令/脚本）、填写内容 → 确定
3. 建立连接后点击按钮：
   - 按钮变蓝，终端输出框显示执行内容和回显
   - 执行完成按钮恢复深灰色
4. 右键单个按钮 → 编辑/删除功能正常
5. 重启应用，按钮配置应持久化加载
6. 切换主题，按钮样式应随主题刷新
