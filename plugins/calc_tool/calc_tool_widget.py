import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QGroupBox, QMessageBox,
    QSplitter, QSizePolicy, QPlainTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QFontMetrics, QTextDocument
import os

# 下拉框三角形箭头图片路径
_DOWN_ARROW_IMG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'assets', 'down_arrow.png'
).replace('\\', '/')


class AutoResizeTextEdit(QPlainTextEdit):
    """支持自动换行和自动加高的多行文本输入框

    - 开启自动换行（WordWrap），内容超出宽度时自动折行显示
    - 内容行数增加时直接扩展控件高度，无滚动条，完整显示所有内容
    - 支持 sync_group 同步：同一组内的控件自动保持相同高度
    - 使用 QTimer 防抖，避免快速输入时频繁计算高度
    - 重用 QTextDocument 实例，避免重复创建开销
    - 提供 text()/setText() 兼容方法，可直接替换 QLineEdit
    """

    height_changed = pyqtSignal()

    def __init__(self, min_height=30, parent=None):
        super().__init__(parent)
        self._min_height = min_height
        self._needed_height = min_height
        self._sync_group = None
        # 组级别同步锁，所有组成员共享同一个标志（首次同步时初始化）
        self._group_sync_active = False

        # 重用的 QTextDocument（避免每次 resize 都重新创建）
        self._layout_doc = QTextDocument()
        self._layout_doc.setDefaultFont(self.font())

        # 防抖定时器：合并快速连续的文本变化
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(30)  # 30ms 防抖
        self._resize_timer.timeout.connect(self._do_auto_resize)

        # 开启自动换行
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # 滚动条始终隐藏，通过扩展高度来显示全部内容
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 大小策略：水平扩展，垂直固定（由内容决定高度）
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # 最小高度
        self.setMinimumHeight(min_height)
        # 去除默认边距，使外观接近 QLineEdit
        self.setContentsMargins(0, 0, 0, 0)

        # 内容变化时触发防抖 resize
        self.textChanged.connect(self._schedule_resize)

    def set_sync_group(self, widgets):
        """设置同步组：当本控件高度变化时，组内所有控件同步为最大高度"""
        self._sync_group = widgets

    def _schedule_resize(self):
        """防抖：延迟执行 resize，合并快速连续的文本变化"""
        self._resize_timer.start()

    def _do_auto_resize(self):
        """实际执行高度计算（由定时器触发，避免频繁调用）"""
        self._auto_resize()

    def _auto_resize(self):
        """根据内容实际显示高度（含自动换行）自动调整控件高度

        使用重用的 QTextDocument 实例计算文本渲染高度。
        组级别同步锁防止递归。
        """
        viewport_width = self.viewport().width()
        if viewport_width <= 0:
            self._needed_height = self._min_height
            return

        text = self.toPlainText()

        # 使用重用的 QTextDocument 计算高度（避免每次都创建新对象）
        self._layout_doc.setPlainText(text)
        self._layout_doc.setTextWidth(viewport_width)
        doc_height = int(self._layout_doc.size().height())
        doc_margin = int(self._layout_doc.documentMargin())
        total_height = doc_height + doc_margin * 2 + 2

        self._needed_height = max(self._min_height, total_height)

        # 只在非同步状态下设置自身高度
        if not self._group_sync_active:
            self.setFixedHeight(self._needed_height)
            self.height_changed.emit()
            # 触发组同步
            if self._sync_group:
                self._sync_group_heights()

    def _sync_group_heights(self):
        """同步组内所有控件高度为最大值（组级别锁防止递归）"""
        if not self._sync_group:
            return
        # 组级别锁：检查所有成员的 _group_sync_active
        if any(getattr(w, '_group_sync_active', False) for w in self._sync_group):
            return
        # 设置所有成员的锁
        for w in self._sync_group:
            w._group_sync_active = True
        try:
            max_h = max(w._needed_height for w in self._sync_group)
            for w in self._sync_group:
                if w.height() != max_h:
                    w.setFixedHeight(max_h)
        finally:
            for w in self._sync_group:
                w._group_sync_active = False

    def text(self):
        """兼容 QLineEdit.text()"""
        return self.toPlainText()

    def setText(self, text):
        """兼容 QLineEdit.setText()，即使信号被阻塞也会调整高度"""
        self.setPlainText(text)
        # 立即计算高度（不等防抖定时器），但不触发同步（由调用方统一处理）
        self._calc_height_only()
        self._sync_group_heights()

    def clear(self):
        """兼容 QLineEdit.clear()，清空后重置高度"""
        super().clear()
        self._calc_height_only()
        self._sync_group_heights()

    def _calc_height_only(self):
        """仅计算所需高度，不设置控件高度也不触发同步（供 setText/clear 内部使用）"""
        viewport_width = self.viewport().width()
        if viewport_width <= 0:
            self._needed_height = self._min_height
            return
        text = self.toPlainText()
        self._layout_doc.setPlainText(text)
        self._layout_doc.setTextWidth(viewport_width)
        doc_height = int(self._layout_doc.size().height())
        doc_margin = int(self._layout_doc.documentMargin())
        self._needed_height = max(self._min_height, doc_height + doc_margin * 2 + 2)

    def resizeEvent(self, event):
        """控件宽度变化时重新计算高度"""
        super().resizeEvent(event)
        # 宽度变化时延迟重算（避免 resize 循环）
        if not self._group_sync_active:
            self._resize_timer.start()


class CalcToolPlugin:
    """计算工具插件 - 提供计算器和数制转换功能"""

    def __init__(self, config, config_manager=None, plugin_manager=None):
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = CalcToolWidget(self.config, self._config_manager, self._plugin_manager)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass


class CalcToolWidget(QWidget):
    """计算工具主组件 - 左侧计算器 + 右侧数值/字符串转换"""

    def __init__(self, config=None, config_manager=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.init_ui()
        # 启用键盘输入：设置焦点策略，使计算工具面板可接收键盘事件
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def get_style(self, key, default=None):
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        return default

    def keyPressEvent(self, event):
        """键盘输入支持：映射键盘按键到计算器操作"""
        # 如果焦点在输入框（如数制转换的输入框）上，不拦截键盘事件
        from PyQt6.QtWidgets import QLineEdit, QComboBox
        focused = self.focusWidget()
        if isinstance(focused, (QLineEdit, QComboBox)):
            super().keyPressEvent(event)
            return

        key = event.key()
        text = event.text()

        # 数字输入 0-9
        if key in (Qt.Key.Key_0, Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3,
                   Qt.Key.Key_4, Qt.Key.Key_5, Qt.Key.Key_6, Qt.Key.Key_7,
                   Qt.Key.Key_8, Qt.Key.Key_9):
            self._on_calc_input(text)
            return

        # 十六进制输入 A-F（程序员模式）
        if self.calc_mode_combo.currentIndex() == 1 and text.upper() in "ABCDEF":
            self._on_calc_input(text.upper())
            return

        # 小数点
        if key == Qt.Key.Key_Period:
            self._on_calc_input('.')
            return

        # 运算符
        if key == Qt.Key.Key_Plus:
            self._on_calc_operator('+')
            return
        if key == Qt.Key.Key_Minus:
            self._on_calc_operator('-')
            return
        if key == Qt.Key.Key_Asterisk:
            self._on_calc_operator('*')
            return
        if key == Qt.Key.Key_Slash:
            self._on_calc_operator('/')
            return
        if key == Qt.Key.Key_Percent:
            self._on_calc_operator('%')
            return

        # 程序员模式位运算符
        if self.calc_mode_combo.currentIndex() == 1:
            if key == Qt.Key.Key_Ampersand:
                self._on_calc_operator('&')
                return
            if key == Qt.Key.Key_Bar:
                self._on_calc_operator('|')
                return
            if key == Qt.Key.Key_AsciiCircum:
                self._on_calc_operator('^')
                return
            if key == Qt.Key.Key_Less:
                self._on_calc_operator('<<')
                return
            if key == Qt.Key.Key_Greater:
                self._on_calc_operator('>>')
                return

        # 等号 / Enter / Return
        if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Equal):
            self._on_calc_equals()
            return

        # Esc 清除
        if key == Qt.Key.Key_Escape:
            self._on_calc_clear()
            return

        # Backspace 退格
        if key == Qt.Key.Key_Backspace:
            self._on_calc_backspace()
            return

        # 其他按键交给父类处理
        super().keyPressEvent(event)

    def get_font_size(self, key, default='12px'):
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        return default

    def get_border_radius(self, key, default='4px'):
        if self._config_manager:
            return self._config_manager.get_border_radius(key, default)
        return default

    def get_button_css(self, button_type='button'):
        if self._config_manager:
            return self._config_manager.get_button_css(button_type)
        return f"""
            QPushButton {{
                background-color: #3a8fd4;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #4a9fe4;
            }}
            QPushButton:pressed {{
                background-color: #2a7fc4;
            }}
        """

    def get_menu_css(self):
        if self._config_manager:
            return self._config_manager.get_menu_css()
        primary = self.get_style('primary', '#007acc')
        bg_tertiary = self.get_style('bg-tertiary', '#2d2d30')
        text_primary = self.get_style('text', '#ffffff')
        border = self.get_style('border-light', '#4a4a4d')
        return f"""
            QMenu {{
                background-color: {bg_tertiary};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 24px;
                min-width: 100px;
                color: {text_primary};
            }}
            QMenu::item:selected {{
                background-color: {primary};
                color: #ffffff;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {border};
                margin: 4px 0;
            }}
        """

    def _get_button_style(self, type='primary'):
        type_map = {
            'primary': 'button',
            'success': 'button',
            'secondary': 'button-secondary',
        }
        button_type = type_map.get(type, 'button')
        return self.get_button_css(button_type)

    def _get_group_box_style(self):
        text_primary = self.get_style('text', '#ffffff')
        border_light = self.get_style('border-light', '#4a4a4d')
        border_radius = self.get_border_radius('lg', '8px')
        bg_secondary = self.get_style('bg-secondary', '#252526')
        font_size = self.get_font_size('size-md', '12px')

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

    def _get_combo_box_style(self):
        bg_input = self.get_style('bg-input', '#3c3c3c')
        text_primary = self.get_style('text', '#ffffff')
        border_light = self.get_style('border-light', '#4a4a4d')
        border_focus = self.get_style('border-focus', '#007acc')
        bg_input_focus = self.get_style('bg-input-focus', '#4c4c4c')
        text_secondary = self.get_style('text-secondary', '#cccccc')
        bg_tertiary = self.get_style('bg-tertiary', '#2d2d30')
        selection = self.get_style('selection', '#007acc')
        selection_text = self.get_style('selection-text', '#ffffff')
        border_radius = self.get_border_radius('sm', '4px')
        font_size = self.get_font_size('size-md', '12px')

        return f"""
            QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 4px 8px;
                min-width: 120px;
                border-radius: {border_radius};
                font-size: {font_size};
            }}
            QComboBox:hover {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
            QComboBox:focus {{
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
                border-radius: {border_radius};
            }}
        """

    def _get_line_edit_style(self, read_only=False):
        bg_input = self.get_style('bg-input', '#3c3c3c')
        text_primary = self.get_style('text', '#ffffff')
        border_light = self.get_style('border-light', '#4a4a4d')
        border_focus = self.get_style('border-focus', '#007acc')
        bg_input_focus = self.get_style('bg-input-focus', '#4c4c4c')
        bg_main = self.get_style('bg-main', '#1e1e1e')
        text_success = self.get_style('text-success', '#00ff00')
        border_radius = self.get_border_radius('sm', '4px')
        font_size = self.get_font_size('size-md', '12px')

        if read_only:
            return f"""
                QLineEdit, QPlainTextEdit {{
                    background-color: {bg_main};
                    color: {text_success};
                    border: 1px solid {border_light};
                    padding: 4px 8px;
                    border-radius: {border_radius};
                    font-size: {font_size};
                    font-family: Consolas;
                }}
            """

        return f"""
            QLineEdit, QPlainTextEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 4px 8px;
                border-radius: {border_radius};
                font-size: {font_size};
            }}
            QLineEdit:focus, QPlainTextEdit:focus {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
        """

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)

        calc_widget = self._create_calculator_panel()
        splitter.addWidget(calc_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(10)

        convert_widget = self._create_number_convert_panel()
        right_layout.addWidget(convert_widget)

        hex_str_widget = self._create_hex_string_panel()
        right_layout.addWidget(hex_str_widget)

        right_layout.addStretch()

        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([300, 600])
        splitter.setChildrenCollapsible(False)

        main_layout.addWidget(splitter)

        # 保存需要刷新样式的控件引用
        self._style_widgets = {
            'calc_mode_combo': self.calc_mode_combo,
            'calc_display': self.calc_display,
            'calc_expression_display': self.calc_expression_display,
            'dec_input': self.dec_input,
            'bin_input': self.bin_input,
            'hex_input': self.hex_input,
            'hex_array_input': self.hex_array_input,
            'string_input': self.string_input,
            'prog_dec_value': self.prog_dec_value,
            'prog_bin_value': self.prog_bin_value,
            'prog_hex_value': self.prog_hex_value,
        }

    def refresh_theme_styles(self):
        """刷新主题样式"""
        if not hasattr(self, '_style_widgets'):
            return
        # 刷新各面板GroupBox样式
        for widget in self.findChildren(QGroupBox):
            widget.setStyleSheet(self._get_group_box_style())
        # 刷新ComboBox
        if 'calc_mode_combo' in self._style_widgets:
            self._style_widgets['calc_mode_combo'].setStyleSheet(self._get_combo_box_style())
        # 刷新LineEdit（普通输入框）
        line_edit_style = self._get_line_edit_style()
        for key in ['dec_input', 'bin_input', 'hex_input', 'hex_array_input', 'string_input']:
            if key in self._style_widgets:
                self._style_widgets[key].setStyleSheet(line_edit_style)
        # 刷新只读LineEdit（程序员模式的结果显示框）
        read_only_style = self._get_line_edit_style(read_only=True)
        for key in ['prog_dec_value', 'prog_bin_value', 'prog_hex_value']:
            if key in self._style_widgets:
                self._style_widgets[key].setStyleSheet(read_only_style)
        # 刷新显示框（使用 transparent 背景，由容器提供背景色）
        if 'calc_display' in self._style_widgets:
            text_primary = self.get_style('text', '#e0e0e0')
            self._style_widgets['calc_display'].setStyleSheet(f"""
                QLineEdit {{
                    background-color: transparent;
                    color: {text_primary};
                    border: none;
                    font-size: 20px;
                    font-weight: bold;
                    font-family: Consolas;
                    padding: 0px;
                }}
            """)
        if 'calc_expression_display' in self._style_widgets:
            text_secondary = self.get_style('text-secondary', '#b0b0b0')
            self._style_widgets['calc_expression_display'].setStyleSheet(f"""
                QLineEdit {{
                    background-color: transparent;
                    color: {text_secondary};
                    border: none;
                    font-size: 11px;
                    font-family: Consolas;
                    padding: 0px;
                }}
            """)
        # 刷新显示框容器背景（使用主题 bg-input 变量）
        bg_input = self.get_style('bg-input', '#454545')
        border_style = self.get_style('border', '#3c3c3c')
        border_radius = self.get_border_radius('md', '6px')
        calc_display = self._style_widgets.get('calc_display')
        if calc_display is not None:
            container = calc_display.parent()
            if container is not None and container is not self:
                container.setStyleSheet(f"""
                    QWidget {{
                        background-color: {bg_input};
                        border: 1px solid {border_style};
                        border-radius: {border_radius};
                    }}
                """)
        # 刷新按钮样式
        btn_css = self.get_button_css('button-calc-number')
        for btn in self.findChildren(QPushButton):
            btn_type = btn.property('button_type')
            if btn_type == 'function':
                btn.setStyleSheet(self.get_button_css('button-calc-function'))
            elif btn_type == 'equals':
                btn.setStyleSheet(self.get_button_css('button-calc-equals'))
            elif btn_type == 'clear':
                btn.setStyleSheet(self.get_button_css('button-calc-clear'))
            else:
                btn.setStyleSheet(btn_css)
        # 刷新所有标签样式（十进制、二进制、十六进制、模式等）
        label_text = self.get_style('text', '#e0e0e0')
        label_font = self.get_font_size('size-md', '12px')
        label_style = f"color: {label_text}; font-size: {label_font}; font-weight: 500;"
        for label in self.findChildren(QLabel):
            label.setStyleSheet(label_style)

    def _create_calculator_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        text_primary = self.get_style('text', '#ffffff')
        font_size = self.get_font_size('size-md', '12px')

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(4)
        mode_label = QLabel("模式:")
        mode_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        mode_label.setFixedWidth(96)
        mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mode_layout.addWidget(mode_label)

        self.calc_mode_combo = QComboBox()
        self.calc_mode_combo.addItems(["标准模式", "程序员模式"])
        self.calc_mode_combo.setStyleSheet(self._get_combo_box_style())
        self.calc_mode_combo.currentIndexChanged.connect(self._on_calc_mode_changed)
        mode_layout.addWidget(self.calc_mode_combo, 1)
        layout.addLayout(mode_layout)

        bg_input = self.get_style('bg-input', '#454545')
        text_primary_color = self.get_style('text', '#e0e0e0')
        text_secondary = self.get_style('text-secondary', '#b0b0b0')
        border_style = self.get_style('border', '#3c3c3c')
        border_radius = self.get_border_radius('md', '6px')

        display_container = QWidget()
        display_container.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_input};
                border: 1px solid {border_style};
                border-radius: {border_radius};
            }}
        """)
        display_layout = QVBoxLayout(display_container)
        display_layout.setContentsMargins(8, 4, 8, 4)
        display_layout.setSpacing(1)

        self.calc_expression_display = QLineEdit()
        self.calc_expression_display.setReadOnly(True)
        self.calc_expression_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.calc_expression_display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.calc_expression_display.setStyleSheet(f"""
            QLineEdit {{
                background-color: transparent;
                color: {text_secondary};
                border: none;
                font-size: 11px;
                font-family: Consolas;
                padding: 0px;
            }}
        """)
        self.calc_expression_display.setFixedHeight(16)
        self.calc_expression_display.setText("")
        display_layout.addWidget(self.calc_expression_display)

        self.calc_display = QLineEdit()
        self.calc_display.setReadOnly(True)
        self.calc_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.calc_display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.calc_display.setStyleSheet(f"""
            QLineEdit {{
                background-color: transparent;
                color: {text_primary_color};
                border: none;
                font-size: 20px;
                font-weight: bold;
                font-family: Consolas;
                padding: 0px;
            }}
        """)
        self.calc_display.setFixedHeight(28)
        self.calc_display.setText("0")
        display_layout.addWidget(self.calc_display)

        layout.addWidget(display_container)

        self.programmer_display = QWidget()
        prog_layout = QFormLayout(self.programmer_display)
        prog_layout.setSpacing(4)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setLabelAlignment(Qt.AlignmentFlag.AlignCenter)

        self.prog_dec_label = QLabel("十进制:")
        self.prog_dec_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size};")
        self.prog_dec_label.setFixedWidth(96)
        self.prog_dec_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prog_dec_value = QLineEdit()
        self.prog_dec_value.setReadOnly(True)
        self.prog_dec_value.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prog_dec_value.setStyleSheet(self._get_line_edit_style(read_only=True))
        prog_layout.addRow(self.prog_dec_label, self.prog_dec_value)

        self.prog_bin_label = QLabel("二进制:")
        self.prog_bin_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size};")
        self.prog_bin_label.setFixedWidth(96)
        self.prog_bin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prog_bin_value = QLineEdit()
        self.prog_bin_value.setReadOnly(True)
        self.prog_bin_value.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prog_bin_value.setStyleSheet(self._get_line_edit_style(read_only=True))
        prog_layout.addRow(self.prog_bin_label, self.prog_bin_value)

        self.prog_hex_label = QLabel("十六进制:")
        self.prog_hex_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size};")
        self.prog_hex_label.setFixedWidth(96)
        self.prog_hex_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prog_hex_value = QLineEdit()
        self.prog_hex_value.setReadOnly(True)
        self.prog_hex_value.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prog_hex_value.setStyleSheet(self._get_line_edit_style(read_only=True))
        prog_layout.addRow(self.prog_hex_label, self.prog_hex_value)

        self.programmer_display.hide()
        layout.addWidget(self.programmer_display)

        self.calc_buttons_widget = QWidget()
        self.calc_buttons_layout = QVBoxLayout(self.calc_buttons_widget)
        self.calc_buttons_layout.setSpacing(3)
        self.calc_buttons_layout.setContentsMargins(0, 0, 0, 0)

        self._init_standard_buttons()
        layout.addWidget(self.calc_buttons_widget)

        layout.addStretch()

        self._calc_reset()

        return panel

    def _init_standard_buttons(self):
        self._clear_buttons()

        num_btn_style = self.get_button_css('button-calc-number')
        fn_btn_style = self.get_button_css('button-calc-function')
        clear_btn_style = self.get_button_css('button-calc-clear')
        equals_btn_style = self.get_button_css('button-calc-equals')

        btn_height = 28

        row1 = QHBoxLayout()
        row1.setSpacing(3)
        btn_pct = self._create_calc_btn("%", fn_btn_style, lambda: self._on_calc_operator("%"), 'function')
        btn_ce = self._create_calc_btn("CE", clear_btn_style, self._on_calc_clear, 'clear')
        btn_c = self._create_calc_btn("C", clear_btn_style, self._on_calc_clear, 'clear')
        btn_back = self._create_calc_btn("⌫", fn_btn_style, self._on_calc_backspace, 'function')
        for btn in [btn_pct, btn_ce, btn_c, btn_back]:
            btn.setFixedHeight(btn_height)
            row1.addWidget(btn)
        self.calc_buttons_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(3)
        btn_recip = self._create_calc_btn("1/x", fn_btn_style, lambda: self._on_calc_reciprocal(), 'function')
        btn_sq = self._create_calc_btn("x²", fn_btn_style, lambda: self._on_calc_square(), 'function')
        btn_sqrt = self._create_calc_btn("√x", fn_btn_style, lambda: self._on_calc_sqrt(), 'function')
        btn_div = self._create_calc_btn("÷", fn_btn_style, lambda: self._on_calc_operator("/"), 'function')
        for btn in [btn_recip, btn_sq, btn_sqrt, btn_div]:
            btn.setFixedHeight(btn_height)
            row2.addWidget(btn)
        self.calc_buttons_layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(3)
        btn_7 = self._create_calc_btn("7", num_btn_style, lambda: self._on_calc_input("7"), 'number')
        btn_8 = self._create_calc_btn("8", num_btn_style, lambda: self._on_calc_input("8"), 'number')
        btn_9 = self._create_calc_btn("9", num_btn_style, lambda: self._on_calc_input("9"), 'number')
        btn_mul = self._create_calc_btn("×", fn_btn_style, lambda: self._on_calc_operator("*"), 'function')
        for btn in [btn_7, btn_8, btn_9, btn_mul]:
            btn.setFixedHeight(btn_height)
            row3.addWidget(btn)
        self.calc_buttons_layout.addLayout(row3)

        row4 = QHBoxLayout()
        row4.setSpacing(3)
        btn_4 = self._create_calc_btn("4", num_btn_style, lambda: self._on_calc_input("4"), 'number')
        btn_5 = self._create_calc_btn("5", num_btn_style, lambda: self._on_calc_input("5"), 'number')
        btn_6 = self._create_calc_btn("6", num_btn_style, lambda: self._on_calc_input("6"), 'number')
        btn_sub = self._create_calc_btn("−", fn_btn_style, lambda: self._on_calc_operator("-"), 'function')
        for btn in [btn_4, btn_5, btn_6, btn_sub]:
            btn.setFixedHeight(btn_height)
            row4.addWidget(btn)
        self.calc_buttons_layout.addLayout(row4)

        row5 = QHBoxLayout()
        row5.setSpacing(3)
        btn_1 = self._create_calc_btn("1", num_btn_style, lambda: self._on_calc_input("1"), 'number')
        btn_2 = self._create_calc_btn("2", num_btn_style, lambda: self._on_calc_input("2"), 'number')
        btn_3 = self._create_calc_btn("3", num_btn_style, lambda: self._on_calc_input("3"), 'number')
        btn_add = self._create_calc_btn("+", fn_btn_style, lambda: self._on_calc_operator("+"), 'function')
        for btn in [btn_1, btn_2, btn_3, btn_add]:
            btn.setFixedHeight(btn_height)
            row5.addWidget(btn)
        self.calc_buttons_layout.addLayout(row5)

        row6 = QHBoxLayout()
        row6.setSpacing(3)
        btn_0 = self._create_calc_btn("0", num_btn_style, lambda: self._on_calc_input("0"), 'number')
        btn_0.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_dot = self._create_calc_btn(".", num_btn_style, lambda: self._on_calc_input("."), 'number')
        btn_eq = self._create_calc_btn("=", equals_btn_style, self._on_calc_equals, 'equals')
        btn_eq.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_0.setFixedHeight(btn_height)
        btn_dot.setFixedHeight(btn_height)
        btn_eq.setFixedHeight(btn_height)
        row6.addWidget(btn_0, 2)
        row6.addWidget(btn_dot, 1)
        row6.addWidget(btn_eq, 2)
        self.calc_buttons_layout.addLayout(row6)

    def _init_programmer_buttons(self):
        self._clear_buttons()

        hex_btn_style = self.get_button_css('button-calc-number')
        func_btn_style = self.get_button_css('button-calc-function')
        clear_btn_style = self.get_button_css('button-calc-clear')
        equals_btn_style = self.get_button_css('button-calc-equals')

        btn_height = 26

        row1 = QHBoxLayout()
        row1.setSpacing(3)
        for text, handler in [("<<", lambda: self._on_calc_operator("<<")),
                               (">>", lambda: self._on_calc_operator(">>")),
                               ("&", lambda: self._on_calc_operator("&")),
                               ("|", lambda: self._on_calc_operator("|")),
                               ("^", lambda: self._on_calc_operator("^")),
                               ("~", self._on_calc_bitwise_not)]:
            btn = self._create_calc_btn(text, func_btn_style, handler)
            btn.setFixedHeight(btn_height)
            row1.addWidget(btn)
        self.calc_buttons_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(3)
        for text, handler, style in [("C", self._on_calc_clear, clear_btn_style),
                                     ("←", self._on_calc_backspace, func_btn_style),
                                     ("%", lambda: self._on_calc_operator("%"), func_btn_style),
                                     ("/", lambda: self._on_calc_operator("/"), func_btn_style)]:
            btn = self._create_calc_btn(text, style, handler)
            btn.setFixedHeight(btn_height)
            row2.addWidget(btn)
        self.calc_buttons_layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(3)
        for text, handler in [("A", lambda: self._on_calc_input("A")),
                               ("B", lambda: self._on_calc_input("B")),
                               ("C", lambda: self._on_calc_input("C")),
                               ("D", lambda: self._on_calc_input("D")),
                               ("E", lambda: self._on_calc_input("E")),
                               ("F", lambda: self._on_calc_input("F"))]:
            btn = self._create_calc_btn(text, hex_btn_style, handler)
            btn.setFixedHeight(btn_height)
            row3.addWidget(btn)
        self.calc_buttons_layout.addLayout(row3)

        row4 = QHBoxLayout()
        row4.setSpacing(3)
        for text, handler, style in [("7", lambda: self._on_calc_input("7"), hex_btn_style),
                                     ("8", lambda: self._on_calc_input("8"), hex_btn_style),
                                     ("9", lambda: self._on_calc_input("9"), hex_btn_style),
                                     ("*", lambda: self._on_calc_operator("*"), func_btn_style),
                                     ("-", lambda: self._on_calc_operator("-"), func_btn_style)]:
            btn = self._create_calc_btn(text, style, handler)
            btn.setFixedHeight(btn_height)
            row4.addWidget(btn)
        self.calc_buttons_layout.addLayout(row4)

        row5 = QHBoxLayout()
        row5.setSpacing(3)
        for text, handler, style in [("4", lambda: self._on_calc_input("4"), hex_btn_style),
                                     ("5", lambda: self._on_calc_input("5"), hex_btn_style),
                                     ("6", lambda: self._on_calc_input("6"), hex_btn_style),
                                     ("+", lambda: self._on_calc_operator("+"), func_btn_style)]:
            btn = self._create_calc_btn(text, style, handler)
            btn.setFixedHeight(btn_height)
            row5.addWidget(btn)
        self.calc_buttons_layout.addLayout(row5)

        row6 = QHBoxLayout()
        row6.setSpacing(3)
        for text, handler, style in [("0", lambda: self._on_calc_input("0"), hex_btn_style),
                                     ("1", lambda: self._on_calc_input("1"), hex_btn_style),
                                     ("2", lambda: self._on_calc_input("2"), hex_btn_style),
                                     ("3", lambda: self._on_calc_input("3"), hex_btn_style),
                                     ("=", self._on_calc_equals, equals_btn_style)]:
            btn = self._create_calc_btn(text, style, handler)
            btn.setFixedHeight(btn_height)
            row6.addWidget(btn)
        self.calc_buttons_layout.addLayout(row6)

    def _clear_buttons(self):
        while self.calc_buttons_layout.count():
            item = self.calc_buttons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _create_calc_btn(self, text, style, handler, button_type=None):
        # 使用 "&&" 转义，避免 Qt 将 "&" 解析为快捷键前缀导致符号不显示
        display_text = text.replace("&", "&&")
        btn = QPushButton(display_text)
        btn.setStyleSheet(style)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(handler)
        # 保存真实文本用于后续判断
        btn.setProperty('real_text', text)
        # 如果未显式指定 button_type，则从 style 字符串中推断
        if button_type is None:
            if 'calc-clear' in style:
                button_type = 'clear'
            elif 'calc-equals' in style:
                button_type = 'equals'
            elif 'calc-function' in style:
                button_type = 'function'
            else:
                button_type = 'number'
        btn.setProperty('button_type', button_type)
        return btn

    def _on_calc_mode_changed(self, index):
        if index == 0:
            self.programmer_display.hide()
            self._init_standard_buttons()
        else:
            self.programmer_display.show()
            self._init_programmer_buttons()
        self._calc_reset()
        # 切换模式后将焦点返回给计算工具面板，使键盘输入保持有效
        self.setFocus()

    def _calc_reset(self):
        self._calc_expression = ""
        self._calc_operand1 = None
        self._calc_operator = None
        self._calc_waiting_for_operand2 = False
        self.calc_display.setText("0")
        self.calc_expression_display.setText("")
        self._update_programmer_display(0)

    def _on_calc_clear(self):
        self._calc_reset()

    def _on_calc_backspace(self):
        current = self.calc_display.text()
        if current and current != "0":
            new_text = current[:-1]
            self.calc_display.setText(new_text if new_text else "0")
            self._update_programmer_display(self._calc_parse_number(self.calc_display.text()))

    def _on_calc_input(self, char):
        if not hasattr(self, '_calc_expression'):
            self._calc_reset()

        current = self.calc_display.text()

        if self.calc_mode_combo.currentIndex() == 1:
            if char not in "0123456789ABCDEF":
                return

        if self._calc_waiting_for_operand2:
            current = ""
            self._calc_waiting_for_operand2 = False

        if char == "." and "." in current:
            return

        if current == "0" and char != ".":
            current = char
        elif current == "0" and char == ".":
            current = "0."
        else:
            current += char

        self.calc_display.setText(current)
        self._update_programmer_display(self._calc_parse_number(current))

    def _on_calc_operator(self, op):
        if not hasattr(self, '_calc_expression'):
            self._calc_reset()

        if self._calc_operator and not self._calc_waiting_for_operand2:
            self._on_calc_equals()

        self._calc_operand1 = self._calc_parse_number(self.calc_display.text())
        self._calc_operator = op
        self._calc_waiting_for_operand2 = True
        self._calc_expression = self.calc_display.text() + " " + op + " "
        self.calc_expression_display.setText(self._calc_expression)

    def _on_calc_equals(self):
        if not hasattr(self, '_calc_expression'):
            return

        if self._calc_operator is None or self._calc_operand1 is None:
            return

        operand2 = self._calc_parse_number(self.calc_display.text())
        op1 = self._calc_operand1
        op2 = operand2
        op = self._calc_operator

        full_expression = f"{self._calc_expression}{self.calc_display.text()} ="

        try:
            if self.calc_mode_combo.currentIndex() == 1:
                op1 = int(op1)
                op2 = int(op2)
                if op == "+":
                    result = op1 + op2
                elif op == "-":
                    result = op1 - op2
                elif op == "*":
                    result = op1 * op2
                elif op == "/":
                    if op2 == 0:
                        self.calc_display.setText("错误: 除零")
                        self.calc_expression_display.setText(full_expression)
                        return
                    result = op1 // op2
                elif op == "%":
                    if op2 == 0:
                        self.calc_display.setText("错误: 除零")
                        self.calc_expression_display.setText(full_expression)
                        return
                    result = op1 % op2
                elif op == "<<":
                    result = op1 << op2
                elif op == ">>":
                    result = op1 >> op2
                elif op == "&":
                    result = op1 & op2
                elif op == "|":
                    result = op1 | op2
                elif op == "^":
                    result = op1 ^ op2
                else:
                    result = op1
            else:
                if op == "+":
                    result = op1 + op2
                elif op == "-":
                    result = op1 - op2
                elif op == "*":
                    result = op1 * op2
                elif op == "/":
                    if op2 == 0:
                        self.calc_display.setText("错误: 除零")
                        self.calc_expression_display.setText(full_expression)
                        return
                    result = op1 / op2
                elif op == "%":
                    result = op1 * op2 / 100
                else:
                    result = op1

            self.calc_expression_display.setText(full_expression)
            self.calc_display.setText(str(result))
            self._calc_operand1 = None
            self._calc_operator = None
            self._calc_waiting_for_operand2 = True
            self._update_programmer_display(result)
        except Exception as e:
            self.calc_expression_display.setText(full_expression)
            self.calc_display.setText(f"错误: {str(e)}")

    def _on_calc_negate(self):
        current = self.calc_display.text()
        if current and current != "0" and not current.startswith("错误"):
            try:
                val = self._calc_parse_number(current)
                if self.calc_mode_combo.currentIndex() == 1:
                    self.calc_display.setText(str(-int(val)))
                    self._update_programmer_display(-int(val))
                else:
                    self.calc_display.setText(str(-val))
                    self._update_programmer_display(-val)
            except (ValueError, TypeError):
                pass

    def _on_calc_reciprocal(self):
        current = self.calc_display.text()
        if not current or current.startswith("错误"):
            return
        try:
            val = self._calc_parse_number(current)
            if val == 0:
                self.calc_expression_display.setText(f"1/({current}) =")
                self.calc_display.setText("错误: 除零")
                return
            result = 1.0 / val
            self.calc_expression_display.setText(f"1/({current}) =")
            self.calc_display.setText(str(result))
            self._update_programmer_display(result)
            self._calc_waiting_for_operand2 = True
        except (ValueError, TypeError):
            pass

    def _on_calc_square(self):
        current = self.calc_display.text()
        if not current or current.startswith("错误"):
            return
        try:
            val = self._calc_parse_number(current)
            if self.calc_mode_combo.currentIndex() == 1:
                result = int(val) ** 2
            else:
                result = val ** 2
            self.calc_expression_display.setText(f"sqr({current}) =")
            self.calc_display.setText(str(result))
            self._update_programmer_display(result)
            self._calc_waiting_for_operand2 = True
        except (ValueError, TypeError):
            pass

    def _on_calc_sqrt(self):
        current = self.calc_display.text()
        if not current or current.startswith("错误"):
            return
        try:
            val = self._calc_parse_number(current)
            if val < 0:
                self.calc_expression_display.setText(f"√({current}) =")
                self.calc_display.setText("错误: 负数不能开方")
                return
            result = val ** 0.5
            if self.calc_mode_combo.currentIndex() == 1:
                result = int(result)
            self.calc_expression_display.setText(f"√({current}) =")
            self.calc_display.setText(str(result))
            self._update_programmer_display(result)
            self._calc_waiting_for_operand2 = True
        except (ValueError, TypeError):
            pass

    def _on_calc_bitwise_not(self):
        current = self.calc_display.text()
        try:
            val = self._calc_parse_number(current)
            result = ~int(val)
            self.calc_display.setText(str(result))
            self._update_programmer_display(result)
            self._calc_waiting_for_operand2 = True
        except (ValueError, TypeError):
            pass

    def _calc_parse_number(self, text):
        try:
            if self.calc_mode_combo.currentIndex() == 1:
                text = text.strip()
                if text.startswith("0x"):
                    return int(text, 16)
                elif any(c in text.upper() for c in "ABCDEF"):
                    return int(text, 16)
                else:
                    return int(text)
            else:
                if "." in text:
                    return float(text)
                else:
                    return int(text)
        except ValueError:
            return 0

    def _update_programmer_display(self, value):
        if self.calc_mode_combo.currentIndex() == 1 and self.programmer_display.isVisible():
            try:
                int_val = int(value)
                self.prog_dec_value.setText(str(int_val))
                self.prog_bin_value.setText("0b" + bin(int_val)[2:])
                self.prog_hex_value.setText("0x" + hex(int_val).upper()[2:])
            except (ValueError, OverflowError):
                self.prog_dec_value.setText(str(value))
                self.prog_bin_value.setText("错误")
                self.prog_hex_value.setText("错误")

    def _create_number_convert_panel(self):
        group = QGroupBox("数制转换 (十进制/二进制/十六进制)")
        group.setStyleSheet(self._get_group_box_style())
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        text_primary = self.get_style('text', '#ffffff')
        font_size = self.get_font_size('size-md', '12px')
        input_min_height = 30

        result_layout = QFormLayout()
        result_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        result_layout.setSpacing(8)
        result_layout.setContentsMargins(0, 0, 0, 0)

        dec_label = QLabel("十进制:")
        dec_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        dec_label.setFixedWidth(96)
        dec_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dec_input = AutoResizeTextEdit(min_height=input_min_height)
        self.dec_input.setPlaceholderText("输入十进制数值...")
        self.dec_input.setStyleSheet(self._get_line_edit_style())
        self.dec_input.textChanged.connect(self.on_dec_input_changed)
        result_layout.addRow(dec_label, self.dec_input)

        bin_label = QLabel("二进制:")
        bin_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        bin_label.setFixedWidth(96)
        bin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bin_input = AutoResizeTextEdit(min_height=input_min_height)
        self.bin_input.setPlaceholderText("输入二进制 (如: 0b1010)")
        self.bin_input.setStyleSheet(self._get_line_edit_style())
        self.bin_input.textChanged.connect(self.on_bin_input_changed)
        result_layout.addRow(bin_label, self.bin_input)

        hex_label = QLabel("十六进制:")
        hex_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        hex_label.setFixedWidth(96)
        hex_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hex_input = AutoResizeTextEdit(min_height=input_min_height)
        self.hex_input.setPlaceholderText("输入十六进制 (如: 0xFF)")
        self.hex_input.setStyleSheet(self._get_line_edit_style())
        self.hex_input.textChanged.connect(self.on_hex_input_changed)
        result_layout.addRow(hex_label, self.hex_input)

        # 设置同步组：dec/bin/hex 三个输入框保持相同高度
        number_convert_group = [self.dec_input, self.bin_input, self.hex_input]
        for w in number_convert_group:
            w.set_sync_group(number_convert_group)

        layout.addLayout(result_layout)
        return group

    def _create_hex_string_panel(self):
        group = QGroupBox("十六进制数组与字符串转换")
        group.setStyleSheet(self._get_group_box_style())
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        text_primary = self.get_style('text', '#ffffff')
        font_size = self.get_font_size('size-md', '12px')
        input_min_height = 30

        hex_row = QHBoxLayout()
        hex_row.setSpacing(8)
        hex_label = QLabel("十六进制数组:")
        hex_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        hex_label.setFixedWidth(96)
        hex_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hex_row.addWidget(hex_label)

        self.hex_array_input = AutoResizeTextEdit(min_height=input_min_height)
        self.hex_array_input.setPlaceholderText("如: 0x48 0x65 0x6C 0x6C 0x6F")
        self.hex_array_input.setStyleSheet(self._get_line_edit_style())
        self.hex_array_input.textChanged.connect(self.on_hex_array_input_changed)
        hex_row.addWidget(self.hex_array_input)
        layout.addLayout(hex_row)

        str_row = QHBoxLayout()
        str_row.setSpacing(8)
        str_label = QLabel("字符串:")
        str_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        str_label.setFixedWidth(96)
        str_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        str_row.addWidget(str_label)

        self.string_input = AutoResizeTextEdit(min_height=input_min_height)
        self.string_input.setPlaceholderText("输入字符串...")
        self.string_input.setStyleSheet(self._get_line_edit_style())
        self.string_input.textChanged.connect(self.on_string_input_changed)
        str_row.addWidget(self.string_input)
        layout.addLayout(str_row)

        # 设置同步组：hex_array/string 两个输入框保持相同高度
        hex_string_group = [self.hex_array_input, self.string_input]
        for w in hex_string_group:
            w.set_sync_group(hex_string_group)

        return group

    def _is_updating(self):
        return getattr(self, '_updating_conversion', False)

    def _set_updating(self, value):
        self._updating_conversion = value

    def on_dec_input_changed(self):
        if self._is_updating():
            return

        input_val = self.dec_input.text().strip()

        if not input_val:
            self.bin_input.blockSignals(True)
            self.hex_input.blockSignals(True)
            self.bin_input.clear()
            self.hex_input.clear()
            self.bin_input.blockSignals(False)
            self.hex_input.blockSignals(False)
            return

        try:
            num = int(input_val, 10)
            self._set_updating(True)
            self.bin_input.blockSignals(True)
            self.hex_input.blockSignals(True)
            self.bin_input.setText("0b" + bin(num)[2:])
            self.hex_input.setText("0x" + hex(num).upper()[2:])
            self.bin_input.blockSignals(False)
            self.hex_input.blockSignals(False)
            self._set_updating(False)
        except ValueError:
            self._set_updating(True)
            self.bin_input.blockSignals(True)
            self.hex_input.blockSignals(True)
            self.bin_input.clear()
            self.hex_input.clear()
            self.bin_input.blockSignals(False)
            self.hex_input.blockSignals(False)
            self._set_updating(False)

    def on_bin_input_changed(self):
        if self._is_updating():
            return

        input_val = self.bin_input.text().strip().lower()

        if not input_val:
            self.dec_input.blockSignals(True)
            self.hex_input.blockSignals(True)
            self.dec_input.clear()
            self.hex_input.clear()
            self.dec_input.blockSignals(False)
            self.hex_input.blockSignals(False)
            return

        try:
            val = input_val.replace("0b", "")
            num = int(val, 2)
            self._set_updating(True)
            self.dec_input.blockSignals(True)
            self.hex_input.blockSignals(True)
            self.dec_input.setText(str(num))
            self.hex_input.setText("0x" + hex(num).upper()[2:])
            self.dec_input.blockSignals(False)
            self.hex_input.blockSignals(False)
            self._set_updating(False)
        except ValueError:
            self._set_updating(True)
            self.dec_input.blockSignals(True)
            self.hex_input.blockSignals(True)
            self.dec_input.clear()
            self.hex_input.clear()
            self.dec_input.blockSignals(False)
            self.hex_input.blockSignals(False)
            self._set_updating(False)

    def on_hex_input_changed(self):
        if self._is_updating():
            return

        input_val = self.hex_input.text().strip().lower()

        if not input_val:
            self.dec_input.blockSignals(True)
            self.bin_input.blockSignals(True)
            self.dec_input.clear()
            self.bin_input.clear()
            self.dec_input.blockSignals(False)
            self.bin_input.blockSignals(False)
            return

        try:
            val = input_val.replace("0x", "")
            num = int(val, 16)
            self._set_updating(True)
            self.dec_input.blockSignals(True)
            self.bin_input.blockSignals(True)
            self.dec_input.setText(str(num))
            self.bin_input.setText("0b" + bin(num)[2:])
            self.dec_input.blockSignals(False)
            self.bin_input.blockSignals(False)
            self._set_updating(False)
        except ValueError:
            self._set_updating(True)
            self.dec_input.blockSignals(True)
            self.bin_input.blockSignals(True)
            self.dec_input.clear()
            self.bin_input.clear()
            self.dec_input.blockSignals(False)
            self.bin_input.blockSignals(False)
            self._set_updating(False)

    def on_hex_array_input_changed(self):
        if getattr(self, '_hex_str_updating', False):
            return

        hex_input = self.hex_array_input.text().strip()

        if not hex_input:
            self.string_input.blockSignals(True)
            self.string_input.clear()
            self.string_input.blockSignals(False)
            return

        try:
            hex_values = hex_input.replace(",", " ").split()
            bytes_data = []
            for val in hex_values:
                val = val.lower().replace("0x", "")
                bytes_data.append(int(val, 16))

            result = bytes(bytes_data).decode('utf-8', errors='replace')
            self._hex_str_updating = True
            self.string_input.blockSignals(True)
            self.string_input.setText(result)
            self.string_input.blockSignals(False)
            self._hex_str_updating = False
        except ValueError:
            self._hex_str_updating = True
            self.string_input.blockSignals(True)
            self.string_input.clear()
            self.string_input.blockSignals(False)
            self._hex_str_updating = False

    def on_string_input_changed(self):
        if getattr(self, '_hex_str_updating', False):
            return

        str_input = self.string_input.text()

        if not str_input:
            self.hex_array_input.blockSignals(True)
            self.hex_array_input.clear()
            self.hex_array_input.blockSignals(False)
            return

        try:
            hex_array = ' '.join(f"0x{byte:02X}" for byte in str_input.encode('utf-8'))
            self._hex_str_updating = True
            self.hex_array_input.blockSignals(True)
            self.hex_array_input.setText(hex_array)
            self.hex_array_input.blockSignals(False)
            self._hex_str_updating = False
        except Exception:
            self._hex_str_updating = True
            self.hex_array_input.blockSignals(True)
            self.hex_array_input.clear()
            self.hex_array_input.blockSignals(False)
            self._hex_str_updating = False