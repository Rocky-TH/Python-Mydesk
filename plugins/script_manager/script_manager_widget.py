import os
import threading
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QPlainTextEdit, QComboBox,
    QGroupBox, QMessageBox, QDialog, QLineEdit,
    QTextEdit, QDialogButtonBox, QTreeView, QHeaderView,
    QInputDialog, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QAction, QStandardItemModel, QStandardItem

from plugins.script_runner import ScriptRunner


SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts')


class ScriptEditorDialog(QDialog):
    """脚本编辑对话框"""
    
    def __init__(self, script=None, parent=None):
        super().__init__(parent)
        self.script = script or {}
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("编辑脚本" if self.script else "新建脚本")
        self.setMinimumSize(600, 500)
        
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setText(self.script.get('name', ''))
        form_layout.addRow("名称:", self.name_edit)
        
        self.id_edit = QLineEdit()
        self.id_edit.setText(self.script.get('id', ''))
        self.id_edit.setReadOnly(bool(self.script))
        form_layout.addRow("ID:", self.id_edit)
        
        self.desc_edit = QTextEdit()
        self.desc_edit.setText(self.script.get('description', ''))
        self.desc_edit.setMaximumHeight(60)
        form_layout.addRow("描述:", self.desc_edit)
        
        layout.addLayout(form_layout)
        
        desc_label = QLabel("脚本内容:")
        layout.addWidget(desc_label)
        
        self.script_edit = QPlainTextEdit()
        self.script_edit.setFont(QFont("Consolas", 11))
        default_script = self.script.get('script', '''# 脚本说明:
# - 使用 session.send_cmd(command) 发送命令并获取响应
# - 使用 session.send(data) 发送原始数据
# - 使用 session.recv(timeout) 接收响应
# - 使用 log(message) 输出日志
# - 使用 session.set_result(key, value) 保存结果

# 示例:
log("开始执行脚本...")
output = session.send_cmd("echo hello")
log(f"命令输出: {output}")
session.set_result("status", "ok")
''')
        self.script_edit.setPlainText(default_script)
        layout.addWidget(self.script_edit)
        
        self.script_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 8px;
                font-family: Consolas;
            }
        """)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def get_script_data(self):
        """获取脚本数据"""
        return {
            'id': self.id_edit.text(),
            'name': self.name_edit.text() or '未命名脚本',
            'description': self.desc_edit.toPlainText(),
            'script': self.script_edit.toPlainText()
        }


class ScriptManagerWidget(QWidget):
    """脚本管理器控件"""
    
    script_executed = pyqtSignal(dict)
    output_updated = pyqtSignal(str)
    button_enabled = pyqtSignal(bool)
    
    def __init__(self, config, config_manager=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self._remote_cmd_plugin = None
        self._color_scheme = self._get_color_scheme()
        self._script_threads = []
        self._current_file_path = None
        
        self.output_updated.connect(self._append_output)
        self.button_enabled.connect(self._set_button_enabled)
        
        self._ensure_scripts_dir()
        self.init_ui()
    
    def _ensure_scripts_dir(self):
        """确保脚本目录存在"""
        if not os.path.exists(SCRIPTS_DIR):
            os.makedirs(SCRIPTS_DIR)
    
    def _get_color_scheme(self):
        """获取颜色方案"""
        if self._config_manager:
            return self._config_manager.get_color_scheme()
        return {}
    
    def _get_style(self, key, default=None):
        """获取样式配置"""
        return self._color_scheme.get(key, default)
    
    def _get_font_size(self, key, default='12px'):
        """获取字体大小"""
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        return default
    
    def _get_remote_cmd_plugin(self):
        """获取RemoteCmd插件"""
        if not self._remote_cmd_plugin and self._plugin_manager:
            self._remote_cmd_plugin = self._plugin_manager.get_plugin("RemoteCmd")
        return self._remote_cmd_plugin
    
    def _append_output(self, text):
        """线程安全的输出追加"""
        self.output_text.appendPlainText(text)
    
    def _set_button_enabled(self, enabled):
        """线程安全的按钮状态设置"""
        self.run_btn.setEnabled(enabled)
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        left_panel = self._create_left_panel()
        layout.addWidget(left_panel, 1)
        
        right_panel = self._create_right_panel()
        layout.addWidget(right_panel, 3)
    
    def _create_left_panel(self):
        """创建左侧面板（文件树）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        header_layout = QHBoxLayout()
        title = QLabel("脚本文件")
        primary = self._get_style('primary', '#007acc')
        text_primary = self._get_style('text', '#ffffff')
        title.setStyleSheet(f"color: {text_primary}; font-weight: bold; font-size: 14px;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        add_btn = QPushButton("新建")
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary};
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: #005a9e;
            }}
        """)
        add_btn.clicked.connect(self.on_add_script)
        header_layout.addWidget(add_btn)
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedHeight(28)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #3c3c3c;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: #4c4c4c;
            }}
        """)
        refresh_btn.clicked.connect(self._refresh_file_tree)
        header_layout.addWidget(refresh_btn)
        
        layout.addLayout(header_layout)
        
        self.file_model = QStandardItemModel()
        self.file_model.setHorizontalHeaderLabels(["名称"])
        
        self.file_tree = QTreeView()
        self.file_tree.setModel(self.file_model)
        self.file_tree.setHeaderHidden(True)
        self._populate_file_tree()
        self.file_tree.setStyleSheet("""
            QTreeView {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }
            QTreeView::item {
                padding: 6px;
            }
            QTreeView::item:selected {
                background-color: #007acc;
            }
            QTreeView::item:hover {
                background-color: #2d2d30;
            }
        """)
        self.file_tree.clicked.connect(self.on_file_selected)
        self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        layout.addWidget(self.file_tree)
        
        return widget
    
    def _create_right_panel(self):
        """创建右侧面板（脚本编辑器）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        info_group = QGroupBox("脚本信息")
        info_layout = QFormLayout(info_group)
        
        text_primary = self._get_style('text', '#ffffff')
        font_size = self._get_font_size('size-md', '12px')
        
        self.script_name_label = QLabel("未选择")
        self.script_name_label.setStyleSheet(f"color: {text_primary}; font-size: 16px; font-weight: bold;")
        info_layout.addRow("文件:", self.script_name_label)
        
        self.script_desc_label = QLabel("")
        self.script_desc_label.setStyleSheet(f"color: #888888; font-size: {font_size};")
        self.script_desc_label.setWordWrap(True)
        info_layout.addRow("描述:", self.script_desc_label)
        
        layout.addWidget(info_group)
        
        editor_group = QGroupBox("脚本内容")
        editor_layout = QVBoxLayout(editor_group)
        
        self.script_editor = QPlainTextEdit()
        self.script_editor.setFont(QFont("Consolas", 11))
        self.script_editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 8px;
                font-family: Consolas;
            }
        """)
        editor_layout.addWidget(self.script_editor)
        
        layout.addWidget(editor_group)
        
        env_group = QGroupBox("运行环境")
        env_layout = QHBoxLayout(env_group)
        
        self.env_combo = QComboBox()
        self.env_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #5a5a5d;
                padding: 6px 10px;
                border-radius: 4px;
            }
        """)
        self._load_environments()
        env_layout.addWidget(self.env_combo, 1)
        
        layout.addWidget(env_group)
        
        btn_layout = QHBoxLayout()
        
        self.run_btn = QPushButton("运行脚本")
        self.run_btn.setFixedHeight(36)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #555555;
            }
        """)
        self.run_btn.clicked.connect(self.on_run_script)
        btn_layout.addWidget(self.run_btn)
        
        self.validate_btn = QPushButton("验证语法")
        self.validate_btn.setFixedHeight(36)
        self.validate_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        self.validate_btn.clicked.connect(self.on_validate_script)
        btn_layout.addWidget(self.validate_btn)
        
        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedHeight(36)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        self.save_btn.clicked.connect(self.on_save_script)
        btn_layout.addWidget(self.save_btn)
        
        self.delete_btn = QPushButton("删除")
        self.delete_btn.setFixedHeight(36)
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        self.delete_btn.clicked.connect(self.on_delete_script)
        btn_layout.addWidget(self.delete_btn)
        
        layout.addLayout(btn_layout)
        
        output_group = QGroupBox("执行输出")
        output_layout = QVBoxLayout(output_group)
        
        self.output_text = QPlainTextEdit()
        self.output_text.setFont(QFont("Consolas", 10))
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0c0c0c;
                color: #00ff00;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 8px;
                font-family: Consolas;
            }
        """)
        output_layout.addWidget(self.output_text)
        
        layout.addWidget(output_group)
        
        return widget
    
    def _refresh_file_tree(self):
        """刷新文件树"""
        self._populate_file_tree()
    
    def _populate_file_tree(self):
        """填充文件树"""
        self.file_model.clear()
        self.file_model.setHorizontalHeaderLabels(["名称"])
        self._add_files_to_tree(SCRIPTS_DIR, self.file_model.invisibleRootItem())
    
    def _add_files_to_tree(self, dir_path, parent_item):
        """递归添加文件到树"""
        try:
            entries = sorted(os.listdir(dir_path))
        except OSError:
            return
        
        for entry in entries:
            full_path = os.path.join(dir_path, entry)
            if os.path.isdir(full_path):
                # 文件夹
                folder_item = QStandardItem(entry)
                folder_item.setSelectable(False)
                folder_item.setEditable(False)
                parent_item.appendRow(folder_item)
                self._add_files_to_tree(full_path, folder_item)
            elif os.path.isfile(full_path) and entry.endswith('.py'):
                # Python文件
                file_item = QStandardItem(entry)
                file_item.setEditable(False)
                file_item.setData(full_path, Qt.ItemDataRole.UserRole)
                parent_item.appendRow(file_item)
    
    def _on_tree_context_menu(self, pos):
        """文件树右键菜单"""
        index = self.file_tree.indexAt(pos)
        if not index.isValid():
            return
        
        menu = QMenu(self)
        
        run_action = QAction("运行", self)
        run_action.triggered.connect(lambda: self.on_run_script())
        menu.addAction(run_action)
        
        edit_action = QAction("编辑", self)
        edit_action.triggered.connect(lambda: self.on_file_selected(index))
        menu.addAction(edit_action)
        
        menu.addSeparator()
        
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self.on_delete_script())
        menu.addAction(delete_action)
        
        menu.exec(self.file_tree.viewport().mapToGlobal(pos))
    
    def _load_environments(self):
        """加载环境列表"""
        self.env_combo.clear()
        
        if self._config_manager:
            plugin_config = self._config_manager.get_plugin_config("QuicklyCmd")
            if plugin_config and 'compile' in plugin_config:
                environments = plugin_config['compile'].get('compile_environments', [])
                for env in environments:
                    env_name = env.get('name', '未命名')
                    has_conn = bool(env.get('connection'))
                    display = env_name if has_conn else f"{env_name}（无连接）"
                    self.env_combo.addItem(display, env)
        
        if self.env_combo.count() == 0:
            self.env_combo.addItem("（无可用环境）", None)
    
    def on_file_selected(self, index):
        """文件选择变化"""
        if not index.isValid():
            return
        
        # 从item的UserRole获取文件路径
        item = self.file_model.itemFromIndex(index)
        file_path = item.data(Qt.ItemDataRole.UserRole)
        
        if file_path and os.path.isfile(file_path) and file_path.endswith('.py'):
            self._current_file_path = file_path
            file_name = os.path.basename(file_path)
            self.script_name_label.setText(file_name)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.script_editor.setPlainText(content)
                
                # 从第一行注释提取描述
                first_line = content.split('\n')[0] if content else ''
                if first_line.startswith('#'):
                    self.script_desc_label.setText(first_line.lstrip('# ').strip())
                else:
                    self.script_desc_label.setText("")
            except Exception as e:
                self.output_text.appendPlainText(f"[错误] 读取文件失败: {e}")
    
    def on_add_script(self):
        """新建脚本文件"""
        name, ok = QInputDialog.getText(self, "新建脚本", "脚本文件名（不含.py后缀）:")
        if not ok or not name.strip():
            return
        
        name = name.strip()
        if not name.endswith('.py'):
            name += '.py'
        
        file_path = os.path.join(SCRIPTS_DIR, name)
        
        if os.path.exists(file_path):
            self.output_text.appendPlainText(f"[新建] 文件已存在: {name}")
            return
        
        default_content = '''# 脚本说明:
# - 使用 session.send_cmd(command) 发送命令并获取响应
# - 使用 session.send(data) 发送原始数据
# - 使用 session.recv(timeout) 接收响应
# - 使用 log(message) 输出日志
# - 使用 session.set_result(key, value) 保存结果

# 示例:
log("开始执行脚本...")
output = session.send_cmd("echo hello")
log(f"命令输出: {output}")
session.set_result("status", "ok")
'''
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(default_content)
            self.output_text.appendPlainText(f"[新建] 脚本文件已创建: {name}")
            
            # 刷新并选中新创建的文件
            self._refresh_file_tree()
            self._select_file_in_tree(file_path)
        except Exception as e:
            self.output_text.appendPlainText(f"[错误] 创建文件失败: {e}")
    
    def _select_file_in_tree(self, file_path):
        """在文件树中选中指定文件"""
        root = self.file_model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.data(Qt.ItemDataRole.UserRole) == file_path:
                idx = item.index()
                self.file_tree.setCurrentIndex(idx)
                self.on_file_selected(idx)
                return
    
    def on_validate_script(self):
        """验证脚本语法"""
        script_content = self.script_editor.toPlainText()
        if not script_content.strip():
            self.output_text.appendPlainText("[验证] 脚本内容为空")
            return
        
        result = ScriptRunner.validate(script_content)
        if result['valid']:
            self.output_text.appendPlainText("[验证] 语法正确 ✓")
        else:
            self.output_text.appendPlainText(f"[验证] 语法错误: {result['error']}")
            if result['line']:
                self.output_text.appendPlainText(f"  位置: 第{result['line']}行")
    
    def on_run_script(self):
        """运行脚本"""
        script_content = self.script_editor.toPlainText()
        if not script_content.strip():
            self.output_text.appendPlainText("[执行] 脚本内容为空")
            return
        
        env_data = self.env_combo.currentData()
        if not env_data:
            self.output_text.appendPlainText("[执行] 请选择运行环境")
            return
        
        env_name = env_data.get('name', '')
        file_name = os.path.basename(self._current_file_path) if self._current_file_path else "未命名"
        self.output_text.appendPlainText(f"[执行] 开始执行脚本: {file_name}")
        self.output_text.appendPlainText(f"[执行] 运行环境: {env_name}")
        self.run_btn.setEnabled(False)
        
        remote_cmd = self._get_remote_cmd_plugin()
        if not remote_cmd:
            self.output_text.appendPlainText("[错误] 无法获取RemoteCmd插件")
            self.run_btn.setEnabled(True)
            return
        
        def run_in_thread():
            try:
                if env_data.get('connection'):
                    success, msg = remote_cmd.connect(env_name, timeout=10)
                    if not success:
                        self.output_updated.emit(f"[连接] {msg}")
                        self.button_enabled.emit(True)
                        return
                    self.output_updated.emit(f"[连接] {msg}")
                
                result = remote_cmd.execute_script(env_name, script_content, timeout=60)
                
                output = result.get('output', '')
                if output:
                    self.output_updated.emit(f"[输出]\n{output}")
                
                if result['success']:
                    self.output_updated.emit("[执行] 脚本执行成功 ✓")
                    session_result = result.get('session_result')
                    if session_result:
                        self.output_updated.emit(f"[结果] {session_result}")
                else:
                    error_msg = result.get('error', '未知错误')
                    self.output_updated.emit(f"[错误] {error_msg}")
                
                self.output_updated.emit("-" * 50)
                self.button_enabled.emit(True)
                
            except Exception as e:
                self.output_updated.emit(f"[异常] {str(e)}")
                self.button_enabled.emit(True)
        
        thread = threading.Thread(target=run_in_thread)
        thread.daemon = True
        thread.start()
    
    def on_save_script(self):
        """保存脚本到文件"""
        if not self._current_file_path:
            self.output_text.appendPlainText("[保存] 请先选择要保存的文件")
            return
        
        try:
            content = self.script_editor.toPlainText()
            with open(self._current_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.output_text.appendPlainText(f"[保存] 文件已保存 ✓")
        except Exception as e:
            self.output_text.appendPlainText(f"[错误] 保存文件失败: {e}")
    
    def on_delete_script(self):
        """删除脚本文件"""
        if not self._current_file_path:
            self.output_text.appendPlainText("[删除] 请先选择要删除的文件")
            return
        
        file_name = os.path.basename(self._current_file_path)
        reply = QMessageBox.question(
            self, '确认删除',
            f"确定要删除脚本文件 \"{file_name}\" 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self._current_file_path)
                self.output_text.appendPlainText(f"[删除] 文件已删除: {file_name}")
                self._current_file_path = None
                self.script_name_label.setText("未选择")
                self.script_desc_label.setText("")
                self.script_editor.clear()
                self._refresh_file_tree()
            except Exception as e:
                self.output_text.appendPlainText(f"[错误] 删除文件失败: {e}")
