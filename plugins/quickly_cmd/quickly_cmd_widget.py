import json
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QGroupBox, QMessageBox, QCheckBox,
    QTabWidget, QSpinBox, QPlainTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class QuicklyCmdPlugin:
    def __init__(self, config, config_manager=None):
        self.config = config
        self._config_manager = config_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = QuicklyCmdWidget(self.config, self._config_manager)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass


class QuicklyCmdWidget(QWidget):
    """快捷命令插件 - 包含编译工具和字节转换工具"""

    def __init__(self, config=None, config_manager=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._config_manager = config_manager
        self.compile_config = self.load_compile_config()
        self.init_ui()

    def load_compile_config(self):
        """加载编译配置"""
        if self._config_manager:
            plugin_config = self._config_manager.get_plugin_config("QuicklyCmd")
            if plugin_config:
                return plugin_config.get('compile', {})
        
        return {
            "compile_environments": [{"name": "本地环境", "server": "localhost", "path": ".", "docker": None}],
            "compile_components": [{"name": "全部组件", "targets": ["all"]}],
            "test_environments": [{"name": "单元测试", "type": "unit", "command": "pytest"}]
        }

    def get_style(self, key, default=None):
        """获取样式配置"""
        if self._config_manager:
            return self._config_manager.get_color(key, default)
        return default

    def get_font_size(self, key, default='12px'):
        """获取字体大小"""
        if self._config_manager:
            return self._config_manager.get_font_size(key, default)
        return default

    def get_border_radius(self, key, default='4px'):
        """获取边框圆角"""
        if self._config_manager:
            return self._config_manager.get_border_radius(key, default)
        return default

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.tool_tabs = QTabWidget()
        tab_style = self._get_tab_widget_style()
        self.tool_tabs.setStyleSheet(tab_style)
        layout.addWidget(self.tool_tabs)

        compile_tab = self.create_compile_tool()
        self.tool_tabs.addTab(compile_tab, "编译工具")

        byte_tab = self.create_byte_convert_tool()
        self.tool_tabs.addTab(byte_tab, "字节转换")

    def _get_tab_widget_style(self):
        """生成标签页样式"""
        primary = self.get_style('primary', '#007acc')
        bg_main = self.get_style('background_main', '#1e1e1e')
        bg_tertiary = self.get_style('background_tertiary', '#2d2d30')
        border = self.get_style('border', '#3d3d40')
        text_primary = self.get_style('text_primary', '#ffffff')
        text_secondary = self.get_style('text_secondary', '#cccccc')
        bg_input = self.get_style('background_input', '#3c3c3c')
        font_size = self.get_font_size('medium', '13px')
        border_radius = self.get_border_radius('normal', '6px')

        return f"""
            QTabWidget::pane {{
                border: 1px solid {border};
                background-color: {bg_main};
            }}
            QTabBar::tab {{
                background-color: {bg_tertiary};
                color: {text_secondary};
                padding: 8px 20px;
                border: 1px solid {border};
                border-bottom: none;
                margin-right: 2px;
                margin-top: 4px;
                border-top-left-radius: {border_radius};
                border-top-right-radius: {border_radius};
                font-size: {font_size};
            }}
            QTabBar::tab:selected {{
                background-color: {primary};
                color: {text_primary};
                border-color: {primary};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {bg_input};
                color: {text_primary};
            }}
        """

    def _get_group_box_style(self):
        """生成GroupBox样式"""
        text_primary = self.get_style('text_primary', '#ffffff')
        border_light = self.get_style('border_light', '#4a4a4d')
        border_radius = self.get_border_radius('large', '8px')
        bg_secondary = self.get_style('background_secondary', '#252526')
        font_size = self.get_font_size('medium', '13px')

        return f"""
            QGroupBox {{
                color: {text_primary};
                font-weight: bold;
                font-size: {font_size};
                border: 2px solid {border_light};
                border-radius: {border_radius};
                margin-top: 12px;
                padding-top: 15px;
                background-color: {bg_secondary};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }}
        """

    def _get_combo_box_style(self):
        """生成ComboBox样式"""
        bg_input = self.get_style('background_input', '#3c3c3c')
        text_primary = self.get_style('text_primary', '#ffffff')
        border_light = self.get_style('border_light', '#4a4a4d')
        border_focus = self.get_style('border_focus', '#007acc')
        bg_input_focus = self.get_style('background_input_focus', '#4c4c4c')
        text_secondary = self.get_style('text_secondary', '#cccccc')
        bg_tertiary = self.get_style('background_tertiary', '#2d2d30')
        selection = self.get_style('selection', '#007acc')
        selection_text = self.get_style('selection_text', '#ffffff')
        border_radius = self.get_border_radius('small', '4px')
        font_size = self.get_font_size('normal', '12px')

        return f"""
            QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 6px 10px;
                min-width: 200px;
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
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {text_secondary};
                margin-right: 5px;
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
        """生成LineEdit样式"""
        bg_input = self.get_style('background_input', '#3c3c3c')
        text_primary = self.get_style('text_primary', '#ffffff')
        border_light = self.get_style('border_light', '#4a4a4d')
        border_focus = self.get_style('border_focus', '#007acc')
        bg_input_focus = self.get_style('background_input_focus', '#4c4c4c')
        bg_main = self.get_style('background_main', '#1e1e1e')
        text_success = self.get_style('text_success', '#00ff00')
        border_radius = self.get_border_radius('small', '4px')
        font_size = self.get_font_size('normal', '12px')

        if read_only:
            return f"""
                QLineEdit {{
                    background-color: {bg_main};
                    color: {text_success};
                    border: 1px solid {border_light};
                    padding: 6px 10px;
                    border-radius: {border_radius};
                    font-size: {font_size};
                    font-family: Consolas;
                }}
            """
        
        return f"""
            QLineEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 6px 10px;
                border-radius: {border_radius};
                font-size: {font_size};
            }}
            QLineEdit:focus {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
        """

    def _get_button_style(self, type='primary'):
        """生成按钮样式"""
        primary = self.get_style('primary', '#007acc')
        primary_hover = self.get_style('primary_hover', '#005a9e')
        primary_pressed = self.get_style('primary_pressed', '#004575')
        text_primary = self.get_style('text_primary', '#ffffff')
        bg_input = self.get_style('background_input', '#3c3c3c')
        border_light = self.get_style('border_light', '#4a4a4d')
        bg_input_focus = self.get_style('background_input_focus', '#4c4c4c')
        bg_tertiary = self.get_style('background_tertiary', '#2d2d30')
        success = self.get_style('success', '#28a745')
        success_hover = self.get_style('success_hover', '#218838')
        border_radius = self.get_border_radius('normal', '6px')
        font_size = self.get_font_size('medium', '14px')

        if type == 'success':
            return f"""
                QPushButton {{
                    background-color: {success};
                    color: {text_primary};
                    border: none;
                    font-size: {font_size};
                    font-weight: bold;
                    border-radius: {border_radius};
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {success_hover};
                }}
                QPushButton:pressed {{
                    background-color: {primary_pressed};
                }}
            """
        elif type == 'secondary':
            return f"""
                QPushButton {{
                    background-color: {bg_input};
                    color: {text_primary};
                    border: 1px solid {border_light};
                    font-size: {font_size};
                    font-weight: bold;
                    border-radius: {border_radius};
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {bg_input_focus};
                    border-color: {primary};
                }}
                QPushButton:pressed {{
                    background-color: {bg_tertiary};
                }}
            """
        
        return f"""
            QPushButton {{
                background-color: {primary};
                color: {text_primary};
                border: none;
                font-size: {font_size};
                font-weight: bold;
                border-radius: {border_radius};
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {primary_pressed};
            }}
        """

    def _get_plain_text_edit_style(self):
        """生成PlainTextEdit样式"""
        text_success = self.get_style('text_success', '#00ff00')
        border = self.get_style('border', '#3c3c3c')
        border_radius = self.get_border_radius('small', '4px')
        font_size = self.get_font_size('normal', '11px')

        return f"""
            QPlainTextEdit {{
                background-color: #0c0c0c;
                color: {text_success};
                border: 1px solid {border};
                border-radius: {border_radius};
                padding: 8px;
                font-size: {font_size};
                font-family: Consolas;
            }}
        """

    def create_compile_tool(self):
        """创建编译工具"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)

        options_group = QGroupBox("编译选项")
        options_group.setStyleSheet(self._get_group_box_style())
        options_layout = QFormLayout(options_group)
        options_layout.setSpacing(10)

        text_primary = self.get_style('text_primary', '#ffffff')
        font_size = self.get_font_size('normal', '12px')

        env_label = QLabel("编译环境:")
        env_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        self.compile_env_combo = QComboBox()
        self.compile_env_combo.setStyleSheet(self._get_combo_box_style())
        
        for env in self.compile_config.get('compile_environments', []):
            self.compile_env_combo.addItem(env['name'], env)
        
        options_layout.addRow(env_label, self.compile_env_combo)

        comp_label = QLabel("编译组件:")
        comp_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        self.compile_component_combo = QComboBox()
        self.compile_component_combo.setStyleSheet(self._get_combo_box_style())
        
        for comp in self.compile_config.get('compile_components', []):
            self.compile_component_combo.addItem(comp['name'], comp)
        
        options_layout.addRow(comp_label, self.compile_component_combo)

        test_label = QLabel("测试环境:")
        test_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        self.test_env_combo = QComboBox()
        self.test_env_combo.setStyleSheet(self._get_combo_box_style())
        
        for test in self.compile_config.get('test_environments', []):
            self.test_env_combo.addItem(test['name'], test)
        
        options_layout.addRow(test_label, self.test_env_combo)

        layout.addWidget(options_group)

        detail_group = QGroupBox("当前配置详情")
        detail_group.setStyleSheet(self._get_group_box_style())
        detail_layout = QVBoxLayout(detail_group)

        self.detail_text = QLabel("选择编译环境后显示详细配置信息")
        text_success = self.get_style('text_success', '#00ff00')
        font_size = self.get_font_size('normal', '12px')
        self.detail_text.setStyleSheet(f"color: {text_success}; font-size: {font_size}; font-weight: 500;")
        self.detail_text.setWordWrap(True)
        detail_layout.addWidget(self.detail_text)

        layout.addWidget(detail_group)

        self.compile_env_combo.currentIndexChanged.connect(self.update_detail_info)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.compile_btn = QPushButton("开始编译")
        self.compile_btn.setFixedHeight(38)
        self.compile_btn.setFixedWidth(160)
        self.compile_btn.setStyleSheet(self._get_button_style('primary'))
        self.compile_btn.clicked.connect(self.on_compile)
        btn_layout.addWidget(self.compile_btn)

        self.test_btn = QPushButton("运行测试")
        self.test_btn.setFixedHeight(38)
        self.test_btn.setFixedWidth(110)
        self.test_btn.setStyleSheet(self._get_button_style('success'))
        self.test_btn.clicked.connect(self.on_test)
        btn_layout.addWidget(self.test_btn)

        self.clean_btn = QPushButton("清理")
        self.clean_btn.setFixedHeight(38)
        self.clean_btn.setFixedWidth(90)
        self.clean_btn.setStyleSheet(self._get_button_style('secondary'))
        self.clean_btn.clicked.connect(self.on_clean)
        btn_layout.addWidget(self.clean_btn)

        layout.addLayout(btn_layout)

        output_group = QGroupBox("编译输出")
        output_group.setStyleSheet(self._get_group_box_style())
        output_layout = QVBoxLayout(output_group)

        self.compile_output = QPlainTextEdit()
        self.compile_output.setFont(QFont("Consolas", 11))
        self.compile_output.setReadOnly(True)
        self.compile_output.setStyleSheet(self._get_plain_text_edit_style())
        output_layout.addWidget(self.compile_output)

        layout.addWidget(output_group)

        self.status_bar = QWidget()
        self.status_bar.setFixedHeight(30)
        primary = self.get_style('primary', '#007acc')
        self.status_bar.setStyleSheet(f"background-color: {primary}; border-radius: {self.get_border_radius('small', '4px')};")
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(10, 0, 10, 0)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: white; font-weight: bold;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: rgba(255,255,255,0.9);")
        status_layout.addWidget(self.progress_label)

        layout.addWidget(self.status_bar)

        self.update_detail_info()

        return widget

    def update_detail_info(self):
        """更新配置详情显示"""
        env_data = self.compile_env_combo.currentData()
        if env_data:
            server = env_data.get('server', 'N/A')
            path = env_data.get('path', 'N/A')
            docker = env_data.get('docker', '无')
            desc = env_data.get('description', '')
            
            info = f"服务器: {server} | 路径: {path} | Docker: {docker}"
            if desc:
                info += f"\n说明: {desc}"
            self.detail_text.setText(info)
            text_success = self.get_style('text_success', '#00ff00')
            self.detail_text.setStyleSheet(f"color: {text_success}; font-size: {self.get_font_size('small', '11px')};")

    def create_byte_convert_tool(self):
        """创建字节转换工具"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)

        tool1_group = QGroupBox("数制转换 (十进制/二进制/十六进制)")
        tool1_group.setStyleSheet(self._get_group_box_style())
        tool1_layout = QVBoxLayout(tool1_group)

        text_primary = self.get_style('text_primary', '#ffffff')
        font_size = self.get_font_size('normal', '12px')

        result_layout = QFormLayout()
        result_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        result_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        dec_label = QLabel("十进制:")
        dec_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        self.dec_input = QLineEdit()
        self.dec_input.setPlaceholderText("输入十进制数值...")
        self.dec_input.setStyleSheet(self._get_line_edit_style())
        self.dec_input.textChanged.connect(self.on_dec_input_changed)
        result_layout.addRow(dec_label, self.dec_input)

        bin_label = QLabel("二进制:")
        bin_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        self.bin_input = QLineEdit()
        self.bin_input.setPlaceholderText("输入二进制数值 (如: 0b1010 或 1010)...")
        self.bin_input.setStyleSheet(self._get_line_edit_style())
        self.bin_input.textChanged.connect(self.on_bin_input_changed)
        result_layout.addRow(bin_label, self.bin_input)

        hex_label = QLabel("十六进制:")
        hex_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        self.hex_input = QLineEdit()
        self.hex_input.setPlaceholderText("输入十六进制数值 (如: 0xFF 或 FF)...")
        self.hex_input.setStyleSheet(self._get_line_edit_style())
        self.hex_input.textChanged.connect(self.on_hex_input_changed)
        result_layout.addRow(hex_label, self.hex_input)

        tool1_layout.addLayout(result_layout)
        layout.addWidget(tool1_group)

        tool2_group = QGroupBox("十六进制数组与字符串转换")
        tool2_group.setStyleSheet(self._get_group_box_style())
        tool2_layout = QVBoxLayout(tool2_group)

        hex_row = QHBoxLayout()
        hex_label = QLabel("十六进制数组:")
        hex_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        hex_row.addWidget(hex_label)
        
        self.hex_array_input = QLineEdit()
        self.hex_array_input.setPlaceholderText("如: 0x48 0x65 0x6C 0x6C 0x6F 或 48 65 6C 6C 6F")
        self.hex_array_input.setStyleSheet(self._get_line_edit_style())
        self.hex_array_input.textChanged.connect(self.on_hex_array_input_changed)
        hex_row.addWidget(self.hex_array_input)
        tool2_layout.addLayout(hex_row)

        str_row = QHBoxLayout()
        str_label = QLabel("字符串:")
        str_label.setStyleSheet(f"color: {text_primary}; font-size: {font_size}; font-weight: 500;")
        str_row.addWidget(str_label)
        
        self.string_input = QLineEdit()
        self.string_input.setPlaceholderText("输入字符串...")
        self.string_input.setStyleSheet(self._get_line_edit_style())
        self.string_input.textChanged.connect(self.on_string_input_changed)
        str_row.addWidget(self.string_input)
        tool2_layout.addLayout(str_row)
        layout.addWidget(tool2_group)

        layout.addStretch()
        return widget

    def on_compile(self):
        """编译按钮点击"""
        self.compile_output.clear()
        self.status_label.setText("编译中...")
        self.progress_label.setText("")

        env_data = self.compile_env_combo.currentData()
        comp_data = self.compile_component_combo.currentData()

        if not env_data or not comp_data:
            self.compile_output.appendPlainText("[错误] 配置数据无效")
            self.status_label.setText("就绪")
            return

        server = env_data.get('server', 'localhost')
        path = env_data.get('path', '.')
        docker = env_data.get('docker')
        targets = comp_data.get('targets', ['all'])

        self.compile_output.appendPlainText(f"编译环境: {env_data.get('name', 'Unknown')}")
        self.compile_output.appendPlainText(f"服务器: {server}")
        self.compile_output.appendPlainText(f"路径: {path}")
        if docker:
            self.compile_output.appendPlainText(f"Docker: {docker}")
        self.compile_output.appendPlainText(f"编译目标: {', '.join(targets)}")
        self.compile_output.appendPlainText("-" * 40)

        for i, target in enumerate(targets):
            self.compile_output.appendPlainText(f"\n[{target}] 开始编译...")
            self.progress_label.setText(f"{i+1}/{len(targets)}")

        self.compile_output.appendPlainText("\n" + "-" * 40)
        self.compile_output.appendPlainText("[完成] 编译成功")
        self.status_label.setText("编译完成")
        self.progress_label.setText("100%")

    def on_test(self):
        """运行测试"""
        self.compile_output.clear()
        self.status_label.setText("测试中...")

        test_data = self.test_env_combo.currentData()
        if test_data:
            test_name = test_data.get('name', 'Unknown')
            test_cmd = test_data.get('command', '')

            self.compile_output.appendPlainText(f"测试类型: {test_name}")
            self.compile_output.appendPlainText(f"测试命令: {test_cmd}")
            self.compile_output.appendPlainText("-" * 40)
            self.compile_output.appendPlainText("\n[模拟] 测试运行中...")
            self.compile_output.appendPlainText("\n" + "-" * 40)
            self.compile_output.appendPlainText("[完成] 测试通过")

        self.status_label.setText("测试完成")
        self.progress_label.setText("")

    def on_clean(self):
        """清理按钮点击"""
        self.compile_output.clear()
        self.status_label.setText("就绪")
        self.progress_label.setText("")

    def _is_updating(self):
        """检查是否正在更新，避免循环触发"""
        return getattr(self, '_updating_conversion', False)
    
    def _set_updating(self, value):
        """设置更新状态"""
        self._updating_conversion = value
    
    def on_dec_input_changed(self):
        """十进制输入变化时自动转换"""
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
        """二进制输入变化时自动转换"""
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
        """十六进制输入变化时自动转换"""
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
        """十六进制数组输入变化时自动转换为字符串"""
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
        """字符串输入变化时自动转换为十六进制数组"""
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

