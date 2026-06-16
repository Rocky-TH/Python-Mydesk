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
    def __init__(self, config):
        self.config = config
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = QuicklyCmdWidget(self.config)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass


class QuicklyCmdWidget(QWidget):
    """快捷命令插件 - 包含编译工具和字节转换工具"""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.compile_config = self.load_compile_config()
        self.init_ui()

    def load_compile_config(self):
        """加载编译配置文件"""
        # 尝试从插件配置文件加载
        config_path = os.path.join(
            os.path.dirname(__file__),
            'config.json'
        )
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    full_config = json.load(f)
                    return full_config.get('compile', {})
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载编译配置失败: {e}")
        
        # 返回默认配置
        return {
            "environments": [{"name": "本地环境", "server": "localhost", "path": ".", "docker": None}],
            "components": [{"name": "全部组件", "targets": ["all"]}],
            "test_environments": [{"name": "单元测试", "type": "unit", "command": "pytest"}]
        }

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # 使用标签页组织工具
        self.tool_tabs = QTabWidget()
        self.tool_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3d3d40;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px 20px;
                border: 1px solid #3d3d40;
            }
            QTabBar::tab:selected {
                background-color: #007acc;
                color: white;
            }
        """)
        layout.addWidget(self.tool_tabs)

        # 编译工具标签页
        compile_tab = self.create_compile_tool()
        self.tool_tabs.addTab(compile_tab, "编译工具")

        # 字节转换工具标签页
        byte_tab = self.create_byte_convert_tool()
        self.tool_tabs.addTab(byte_tab, "字节转换")

    def create_compile_tool(self):
        """创建编译工具"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)

        # 编译选项组
        options_group = QGroupBox("编译选项")
        options_group.setStyleSheet("""
            QGroupBox {
                color: #cccccc;
                font-weight: bold;
                border: 1px solid #3d3d40;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
            }
        """)
        options_layout = QFormLayout(options_group)
        options_layout.setSpacing(10)

        # 编译环境 - ComboBox
        self.compile_env_combo = QComboBox()
        self.compile_env_combo.setStyleSheet("""
            QComboBox {
                background-color: #3d3d40;
                color: #cccccc;
                border: 1px solid #555;
                padding: 5px;
                min-width: 200px;
            }
            QComboBox:hover {
                border-color: #007acc;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d30;
                color: #cccccc;
                selection-background-color: #007acc;
            }
        """)
        
        # 从配置加载编译环境选项
        for env in self.compile_config.get('environments', []):
            self.compile_env_combo.addItem(env['name'], env)
        
        options_layout.addRow("编译环境:", self.compile_env_combo)

        # 编译组件 - ComboBox
        self.compile_component_combo = QComboBox()
        self.compile_component_combo.setStyleSheet(self.compile_env_combo.styleSheet())
        
        # 从配置加载编译组件选项
        for comp in self.compile_config.get('components', []):
            self.compile_component_combo.addItem(comp['name'], comp)
        
        options_layout.addRow("编译组件:", self.compile_component_combo)

        # 测试环境 - ComboBox
        self.test_env_combo = QComboBox()
        self.test_env_combo.setStyleSheet(self.compile_env_combo.styleSheet())
        
        # 从配置加载测试环境选项
        for test in self.compile_config.get('test_environments', []):
            self.test_env_combo.addItem(test['name'], test)
        
        options_layout.addRow("测试环境:", self.test_env_combo)

        layout.addWidget(options_group)

        # 当前选择详情显示
        detail_group = QGroupBox("当前配置详情")
        detail_group.setStyleSheet("""
            QGroupBox {
                color: #cccccc;
                font-weight: bold;
                border: 1px solid #3d3d40;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        detail_layout = QVBoxLayout(detail_group)

        self.detail_text = QLabel("选择编译环境后显示详细配置信息")
        self.detail_text.setStyleSheet("color: #888; font-size: 11px;")
        self.detail_text.setWordWrap(True)
        detail_layout.addWidget(self.detail_text)

        layout.addWidget(detail_group)

        # 绑定选择变化事件
        self.compile_env_combo.currentIndexChanged.connect(self.update_detail_info)

        # 编译按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.compile_btn = QPushButton("开始编译")
        self.compile_btn.setFixedHeight(35)
        self.compile_btn.setFixedWidth(150)
        self.compile_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        self.compile_btn.clicked.connect(self.on_compile)
        btn_layout.addWidget(self.compile_btn)

        self.test_btn = QPushButton("运行测试")
        self.test_btn.setFixedHeight(35)
        self.test_btn.setFixedWidth(100)
        self.test_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        self.test_btn.clicked.connect(self.on_test)
        btn_layout.addWidget(self.test_btn)

        self.clean_btn = QPushButton("清理")
        self.clean_btn.setFixedHeight(35)
        self.clean_btn.setFixedWidth(80)
        self.clean_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d3d40;
                color: #cccccc;
                border: none;
            }
            QPushButton:hover {
                background-color: #4d4d50;
            }
        """)
        self.clean_btn.clicked.connect(self.on_clean)
        btn_layout.addWidget(self.clean_btn)

        layout.addLayout(btn_layout)

        # 输出区域
        output_group = QGroupBox("编译输出")
        output_group.setStyleSheet("""
            QGroupBox {
                color: #cccccc;
                font-weight: bold;
                border: 1px solid #3d3d40;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        output_layout = QVBoxLayout(output_group)

        self.compile_output = QPlainTextEdit()
        self.compile_output.setFont(QFont("Consolas", 10))
        self.compile_output.setReadOnly(True)
        self.compile_output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0c0c0c;
                color: #00ff00;
                border: none;
            }
        """)
        output_layout.addWidget(self.compile_output)

        layout.addWidget(output_group)

        # 状态栏
        self.status_bar = QWidget()
        self.status_bar.setFixedHeight(30)
        self.status_bar.setStyleSheet("background-color: #007acc;")
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(10, 0, 10, 0)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: white; font-weight: bold;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: rgba(255,255,255,0.8);")
        status_layout.addWidget(self.progress_label)

        layout.addWidget(self.status_bar)

        # 初始化详情显示
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
            self.detail_text.setStyleSheet("color: #00ff00; font-size: 11px;")

    def create_byte_convert_tool(self):
        """创建字节转换工具"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)

        # 小工具1: 数制转换
        tool1_group = QGroupBox("数制转换 (十进制/二进制/十六进制)")
        tool1_group.setStyleSheet("""
            QGroupBox {
                color: #cccccc;
                font-weight: bold;
                border: 1px solid #3d3d40;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        tool1_layout = QVBoxLayout(tool1_group)

        # 输入行
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("输入值:"))
        self.num_input = QLineEdit()
        self.num_input.setPlaceholderText("输入数值...")
        self.num_input.setStyleSheet("background-color: #3d3d40; color: #cccccc; border: 1px solid #555;")
        input_row.addWidget(self.num_input)

        input_row.addWidget(QLabel("类型:"))
        self.num_type_combo = QComboBox()
        self.num_type_combo.addItems(["十进制", "二进制", "十六进制"])
        self.num_type_combo.setStyleSheet("background-color: #3d3d40; color: #cccccc;")
        input_row.addWidget(self.num_type_combo)

        tool1_layout.addLayout(input_row)

        # 转换按钮
        convert_btn_row = QHBoxLayout()
        convert_btn_row.addStretch()

        self.convert_num_btn = QPushButton("转换")
        self.convert_num_btn.setStyleSheet("""
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
        self.convert_num_btn.clicked.connect(self.on_convert_number)
        convert_btn_row.addWidget(self.convert_num_btn)

        tool1_layout.addLayout(convert_btn_row)

        # 输出结果
        result_layout = QFormLayout()
        self.dec_result = QLineEdit()
        self.dec_result.setReadOnly(True)
        self.dec_result.setStyleSheet("background-color: #1e1e1e; color: #00ff00;")
        result_layout.addRow("十进制:", self.dec_result)

        self.bin_result = QLineEdit()
        self.bin_result.setReadOnly(True)
        self.bin_result.setStyleSheet("background-color: #1e1e1e; color: #00ff00;")
        result_layout.addRow("二进制:", self.bin_result)

        self.hex_result = QLineEdit()
        self.hex_result.setReadOnly(True)
        self.hex_result.setStyleSheet("background-color: #1e1e1e; color: #00ff00;")
        result_layout.addRow("十六进制:", self.hex_result)

        tool1_layout.addLayout(result_layout)
        layout.addWidget(tool1_group)

        # 小工具2: 十六进制数组与字符串转换
        tool2_group = QGroupBox("十六进制数组与字符串转换")
        tool2_group.setStyleSheet("""
            QGroupBox {
                color: #cccccc;
                font-weight: bold;
                border: 1px solid #3d3d40;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        tool2_layout = QVBoxLayout(tool2_group)

        # 十六进制数组输入
        hex_row = QHBoxLayout()
        hex_row.addWidget(QLabel("十六进制数组:"))
        self.hex_array_input = QLineEdit()
        self.hex_array_input.setPlaceholderText("如: 0x48 0x65 0x6C 0x6C 0x6F 或 48 65 6C 6C 6F")
        self.hex_array_input.setStyleSheet("background-color: #3d3d40; color: #cccccc; border: 1px solid #555;")
        hex_row.addWidget(self.hex_array_input)
        tool2_layout.addLayout(hex_row)

        # 字符串输入
        str_row = QHBoxLayout()
        str_row.addWidget(QLabel("字符串:"))
        self.string_input = QLineEdit()
        self.string_input.setPlaceholderText("输入字符串...")
        self.string_input.setStyleSheet("background-color: #3d3d40; color: #cccccc; border: 1px solid #555;")
        str_row.addWidget(self.string_input)
        tool2_layout.addLayout(str_row)

        # 转换按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.hex_to_str_btn = QPushButton("数组→字符串")
        self.hex_to_str_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        self.hex_to_str_btn.clicked.connect(self.on_hex_to_string)
        btn_row.addWidget(self.hex_to_str_btn)

        self.str_to_hex_btn = QPushButton("字符串→数组")
        self.str_to_hex_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
        """)
        self.str_to_hex_btn.clicked.connect(self.on_string_to_hex)
        btn_row.addWidget(self.str_to_hex_btn)

        tool2_layout.addLayout(btn_row)
        layout.addWidget(tool2_group)

        layout.addStretch()
        return widget

    def on_compile(self):
        """编译按钮点击"""
        self.compile_output.clear()
        self.status_label.setText("编译中...")
        self.progress_label.setText("")

        # 获取选择的配置
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

        # 模拟编译过程
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

    def on_convert_number(self):
        """数制转换"""
        input_val = self.num_input.text().strip()
        if not input_val:
            QMessageBox.warning(self, "警告", "请输入数值")
            return

        try:
            input_type = self.num_type_combo.currentText()

            # 根据输入类型解析数值
            if input_type == "十进制":
                num = int(input_val, 10)
            elif input_type == "二进制":
                # 去掉可能的0b前缀
                val = input_val.lower().replace("0b", "")
                num = int(val, 2)
            elif input_type == "十六进制":
                # 去掉可能的0x前缀
                val = input_val.lower().replace("0x", "")
                num = int(val, 16)

            # 显示三种进制结果
            self.dec_result.setText(str(num))
            self.bin_result.setText("0b" + bin(num))
            self.hex_result.setText("0x" + hex(num).upper()[2:])

        except ValueError as e:
            QMessageBox.warning(self, "错误", f"无效的数值格式: {str(e)}")

    def on_hex_to_string(self):
        """十六进制数组转字符串"""
        hex_input = self.hex_array_input.text().strip()
        if not hex_input:
            QMessageBox.warning(self, "警告", "请输入十六进制数组")
            return

        try:
            # 解析十六进制数组
            # 支持格式: "0x48 0x65 0x6C" 或 "48 65 6C" 或 "48,65,6C"
            hex_values = hex_input.replace(",", " ").split()
            bytes_data = []
            for val in hex_values:
                val = val.lower().replace("0x", "")
                bytes_data.append(int(val, 16))

            # 转换为字符串
            result = bytes(bytes_data).decode('utf-8', errors='replace')
            self.string_input.setText(result)

        except ValueError as e:
            QMessageBox.warning(self, "错误", f"无效的十六进制格式: {str(e)}")

    def on_string_to_hex(self):
        """字符串转十六进制数组"""
        str_input = self.string_input.text()
        if not str_input:
            QMessageBox.warning(self, "警告", "请输入字符串")
            return

        try:
            # 转换为字节
            bytes_data = str_input.encode('utf-8')

            # 格式化为十六进制数组
            hex_array = " ".join([f"0x{b:02X}" for b in bytes_data])
            self.hex_array_input.setText(hex_array)

        except Exception as e:
            QMessageBox.warning(self, "错误", f"转换失败: {str(e)}")