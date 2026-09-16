import os
import posixpath
import re
import threading
import time
import uuid
from datetime import datetime
from stat import S_ISDIR
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QLabel, QLineEdit, QComboBox, QSpinBox, QPushButton,
    QTextEdit, QTabWidget, QTabBar, QMessageBox, QCheckBox,
    QListWidget, QListWidgetItem, QMenu, QDialog,
    QPlainTextEdit, QFileDialog, QProgressDialog, QApplication,
    QDialogButtonBox, QFrame, QStackedWidget, QToolButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import (
    QFont, QAction, QTextCursor, QColor, QKeyEvent, QTextCharFormat,
    QCursor, QKeySequence, QShortcut
)
from .connection_context import ConnectionContext
from .ssh_connection import SSHConnection
from .telnet_connection import TelnetConnection
from .serial_connection import SerialConnection
from .connection_manager import ConnectionManager
from .connection_factory import ConnectionFactory
from .ansi_parser import ANSIParser
from plugins.script_runner import Session, ScriptRunner

# 下拉框三角形箭头图片路径
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DOWN_ARROW_IMG = os.path.join(
    _PROJECT_ROOT,
    'assets', 'down_arrow.png'
).replace('\\', '/')

# 终端会话日志默认目录
_TERMINAL_LOG_DIR = os.path.join(_PROJECT_ROOT, 'logs', 'terminal')

# 保活发送间隔（秒）
_KEEPALIVE_INTERVAL = 30


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

        builder.add_separator()

        # 日志记录：勾选后每个会话的终端内容保存到 logs/terminal 目录
        log_enabled = getattr(widget, '_log_enabled', False)
        builder.add_action(
            "日志记录",
            lambda checked: widget.toggle_logging(checked),
            checkable=True,
            checked=log_enabled,
        )

        # 侧边栏：控制左侧保存链接栏显示/收缩
        sidebar_visible = getattr(widget, '_sidebar_visible', True)
        builder.add_action(
            "侧边栏",
            lambda checked: widget.toggle_sidebar(checked),
            checkable=True,
            checked=sidebar_visible,
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
        self._mouse_down = False  # 鼠标按下标记（拖选进行中，渲染层据此保护选区）
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
                # QTextEdit.selectedText() 用 U+2029/U+2028 表示段落/行分隔，
                # 直接入剪贴板会导致外部应用/终端粘贴时无法识别换行；
                # 先统一为 \n，再转为 Windows 剪贴板标准的 \r\n
                selected = selected.replace('\u2029', '\n').replace('\u2028', '\n')
                selected = selected.replace('\r\n', '\n').replace('\n', '\r\n')
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

    def mousePressEvent(self, event):
        """记录点击前的光标位置（供 mouseRelease 恢复），并标记拖选进行中"""
        self._cursor_pos_before_mouse = self.textCursor().position()
        self._mouse_down = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放后：纯点击（非拖选）恢复光标位置

        终端光标位置由远程 shell 通过 ANSI 序列控制，
        鼠标点击不应改变它，否则会导致后续行内编辑回显插入错位。
        拖选/双击选词（复制场景）保留选区，渲染层在选中保护模式下
        不会触碰显示光标（见 SessionTab._render_text）。
        """
        super().mouseReleaseEvent(event)
        self._mouse_down = False
        if not self.textCursor().hasSelection():
            pos = getattr(self, '_cursor_pos_before_mouse', None)
            if pos is not None:
                cur = self.textCursor()
                cur.setPosition(min(pos, self.document().characterCount() - 1))
                self.setTextCursor(cur)

    def keyPressEvent(self, event):
        """拦截所有键盘事件并发送给父组件处理"""
        # 终端标准行为：按键清除残留选区（拖选/双击选中的高亮），
        # 恢复正常渲染与光标跟踪
        if self.textCursor().hasSelection():
            cur = self.textCursor()
            cur.clearSelection()
            self.setTextCursor(cur)
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
        self._bracketed_paste_enabled = False  # 远端shell是否启用bracketed paste（收到 \x1b[?2004h 时置位）
        self._application_cursor_mode = False  # DECCKM 应用光标键模式（收到 \x1b[?1h 时置位，方向/Home/End 改发 SS3 序列）
        self._saved_cursor_pos = None  # DECSC/DECRC (\x1b7/\x1b[s 保存的光标位置)
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
        # 会话日志：是否将终端内容写入日志文件（由全局设置开关控制）
        self._log_enabled = False
        self._log_dir = _TERMINAL_LOG_DIR
        self._log_file = None
        self._log_path = ""

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
                border-radius: 8px;
                margin: 6px;
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
                border-radius: 8px;
                margin: 6px;
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

        # 日志记录开启时同步写入会话日志文件（去除 ANSI 转义序列，保留终端文字内容）
        self._write_session_log(text)

        self._render_text(text, color)

    # ========== 会话日志 ==========

    def set_logging(self, enabled):
        """开启/关闭本会话的终端内容日志记录

        - 开启时若尚未打开日志文件（如已连接状态下切换开关），立即创建；
        - 关闭时关闭文件句柄。新连接的日志文件在 connect_with_config 时创建。
        """
        self._log_enabled = bool(enabled)
        if self._log_enabled:
            if self._log_file is None:
                self._open_log_file()
        else:
            self._close_log_file()

    def _open_log_file(self):
        """为当前连接创建一个日志文件（每次连接生成一个新文件）"""
        self._close_log_file()
        if not self._log_enabled or not self._log_dir:
            return
        if not self.current_connection:
            # 尚未发起连接（如开启日志开关后），等 connect_with_config 时再创建
            return
        conn = self.current_connection or {}
        config = conn.get('config', {}) if isinstance(conn, dict) else {}
        base = conn.get('name') or config.get('host') or config.get('port') or 'session'
        safe_name = re.sub(r'[^A-Za-z0-9_.\-]', '_', str(base))[:40].strip('_') or 'session'
        filename = f"terminal_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            self._log_path = os.path.join(self._log_dir, filename)
            self._log_file = open(self._log_path, 'a', encoding='utf-8')
            self._log_file.write(
                f"===== 终端会话日志 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                f"{conn.get('name', '')} ({conn.get('type', '')}) =====\n"
            )
            self._log_file.flush()
        except Exception as e:
            print(f"打开终端日志文件失败: {e}")
            self._log_file = None
            self._log_path = ""

    def _close_log_file(self):
        """关闭日志文件句柄"""
        if self._log_file is not None:
            try:
                self._log_file.write(
                    f"===== 会话结束 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n"
                )
                self._log_file.close()
            except Exception:
                pass
        self._log_file = None

    def _write_session_log(self, text):
        """将一段终端输出（去除 ANSI 序列后）追加到日志文件"""
        if not self._log_enabled or self._log_file is None or not text:
            return
        try:
            clean = self._strip_ansi(text)
            clean = clean.replace('\r\n', '\n').replace('\r', '')
            self._log_file.write(clean)
            self._log_file.flush()
        except Exception:
            pass

    def _render_text(self, text, color=None):
        """将文本渲染到终端显示控件（内部方法，不记录历史）

        color 参数支持两种形式：
        - 颜色键名（如 'text-info', 'text-success'）：每次渲染时从当前主题实时解析
        - 十六进制颜色值（如 '#007acc'）：直接使用
        - None：使用ANSI解析器处理
        """
        if not text:
            return

        # 选中保护模式判定：用户正在拖选（鼠标按下）或已存在选区（双击选词/拖选结果）
        # 时，渲染过程不触碰显示光标，避免输出到达时选区被打断、
        # 光标跳到最新内容处导致无法准确选中
        preserve_selection = (getattr(self.terminal_display, '_mouse_down', False)
                              or self.terminal_display.textCursor().hasSelection())

        # 光标起点策略（终端光标位置同步的关键）：
        # - 系统提示文本（color 参数，如连接提示、错误信息）：始终追加到文档末尾；
        # - 选中保护模式：使用独立游标在文档末尾追加，不回写显示光标；
        # - 服务器回显：光标在最后一个文本块（当前输入行）时保持原位，使上一次
        #   渲染中通过 \x1b[D/\x1b[C 等序列移动到行中的光标得以延续，readline 的
        #   增量行编辑（\x1b[@ 插入、\x1b[P 删除）才能作用在正确位置；
        # - 光标不在最后一行（如用户点击了历史区）时：跳到文档末尾追加，
        #   避免把输出插入到历史文本中间。
        cursor = self.terminal_display.textCursor()
        if preserve_selection:
            cursor = QTextCursor(self.terminal_display.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
        elif color is not None:
            cursor.movePosition(QTextCursor.MoveOperation.End)
        else:
            doc = cursor.document()
            if doc.lastBlock().blockNumber() != cursor.block().blockNumber():
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

        # 选中保护模式下不回写显示光标、不自动滚动（保持选区与视图稳定，便于复制）；
        # 新输出已通过独立游标追加到文档末尾
        if not preserve_selection:
            self.terminal_display.setTextCursor(cursor)
            # 仅在需要时滚动，减少频繁调用
            if self._should_scroll():
                self.terminal_display.ensureCursorVisible()

        # 更新current_input：仅在Tab补全等待状态下从显示内容提取
        # 交互模式下current_input由本地按键追踪维护，减少对display解析的依赖
        # 注意：只有成功从最后一行识别到提示符时才清除等待标志，
        # 否则保持标志，等待后续分块重绘完成后再解析（避免半行状态误判）
        if getattr(self, '_tab_pending', False):
            if self._update_current_input_from_display():
                self._tab_pending = False

    def _update_current_input_from_display(self):
        """从显示内容中更新current_input（处理Tab补全、历史回填、多行粘贴等场景）

        策略：**只在最后一行能明确识别到提示符时才更新**，
        识别失败返回 False 且绝不修改 current_input，
        避免"把服务器输出当作用户输入"或"错误清空current_input"导致的删除异常。

        Returns:
            bool: 是否成功识别提示符并更新
        """
        import re
        plain_text = self.terminal_display.toPlainText()
        lines = plain_text.split('\n')
        if not lines:
            return False

        # 去除可能残留的 C0 控制字符（如 BEL），避免污染提示符识别和输入追踪
        last_line = re.sub(r'[\x00-\x1f\x7f]', '', lines[-1])

        # 查找提示符位置（常见提示符：# $ > %）
        prompt_patterns = [
            r'^\s*[\w@.\-\[\]]+[\s:]*[\w/~.@\-\[\]]*[#$>%]\s*',  # user@host:path$ / [user@host dir]$ 形式
            r'^\s*[A-Za-z0-9_.\-]+[#$>%]\s+',                    # 简化提示符 xxx$
            r'^\s*[#$>%]\s+',                                     # 最简 $
        ]

        for pattern in prompt_patterns:
            match = re.match(pattern, last_line)
            if match:
                self.current_input = last_line[match.end():]
                # 检测到提示符说明命令已结束，重置ANSI颜色格式，避免颜色跨命令残留
                if self.ansi_parser.enable_color:
                    self.ansi_parser.reset_format()
                return True

        # 未找到提示符 → 保守策略：保持原来的 current_input 不变
        return False

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

    # 无显示效果、直接忽略的 C0 控制字符：
    # BEL(0x07 响铃)、SO/SI(0x0e/0x0f 字符集切换) —— 绝不能插入文档，
    # 否则会形成不可见残留字符，导致退格/删除错位（Tab无补全后命令残留的根因）
    _IGNORE_CHARS = '\x07\x0e\x0f'

    def _terminal_write_char(self, cursor, ch):
        """按终端语义写入一个可见字符：光标处已有字符则覆盖，行尾则追加

        终端单元格是定长的，可打印字符总是"覆盖"光标处单元格并右移；
        QTextEdit 默认 insertText 是"插入"模式（尾部右移），在光标位于行中
        （如 readline 行内编辑回显）时会把文本写错位置，故行中需逐字覆盖。
        """
        block = cursor.block()
        block_end = block.position() + block.length() - 1  # 块内最后一个可见字符之后的位置
        if cursor.position() < block_end:
            # 光标右侧还有字符：选中右侧一个字符并替换（终端覆盖语义）
            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                QTextCursor.MoveMode.KeepAnchor, 1)
            cursor.insertText(ch)
        else:
            cursor.insertText(ch)

    def _insert_text_with_cr(self, cursor, text):
        """插入文本，按终端语义处理控制字符

        - \\r (CR)：回到行首并清空当前行内容（readline 重绘输入行的标准动作）
        - \\b (BS)：光标左移一格，不删除内容（删除由随后的"空格覆盖"或
          \\x1b[P 等序列表达）；不能跨出当前文本块
        - \\x07 (BEL) / \\x0e / \\x0f：无显示效果，忽略
        - \\t：制表符按4空格展开
        - \\x1b...：ANSI 光标/编辑序列，交由 _apply_cursor_sequence 执行
        - 可打印字符：行尾批量追加（快速路径），行中逐字覆盖
        """
        control_chars = '\r\b\x7f\t\x1b' + self._IGNORE_CHARS
        if not any(c in text for c in control_chars):
            # 纯文本快速路径：文档末尾直接批量追加；行中逐字覆盖
            if cursor.atEnd():
                cursor.insertText(text)
            else:
                for ch in text:
                    self._terminal_write_char(cursor, ch)
            return

        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == '\r':
                # 回到行首并清空整行（readline 重绘：先 CR 再重印提示符+输入行）
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                i += 1
            elif ch == '\b':
                # BS：仅左移光标（不允许退到上一个文本块）
                if cursor.position() > cursor.block().position():
                    cursor.movePosition(QTextCursor.MoveOperation.Left,
                                        QTextCursor.MoveMode.MoveAnchor, 1)
                i += 1
            elif ch in self._IGNORE_CHARS:
                # BEL/SO/SI：无显示效果，跳过
                i += 1
            elif ch == '\x7f':
                # DEL（输出流中罕见）：删除光标右侧字符
                if not cursor.atEnd():
                    cursor.movePosition(QTextCursor.MoveOperation.Right,
                                        QTextCursor.MoveMode.KeepAnchor, 1)
                    cursor.removeSelectedText()
                i += 1
            elif ch == '\t':
                if cursor.atEnd():
                    cursor.insertText("    ")
                else:
                    for _ in range(4):
                        self._terminal_write_char(cursor, ' ')
                i += 1
            elif ch == '\x1b':
                seq_end = self._scan_escape_seq(text, i)
                if seq_end > i:
                    self._apply_cursor_sequence(cursor, text[i:seq_end])
                    i = seq_end
                else:
                    i += 1  # 单独 ESC，忽略
            else:
                # 连续可打印字符片段
                j = i
                while j < n and text[j] not in control_chars:
                    j += 1
                run = text[i:j]
                if run:
                    if cursor.atEnd():
                        cursor.insertText(run)  # 文档末尾：批量追加（快速路径）
                    else:
                        for rc in run:
                            self._terminal_write_char(cursor, rc)
                i = j

    @staticmethod
    def _scan_escape_seq(text, i):
        """扫描从 i 处 ESC 开始的转义序列，返回序列结束下标（不完整返回 i）"""
        n = len(text)
        if i + 1 >= n:
            return i  # 只有单独 ESC
        c1 = text[i + 1]
        if c1 == '[':
            # CSI: ESC [ 参数(0x30-0x3F)* 中间(0x20-0x2F)* 终止(0x40-0x7E)
            j = i + 2
            while j < n and '\x20' <= text[j] <= '\x3f':
                j += 1
            if j < n and '\x40' <= text[j] <= '\x7e':
                return j + 1
            return i  # 不完整，等待更多数据
        if c1 == ']':
            # OSC: ESC ] ... BEL(0x07) 或 ST(ESC \)
            j = i + 2
            while j < n:
                if text[j] == '\x07':
                    return j + 1
                if text[j] == '\x1b' and j + 1 < n and text[j + 1] == '\\':
                    return j + 2
                j += 1
            return i  # 不完整
        if c1 == 'O':
            # SS3: ESC O + 单字符（应用模式方向键等）
            if i + 2 < n:
                return i + 3
            return i
        # 其他 Fe 序列: ESC + 单字符
        return i + 2
    
    def _apply_cursor_sequence(self, cursor, seq):
        """应用 ANSI 光标/行编辑序列（readline 行编辑回显的核心）

        覆盖 readline 常用序列：
        - 光标移动：A/B/C/D（上下左右）、E/F（下/上+行首）、G/H/f（定位列）
        - 行编辑：K（清行）、J（清屏）、@（插入字符位）、P（删除字符）、X（擦除字符）
        - 光标保存/恢复：s/u、ESC 7/8
        - 私有模式：?2004h/?2004l（bracketed paste 协商）
        - 其余（h/l/r/L/M/S/T/q/~ 等）：无显示效果，忽略
        """
        if not seq or seq[0] != '\x1b':
            return

        MOVE = QTextCursor.MoveOperation
        MODE = QTextCursor.MoveMode

        # === Fe 单字符序列：ESC 7 保存光标 / ESC 8 恢复光标 ===
        if len(seq) == 2 and seq[1] == '7':
            self._saved_cursor_pos = cursor.position()
            return
        if len(seq) == 2 and seq[1] == '8':
            if self._saved_cursor_pos is not None:
                pos = max(0, min(self._saved_cursor_pos, cursor.document().characterCount() - 1))
                cursor.setPosition(pos)
            return

        # === SS3 应用模式序列：ESC O A/B/C/D/F/H ===
        if seq.startswith('\x1bO') and len(seq) == 3:
            c = seq[2]
            if c == 'A':
                cursor.movePosition(MOVE.Up)
            elif c == 'B':
                cursor.movePosition(MOVE.Down)
            elif c == 'C':
                cursor.movePosition(MOVE.Right)
            elif c == 'D':
                if cursor.position() > cursor.block().position():
                    cursor.movePosition(MOVE.Left)
            elif c in ('F', 'H'):
                cursor.movePosition(MOVE.StartOfLine)
            return

        if not seq.startswith('\x1b['):
            return  # OSC 等不可见序列，忽略

        body = seq[2:-1]
        end_char = seq[-1]
        private = body[:1] in '?<>=!'
        param_str = body[1:] if private else body
        params = [int(p) for p in param_str.split(';') if p.isdigit()]
        count = params[0] if params else 1

        if end_char == 'A':
            cursor.movePosition(MOVE.Up, MODE.MoveAnchor, count)
        elif end_char == 'B':
            cursor.movePosition(MOVE.Down, MODE.MoveAnchor, count)
        elif end_char == 'C':
            cursor.movePosition(MOVE.Right, MODE.MoveAnchor, count)
        elif end_char == 'D':
            # 左移不允许跨出当前文本块（终端中光标不会越过行首）
            block_start = cursor.block().position()
            for _ in range(count):
                if cursor.position() > block_start:
                    cursor.movePosition(MOVE.Left)
        elif end_char == 'E':
            cursor.movePosition(MOVE.Down, MODE.MoveAnchor, count)
            cursor.movePosition(MOVE.StartOfLine)
        elif end_char == 'F':
            cursor.movePosition(MOVE.Up, MODE.MoveAnchor, count)
            cursor.movePosition(MOVE.StartOfLine)
        elif end_char in ('G', 'H', 'f', 'd'):
            # 绝对定位：readline 只在当前输入行上定位列（行号忽略）
            col = params[-1] if params else 1
            cursor.movePosition(MOVE.StartOfLine)
            if col > 1:
                cursor.movePosition(MOVE.Right, MODE.MoveAnchor, col - 1)
        elif end_char == 'J':
            # 清屏：0=光标到文末, 1=文首到光标, 2/3=全屏
            mode = params[0] if params else 0
            if mode == 2 or mode == 3:
                cursor.select(QTextCursor.SelectionType.Document)
                cursor.removeSelectedText()
            elif mode == 1:
                cursor.movePosition(MOVE.Start, MODE.KeepAnchor)
                cursor.removeSelectedText()
            else:
                cursor.movePosition(MOVE.End, MODE.KeepAnchor)
                cursor.removeSelectedText()
        elif end_char == 'K':
            # 清行：0=光标到行尾, 1=行首到光标, 2=整行
            mode = params[0] if params else 0
            if mode == 2:
                cursor.movePosition(MOVE.StartOfLine)
                cursor.movePosition(MOVE.EndOfLine, MODE.KeepAnchor)
                cursor.removeSelectedText()
            elif mode == 1:
                cursor.movePosition(MOVE.StartOfLine, MODE.KeepAnchor)
                cursor.removeSelectedText()
            else:
                cursor.movePosition(MOVE.EndOfLine, MODE.KeepAnchor)
                cursor.removeSelectedText()
        elif end_char == '@':
            # ICH 插入字符位：在光标处腾出 count 个空格（后续字符覆盖填入），
            # 光标保持在插入点不动
            cursor.insertText(' ' * count)
            cursor.movePosition(MOVE.Left, MODE.MoveAnchor, count)
        elif end_char == 'P':
            # DCH 删除字符：删除光标右侧 count 个字符，尾部左移
            cursor.movePosition(MOVE.Right, MODE.KeepAnchor, count)
            cursor.removeSelectedText()
        elif end_char == 'X':
            # ECH 擦除字符：光标右侧 count 个字符替换为空格，光标不动
            start = cursor.position()
            cursor.movePosition(MOVE.Right, MODE.KeepAnchor, count)
            erased = cursor.position() - start
            if erased > 0:
                cursor.insertText(' ' * erased)
                cursor.movePosition(MOVE.Left, MODE.MoveAnchor, erased)
        elif end_char == 's':
            self._saved_cursor_pos = cursor.position()
        elif end_char == 'u':
            if self._saved_cursor_pos is not None:
                pos = max(0, min(self._saved_cursor_pos, cursor.document().characterCount() - 1))
                cursor.setPosition(pos)
        elif end_char in ('h', 'l') and private:
            # 私有模式协商
            if 2004 in params:
                # bracketed paste 模式协商：?2004h 开启 / ?2004l 关闭
                self._bracketed_paste_enabled = (end_char == 'h')
            if 1 in params:
                # DECCKM 应用光标键模式：?1h 开启（方向/Home/End 改发 SS3 形式）
                # / ?1l 关闭（CSI 形式）。vim/less 等全屏程序会开启此模式。
                self._application_cursor_mode = (end_char == 'h')
        # 其余序列（r 滚动区域、L/M 插删行、S/T 滚动、I/Z 制表、
        # g 清制表位、q 光标样式、~ 功能键/粘贴标记、c/n 设备查询等）无显示效果，忽略

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

        # 中断后关闭本次会话日志
        self._close_log_file()

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

    def _flush_output_buffer(self):
        """刷新输出缓冲区，处理不完整的ANSI序列

        设计原则：交互模式下完全依赖服务器端 PTY 回显，本地不做任何回显或消重。
        这与标准终端（xterm/gnome-terminal）行为一致，从根本上消除双显和首字母
        重复问题。本地仅负责将服务器返回的数据按 ANSI 序列完整性刷新到显示区。

        ANSI 序列类型：
        - CSI: \\x1b[ 参数 结尾字母([a-zA-Z@])
        - OSC: \\x1b] ... \\x07 (BEL) 或 \\x1b] ... \\x1b\\\\ (ST)
        - SS3: \\x1bO 单个字母
        - 其他: \\x1b + 单个字符
        """
        if not self._output_buffer:
            return

        # 从左到右扫描，找到最后一个不完整序列的起点
        i = 0
        n = len(self._output_buffer)
        last_complete = 0  # 最后一个完整序列的末尾位置

        while i < n:
            if self._output_buffer[i] == '\x1b':
                # 发现 ESC，尝试解析完整序列
                seq_end = self._parse_ansi_seq(self._output_buffer, i)
                if seq_end > i:
                    # 序列完整，继续扫描
                    i = seq_end
                    last_complete = i
                else:
                    # 序列不完整，需要等待更多数据
                    break
            else:
                i += 1
                last_complete = i

        if last_complete > 0:
            # 输出所有完整的内容
            complete_data = self._output_buffer[:last_complete]
            self._output_buffer = self._output_buffer[last_complete:]
            if complete_data:
                self.write_output(complete_data)
        # 如果 last_complete == 0，说明开头就有不完整序列，等待更多数据

    def _parse_ansi_seq(self, data, start):
        """解析从 start 位置开始的 ANSI 转义序列

        Returns:
            序列结束位置的下一个索引（序列完整时）
            start（序列不完整时，需要等待更多数据）
        """
        n = len(data)
        if start >= n:
            return start

        # 必须以 ESC 开头
        if data[start] != '\x1b':
            return start + 1  # 不是 ESC，跳过

        if start + 1 >= n:
            return start  # 只有单独 ESC，等待后续字符

        c1 = data[start + 1]

        # === CSI 序列: ESC [ 参数(0x30-0x3F)* 中间(0x20-0x2F)* 终止(0x40-0x7E) ===
        if c1 == '[':
            i = start + 2
            # 跳过参数/中间字节（数字、分号、问号、空格、! " # 等）
            while i < n and '\x20' <= data[i] <= '\x3f':
                i += 1
            # 期望一个终止字节（0x40-0x7E，含字母、@、~ 等）
            if i < n and '\x40' <= data[i] <= '\x7e':
                return i + 1  # 序列完整
            return start  # 序列不完整，等待更多数据

        # === OSC 序列: \x1b] ... \x07 (BEL) 或 \x1b] ... \x1b\\ (ST) ===
        if c1 == ']':
            i = start + 2
            while i < n:
                if data[i] == '\x07':  # BEL 结尾
                    return i + 1
                if data[i] == '\x1b' and i + 1 < n and data[i + 1] == '\\':  # ST 结尾
                    return i + 2
                if data[i] == '\x1b':  # 未匹配的 ESC，序列异常
                    return start  # 不完整
                i += 1
            return start  # 序列不完整，等待更多数据

        # === SS3 序列: \x1bO + 单个字母 ===
        if c1 == 'O':
            if start + 2 < n:
                return start + 3  # \x1b + O + 字母
            return start  # 不完整

        # === 其他: \x1b + 单个字符（如 \x1b=, \x1b> 等） ===
        return start + 2

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
                # Ctrl+左方向键：按词左跳（xterm 扩展修饰键序列）
                if modifiers & Qt.KeyboardModifier.ControlModifier:
                    strategy.send_raw("\x1b[1;5D")
                else:
                    strategy.send_raw("\x1b[D")
            return
        elif key == Qt.Key.Key_Right:
            if has_raw:
                # Ctrl+右方向键：按词右跳
                if modifiers & Qt.KeyboardModifier.ControlModifier:
                    strategy.send_raw("\x1b[1;5C")
                else:
                    strategy.send_raw("\x1b[C")
            return

        if key == Qt.Key.Key_Home:
            if has_raw:
                # DECCKM 应用模式（\x1b[?1h，vim/less 等开启）发送 SS3 形式；
                # 普通模式发送 \x1b[1~（Debian/Ubuntu inputrc 与 readline
                # 默认绑定的 Home 键序，PuTTY 等主流终端同样发送此序列）
                if self._application_cursor_mode:
                    strategy.send_raw("\x1bOH")
                else:
                    strategy.send_raw("\x1b[1~")
            return
        elif key == Qt.Key.Key_End:
            if has_raw:
                # End 键：应用模式 SS3 / 普通模式 \x1b[4~（同 Home 的兼容性策略）
                if self._application_cursor_mode:
                    strategy.send_raw("\x1bOF")
                else:
                    strategy.send_raw("\x1b[4~")
            return

        if key == Qt.Key.Key_Insert:
            # Ins 键（xterm 各模式下均发送 \x1b[2~）
            if has_raw:
                strategy.send_raw("\x1b[2~")
            return
        elif key == Qt.Key.Key_PageUp:
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
                # 发送 \r (CR) — PTY 标准回车符，触发服务器执行命令并回显 \r\n
                # 不做本地回显：服务器 PTY 会完整回显命令行+换行，本地回显会导致双显
                strategy.send_raw("\r")
                self.current_input = ""
                if self.ansi_parser.enable_color:
                    self.ansi_parser.reset_format()
            else:
                self.execute_command()
            return

        # 退格 / 删除
        if key == Qt.Key.Key_Backspace:
            if has_raw:
                # 发送 DEL (\x7f) — PTY 标准退格符，服务器负责删除字符并回显退格序列
                # 不做本地退格回显：服务器 PTY 会回显 \b \b，本地回显会导致双重退格
                strategy.send_raw("\x7f")
                if self.current_input:
                    self.current_input = self.current_input[:-1]
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
                # 发送字符到服务器，不做本地回显
                # 服务器 PTY 会回显该字符，通过 poll_remote_output → _flush_output_buffer 显示
                strategy.send_raw(text)
                self.current_input += text
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
            # 交互模式：发送到服务器，由 PTY 回显，不做本地回显
            self.current_input += text
            strategy.send_raw(text)
        else:
            self.current_input += text
            self.write_output(text, self._get_style('text', '#e0e0e0'))

    def exec_button_command(self, btn_name, command):
        """以"模拟手工输入"方式执行按钮命令（交互式 PTY 会话）

        显示效果与真实终端逐字输入完全一致，由服务器 PTY 负责回显：
            demo@test:/$ >>> 执行按钮: <按钮名>
            demo@test:/$ <命令>
            <命令输出>
            demo@test:/$

        关键点：
        - 头信息接在当前提示符行末，不主动换行；换行交给下面空回车的
          \\r\\n 回显完成，避免本地/远端光标状态不同步；
        - 先发空回车（\\r）让远端输出一个新提示符，再发送命令行，
          命令回显才会带提示符前缀；
        - 必须使用 \\r 提交（PTY 规范模式以 CR 作为行结束），
          裸 \\n 在部分 tty 配置下不提交，会导致命令挂起不执行；
        - 支持按钮命令含多行内容，逐行以 \\r 提交。
        """
        strategy = self.connection_context._strategy
        if strategy is None or not hasattr(strategy, 'send_raw'):
            return
        # 1) 头信息追加到当前提示符行（换行由空回车回显产生）
        self.write_output(f">>> 执行按钮: {btn_name}", 'text-info')
        # 2) 空回车：远端回显 \r\n 换行并输出新提示符
        strategy.send_raw("\r")
        # 3) 规范化命令中的换行，逐行以 CR 提交；去掉尾部多余空行
        cmd = (command or '').replace('\r\n', '\n').replace('\r', '\n')
        lines = cmd.split('\n')
        while lines and lines[-1] == '':
            lines.pop()
        for line in lines:
            strategy.send_raw(line + "\r")
        # 4) 重置本地输入追踪与颜色格式，后续由 PTY 回显驱动
        self.current_input = ""
        if self.ansi_parser.enable_color:
            self.ansi_parser.reset_format()

    def handle_paste_text(self, text):
        """处理粘贴的文本（来自 Ctrl+V 或右键菜单粘贴）

        交互模式：
        - 若远程 shell 已协商开启 bracketed paste（收到过 \\x1b[?2004h），
          用 \\x1b[200~ ... \\x1b[201~ 包裹发送：readline 将整块内容作为一次
          插入处理（Tab 不触发补全、换行不立即执行、长内容一次重绘），
          避免长命令只回显后半段、粘贴中途执行等问题；
        - 否则逐行以 \\r 提交（\\r\\n/\\n/U+2028/U+2029 一律先归一化），
          末尾不带换行时最后一行仅注入、留给用户回车确认。
        非交互模式：追加到 current_input，遇到换行符时逐条 execute_command。
"""
        if not self.connection_context.is_connected():
            return
        if not text:
            return

        # 统一换行表示：Windows 剪贴板为 \r\n、旧系统可能为 \r、
        # Qt 文档/其他富文本来源可能使用 U+2028/U+2029 段落分隔符，
        # 不归一化会导致粘贴多行内容时换行不识别（粘成一行或空行错乱）
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = text.replace('\u2028', '\n').replace('\u2029', '\n')

        strategy = self.connection_context._strategy
        has_raw = hasattr(strategy, 'send_raw') and self.interactive_mode

        if has_raw:
            if self._bracketed_paste_enabled:
                # 包裹 bracketed paste 标记，readline 整块插入、不立即执行
                strategy.send_raw('\x1b[200~' + text + '\x1b[201~')
                lines = text.split('\n')
                # 本地输入追踪：取最后一行（等待用户按回车统一执行）
                self.current_input = lines[-1] if lines else ''
            else:
                # 未启用 bracketed paste：每个换行转为一次回车（CR）。
                # PTY 规范模式以 CR 提交行；直接发 \r\n 会造成 CR、LF 各提交
                # 一次（命令拆行/多一个空提示符），裸 \n 在部分 tty 下不提交。
                # 末尾不带换行时，最后一行只注入不回车，留给用户确认执行。
                lines = text.split('\n')
                submit_all = text.endswith('\n')
                if submit_all:
                    # 去掉尾部空行，避免末尾换行多产生一个空命令提示符
                    while lines and lines[-1] == '':
                        lines.pop()
                    payload = ''.join(line + '\r' for line in lines)
                    pending = ''
                else:
                    payload = ''.join(line + '\r' for line in lines[:-1]) + lines[-1]
                    pending = lines[-1]
                strategy.send_raw(payload)
                self.current_input = pending
            if '\n' in text:
                # 多行粘贴后等待远程重绘完成，再从显示区同步输入内容
                self._tab_pending = True
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
        self._bracketed_paste_enabled = False  # 重置bracketed paste标志（新shell会重新协商）
        self._application_cursor_mode = False  # 重置DECCKM应用光标键模式标志（新shell会重新协商）
        self._saved_cursor_pos = None
        # 为本次连接新建日志文件（日志开关开启时）；disconnect() 已先关闭旧文件
        self._open_log_file()

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
                # 默认开启连接保活，避免长时间空闲被 NAT/防火墙超时断开
                if hasattr(strategy, 'enable_keepalive'):
                    try:
                        strategy.enable_keepalive(_KEEPALIVE_INTERVAL)
                    except Exception:
                        pass
                # 连接成功 banner（双方地址、协议、时间等），先于服务器初始输出显示
                self._write_connect_banner(conn_type, config, strategy)
                if initial_output:
                    self.write_output(initial_output)
                # 连接成功后立即根据终端实际宽度调整PTY大小，避免长路径无法显示
                self._last_pty_size = None  # 强制重新测量
                self._update_terminal_size()
                # 布局稳定后再次测量（此时控件宽度才是最终值），
                # 确保PTY列数与控件一致，避免长命令/长粘贴被readline水平滚动截断
                QTimer.singleShot(300, self._update_terminal_size)
                QTimer.singleShot(1500, self._update_terminal_size)
                # 启动输出轮询，使用更短的间隔提高响应速度
                self.output_timer.start(30)  # 30ms间隔，提高响应速度
            else:
                self.interactive_mode = False
                self._write_connect_banner(conn_type, config, strategy)
                self.show_input_line()

            # 连接成功后焦点交给终端输入区（重新连接/复制连接等操作无需再点击）
            self.terminal_display.setFocus()
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

    def _write_connect_banner(self, conn_type, config, strategy):
        """连接成功后输出 banner：连接名称、协议、本地/远程地址、用户、时间、保活状态"""
        bar = '─' * 58
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.write_output(bar + '\n', 'text-hint')
        self.write_output('✔ 连接成功\n', 'text-success')

        name = (self.current_connection or {}).get('name', '')
        if name:
            self.write_output(f'  连接名称 : {name}\n', 'text-info')
        self.write_output(f'  协议类型 : {(conn_type or "").upper() or "-"}\n', 'text-info')

        if conn_type == 'serial':
            self.write_output(
                f'  本地串口 : {config.get("port", "-")} @ {config.get("baud", "-")} bps\n',
                'text-info')
            self.write_output('  对端设备 : 串口设备\n', 'text-info')
        else:
            local, remote = '', ''
            if strategy is not None and hasattr(strategy, 'get_endpoints'):
                try:
                    local, remote = strategy.get_endpoints()
                except Exception:
                    local, remote = '', ''
            host = config.get('host', '')
            port = config.get('port', '')
            if not remote and host:
                remote = f"{host}:{port}"
            self.write_output(f'  本地地址 : {local or "-"}\n', 'text-info')
            self.write_output(f'  远程地址 : {remote or "-"}\n', 'text-info')
            user = config.get('username', '')
            if user:
                self.write_output(f'  登录用户 : {user}\n', 'text-info')

        self.write_output(f'  连接时间 : {now}\n', 'text-info')
        if strategy is not None and hasattr(strategy, 'enable_keepalive'):
            self.write_output(f'  保活     : 已开启（{_KEEPALIVE_INTERVAL} 秒）\n', 'text-hint')
        self.write_output(bar + '\n', 'text-hint')

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
        # 断开后关闭本次会话日志（"已断开连接"已在关闭前写入）
        self._close_log_file()

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
                border-radius: 6px;
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
                border-radius: 6px;
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

        # 终端设置（日志开关、侧边栏可见性、快速连接栏保留的配置）
        self._log_enabled = False
        self._sidebar_visible = True
        self._quick_conn_data = {}
        self._load_terminal_settings()

        self.init_ui()

        # 恢复侧边栏收缩状态
        if not self._sidebar_visible:
            self.toggle_sidebar(False)

    # ========== 终端设置持久化 ==========

    def _load_terminal_settings(self):
        """加载终端设置（日志记录、侧边栏、快速连接栏数据）"""
        if not self._config_manager:
            return
        data = self._config_manager.get_plugin_data('Terminal', 'terminal_settings')
        if not isinstance(data, dict):
            return
        self._log_enabled = bool(data.get('log_enabled', False))
        self._sidebar_visible = bool(data.get('sidebar_visible', True))
        qc = data.get('quick_connect')
        if isinstance(qc, dict):
            self._quick_conn_data = qc

    def _save_terminal_settings(self):
        """持久化终端设置"""
        if not self._config_manager:
            return
        data = {
            'log_enabled': bool(self._log_enabled),
            'sidebar_visible': bool(self._sidebar_visible),
            'quick_connect': self._quick_conn_data,
        }
        self._config_manager.set_plugin_data('Terminal', 'terminal_settings', data)
        self._config_manager.save_plugin_data('Terminal', 'terminal_settings')

    def toggle_logging(self, checked):
        """切换终端内容日志记录（菜单开关）"""
        self._log_enabled = bool(checked)
        self._save_terminal_settings()
        for sess in self.sessions.values():
            tab = sess.get('tab')
            if tab is not None:
                tab.set_logging(self._log_enabled)
        if self._plugin_manager_ref and hasattr(self._plugin_manager_ref, 'set_tool_status'):
            if self._log_enabled:
                status = f"日志记录已开启（{_TERMINAL_LOG_DIR}）"
            else:
                status = "日志记录已关闭"
            self._plugin_manager_ref.set_tool_status('Terminal', status)
    
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

    def _connection_list_qss(self):
        """保存链接列表样式（Tabby 风格：圆角条目，无分割线）

        Returns:
            str: QListWidget 的 QSS
        """
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        text_primary = self._get_style('text', '#ffffff')
        selected_bg, selected_text = self._get_selected_colors()
        font_size_normal = self._get_font_size('size-md', '12px')
        return f"""
            QListWidget {{
                background-color: {bg_main};
                color: {text_primary};
                border: none;
                padding: 2px 0px;
            }}
            QListWidget::item {{
                padding: 4px 8px;
                margin: 1px 4px;
                border-radius: 4px;
                font-size: {font_size_normal};
            }}
            QListWidget::item:selected {{
                background-color: {selected_bg};
                color: {selected_text};
            }}
            QListWidget::item:hover {{
                background-color: {bg_tertiary};
            }}
        """

    def _tab_bar_qss(self):
        """会话标签栏样式（Tabby 风格：圆角浮起标签片，无生硬边框）

        Returns:
            str: QTabWidget/QTabBar 的 QSS
        """
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        font_size_normal = self._get_font_size('size-md', '12px')
        # 选中标签使用更亮的浮起色，与悬停态（bg-input）形成区分
        if self._is_dark_theme():
            tab_sel_bg, tab_sel_text = '#454545', '#ffffff'
        else:
            tab_sel_bg, tab_sel_text = '#f9f9f9', '#1e1e1e'

        return f"""
            QTabWidget::pane {{
                border: none;
                background-color: {bg_main};
            }}
            QTabBar {{
                background: transparent;
            }}
            QTabBar::tab {{
                background-color: {bg_tertiary};
                color: {text_secondary};
                padding: 4px 14px;
                min-width: 64px;
                border: none;
                margin-right: 4px;
                margin-top: 3px;
                margin-bottom: 3px;
                border-radius: 6px;
                font-size: {font_size_normal};
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {tab_sel_bg};
                color: {tab_sel_text};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {bg_input};
                color: {text_primary};
            }}
            QTabBar::tab:closable {{
                margin-left: 5px;
            }}
        """

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

        # 操作按钮行：新建连接、SFTP
        # （重新连接/复制连接已移至会话标签页右键菜单及快捷键）
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

        sidebar_layout.addWidget(self.quick_actions)

        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        bg_main = self._get_style('bg-main', '#1e1e1e')
        border = self._get_style('border', '#3c3c3c')
        # 选中态使用深灰色背景（不使用蓝色），字体颜色与背景有适当对比度
        selected_bg, selected_text = self._get_selected_colors()
        font_size_normal = self._get_font_size('size-md', '12px')

        # 保存链接标题栏：标题 + 收缩侧边栏按钮
        self.sidebar_header = QWidget()
        self.sidebar_header.setStyleSheet(f"background-color: {bg_tertiary};")
        header_layout = QHBoxLayout(self.sidebar_header)
        header_layout.setContentsMargins(8, 4, 4, 4)
        header_layout.setSpacing(4)

        self.saved_links_label = QLabel("保存链接")
        self.saved_links_label.setStyleSheet(f"""
            QLabel {{
                background-color: transparent;
                color: {text_primary};
                padding: 6px 0px;
                font-weight: bold;
                font-size: {font_size};
                border: none;
            }}
        """)
        self.saved_links_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self.saved_links_label)
        header_layout.addStretch()

        # 收缩按钮（«）：点击后隐藏侧边栏，显示左侧窄条恢复按钮
        self.collapse_sidebar_btn = QToolButton()
        self.collapse_sidebar_btn.setText("«")
        self.collapse_sidebar_btn.setFixedSize(24, 24)
        self.collapse_sidebar_btn.setToolTip("收起侧边栏")
        self.collapse_sidebar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_sidebar_btn.clicked.connect(lambda: self.toggle_sidebar(False))
        self.collapse_sidebar_btn.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                color: {text_primary};
                border: none;
                font-size: {font_size};
            }}
            QToolButton:hover {{
                background-color: {bg_input};
                border-radius: 4px;
            }}
        """)
        header_layout.addWidget(self.collapse_sidebar_btn)
        sidebar_layout.addWidget(self.sidebar_header)

        self.connection_list = QListWidget()
        self.connection_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.connection_list.customContextMenuRequested.connect(self.show_connection_menu)
        self.connection_list.doubleClicked.connect(self.on_connection_double_click)
        self.connection_list.setStyleSheet(self._connection_list_qss())
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
        # 允许拖动调整连接选项卡位置（QTabWidget 原生支持）
        self.session_tabs.setMovable(True)
        self.session_tabs.tabCloseRequested.connect(self.close_session)
        self.session_tabs.tabBar().tabMoved.connect(self._on_session_tab_moved)
        self.session_tabs.setStyleSheet(self._tab_bar_qss())
        self.session_tabs.currentChanged.connect(self.on_session_changed)

        # 会话标签页右键菜单：复制连接 / 重新连接 / 断开连接（含快捷键）
        self._init_tab_context_actions()
        self.session_tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_tabs.tabBar().customContextMenuRequested.connect(
            self.show_tab_context_menu)

        right_layout.addWidget(self.session_tabs, 1)

        # 顶部快速连接栏：填好参数一键连接，连接后保留配置方便复用
        self._init_quick_connect_bar(right_layout, unified_btn_css)

        # 底部自定义按钮工具栏（与输出框作为一个整体，宽度对齐）
        self._button_toolbar_visible = True
        self.button_toolbar = TerminalButtonToolbar(self._config_manager, self)
        self.button_toolbar.button_triggered.connect(self._execute_button)
        self._load_button_toolbar_visible()
        right_layout.addWidget(self.button_toolbar, 0)

        # 侧边栏收缩后显示的窄恢复条（默认隐藏）
        self.sidebar_expand_bar = QFrame()
        self.sidebar_expand_bar.setFixedWidth(22)
        self.sidebar_expand_bar.setStyleSheet(f"background-color: {bg_secondary};")
        expand_layout = QVBoxLayout(self.sidebar_expand_bar)
        expand_layout.setContentsMargins(0, 6, 0, 0)
        expand_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.expand_sidebar_btn = QToolButton()
        self.expand_sidebar_btn.setText("»")
        self.expand_sidebar_btn.setFixedSize(20, 24)
        self.expand_sidebar_btn.setToolTip("展开侧边栏")
        self.expand_sidebar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_sidebar_btn.clicked.connect(lambda: self.toggle_sidebar(True))
        self.expand_sidebar_btn.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                color: {text_primary};
                border: none;
                font-size: {font_size};
            }}
            QToolButton:hover {{
                background-color: {bg_input};
                border-radius: 4px;
            }}
        """)
        expand_layout.addWidget(self.expand_sidebar_btn)
        self.sidebar_expand_bar.hide()
        main_layout.addWidget(self.sidebar_expand_bar)

        # Add to splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 0)  # 左侧不随窗口扩展
        self.splitter.setStretchFactor(1, 1)  # 右侧自动扩展
        self.splitter.setSizes([220, 780])  # 初始宽度：侧边栏220，右侧780
        self.splitter.setHandleWidth(4)  # 拖拽手柄宽度
        self.splitter.setChildrenCollapsible(False)  # 防止子组件被折叠
        self._sidebar_saved_width = 220  # 收缩前侧边栏宽度，展开时恢复

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
        
        hint_label = QLabel("通过上方「快速连接」或左侧「新建连接」开始使用")
        hint_label.setStyleSheet(f"""
            QLabel {{
                color: {text_secondary};
                font-size: {font_size_medium};
                margin-top: 10px;
            }}
        """)
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint_label)

        # 快捷键提示面板
        self.welcome_shortcut_panel = self._make_welcome_shortcut_panel()
        empty_layout.addWidget(self.welcome_shortcut_panel, 0, Qt.AlignmentFlag.AlignCenter)

        empty_layout.addStretch()
        
        # 将空白页面添加到标签页（不可关闭）
        self.session_tabs.addTab(self.empty_page, "欢迎")
        self.session_tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

    # 欢迎页快捷键条目（与 Tab 右键菜单/全局快捷键保持一致）
    _WELCOME_SHORTCUTS = [
        ("Ctrl+Shift+D", "复制当前连接"),
        ("Ctrl+Shift+R", "重新连接"),
        ("Ctrl+Shift+K", "断开连接"),
        ("Ctrl+Shift+W", "关闭连接"),
        ("F5", "刷新连接列表"),
    ]

    def _make_welcome_shortcut_panel(self):
        """构建欢迎页快捷键提示面板（样式随主题刷新）"""
        panel = QFrame()
        panel.setObjectName("welcome_shortcut_panel")

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 12, 20, 14)
        lay.setSpacing(8)

        title = QLabel("快捷键提示")
        title.setObjectName("welcome_shortcut_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        content = QLabel()
        content.setObjectName("welcome_shortcut_text")
        content.setTextFormat(Qt.TextFormat.RichText)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        lay.addWidget(content)

        note = QLabel("在会话标签上单击右键，也可调出「复制连接 / 重新连接 / 断开连接 / 关闭连接」菜单")
        note.setObjectName("welcome_shortcut_note")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(note)

        self._style_welcome_shortcut_panel(panel)
        return panel

    def _style_welcome_shortcut_panel(self, panel):
        """按当前主题刷新欢迎页快捷键面板样式"""
        bg = self._get_style('bg-tertiary', '#2d2d30')
        border = self._get_style('border-light', '#5a5a5d')
        primary = self._get_style('primary', '#3a8fd4')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        font_size_md = self._get_font_size('size-md', '12px')

        panel.setStyleSheet(f"""
            QFrame#welcome_shortcut_panel {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            QLabel#welcome_shortcut_title {{
                color: {text_primary};
                font-size: 13px;
                font-weight: bold;
                background: transparent;
            }}
            QLabel#welcome_shortcut_note {{
                color: {text_secondary};
                font-size: {font_size_md};
                background: transparent;
            }}
        """)

        rows = []
        for key, desc in self._WELCOME_SHORTCUTS:
            rows.append(
                "<tr>"
                f"<td style='color:{primary}; font-weight:bold; font-family:Consolas,monospace;' "
                "align='right' nowrap='nowrap'>"
                f"{key}</td>"
                f"<td style='color:{text_secondary}; padding-left:18px;' nowrap='nowrap'>{desc}</td>"
                "</tr>"
            )
        content = panel.findChild(QLabel, "welcome_shortcut_text")
        if content is not None:
            content.setStyleSheet("background: transparent;")
            content.setText(
                "<table cellspacing='0' cellpadding='3'>" + "".join(rows) + "</table>"
            )

    # ========== 快速连接栏 ==========

    def _quick_bar_qss(self):
        """快速连接栏的主题样式（初始化/主题切换时复用）"""
        bg_bar = self._get_style('bg-secondary', '#252526')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        border_light = self._get_style('border-light', '#5a5a5d')
        border_focus = self._get_style('border-focus', '#007acc')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        selection = self._get_style('selection', '#007acc')
        font_size_normal = self._get_font_size('size-md', '12px')
        return f"""
            QWidget#quick_bar {{
                background-color: {bg_bar};
                border-bottom: 1px solid {self._get_style('border', '#3c3c3c')};
            }}
            QLabel#quick_bar_title {{
                color: {text_secondary};
                background: transparent;
                font-size: {font_size_normal};
                font-weight: bold;
            }}
            QLineEdit, QSpinBox, QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 3px 8px;
                border-radius: 6px;
                font-size: {font_size_normal};
                min-height: 22px;
            }}
            QLineEdit:focus, QSpinBox:focus, QComboBox:hover {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox::down-arrow {{ image: url({_DOWN_ARROW_IMG}); }}
            QComboBox QAbstractItemView {{
                background-color: {bg_tertiary};
                color: {text_primary};
                selection-background-color: {selection};
                selection-color: #ffffff;
                border: 1px solid {border_light};
                border-radius: 4px;
            }}
            QPushButton#qc_connect_btn {{
                background-color: {self._get_style('primary', '#3a8fd4')};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 5px 18px;
                font-size: {font_size_normal};
                font-weight: bold;
            }}
            QPushButton#qc_connect_btn:hover {{
                background-color: {self._get_style('primary-hover', '#4a9fe4')};
            }}
            QPushButton#qc_connect_btn:pressed {{
                background-color: {self._get_style('primary-pressed', '#2a7fc4')};
            }}
            QPushButton#qc_key_browse_btn {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                border-radius: 6px;
                font-size: {font_size_normal};
            }}
            QPushButton#qc_key_browse_btn:hover {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
        """

    def _init_quick_connect_bar(self, right_layout, btn_css=None):
        """构建顶部快速连接栏

        网络类型（ssh/telnet）：主机、端口、用户名、密码；
        串口类型：串口号、波特率。连接成功后所有输入均保留，
        并持久化到插件数据，下次启动自动恢复，方便重复连接。
        """
        self.quick_bar = QWidget()
        self.quick_bar.setObjectName("quick_bar")
        bar = QHBoxLayout(self.quick_bar)
        bar.setContentsMargins(8, 4, 8, 4)
        bar.setSpacing(6)

        title = QLabel("快速连接")
        title.setObjectName("quick_bar_title")
        bar.addWidget(title)

        self.qc_type_combo = QComboBox()
        self.qc_type_combo.addItems(["ssh", "telnet", "serial"])
        self.qc_type_combo.setFixedWidth(76)
        self.qc_type_combo.currentTextChanged.connect(self._on_quick_type_changed)
        bar.addWidget(self.qc_type_combo)

        # 网络连接参数页
        net_page = QWidget()
        nl = QHBoxLayout(net_page)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(6)
        self.qc_host_input = QLineEdit()
        self.qc_host_input.setPlaceholderText("主机地址")
        self.qc_host_input.setFixedWidth(195)  # 地址框固定宽度（原弹性宽度收窄约50%）
        nl.addWidget(self.qc_host_input)
        self.qc_port_input = QSpinBox()
        self.qc_port_input.setRange(1, 65535)
        self.qc_port_input.setValue(22)
        self.qc_port_input.setButtonSymbols(
            QSpinBox.ButtonSymbols.NoButtons)  # 不显示增减按钮，仅手动输入
        self.qc_port_input.setFixedWidth(64)   # 无按钮后按5位端口号收窄
        nl.addWidget(self.qc_port_input)
        self.qc_user_input = QLineEdit()
        self.qc_user_input.setPlaceholderText("用户名")
        self.qc_user_input.setFixedWidth(96)
        nl.addWidget(self.qc_user_input)
        self.qc_password_input = QLineEdit()
        self.qc_password_input.setPlaceholderText("密码")
        self.qc_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.qc_password_input.setFixedWidth(96)
        nl.addWidget(self.qc_password_input)
        # SSH 密钥文件选择（输入框 + 浏览按钮），与主机框平分弹性宽度
        self.qc_keyfile_widget = QWidget()
        kl = QHBoxLayout(self.qc_keyfile_widget)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(4)
        self.qc_keyfile_input = QLineEdit()
        self.qc_keyfile_input.setPlaceholderText("密钥文件（与密码任一即可）")
        self.qc_keyfile_input.setMinimumWidth(90)
        kl.addWidget(self.qc_keyfile_input, 1)
        self.qc_key_browse_btn = QPushButton("…")
        self.qc_key_browse_btn.setObjectName("qc_key_browse_btn")
        self.qc_key_browse_btn.setFixedWidth(30)
        self.qc_key_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qc_key_browse_btn.setToolTip("选择密钥文件")
        self.qc_key_browse_btn.clicked.connect(self._browse_quick_key_file)
        kl.addWidget(self.qc_key_browse_btn)
        nl.addWidget(self.qc_keyfile_widget, 1)

        # 串口参数页
        serial_page = QWidget()
        sl = QHBoxLayout(serial_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        self.qc_serial_combo = QComboBox()
        self.qc_serial_combo.setEditable(True)
        self.qc_serial_combo.addItems([f'COM{i}' for i in range(1, 21)])
        self.qc_serial_combo.setMinimumWidth(130)
        sl.addWidget(self.qc_serial_combo, 1)
        sl.addWidget(QLabel("波特率"))
        self.qc_baud_combo = QComboBox()
        self.qc_baud_combo.setEditable(True)
        self.qc_baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.qc_baud_combo.setCurrentText("115200")
        self.qc_baud_combo.setFixedWidth(96)
        sl.addWidget(self.qc_baud_combo)
        sl.addStretch()

        self.qc_stack = QStackedWidget()
        self.qc_stack.addWidget(net_page)
        self.qc_stack.addWidget(serial_page)
        self.qc_stack.setFixedHeight(30)
        bar.addWidget(self.qc_stack, 1)

        self.qc_connect_btn = QPushButton("连接")
        self.qc_connect_btn.setObjectName("qc_connect_btn")
        self.qc_connect_btn.setFixedHeight(28)
        self.qc_connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qc_connect_btn.clicked.connect(self._do_quick_connect)
        bar.addWidget(self.qc_connect_btn)

        self.quick_bar.setFixedHeight(38)  # 固定高度，避免垂直方向抢占会话区空间
        self.quick_bar.setStyleSheet(self._quick_bar_qss())
        # 快速栏位于标签页上方
        right_layout.insertWidget(0, self.quick_bar)

        # 恢复上次保留的快速连接配置（不清空）
        self._restore_quick_conn_data()
        # 仅按当前类型初始化参数页与密钥框可见性（不重置端口，避免覆盖恢复值）
        cur_type = self.qc_type_combo.currentText()
        self.qc_stack.setCurrentIndex(1 if cur_type == "serial" else 0)
        self.qc_keyfile_widget.setVisible(cur_type == "ssh")

    def _on_quick_type_changed(self, conn_type):
        """切换快速连接类型：切换参数页并设置默认端口"""
        if not hasattr(self, 'qc_stack'):
            return
        self.qc_stack.setCurrentIndex(1 if conn_type == "serial" else 0)
        if conn_type == "ssh":
            self.qc_port_input.setValue(22)
        elif conn_type == "telnet":
            self.qc_port_input.setValue(23)
        # 密钥文件仅 SSH 使用
        if hasattr(self, 'qc_keyfile_widget'):
            self.qc_keyfile_widget.setVisible(conn_type == "ssh")

    def _browse_quick_key_file(self):
        """快速连接栏：浏览选择 SSH 密钥文件"""
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择密钥文件",
            self.qc_keyfile_input.text() or "",
            "密钥文件 (*.pem *.key);;所有文件 (*)"
        )
        if file_path:
            self.qc_keyfile_input.setText(file_path)

    def _collect_quick_conn_data(self):
        """收集快速连接栏当前配置（用于持久化，连接后不清理）"""
        return {
            'type': self.qc_type_combo.currentText(),
            'host': self.qc_host_input.text().strip(),
            'port': self.qc_port_input.value(),
            'username': self.qc_user_input.text(),
            'password': self.qc_password_input.text(),
            'key_file': self.qc_keyfile_input.text().strip(),
            'serial_port': self.qc_serial_combo.currentText().strip(),
            'baud': self.qc_baud_combo.currentText().strip(),
        }

    def _restore_quick_conn_data(self):
        """从持久化数据恢复快速连接栏内容"""
        data = self._quick_conn_data
        if not data:
            return
        conn_type = data.get('type', 'ssh')
        if conn_type in ("ssh", "telnet", "serial"):
            self.qc_type_combo.setCurrentText(conn_type)
        self.qc_host_input.setText(data.get('host', ''))
        try:
            port = int(data.get('port', 0))
            if 1 <= port <= 65535:
                self.qc_port_input.setValue(port)
        except (ValueError, TypeError):
            pass
        self.qc_user_input.setText(data.get('username', ''))
        self.qc_password_input.setText(data.get('password', ''))
        self.qc_keyfile_input.setText(data.get('key_file', ''))
        if data.get('serial_port'):
            self.qc_serial_combo.setCurrentText(data['serial_port'])
        if data.get('baud'):
            self.qc_baud_combo.setCurrentText(str(data['baud']))

    def _do_quick_connect(self):
        """使用快速连接栏的配置发起连接（连接后保留配置）"""
        conn_type = self.qc_type_combo.currentText()
        if conn_type == 'serial':
            serial_port = self.qc_serial_combo.currentText().strip()
            if not serial_port:
                QMessageBox.warning(self, "提示", "请填写串口号")
                return
            try:
                baud = int(self.qc_baud_combo.currentText().strip() or '115200')
            except ValueError:
                baud = 115200
            conn = {
                'name': serial_port,
                'type': 'serial',
                'config': {'port': serial_port, 'baud': baud},
            }
        else:
            host = self.qc_host_input.text().strip()
            if not host:
                QMessageBox.warning(self, "提示", "请填写主机地址")
                self.qc_host_input.setFocus()
                return
            password = self.qc_password_input.text()
            key_file = self.qc_keyfile_input.text().strip()
            # SSH：密码与密钥文件任一存在即可
            if conn_type == 'ssh' and not password and not key_file:
                QMessageBox.warning(self, "提示", "请填写密码或选择密钥文件")
                self.qc_password_input.setFocus()
                return
            port = self.qc_port_input.value()
            config = {
                'host': host,
                'port': port,
                'username': self.qc_user_input.text().strip(),
                'password': password,
            }
            if conn_type == 'ssh':
                config['key_file'] = key_file
            conn = {
                'name': host,
                'type': conn_type,
                'config': config,
            }
        # 保留并持久化配置，方便下一次直接连接
        self._quick_conn_data = self._collect_quick_conn_data()
        self._save_terminal_settings()
        self.create_session(conn)

    # ========== 会话标签页右键菜单/快捷键 ==========

    def _init_tab_context_actions(self):
        """创建会话标签页右键菜单动作及全局快捷键

        QAction 仅承载菜单项文本（不在菜单中显示快捷键提示），
        快捷键功能由下方 QShortcut 提供。
        """
        self.act_tab_duplicate = QAction("复制连接", self)
        self.act_tab_duplicate.triggered.connect(self._action_tab_duplicate)

        self.act_tab_reconnect = QAction("重新连接", self)
        self.act_tab_reconnect.triggered.connect(self._action_tab_reconnect)

        self.act_tab_disconnect = QAction("断开连接", self)
        self.act_tab_disconnect.triggered.connect(self._action_tab_disconnect)

        self.act_tab_close = QAction("关闭连接", self)
        self.act_tab_close.triggered.connect(self._action_tab_close)

        # QShortcut 保证动作在终端工具窗口内随时可用（焦点在终端控件中也能触发）
        QShortcut(QKeySequence("Ctrl+Shift+D"), self,
                  context=Qt.ShortcutContext.WindowShortcut,
                  activated=self._action_tab_duplicate)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self,
                  context=Qt.ShortcutContext.WindowShortcut,
                  activated=self._action_tab_reconnect)
        QShortcut(QKeySequence("Ctrl+Shift+K"), self,
                  context=Qt.ShortcutContext.WindowShortcut,
                  activated=self._action_tab_disconnect)
        QShortcut(QKeySequence("Ctrl+Shift+W"), self,
                  context=Qt.ShortcutContext.WindowShortcut,
                  activated=self._action_tab_close)

    def _action_tab_duplicate(self):
        """复制当前会话连接（同配置新建一个会话标签）"""
        session = self.get_current_session()
        if session and session.current_connection:
            self.create_session(session.current_connection)
        else:
            QMessageBox.information(self, "提示", "没有可复制的连接")

    def _action_tab_reconnect(self):
        """使用当前会话的配置重新连接"""
        session = self.get_current_session()
        if session and session.current_connection:
            session.connect_with_config(session.current_connection)
        else:
            QMessageBox.information(self, "提示", "没有可重新连接的会话")

    def _action_tab_disconnect(self):
        """断开当前会话连接"""
        session = self.get_current_session()
        if session and session.connection_context.is_connected():
            session.disconnect()
        else:
            QMessageBox.information(self, "提示", "当前会话未建立连接")

    def _action_tab_close(self):
        """关闭当前会话连接（断开连接并关闭标签页）"""
        session = self.get_current_session()
        if session is None:
            return
        index = self.session_tabs.indexOf(session)
        if index >= 0:
            self.close_session(index)

    def _make_themed_menu(self):
        """创建适配当前主题的右键菜单"""
        menu = QMenu(self)
        if self._config_manager:
            menu.setStyleSheet(self._config_manager.get_menu_css())
        else:
            bg = self._get_style('bg-tertiary', '#2d2d30')
            color = self._get_style('text', '#ffffff')
            border = self._get_style('border-light', '#4a4a4d')
            selected = self._get_style('primary', '#3a8fd4')
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {bg}; color: {color};
                    border: 1px solid {border}; padding: 4px;
                }}
                QMenu::item {{ padding: 6px 24px; min-width: 120px; color: {color}; }}
                QMenu::item:selected {{ background-color: {selected}; color: #ffffff; }}
            """)
        return menu

    def show_tab_context_menu(self, pos):
        """会话标签页右键菜单：复制连接 / 重新连接 / 断开连接 / 关闭连接"""
        bar = self.session_tabs.tabBar()
        index = bar.tabAt(pos)
        if index < 0:
            return
        # 欢迎页不提供会话操作
        if self.session_tabs.widget(index) is getattr(self, 'empty_page', None):
            return
        # 右键先切换到被点击的标签，使后续操作作用于该会话
        self.session_tabs.setCurrentIndex(index)

        session = self.get_current_session()
        has_conn = session is not None and bool(getattr(session, 'current_connection', None))
        connected = session is not None and session.connection_context.is_connected()
        self.act_tab_duplicate.setEnabled(has_conn)
        self.act_tab_reconnect.setEnabled(has_conn)
        self.act_tab_disconnect.setEnabled(connected)
        self.act_tab_close.setEnabled(True)

        menu = self._make_themed_menu()
        menu.addAction(self.act_tab_duplicate)
        menu.addAction(self.act_tab_reconnect)
        menu.addSeparator()
        menu.addAction(self.act_tab_disconnect)
        menu.addAction(self.act_tab_close)
        menu.exec(bar.mapToGlobal(pos))

    # ========== 侧边栏收缩 ==========

    def toggle_sidebar(self, visible):
        """显示/隐藏左侧保存链接侧边栏"""
        if visible:
            self.sidebar.show()
            self.sidebar_expand_bar.hide()
            handle = self.splitter.handle(1)
            if handle is not None:
                handle.show()
            width = self._sidebar_saved_width or 220
            self.splitter.setSizes([width, max(200, self.right_panel.width())])
        else:
            # 先记住当前宽度供展开时恢复
            sizes = self.splitter.sizes()
            if sizes and sizes[0] > 30:
                self._sidebar_saved_width = sizes[0]
            self.sidebar.hide()
            self.sidebar_expand_bar.show()
            handle = self.splitter.handle(1)
            if handle is not None:
                handle.hide()
        self._sidebar_visible = bool(visible)
        self._save_terminal_settings()

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
        # 同步日志记录开关（文件在 connect_with_config 时创建）
        tab.set_logging(getattr(self, '_log_enabled', False))

        # 设置初始字体大小，clamp到>0避免setPointSize(-1)警告
        safe_size = max(1, int(self.current_font_size)) if self.current_font_size and isinstance(self.current_font_size, (int, float)) else 11
        tab.terminal_display.setFont(QFont("Consolas", safe_size))
        
        # 标签只显示名称，没有名称则显示IP
        conn_name = conn.get('name', '')
        if not conn_name:
            conn_name = conn.get('config', {}).get('host', '会话')
        
        index = self.session_tabs.addTab(tab, conn_name)
        self.session_tabs.setCurrentIndex(index)
        # 自动选中新会话并将键盘焦点交给终端输入区，无需再次点击窗口
        tab.terminal_display.setFocus()
        
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

    def _on_session_tab_moved(self, from_index, to_index):
        """连接选项卡拖动重排后的处理

        欢迎页作为固定占位页始终保留在首位：若拖动导致欢迎页离开首位，
        立即将其移回（moveTab 会再次触发本信号，届时欢迎页已在首位而结束）。
        会话与标签的映射基于 widget 引用，位置变化不影响关闭/切换逻辑。
        """
        empty = getattr(self, 'empty_page', None)
        if empty is not None:
            empty_index = self.session_tabs.indexOf(empty)
            if empty_index > 0:
                self.session_tabs.tabBar().moveTab(empty_index, 0)

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
        # 交互式 PTY 会话（SSH/Telnet）的命令型按钮：直接模拟手工输入注入，
        # 保持输出轮询运行，由服务器 PTY 完整回显（提示符 + 命令 + 输出），
        # 显示效果与逐字输入一致；不再经 worker 直读 recv（裸 \n 会导致
        # 命令在部分 tty 下挂起、本地头信息与远端光标不同步）。
        conn_type = (session_tab.current_connection or {}).get('type', '')
        if btn_data.get('type') != 'script' and session_tab.interactive_mode \
                and conn_type in ('ssh', 'telnet'):
            session_tab.exec_button_command(btn_data.get('name', ''),
                                            btn_data.get('command', ''))
            # 执行中态短暂反馈（命令执行结果由终端轮询直接呈现）
            self.button_toolbar.set_button_executing(btn_id, True)
            QTimer.singleShot(
                800, lambda bid=btn_id: self.button_toolbar.set_button_executing(bid, False))
            if self._plugin_manager_ref and hasattr(self._plugin_manager_ref, 'set_tool_status'):
                self._plugin_manager_ref.set_tool_status(
                    'Terminal', f"按钮 {btn_data.get('name', '')}: 已执行")
            return
        # 脚本型 / 串口 / 非交互式：走 worker（直读响应）
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

        # 刷新保存链接标题栏（标题 + 收缩按钮）
        if hasattr(self, 'sidebar_header'):
            self.sidebar_header.setStyleSheet(f"background-color: {bg_tertiary};")
            self.saved_links_label.setStyleSheet(f"""
                QLabel {{
                    background-color: transparent;
                    color: {text_primary};
                    padding: 6px 0px;
                    font-weight: bold;
                    font-size: {font_size};
                    border: none;
                }}
            """)
            self.collapse_sidebar_btn.setStyleSheet(f"""
                QToolButton {{
                    background-color: transparent;
                    color: {text_primary};
                    border: none;
                    font-size: {font_size};
                }}
                QToolButton:hover {{
                    background-color: {bg_input};
                    border-radius: 4px;
                }}
            """)

        # 刷新侧边栏收缩后的恢复窄条
        if hasattr(self, 'sidebar_expand_bar'):
            self.sidebar_expand_bar.setStyleSheet(f"background-color: {bg_secondary};")
            self.expand_sidebar_btn.setStyleSheet(f"""
                QToolButton {{
                    background-color: transparent;
                    color: {text_primary};
                    border: none;
                    font-size: {font_size};
                }}
                QToolButton:hover {{
                    background-color: {bg_input};
                    border-radius: 4px;
                }}
            """)

        # 刷新快速连接栏样式
        if hasattr(self, 'quick_bar'):
            self.quick_bar.setStyleSheet(self._quick_bar_qss())

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
            shortcut_panel = getattr(self, 'welcome_shortcut_panel', None)
            for label in self.empty_page.findChildren(QLabel):
                # 快捷键面板内部标签由面板统一样式管理，跳过通用刷新
                if shortcut_panel is not None and label.parent() is not None \
                        and label.isWidgetType() and shortcut_panel.isAncestorOf(label):
                    continue
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
            # 快捷键面板按新主题整体刷新
            if shortcut_panel is not None:
                self._style_welcome_shortcut_panel(shortcut_panel)

        # 重新应用侧边栏按钮样式
        if hasattr(self, 'new_conn_btn'):
            btn_css = self._get_button_css('button')
            self.new_conn_btn.setStyleSheet(btn_css)
            self.sftp_btn.setStyleSheet(btn_css)

        # 刷新连接列表样式
        if hasattr(self, 'connection_list'):
            self.connection_list.setStyleSheet(self._connection_list_qss())

        # 刷新会话标签页样式
        if hasattr(self, 'session_tabs'):
            self.session_tabs.setStyleSheet(self._tab_bar_qss())

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
        """加载连接列表（默认按连接名称不区分大小写排序）"""
        self.connection_list.clear()
        connections = sorted(
            self.connection_manager.get_connections(),
            key=lambda c: str(c.get('name', '')).lower()
        )

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
