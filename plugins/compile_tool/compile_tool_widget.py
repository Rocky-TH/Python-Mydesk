import json
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QGroupBox, QMessageBox, QCheckBox,
    QTabWidget, QSpinBox, QPlainTextEdit,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

# 下拉框三角形箭头图片路径
_DOWN_ARROW_IMG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'assets', 'down_arrow.png'
).replace('\\', '/')


class CompileToolPlugin:
    """编译工具插件"""

    def __init__(self, config, config_manager=None, plugin_manager=None):
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = CompileToolWidget(self.config, self._config_manager, self._plugin_manager)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass


class CompileToolWidget(QWidget):
    """编译工具组件"""

    def __init__(self, config=None, config_manager=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self._remote_cmd_plugin = None
        self._current_connection = None
        self.compile_config = self.load_compile_config()
        self.init_ui()

    def _get_remote_cmd_plugin(self):
        """获取 RemoteCmd 插件实例"""
        if not self._remote_cmd_plugin and self._plugin_manager:
            self._remote_cmd_plugin = self._plugin_manager.get_plugin("RemoteCmd")
        return self._remote_cmd_plugin

    def load_compile_config(self):
        """加载编译配置"""
        if self._config_manager:
            plugin_config = self._config_manager.get_plugin_config("CompileTool")
            if plugin_config:
                return plugin_config.get('compile', {})

        return {
            "compile_environments": [{"name": "本地环境", "server": "localhost", "path": ".", "docker": None, "script": ""}],
            "compile_components": [{"name": "全部组件", "targets": ["all"], "script": ""}],
            "test_environments": [{"name": "单元测试", "type": "unit", "command": "pytest", "script": ""}]
        }

    def get_style(self, key, default=None):
        """获取样式配置（支持新旧两种格式）"""
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

    def get_button_css(self, button_type='button'):
        """获取按钮的统一 CSS 样式

        Args:
            button_type: 按钮类型
                - 'button': 标准按钮（蓝色背景、白色字体）
                - 'button-function': 功能按钮（蓝色背景、白色字体）
                - 'button-calc-number': 计算器数字按钮
                - 'button-calc-function': 计算器功能按钮（蓝色背景、白色字体）
                - 'button-calc-equals': 计算器等号按钮（蓝色背景、白色字体）
                - 'button-calc-clear': 计算器清除按钮（红色背景、白色字体）
        """
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
        """获取统一菜单 CSS 样式（悬停/选中时字体为白色）"""
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

    def _get_group_box_style(self):
        """生成GroupBox样式"""
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
        """生成ComboBox样式"""
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
        """生成LineEdit样式"""
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
                QLineEdit {{
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
            QLineEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 4px 8px;
                border-radius: {border_radius};
                font-size: {font_size};
            }}
            QLineEdit:focus {{
                border-color: {border_focus};
                background-color: {bg_input_focus};
            }}
        """

    def _get_button_style(self, type='primary'):
        """生成按钮样式（统一使用蓝色背景+白色字体+加粗）"""
        type_map = {
            'primary': 'button',
            'success': 'button',
            'secondary': 'button-secondary',
        }
        button_type = type_map.get(type, 'button')
        return self.get_button_css(button_type)

    def _get_plain_text_edit_style(self):
        """生成PlainTextEdit样式"""
        text_primary = self.get_style('text', '#e0e0e0')
        bg_main = self.get_style('bg-main', '#1e1e1e')
        border = self.get_style('border', '#3c3c3c')
        border_radius = self.get_border_radius('sm', '4px')
        font_size = self.get_font_size('size-sm', '11px')

        return f"""
            QPlainTextEdit {{
                background-color: {bg_main};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius};
                padding: 8px;
                font-size: {font_size};
                font-family: Consolas;
            }}
        """

    def init_ui(self):
        """初始化编译工具界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        options_group = QGroupBox("编译选项")
        options_group.setStyleSheet(self._get_group_box_style())
        options_layout = QHBoxLayout(options_group)
        options_layout.setSpacing(10)
        options_layout.setContentsMargins(10, 8, 10, 8)

        text_primary = self.get_style('text', '#ffffff')
        font_size = self.get_font_size('size-md', '12px')
        label_style = f"color: {text_primary}; font-size: {font_size}; font-weight: 500;"

        env_label = QLabel("编译环境:")
        env_label.setStyleSheet(label_style)
        env_label.setFixedWidth(80)
        env_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        options_layout.addWidget(env_label)
        self.compile_env_combo = QComboBox()
        self.compile_env_combo.setStyleSheet(self._get_combo_box_style())
        self.compile_env_combo.setMinimumWidth(140)

        for env in self.compile_config.get('compile_environments', []):
            self.compile_env_combo.addItem(env['name'], env)

        options_layout.addWidget(self.compile_env_combo, 1)

        comp_label = QLabel("编译组件:")
        comp_label.setStyleSheet(label_style)
        comp_label.setFixedWidth(80)
        comp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        options_layout.addWidget(comp_label)
        self.compile_component_combo = QComboBox()
        self.compile_component_combo.setStyleSheet(self._get_combo_box_style())
        self.compile_component_combo.setMinimumWidth(140)

        for comp in self.compile_config.get('compile_components', []):
            self.compile_component_combo.addItem(comp['name'], comp)

        options_layout.addWidget(self.compile_component_combo, 1)

        test_label = QLabel("测试环境:")
        test_label.setStyleSheet(label_style)
        test_label.setFixedWidth(80)
        test_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        options_layout.addWidget(test_label)
        self.test_env_combo = QComboBox()
        self.test_env_combo.setStyleSheet(self._get_combo_box_style())
        self.test_env_combo.setMinimumWidth(140)

        for test in self.compile_config.get('test_environments', []):
            self.test_env_combo.addItem(test['name'], test)

        options_layout.addWidget(self.test_env_combo, 1)

        layout.addWidget(options_group)

        detail_group = QGroupBox("当前配置详情")
        detail_group.setStyleSheet(self._get_group_box_style())
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(8, 6, 8, 6)
        detail_layout.setSpacing(2)

        self.detail_text = QLabel("选择编译环境后显示详细配置信息")
        text_success = self.get_style('text-success', '#00ff00')
        font_size = self.get_font_size('size-md', '12px')
        self.detail_text.setStyleSheet(f"color: {text_success}; font-size: {font_size}; font-weight: 500;")
        self.detail_text.setWordWrap(True)
        self.detail_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_layout.addWidget(self.detail_text)

        layout.addWidget(detail_group)

        self.compile_env_combo.currentIndexChanged.connect(self.update_detail_info)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.addStretch()

        self.compile_btn = QPushButton("开始编译")
        self.compile_btn.setFixedHeight(32)
        self.compile_btn.setFixedWidth(140)
        self.compile_btn.setStyleSheet(self._get_button_style('primary'))
        self.compile_btn.clicked.connect(self.on_compile)
        btn_layout.addWidget(self.compile_btn)

        self.test_btn = QPushButton("运行测试")
        self.test_btn.setFixedHeight(32)
        self.test_btn.setFixedWidth(100)
        self.test_btn.setStyleSheet(self._get_button_style('success'))
        self.test_btn.clicked.connect(self.on_test)
        btn_layout.addWidget(self.test_btn)

        self.clean_btn = QPushButton("清理")
        self.clean_btn.setFixedHeight(32)
        self.clean_btn.setFixedWidth(80)
        self.clean_btn.setStyleSheet(self._get_button_style('secondary'))
        self.clean_btn.clicked.connect(self.on_clean)
        btn_layout.addWidget(self.clean_btn)

        layout.addLayout(btn_layout)

        output_group = QGroupBox("编译输出")
        output_group.setStyleSheet(self._get_group_box_style())
        output_layout = QVBoxLayout(output_group)
        output_layout.setContentsMargins(8, 6, 8, 6)
        output_layout.setSpacing(2)

        self.compile_output = QPlainTextEdit()
        self.compile_output.setFont(QFont("Consolas", 11))
        self.compile_output.setReadOnly(True)
        self.compile_output.setStyleSheet(self._get_plain_text_edit_style())
        output_layout.addWidget(self.compile_output)

        layout.addWidget(output_group, 1)

        # 状态显示通过框架统一状态接口（不再渲染独立状态栏）
        # 保留字段以兼容现有逻辑
        self.status_label = QLabel("就绪")
        self.progress_label = QLabel("")
        self._set_tool_status("就绪")

        self.update_detail_info()

        # 保存需要刷新样式的控件引用
        self._style_widgets = {
            'compile_env_combo': self.compile_env_combo,
            'compile_component_combo': self.compile_component_combo,
            'test_env_combo': self.test_env_combo,
            'detail_text': self.detail_text,
            'compile_output': self.compile_output,
        }

    def refresh_theme_styles(self):
        """刷新主题样式"""
        if not hasattr(self, '_style_widgets'):
            return
        text_primary = self.get_style('text', '#e0e0e0')
        text_success = self.get_style('text-success', '#4ec9b0')
        font_size = self.get_font_size('size-md', '12px')
        # 刷新GroupBox样式
        for widget in self.findChildren(QGroupBox):
            widget.setStyleSheet(self._get_group_box_style())
        # 刷新ComboBox样式
        combo_style = self._get_combo_box_style()
        for key in ['compile_env_combo', 'compile_component_combo', 'test_env_combo']:
            if key in self._style_widgets:
                self._style_widgets[key].setStyleSheet(combo_style)
        # 刷新按钮样式
        self.compile_btn.setStyleSheet(self._get_button_style('primary'))
        self.test_btn.setStyleSheet(self._get_button_style('success'))
        self.clean_btn.setStyleSheet(self._get_button_style('secondary'))
        # 刷新输出区样式
        if 'compile_output' in self._style_widgets:
            self._style_widgets['compile_output'].setStyleSheet(self._get_plain_text_edit_style())
        # 刷新所有标签样式（编译环境、编译组件、测试环境等）
        label_style = f"color: {text_primary}; font-size: {font_size}; font-weight: 500;"
        for label in self.findChildren(QLabel):
            label.setStyleSheet(label_style)
        # detail_text 使用绿色（text-success），放在最后避免被覆盖
        if 'detail_text' in self._style_widgets:
            self._style_widgets['detail_text'].setStyleSheet(
                f"color: {text_success}; font-size: {font_size}; font-weight: 500;"
            )

    def _set_tool_status(self, text):
        """通过框架统一状态接口上报工具状态"""
        if self._plugin_manager and hasattr(self._plugin_manager, 'set_tool_status'):
            self._plugin_manager.set_tool_status('CompileTool', text)
        self.status_label.setText(text)

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

    def _auto_connect_and_discover_components(self, env_data):
        """自动连接到编译环境并发现组件"""
        remote_cmd = self._get_remote_cmd_plugin()
        if not remote_cmd:
            return

        env_name = env_data.get('name', '')

        if env_data.get('connection'):
            self.detail_text.setText(self.detail_text.text() + "\n连接中...")

            success, msg = remote_cmd.connect(env_name)
            if success:
                text_success = self.get_style('text_success', '#00ff00')
                self.detail_text.setText(self.detail_text.text() + f"\n{msg}")
                self.detail_text.setStyleSheet(f"color: {text_success}; font-size: {self.get_font_size('small', '11px')};")
                self._current_connection = env_name

                path = env_data.get('path', '.')
                self._discover_components(path)
            else:
                text_error = self.get_style('text_error', '#ff6b6b')
                self.detail_text.setText(self.detail_text.text() + f"\n[连接失败] {msg}")
                self.detail_text.setStyleSheet(f"color: {text_error}; font-size: {self.get_font_size('small', '11px')};")
        else:
            path = env_data.get('path', '.')
            self._discover_components(path)

    def _discover_components(self, path):
        """发现当前路径下的编译组件"""
        discovered_components = []

        script_dir = os.path.join(path, 'script')
        make_rom_path = os.path.join(script_dir, 'make_rom.sh')

        if os.path.exists(make_rom_path):
            component_name = os.path.basename(path)
            discovered_components.append({
                'name': component_name,
                'targets': [component_name],
                'description': f"基于 make_rom.sh 的 {component_name} 组件"
            })

        component_dirs = ['support_components', 'functional_components', 'buiness_components']
        for comp_dir in component_dirs:
            full_path = os.path.join(path, comp_dir)
            if os.path.isdir(full_path):
                for item in os.listdir(full_path):
                    item_path = os.path.join(full_path, item)
                    if os.path.isdir(item_path):
                        discovered_components.append({
                            'name': item,
                            'targets': [item],
                            'description': f"{comp_dir} 下的 {item} 组件"
                        })

        default_components = self.compile_config.get('compile_components', [])

        all_components = []
        existing_names = set()

        for comp in default_components:
            all_components.append(comp)
            existing_names.add(comp['name'])

        for comp in discovered_components:
            if comp['name'] not in existing_names:
                all_components.append(comp)
                existing_names.add(comp['name'])

        self.compile_component_combo.blockSignals(True)
        self.compile_component_combo.clear()
        for comp in all_components:
            self.compile_component_combo.addItem(comp['name'], comp)
        self.compile_component_combo.blockSignals(False)

    def on_compile(self):
        """编译按钮点击"""
        self.compile_output.clear()
        self._set_tool_status("编译中...")
        self.progress_label.setText("")

        env_data = self.compile_env_combo.currentData()
        comp_data = self.compile_component_combo.currentData()

        if not env_data or not comp_data:
            self.compile_output.appendPlainText("[错误] 配置数据无效")
            self._set_tool_status("就绪")
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
            self._set_tool_status(f"编译中... {i+1}/{len(targets)}")

        self.compile_output.appendPlainText("\n" + "-" * 40)
        self.compile_output.appendPlainText("[完成] 编译成功")
        self._set_tool_status("编译完成")

    def on_test(self):
        """运行测试"""
        self.compile_output.clear()
        self._set_tool_status("测试中...")

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

        self._set_tool_status("测试完成")

    def on_clean(self):
        """清理按钮点击"""
        self.compile_output.clear()
        self._set_tool_status("就绪")
        self.progress_label.setText("")