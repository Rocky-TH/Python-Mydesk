import os
import threading
import time
from stat import S_ISDIR
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QLabel, QLineEdit, QComboBox, QSpinBox, QPushButton,
    QTextEdit, QTabWidget, QMessageBox, QCheckBox,
    QListWidget, QListWidgetItem, QMenu, QDialog,
    QPlainTextEdit, QFileDialog, QProgressDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction, QTextCursor, QColor, QKeyEvent, QTextCharFormat
from .connection_context import ConnectionContext
from .ssh_connection import SSHConnection
from .telnet_connection import TelnetConnection
from .serial_connection import SerialConnection
from .connection_manager import ConnectionManager
from .connection_factory import ConnectionFactory
from .ansi_parser import ANSIParser


class TerminalPlugin:
    def __init__(self, config, config_manager=None):
        self.config = config
        self._config_manager = config_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = TerminalWidget(self.config, self._config_manager)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass


class TerminalEdit(QTextEdit):
    """自定义终端编辑控件，用于拦截键盘事件"""

    key_pressed = pyqtSignal(QKeyEvent)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("""
            QTextEdit {
                background-color: #0c0c0c;
                color: #cccccc;
                border: none;
            }
            QTextEdit:focus {
                border: 2px solid #007acc;
            }
        """)

    def keyPressEvent(self, event):
        """拦截所有键盘事件并发送给父组件处理"""
        self.key_pressed.emit(event)
        event.accept()


class SessionTab(QWidget):
    """单个会话标签页 - 交互式终端"""
    def __init__(self, session_id, session_name, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.session_name = session_name
        self.connection_context = ConnectionContext()
        self.current_connection = None
        self.command_history = []
        self.history_index = -1
        self.current_input = ""
        self.interactive_mode = False
        self.ansi_parser = ANSIParser()

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Terminal area - 使用自定义控件
        self.terminal_display = TerminalEdit()
        self.terminal_display.setFont(QFont("Consolas", 11))
        self.terminal_display.key_pressed.connect(self.handle_key_press)
        layout.addWidget(self.terminal_display)

        # Status bar
        self.status_bar = QWidget()
        self.status_bar.setFixedHeight(25)
        self.status_bar.setStyleSheet("background-color: #007acc;")
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(10, 0, 10, 0)

        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: white; font-weight: bold; font-size: 11px;")
        status_layout.addWidget(self.status_label)

        self.connection_info = QLabel("")
        self.connection_info.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 11px;")
        status_layout.addWidget(self.connection_info)

        status_layout.addStretch()

        self.connection_type_label = QLabel("")
        self.connection_type_label.setStyleSheet("color: white; font-size: 11px;")
        status_layout.addWidget(self.connection_type_label)

        layout.addWidget(self.status_bar)

        # 远程输出轮询定时器
        self.output_timer = QTimer(self)
        self.output_timer.timeout.connect(self.poll_remote_output)

    # ========== 公共接口 ==========

    def get_connection(self):
        """获取当前连接上下文"""
        return self.connection_context

    def send(self, data):
        """发送数据到远程"""
        if self.connection_context.is_connected():
            strategy = self.connection_context._strategy
            if hasattr(strategy, 'send_raw'):
                strategy.send_raw(data)
                return True
        return False

    def recv(self, timeout=0.1):
        """接收远程数据"""
        if self.connection_context.is_connected():
            strategy = self.connection_context._strategy
            if hasattr(strategy, 'read_output'):
                return strategy.read_output(timeout)
        return ""

    # ========== 内部方法 ==========

    def write_output(self, text, color=None):
        """写入终端输出，支持ANSI转义序列和回车符处理"""
        cursor = self.terminal_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # 先处理回车符 \r\n -> \n, 然后处理单独的 \r
        text = text.replace('\r\n', '\n')

        # 如果指定了颜色，直接使用
        if color:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            cursor.setCharFormat(fmt)
            self._insert_text_with_cr(cursor, text)
        else:
            # 使用ANSI解析器处理转义序列
            parts = self.ansi_parser.parse(text)
            for part_text, part_format in parts:
                cursor.setCharFormat(part_format)
                self._insert_text_with_cr(cursor, part_text)

        self.terminal_display.setTextCursor(cursor)
        self.terminal_display.ensureCursorVisible()

    def _insert_text_with_cr(self, cursor, text):
        """插入文本，处理 \r 回车符和 \b 退格符"""
        i = 0
        while i < len(text):
            if text[i] == '\r':
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                i += 1
            elif text[i] == '\b':
                # 退格：删除前一个字符
                cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                i += 1
            elif text[i] == '\x7f':
                # DEL 键：删除当前字符
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                i += 1
            else:
                # 找到下一个控制字符
                next_control = len(text)
                for j in range(i, len(text)):
                    if text[j] in '\r\b\x7f':
                        next_control = j
                        break
                chunk = text[i:next_control]
                cursor.insertText(chunk)
                i = next_control

    def make_format(self, color):
        """创建文本格式"""
        from PyQt6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        return fmt

    def poll_remote_output(self):
        """轮询远程输出（交互模式）"""
        if not self.connection_context.is_connected():
            return

        strategy = self.connection_context._strategy
        if hasattr(strategy, 'read_output'):
            output = strategy.read_output(timeout=0.1)
            if output:
                self.write_output(output)

    def handle_key_press(self, event):
        """处理键盘事件"""
        if not self.connection_context.is_connected():
            return

        key = event.key()
        text = event.text()
        modifiers = event.modifiers()

        # 获取底层策略
        strategy = self.connection_context._strategy
        has_raw = hasattr(strategy, 'send_raw') and self.interactive_mode

        # Ctrl+C - 发送中断信号
        if key == Qt.Key.Key_C and modifiers == Qt.KeyboardModifier.ControlModifier:
            if has_raw:
                strategy.send_raw("\x03")  # ETX (Ctrl+C)
            return

        # 方向键
        if key == Qt.Key.Key_Up:
            if has_raw:
                strategy.send_raw("\x1b[A")  # ANSI 上箭头
                self.navigate_history(-1)
            return
        elif key == Qt.Key.Key_Down:
            if has_raw:
                strategy.send_raw("\x1b[B")  # ANSI 下箭头
                self.navigate_history(1)
            return
        elif key == Qt.Key.Key_Left:
            if has_raw:
                strategy.send_raw("\x1b[D")  # ANSI 左箭头
            return
        elif key == Qt.Key.Key_Right:
            if has_raw:
                strategy.send_raw("\x1b[C")  # ANSI 右箭头
            return

        # Home / End
        if key == Qt.Key.Key_Home:
            if has_raw:
                strategy.send_raw("\x1b[H")  # ANSI Home
            return
        elif key == Qt.Key.Key_End:
            if has_raw:
                strategy.send_raw("\x1b[F")  # ANSI End
            return

        # Tab
        if key == Qt.Key.Key_Tab:
            if has_raw:
                strategy.send_raw("\t")
            return

        # Esc
        if key == Qt.Key.Key_Escape:
            if has_raw:
                strategy.send_raw("\x1b")
            return

        # 回车
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if has_raw:
                # 交互模式：发送换行到远程，由远程处理
                if self.current_input.strip():
                    self.command_history.append(self.current_input)
                self.history_index = len(self.command_history)
                self.current_input = ""
                strategy.send_raw("\n")
            else:
                self.execute_command()
            return

        # 退格 / 删除
        if key == Qt.Key.Key_Backspace:
            if has_raw:
                if len(self.current_input) > 0:
                    self.current_input = self.current_input[:-1]
                strategy.send_raw("\x7f")  # DEL 键 (大多数SSH服务器期望的退格)
            elif len(self.current_input) > 0:
                self.current_input = self.current_input[:-1]
                self.redraw_input_line()
            return
        elif key == Qt.Key.Key_Delete:
            if has_raw:
                strategy.send_raw("\x1b[3~")  # ANSI Delete
            return

        # 普通字符
        if text and len(text) == 1 and text.isprintable():
            if has_raw:
                # 交互模式：直接发送到远程，不在本地显示
                self.current_input += text
                strategy.send_raw(text)
            else:
                # 非交互模式：本地显示
                self.current_input += text
                self.write_output(text, "#ffffff")

    def navigate_history(self, direction):
        """导航命令历史（交互模式）"""
        if not self.command_history:
            return

        self.history_index += direction

        if self.history_index < 0:
            self.history_index = 0
        elif self.history_index >= len(self.command_history):
            self.history_index = len(self.command_history)
            # 发送Ctrl+C取消当前输入，然后输入空命令
            self.current_input = ""
        else:
            cmd = self.command_history[self.history_index]
            self.current_input = cmd

    def redraw_input_line(self):
        """重绘输入行（非交互模式）"""
        cursor = self.terminal_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()
        
        prompt = self.get_prompt()
        self.write_output(f"{prompt} {self.current_input}", "#00ff00")

    def get_prompt(self):
        """获取提示符"""
        if self.connection_context.is_connected():
            return f"{self.connection_context.get_strategy_name()}>"
        return "$"

    def execute_command(self):
        """执行命令（非交互模式）"""
        if not self.current_input.strip():
            self.write_output("\n")
            self.show_input_line()
            return

        self.command_history.append(self.current_input)
        self.history_index = len(self.command_history)

        cmd = self.current_input
        self.current_input = ""
        self.write_output("\n")

        response = self.connection_context.send_command(cmd)
        if response:
            self.write_output(response, "#cccccc")

        self.show_input_line()

    def show_input_line(self):
        """显示输入行提示符（非交互模式）"""
        prompt = self.get_prompt()
        self.write_output(f"{prompt} ", "#00ff00")

    def connect_with_config(self, conn):
        """使用保存的连接配置进行连接"""
        conn_type = conn.get('type')
        config = conn.get('config', {})

        self.current_connection = conn
        self.session_name = conn.get('name', '会话')

        self.terminal_display.clear()
        self.write_output(f"正在连接 {conn.get('name', '')} ({conn_type})...\n", "#ffff00")

        # 使用工厂模式创建连接
        strategy = ConnectionFactory.create_connection(conn_type)
        if strategy:
            self.connection_context.set_strategy(strategy)
            success = self.connection_context.connect(config)

            if success:
                self.status_label.setText("已连接")
                self.status_label.setStyleSheet("color: #00ff00; font-weight: bold; font-size: 11px;")

                host = config.get('host', '')
                port = config.get('port', '')
                self.connection_info.setText(f"{host}:{port}" if host else config.get('port', ''))
                self.connection_type_label.setText(conn_type.upper())

                # 检测是否支持交互模式
                if hasattr(strategy, 'send_raw') and hasattr(strategy, 'read_output'):
                    self.interactive_mode = True
                    # 等待shell初始化并读取初始输出
                    import time
                    time.sleep(1.0)  # 增加等待时间
                    initial_output = strategy.read_output(timeout=0.5)
                    if initial_output:
                        self.write_output(initial_output)
                    # 启动输出轮询
                    self.output_timer.start(100)
                else:
                    self.interactive_mode = False
                    self.write_output("连接成功!\n", "#00ff00")
                    self.write_output("-" * 50 + "\n", "#888888")
                    self.show_input_line()

                self.setFocus()
            else:
                self.write_output("连接失败!\n", "#ff0000")
                self.write_output("请检查连接参数是否正确\n", "#ff6666")
                self.status_label.setText("连接失败")
                self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold; font-size: 11px;")
        else:
            self.write_output(f"不支持的连接类型: {conn_type}\n", "#ff0000")
            self.status_label.setText("连接失败")
            self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold; font-size: 11px;")

    def disconnect(self):
        """断开连接"""
        self.output_timer.stop()
        self.connection_context.disconnect()
        self.interactive_mode = False
        self.write_output("\n已断开连接\n", "#ff6600")
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: white; font-weight: bold; font-size: 11px;")
        self.connection_info.setText("")
        self.connection_type_label.setText("")


class TerminalWidget(QWidget):
    connection_status_changed = pyqtSignal(str)

    def __init__(self, config=None, config_manager=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._config_manager = config_manager
        self.connection_manager = ConnectionManager(config_manager)
        self.sessions = {}  # session_id -> SessionTab
        self.session_counter = 0
        self.current_session_id = None

        self.init_ui()

    def init_ui(self):
        # Main layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Left sidebar for saved connections
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)

        # Quick action buttons at top of sidebar
        self.quick_actions = QWidget()
        self.quick_actions.setStyleSheet("background-color: #252526;")
        quick_layout = QVBoxLayout(self.quick_actions)
        quick_layout.setContentsMargins(5, 5, 5, 5)
        quick_layout.setSpacing(5)

        # 新建连接 button
        self.new_conn_btn = QPushButton("新建连接")
        self.new_conn_btn.setFixedHeight(28)
        self.new_conn_btn.clicked.connect(self.show_new_connection_dialog)
        self.new_conn_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 4px;
                text-align: left;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        quick_layout.addWidget(self.new_conn_btn)

        # 重新连接 button
        self.reconnect_btn = QPushButton("重新连接")
        self.reconnect_btn.setFixedHeight(28)
        self.reconnect_btn.clicked.connect(self.reconnect_last)
        self.reconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d40;
                color: #cccccc;
                border: none;
                padding: 4px;
                text-align: left;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4d4d50;
            }
        """)
        quick_layout.addWidget(self.reconnect_btn)

        # SFTP button
        self.sftp_btn = QPushButton("SFTP")
        self.sftp_btn.setFixedHeight(28)
        self.sftp_btn.clicked.connect(self.show_sftp_dialog)
        self.sftp_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d40;
                color: #cccccc;
                border: none;
                padding: 4px;
                text-align: left;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4d4d50;
            }
        """)
        quick_layout.addWidget(self.sftp_btn)

        sidebar_layout.addWidget(self.quick_actions)

        # Session label
        session_label = QLabel("会话列表")
        session_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px;
                font-weight: bold;
                border-bottom: 1px solid #3d3d40;
            }
        """)
        sidebar_layout.addWidget(session_label)

        # Connection list
        self.connection_list = QListWidget()
        self.connection_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.connection_list.customContextMenuRequested.connect(self.show_connection_menu)
        self.connection_list.doubleClicked.connect(self.on_connection_double_click)
        self.connection_list.setStyleSheet("""
            QListWidget {
                background-color: #2d2d30;
                color: #cccccc;
                border: none;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3d3d40;
            }
            QListWidget::item:selected {
                background-color: #007acc;
                color: white;
            }
        """)
        sidebar_layout.addWidget(self.connection_list)

        # Refresh button
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.setFixedHeight(25)
        self.refresh_btn.clicked.connect(self.load_connections)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d40;
                color: #cccccc;
                border: none;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: #4d4d50;
            }
        """)
        sidebar_layout.addWidget(self.refresh_btn)

        # Right panel - Session tabs
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Session tabs at top
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self.close_session)
        self.session_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 6px 15px;
                border: 1px solid #3d3d40;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #007acc;
                color: white;
                border-color: #007acc;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3d3d40;
            }
            QTabBar::tab:closable {
                margin-left: 5px;
            }
        """)
        self.session_tabs.currentChanged.connect(self.on_session_changed)
        right_layout.addWidget(self.session_tabs)

        # Add to splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.right_panel)

        main_layout.addWidget(self.splitter)

        # Load connections
        self.load_connections()

    def create_session(self, conn):
        """创建新会话"""
        self.session_counter += 1
        session_id = self.session_counter
        
        # 创建会话标签
        tab = SessionTab(session_id, conn.get('name', '会话'))
        
        # 标签只显示名称，没有名称则显示IP
        conn_name = conn.get('name', '')
        if not conn_name:
            conn_name = conn.get('config', {}).get('host', '会话')
        
        index = self.session_tabs.addTab(tab, conn_name)
        self.session_tabs.setCurrentIndex(index)
        
        # 保存会话
        self.sessions[session_id] = {
            'tab': tab,
            'connection': conn,
            'id': session_id
        }
        self.current_session_id = session_id
        
        # 连接
        tab.connect_with_config(conn)
        
        return tab

    def close_session(self, index):
        """关闭会话"""
        tab = self.session_tabs.widget(index)
        if tab:
            # 找到对应的session_id
            session_id_to_remove = None
            for sid, sess in self.sessions.items():
                if sess['tab'] == tab:
                    session_id_to_remove = sid
                    break
            
            if session_id_to_remove:
                tab.disconnect()
                self.sessions.pop(session_id_to_remove)
                if self.current_session_id == session_id_to_remove:
                    self.current_session_id = None
            
            self.session_tabs.removeTab(index)
            tab.deleteLater()

    def on_session_changed(self, index):
        """会话切换"""
        if index >= 0:
            tab = self.session_tabs.widget(index)
            if tab:
                for sid, sess in self.sessions.items():
                    if sess['tab'] == tab:
                        self.current_session_id = sid
                        break

    def get_current_session(self):
        """获取当前会话"""
        if self.current_session_id and self.current_session_id in self.sessions:
            return self.sessions[self.current_session_id]['tab']
        return None

    def load_connections(self):
        """加载连接列表"""
        self.connection_list.clear()
        connections = self.connection_manager.get_connections()

        type_icons = {
            "ssh": "SSH",
            "telnet": "TEL",
            "serial": "SER"
        }

        for conn in connections:
            conn_type = conn.get('type', 'unknown')
            name = conn.get('name', '未命名')
            icon = type_icons.get(conn_type, "???")
            item = QListWidgetItem(f"[{icon}] {name}")
            item.setData(Qt.ItemDataRole.UserRole, conn)
            self.connection_list.addItem(item)

    def show_new_connection_dialog(self):
        """显示新建连接对话框"""
        dialog = ConnectionDialog(self)
        if dialog.exec():
            conn_data = dialog.get_connection_data()
            self.connection_manager.create_connection(
                conn_data['name'],
                conn_data['type'],
                conn_data['config']
            )
            self.load_connections()

    def show_sftp_dialog(self):
        """显示SFTP对话框"""
        session = self.get_current_session()
        if not session or not session.connection_context.is_connected():
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        
        dialog = SFTPDialog(session.connection_context, self)
        dialog.exec()

    def reconnect_last(self):
        """重新连接上一个会话"""
        session = self.get_current_session()
        if session and session.current_connection:
            session.connect_with_config(session.current_connection)
        else:
            QMessageBox.information(self, "提示", "没有可重新连接的会话")

    def show_connection_menu(self, pos):
        """显示连接右键菜单"""
        item = self.connection_list.itemAt(pos)
        if not item:
            return

        conn = item.data(Qt.ItemDataRole.UserRole)
        if not conn:
            return

        menu = QMenu(self)

        connect_action = QAction("新建会话", self)
        connect_action.triggered.connect(lambda: self.create_session(conn))
        menu.addAction(connect_action)

        edit_action = QAction("编辑", self)
        edit_action.triggered.connect(lambda: self.edit_connection(conn))
        menu.addAction(edit_action)

        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self.delete_connection(conn))
        menu.addAction(delete_action)

        menu.exec(self.connection_list.mapToGlobal(pos))

    def on_connection_double_click(self, index):
        """双击连接创建新会话"""
        item = self.connection_list.item(index.row())
        if item:
            conn = item.data(Qt.ItemDataRole.UserRole)
            if conn:
                self.create_session(conn)

    def edit_connection(self, conn):
        """编辑连接"""
        dialog = ConnectionDialog(self, conn)
        if dialog.exec():
            conn_id = conn.get('id')
            conn_data = dialog.get_connection_data()
            self.connection_manager.update_connection(conn_id, conn_data)
            self.load_connections()

    def delete_connection(self, conn):
        """删除连接"""
        conn_id = conn.get('id')
        name = conn.get('name', '')

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除连接 '{name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.connection_manager.delete_connection(conn_id)
            self.load_connections()

    def set_connection_type(self, connection_type):
        """设置连接类型（用于外部调用）"""
        pass

    def closeEvent(self, event):
        # 关闭所有会话
        for sid, sess in list(self.sessions.items()):
            sess['tab'].disconnect()
        event.accept()


class ConnectionDialog(QDialog):
    """新建/编辑连接对话框"""
    def __init__(self, parent=None, connection=None):
        super().__init__(parent)
        self.connection = connection
        self.init_ui()

    def init_ui(self):
        title = "编辑连接" if self.connection else "新建连接"
        self.setWindowTitle(title)
        self.setGeometry(300, 300, 400, 350)
        self.setStyleSheet("""
            QDialog {
                background-color: #2d2d30;
            }
            QLabel {
                color: #cccccc;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #3d3d40;
                color: #cccccc;
                border: 1px solid #555555;
                padding: 5px;
            }
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Connection name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("连接名称:"))
        self.name_input = QLineEdit()
        if self.connection:
            self.name_input.setText(self.connection.get('name', ''))
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # Connection type
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("连接类型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["ssh", "telnet", "serial"])
        if self.connection:
            self.type_combo.setCurrentText(self.connection.get('type', 'ssh'))
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        type_layout.addWidget(self.type_combo)
        layout.addLayout(type_layout)

        # Config area
        self.config_widget = QWidget()
        self.config_layout = QFormLayout(self.config_widget)
        self.config_layout.setSpacing(8)

        # SSH/Telnet config fields
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("主机地址")
        self.config_layout.addRow("主机:", self.host_input)

        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(22)
        self.config_layout.addRow("端口:", self.port_input)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("用户名")
        self.config_layout.addRow("用户名:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("密码")
        self.config_layout.addRow("密码:", self.password_input)

        # SSH key file config (hidden by default)
        self.key_file_input = QLineEdit()
        self.key_file_input.setPlaceholderText("密钥文件路径")
        self.key_file_input.hide()
        
        self.key_browse_btn = QPushButton("浏览...")
        self.key_browse_btn.setFixedWidth(60)
        self.key_browse_btn.clicked.connect(self.browse_key_file)
        self.key_browse_btn.hide()
        
        key_file_row_widget = QWidget()
        key_file_row_layout = QHBoxLayout(key_file_row_widget)
        key_file_row_layout.setContentsMargins(0, 0, 0, 0)
        key_file_row_layout.addWidget(self.key_file_input)
        key_file_row_layout.addWidget(self.key_browse_btn)
        self.config_layout.addRow("密钥文件:", key_file_row_widget)

        # Serial config fields (hidden by default)
        self.serial_port_combo = QComboBox()
        self.serial_port_combo.addItems([f'COM{i}' for i in range(1, 21)])
        self.serial_port_combo.hide()
        self.serial_port_label = QLabel("串口:")
        self.serial_port_label.hide()
        self.config_layout.addRow(self.serial_port_label, self.serial_port_combo)

        self.serial_baud_combo = QComboBox()
        self.serial_baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.serial_baud_combo.setCurrentText("115200")
        self.serial_baud_combo.hide()
        self.serial_baud_label = QLabel("波特率:")
        self.serial_baud_label.hide()
        self.config_layout.addRow(self.serial_baud_label, self.serial_baud_combo)

        layout.addWidget(self.config_widget)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d40;
            }
            QPushButton:hover {
                background-color: #4d4d50;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        if self.connection:
            self.load_connection_config()
        
        self.on_type_changed(self.type_combo.currentText())

    def on_type_changed(self, conn_type):
        """根据连接类型切换配置字段"""
        self.serial_port_combo.hide()
        self.serial_port_label.hide()
        self.serial_baud_combo.hide()
        self.serial_baud_label.hide()
        
        # 隐藏密钥相关字段
        self.key_file_input.hide()
        self.key_browse_btn.hide()
        
        if conn_type == "serial":
            self.host_input.hide()
            self.port_input.hide()
            self.username_input.hide()
            self.password_input.hide()
            
            self.serial_port_combo.show()
            self.serial_port_label.show()
            self.serial_baud_combo.show()
            self.serial_baud_label.show()
            
            self.port_input.setValue(115200)
        else:
            self.host_input.show()
            self.port_input.show()
            self.username_input.show()
            self.password_input.hide() if conn_type == "telnet" else self.password_input.show()
            
            if conn_type == "ssh":
                self.port_input.setValue(22)
                self.key_file_input.show()
                self.key_browse_btn.show()
            elif conn_type == "telnet":
                self.port_input.setValue(23)

    def load_connection_config(self):
        """加载现有连接配置"""
        conn_type = self.connection.get('type', 'ssh')
        config = self.connection.get('config', {})

        if conn_type == "ssh":
            self.host_input.setText(config.get('host', ''))
            self.port_input.setValue(config.get('port', 22))
            self.username_input.setText(config.get('username', ''))
            self.password_input.setText(config.get('password', ''))
            self.key_file_input.setText(config.get('key_file', ''))
        elif conn_type == "telnet":
            self.host_input.setText(config.get('host', ''))
            self.port_input.setValue(config.get('port', 23))
            self.username_input.setText(config.get('username', ''))
            self.password_input.setText(config.get('password', ''))
        elif conn_type == "serial":
            self.serial_port_combo.setCurrentText(config.get('port', 'COM1'))
            self.serial_baud_combo.setCurrentText(str(config.get('baud', 115200)))

    def browse_key_file(self):
        """浏览选择密钥文件"""
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择密钥文件", 
            "", 
            "密钥文件 (*.pem *.key);;所有文件 (*)"
        )
        if file_path:
            self.key_file_input.setText(file_path)

    def get_connection_data(self):
        """获取连接数据"""
        conn_type = self.type_combo.currentText()

        if conn_type == "ssh":
            config = {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text(),
                'key_file': self.key_file_input.text()
            }
        elif conn_type == "telnet":
            config = {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            }
        else:
            config = {
                'port': self.serial_port_combo.currentText(),
                'baud': int(self.serial_baud_combo.currentText())
            }

        return {
            'name': self.name_input.text(),
            'type': conn_type,
            'config': config
        }


class SFTPDialog(QDialog):
    """SFTP文件传输对话框"""
    def __init__(self, connection_context, parent=None):
        super().__init__(parent)
        self.connection_context = connection_context
        self.sftp = None
        self.current_remote_dir = "/home/"
        self.init_ui()
        self.init_sftp()

    def init_ui(self):
        self.setWindowTitle("SFTP 文件传输")
        self.setGeometry(300, 300, 700, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #2d2d30;
            }
            QLabel {
                color: #cccccc;
            }
            QLineEdit {
                background-color: #3d3d40;
                color: #cccccc;
                border: 1px solid #555555;
                padding: 5px;
            }
            QListWidget {
                background-color: #1e1e1e;
                color: #cccccc;
                border: 1px solid #3d3d40;
            }
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QListWidget::item:selected {
                background-color: #007acc;
            }
            QListWidget::item:hover {
                background-color: #3d3d40;
            }
        """)

        layout = QVBoxLayout(self)

        # 连接状态
        self.status_label = QLabel("SFTP状态: 未连接")
        self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        layout.addWidget(self.status_label)

        # 本地路径
        local_layout = QHBoxLayout()
        local_layout.addWidget(QLabel("本地路径:"))
        self.local_path = QLineEdit()
        self.local_path.setText(os.path.expanduser("~"))
        local_layout.addWidget(self.local_path)
        self.local_browse_btn = QPushButton("浏览...")
        self.local_browse_btn.setFixedWidth(80)
        self.local_browse_btn.clicked.connect(self.browse_local)
        local_layout.addWidget(self.local_browse_btn)
        layout.addLayout(local_layout)

        # 远程路径
        remote_layout = QHBoxLayout()
        remote_layout.addWidget(QLabel("远程路径:"))
        self.remote_path = QLineEdit()
        self.remote_path.setText(self.current_remote_dir)
        self.remote_path.returnPressed.connect(self.on_remote_path_changed)
        remote_layout.addWidget(self.remote_path)
        layout.addLayout(remote_layout)

        # 文件列表
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.on_item_double_click)
        layout.addWidget(self.file_list)

        # 按钮
        btn_layout = QHBoxLayout()
        self.upload_btn = QPushButton("上传到远程")
        self.download_btn = QPushButton("下载到本地")
        self.refresh_btn = QPushButton("刷新列表")
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d40;
            }
        """)
        btn_layout.addWidget(self.upload_btn)
        btn_layout.addWidget(self.download_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.upload_btn.clicked.connect(self.upload)
        self.download_btn.clicked.connect(self.download)
        self.refresh_btn.clicked.connect(self.refresh)
        close_btn.clicked.connect(self.close)

    def init_sftp(self):
        """初始化SFTP连接"""
        strategy = self.connection_context._strategy
        if not isinstance(strategy, SSHConnection):
            self.status_label.setText("SFTP状态: 仅支持SSH连接")
            self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
            self.set_buttons_enabled(False)
            return

        if not strategy.client:
            self.status_label.setText("SFTP状态: SSH未连接")
            self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
            self.set_buttons_enabled(False)
            return

        try:
            self.sftp = strategy.client.open_sftp()
            self.current_remote_dir = self.sftp.normalize(".")
            self.remote_path.setText(self.current_remote_dir)
            self.status_label.setText(f"SFTP状态: 已连接 ({strategy.host})")
            self.status_label.setStyleSheet("color: #00ff00; font-weight: bold;")
            self.refresh()
        except Exception as e:
            self.status_label.setText(f"SFTP状态: 连接失败 ({str(e)})")
            self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
            self.set_buttons_enabled(False)

    def set_buttons_enabled(self, enabled):
        """设置按钮状态"""
        self.upload_btn.setEnabled(enabled)
        self.download_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)

    def browse_local(self):
        """浏览本地目录"""
        directory = QFileDialog.getExistingDirectory(self, "选择本地目录", self.local_path.text())
        if directory:
            self.local_path.setText(directory)

    def on_remote_path_changed(self):
        """远程路径改变"""
        path = self.remote_path.text()
        if path:
            self.current_remote_dir = path
            self.refresh()

    def on_item_double_click(self, item):
        """双击进入目录"""
        if not self.sftp:
            return

        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data['type'] == 'dir':
            self.current_remote_dir = data['path']
            self.remote_path.setText(self.current_remote_dir)
            self.refresh()
        elif data['type'] == 'parent':
            # 返回上级目录
            try:
                parent = self.sftp.normalize("..")
                self.current_remote_dir = parent
                self.remote_path.setText(self.current_remote_dir)
                self.refresh()
            except:
                pass

    def refresh(self):
        """刷新远程文件列表"""
        self.file_list.clear()

        if not self.sftp:
            self.file_list.addItem("SFTP未连接")
            return

        try:
            # 添加上级目录
            parent_item = QListWidgetItem("../")
            parent_item.setData(Qt.ItemDataRole.UserRole, {'type': 'parent'})
            self.file_list.addItem(parent_item)

            # 列出文件
            for entry in self.sftp.listdir_attr(self.current_remote_dir):
                name = entry.filename
                if S_ISDIR(entry.st_mode):
                    name += "/"
                    icon = "[目录] "
                else:
                    icon = "[文件] "

                size = self.format_size(entry.st_size) if not S_ISDIR(entry.st_mode) else ""
                item_text = f"{icon}{name:<30} {size}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, {
                    'type': 'dir' if S_ISDIR(entry.st_mode) else 'file',
                    'name': entry.filename,
                    'path': f"{self.current_remote_dir}/{entry.filename}".replace("//", "/"),
                    'size': entry.st_size
                })
                self.file_list.addItem(item)

            self.status_label.setText(f"SFTP状态: 已连接 - {self.current_remote_dir}")
        except Exception as e:
            self.file_list.addItem(f"错误: {str(e)}")

    def format_size(self, size):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def upload(self):
        """上传文件到远程"""
        if not self.sftp:
            QMessageBox.warning(self, "警告", "SFTP未连接")
            return

        local_file, _ = QFileDialog.getOpenFileName(self, "选择要上传的文件", self.local_path.text())
        if not local_file:
            return

        filename = os.path.basename(local_file)
        remote_file = f"{self.current_remote_dir}/{filename}".replace("//", "/")

        try:
            self.sftp.put(local_file, remote_file)
            QMessageBox.information(self, "成功", f"上传完成:\n{filename}")
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"上传失败:\n{str(e)}")

    def download(self):
        """下载文件到本地"""
        if not self.sftp:
            QMessageBox.warning(self, "警告", "SFTP未连接")
            return

        item = self.file_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择要下载的文件")
            return

        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data['type'] != 'file':
            QMessageBox.information(self, "提示", "只能选择文件进行下载")
            return

        local_dir = self.local_path.text()
        if not os.path.isdir(local_dir):
            QMessageBox.warning(self, "警告", "本地路径不是有效目录")
            return

        local_file = os.path.join(local_dir, data['name'])

        try:
            self.sftp.get(data['path'], local_file)
            QMessageBox.information(self, "成功", f"下载完成:\n{data['name']}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"下载失败:\n{str(e)}")

    def closeEvent(self, event):
        """关闭时清理SFTP连接"""
        if self.sftp:
            try:
                self.sftp.close()
            except:
                pass
        event.accept()
