# -*- coding: utf-8 -*-
"""调测工具插件。

提供日志查看界面，支持：
- 日志级别过滤（DEBUG/INFO/WARNING/ERROR/CRITICAL）
- 关键词搜索
- 自动刷新
- 清空显示
- 打开日志目录

日志数据来源：utils.logger.Logger 单例的内存缓冲区。
全局异常捕获和插件加载错误由 main.py 和 PluginManager 写入 Logger。
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QPlainTextEdit,
    QCheckBox, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat
from PyQt6.QtGui import QDesktopServices

from utils.logger import Logger, DEBUG, INFO, WARNING, ERROR, CRITICAL


# 下拉框三角形箭头图片路径（与项目其他模块保持一致）
_DOWN_ARROW_IMG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'assets', 'down_arrow.png'
).replace('\\', '/')


# 各日志级别对应的颜色（深色主题默认值，浅色主题由 refresh_theme_styles 调整）
_LEVEL_COLORS = {
    DEBUG:    '#808080',   # 灰色
    INFO:     '#e0e0e0',   # 默认文字色
    WARNING:  '#d97706',   # 橙色
    ERROR:    '#f44747',   # 红色
    CRITICAL: '#ff0000',   # 亮红色
}

# 所有级别（按严重程度排序）
_ALL_LEVELS = [DEBUG, INFO, WARNING, ERROR, CRITICAL]


class DebugToolPlugin:
    """调测工具插件"""

    def __init__(self, config, config_manager=None, plugin_manager=None):
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None
        self._tab_visible = False  # 默认不显示 tab

    def get_widget(self):
        if self.widget is None:
            self.widget = DebugToolWidget(self.config, self._config_manager, self._plugin_manager)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass

    def register_menus(self, registry):
        """注册菜单项：通过菜单控制调测工具 tab 的显示/隐藏"""
        builder = registry.add_menu(self.name, "调测(&D)")
        builder.add_action(
            "显示调测工具",
            lambda checked: self._toggle_tab_visibility(checked),
            checkable=True,
            checked=self._tab_visible,
        )

    def _toggle_tab_visibility(self, visible):
        """切换调测工具 tab 的显示/隐藏"""
        self._tab_visible = visible
        # 通过 plugin_manager 找到 main_window 并操作 tab
        if self._plugin_manager:
            # plugin_manager 的 status_callback 通常绑定到 main_window
            # 但这里需要直接操作 main_window，通过遍历 widget 的 parent 链
            widget = self.get_widget()
            parent = widget.parent()
            while parent is not None:
                if hasattr(parent, 'plugin_tabs') and hasattr(parent, 'plugin_widgets'):
                    self._update_tab(parent, visible)
                    return
                parent = parent.parent()

    def _update_tab(self, main_window, visible):
        """在 main_window 中添加或移除调测工具 tab"""
        if visible:
            if self.name not in main_window.plugin_widgets:
                widget = self.get_widget()
                main_window.plugin_widgets[self.name] = widget
                # 查找颜色方案
                tab_colors = [
                    {"bg": "#3d2b4a", "border": "#a06bff"},  # 调测工具 - 紫色
                ]
                tab_index = main_window.plugin_tabs.addTab(widget, self.display_name)
                main_window.plugin_tabs.tabBar().setTabData(tab_index, tab_colors[0])
        else:
            if self.name in main_window.plugin_widgets:
                widget = main_window.plugin_widgets[self.name]
                # 找到 tab 索引并移除
                for i in range(main_window.plugin_tabs.count()):
                    if main_window.plugin_tabs.widget(i) is widget:
                        main_window.plugin_tabs.removeTab(i)
                        break
                # 不从 plugin_widgets 中删除，以便下次能再显示


class DebugToolWidget(QWidget):
    """调测工具主组件"""

    def __init__(self, config=None, config_manager=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self._logger = Logger.get_instance()

        # 读取配置
        settings = self.config.get('settings', {})
        self._auto_refresh_interval = settings.get('auto_refresh_interval_ms', 200)
        self._max_display_lines = settings.get('max_display_lines', 2000)

        # 级别过滤状态：默认全选
        self._level_filters = set(_ALL_LEVELS)
        # 上次刷新时的缓冲区条数，用于判断是否需要刷新
        self._last_buffer_count = 0

        self.init_ui()
        self.refresh_theme_styles()

        # 自动刷新定时器
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._refresh_timer.start(self._auto_refresh_interval)

        # 初始加载日志
        self._refresh_logs()

    # ========== 样式接口 ==========
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

    def _get_button_css(self, button_type='button'):
        if self._config_manager:
            return self._config_manager.get_button_css(button_type)
        return """
            QPushButton {
                background-color: #3a8fd4; color: #ffffff; border: none;
                border-radius: 4px; padding: 6px 12px;
                font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #4a9fe4; }
            QPushButton:pressed { background-color: #2a7fc4; }
        """

    def _get_checkbox_style(self):
        text_primary = self._get_style('text', '#ffffff')
        font_size = self._get_font_size('size-md', '12px')
        border_light = self._get_style('border-light', '#4a4a4d')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        primary = self._get_style('primary', '#3a8fd4')
        return f"""
            QCheckBox {{
                color: {text_primary};
                font-size: {font_size};
                spacing: 4px;
            }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {border_light};
                border-radius: 3px;
                background-color: {bg_input};
            }}
            QCheckBox::indicator:checked {{
                background-color: {primary};
                border-color: {primary};
            }}
        """

    def _get_line_edit_style(self):
        bg_input = self._get_style('bg-input', '#3c3c3c')
        text_primary = self._get_style('text', '#ffffff')
        border_light = self._get_style('border-light', '#4a4a4d')
        border_focus = self._get_style('border-focus', '#007acc')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        border_radius = self._get_border_radius('sm', '4px')
        font_size = self._get_font_size('size-md', '12px')
        return f"""
            QLineEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 0px 10px;
                min-height: 28px; height: 28px;
                border-radius: {border_radius};
                font-size: {font_size};
            }}
            QLineEdit:focus {{ border-color: {border_focus}; background-color: {bg_input_focus}; }}
        """

    def _get_plain_text_edit_style(self):
        bg_main = self._get_style('bg-main', '#1e1e1e')
        text_primary = self._get_style('text', '#e0e0e0')
        border = self._get_style('border', '#3c3c3c')
        border_focus = self._get_style('border-focus', '#007acc')
        border_radius = self._get_border_radius('sm', '4px')
        font_size = self._get_font_size('size-md', '12px')
        return f"""
            QPlainTextEdit {{
                background-color: {bg_main};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius};
                font-family: Consolas;
                font-size: {font_size};
                padding: 4px;
            }}
            QPlainTextEdit:focus {{ border-color: {border_focus}; }}
        """

    def _get_label_style(self):
        text = self._get_style('text', '#e0e0e0')
        font_size = self._get_font_size('size-md', '12px')
        return f"color: {text}; font-size: {font_size}; font-weight: 500;"

    def _get_status_bar_style(self):
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        border = self._get_style('border', '#3c3c3c')
        text_primary = self._get_style('text', '#e0e0e0')
        font_size = self._get_font_size('size-sm', '11px')
        return f"""
            QFrame#debug_status_bar {{
                background-color: {bg_tertiary};
                border-top: 1px solid {border};
            }}
            QLabel {{ color: {text_primary}; font-size: {font_size}; }}
        """

    # ========== UI 构建 ==========
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 顶部工具栏
        main_layout.addLayout(self._create_toolbar())

        # 中部日志显示区
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(self._max_display_lines)
        self.log_text.setStyleSheet(self._get_plain_text_edit_style())
        main_layout.addWidget(self.log_text, 1)

        # 底部状态栏
        main_layout.addWidget(self._create_status_bar())

    def _create_toolbar(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 级别过滤复选框
        level_label = QLabel("级别:")
        level_label.setStyleSheet(self._get_label_style())
        layout.addWidget(level_label)

        self.level_checks = {}
        for level in _ALL_LEVELS:
            chk = QCheckBox(level)
            chk.setStyleSheet(self._get_checkbox_style())
            chk.setChecked(True)
            chk.stateChanged.connect(self._on_filter_changed)
            layout.addWidget(chk)
            self.level_checks[level] = chk

        layout.addWidget(self._make_separator())

        # 关键词搜索
        search_label = QLabel("搜索:")
        search_label.setStyleSheet(self._get_label_style())
        layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词过滤...")
        self.search_input.setStyleSheet(self._get_line_edit_style())
        self.search_input.setMinimumWidth(180)
        self.search_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.search_input)

        layout.addStretch()

        # 自动刷新复选框
        self.auto_refresh_chk = QCheckBox("自动刷新")
        self.auto_refresh_chk.setStyleSheet(self._get_checkbox_style())
        self.auto_refresh_chk.setChecked(True)
        self.auto_refresh_chk.toggled.connect(self._on_auto_refresh_toggled)
        layout.addWidget(self.auto_refresh_chk)

        # 清空显示按钮
        self.clear_btn = QPushButton("清空显示")
        self.clear_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.clicked.connect(self._on_clear_display)
        layout.addWidget(self.clear_btn)

        # 打开日志目录按钮
        self.open_dir_btn = QPushButton("打开日志目录")
        self.open_dir_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.open_dir_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_dir_btn.clicked.connect(self._on_open_log_dir)
        layout.addWidget(self.open_dir_btn)

        return layout

    def _make_separator(self):
        """创建垂直分隔线"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet(f"color: {self._get_style('border-light', '#4a4a4d')};")
        return line

    def _create_status_bar(self):
        frame = QFrame()
        frame.setObjectName('debug_status_bar')
        frame.setStyleSheet(self._get_status_bar_style())
        frame.setFixedHeight(26)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(12)

        self.file_path_label = QLabel("日志文件: -")
        self.count_label = QLabel("显示: 0 / 0 条")
        layout.addWidget(self.file_path_label)
        layout.addStretch()
        layout.addWidget(self.count_label)
        return frame

    # ========== 主题刷新 ==========
    def refresh_theme_styles(self):
        """主题切换时刷新所有控件样式"""
        # 复选框
        chk_style = self._get_checkbox_style()
        for chk in self.level_checks.values():
            chk.setStyleSheet(chk_style)
        self.auto_refresh_chk.setStyleSheet(chk_style)

        # 输入框
        self.search_input.setStyleSheet(self._get_line_edit_style())

        # 日志文本框
        self.log_text.setStyleSheet(self._get_plain_text_edit_style())

        # 按钮
        btn_secondary = self._get_button_css('button-secondary')
        self.clear_btn.setStyleSheet(btn_secondary)
        self.open_dir_btn.setStyleSheet(btn_secondary)

        # 标签
        label_style = self._get_label_style()
        for lbl in self.findChildren(QLabel):
            if lbl.parent() is not None and isinstance(lbl.parent(), QFrame) and lbl.parent().objectName() == 'debug_status_bar':
                continue
            lbl.setStyleSheet(label_style)

        # 状态栏
        for frame in self.findChildren(QFrame):
            if frame.objectName() == 'debug_status_bar':
                frame.setStyleSheet(self._get_status_bar_style())

        # 更新级别颜色（浅色主题下调整）
        self._update_level_colors()
        # 重新渲染日志以应用新颜色
        self._refresh_logs()

    def _update_level_colors(self):
        """根据当前主题调整日志级别颜色"""
        is_dark = self._is_dark_theme()
        if is_dark:
            self._level_colors = {
                DEBUG:    self._get_style('text-hint', '#808080'),
                INFO:     self._get_style('text', '#e0e0e0'),
                WARNING:  self._get_style('text-warning', '#d97706'),
                ERROR:    self._get_style('text-danger', '#f44747'),
                CRITICAL: '#ff0000',
            }
        else:
            self._level_colors = {
                DEBUG:    '#888888',
                INFO:     '#333333',
                WARNING:  '#b45309',
                ERROR:    '#dc2626',
                CRITICAL: '#b91c1c',
            }

    def _is_dark_theme(self):
        """判断当前是否为深色主题"""
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

    # ========== 事件处理 ==========
    def _on_filter_changed(self):
        """级别复选框或搜索框变化时刷新日志"""
        self._level_filters = set(
            level for level, chk in self.level_checks.items() if chk.isChecked()
        )
        self._refresh_logs()

    def _on_auto_refresh_toggled(self, checked):
        if checked:
            self._refresh_timer.start(self._auto_refresh_interval)
        else:
            self._refresh_timer.stop()

    def _on_refresh_tick(self):
        """定时刷新回调：仅当缓冲区有新日志时才刷新"""
        current_count = self._logger.get_buffer_count()
        if current_count != self._last_buffer_count:
            self._refresh_logs()

    def _on_clear_display(self):
        """清空显示缓冲区"""
        self._logger.clear_display_buffer()
        self._last_buffer_count = 0
        self.log_text.clear()
        self._update_status(0, 0)

    def _on_open_log_dir(self):
        """打开日志所在目录"""
        log_dir = self._logger.get_log_dir()
        if os.path.exists(log_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))
        else:
            try:
                os.makedirs(log_dir, exist_ok=True)
                QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))
            except Exception:
                pass

    # ========== 日志渲染 ==========
    def _refresh_logs(self):
        """从 Logger 获取日志并渲染到文本框"""
        keyword = self.search_input.text().strip() or None
        entries = self._logger.get_recent_logs(
            level_filter=self._level_filters,
            keyword=keyword,
            limit=self._max_display_lines
        )

        self._last_buffer_count = self._logger.get_buffer_count()

        # 渲染：按级别着色
        self.log_text.clear()
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        for entry in entries:
            color = self._level_colors.get(entry.level, self._level_colors[INFO])
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            cursor.setCharFormat(fmt)
            cursor.insertText(entry.format() + '\n')

        self.log_text.ensureCursorVisible()

        # 更新状态栏
        total = self._logger.get_buffer_count()
        self._update_status(len(entries), total)

    def _update_status(self, shown, total):
        """更新底部状态栏"""
        log_file = self._logger.get_log_file_path()
        self.file_path_label.setText(f"日志文件: {log_file or '-'}")
        self.count_label.setText(f"显示: {shown} / {total} 条")

    # ========== 插件状态上报 ==========
    def report_status(self):
        """向框架状态栏上报当前状态"""
        if self._plugin_manager:
            total = self._logger.get_buffer_count()
            self._plugin_manager.set_tool_status('DebugTool', f"日志缓冲: {total} 条")
