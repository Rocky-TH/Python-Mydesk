import os
import re
import threading
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QPlainTextEdit, QComboBox,
    QGroupBox,
    QTextEdit, QTreeView, QHeaderView,
    QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QFont, QAction, QStandardItemModel, QStandardItem, QColor, QTextCursor,
    QKeySequence, QShortcut
)

from plugins.script_runner import ScriptRunner
from utils import dialog_helper
from utils.ansi_parser import ANSIParser


SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'scripts')


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
        # 复用终端侧 ANSI 解析器，保证脚本输出区与终端输出区颜色表现一致
        self._ansi_parser = ANSIParser(
            enable_color=True,
            default_foreground=QColor(self._get_style('text', '#e0e0e0')),
            is_dark=self._is_dark_theme()
        )
        self._script_threads = []
        self._current_file_path = None
        
        self.output_updated.connect(self._append_output)
        self.button_enabled.connect(self._set_button_enabled)
        
        self._ensure_scripts_dir()
        self.init_ui()

        # Ctrl+S 保存当前脚本（仅在本插件内生效）
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self.on_save_script)
    
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
    
    def _is_dark_theme(self):
        """根据背景色亮度判断是否为深色主题（与终端 ANSI 配色判断保持一致）"""
        bg_hex = self._get_style('bg-main', '#1e1e1e').lstrip('#')
        try:
            r = int(bg_hex[0:2], 16)
            g = int(bg_hex[2:4], 16)
            b = int(bg_hex[4:6], 16)
        except ValueError:
            return True
        return (r * 299 + g * 587 + b * 114) / 1000 < 128

    def _get_font_size(self, key, default='12px'):
        """获取字体大小"""
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        return default

    def _get_border_radius(self, key, default='4px'):
        """获取边框圆角"""
        if self._config_manager:
            return self._config_manager.get_border_radius(key, default)
        return default

    def _get_label_width(self, key='md', default=96):
        """获取标签固定宽度令牌（像素整数）"""
        if self._config_manager:
            return self._config_manager.get_label_width(key, default)
        return default

    def _get_button_css(self, button_type='button'):
        """获取统一按钮 CSS 样式（蓝色背景+白色字体+加粗）"""
        if self._config_manager:
            return self._config_manager.get_button_css(button_type)
        primary = self._get_style('primary', '#3a8fd4')
        primary_hover = self._get_style('primary-hover', '#4a9fe4')
        primary_pressed = self._get_style('primary-pressed', '#2a7fc4')
        return f"""
            QPushButton {{
                background-color: {primary};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {primary_pressed};
            }}
        """
    
    def _get_combo_box_css(self):
        """获取统一下拉框 CSS（含随主题变化的箭头，初始化与刷新共用）"""
        bg_input = self._get_style('bg-input', '#454545')
        text_primary = self._get_style('text', '#e0e0e0')
        border = self._get_style('border', '#3c3c3c')
        arrow_css = self._config_manager.get_combo_arrow_css() if self._config_manager else ''
        return f"""
            QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border};
                padding: 6px 10px;
                border-radius: {self._get_border_radius('sm', '4px')};
            }}
            {arrow_css}
        """
    
    def _get_menu_css(self):
        """获取统一菜单 CSS 样式（悬停/选中时字体为白色）"""
        if self._config_manager:
            return self._config_manager.get_menu_css()
        bg = self._get_style('bg-tertiary', '#2d2d30')
        color = self._get_style('text', '#e0e0e0')
        border = self._get_style('border', '#3c3c3c')
        primary = self._get_style('primary', '#3a8fd4')
        separator_bg = self._get_style('border', '#3c3c3c')
        return f"""
            QMenu {{
                background-color: {bg};
                color: {color};
                border: 1px solid {border};
                border-radius: {self._get_border_radius('md', '6px')};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 24px;
                min-width: 100px;
                color: {color};
            }}
            QMenu::item:selected {{
                background-color: {primary};
                color: #ffffff;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {separator_bg};
                margin: 4px 0;
            }}
        """

    def _get_group_box_style(self):
        """获取统一 QGroupBox 样式（标题颜色随主题变化）"""
        text_primary = self._get_style('text', '#e0e0e0')
        border_light = self._get_style('border-light', '#4a4a4a')
        border_radius = self._get_border_radius('lg', '8px')
        bg_secondary = self._get_style('bg-secondary', '#252526')
        font_size = self._get_font_size('size-md', '12px')

        return f"""
            QGroupBox {{
                color: {text_primary};
                font-weight: bold;
                font-size: {font_size};
                border: 1px solid {border_light};
                border-radius: {border_radius};
                margin-top: 8px;
                padding-top: 10px;
                background-color: {bg_secondary};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: {text_primary};
                background-color: {bg_secondary};
            }}
        """

    def _get_remote_cmd_plugin(self):
        """获取RemoteCmd插件"""
        if not self._remote_cmd_plugin and self._plugin_manager:
            self._remote_cmd_plugin = self._plugin_manager.get_plugin("RemoteCmd")
        return self._remote_cmd_plugin
    
    def _append_output(self, text):
        """线程安全的输出追加，复用终端 ANSI 解析器渲染颜色"""
        if not text:
            return

        # 统一换行符；\r 行内刷新只保留每行最后一个 \r 之后的内容
        text = text.replace('\r\n', '\n')
        if '\r' in text:
            text = '\n'.join(line.rsplit('\r', 1)[-1] for line in text.split('\n'))

        self._ansi_parser.reset_format()
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.setCharFormat(self._ansi_parser.get_current_format())

        # 与 appendPlainText 行为保持一致：每次追加独占行
        # 注意：QTextDocument 中段落分隔符为 U+2029，toPlainText 时才显示为 \n
        if cursor.position() > 0 and \
                cursor.document().characterAt(cursor.position() - 1) not in ('\n', '\u2029'):
            cursor.insertText('\n')

        for part_text, part_format in self._ansi_parser.parse_text(text):
            if part_text:
                # 解析后清除残余 C0 控制字符，制表符按 4 空格展开（与终端一致）
                part_text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', part_text)
                part_text = part_text.replace('\t', '    ')
                if not part_text:
                    continue
                cursor.setCharFormat(part_format)
                cursor.insertText(part_text)

        # 复位解析器状态，避免颜色格式泄漏到后续系统提示行
        self._ansi_parser.reset_format()
        if not text.endswith('\n'):
            cursor.setCharFormat(self._ansi_parser.get_current_format())
            cursor.insertText('\n')

        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()
    
    def _set_button_enabled(self, enabled):
        """线程安全的按钮状态设置（禁用时展示忙碌文案，防止重复点击）"""
        self.run_btn.setEnabled(enabled)
        self.run_btn.setText("运行脚本" if enabled else "运行中...")
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        left_panel = self._create_left_panel()
        layout.addWidget(left_panel, 1)

        right_panel = self._create_right_panel()
        layout.addWidget(right_panel, 3)

    def refresh_theme_styles(self):
        """刷新主题样式（主题切换时由框架调用）"""
        # 更新缓存的颜色方案，确保使用最新主题颜色
        self._color_scheme = self._get_color_scheme()
        text_primary = self._get_style('text', '#e0e0e0')
        text_hint = self._get_style('text-hint', '#858585')
        text_secondary = self._get_style('text-secondary', '#b0b0b0')
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        border = self._get_style('border', '#3c3c3c')
        selection = self._get_style('selection', '#264f78')
        selection_text = self._get_style('selection-text', '#ffffff')
        font_size = self._get_font_size('size-md', '12px')

        # 刷新所有 QGroupBox
        group_box_style = self._get_group_box_style()
        for gb in self.findChildren(QGroupBox):
            gb.setStyleSheet(group_box_style)

        # 刷新文件树
        if hasattr(self, 'file_tree'):
            self.file_tree.setStyleSheet(f"""
                QTreeView {{
                    background-color: {bg_main};
                    color: {text_primary};
                    border: 1px solid {border};
                    border-radius: {self._get_border_radius('sm', '4px')};
                }}
                QTreeView::item {{
                    padding: 6px;
                }}
                QTreeView::item:selected {{
                    background-color: {selection};
                    color: {selection_text};
                }}
                QTreeView::item:hover {{
                    background-color: {bg_tertiary};
                }}
            """)

        # 刷新脚本编辑器
        if hasattr(self, 'script_editor'):
            self.script_editor.setStyleSheet(f"""
                QPlainTextEdit {{
                    background-color: {bg_main};
                    color: {text_primary};
                    border: 1px solid {border};
                    border-radius: {self._get_border_radius('sm', '4px')};
                    padding: 8px;
                    font-family: Consolas;
                }}
            """)

        # 刷新输出区域
        if hasattr(self, 'output_text'):
            self.output_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {bg_main};
                    color: {text_primary};
                    border: 1px solid {border};
                    border-radius: {self._get_border_radius('sm', '4px')};
                    padding: 8px;
                    font-family: Consolas;
                }}
            """)
            # 同步 ANSI 解析器的默认前景色与主题配色
            self._ansi_parser.default_foreground = QColor(text_primary)
            self._ansi_parser.set_theme_mode(self._is_dark_theme())
            self._ansi_parser.reset_format()

        # 刷新下拉框
        if hasattr(self, 'env_combo'):
            self.env_combo.setStyleSheet(self._get_combo_box_css())

        # 刷新所有标准标签（文件、描述、脚本列表等）
        label_style = f"color: {text_primary}; font-size: {font_size}; font-weight: 500;"
        for label in self.findChildren(QLabel):
            label.setStyleSheet(label_style)
        # 特殊标签单独覆盖
        if hasattr(self, 'script_name_label'):
            self.script_name_label.setStyleSheet(
                f"color: {text_primary}; font-size: {self._get_font_size('size-xxl', '16px')}; font-weight: bold;")
        if hasattr(self, 'script_desc_label'):
            self.script_desc_label.setStyleSheet(f"color: {text_hint}; font-size: {font_size};")

        # 刷新按钮（按控件引用刷新，保留删除按钮的危险色语义）
        for btn in self.findChildren(QPushButton):
            if btn is getattr(self, 'delete_btn', None):
                btn.setStyleSheet(self._get_button_css('button-danger'))
            else:
                btn.setStyleSheet(self._get_button_css('button'))
    
    def _create_left_panel(self):
        """创建左侧面板（文件树）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        primary = self._get_style('primary', '#3a8fd4')
        primary_hover = self._get_style('primary-hover', '#4a9fe4')
        bg_input = self._get_style('bg-input', '#454545')
        bg_input_focus = self._get_style('bg-input-focus', '#3a5878')
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        border = self._get_style('border', '#3c3c3c')
        text_primary = self._get_style('text', '#e0e0e0')
        selection = self._get_style('selection', '#264f78')
        selection_text = self._get_style('selection-text', '#ffffff')
        
        header_layout = QHBoxLayout()
        title = QLabel("脚本文件")
        title.setStyleSheet(
            f"color: {text_primary}; font-weight: bold; "
            f"font-size: {self._get_font_size('size-xl', '14px')};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        add_btn = QPushButton("新建")
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(self._get_button_css('button'))
        add_btn.clicked.connect(self.on_add_script)
        header_layout.addWidget(add_btn)
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedHeight(28)
        refresh_btn.setStyleSheet(self._get_button_css('button'))
        refresh_btn.clicked.connect(self._refresh_file_tree)
        header_layout.addWidget(refresh_btn)
        
        layout.addLayout(header_layout)
        
        self.file_model = QStandardItemModel()
        self.file_model.setHorizontalHeaderLabels(["名称"])
        
        self.file_tree = QTreeView()
        self.file_tree.setModel(self.file_model)
        self.file_tree.setHeaderHidden(True)
        self._populate_file_tree()
        self.file_tree.setStyleSheet(f"""
            QTreeView {{
                background-color: {bg_main};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {self._get_border_radius('sm', '4px')};
            }}
            QTreeView::item {{
                padding: 6px;
            }}
            QTreeView::item:selected {{
                background-color: {selection};
                color: {selection_text};
            }}
            QTreeView::item:hover {{
                background-color: {bg_tertiary};
            }}
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
        
        # 获取主题颜色
        primary = self._get_style('primary', '#3a8fd4')
        primary_hover = self._get_style('primary-hover', '#4a9fe4')
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_input_focus = self._get_style('bg-input-focus', '#3a5878')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        border = self._get_style('border', '#3c3c3c')
        border_light = self._get_style('border-light', '#4a4a4a')
        text_primary = self._get_style('text', '#e0e0e0')
        text_secondary = self._get_style('text-secondary', '#b0b0b0')
        text_hint = self._get_style('text-hint', '#858585')
        success = self._get_style('success', '#4ec9b0')
        success_hover = self._get_style('success-hover', '#5dd4bb')
        danger = self._get_style('danger', '#f44747')
        danger_hover = self._get_style('danger-hover', '#f65a5a')
        
        info_group = QGroupBox("脚本信息")
        info_group.setStyleSheet(self._get_group_box_style())
        info_layout = QFormLayout(info_group)
        info_layout.setLabelAlignment(Qt.AlignmentFlag.AlignCenter)

        font_size = self._get_font_size('size-md', '12px')
        label_style = f"color: {text_primary}; font-size: {font_size};"

        self.script_name_label = QLabel("未选择")
        self.script_name_label.setStyleSheet(
            f"color: {text_primary}; font-size: {self._get_font_size('size-xxl', '16px')}; font-weight: bold;")
        self.script_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_label = QLabel("文件:")
        file_label.setStyleSheet(label_style)
        file_label.setFixedWidth(self._get_label_width('md', 96))
        file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addRow(file_label, self.script_name_label)

        self.script_desc_label = QLabel("")
        self.script_desc_label.setStyleSheet(f"color: {text_hint}; font-size: {font_size};")
        self.script_desc_label.setWordWrap(True)
        self.script_desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label = QLabel("描述:")
        desc_label.setStyleSheet(label_style)
        desc_label.setFixedWidth(self._get_label_width('md', 96))
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addRow(desc_label, self.script_desc_label)

        layout.addWidget(info_group)

        editor_group = QGroupBox("脚本内容")
        editor_group.setStyleSheet(self._get_group_box_style())
        editor_layout = QVBoxLayout(editor_group)
        
        self.script_editor = QPlainTextEdit()
        self.script_editor.setFont(QFont("Consolas", 11))
        self.script_editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {bg_main};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {self._get_border_radius('sm', '4px')};
                padding: 8px;
                font-family: Consolas;
            }}
        """)
        editor_layout.addWidget(self.script_editor)
        
        layout.addWidget(editor_group)
        
        env_group = QGroupBox("运行环境")
        env_group.setStyleSheet(self._get_group_box_style())
        env_layout = QHBoxLayout(env_group)
        
        self.env_combo = QComboBox()
        self.env_combo.setStyleSheet(self._get_combo_box_css())
        self._load_environments()
        env_layout.addWidget(self.env_combo, 1)
        
        layout.addWidget(env_group)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(36)
        
        self.run_btn = QPushButton("运行脚本")
        self.run_btn.setFixedHeight(36)
        self.run_btn.setStyleSheet(self._get_button_css('button'))
        self.run_btn.clicked.connect(self.on_run_script)
        btn_layout.addWidget(self.run_btn)
        
        self.validate_btn = QPushButton("验证语法")
        self.validate_btn.setFixedHeight(36)
        self.validate_btn.setStyleSheet(self._get_button_css('button'))
        self.validate_btn.clicked.connect(self.on_validate_script)
        btn_layout.addWidget(self.validate_btn)
        
        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedHeight(36)
        self.save_btn.setStyleSheet(self._get_button_css('button'))
        self.save_btn.clicked.connect(self.on_save_script)
        btn_layout.addWidget(self.save_btn)
        
        self.delete_btn = QPushButton("删除")
        self.delete_btn.setFixedHeight(36)
        self.delete_btn.setStyleSheet(self._get_button_css('button-danger'))
        self.delete_btn.clicked.connect(self.on_delete_script)
        btn_layout.addWidget(self.delete_btn)
        
        layout.addLayout(btn_layout)
        
        output_group = QGroupBox("执行输出")
        output_group.setStyleSheet(self._get_group_box_style())
        output_layout = QVBoxLayout(output_group)
        
        # 使用 QTextEdit 以支持按字符着色（QPlainTextEdit 不支持富文本格式）
        self.output_text = QTextEdit()
        self.output_text.setFont(QFont("Consolas", 10))
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {bg_main};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {self._get_border_radius('sm', '4px')};
                padding: 8px;
                font-family: Consolas;
            }}
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
        menu.setStyleSheet(self._get_menu_css())
        
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
            plugin_config = self._config_manager.get_plugin_config("CompileTool")
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
                self._append_output(f"[错误] 读取文件失败: {e}")
    
    def on_add_script(self):
        """新建脚本文件"""
        name = dialog_helper.get_text(
            self, "新建脚本", "脚本文件名（不含.py后缀）:", config_manager=self._config_manager,
            placeholder="例如：check_status"
        )
        if name is None or not name.strip():
            return
        
        name = name.strip()
        if not name.endswith('.py'):
            name += '.py'
        
        file_path = os.path.join(SCRIPTS_DIR, name)
        
        if os.path.exists(file_path):
            self._append_output(f"[新建] 文件已存在: {name}")
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
            self._append_output(f"[新建] 脚本文件已创建: {name}")
            
            # 刷新并选中新创建的文件
            self._refresh_file_tree()
            self._select_file_in_tree(file_path)
        except Exception as e:
            self._append_output(f"[错误] 创建文件失败: {e}")
    
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
            self._append_output("[验证] 脚本内容为空")
            return
        
        result = ScriptRunner.validate(script_content)
        if result['valid']:
            self._append_output("[验证] 语法正确 ✓")
        else:
            self._append_output(f"[验证] 语法错误: {result['error']}")
            if result['line']:
                self._append_output(f"  位置: 第{result['line']}行")
    
    def on_run_script(self):
        """运行脚本"""
        script_content = self.script_editor.toPlainText()
        if not script_content.strip():
            self._append_output("[执行] 脚本内容为空")
            return
        
        env_data = self.env_combo.currentData()
        if not env_data:
            self._append_output("[执行] 请选择运行环境")
            return
        
        env_name = env_data.get('name', '')
        file_name = os.path.basename(self._current_file_path) if self._current_file_path else "未命名"
        self._append_output(f"[执行] 开始执行脚本: {file_name}")
        self._append_output(f"[执行] 运行环境: {env_name}")
        self.run_btn.setEnabled(False)
        
        remote_cmd = self._get_remote_cmd_plugin()
        if not remote_cmd:
            self._append_output("[错误] 无法获取RemoteCmd插件")
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
            self._append_output("[保存] 请先选择要保存的文件")
            return
        
        try:
            content = self.script_editor.toPlainText()
            with open(self._current_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._append_output(f"[保存] 文件已保存 ✓")
        except Exception as e:
            self._append_output(f"[错误] 保存文件失败: {e}")
    
    def on_delete_script(self):
        """删除脚本文件"""
        if not self._current_file_path:
            self._append_output("[删除] 请先选择要删除的文件")
            return
        
        file_name = os.path.basename(self._current_file_path)
        confirmed = dialog_helper.confirm(
            self, '确认删除',
            f"确定要删除脚本文件 \"{file_name}\" 吗？",
            self._config_manager,
            confirm_text='删除', danger=True
        )
        
        if confirmed:
            try:
                os.remove(self._current_file_path)
                self._append_output(f"[删除] 文件已删除: {file_name}")
                self._current_file_path = None
                self.script_name_label.setText("未选择")
                self.script_desc_label.setText("")
                self.script_editor.clear()
                self._refresh_file_tree()
            except Exception as e:
                self._append_output(f"[错误] 删除文件失败: {e}")
