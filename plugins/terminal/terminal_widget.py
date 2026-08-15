import os
import posixpath
import re
import threading
import time
import uuid
from stat import S_ISDIR
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QLabel, QLineEdit, QComboBox, QSpinBox, QPushButton,
    QTextEdit, QTabWidget, QTabBar, QMessageBox, QCheckBox,
    QListWidget, QListWidgetItem, QMenu, QDialog,
    QPlainTextEdit, QFileDialog, QProgressDialog, QApplication,
    QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QFont, QAction, QTextCursor, QColor, QKeyEvent, QTextCharFormat, QCursor
from .connection_context import ConnectionContext
from .ssh_connection import SSHConnection
from .telnet_connection import TelnetConnection
from .serial_connection import SerialConnection
from .connection_manager import ConnectionManager
from .connection_factory import ConnectionFactory
from .ansi_parser import ANSIParser
from plugins.script_runner import Session, ScriptRunner

# 下拉框三角形箭头图片路径
_DOWN_ARROW_IMG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'assets', 'down_arrow.png'
).replace('\\', '/')


class TerminalPlugin:
    def __init__(self, config, config_manager=None, plugin_manager=None):
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = TerminalWidget(self.config, self._config_manager, self._plugin_manager)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass

    # 终端工具支持的字体大小档位（与 show_font_size_menu 保持一致）
    _FONT_SIZES = [
        ("8px", 8),
        ("10px", 10),
        ("11px", 11),
        ("12px", 12),
        ("14px", 14),
        ("16px", 16),
        ("18px", 18),
        ("20px", 20),
    ]

    def register_menus(self, registry):
        """向框架菜单栏注册终端工具的菜单项。

        注册一个「终端」顶级菜单，包含：
          - 刷新列表（F5）
          - 字体大小（子菜单，单选互斥）
          - 颜色显示（可勾选开关）

        菜单在每次重建（含主题切换）时由框架重新收集，
        因此 checked 状态会读取 widget 的最新值。
        """
        widget = self.get_widget()
        current_size = getattr(widget, 'current_font_size', 11)
        color_enabled = getattr(widget, 'color_enabled', True)

        builder = registry.add_menu(self.name, "终端(&T)")
        builder.add_action(
            "刷新列表",
            lambda checked: widget.load_connections(),
            shortcut="F5",
        )
        builder.add_separator()

        # 字体大小子菜单：使用同组名实现单选互斥
        submenu = builder.add_submenu("字体大小")
        for label, size in self._FONT_SIZES:
            submenu.add_action(
                label,
                lambda checked, s=size: widget.set_font_size(s),
                checkable=True,
                checked=(current_size == size),
                group="terminal_font_size",
            )
        submenu.end()

        builder.add_action(
            "颜色显示",
            lambda checked: widget.toggle_color_display(checked),
            checkable=True,
            checked=color_enabled,
        )

        toolbar_visible = getattr(widget, '_button_toolbar_visible', True)
        builder.add_action(
            "按钮工具栏",
            lambda checked: widget.toggle_button_toolbar(checked),
            checkable=True,
            checked=toolbar_visible,
        )


class TerminalEdit(QTextEdit):
    """自定义终端编辑控件，用于拦截键盘事件和输入法输入"""

    key_pressed = pyqtSignal(QKeyEvent)
    input_method_text = pyqtSignal(str)
    paste_text = pyqtSignal(str)

    def __init__(self, color_scheme=None, config_manager=None, parent=None):
        super().__init__(parent)
        self._color_scheme = color_scheme or {}
        self._config_manager = config_manager
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.set_style()

    def set_style(self):
        text_color = self._color_scheme.get('text', self._color_scheme.get('text_primary', '#ffffff'))
        border_focus = self._color_scheme.get('border-focus', self._color_scheme.get('border_focus', '#007acc'))

        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {text_color};
                border: none;
            }}
            QTextEdit:focus {{
                border: 2px solid {border_focus};
            }}
        """)

    def _get_menu_style(self):
        """获取适配主题的右键菜单 CSS 样式"""
        if self._config_manager:
            return self._config_manager.get_menu_css()
        # 降级：使用 color_scheme 中的颜色构建菜单样式
        bg = self._color_scheme.get('bg-tertiary', '#2d2d30')
        color = self._color_scheme.get('text', '#ffffff')
        border = self._color_scheme.get('border-light', '#4a4a4d')
        item_selected_bg = self._color_scheme.get('primary', '#007acc')
        return f"""
            QMenu {{
                background-color: {bg};
                color: {color};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 24px;
                min-width: 100px;
                color: {color};
            }}
            QMenu::item:selected {{
                background-color: {item_selected_bg};
                color: #ffffff;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {border};
                margin: 4px 0;
            }}
        """

    def contextMenuEvent(self, event):
        """重写右键菜单事件，创建适配主题的自定义菜单"""
        from PyQt6.QtGui import QAction, QCursor
        from PyQt6.QtWidgets import QMenu, QApplication

        menu = QMenu(self)
        menu.setStyleSheet(self._get_menu_style())

        # 复制选中内容
        copy_action = QAction("复制", self)
        copy_action.setEnabled(self.textCursor().hasSelection())
        def do_copy():
            selected = self.textCursor().selectedText()
            if selected:
                QApplication.clipboard().setText(selected)
        copy_action.triggered.connect(do_copy)
        menu.addAction(copy_action)

        # 全选
        select_all_action = QAction("全选", self)
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)

        menu.addSeparator()

        # 粘贴（使用自定义 paste 处理，保证文本发送到远端）
        paste_action = QAction("粘贴", self)
        def do_paste():
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            if text:
                self.paste_text.emit(text)
        paste_action.triggered.connect(do_paste)
        menu.addAction(paste_action)

        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        """拦截所有键盘事件并发送给父组件处理"""
        self.key_pressed.emit(event)
        event.accept()

    def event(self, event):
        """拦截Tab键事件，防止焦点切换"""
        if event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Tab:
                self.key_pressed.emit(event)
                event.accept()
                return True
        return super().event(event)

    def inputMethodEvent(self, event):
        """处理输入法输入事件（中文输入）"""
        text = event.commitString()
        if text:
            self.input_method_text.emit(text)
        # 不调用super，避免文本被默认处理插入两次

    def pasteEvent(self, event):
        """拦截粘贴事件，通过信号交由父组件统一处理

        避免右键菜单粘贴的内容只显示在UI上而没有真正发送到远程shell。
        """
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        paste_text = clipboard.text()
        if paste_text:
            self.paste_text.emit(paste_text)
        event.accept()


class ConnectionWorker(QThread):
    """异步连接工作线程

    在后台线程执行阻塞的网络连接操作，避免冻结 UI。
    连接完成（含初始输出读取）后通过信号通知主线程更新 UI。
    """
    connected = pyqtSignal(bool, str, str)  # success, initial_output, error_msg

    def __init__(self, strategy, config, parent=None):
        super().__init__(parent)
        self._strategy = strategy
        self._config = config

    def run(self):
        try:
            success = self._strategy.connect(self._config)
            if not success:
                self.connected.emit(False, "", "连接失败")
                return
            # 等待 shell 初始化并读取初始输出（与原同步逻辑一致）
            time.sleep(0.3)
            initial_output = ""
            if hasattr(self._strategy, 'read_output'):
                try:
                    initial_output = self._strategy.read_output(timeout=0.2) or ""
                except Exception:
                    initial_output = ""
            self.connected.emit(True, initial_output, "")
        except Exception as e:
            self.connected.emit(False, "", str(e))


class ButtonExecutionWorker(QThread):
    """按钮执行工作线程

    在后台线程执行命令或脚本，避免阻塞 UI。
    复用 ConnectionContext.send_command 和 ScriptRunner/Session，不重复实现。
    """
    finished = pyqtSignal(str, dict)  # btn_id, result

    def __init__(self, btn_id, btn_data, session_tab, parent=None):
        super().__init__(parent)
        self._btn_id = btn_id
        self._btn_data = btn_data
        self._session_tab = session_tab

    def run(self):
        try:
            if self._btn_data['type'] == 'command':
                result = self._run_command()
            else:
                result = self._run_script()
        except Exception as e:
            result = {'success': False, 'output': '', 'error': f"{type(e).__name__}: {e}"}
        self.finished.emit(self._btn_id, result)

    def _run_command(self):
        """执行命令 — 复用 ConnectionContext.send_command"""
        cmd = self._btn_data.get('command', '')
        output = self._session_tab.connection_context.send_command(cmd)
        return {'success': True, 'output': output, 'error': '', 'command': cmd}

    def _run_script(self):
        """执行脚本 — 复用 ScriptRunner + Session"""
        script_path = self._btn_data.get('script_path', '')
        with open(script_path, 'r', encoding='utf-8') as f:
            script_content = f.read()
        # ConnectionContext._strategy 兼容 Session 的 connection 参数
        strategy = self._session_tab.connection_context._strategy
        session = Session(strategy, "terminal", {})
        runner = ScriptRunner()
        result = runner.execute(script_content, session)
        return result


class SessionTab(QWidget):
    """单个会话标签页 - 交互式终端"""
    def __init__(self, session_id, session_name, color_scheme=None, config_manager=None, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.session_name = session_name
        self._color_scheme = color_scheme or {}
        self._config_manager = config_manager
        self.connection_context = ConnectionContext()
        self.current_connection = None
        self.command_history = []
        self.history_index = -1
        self.current_input = ""
        self.interactive_mode = False
        self._tab_pending = False  # Tab补全等待标志：下次输出时从display提取补全结果
        # 本地回显消重队列：交互模式下，为消除"输入不及时显示"，用户按键时先本地write_output回显；
        # 等服务器回显到来时，从回显文本头部吸收掉与本地echo相同的部分，防止双显。
        self._local_echo_sent = ""
        # 使用主题文字颜色作为ANSI解析器默认前景色
        text_hex = self._color_scheme.get('text', self._color_scheme.get('text_primary', '#cccccc'))
        # 根据背景色亮度判断主题模式，决定ANSI颜色映射
        is_dark = self._is_dark_theme()
        self.ansi_parser = ANSIParser(default_foreground=QColor(text_hex), is_dark=is_dark)
        self._output_buffer = ""  # 输出缓冲区，用于处理跨数据块的ANSI序列
        self._output_history = []  # 原始输出历史（text, color），用于主题切换时重新渲染
        self._output_history_max = 2000  # 最大历史条目数，防止内存无限增长
        self._connection_lost = False  # 连接中断标志
        self._connection_worker = None  # 异步连接工作线程

        self.init_ui()
    
    def _get_style(self, key, default=None):
        """获取样式配置"""
        value = self._color_scheme.get(key)
        if value is not None:
            return value
        old_key_map = {
            'background_main': 'bg-main',
            'text_primary': 'text',
            'text_success': 'text-success',
            'text_danger': 'text-danger',
            'text_warning': 'text-warning',
            'text_hint': 'text-hint',
            'primary_hover': 'primary-hover'
        }
        if key in old_key_map:
            return self._color_scheme.get(old_key_map[key], default)
        return default

    def _is_dark_theme(self):
        """根据背景色亮度判断是否为深色主题（用于ANSI颜色映射选择）"""
        bg_hex = self._color_scheme.get('bg-main', '#1e1e1e')
        try:
            bg_hex = bg_hex.lstrip('#')
            r = int(bg_hex[0:2], 16)
            g = int(bg_hex[2:4], 16)
            b = int(bg_hex[4:6], 16)
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            return brightness < 128
        except (ValueError, IndexError):
            return True  # 解析失败时默认深色主题

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        text_color = self._color_scheme.get('text', self._color_scheme.get('text_primary', '#ffffff'))
        border = self._color_scheme.get('border', '#3c3c3c')
        border_focus = self._color_scheme.get('border-focus', self._color_scheme.get('border_focus', '#007acc'))
        
        self.terminal_display = TerminalEdit(self._color_scheme, self._config_manager)
        self.terminal_display.setFont(QFont("Consolas", 11))
        self.terminal_display.key_pressed.connect(self.handle_key_press)
        self.terminal_display.input_method_text.connect(self.handle_input_method_text)
        self.terminal_display.paste_text.connect(self.handle_paste_text)
        self.terminal_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {text_color};
                border: 1px solid {border};
                border-radius: 4px;
                margin: 4px;
            }}
            QTextEdit:focus {{
                border: 2px solid {border_focus};
            }}
        """)
        layout.addWidget(self.terminal_display)

        # 状态信息（不再渲染独立状态栏，改为通过框架统一状态接口上报）
        # 保留内部状态字段供现有逻辑使用
        self._status_text = "未连接"
        self._conn_info_text = ""
        self._conn_type_text = ""
        # 兼容字段：保留为隐藏 QLabel 防止外部访问出错
        text_primary = self._color_scheme.get('text', self._color_scheme.get('text_primary', '#ffffff'))
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet(f"color: {text_primary}; font-weight: bold; font-size: 12px;")
        self.connection_info = QLabel("")
        self.connection_type_label = QLabel("")

        # 远程输出轮询定时器
        self.output_timer = QTimer(self)
        self.output_timer.timeout.connect(self.poll_remote_output)

    def resizeEvent(self, event):
        """窗口大小改变时动态调整PTY终端大小，使远程shell感知终端实际宽度"""
        super().resizeEvent(event)
        self._update_terminal_size()

    def _update_terminal_size(self):
        """根据终端显示控件的实际宽度计算列数并调整PTY大小

        解决SSH连接下路径过长无法完整显示的问题：
        远程shell根据PTY宽度决定提示符换行和路径显示，若PTY宽度固定为80列
        而终端实际更宽，长路径会被错误换行或截断。
        """
        if not self.connection_context or not self.connection_context.is_connected():
            return
        if not self.interactive_mode:
            return

        strategy = self.connection_context._strategy
        if not strategy or not hasattr(strategy, 'resize_pty'):
            return

        # 基于字体度量计算终端可显示的列数和行数
        from PyQt6.QtGui import QFontMetrics
        font = self.terminal_display.font()
        fm = QFontMetrics(font)

        # 控件可用宽度（减去边距）
        margins = self.terminal_display.contentsMargins()
        avail_width = self.terminal_display.width() - margins.left() - margins.right() - 10  # 额外留10px余量
        avail_height = self.terminal_display.height() - margins.top() - margins.bottom() - 10

        # 计算列数和行数（确保最小值）
        char_width = fm.horizontalAdvance('M')
        line_height = fm.lineSpacing()
        if char_width <= 0 or line_height <= 0:
            return

        cols = max(20, avail_width // char_width)
        rows = max(5, avail_height // line_height)

        # 避免重复设置相同大小
        prev = getattr(self, '_last_pty_size', None)
        if prev == (cols, rows):
            return
        self._last_pty_size = (cols, rows)

        strategy.resize_pty(width=cols, height=rows)

    def refresh_theme_styles(self):
        """刷新会话标签页的主题样式（主题切换时调用）"""
        text_color = self._color_scheme.get('text', self._color_scheme.get('text_primary', '#ffffff'))
        border = self._color_scheme.get('border', '#3c3c3c')
        border_focus = self._color_scheme.get('border-focus', self._color_scheme.get('border_focus', '#007acc'))

        # 更新终端显示控件样式（透明背景，仅保留边框和文字颜色）
        self.terminal_display._color_scheme = self._color_scheme
        self.terminal_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {text_color};
                border: 1px solid {border};
                border-radius: 4px;
                margin: 4px;
            }}
            QTextEdit:focus {{
                border: 2px solid {border_focus};
            }}
        """)

        # 更新ANSI解析器：默认前景色 + 主题模式（浅色主题下加深白色/黄色等浅色文字）
        self.ansi_parser.default_foreground = QColor(text_color)
        self.ansi_parser.set_theme_mode(self._is_dark_theme())
        self.ansi_parser.reset_format()

        # 重新渲染所有已输出文字，使其使用最新主题颜色
        self._rerender_output()

        # 更新状态标签（根据连接状态选择颜色）
        self._refresh_status_label_style()

    def _rerender_output(self):
        """清空终端显示并从历史缓冲区重新渲染所有文字（主题切换时调用）"""
        if not self._output_history:
            return

        # 保存当前光标位置（是否在末尾）
        cursor = self.terminal_display.textCursor()
        was_at_end = cursor.atEnd()

        # 重置ANSI解析器状态
        self.ansi_parser.reset_format()

        # 重置滚动计数器，避免渲染过程中频繁滚动
        self._scroll_counter = 0

        # 临时禁用自动滚动
        self._rerendering = True

        # 清空显示
        self.terminal_display.clear()

        # 重新渲染所有历史输出
        for text, color in self._output_history:
            self._render_text(text, color)

        # 恢复自动滚动
        self._rerendering = False

        # 滚动到最底部
        self.terminal_display.ensureCursorVisible()

    def _refresh_status_label_style(self):
        """根据连接状态刷新状态标签样式"""
        text_color = self._color_scheme.get('text', self._color_scheme.get('text_primary', '#ffffff'))
        if self._connection_lost:
            # 连接中断：使用危险色
            danger_color = self._get_style('text-danger', '#f44747')
            self.status_label.setStyleSheet(f"color: {danger_color}; font-weight: bold; font-size: 12px;")
        elif self.connection_context.is_connected():
            # 已连接：使用成功色
            success_color = self._get_style('text-success', '#4ec9b0')
            self.status_label.setStyleSheet(f"color: {success_color}; font-weight: bold; font-size: 12px;")
        else:
            # 未连接：使用默认文字色
            self.status_label.setStyleSheet(f"color: {text_color}; font-weight: bold; font-size: 12px;")

    def _set_status(self, text):
        """更新会话状态并上报到框架状态接口"""
        self._status_text = text
        self.status_label.setText(text)
        self._report_status()

    def _set_conn_info(self, text):
        """更新连接信息并上报"""
        self._conn_info_text = text
        self.connection_info.setText(text)
        self._report_status()

    def _set_conn_type(self, text):
        """更新连接类型并上报"""
        self._conn_type_text = text
        self.connection_type_label.setText(text)
        self._report_status()

    def _report_status(self):
        """向框架上报当前会话的合并状态文本"""
        parts = [self._status_text]
        if self._conn_info_text:
            parts.append(self._conn_info_text)
        if self._conn_type_text:
            parts.append(self._conn_type_text)
        status = " | ".join(parts)
        # 向上委托给 TerminalWidget，再由其调用框架状态接口
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_report_session_status'):
                parent._report_session_status(status)
                return
            parent = parent.parent()

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
        if not text:
            return

        # 记录原始输出到历史缓冲区（用于主题切换时重新渲染）
        # 保存 \r\n 替换前的原始文本，确保 ANSI 序列完整保留
        self._output_history.append((text, color))
        if len(self._output_history) > self._output_history_max:
            # 超出限制时丢弃最旧的部分
            self._output_history = self._output_history[-self._output_history_max:]

        self._render_text(text, color)

    def _render_text(self, text, color=None):
        """将文本渲染到终端显示控件（内部方法，不记录历史）

        color 参数支持两种形式：
        - 颜色键名（如 'text-info', 'text-success'）：每次渲染时从当前主题实时解析
        - 十六进制颜色值（如 '#007acc'）：直接使用
        - None：使用ANSI解析器处理
        """
        if not text:
            return

        cursor = self.terminal_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # 先处理回车符 \r\n -> \n, 然后处理单独的 \r
        text = text.replace('\r\n', '\n')

        # 解析颜色：若为颜色键名则从当前主题获取，若为十六进制值则直接使用
        if color:
            resolved = color if color.startswith('#') else self._get_style(color, color)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(resolved))
            cursor.setCharFormat(fmt)
            self._insert_text_with_cr(cursor, text)
            # —— color 分支代表"程序主动写入的系统提示文本"（非服务器ANSI回显）
            #    完成后强制重置 cursor 格式 + ANSI parser 格式，
            #    避免颜色格式残留，污染后续服务器返回的 ANSI 输出。
            if self.ansi_parser.enable_color:
                self.ansi_parser.reset_format()
                cursor.setCharFormat(self.ansi_parser.get_current_format())
        else:
            # 使用ANSI解析器处理转义序列
            parts = self.ansi_parser.parse(text)
            for part_text, part_format in parts:
                cursor.setCharFormat(part_format)
                self._insert_text_with_cr(cursor, part_text)

        self.terminal_display.setTextCursor(cursor)
        # 仅在需要时滚动，减少频繁调用
        if self._should_scroll():
            self.terminal_display.ensureCursorVisible()

        # 更新current_input：仅在Tab补全等待状态下从显示内容提取
        # 交互模式下current_input由本地按键追踪维护，减少对display解析的依赖
        if getattr(self, '_tab_pending', False):
            self._update_current_input_from_display()
            self._tab_pending = False

    def _update_current_input_from_display(self):
        """从显示内容中更新current_input（处理Tab补全等场景）

        策略：**只在最后一行能明确识别到提示符时才更新**，
        任何识别失败的情况都直接返回，绝不修改 current_input，
        避免"把服务器输出当作用户输入"或"错误清空current_input"导致的删除异常。
        """
        import re
        plain_text = self.terminal_display.toPlainText()
        lines = plain_text.split('\n')
        if not lines:
            return

        last_line = lines[-1]

        # 查找提示符位置（常见提示符：# $ > %）
        prompt_patterns = [
            r'^\s*[\w@.-]+[\s]*:[\s]*[\w/~.@-]*\s*[#$>%]\s*',  # user@host:path$ 形式
            r'^\s*[A-Za-z0-9_.\-]+[#$>%]\s+',                    # 简化提示符 xxx$ 
            r'^\s*[#$>%]\s+',                                      # 最简 $ 
        ]

        for pattern in prompt_patterns:
            match = re.match(pattern, last_line)
            if match:
                self.current_input = last_line[match.end():]
                # 检测到提示符说明命令已结束，重置ANSI颜色格式，避免颜色跨命令残留
                if self.ansi_parser.enable_color:
                    self.ansi_parser.reset_format()
                return

        # ============================================================
        # 未找到提示符 → 保守策略：直接 return，保持原来的 current_input 不变
        # 不做"往前5行回溯查找 + 强制赋值last_line"这类高风险操作
        # ============================================================
        return

    def _should_scroll(self):
        """判断是否需要滚动到可见区域"""
        # 重新渲染时不滚动（最后统一滚动）
        if getattr(self, '_rerendering', False):
            return False
        # 使用计数器减少滚动频率
        if not hasattr(self, '_scroll_counter'):
            self._scroll_counter = 0
        self._scroll_counter += 1
        # 每5次输出才滚动一次
        return self._scroll_counter % 5 == 0

    def _insert_text_with_cr(self, cursor, text):
        """插入文本，处理 \r 回车符、\b 退格符、\t 制表符等控制字符"""
        if '\r' not in text and '\b' not in text and '\x7f' not in text and '\t' not in text and '\x1b' not in text:
            cursor.insertText(text)
            return
        
        i = 0
        while i < len(text):
            if text[i] == '\r':
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                i += 1
            elif text[i] == '\b':
                if i + 2 < len(text) and text[i+1] == ' ' and text[i+2] == '\b':
                    if cursor.position() > 0:
                        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                    i += 3
                elif i + 1 < len(text) and text[i+1] == '\b':
                    if cursor.position() > 0:
                        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                    if cursor.position() > 0:
                        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                    i += 2
                else:
                    if cursor.position() > 0:
                        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                    i += 1
            elif text[i] == '\x7f':
                # DEL：删除光标右侧字符；只要还没到文档真正末尾（characterCount包含末尾不可见段落标记）
                # 就允许删除（避免原条件 position < count-1 把"倒数第一个可见字符前"的删除也拦截掉）
                total = cursor.document().characterCount()
                if cursor.position() < total - 1:  # 右侧至少还有一个真正可见的字符
                    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                i += 1
            elif text[i] == '\t':
                cursor.insertText("    ")
                i += 1
            elif text[i] == '\x1b':
                seq_end = i + 1
                if seq_end < len(text) and text[seq_end] == '[':
                    seq_end += 1
                    while seq_end < len(text) and (text[seq_end].isdigit() or text[seq_end] == ';'):
                        seq_end += 1
                    if seq_end < len(text) and text[seq_end].isalpha():
                        seq_end += 1
                elif seq_end < len(text) and text[seq_end].isalpha():
                    seq_end += 1
                
                if seq_end > i:
                    ansi_seq = text[i:seq_end]
                    self._apply_cursor_sequence(cursor, ansi_seq)
                i = seq_end
            else:
                next_control = len(text)
                for j in range(i, len(text)):
                    if text[j] in '\r\b\x7f\t\x1b':
                        next_control = j
                        break
                if next_control > i:
                    cursor.insertText(text[i:next_control])
                i = next_control
    
    def _apply_cursor_sequence(self, cursor, seq):
        """应用ANSI光标移动序列"""
        if not seq or seq[0] != '\x1b':
            return
        
        if seq.startswith('\x1b['):
            # CSI序列
            if len(seq) >= 3:
                params_part = seq[2:-1]
                end_char = seq[-1]
                
                # 解析参数
                params = []
                if params_part:
                    params = [int(p) for p in params_part.split(';') if p.isdigit()]
                
                # 光标移动命令
                if end_char == 'A':
                    # 上移
                    count = params[0] if params else 1
                    for _ in range(count):
                        cursor.movePosition(QTextCursor.MoveOperation.Up)
                elif end_char == 'B':
                    # 下移
                    count = params[0] if params else 1
                    for _ in range(count):
                        cursor.movePosition(QTextCursor.MoveOperation.Down)
                elif end_char == 'C':
                    # 右移
                    count = params[0] if params else 1
                    for _ in range(count):
                        cursor.movePosition(QTextCursor.MoveOperation.Right)
                elif end_char == 'D':
                    # 左移
                    count = params[0] if params else 1
                    for _ in range(count):
                        cursor.movePosition(QTextCursor.MoveOperation.Left)
                elif end_char in ('H', 'f'):
                    # 移动到指定位置
                    if len(params) >= 2:
                        row, col = params[0], params[1]
                        cursor.movePosition(QTextCursor.MoveOperation.Start)
                        for _ in range(row - 1):
                            cursor.movePosition(QTextCursor.MoveOperation.Down)
                        for _ in range(col - 1):
                            cursor.movePosition(QTextCursor.MoveOperation.Right)
                    else:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                elif end_char == 'J':
                    # 清屏
                    if params and params[0] == 2:
                        cursor.select(QTextCursor.SelectionType.Document)
                        cursor.removeSelectedText()
                    elif params and params[0] == 1:
                        cursor.movePosition(QTextCursor.MoveOperation.Start)
                        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                    else:
                        cursor.movePosition(QTextCursor.MoveOperation.End)
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                elif end_char == 'K':
                    # 清除行
                    if params and params[0] == 2:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                    elif params and params[0] == 1:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()
                    else:
                        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
                        cursor.removeSelectedText()

    def make_format(self, color):
        """创建文本格式"""
        from PyQt6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        return fmt

    def poll_remote_output(self):
        """轮询远程输出（交互模式），使用缓冲区处理跨数据块的ANSI序列"""
        if not self.connection_context.is_connected():
            # 连接已断开，检测是否为意外中断（非用户主动断开）
            if not self._connection_lost and self.interactive_mode:
                self._on_connection_lost()
            return

        strategy = self.connection_context._strategy
        if hasattr(strategy, 'read_output'):
            # 批量读取，减少调用次数
            total_output = ""
            max_reads = 3  # 每次最多读取3次

            for _ in range(max_reads):
                output = strategy.read_output(timeout=0.05)
                if output:
                    total_output += output
                else:
                    break

            if total_output:
                self._output_buffer += total_output
                self._flush_output_buffer()

            # 读取后再次检查连接状态（可能在读取过程中连接已断开）
            if not self.connection_context.is_connected() and not self._connection_lost:
                self._on_connection_lost()

    def _on_connection_lost(self):
        """处理连接意外中断"""
        self._connection_lost = True
        self.output_timer.stop()
        self.interactive_mode = False

        # 在终端中显示连接中断提示（使用颜色键名，主题切换时可自动重新解析）
        separator = "═" * 50
        self.write_output(f"\n{separator}\n", 'text-danger')
        self.write_output("⚠ 连接已中断\n", 'text-danger')
        self.write_output("远程连接已断开，可能是网络故障或服务器关闭了连接\n", 'text-warning')
        self.write_output("如需重新连接，请点击左侧「新建连接」或右键选择「编辑连接」\n", 'text-hint')
        self.write_output(f"{separator}\n", 'text-danger')

        # 更新状态显示
        self._set_status("连接中断")
        self._refresh_status_label_style()

        # 更新标签页标题（添加中断标记）
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_update_session_tab_title'):
                parent._update_session_tab_title(self, connection_lost=True)
                break
            parent = parent.parent()

    @staticmethod
    def _strip_ansi(s):
        """移除字符串中的 ANSI 转义序列（CSI、OSC 等），返回纯文本。

        用于服务器回显与本地echo对比（本地echo不含ANSI）。
        """
        import re
        # CSI：\x1b [ ... [a-zA-Z@]   OSC：\x1b ] ... \x07 / \x1b \\
        # 以及 Fe 单字控制符（单独ESC加一个字母）：简单处理
        s = re.sub(r'\x1b\[[0-9:;<=>?]*[ -/]*[@-~]', '', s)  # CSI
        s = re.sub(r'\x1b\][^\x07]*(\x07|\x1b\\)', '', s)     # OSC 终止于 BEL 或 ST
        s = re.sub(r'\x1b[][A-Za-z0-9^_]', '', s)             # 简单Fe序列
        return s

    def _echo_suppress(self, raw_data):
        """echo suppression（回显消重）

        交互模式下用户按键时本地已即时回显，服务器回显到达时需要消重。
        支持部分匹配：服务器可能分多次发送回显（逐字符或分块），只要
        raw_data 的纯文本前缀与 _local_echo_sent 的前缀有公共部分就消耗它。

        返回：(剩余文本, 是否消耗了echo)
        """
        echo = getattr(self, '_local_echo_sent', '')
        if not echo:
            return raw_data, False
        stripped = self._strip_ansi(raw_data)
        if not stripped:
            return raw_data, False

        # ---- 计算最长公共前缀 ----
        common_len = 0
        min_len = min(len(stripped), len(echo))
        while common_len < min_len and stripped[common_len] == echo[common_len]:
            common_len += 1

        if common_len == 0:
            # 无任何公共前缀 → 服务器输出了其他内容，echo 过期
            self._local_echo_sent = ""
            return raw_data, False

        # ---- 从 raw_data 中消耗 common_len 个非 ANSI 字符 ----
        consume_count = common_len
        i = 0
        seen = 0
        n = len(raw_data)
        while i < n and seen < consume_count:
            c = raw_data[i]
            if c == '\x1b':
                if i + 1 < n and raw_data[i + 1] == '[':
                    j = i + 2
                    while j < n:
                        if raw_data[j].isalpha() or raw_data[j] == '@':
                            i = j + 1
                            break
                        j += 1
                    else:
                        i += 1
                elif i + 1 < n and raw_data[i + 1] == ']':
                    j = i + 2
                    while j < n:
                        if raw_data[j] == '\x07':
                            i = j + 1
                            break
                        if raw_data[j] == '\x1b' and j + 1 < n and raw_data[j + 1] == '\\':
                            i = j + 2
                            break
                        j += 1
                    else:
                        i += 1
                else:
                    i += 2
            else:
                seen += 1
                i += 1

        # 保留 echo 中未被消耗的尾部，供下次消重使用
        self._local_echo_sent = echo[common_len:]
        return raw_data[i:], True

    def _flush_output_buffer(self):
        """刷新输出缓冲区，处理不完整的ANSI序列

        关键修复：
        1) 删除"退格序列等待"逻辑——\b 本身是单字符完整的控制符，不需要等待，
           否则会出现"按Backspace界面不更新，卡住一段时间"的错觉/死等。
        2) ANSI CSI 序列完整性判断：结尾字符只需是字母 [a-zA-Z@]，
           原正则把 CSI 结尾字母枚举不全，并且混入了毫无意义的 `|n$`，
           导致大量合法 CSI 序列被错误判定为"不完整"，永远滞留在缓冲区。
        3) 本地即时回显 + echo suppression：用户按键时本地立刻显示，
           服务器回显到达时消重，既消除输入延迟感，又避免双显。
        """
        if not self._output_buffer:
            return

        # ============================================================
        # 1. 缓冲区末尾只有单独 ESC (\x1b) —— 等后续字符再判断序列类型
        # ============================================================
        if self._output_buffer.endswith('\x1b'):
            complete_part = self._output_buffer[:-1]
            self._output_buffer = '\x1b'
            if complete_part:
                complete_part, _ = self._echo_suppress(complete_part)
                if complete_part:
                    self.write_output(complete_part)
            return

        # ============================================================
        # 2. 缓冲区中包含 ESC，判断最后一个转义序列是否完整
        # ============================================================
        last_esc = self._output_buffer.rfind('\x1b')
        if last_esc != -1:
            after_esc = self._output_buffer[last_esc:]
            # 2a) CSI 序列：\x1b [ 参数 ; 参数 ... 结尾字母([a-zA-Z@])
            if len(after_esc) >= 2 and after_esc[1] == '[':
                # 判断是否以合法 CSI 结尾字符收尾（字母 A-Za-z 或 @）
                if len(after_esc) < 3 or not (after_esc[-1].isalpha() or after_esc[-1] == '@'):
                    # 序列不完整 → 输出 ESC 前的内容，把不完整序列留在缓冲区
                    complete_part = self._output_buffer[:last_esc]
                    self._output_buffer = after_esc
                    if complete_part:
                        complete_part, _ = self._echo_suppress(complete_part)
                        if complete_part:
                            self.write_output(complete_part)
                    return
            # 2b) 只有单独 ESC （尚未出现后续控制字符）
            elif len(after_esc) == 1:
                complete_part = self._output_buffer[:last_esc]
                self._output_buffer = after_esc
                if complete_part:
                    complete_part, _ = self._echo_suppress(complete_part)
                    if complete_part:
                        self.write_output(complete_part)
                return

        # ============================================================
        # 3. 缓冲区数据完整 → echo suppression 后全部输出
        # ============================================================
        complete_data = self._output_buffer
        self._output_buffer = ""
        complete_data, _ = self._echo_suppress(complete_data)
        if complete_data:
            self.write_output(complete_data)

    def handle_key_press(self, event):
        """处理键盘事件"""
        if not self.connection_context.is_connected():
            return

        key = event.key()
        text = event.text()
        modifiers = event.modifiers()

        strategy = self.connection_context._strategy
        has_raw = hasattr(strategy, 'send_raw') and self.interactive_mode

        if key == Qt.Key.Key_C and modifiers == Qt.KeyboardModifier.ControlModifier:
            if has_raw:
                strategy.send_raw("\x03")
            return

        # 粘贴：Ctrl+V 或 Shift+Insert — 统一交给 handle_paste_text 处理
        if (key == Qt.Key.Key_V and modifiers == Qt.KeyboardModifier.ControlModifier) or \
           (key == Qt.Key.Key_Insert and modifiers == Qt.KeyboardModifier.ShiftModifier):
            clipboard = QApplication.clipboard()
            paste_text = clipboard.text()
            if paste_text:
                self.handle_paste_text(paste_text)
            return

        if key == Qt.Key.Key_D and modifiers == Qt.KeyboardModifier.ControlModifier:
            if has_raw:
                strategy.send_raw("\x04")
            return

        if key == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier:
            if has_raw:
                strategy.send_raw("\x1a")
            return

        if key == Qt.Key.Key_L and modifiers == Qt.KeyboardModifier.ControlModifier:
            if has_raw:
                strategy.send_raw("\x0c")
            return

        # 方向键 - 交互模式下完全由远程控制光标位置
        if key == Qt.Key.Key_Up:
            if has_raw:
                strategy.send_raw("\x1b[A")
                # 上下方向键浏览历史命令，需要从display提取服务器回显的内容
                self._tab_pending = True
            return
        elif key == Qt.Key.Key_Down:
            if has_raw:
                strategy.send_raw("\x1b[B")
                self._tab_pending = True
            return
        elif key == Qt.Key.Key_Left:
            if has_raw:
                strategy.send_raw("\x1b[D")
            return
        elif key == Qt.Key.Key_Right:
            if has_raw:
                strategy.send_raw("\x1b[C")
            return

        if key == Qt.Key.Key_Home:
            if has_raw:
                strategy.send_raw("\x1b[H")
            return
        elif key == Qt.Key.Key_End:
            if has_raw:
                strategy.send_raw("\x1b[F")
            return

        if key == Qt.Key.Key_PageUp:
            if has_raw:
                strategy.send_raw("\x1b[5~")
            return
        elif key == Qt.Key.Key_PageDown:
            if has_raw:
                strategy.send_raw("\x1b[6~")
            return

        if key == Qt.Key.Key_Tab:
            if has_raw:
                strategy.send_raw("\t")
                # 设置Tab补全等待标志，下次输出时从display提取补全后的内容
                self._tab_pending = True
            return

        if key == Qt.Key.Key_Escape:
            if has_raw:
                strategy.send_raw("\x1b")
            return

        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if has_raw:
                strategy.send_raw("\n")
                # 本地即时回显换行：避免用户按回车后没有视觉反馈，消除"按回车没反应"的卡顿感
                self.write_output('\n', 'text')
                # 追踪 \r\n 用于 echo suppression（服务器回显通常为 \r\n，与本地回显的 \n 对齐消重）
                self._local_echo_sent += '\r\n'
                # 交互模式下清空本地输入追踪 + 重置ANSI颜色格式
                # （作为颜色泄漏的防护层：命令提交时强制重置一次，防止上一条命令的颜色泄漏到下一条）
                self.current_input = ""
                if self.ansi_parser.enable_color:
                    self.ansi_parser.reset_format()
            else:
                self.execute_command()
            return

        # 退格 / 删除
        if key == Qt.Key.Key_Backspace:
            if has_raw:
                # 交互模式下始终发送退格符，交给服务器维护真正的输入缓冲区
                # （避免因 current_input 与服务器回显不同步，导致"门禁判断"把退格拦截，造成删不掉）
                strategy.send_raw(self._get_backspace_char())
                # 本地仅做"尽力而为"的同步截断：非空时才删，防止负索引
                if self.current_input:
                    self.current_input = self.current_input[:-1]
                # 本地即时显示退格效果：\b 移动光标 + 空格覆盖 + 再 \b 移回
                #   —— 避免用户感觉"按了退格键没反应"，要等服务器回显才更新
                self.write_output('\b \b', 'text')
                # 同步维护本地echo消重队列：如果有尚未被服务器吸收的本地echo，
                # 把最末尾的一个字符砍掉，保证后续服务器回显消重时长度一致。
                if self._local_echo_sent:
                    self._local_echo_sent = self._local_echo_sent[:-1]
            elif len(self.current_input) > 0:
                self.current_input = self.current_input[:-1]
                self.redraw_input_line()
            return
        elif key == Qt.Key.Key_Delete:
            if has_raw:
                strategy.send_raw("\x1b[3~")
            return

        # 普通字符
        if text:
            if has_raw:
                strategy.send_raw(text)
                # 交互模式下本地追踪用户输入，与服务器回显分离维护
                self.current_input += text
                # 本地即时回显：保证用户一按键就能看到字符，消除"输入不及时显示"的延迟感。
                # 后续服务器回显到达时，会通过 _local_echo_sent 匹配消重，避免双显。
                self.write_output(text, 'text')
                self._local_echo_sent += text
            else:
                self.current_input += text
                self.write_output(text, 'text')
    
    def _get_backspace_char(self):
        """获取退格字符，支持配置或自动检测"""
        # 默认使用 \x08 (BS - Backspace)，这是大多数现代终端的标准
        # 某些旧系统可能需要 \x7f (DEL)
        return getattr(self, '_backspace_char', '\x08')

    def _auto_detect_backspace(self):
        """自动检测服务器期望的退格字符类型"""
        # 发送测试序列，检测服务器响应
        # 大多数现代SSH服务器使用 \x08 (BS)
        # 某些旧系统或特定配置可能需要 \x7f (DEL)
        # 这里我们采用保守策略：默认使用 \x08，如果出现乱码则切换到 \x7f
        pass

    def handle_input_method_text(self, text):
        """处理输入法输入的文本（如中文）"""
        if not self.connection_context.is_connected():
            return

        strategy = self.connection_context._strategy
        has_raw = hasattr(strategy, 'send_raw') and self.interactive_mode

        if has_raw:
            # 交互模式下本地追踪输入法文本，与服务器回显分离维护
            self.current_input += text
            strategy.send_raw(text)
            # 本地即时回显：消除中文输入法提交时的显示延迟
            self.write_output(text, 'text')
            self._local_echo_sent += text
        else:
            self.current_input += text
            self.write_output(text, self._get_style('text', '#e0e0e0'))

    def handle_paste_text(self, text):
        """处理粘贴的文本（来自 Ctrl+V 或右键菜单粘贴）

        交互模式下直接将完整文本发送到远程 shell（包括换行符自动执行多条命令）；
        非交互模式下追加到 current_input，遇到换行符时逐条 execute_command。
        """
        if not self.connection_context.is_connected():
            return
        if not text:
            return

        strategy = self.connection_context._strategy
        has_raw = hasattr(strategy, 'send_raw') and self.interactive_mode

        if has_raw:
            # 交互模式：直接发送（包括其中的换行符会触发远程执行）
            strategy.send_raw(text)
            # 本地追踪输入：仅保留最后一行内容（前面的行已随换行符执行）
            lines = text.split('\n')
            self.current_input = lines[-1] if lines else ''
            # 如果包含换行符，说明已有命令被执行，最后一行是新命令开头
            if '\n' in text:
                # 标记需要从display提取（可能包含补全/提示信息）
                self._tab_pending = True
            # 本地即时回显：让粘贴内容立即显示（防止网络卡顿导致无反馈）
            self.write_output(text, 'text')
            self._local_echo_sent += text
        else:
            # 非交互模式：若包含换行，逐条执行；否则追加到输入
            if '\n' in text:
                lines = text.split('\n')
                # 前面的行每条作为一条命令执行
                for i, line in enumerate(lines):
                    line = line.strip()
                    if not line:
                        continue
                    if i < len(lines) - 1:
                        # 非最后一行：构造完整命令并执行
                        self.current_input += line
                        # 显示要执行的命令
                        self.redraw_input_line()
                        self.write_output("\n")
                        cmd = self.current_input
                        self.current_input = ""
                        self.command_history.append(cmd)
                        self.history_index = len(self.command_history)
                        response = self.connection_context.send_command(cmd)
                        if response:
                            self.write_output(response, 'text-secondary')
                        # 命令结束后重置ANSI颜色格式
                        self.ansi_parser.reset_format()
                        self.show_input_line()
                    else:
                        # 最后一行保留在输入框中（不自动执行，用户可继续编辑后回车确认）
                        self.current_input += line
                        self.redraw_input_line()
            else:
                self.current_input += text
                self.write_output(text, 'text')

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
        self.write_output(f"{prompt} {self.current_input}", 'text-info')

    def get_prompt(self):
        """获取提示符"""
        if self.connection_context.is_connected():
            return f"{self.connection_context.get_strategy_name()}>"
        return "$"

    def execute_command(self):
        """执行命令（非交互模式）"""
        if not self.connection_context.is_connected():
            if not self._connection_lost:
                self._on_connection_lost()
            return

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
            self.write_output(response, 'text-secondary')

        # 命令结束后重置ANSI颜色格式，恢复默认配置，避免颜色跨命令残留
        self.ansi_parser.reset_format()

        self.show_input_line()

    def show_input_line(self):
        """显示输入行提示符（非交互模式）"""
        prompt = self.get_prompt()
        self.write_output(f"{prompt} ", 'text-info')

    def connect_with_config(self, conn):
        """使用保存的连接配置进行连接（异步）"""
        conn_type = conn.get('type')
        config = conn.get('config', {})

        self.current_connection = conn
        self.session_name = conn.get('name', '会话')

        # 先断开现有连接
        if self.connection_context.is_connected():
            self.disconnect()

        self.terminal_display.clear()
        self._output_history.clear()  # 清空输出历史，开始新会话
        self._output_buffer = ""
        self._connection_lost = False  # 重置连接中断标志
        self._tab_pending = False  # 重置Tab补全等待标志
        self.current_input = ""  # 重置本地输入追踪

        # 恢复标签页标题（移除中断标记）
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_update_session_tab_title'):
                parent._update_session_tab_title(self, connection_lost=False)
                break
            parent = parent.parent()

        self.write_output(f"正在连接 {conn.get('name', '')} ({conn_type})...\n", 'text-info')
        self._set_status("正在连接...")
        self._refresh_status_label_style()

        # 使用工厂模式创建连接
        strategy = ConnectionFactory.create_connection(conn_type)
        if strategy:
            self.connection_context.set_strategy(strategy)
            # 异步连接：在后台线程执行阻塞的网络连接，避免冻结 UI
            # 弹窗/标签页立即显示"正在连接..."，连接完成后通过信号回调更新 UI
            self._connection_worker = ConnectionWorker(strategy, config, self)
            self._connection_worker.connected.connect(self._on_async_connection_result)
            self._connection_worker.start()
        else:
            self.write_output(f"不支持的连接类型: {conn_type}\n", 'text-danger')
            self._set_status("连接失败")
            self._refresh_status_label_style()

    def _on_async_connection_result(self, success, initial_output, error_msg):
        """异步连接完成后的回调（在主线程执行，由 ConnectionWorker 信号触发）"""
        conn = self.current_connection
        conn_type = conn.get('type', '') if conn else ''
        config = conn.get('config', {}) if conn else {}
        strategy = self.connection_context._strategy if self.connection_context._strategy else None

        if success:
            self._set_status("已连接")
            self._refresh_status_label_style()

            host = config.get('host', '')
            port = config.get('port', '')
            self._set_conn_info(f"{host}:{port}" if host else str(config.get('port', '')))
            self._set_conn_type(conn_type.upper())

            # 检测是否支持交互模式
            if strategy and hasattr(strategy, 'send_raw') and hasattr(strategy, 'read_output'):
                self.interactive_mode = True
                if initial_output:
                    self.write_output(initial_output)
                # 连接成功后立即根据终端实际宽度调整PTY大小，避免长路径无法显示
                self._update_terminal_size()
                # 启动输出轮询，使用更短的间隔提高响应速度
                self.output_timer.start(30)  # 30ms间隔，提高响应速度
            else:
                self.interactive_mode = False
                self.write_output("连接成功!\n", 'text-success')
                self.write_output("-" * 50 + "\n", 'text-hint')
                self.show_input_line()

            self.setFocus()
        else:
            self.write_output("连接失败!\n", 'text-danger')
            if error_msg:
                self.write_output(f"错误: {error_msg}\n", 'text-danger')
            else:
                self.write_output("请检查连接参数是否正确\n", 'text-danger')
            self._set_status("连接失败")
            self._refresh_status_label_style()

        # 清理工作线程引用
        self._connection_worker = None

    def disconnect(self):
        """断开连接"""
        # 如果异步连接正在进行，等待其结束并断开信号连接
        if self._connection_worker is not None:
            try:
                self._connection_worker.connected.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._connection_worker = None
        self.output_timer.stop()
        self.connection_context.disconnect()
        self.interactive_mode = False
        self._connection_lost = False
        self.write_output("\n已断开连接\n", 'text-warning')
        self._set_status("未连接")
        self._refresh_status_label_style()
        self._set_conn_info("")
        self._set_conn_type("")

        # 恢复标签页标题（移除中断标记）
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_update_session_tab_title'):
                parent._update_session_tab_title(self, connection_lost=False)
                break
            parent = parent.parent()


class TerminalButtonToolbar(QWidget):
    """终端底部自定义按钮工具栏

    右键添加/编辑/删除按钮，按钮点击发出 button_triggered 信号。
    执行逻辑由 TerminalWidget 处理（解耦）。
    """

    button_triggered = pyqtSignal(str)  # btn_id

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self._config_manager = config_manager
        self._buttons_data = []
        self._button_widgets = {}  # btn_id → QPushButton
        self._get_style_fn = None  # 由 TerminalWidget 注入
        self._get_font_size_fn = None
        self.init_ui()
        self._load_buttons()
        self._build_toolbar()

    # ========== 样式辅助 ==========
    def _get_style(self, key, default=None):
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        return default

    def _get_font_size(self, key, default='12px'):
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        return default

    def _build_button_css(self):
        """生成按钮 CSS（含 executing 属性选择器）"""
        bg_input = self._get_style('bg-input', '#3c3c3c')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        border_light = self._get_style('border-light', '#5a5a5d')
        text_primary = self._get_style('text', '#ffffff')
        primary = self._get_style('primary', '#3a8fd4')
        font_size_sm = self._get_font_size('size-sm', '11px')
        return f"""
            QPushButton[executing="false"] {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {font_size_sm};
                font-weight: bold;
            }}
            QPushButton[executing="false"]:hover {{
                background-color: {bg_input_focus};
            }}
            QPushButton[executing="true"] {{
                background-color: {primary};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {font_size_sm};
                font-weight: bold;
            }}
        """

    # ========== UI 构建 ==========
    def init_ui(self):
        bg_main = self._get_style('bg-main', '#1e1e1e')
        border = self._get_style('border', '#3c3c3c')
        self.setStyleSheet(f"background-color: {bg_main};")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_toolbar_context_menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 2)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # 按钮容器
        self.buttons_container = QWidget()
        self.buttons_layout = QHBoxLayout(self.buttons_container)
        self.buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.buttons_layout.setSpacing(4)
        layout.addWidget(self.buttons_container)

        # 空列表提示
        self.hint_label = QLabel("右键添加按钮")
        hint_color = self._get_style('text-hint', '#858585')
        font_size_sm = self._get_font_size('size-sm', '11px')
        self.hint_label.setStyleSheet(
            f"color: {hint_color}; font-size: {font_size_sm}; padding: 4px 8px;")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)

        layout.addStretch()

    def _build_toolbar(self):
        """按数据重建按钮 UI"""
        # 清空旧按钮
        while self.buttons_layout.count():
            item = self.buttons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._button_widgets.clear()

        btn_css = self._build_button_css()
        for btn_data in self._buttons_data:
            btn_id = btn_data['id']
            btn = QPushButton(btn_data.get('name', '按钮'))
            btn.setProperty("executing", False)
            btn.setStyleSheet(btn_css)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.clicked.connect(lambda checked, bid=btn_id: self.button_triggered.emit(bid))
            btn.customContextMenuRequested.connect(
                lambda pos, bid=btn_id, b=btn: self._show_button_context_menu(bid, b.mapToParent(pos)))
            # Tooltip
            if btn_data['type'] == 'command':
                btn.setToolTip(f"命令: {btn_data.get('command', '')}")
            else:
                script_name = os.path.basename(btn_data.get('script_path', ''))
                btn.setToolTip(f"脚本: {script_name}")
            self.buttons_layout.addWidget(btn)
            self._button_widgets[btn_id] = btn

        # 显示/隐藏提示
        self.hint_label.setVisible(len(self._buttons_data) == 0)

    # ========== 右键菜单 ==========
    def _show_toolbar_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(self._config_manager.get_menu_css() if self._config_manager else "")
        add_action = menu.addAction("添加按钮")
        action = menu.exec(self.mapToGlobal(pos))
        if action == add_action:
            self._open_edit_dialog(None)

    def _show_button_context_menu(self, btn_id, pos):
        menu = QMenu(self)
        menu.setStyleSheet(self._config_manager.get_menu_css() if self._config_manager else "")
        edit_action = menu.addAction("编辑")
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        action = menu.exec(pos)
        if action == edit_action:
            btn_data = self.get_button_data(btn_id)
            if btn_data:
                self._open_edit_dialog(btn_data)
        elif action == delete_action:
            reply = QMessageBox.question(self, "确认", "确定删除此按钮？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.delete_button(btn_id)

    # ========== 编辑对话框 ==========
    def _open_edit_dialog(self, button_data=None):
        dialog = ButtonEditDialog(button_data, self._config_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_button_data()
            if button_data is None:
                self.add_button(new_data)
            else:
                self.edit_button(button_data['id'], new_data)

    # ========== 数据操作 ==========
    def _load_buttons(self):
        if self._config_manager:
            data = self._config_manager.get_plugin_data('Terminal', 'terminal_buttons')
            if isinstance(data, dict):
                self._buttons_data = data.get('buttons', [])
            else:
                self._buttons_data = []
        else:
            self._buttons_data = []
        # 补全字段
        for b in self._buttons_data:
            if not b.get('id'):
                b['id'] = uuid.uuid4().hex
            if 'created_at' not in b:
                b['created_at'] = 0
        self._buttons_data.sort(key=lambda x: x.get('created_at', 0))

    def _save_buttons(self):
        if not self._config_manager:
            return
        # 保留 visible 字段（由 TerminalWidget.toggle_button_toolbar 管理）
        existing = self._config_manager.get_plugin_data('Terminal', 'terminal_buttons') or {}
        visible = existing.get('visible', True) if isinstance(existing, dict) else True
        self._config_manager.set_plugin_data('Terminal', 'terminal_buttons',
                                             {'buttons': self._buttons_data, 'visible': visible})
        self._config_manager.save_plugin_data('Terminal', 'terminal_buttons')

    def add_button(self, btn_data):
        btn_data['created_at'] = int(time.time())
        self._buttons_data.append(btn_data)
        self._buttons_data.sort(key=lambda x: x.get('created_at', 0))
        self._save_buttons()
        self._build_toolbar()

    def edit_button(self, btn_id, new_data):
        for i, b in enumerate(self._buttons_data):
            if b['id'] == btn_id:
                new_data['id'] = btn_id
                new_data['created_at'] = b.get('created_at', 0)
                self._buttons_data[i] = new_data
                break
        self._save_buttons()
        self._build_toolbar()

    def delete_button(self, btn_id):
        self._buttons_data = [b for b in self._buttons_data if b['id'] != btn_id]
        self._save_buttons()
        self._build_toolbar()

    def get_button_data(self, btn_id):
        for b in self._buttons_data:
            if b['id'] == btn_id:
                return b
        return None

    def set_button_executing(self, btn_id, executing):
        btn = self._button_widgets.get(btn_id)
        if btn:
            btn.setProperty("executing", executing)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.setEnabled(not executing)

    # ========== 主题刷新 ==========
    def refresh_theme_styles(self):
        bg_main = self._get_style('bg-main', '#1e1e1e')
        self.setStyleSheet(f"background-color: {bg_main};")
        btn_css = self._build_button_css()
        for btn in self._button_widgets.values():
            btn.setStyleSheet(btn_css)
        hint_color = self._get_style('text-hint', '#858585')
        font_size_sm = self._get_font_size('size-sm', '11px')
        self.hint_label.setStyleSheet(
            f"color: {hint_color}; font-size: {font_size_sm}; padding: 4px 8px;")


class TerminalWidget(QWidget):
    connection_status_changed = pyqtSignal(str)

    def __init__(self, config=None, config_manager=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._config_manager = config_manager
        self._plugin_manager_ref = plugin_manager
        self._color_scheme = self._get_color_scheme()
        self.connection_manager = ConnectionManager(config_manager)
        self.sessions = {}  # session_id -> SessionTab
        self.session_counter = 0
        self.current_session_id = None
        self._executing_workers = {}  # btn_id -> ButtonExecutionWorker（防 GC）

        self.init_ui()
    
    def _get_color_scheme(self):
        """获取颜色方案配置"""
        if self._config_manager:
            return self._config_manager.get_color_scheme()
        return {}

    def _is_dark_theme(self):
        """根据背景色亮度判断是否为深色主题"""
        bg_hex = self._get_style('bg-main', '#1e1e1e')
        try:
            bg_hex = bg_hex.lstrip('#')
            r = int(bg_hex[0:2], 16)
            g = int(bg_hex[2:4], 16)
            b = int(bg_hex[4:6], 16)
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            return brightness < 128
        except (ValueError, IndexError):
            return True

    def _get_selected_colors(self):
        """获取选中态颜色：深灰色背景 + 适当对比度文字（不使用蓝色）

        Returns:
            (selected_bg, selected_text) 元组
        """
        if self._is_dark_theme():
            return '#3c3c3c', '#e0e0e0'  # 深灰色背景 + 浅色文字（高对比度）
        else:
            return '#c8c8c8', '#1e1e1e'  # 灰色背景 + 深色文字（高对比度）

    def _get_style(self, key, default=None):
        """获取样式配置（支持新旧两种格式）"""
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        return default
    
    def _get_font_size(self, key, default='12px'):
        """获取字体大小"""
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        font_sizes = {
            'small': '11px',
            'normal': '12px',
            'medium': '13px',
            'large': '14px',
            'size-sm': '11px',
            'size-md': '12px',
            'size-lg': '13px',
            'size-xl': '14px',
            'size-xxl': '16px'
        }
        return font_sizes.get(key, default)
    
    def _get_border_radius(self, key, default='4px'):
        """获取边框圆角"""
        if self._config_manager:
            return self._config_manager.get_border_radius(key, default)
        border_radii = {
            'small': '4px',
            'normal': '6px',
            'large': '8px',
            'sm': '4px',
            'md': '6px',
            'lg': '8px',
            'xl': '12px'
        }
        return border_radii.get(key, default)

    def _get_button_css(self, button_type='button'):
        """获取统一按钮 CSS 样式（蓝色背景+白色字体+加粗）"""
        if self._config_manager:
            return self._config_manager.get_button_css(button_type)
        # 默认蓝色背景、白色字体、加粗（淡蓝色，降低对比度）
        return f"""
            QPushButton {{
                background-color: #3a8fd4;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #4a9fe4;
            }}
            QPushButton:pressed {{
                background-color: #2a7fc4;
            }}
        """

    def init_ui(self):
        # Main layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Left sidebar for saved connections
        self.sidebar = QWidget()
        self.sidebar.setMinimumWidth(180)
        self.sidebar.setMaximumWidth(400)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)

        primary = self._get_style('primary', '#007acc')
        primary_hover = self._get_style('primary-hover', '#005a9e')
        primary_pressed = self._get_style('primary-pressed', '#004575')
        text_primary = self._get_style('text', '#ffffff')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        bg_tertiary = self._get_style('bg-tertiary', '#2c2c2c')
        bg_secondary = self._get_style('bg-secondary', '#252526')
        border_focus = self._get_style('border-focus', '#007acc')
        font_size = self._get_font_size('size-lg', '13px')
        border_radius = self._get_border_radius('sm', '4px')

        self.quick_actions = QWidget()
        self.quick_actions.setStyleSheet(f"background-color: {bg_secondary};")
        quick_layout = QVBoxLayout(self.quick_actions)
        quick_layout.setContentsMargins(8, 8, 8, 8)
        quick_layout.setSpacing(4)

        # 统一按钮样式：蓝色背景 + 白色字体 + 加粗
        unified_btn_css = self._get_button_css('button')

        # 第一行：新建连接、SFTP
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        self.new_conn_btn = QPushButton("新建连接")
        self.new_conn_btn.setFixedHeight(32)
        self.new_conn_btn.clicked.connect(self.show_new_connection_dialog)
        self.new_conn_btn.setStyleSheet(unified_btn_css)
        row1.addWidget(self.new_conn_btn)

        self.sftp_btn = QPushButton("SFTP")
        self.sftp_btn.setFixedHeight(32)
        self.sftp_btn.clicked.connect(self.show_sftp_dialog)
        self.sftp_btn.setStyleSheet(unified_btn_css)
        row1.addWidget(self.sftp_btn)
        quick_layout.addLayout(row1)

        # 第二行：重新连接、复制连接
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self.reconnect_btn = QPushButton("重新连接")
        self.reconnect_btn.setFixedHeight(32)
        self.reconnect_btn.clicked.connect(self.reconnect_last)
        self.reconnect_btn.setStyleSheet(unified_btn_css)
        row2.addWidget(self.reconnect_btn)

        self.copy_conn_btn = QPushButton("复制连接")
        self.copy_conn_btn.setFixedHeight(32)
        self.copy_conn_btn.clicked.connect(self.copy_current_connection)
        self.copy_conn_btn.setStyleSheet(unified_btn_css)
        row2.addWidget(self.copy_conn_btn)
        quick_layout.addLayout(row2)

        sidebar_layout.addWidget(self.quick_actions)

        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        bg_main = self._get_style('bg-main', '#1e1e1e')
        border = self._get_style('border', '#3c3c3c')
        # 选中态使用深灰色背景（不使用蓝色），字体颜色与背景有适当对比度
        selected_bg, selected_text = self._get_selected_colors()
        font_size_normal = self._get_font_size('size-md', '12px')

        session_label = QLabel("保存链接")
        session_label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_tertiary};
                color: {text_primary};
                padding: 10px 8px;
                font-weight: bold;
                font-size: {font_size};
                border-bottom: 1px solid {border_light};
            }}
        """)
        session_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(session_label)

        self.connection_list = QListWidget()
        self.connection_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.connection_list.customContextMenuRequested.connect(self.show_connection_menu)
        self.connection_list.doubleClicked.connect(self.on_connection_double_click)
        self.connection_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {bg_main};
                color: {text_primary};
                border: none;
            }}
            QListWidget::item {{
                padding: 3px 8px;
                border-bottom: 1px solid {border};
                font-size: {font_size_normal};
            }}
            QListWidget::item:selected {{
                background-color: {selected_bg};
                color: {selected_text};
            }}
            QListWidget::item:hover {{
                background-color: {bg_tertiary};
            }}
        """)
        sidebar_layout.addWidget(self.connection_list)

        self.current_font_size = 11
        self.color_enabled = True

        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        text_secondary = self._get_style('text-secondary', '#cccccc')
        border_radius_normal = self._get_border_radius('md', '6px')

        self.session_tabs = QTabWidget()
        self.session_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self.close_session)
        self.session_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {bg_main};
            }}
            QTabBar::tab {{
                background-color: {bg_tertiary};
                color: {text_secondary};
                padding: 8px 16px;
                border: 1px solid {border};
                border-bottom: none;
                margin-right: 2px;
                margin-top: 4px;
                border-top-left-radius: {border_radius_normal};
                border-top-right-radius: {border_radius_normal};
                font-size: {font_size_normal};
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {selected_bg};
                color: {selected_text};
                border-color: {selected_bg};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {bg_input};
                color: {text_primary};
            }}
            QTabBar::tab:closable {{
                margin-left: 5px;
            }}
        """)
        self.session_tabs.currentChanged.connect(self.on_session_changed)
        right_layout.addWidget(self.session_tabs)

        # 底部自定义按钮工具栏（与输出框作为一个整体，宽度对齐）
        self._button_toolbar_visible = True
        self.button_toolbar = TerminalButtonToolbar(self._config_manager, self)
        self.button_toolbar.button_triggered.connect(self._execute_button)
        self._load_button_toolbar_visible()
        right_layout.addWidget(self.button_toolbar, 0)

        # Add to splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 0)  # 左侧不随窗口扩展
        self.splitter.setStretchFactor(1, 1)  # 右侧自动扩展
        self.splitter.setSizes([220, 780])  # 初始宽度：侧边栏220，右侧780
        self.splitter.setHandleWidth(4)  # 拖拽手柄宽度
        self.splitter.setChildrenCollapsible(False)  # 防止子组件被折叠

        main_layout.addWidget(self.splitter)

        # 创建空白欢迎页面
        self._create_empty_page()

        # Load connections
        self.load_connections()

    def _create_empty_page(self):
        """创建空白欢迎页面"""
        bg_secondary = self._get_style('bg-secondary', '#252526')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        text_primary = self._get_style('text', '#ffffff')
        primary = self._get_style('primary', '#007acc')
        font_size_medium = self._get_font_size('size-lg', '13px')
        
        self.empty_page = QWidget()
        self.empty_page.setStyleSheet(f"background-color: {bg_secondary};")
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 添加欢迎提示
        welcome_label = QLabel("欢迎使用终端工具")
        welcome_label.setStyleSheet(f"""
            QLabel {{
                color: {text_primary};
                font-size: 18px;
                font-weight: bold;
            }}
        """)
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(welcome_label)
        
        hint_label = QLabel("点击左侧「新建连接」开始使用")
        hint_label.setStyleSheet(f"""
            QLabel {{
                color: {text_secondary};
                font-size: {font_size_medium};
                margin-top: 10px;
            }}
        """)
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint_label)
        
        empty_layout.addStretch()
        
        # 将空白页面添加到标签页（不可关闭）
        self.session_tabs.addTab(self.empty_page, "欢迎")
        self.session_tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

    def create_session(self, conn):
        """创建新会话"""
        self.session_counter += 1
        session_id = self.session_counter
        
        # 如果存在欢迎页面，先删除
        if hasattr(self, 'empty_page') and self.empty_page:
            empty_index = self.session_tabs.indexOf(self.empty_page)
            if empty_index >= 0:
                self.session_tabs.removeTab(empty_index)
                self.empty_page.deleteLater()
                self.empty_page = None
        
        # 创建会话标签
        tab = SessionTab(session_id, conn.get('name', '会话'), self._color_scheme, self._config_manager)

        # 同步颜色显示开关状态到新会话的ANSI解析器
        tab.ansi_parser.enable_color = getattr(self, 'color_enabled', True)

        # 设置初始字体大小，clamp到>0避免setPointSize(-1)警告
        safe_size = max(1, int(self.current_font_size)) if self.current_font_size and isinstance(self.current_font_size, (int, float)) else 11
        tab.terminal_display.setFont(QFont("Consolas", safe_size))
        
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
            
            # 如果没有会话了，显示欢迎页面
            if len(self.sessions) == 0:
                self._create_empty_page()

    def on_session_changed(self, index):
        """会话切换"""
        if index >= 0:
            tab = self.session_tabs.widget(index)
            if tab:
                for sid, sess in self.sessions.items():
                    if sess['tab'] == tab:
                        self.current_session_id = sid
                        # 切换会话时刷新框架状态栏
                        if hasattr(tab, '_report_status'):
                            tab._report_status()
                        break

    def _report_session_status(self, status_text):
        """SessionTab 上报状态到框架统一状态接口

        由 SessionTab._report_status 调用。仅当前激活会话的状态会显示在框架状态栏。
        """
        current_tab = self.get_current_session()
        if current_tab is None:
            return
        # 仅当上报来自当前激活会话时才更新框架状态
        # 对比状态文本判断来源（简化：直接使用当前会话状态）
        current_status = " | ".join(
            s for s in [current_tab._status_text, current_tab._conn_info_text, current_tab._conn_type_text] if s
        )
        if self._plugin_manager_ref and hasattr(self._plugin_manager_ref, 'set_tool_status'):
            self._plugin_manager_ref.set_tool_status('Terminal', current_status)

    def get_current_session(self):
        """获取当前会话"""
        if self.current_session_id and self.current_session_id in self.sessions:
            return self.sessions[self.current_session_id]['tab']
        return None

    # ========== 按钮工具栏执行 ==========

    def _load_button_toolbar_visible(self):
        """从配置加载按钮工具栏可见性"""
        if self._config_manager:
            data = self._config_manager.get_plugin_data('Terminal', 'terminal_buttons')
            if isinstance(data, dict):
                self._button_toolbar_visible = data.get('visible', True)
        self.button_toolbar.setVisible(self._button_toolbar_visible)

    def toggle_button_toolbar(self, visible):
        """切换按钮工具栏显示/隐藏（由菜单触发）"""
        self._button_toolbar_visible = visible
        self.button_toolbar.setVisible(visible)
        # 持久化（保留 buttons 数据）
        if self._config_manager:
            data = self._config_manager.get_plugin_data('Terminal', 'terminal_buttons') or {}
            if not isinstance(data, dict):
                data = {}
            data['visible'] = visible
            self._config_manager.set_plugin_data('Terminal', 'terminal_buttons', data)
            self._config_manager.save_plugin_data('Terminal', 'terminal_buttons')

    def _execute_button(self, btn_id):
        """按钮触发执行入口（主线程）"""
        btn_data = self.button_toolbar.get_button_data(btn_id)
        if not btn_data:
            return
        session_tab = self.get_current_session()
        if not session_tab or not session_tab.connection_context.is_connected():
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        # 防重入
        if btn_id in self._executing_workers:
            return
        # 暂停终端输出轮询，避免与脚本/命令争抢 read_output
        session_tab.output_timer.stop()
        # 切换按钮为执行中态（蓝色）
        self.button_toolbar.set_button_executing(btn_id, True)
        # 写入执行头信息
        session_tab.write_output(f"\n>>> 执行按钮: {btn_data['name']}\n", 'text-info')
        # 启动 worker
        worker = ButtonExecutionWorker(btn_id, btn_data, session_tab)
        worker.finished.connect(self._on_button_execution_finished)
        self._executing_workers[btn_id] = worker  # 防止 GC
        worker.start()

    def _on_button_execution_finished(self, btn_id, result):
        """按钮执行完成回调（主线程）"""
        btn_data = self.button_toolbar.get_button_data(btn_id)
        session_tab = self.get_current_session()
        # 清理 worker
        worker = self._executing_workers.pop(btn_id, None)
        if worker:
            worker.deleteLater()
        # 恢复按钮默认态（深灰）
        self.button_toolbar.set_button_executing(btn_id, False)
        # 写入输出
        if session_tab:
            if result.get('output'):
                session_tab.write_output(result['output'])
                if not result['output'].endswith('\n'):
                    session_tab.write_output('\n')
            if result.get('error'):
                session_tab.write_output(f"错误: {result['error']}\n", 'text-danger')
            # 脚本型额外信息
            if btn_data and btn_data.get('type') == 'script':
                if result.get('session_result'):
                    session_tab.write_output(f"结果: {result['session_result']}\n", 'text-hint')
                session_tab.write_output(
                    f"状态: {'成功' if result['success'] else '失败'}\n",
                    'text-success' if result['success'] else 'text-danger')
            # 恢复输出轮询
            if session_tab.connection_context.is_connected():
                session_tab.output_timer.start(30)
        # 状态栏上报
        if self._plugin_manager_ref and hasattr(self._plugin_manager_ref, 'set_tool_status'):
            name = btn_data.get('name', '') if btn_data else ''
            status = '成功' if result.get('success') else '失败'
            self._plugin_manager_ref.set_tool_status('Terminal', f"按钮 {name}: {status}")

    def _update_session_tab_title(self, tab, connection_lost=False):
        """更新会话标签页标题（连接中断时添加标记）"""
        for sid, sess in self.sessions.items():
            if sess['tab'] is tab:
                conn = sess.get('connection', {})
                conn_name = conn.get('name', '')
                if not conn_name:
                    conn_name = conn.get('config', {}).get('host', '会话')
                if connection_lost:
                    conn_name = f"⚠ {conn_name}"
                # 找到标签页索引并更新标题
                index = self.session_tabs.indexOf(tab)
                if index >= 0:
                    self.session_tabs.setTabText(index, conn_name)
                break

    def refresh_theme_styles(self):
        """刷新主题样式"""
        # 更新缓存的颜色方案，确保弹窗等子组件获取到最新主题
        self._color_scheme = self._get_color_scheme()
        # 一次性获取所有需要的主题颜色
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_secondary = self._get_style('bg-secondary', '#252526')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border = self._get_style('border', '#3c3c3c')
        border_light = self._get_style('border-light', '#4a4a4a')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        primary = self._get_style('primary', '#007acc')
        # 选中态使用深灰色背景（不使用蓝色），字体颜色与背景有适当对比度
        selected_bg, selected_text = self._get_selected_colors()
        font_size = self._get_font_size('size-lg', '13px')
        font_size_normal = self._get_font_size('size-md', '12px')
        font_size_sm = self._get_font_size('size-sm', '11px')

        # 刷新侧边栏整体背景
        if hasattr(self, 'sidebar'):
            self.sidebar.setStyleSheet(f"background-color: {bg_main};")

        # 刷新快捷操作区背景
        if hasattr(self, 'quick_actions'):
            self.quick_actions.setStyleSheet(f"background-color: {bg_secondary};")

        # 刷新保存链接标题（侧边栏中的 QLabel）
        if hasattr(self, 'sidebar'):
            for label in self.sidebar.findChildren(QLabel):
                label.setStyleSheet(f"""
                    QLabel {{
                        background-color: {bg_tertiary};
                        color: {text_primary};
                        padding: 10px 8px;
                        font-weight: bold;
                        font-size: {font_size};
                        border-bottom: 1px solid {border_light};
                    }}
                """)

        # 刷新右侧面板背景
        if hasattr(self, 'right_panel'):
            self.right_panel.setStyleSheet(f"background-color: {bg_main};")

        # 刷新空页面背景（欢迎页）
        if hasattr(self, 'empty_page') and self.empty_page:
            self.empty_page.setStyleSheet(f"background-color: {bg_secondary};")
            # 刷新欢迎页中的标签
            text_primary = self._get_style('text', '#ffffff')
            text_secondary = self._get_style('text-secondary', '#cccccc')
            font_size_lg = self._get_font_size('size-xl', '14px')
            font_size_md = self._get_font_size('size-md', '12px')
            for label in self.empty_page.findChildren(QLabel):
                if '欢迎' in label.text():
                    label.setStyleSheet(f"""
                        QLabel {{
                            color: {text_primary};
                            font-size: 18px;
                            font-weight: bold;
                        }}
                    """)
                else:
                    label.setStyleSheet(f"""
                        QLabel {{
                            color: {text_secondary};
                            font-size: {font_size_md};
                            margin-top: 10px;
                        }}
                    """)

        # 重新应用侧边栏按钮样式
        if hasattr(self, 'new_conn_btn'):
            btn_css = self._get_button_css('button')
            self.new_conn_btn.setStyleSheet(btn_css)
            self.reconnect_btn.setStyleSheet(btn_css)
            self.sftp_btn.setStyleSheet(btn_css)
            self.copy_conn_btn.setStyleSheet(btn_css)

        # 刷新连接列表样式
        if hasattr(self, 'connection_list'):
            self.connection_list.setStyleSheet(f"""
                QListWidget {{
                    background-color: {bg_main};
                    color: {text_primary};
                    border: none;
                }}
                QListWidget::item {{
                    padding: 3px 8px;
                    border-bottom: 1px solid {border};
                    font-size: {font_size_normal};
                }}
                QListWidget::item:selected {{
                    background-color: {selected_bg};
                    color: {selected_text};
                }}
                QListWidget::item:hover {{
                    background-color: {bg_tertiary};
                }}
            """)

        # 刷新会话标签页样式
        if hasattr(self, 'session_tabs'):
            self.session_tabs.setStyleSheet(f"""
                QTabWidget::pane {{
                    border: 1px solid {border};
                    background-color: {bg_main};
                }}
                QTabBar::tab {{
                    background-color: {bg_tertiary};
                    color: {text_secondary};
                    padding: 5px 12px;
                    border: 1px solid {border};
                    border-bottom: none;
                    margin-right: 1px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    font-size: {font_size_sm};
                }}
                QTabBar::tab:selected {{
                    background-color: {selected_bg};
                    color: {selected_text};
                    border-color: {selected_bg};
                    font-weight: bold;
                }}
                QTabBar::tab:hover:!selected {{
                    background-color: {bg_input};
                    color: {text_primary};
                }}
            """)

        # 刷新SessionTab内部样式
        new_scheme = self._get_color_scheme()
        for sid, sess in self.sessions.items():
            tab = sess.get('tab')
            if tab:
                tab._color_scheme = new_scheme
                if hasattr(tab, 'refresh_theme_styles'):
                    try:
                        tab.refresh_theme_styles()
                    except Exception:
                        pass

        # 刷新按钮工具栏样式
        if hasattr(self, 'button_toolbar'):
            self.button_toolbar.refresh_theme_styles()

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
        dialog = ConnectionDialog(self, config_manager=self._config_manager)
        if dialog.exec():
            conn_data = dialog.get_connection_data()
            # 检查名称是否重复，自动添加序号
            conn_data['name'] = self._ensure_unique_connection_name(conn_data['name'])
            self.connection_manager.create_connection(
                conn_data['name'],
                conn_data['type'],
                conn_data['config']
            )
            self.load_connections()
    
    def _ensure_unique_connection_name(self, name, exclude_id=None):
        """确保连接名称唯一，若重复则自动添加序号"""
        existing_names = set()
        for conn in self.connection_manager.get_connections():
            if conn.get('id') != exclude_id:
                existing_names.add(conn.get('name', ''))
        
        if name not in existing_names:
            return name
        
        # 名称重复，添加序号
        counter = 2
        while f"{name}_{counter}" in existing_names:
            counter += 1
        return f"{name}_{counter}"

    def show_sftp_dialog(self):
        """显示SFTP对话框"""
        session = self.get_current_session()
        if not session or not session.connection_context.is_connected():
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        
        dialog = SFTPDialog(session.connection_context, self, config_manager=self._config_manager)
        dialog.exec()

    def reconnect_last(self):
        """重新连接上一个会话"""
        session = self.get_current_session()
        if session and session.current_connection:
            session.connect_with_config(session.current_connection)
        else:
            QMessageBox.information(self, "提示", "没有可重新连接的会话")

    def copy_current_connection(self):
        """复制当前连接，在主窗体中创建新的会话标签页（使用相同连接配置重新连接）"""
        session = self.get_current_session()
        if not session or not session.current_connection:
            QMessageBox.information(self, "提示", "没有可复制的连接")
            return

        conn = session.current_connection
        # 使用相同连接配置创建新的会话标签页并建立连接
        self.create_session(conn)
        # 通过框架统一状态接口上报结果
        if self._plugin_manager_ref and hasattr(self._plugin_manager_ref, 'set_tool_status'):
            self._plugin_manager_ref.set_tool_status('Terminal', f"已复制连接: {conn.get('name', '连接')}")

    def show_font_size_menu(self):
        """显示字体大小设置菜单"""
        menu = QMenu(self)
        
        if self._config_manager:
            menu.setStyleSheet(self._config_manager.get_menu_css())
        else:
            bg = self._get_style('bg-tertiary', '#2d2d30')
            color = self._get_style('text', '#ffffff')
            border = self._get_style('border-light', '#4a4a4d')
            padding = self._get_style('menu_padding', '4px')
            item_padding = self._get_style('menu_item_padding', '6px 24px')
            item_selected_bg = self._get_style('primary', '#007acc')
            separator_bg = self._get_style('border-light', '#4a4a4d')
            
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {bg};
                    color: {color};
                    border: 1px solid {border};
                    padding: {padding};
                }}
                QMenu::item {{
                    padding: {item_padding};
                    min-width: 100px;
                    color: {color};
                }}
                QMenu::item:selected {{
                    background-color: {item_selected_bg};
                    color: #ffffff;
                }}
                QMenu::separator {{
                    height: 1px;
                    background-color: {separator_bg};
                    margin: 4px 0;
                }}
            """)
        
        font_sizes = [
            ("8px", 8),
            ("10px", 10),
            ("11px", 11),
            ("12px", 12),
            ("14px", 14),
            ("16px", 16),
            ("18px", 18),
            ("20px", 20)
        ]
        
        for label, size in font_sizes:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.current_font_size == size)
            action.triggered.connect(lambda checked, s=size: self.set_font_size(s))
            menu.addAction(action)
        
        menu.exec(QCursor.pos())

    def set_font_size(self, size):
        """设置字体大小"""
        # 验证size合法性，确保>0避免setPointSize(-1)警告
        try:
            safe_size = max(1, int(size))
        except (ValueError, TypeError):
            safe_size = 11
        self.current_font_size = safe_size
        for session_id, session_data in self.sessions.items():
            session = session_data.get('tab')
            if session and hasattr(session, 'terminal_display'):
                session.terminal_display.setFont(QFont("Consolas", safe_size))

    def toggle_color_display(self, checked=None):
        """切换颜色显示开关（支持菜单勾选触发）"""
        if checked is not None:
            self.color_enabled = checked
        else:
            self.color_enabled = not self.color_enabled

        for session_id, session_data in self.sessions.items():
            session = session_data.get('tab')
            if session and hasattr(session, 'ansi_parser'):
                session.ansi_parser.enable_color = self.color_enabled
                # 打开/关闭颜色时都重置格式为默认值，避免颜色状态残留
                session.ansi_parser.reset_format()
                # 重新渲染已输出内容，使开关变更立即生效
                if hasattr(session, '_rerender_output'):
                    session._rerender_output()

    def show_connection_menu(self, pos):
        """显示连接右键菜单"""
        item = self.connection_list.itemAt(pos)
        if not item:
            return

        conn = item.data(Qt.ItemDataRole.UserRole)
        if not conn:
            return

        menu = QMenu(self)
        
        if self._config_manager:
            menu.setStyleSheet(self._config_manager.get_menu_css())
        else:
            bg = self._get_style('bg-tertiary', '#2d2d30')
            color = self._get_style('text', '#ffffff')
            border = self._get_style('border-light', '#4a4a4d')
            padding = self._get_style('menu_padding', '4px')
            item_padding = self._get_style('menu_item_padding', '6px 24px')
            item_selected_bg = self._get_style('primary', '#007acc')
            separator_bg = self._get_style('border-light', '#4a4a4d')
            
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {bg};
                    color: {color};
                    border: 1px solid {border};
                    padding: {padding};
                }}
                QMenu::item {{
                    padding: {item_padding};
                    min-width: 100px;
                    color: {color};
                }}
                QMenu::item:selected {{
                    background-color: {item_selected_bg};
                    color: #ffffff;
                }}
                QMenu::separator {{
                    height: 1px;
                    background-color: {separator_bg};
                    margin: 4px 0;
                }}
            """)

        connect_action = QAction("新建会话", self)
        connect_action.triggered.connect(lambda: self.create_session(conn))
        menu.addAction(connect_action)

        copy_action = QAction("复制", self)
        copy_action.triggered.connect(lambda: self.copy_connection(conn))
        menu.addAction(copy_action)

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
        dialog = ConnectionDialog(self, conn, config_manager=self._config_manager)
        if dialog.exec():
            conn_id = conn.get('id')
            conn_data = dialog.get_connection_data()
            # 检查名称是否重复（排除自身）
            conn_data['name'] = self._ensure_unique_connection_name(conn_data['name'], exclude_id=conn_id)
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

    def copy_connection(self, conn):
        """复制连接"""
        import copy
        new_conn = copy.deepcopy(conn)
        base_name = f"{conn.get('name', '未命名')} 副本"
        # 确保复制的名称也唯一
        new_conn['name'] = self._ensure_unique_connection_name(base_name)
        new_conn.pop('id', None)
        self.connection_manager.create_connection(
            new_conn['name'],
            new_conn['type'],
            new_conn['config']
        )
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
    def __init__(self, parent=None, connection=None, config_manager=None):
        super().__init__(parent)
        self.connection = connection
        self._config_manager = config_manager
        self._color_scheme = self._get_parent_color_scheme(parent)
        self.init_ui()

    def _get_parent_color_scheme(self, parent):
        """从父组件获取颜色方案"""
        if parent and hasattr(parent, '_color_scheme'):
            return parent._color_scheme
        return {}

    def _get_style(self, key, default=None):
        """获取样式配置（优先从config_manager实时获取，支持新旧两种格式）"""
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        value = self._color_scheme.get(key)
        if value is not None:
            return value
        old_key_map = {
            'background_main': 'bg-main',
            'background_secondary': 'bg-secondary',
            'background_tertiary': 'bg-tertiary',
            'background_input': 'bg-input',
            'background_input_focus': 'bg-input-focus',
            'text_primary': 'text',
            'text_secondary': 'text-secondary',
            'border_light': 'border-light',
            'border_focus': 'border-focus',
            'selection_text': 'selection-text',
            'primary_hover': 'primary-hover',
            'primary_pressed': 'primary-pressed'
        }
        if key in old_key_map:
            return self._color_scheme.get(old_key_map[key], default)
        return default

    def _get_font_size(self, key, default='12px'):
        """获取字体大小"""
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        font_sizes = {
            'small': '11px',
            'normal': '12px',
            'medium': '13px',
            'large': '14px',
            'size-sm': '11px',
            'size-md': '12px',
            'size-lg': '13px',
            'size-xl': '14px',
            'size-xxl': '16px'
        }
        return font_sizes.get(key, default)

    def _get_border_radius(self, key, default='4px'):
        """获取边框圆角"""
        if self._config_manager:
            return self._config_manager.get_border_radius(key, default)
        border_radii = {
            'small': '4px',
            'normal': '6px',
            'large': '8px',
            'sm': '4px',
            'md': '6px',
            'lg': '8px',
            'xl': '12px'
        }
        return border_radii.get(key, default)

    def init_ui(self):
        title = "编辑连接" if self.connection else "新建连接"
        self.setWindowTitle(title)
        self.setGeometry(300, 300, 440, 240)
        
        bg_secondary = self._get_style('bg-secondary', '#252526')
        text_primary = self._get_style('text', '#ffffff')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        border_focus = self._get_style('border-focus', '#007acc')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        primary = self._get_style('primary', '#007acc')
        primary_hover = self._get_style('primary-hover', '#005a9e')
        primary_pressed = self._get_style('primary-pressed', '#004575')
        selection = self._get_style('selection', '#007acc')
        selection_text = self._get_style('selection-text', '#ffffff')
        font_size_normal = self._get_font_size('size-md', '12px')
        font_size_medium = self._get_font_size('size-lg', '13px')
        border_radius_small = self._get_border_radius('sm', '4px')
        border_radius_normal = self._get_border_radius('md', '6px')

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_secondary};
                color: {text_primary};
            }}
            QLabel {{
                color: {text_primary};
                font-size: {font_size_normal};
            }}
            QLineEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 4px 8px;
                border-radius: {border_radius_small};
                font-size: {font_size_normal};
            }}
            QLineEdit:focus {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
            QSpinBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 4px 8px;
                border-radius: {border_radius_small};
                font-size: {font_size_normal};
            }}
            QSpinBox:focus {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
            QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 4px 8px;
                border-radius: {border_radius_small};
                font-size: {font_size_normal};
            }}
            QComboBox:hover {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: url({_DOWN_ARROW_IMG});
            }}
            QComboBox QAbstractItemView {{
                background-color: {bg_tertiary};
                color: {text_primary};
                selection-background-color: {selection};
                selection-color: {selection_text};
                border: 1px solid {border_light};
                border-radius: {border_radius_small};
            }}
            QPushButton {{
                background-color: {primary};
                color: #ffffff;
                border: none;
                padding: 6px 18px;
                font-size: {font_size_medium};
                font-weight: bold;
                border-radius: {border_radius_normal};
            }}
            QPushButton:hover {{
                background-color: {primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {primary_pressed};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        label_style = f"color: {text_primary}; font-size: {font_size_normal}; font-weight: 500;"

        # 连接名称
        name_layout = QHBoxLayout()
        name_layout.setSpacing(6)
        name_label = QLabel("连接名称:")
        name_label.setStyleSheet(label_style)
        name_label.setFixedWidth(80)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_layout.addWidget(name_label)
        self.name_input = QLineEdit()
        if self.connection:
            self.name_input.setText(self.connection.get('name', ''))
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # 连接类型 + 端口（同一行，1:1比例）
        self.type_port_layout = QHBoxLayout()
        self.type_port_layout.setSpacing(6)
        type_label = QLabel("连接类型:")
        type_label.setStyleSheet(label_style)
        type_label.setFixedWidth(80)
        type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.type_port_layout.addWidget(type_label)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["ssh", "telnet", "serial"])
        if self.connection:
            self.type_combo.setCurrentText(self.connection.get('type', 'ssh'))
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        self.type_port_layout.addWidget(self.type_combo, 1)

        self.port_label = QLabel("端口:")
        self.port_label.setStyleSheet(label_style)
        self.port_label.setFixedWidth(80)
        self.port_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.type_port_layout.addWidget(self.port_label)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(22)
        self.type_port_layout.addWidget(self.port_input, 1)
        layout.addLayout(self.type_port_layout)

        # 动态配置区：使用 QWidget + QVBoxLayout，切换连接类型时重建内容（不留空白行）
        self._label_style = label_style
        self.config_widget = QWidget()
        self.config_layout = QVBoxLayout(self.config_widget)
        self.config_layout.setContentsMargins(0, 0, 0, 0)
        self.config_layout.setSpacing(6)
        layout.addWidget(self.config_widget)

        # 弹性空间：吸收对话框多余高度，防止行间距被拉伸产生空白
        layout.addStretch()

        # 预创建所有输入控件（不直接加入布局，按需通过 on_type_changed 添加）
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("主机地址")

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("用户名")

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("密码")

        self.key_file_input = QLineEdit()
        self.key_file_input.setPlaceholderText("密钥文件路径")
        self.key_browse_btn = QPushButton("浏览...")
        self.key_browse_btn.setFixedWidth(56)
        self.key_browse_btn.clicked.connect(self.browse_key_file)
        self.key_browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary};
                color: #ffffff;
                border: none;
                padding: 4px 6px;
                font-size: {font_size_normal};
                font-weight: normal;
                border-radius: {border_radius_normal};
            }}
            QPushButton:hover {{ background-color: {primary_hover}; }}
            QPushButton:pressed {{ background-color: {primary_pressed}; }}
        """)

        self.serial_port_combo = QComboBox()
        self.serial_port_combo.addItems([f'COM{i}' for i in range(1, 21)])

        self.serial_baud_combo = QComboBox()
        self.serial_baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.serial_baud_combo.setCurrentText("115200")

        # 按钮区
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        # 先调用on_type_changed初始化布局（设置默认端口），
        # 再调用load_connection_config覆盖实际配置（包括端口），
        # 避免编辑模式加载的端口被on_type_changed重置为默认值22
        self.on_type_changed(self.type_combo.currentText())

        if self.connection:
            self.load_connection_config()

    def _clear_config_layout(self):
        """清空动态配置区布局（保留预创建的输入控件，仅删除行容器及一次性标签）"""
        # 预创建的输入控件清单：重新挂回对话框，避免被行容器连带删除
        protected = [self.host_input, self.username_input, self.password_input,
                     self.key_file_input, self.key_browse_btn,
                     self.serial_port_combo, self.serial_baud_combo]
        while self.config_layout.count():
            item = self.config_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                for child in protected:
                    if child.parent() is w:
                        child.setParent(self)
                w.deleteLater()

    def _make_row(self, label_text, field_widget, label_width=80):
        """创建一个横向 标签+字段 行 widget"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(self._label_style)
        lbl.setFixedWidth(label_width)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(lbl)
        # 重新设置 field_widget 的父对象为当前行，避免跨容器引用
        field_widget.setParent(row_widget)
        row_layout.addWidget(field_widget, 1)
        return row_widget

    def _make_key_file_row(self):
        """创建密钥文件行（输入框 + 浏览按钮）"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        lbl = QLabel("密钥文件:")
        lbl.setStyleSheet(self._label_style)
        lbl.setFixedWidth(80)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(lbl)
        self.key_file_input.setParent(row_widget)
        row_layout.addWidget(self.key_file_input, 1)
        self.key_browse_btn.setParent(row_widget)
        row_layout.addWidget(self.key_browse_btn)
        return row_widget

    def on_type_changed(self, conn_type):
        """根据连接类型动态重建配置字段（不留空白行）"""
        # 先清空动态配置区
        self._clear_config_layout()

        # 端口默认值
        if conn_type == "ssh":
            self.port_input.setValue(22)
        elif conn_type == "telnet":
            self.port_input.setValue(23)

        if conn_type == "serial":
            # 串口：显示串口、波特率；隐藏主机/端口/用户名/密码
            self.config_layout.addWidget(self._make_row("串口:", self.serial_port_combo))
            self.config_layout.addWidget(self._make_row("波特率:", self.serial_baud_combo))
            # 端口行不适用于串口，隐藏端口标签和输入框
            self.port_label.hide()
            self.port_input.hide()
            # 连接类型下拉框填充满整行（端口已隐藏）
            self.type_port_layout.setStretchFactor(self.type_combo, 1)
        else:
            # ssh/telnet：显示主机、用户名
            self.config_layout.addWidget(self._make_row("主机:", self.host_input))
            self.config_layout.addWidget(self._make_row("用户名:", self.username_input))

            if conn_type == "ssh":
                # SSH：显示密码 + 密钥文件
                self.config_layout.addWidget(self._make_row("密码:", self.password_input))
                self.config_layout.addWidget(self._make_key_file_row())
            elif conn_type == "telnet":
                # Telnet：不显示密码和密钥文件（telnet 无加密认证）
                pass

            # 显示端口标签和控件（ssh/telnet 使用端口），连接类型与端口 1:1 比例
            self.port_label.show()
            self.port_input.show()
            self.type_port_layout.setStretchFactor(self.type_combo, 1)

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
    _last_upload_dir = os.path.expanduser("~")
    _last_download_dir = os.path.expanduser("~")

    def __init__(self, connection_context, parent=None, config_manager=None):
        super().__init__(parent)
        self.connection_context = connection_context
        self.sftp = None
        self.current_remote_dir = "/home/"
        self._config_manager = config_manager
        self._color_scheme = self._get_color_scheme(parent)
        # 加载SFTP快捷路径列表（持久化到 config/sftp_shortcuts.json）
        self._shortcuts = self._load_shortcuts()
        self.init_ui()
        # 延迟初始化SFTP连接：先显示弹窗，再异步建立连接，避免启动卡顿
        text_hint = self._get_style('text-hint', '#858585')
        self.status_label.setText("SFTP状态: 正在连接...")
        self.status_label.setStyleSheet(f"color: {text_hint}; font-weight: bold; font-size: 13px;")
        QTimer.singleShot(0, self.init_sftp)

    # ========== 快捷路径管理 ==========
    _SHORTCUTS_PLUGIN = 'Terminal'
    _SHORTCUTS_DATA_KEY = 'sftp_shortcuts'

    def _load_shortcuts(self):
        """从ConfigManager加载快捷路径列表"""
        if self._config_manager:
            data = self._config_manager.get_plugin_data(
                self._SHORTCUTS_PLUGIN, self._SHORTCUTS_DATA_KEY)
            if isinstance(data, list):
                return data
        return []

    def _save_shortcuts(self):
        """保存快捷路径列表到ConfigManager"""
        if not self._config_manager:
            return
        self._config_manager.set_plugin_data(
            self._SHORTCUTS_PLUGIN, self._SHORTCUTS_DATA_KEY, self._shortcuts)
        self._config_manager.save_plugin_data(
            self._SHORTCUTS_PLUGIN, self._SHORTCUTS_DATA_KEY)

    def _render_shortcuts(self):
        """重新渲染快捷路径按钮区域（保留 + 按钮在末尾）"""
        # 清空布局中现有widget（保留add_btn在末尾重新添加）
        while self.shortcuts_layout.count():
            item = self.shortcuts_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        # 快捷路径按钮：点击根据类型跳转（服务器路径或本地路径）
        for idx, sc in enumerate(self._shortcuts):
            name = sc.get('name', sc.get('path', ''))
            path = sc.get('path', '')
            sc_type = sc.get('type', 'remote')  # 默认兼容旧数据为 remote
            btn = QPushButton(name)
            # tooltip 显示类型和路径
            type_label = "本地路径" if sc_type == 'local' else "服务器路径"
            btn.setToolTip(f"[{type_label}] {path}")
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            # 使用闭包捕获path和type，避免循环变量引用问题
            if sc_type == 'local':
                btn.clicked.connect(lambda _checked=False, p=path: self._jump_to_local_shortcut(p))
            else:
                btn.clicked.connect(lambda _checked=False, p=path: self._jump_to_shortcut(p))
            btn.customContextMenuRequested.connect(
                lambda _pos=None, idx=idx: self._show_shortcut_menu(idx))
            btn.setFixedHeight(20)  # 紧凑高度
            self._style_shortcut_btn(btn)
            self.shortcuts_layout.addWidget(btn)

        # 末尾固定的 + 按钮，用于新增快捷路径
        self.add_shortcut_btn = QPushButton("+")
        self.add_shortcut_btn.setToolTip("新增快捷路径")
        self.add_shortcut_btn.setFixedSize(20, 20)  # 紧凑方形
        self.add_shortcut_btn.clicked.connect(self._add_shortcut_dialog)
        self._style_shortcut_btn(self.add_shortcut_btn)
        self.shortcuts_layout.addWidget(self.add_shortcut_btn)
        # 末尾弹性空间，使按钮左对齐
        self.shortcuts_layout.addStretch(1)

    def _style_shortcut_btn(self, btn):
        """为快捷路径按钮应用主题样式（深灰背景，紧凑尺寸）"""
        if self._config_manager:
            btn_css = self._config_manager.get_button_css('button-secondary')
            if btn_css:
                # 在主题CSS基础上叠加紧凑尺寸（覆盖 padding/min-height）
                btn_css += """
                    QPushButton {
                        padding: 0px 6px;
                        font-size: 11px;
                        min-height: 20px;
                        max-height: 20px;
                    }
                """
                btn.setStyleSheet(btn_css)
                return
        # 默认样式：深灰背景，紧凑尺寸
        bg = self._get_style('bg-tertiary', '#2d2d30')
        text = self._get_style('text', '#ffffff')
        border = self._get_style('border', '#3c3c3c')
        primary = self._get_style('primary', '#007acc')
        primary_hover = self._get_style('primary-hover', '#005a9e')
        primary_pressed = self._get_style('primary-pressed', '#004575')
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {text};
                border: 1px solid {border};
                padding: 0px 6px;
                font-size: 11px;
                border-radius: 3px;
                min-height: 20px;
                max-height: 20px;
            }}
            QPushButton:hover {{
                background-color: {primary};
                color: #ffffff;
                border-color: {primary};
            }}
            QPushButton:pressed {{
                background-color: {primary_pressed};
                color: #ffffff;
            }}
        """)

    def _style_operation_btn(self, btn):
        """为下方操作按钮（上传/下载/刷新/关闭）应用紧凑主题样式"""
        if self._config_manager:
            # 在主题 button 样式基础上叠加紧凑参数
            btn_css = self._config_manager.get_button_css('button')
            if btn_css:
                btn_css += """
                    QPushButton {
                        padding: 2px 14px;
                        font-size: 12px;
                        min-height: 20px;
                        max-height: 24px;
                    }
                """
                btn.setStyleSheet(btn_css)
                return
        # 默认紧凑样式（蓝色背景，对齐全局 setStyleSheet 中 QPushButton 但更紧凑）
        primary = self._get_style('primary', '#007acc')
        primary_hover = self._get_style('primary-hover', '#005a9e')
        primary_pressed = self._get_style('primary-pressed', '#004575')
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary};
                color: #ffffff;
                border: none;
                padding: 2px 14px;
                font-size: 12px;
                font-weight: bold;
                border-radius: 4px;
                min-height: 20px;
                max-height: 24px;
            }}
            QPushButton:hover {{ background-color: {primary_hover}; }}
            QPushButton:pressed {{ background-color: {primary_pressed}; }}
        """)

    def _jump_to_shortcut(self, path):
        """跳转到快捷路径指定的远程目录"""
        if not self.sftp or not path:
            return
        try:
            # 验证目标路径存在并切换
            self.sftp.stat(path)
            self.current_remote_dir = path
            self.remote_path.setText(self.current_remote_dir)
            self.refresh()
            self._set_status(f"SFTP状态: 已跳转 - {path}",
                             self._get_style('text-success', '#4ec9b0'))
        except Exception as e:
            self._set_status(f"SFTP状态: 路径无效 ({str(e)})",
                             self._get_style('text-danger', '#f44747'))

    def _jump_to_local_shortcut(self, path):
        """切换本地路径到快捷路径指定的目录"""
        if not path or not os.path.isdir(path):
            self._set_status(f"SFTP状态: 本地路径无效 - {path}",
                             self._get_style('text-danger', '#f44747'))
            return
        SFTPDialog._last_upload_dir = path
        SFTPDialog._last_download_dir = path
        self.local_path.setText(path)
        self._set_status(f"SFTP状态: 本地路径已切换 - {path}",
                         self._get_style('text-success', '#4ec9b0'))

    def _browse_local_dir(self):
        """浏览选择本地目录"""
        local_dir = QFileDialog.getExistingDirectory(
            self, "选择本地目录", SFTPDialog._last_upload_dir)
        if local_dir:
            SFTPDialog._last_upload_dir = local_dir
            SFTPDialog._last_download_dir = local_dir
            self.local_path.setText(local_dir)

    def _show_shortcut_menu(self, idx):
        """右键快捷路径按钮菜单（删除/重命名）"""
        if idx < 0 or idx >= len(self._shortcuts):
            return
        sc = self._shortcuts[idx]
        menu = QMenu(self)
        if self._config_manager:
            menu.setStyleSheet(self._config_manager.get_menu_css())
        act_rename = menu.addAction("重命名")
        act_delete = menu.addAction("删除")
        action = menu.exec(QCursor.pos())
        if action is act_delete:
            del self._shortcuts[idx]
            self._save_shortcuts()
            self._render_shortcuts()
        elif action is act_rename:
            self._edit_shortcut_dialog(idx)

    def _add_shortcut_dialog(self):
        """新增快捷路径弹窗：类型 + 名称 + 路径"""
        dialog = _ShortcutEditDialog(
            name="", path=self.current_remote_dir, sc_type='remote',
            config_manager=self._config_manager, parent=self)
        if dialog.exec():
            name, path, sc_type = dialog.get_values()
            if not path:
                return
            if not name:
                name = path
            self._shortcuts.append({'name': name, 'path': path, 'type': sc_type})
            self._save_shortcuts()
            self._render_shortcuts()

    def _edit_shortcut_dialog(self, idx):
        """编辑现有快捷路径"""
        sc = self._shortcuts[idx]
        dialog = _ShortcutEditDialog(
            name=sc.get('name', ''), path=sc.get('path', ''),
            sc_type=sc.get('type', 'remote'),
            config_manager=self._config_manager, parent=self)
        if dialog.exec():
            name, path, sc_type = dialog.get_values()
            if not path:
                return
            if not name:
                name = path
            self._shortcuts[idx] = {'name': name, 'path': path, 'type': sc_type}
            self._save_shortcuts()
            self._render_shortcuts()

    def _get_color_scheme(self, parent):
        """从父组件获取颜色方案"""
        if parent and hasattr(parent, '_color_scheme'):
            return parent._color_scheme
        return {}

    def _get_style(self, key, default=None):
        """获取样式配置（优先从config_manager实时获取，支持新旧两种格式）"""
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        value = self._color_scheme.get(key)
        if value is not None:
            return value
        old_key_map = {
            'background_main': 'bg-main',
            'background_secondary': 'bg-secondary',
            'background_tertiary': 'bg-tertiary',
            'background_input': 'bg-input',
            'background_input_focus': 'bg-input-focus',
            'text_primary': 'text',
            'text_secondary': 'text-secondary',
            'border_light': 'border-light',
            'border_focus': 'border-focus',
            'primary_hover': 'primary-hover',
            'primary_pressed': 'primary-pressed'
        }
        if key in old_key_map:
            return self._color_scheme.get(old_key_map[key], default)
        return default

    def init_ui(self):
        self.setWindowTitle("SFTP 文件传输")
        self.setMinimumSize(430, 520)
        self.resize(462, 560)
        # 居中显示在屏幕上
        screen = self.screen().availableGeometry()
        x = (screen.width() - 462) // 2
        y = (screen.height() - 560) // 2
        self.setGeometry(x, y, 462, 560)

        bg_secondary = self._get_style('bg-secondary', '#252526')
        text_primary = self._get_style('text', '#ffffff')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        border_focus = self._get_style('border-focus', '#007acc')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        bg_main = self._get_style('bg-main', '#1e1e1e')
        border = self._get_style('border', '#3c3c3c')
        selection = self._get_style('selection', '#007acc')
        selection_text = self._get_style('selection-text', '#ffffff')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        primary = self._get_style('primary', '#007acc')
        primary_hover = self._get_style('primary-hover', '#005a9e')
        primary_pressed = self._get_style('primary-pressed', '#004575')

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_secondary};
                color: {text_primary};
            }}
            QLabel {{
                color: {text_primary};
                font-size: 13px;
            }}
            QLineEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 5px 10px;
                border-radius: 4px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
            QListWidget {{
                background-color: {bg_main};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: 4px;
                font-size: 11px;
                padding: 2px;
            }}
            QListWidget::item {{
                padding: 0px 6px;
            }}
            QListWidget::item:selected {{
                background-color: {selection};
                color: {selection_text};
            }}
            QListWidget::item:hover {{
                background-color: {bg_tertiary};
            }}
            QPushButton {{
                background-color: {primary};
                color: #ffffff;
                border: none;
                padding: 2px 16px;
                font-size: 12px;
                font-weight: bold;
                border-radius: 4px;
                min-height: 20px;
            }}
            QPushButton:hover {{
                background-color: {primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {primary_pressed};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)  # 上下边距减少
        layout.setSpacing(6)  # 紧凑布局间距（原8→6）

        # 连接状态（创建后暂不添加到布局，最终移至最下方）
        text_danger = self._get_style('text-danger', '#ff6b6b')
        self.status_label = QLabel("SFTP状态: 未连接")
        self.status_label.setStyleSheet(f"color: {text_danger}; font-weight: bold; font-size: 12px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 远程路径
        remote_layout = QHBoxLayout()
        remote_layout.setSpacing(6)  # 紧凑间距
        remote_label = QLabel("远程路径:")
        remote_label.setStyleSheet(f"color: {text_primary}; font-weight: 500;")
        remote_label.setFixedWidth(72)  # 略微收窄标签
        remote_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        remote_layout.addWidget(remote_label)
        self.remote_path = QLineEdit()
        self.remote_path.setText(self.current_remote_dir)
        self.remote_path.returnPressed.connect(self.on_remote_path_changed)
        remote_layout.addWidget(self.remote_path)
        layout.addLayout(remote_layout)

        # 本地路径（显示上传/下载时使用的本地目录）
        local_layout = QHBoxLayout()
        local_layout.setSpacing(6)
        local_label = QLabel("本地路径:")
        local_label.setStyleSheet(f"color: {text_primary}; font-weight: 500;")
        local_label.setFixedWidth(72)
        local_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        local_layout.addWidget(local_label)
        self.local_path = QLineEdit()
        self.local_path.setText(SFTPDialog._last_upload_dir)
        self.local_path.setReadOnly(True)
        local_layout.addWidget(self.local_path)
        # 浏览按钮：选择本地目录
        self.local_browse_btn = QPushButton("浏览")
        self.local_browse_btn.setFixedHeight(24)
        self._style_operation_btn(self.local_browse_btn)
        self.local_browse_btn.clicked.connect(self._browse_local_dir)
        local_layout.addWidget(self.local_browse_btn)
        layout.addLayout(local_layout)

        # 快捷路径区域：横向排列的快捷按钮 + 末尾的"+"新增按钮
        # 支持点击跳转、右键删除/重命名，列表持久化到 sftp_shortcuts.json
        self.shortcuts_widget = QWidget()
        self.shortcuts_layout = QHBoxLayout(self.shortcuts_widget)
        self.shortcuts_layout.setContentsMargins(0, 0, 0, 0)
        self.shortcuts_layout.setSpacing(3)  # 紧凑间距（原4→3）
        self._render_shortcuts()
        layout.addWidget(self.shortcuts_widget)

        # 文件列表
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.on_item_double_click)
        layout.addWidget(self.file_list, 1)

        # 按钮 - 4个按钮平均分布间隔，整体紧凑（降低高度/缩小padding）
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(0)
        self.upload_btn = QPushButton("上传")
        self.download_btn = QPushButton("下载")
        self.refresh_btn = QPushButton("刷新")
        close_btn = QPushButton("关闭")
        # 紧凑尺寸：统一高度
        for b in (self.upload_btn, self.download_btn, self.refresh_btn, close_btn):
            b.setFixedHeight(24)
        self._style_operation_btn(self.upload_btn)
        self._style_operation_btn(self.download_btn)
        self._style_operation_btn(self.refresh_btn)
        self._style_operation_btn(close_btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.upload_btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.download_btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch(1)
        layout.addLayout(btn_layout)

        # 连接状态栏（最下方）
        layout.addWidget(self.status_label)

        self.upload_btn.clicked.connect(self.upload)
        self.download_btn.clicked.connect(self.download)
        self.refresh_btn.clicked.connect(self.refresh)
        close_btn.clicked.connect(self.close)

    def init_sftp(self):
        """初始化SFTP连接（延迟调用，避免弹窗启动卡顿）"""
        strategy = self.connection_context._strategy
        text_danger = self._get_style('text-danger', '#ff6b6b')
        text_success = self._get_style('text-success', '#00ff00')

        # 前置检查：连接策略类型和连接状态
        if not isinstance(strategy, SSHConnection):
            self._set_status("SFTP状态: 仅支持SSH连接", text_danger)
            self.set_buttons_enabled(False)
            return

        if not strategy.client:
            self._set_status("SFTP状态: SSH未连接", text_danger)
            self.set_buttons_enabled(False)
            return

        try:
            self.sftp = strategy.client.open_sftp()
            self.current_remote_dir = self.sftp.normalize(".")
            self.remote_path.setText(self.current_remote_dir)
            self._set_status(f"SFTP状态: 已连接 ({strategy.host})", text_success)
            self.refresh()
        except Exception as e:
            self._set_status(f"SFTP状态: 连接失败 ({str(e)})", text_danger)
            self.set_buttons_enabled(False)

    def _set_status(self, text, color):
        """统一设置状态栏文本和颜色"""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px;")

    def set_buttons_enabled(self, enabled):
        """设置按钮状态"""
        self.upload_btn.setEnabled(enabled)
        self.download_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)

    def _show_operation_result(self, success, message):
        """在状态栏显示操作结果（替代弹窗提醒）"""
        color = self._get_style('text-success', '#4ec9b0') if success else self._get_style('text-danger', '#f44747')
        self._set_status(f"SFTP状态: {message}", color)

    def _style_progress_dialog(self, progress):
        """为进度对话框应用主题样式"""
        bg_secondary = self._get_style('bg-secondary', '#252526')
        text_primary = self._get_style('text', '#ffffff')
        primary = self._get_style('primary', '#007acc')
        border_light = self._get_style('border-light', '#5a5a5d')
        if self._config_manager:
            border_radius = self._config_manager.get_border_radius('sm', '4px')
        else:
            border_radius = '4px'
        progress.setStyleSheet(f"""
            QProgressDialog {{
                background-color: {bg_secondary};
                color: {text_primary};
            }}
            QProgressDialog QLabel {{
                color: {text_primary};
            }}
            QProgressBar {{
                background-color: {border_light};
                border: 1px solid {border_light};
                border-radius: {border_radius};
                text-align: center;
                color: {text_primary};
            }}
            QProgressBar::chunk {{
                background-color: {primary};
                border-radius: {border_radius};
            }}
        """)

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
            # 基于current_remote_dir字符串计算父目录，避免依赖SFTP客户端工作目录
            # （SFTP工作目录在初始化后被固定，未跟随导航更新，导致normalize('..')行为不一致）
            try:
                cur = self.current_remote_dir.rstrip('/')
                if not cur or cur == '':
                    # 已在根目录，停留在根目录
                    parent = '/'
                else:
                    parent = posixpath.dirname(cur)
                    if not parent or not parent.startswith('/'):
                        parent = '/'
                self.current_remote_dir = parent
                self.remote_path.setText(self.current_remote_dir)
                self.refresh()
            except:
                pass
        elif data['type'] == 'root':
            # 跳转根目录
            try:
                self.current_remote_dir = "/"
                self.remote_path.setText(self.current_remote_dir)
                self.refresh()
            except:
                pass

    def refresh(self):
        """刷新远程文件列表（根目录优先，上级目录次之，目录在前文件在后，按名称排序）"""
        self.file_list.clear()

        if not self.sftp:
            self.file_list.addItem("SFTP未连接")
            return

        try:
            # 1. 根目录快捷入口（第一位）
            root_item = QListWidgetItem("/")
            root_item.setData(Qt.ItemDataRole.UserRole, {'type': 'root'})
            self.file_list.addItem(root_item)

            # 2. 上级目录快捷入口（第二位）
            parent_item = QListWidgetItem("../")
            parent_item.setData(Qt.ItemDataRole.UserRole, {'type': 'parent'})
            self.file_list.addItem(parent_item)

            # 3. 获取目录内容并按类型+名称排序
            entries = list(self.sftp.listdir_attr(self.current_remote_dir))
            entries.sort(key=lambda e: (0 if S_ISDIR(e.st_mode) else 1, e.filename.lower()))

            for entry in entries:
                is_dir = S_ISDIR(entry.st_mode)
                name = entry.filename + "/" if is_dir else entry.filename
                icon = "📁 " if is_dir else "📄 "
                size = "" if is_dir else self.format_size(entry.st_size)
                item_text = f"{icon}{name}\t{size}" if size else f"{icon}{name}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, {
                    'type': 'dir' if is_dir else 'file',
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

    def _get_remote_file_size(self, remote_path):
        """获取远程文件大小"""
        try:
            file_stat = self.sftp.stat(remote_path)
            return file_stat.st_size
        except:
            return 0

    def upload(self):
        """上传文件到远程"""
        if not self.sftp:
            QMessageBox.warning(self, "警告", "SFTP未连接")
            return

        local_file, _ = QFileDialog.getOpenFileName(self, "选择要上传的文件", SFTPDialog._last_upload_dir)
        if not local_file:
            return

        # 记忆上次上传使用的目录
        local_dir = os.path.dirname(local_file)
        SFTPDialog._last_upload_dir = local_dir

        filename = os.path.basename(local_file)
        remote_file = f"{self.current_remote_dir}/{filename}".replace("//", "/")

        # 获取本地文件大小用于显示
        local_file_size = os.path.getsize(local_file) if os.path.exists(local_file) else 0

        # 创建进度对话框
        progress = QProgressDialog(f"正在上传 {filename}...", None, 0, 100, self)
        progress.setWindowTitle("上传文件")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setCancelButton(None)
        progress.setLabelText(f"上传进度: 0% (0 B / {self.format_size(local_file_size)})")
        self._style_progress_dialog(progress)
        progress.show()

        last_progress = [0]

        def progress_callback(transferred, total):
            percent = int(transferred / total * 100) if total > 0 else 0
            if percent > last_progress[0]:
                last_progress[0] = percent
                progress.setValue(percent)
                progress.setLabelText(f"上传进度: {percent}% ({self.format_size(transferred)}/{self.format_size(total)})")
                QApplication.processEvents()

        try:
            self.sftp.put(local_file, remote_file, callback=progress_callback)
            progress.setValue(100)
            progress.setLabelText(f"上传进度: 100% ({self.format_size(local_file_size)}/{self.format_size(local_file_size)})")
            self._show_operation_result(True, f"上传完成: {filename} ({self.format_size(local_file_size)})")
            self.refresh()
        except Exception as e:
            self._show_operation_result(False, f"上传失败: {str(e)}")
        finally:
            progress.close()

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

        local_dir = QFileDialog.getExistingDirectory(self, "选择下载目录", SFTPDialog._last_download_dir)
        if not local_dir:
            return

        # 记忆上次下载使用的目录
        SFTPDialog._last_download_dir = local_dir

        local_file = os.path.join(local_dir, data['name'])
        filename = data['name']

        # 获取文件大小
        file_size = data.get('size', 0)
        if file_size == 0:
            try:
                file_stat = self.sftp.stat(data['path'])
                file_size = file_stat.st_size
            except:
                pass

        # 创建进度对话框
        progress = QProgressDialog(f"正在下载 {filename}...", None, 0, 100, self)
        progress.setWindowTitle("下载文件")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setCancelButton(None)
        progress.setLabelText(f"下载进度: 0% (0 B / {self.format_size(file_size)})")
        self._style_progress_dialog(progress)
        progress.show()

        last_progress = [0]

        def progress_callback(transferred, total):
            percent = int(transferred / total * 100) if total > 0 else 0
            if percent > last_progress[0]:
                last_progress[0] = percent
                progress.setValue(percent)
                progress.setLabelText(f"下载进度: {percent}% ({self.format_size(transferred)}/{self.format_size(total)})")
                QApplication.processEvents()

        try:
            self.sftp.get(data['path'], local_file, callback=progress_callback)
            progress.setValue(100)
            progress.setLabelText(f"下载进度: 100% ({self.format_size(file_size)}/{self.format_size(file_size)})")
            self._show_operation_result(True, f"下载完成: {filename} ({self.format_size(file_size)})")
        except Exception as e:
            self._show_operation_result(False, f"下载失败: {str(e)}")
        finally:
            progress.close()

    def closeEvent(self, event):
        """关闭时清理SFTP连接，并保存快捷路径"""
        if self.sftp:
            try:
                self.sftp.close()
            except:
                pass
        # 保存快捷路径（即使弹窗未通过+按钮新增也可能有改动）
        self._save_shortcuts()
        event.accept()


# 脚本目录（与 script_manager_widget.py 一致）
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts')


class _ShortcutEditDialog(QDialog):
    """SFTP快捷路径新增/编辑弹窗（类型 + 名称 + 路径）

    支持两种类型：
    - remote: 服务器路径（点击时修改远程目录）
    - local: 本地路径（点击时修改本地目录）
    """

    # 倒三角箭头图片路径
    _DOWN_ARROW_IMG = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'assets', 'down_arrow.png'
    ).replace('\\', '/')

    def __init__(self, name="", path="", sc_type='remote', config_manager=None, parent=None):
        super().__init__(parent)
        self._config_manager = config_manager
        self.setWindowTitle("编辑快捷路径" if name or path else "新增快捷路径")
        self.setMinimumSize(420, 200)
        self._init_ui(name, path, sc_type)

    def _get_style(self, key, default=None):
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        return default

    def _get_font_size(self, key, default='12px'):
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        return default

    def _get_border_radius(self, key, default='4px'):
        if self._config_manager:
            return self._config_manager.get_border_radius(key, default)
        return default

    def _init_ui(self, name, path, sc_type):
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        text_primary = self._get_style('text', '#ffffff')
        border = self._get_style('border', '#3c3c3c')
        border_focus = self._get_style('border-focus', '#007acc')
        font_size_normal = self._get_font_size('size-md', '12px')
        border_radius = self._get_border_radius('sm', '4px')
        unified_btn_css = ""
        if self._config_manager:
            unified_btn_css = self._config_manager.get_button_css('button')

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg_main}; }}
            QLabel {{ color: {text_primary}; font-size: {font_size_normal}; }}
            QLineEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius};
                padding: 4px 8px;
                font-size: {font_size_normal};
            }}
            QLineEdit:focus {{ border: 2px solid {border_focus}; }}
            QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius};
                padding: 4px 8px;
                font-size: {font_size_normal};
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{ image: url({_ShortcutEditDialog._DOWN_ARROW_IMG}); }}
            QPushButton {{
                padding: 4px 16px;
                font-size: {font_size_normal};
                font-weight: bold;
                border-radius: {border_radius};
            }}
            {unified_btn_css}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        label_style = f"color: {text_primary}; font-size: {font_size_normal}; font-weight: 500;"

        # 类型行：服务器路径 / 本地路径
        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        type_label = QLabel("类型:")
        type_label.setStyleSheet(label_style)
        type_label.setFixedWidth(70)
        type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        type_row.addWidget(type_label)
        self.type_combo = QComboBox()
        self.type_combo.addItem("服务器路径", 'remote')
        self.type_combo.addItem("本地路径", 'local')
        # 设置初始类型
        idx = 0 if sc_type == 'remote' else 1
        self.type_combo.setCurrentIndex(idx)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self.type_combo)
        layout.addLayout(type_row)

        # 名称行
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_label = QLabel("名称:")
        name_label.setStyleSheet(label_style)
        name_label.setFixedWidth(70)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_row.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setText(name)
        self.name_input.setPlaceholderText("快捷路径名称（可留空，自动用路径）")
        name_row.addWidget(self.name_input)
        layout.addLayout(name_row)

        # 路径行
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_label = QLabel("路径:")
        path_label.setStyleSheet(label_style)
        path_label.setFixedWidth(70)
        path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path_row.addWidget(path_label)
        self.path_input = QLineEdit()
        self.path_input.setText(path)
        self.path_input.setPlaceholderText("远程绝对路径，如 /var/log")
        path_row.addWidget(self.path_input)
        # 浏览按钮（仅本地路径类型时显示）
        self.browse_btn = QPushButton("浏览")
        self.browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(self.browse_btn)
        layout.addLayout(path_row)

        # 初始化浏览按钮可见性
        self._on_type_changed(self.type_combo.currentIndex())

        layout.addStretch()

        # 按钮区
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_type_changed(self, index):
        """类型切换时更新路径占位符和浏览按钮可见性"""
        sc_type = self.type_combo.currentData()
        if sc_type == 'local':
            self.path_input.setPlaceholderText("本地目录路径，如 C:\\Users 或 /home/user")
            self.browse_btn.setVisible(True)
        else:
            self.path_input.setPlaceholderText("远程绝对路径，如 /var/log")
            self.browse_btn.setVisible(False)

    def _browse_path(self):
        """浏览选择本地目录"""
        from PyQt6.QtWidgets import QFileDialog
        current_path = self.path_input.text().strip()
        if not current_path:
            current_path = os.path.expanduser("~")
        local_dir = QFileDialog.getExistingDirectory(self, "选择本地目录", current_path)
        if local_dir:
            self.path_input.setText(local_dir)

    def get_values(self):
        """获取用户输入的类型、名称和路径"""
        return (self.name_input.text().strip(),
                self.path_input.text().strip(),
                self.type_combo.currentData())


class ButtonEditDialog(QDialog):
    """新增/编辑按钮对话框

    支持两种类型：
    - command: 关联 shell 命令
    - script: 关联 Python 脚本文件
    """

    def __init__(self, button_data=None, config_manager=None, parent=None):
        super().__init__(parent)
        self._button_data = button_data  # None = 新增
        self._config_manager = config_manager
        self._script_preview = None  # 当前预览的脚本路径
        self.init_ui()
        if button_data:
            self._fill_form(button_data)

    def _get_style(self, key, default=None):
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        return default

    def _get_font_size(self, key, default='12px'):
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        return default

    def init_ui(self):
        self.setWindowTitle("编辑按钮" if self._button_data else "新增按钮")
        self.setMinimumSize(480, 360)

        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        border = self._get_style('border', '#3c3c3c')
        border_focus = self._get_style('border-focus', '#007acc')
        font_size_normal = self._get_font_size('size-md', '12px')
        border_radius = self._get_style('border-radius-sm', '4px')

        # 使用统一菜单 CSS（用于 QComboBox 下拉列表）
        menu_css = self._config_manager.get_menu_css() if self._config_manager else ""
        # 统一按钮 CSS（供确定/浏览等按钮复用）
        self._unified_btn_css = self._config_manager.get_button_css('button') if self._config_manager else ""

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg_main}; }}
            QLabel {{ color: {text_primary}; font-size: {font_size_normal}; }}
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius};
                padding: 4px 8px;
                font-size: {font_size_normal};
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
                border: 2px solid {border_focus};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: url({_DOWN_ARROW_IMG});
            }}
            QComboBox QAbstractItemView {{
                background-color: {bg_tertiary};
                color: {text_primary};
                border: 1px solid {border};
                selection-background-color: {self._get_style('primary', '#3a8fd4')};
                selection-color: #ffffff;
                outline: none;
            }}
            {menu_css}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # 名称行
        name_row = QHBoxLayout()
        name_label = QLabel("名称:")
        name_label.setFixedWidth(76)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("按钮显示名称")
        name_row.addWidget(name_label)
        name_row.addWidget(self.name_input)
        layout.addLayout(name_row)

        # 类型行
        type_row = QHBoxLayout()
        type_label = QLabel("类型:")
        type_label.setFixedWidth(76)
        type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.type_combo = QComboBox()
        self.type_combo.addItem("命令", "command")
        self.type_combo.addItem("脚本", "script")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(type_label)
        type_row.addWidget(self.type_combo)
        type_row.addStretch()
        layout.addLayout(type_row)

        # 动态参数区容器
        self.config_widget = QWidget()
        self.config_layout = QVBoxLayout(self.config_widget)
        self.config_layout.setContentsMargins(0, 0, 0, 0)
        self.config_layout.setSpacing(6)
        layout.addWidget(self.config_widget)

        layout.addStretch()

        # 底部按钮 — 使用统一按钮 CSS
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self._on_accept)
        ok_btn.setStyleSheet(self._unified_btn_css)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius};
                padding: 6px 16px;
                font-size: {font_size_normal};
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {bg_tertiary}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # 初始化默认类型 UI
        self._on_type_changed()

    def _clear_config_layout(self):
        """清空动态参数区"""
        while self.config_layout.count():
            item = self.config_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_sub_layout(item.layout())

    def _clear_sub_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_sub_layout(item.layout())

    def _on_type_changed(self):
        """根据类型切换参数区内容"""
        self._clear_config_layout()
        btn_type = self.type_combo.currentData()

        if btn_type == 'command':
            # 命令输入
            cmd_label = QLabel("命令:")
            cmd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.config_layout.addWidget(cmd_label)
            self.cmd_input = QPlainTextEdit()
            self.cmd_input.setPlaceholderText("输入要执行的命令，如: ls -la")
            self.cmd_input.setMinimumHeight(80)
            self.config_layout.addWidget(self.cmd_input)

            # 超时
            timeout_row = QHBoxLayout()
            timeout_label = QLabel("超时(秒):")
            timeout_label.setFixedWidth(76)
            timeout_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.timeout_input = QSpinBox()
            self.timeout_input.setRange(1, 60)
            self.timeout_input.setValue(5)
            timeout_row.addWidget(timeout_label)
            timeout_row.addWidget(self.timeout_input)
            timeout_row.addStretch()
            self.config_layout.addLayout(timeout_row)

        else:  # script
            # 脚本文件路径 + 浏览
            path_label = QLabel("脚本文件:")
            path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.config_layout.addWidget(path_label)
            path_row = QHBoxLayout()
            self.script_path_input = QLineEdit()
            self.script_path_input.setPlaceholderText("选择 .py 脚本文件")
            browse_btn = QPushButton("浏览...")
            browse_btn.setFixedWidth(80)
            browse_btn.setStyleSheet(self._unified_btn_css)
            browse_btn.clicked.connect(self._browse_script)
            path_row.addWidget(self.script_path_input)
            path_row.addWidget(browse_btn)
            self.config_layout.addLayout(path_row)

            # 脚本下拉快速选择
            combo_row = QHBoxLayout()
            combo_label = QLabel("快速选择:")
            combo_label.setFixedWidth(76)
            combo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.script_combo = QComboBox()
            self._populate_script_combo()
            self.script_combo.currentIndexChanged.connect(self._on_script_selected)
            combo_row.addWidget(combo_label)
            combo_row.addWidget(self.script_combo)
            combo_row.addStretch()
            self.config_layout.addLayout(combo_row)

            # 预览
            preview_label = QLabel("预览:")
            preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.config_layout.addWidget(preview_label)
            self.script_preview = QPlainTextEdit()
            self.script_preview.setReadOnly(True)
            self.script_preview.setMaximumHeight(120)
            self.script_preview.setPlaceholderText("选择脚本后显示预览...")
            self.config_layout.addWidget(self.script_preview)

    def _populate_script_combo(self):
        """填充脚本下拉列表"""
        self.script_combo.blockSignals(True)
        self.script_combo.clear()
        self.script_combo.addItem("-- 选择脚本 --", "")
        if os.path.isdir(SCRIPTS_DIR):
            for fname in sorted(os.listdir(SCRIPTS_DIR)):
                if fname.endswith('.py'):
                    self.script_combo.addItem(fname, os.path.join(SCRIPTS_DIR, fname))
        self.script_combo.blockSignals(False)

    def _on_script_selected(self):
        """脚本下拉选择 → 填充路径 + 预览"""
        path = self.script_combo.currentData()
        if path:
            self.script_path_input.setText(path)
            self._update_preview(path)

    def _browse_script(self):
        """浏览选择脚本文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择脚本文件", SCRIPTS_DIR, "Python Files (*.py)")
        if path:
            self.script_path_input.setText(path)
            self._update_preview(path)

    def _update_preview(self, path):
        """更新脚本预览"""
        if not hasattr(self, 'script_preview'):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = [f.readline() for _ in range(20)]
            self.script_preview.setPlainText(''.join(lines))
            self._script_preview = path
        except Exception as e:
            self.script_preview.setPlainText(f"无法读取: {e}")

    def _fill_form(self, data):
        """编辑模式：填充表单"""
        self.name_input.setText(data.get('name', ''))
        btn_type = data.get('type', 'command')
        idx = self.type_combo.findData(btn_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        # _on_type_changed 已重建控件，填充值
        if btn_type == 'command':
            if hasattr(self, 'cmd_input'):
                self.cmd_input.setPlainText(data.get('command', ''))
            if hasattr(self, 'timeout_input'):
                self.timeout_input.setValue(data.get('timeout', 5))
        else:
            if hasattr(self, 'script_path_input'):
                self.script_path_input.setText(data.get('script_path', ''))
                if data.get('script_path'):
                    self._update_preview(data['script_path'])

    def _on_accept(self):
        """确定按钮：校验并接受"""
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入按钮名称")
            return

        btn_type = self.type_combo.currentData()
        if btn_type == 'command':
            cmd = self.cmd_input.toPlainText().strip()
            if not cmd:
                QMessageBox.warning(self, "提示", "请输入命令内容")
                return
        else:
            path = self.script_path_input.text().strip()
            if not path:
                QMessageBox.warning(self, "提示", "请选择脚本文件")
                return
            if not os.path.isfile(path) or not path.endswith('.py'):
                QMessageBox.warning(self, "提示", "脚本文件不存在或不是 .py 文件")
                return

        self.accept()

    def get_button_data(self):
        """返回标准化的按钮数据 dict"""
        btn_type = self.type_combo.currentData()
        data = {
            'id': self._button_data['id'] if self._button_data else uuid.uuid4().hex,
            'name': self.name_input.text().strip(),
            'type': btn_type,
        }
        if btn_type == 'command':
            data['command'] = self.cmd_input.toPlainText().strip()
            data['timeout'] = self.timeout_input.value()
        else:
            data['script_path'] = self.script_path_input.text().strip()
        return data
