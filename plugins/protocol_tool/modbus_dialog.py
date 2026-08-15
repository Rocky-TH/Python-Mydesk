# -*- coding: utf-8 -*-
"""Modbus 报文封装/解析对话框。

为协议测试工具提供图形化的 Modbus 报文构造与解析入口：
- 封装模式：选择协议类型、功能码、地址、数量、值，生成报文并填入发送区
- 解析模式：解析发送区或接收区中的 Modbus 报文，以可读形式展示字段

采用主题样式接口（_get_style 等）保证深色/浅色主题下外观一致。
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox,
    QPlainTextEdit, QGroupBox, QMessageBox, QCheckBox,
    QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor

from .modbus_protocol import (
    ModbusProtocolFactory, FUNC_NAMES,
    FUNC_READ_COILS, FUNC_READ_DISCRETE_INPUTS,
    FUNC_READ_HOLDING_REGISTERS, FUNC_READ_INPUT_REGISTERS,
    FUNC_WRITE_SINGLE_COIL, FUNC_WRITE_SINGLE_REGISTER,
    FUNC_WRITE_MULTIPLE_COILS, FUNC_WRITE_MULTIPLE_REGISTERS,
    MODBUS_RTU, MODBUS_TCP,
    _EXCEPTION_NAMES
)

# 下拉框箭头图片路径
_DOWN_ARROW_IMG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'assets', 'down_arrow.png'
).replace('\\', '/')


# 读功能码集合
_READ_FUNCS = {FUNC_READ_COILS, FUNC_READ_DISCRETE_INPUTS,
               FUNC_READ_HOLDING_REGISTERS, FUNC_INPUT_REGISTERS if False else FUNC_READ_INPUT_REGISTERS}

# 写单个功能码集合
_WRITE_SINGLE = {FUNC_WRITE_SINGLE_COIL, FUNC_WRITE_SINGLE_REGISTER}

# 写多个功能码集合
_WRITE_MULTIPLE = {FUNC_WRITE_MULTIPLE_COILS, FUNC_WRITE_MULTIPLE_REGISTERS}


class ModbusDialog(QDialog):
    """Modbus 封装/解析对话框

    通过 ``mode`` 参数指定模式：
        'build'  - 封装报文（构造请求帧）
        'parse'  - 解析报文（展示字段）
    """

    def __init__(self, mode='build', config_manager=None,
                 source_text='', parent=None):
        """初始化

        Args:
            mode: 'build' 或 'parse'
            config_manager: ConfigManager 实例（用于主题样式）
            source_text: 解析模式下待解析的文本
            parent: 父窗口
        """
        super().__init__(parent)
        self._mode = mode
        self._config_manager = config_manager
        self._source_text = source_text
        self._result_hex = ''  # 封装结果（Hex 字符串）

        self.setWindowTitle("Modbus 报文封装" if mode == 'build' else "Modbus 报文解析")
        self.setMinimumSize(500, 480)
        self._init_ui()
        self._apply_theme()

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
                background-color: #3a8fd4; color: #ffffff;
                border: none; border-radius: 4px;
                padding: 6px 16px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #4a9fe4; }
            QPushButton:pressed { background-color: #2a7fc4; }
        """

    def _apply_theme(self):
        """应用主题样式"""
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        bg_secondary = self._get_style('bg-secondary', '#252526')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        border_light = self._get_style('border-light', '#4a4a4d')
        border_focus = self._get_style('border-focus', '#007acc')
        border_radius = self._get_border_radius('sm', '4px')
        font_size = self._get_font_size('size-md', '12px')
        unified_btn = self._get_button_css('button') if self._config_manager else ''

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg_main}; }}
            QLabel {{ color: {text_primary}; font-size: {font_size}; }}
            QLineEdit, QSpinBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                border-radius: {border_radius};
                padding: 3px 6px;
                font-size: {font_size};
            }}
            QLineEdit:focus, QSpinBox:focus {{ border-color: {border_focus}; }}
            QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                border-radius: {border_radius};
                padding: 3px 6px;
                font-size: {font_size};
                min-width: 180px;
            }}
            QComboBox:hover {{ border-color: {border_focus}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{ image: url({_DOWN_ARROW_IMG}); }}
            QComboBox QAbstractItemView {{
                background-color: {bg_secondary};
                color: {text_primary};
                selection-background-color: {self._get_style('selection', '#007acc')};
                selection-color: #ffffff;
                border: 1px solid {border_light};
            }}
            QPlainTextEdit {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                border-radius: {border_radius};
                font-family: Consolas;
                font-size: {font_size};
                padding: 4px;
            }}
            QGroupBox {{
                color: {text_primary};
                font-weight: bold;
                font-size: {font_size};
                border: 1px solid {border_light};
                border-radius: {self._get_border_radius('lg', '8px')};
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
            QPushButton {{
                padding: 4px 16px;
                font-size: {font_size};
                font-weight: bold;
                border-radius: {border_radius};
            }}
            {unified_btn}
        """)

    # ========== UI 构建 ==========
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        if self._mode == 'build':
            self._init_build_ui(layout)
        else:
            self._init_parse_ui(layout)

    def _init_build_ui(self, layout):
        """封装模式 UI"""
        # 参数区
        param_group = QGroupBox("报文参数")
        param_layout = QFormLayout(param_group)
        param_layout.setSpacing(6)

        # 协议类型
        self.proto_combo = QComboBox()
        self.proto_combo.addItem("Modbus RTU", MODBUS_RTU)
        self.proto_combo.addItem("Modbus TCP", MODBUS_TCP)
        param_layout.addRow("协议类型:", self.proto_combo)

        # 从站地址 / 单元 ID
        self.slave_spin = QSpinBox()
        self.slave_spin.setRange(1, 247)
        self.slave_spin.setValue(1)
        param_layout.addRow("从站地址:", self.slave_spin)

        # 功能码
        self.func_combo = QComboBox()
        for code, name in sorted(FUNC_NAMES.items()):
            self.func_combo.addItem(name, code)
        self.func_combo.currentIndexChanged.connect(self._on_func_changed)
        param_layout.addRow("功能码:", self.func_combo)

        # 起始地址
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(0, 65535)
        self.addr_spin.setValue(0)
        param_layout.addRow("起始地址:", self.addr_spin)

        # 数量（读操作）
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 2000)
        self.qty_spin.setValue(1)
        param_layout.addRow("数量:", self.qty_spin)

        # 写入值（写操作）
        self.values_input = QLineEdit()
        self.values_input.setPlaceholderText("多个值用逗号分隔，如 1,0,1 或 100,200")
        param_layout.addRow("写入值:", self.values_input)

        layout.addWidget(param_group)

        # 结果区
        result_group = QGroupBox("封装结果（Hex）")
        result_layout = QVBoxLayout(result_group)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(80)
        result_layout.addWidget(self.result_text)
        layout.addWidget(result_group)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        build_btn = QPushButton("封装")
        build_btn.clicked.connect(self._do_build)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(build_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # 初始状态
        self._on_func_changed(0)

    def _init_parse_ui(self, layout):
        """解析模式 UI"""
        # 待解析报文
        input_group = QGroupBox("待解析报文（Hex 字符串）")
        input_layout = QVBoxLayout(input_group)
        self.input_text = QPlainTextEdit()
        self.input_text.setPlaceholderText("粘贴 Hex 报文，如 01 03 00 00 00 0A C5 CD")
        self.input_text.setPlainText(self._source_text)
        input_layout.addWidget(self.input_text)

        # 协议类型选择
        proto_row = QHBoxLayout()
        proto_row.addWidget(QLabel("协议类型:"))
        self.proto_combo = QComboBox()
        self.proto_combo.addItem("自动识别", 'auto')
        self.proto_combo.addItem("Modbus RTU", MODBUS_RTU)
        self.proto_combo.addItem("Modbus TCP", MODBUS_TCP)
        proto_row.addWidget(self.proto_combo)
        proto_row.addStretch()
        input_layout.addLayout(proto_row)
        layout.addWidget(input_group)

        # 解析结果
        result_group = QGroupBox("解析结果")
        result_layout = QVBoxLayout(result_group)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)
        layout.addWidget(result_group, 1)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        parse_btn = QPushButton("解析")
        parse_btn.clicked.connect(self._do_parse)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(parse_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ========== 封装逻辑 ==========
    def _on_func_changed(self, _index):
        """功能码切换时更新输入控件可用性"""
        func_code = self.func_combo.currentData()
        is_read = func_code in _READ_FUNCS
        is_write_single = func_code in _WRITE_SINGLE
        is_write_multiple = func_code in _WRITE_MULTIPLE

        # 读操作：启用数量，禁用写入值
        self.qty_spin.setEnabled(is_read)
        self.values_input.setEnabled(not is_read)

        # 提示写入值格式
        if is_write_single and func_code == FUNC_WRITE_SINGLE_COIL:
            self.values_input.setPlaceholderText("线圈值：0 或 1")
        elif is_write_single:
            self.values_input.setPlaceholderText("寄存器值：0-65535")
        elif is_write_multiple and func_code == FUNC_WRITE_MULTIPLE_COILS:
            self.values_input.setPlaceholderText("线圈值列表，逗号分隔，如 1,0,1,0")
        elif is_write_multiple:
            self.values_input.setPlaceholderText("寄存器值列表，逗号分隔，如 100,200,300")
        else:
            self.values_input.setPlaceholderText("")

    def _do_build(self):
        """执行封装"""
        try:
            proto_type = self.proto_combo.currentData()
            func_code = self.func_combo.currentData()
            slave_id = self.slave_spin.value()
            addr = self.addr_spin.value()
            qty = self.qty_spin.value()

            values = None
            if func_code not in _READ_FUNCS:
                values = self._parse_values(func_code)
                if values is None:
                    return

            protocol = ModbusProtocolFactory.create(proto_type)
            adu = protocol.build_request(
                func_code, addr, qty, values=values, slave_id=slave_id)

            hex_str = ' '.join(f'{b:02X}' for b in adu)
            self._result_hex = hex_str
            self.result_text.setPlainText(hex_str)

        except Exception as e:
            QMessageBox.warning(self, "封装失败", str(e))

    def _parse_values(self, func_code):
        """解析写入值输入框"""
        text = self.values_input.text().strip()
        if not text:
            QMessageBox.warning(self, "输入错误", "请输入写入值")
            return None

        try:
            parts = [p.strip() for p in text.split(',') if p.strip()]
            if func_code == FUNC_WRITE_SINGLE_COIL:
                # 单个线圈值 0/1
                val = int(parts[0])
                return [1 if val else 0]
            elif func_code == FUNC_WRITE_SINGLE_REGISTER:
                # 单个寄存器值
                return [int(parts[0]) & 0xFFFF]
            elif func_code == FUNC_WRITE_MULTIPLE_COILS:
                # 线圈值列表
                return [1 if int(p) else 0 for p in parts]
            else:
                # 寄存器值列表
                return [int(p) & 0xFFFF for p in parts]
        except (ValueError, IndexError) as e:
            QMessageBox.warning(self, "输入错误", f"写入值格式无效：{e}")
            return None

    def get_result_hex(self):
        """获取封装结果（Hex 字符串，空格分隔）"""
        return self._result_hex

    # ========== 解析逻辑 ==========
    def _do_parse(self):
        """执行解析"""
        hex_text = self.input_text.toPlainText().strip()
        if not hex_text:
            QMessageBox.warning(self, "解析失败", "请输入待解析的报文")
            return

        try:
            data = self._hex_to_bytes(hex_text)
            if not data:
                QMessageBox.warning(self, "解析失败", "Hex 格式无效")
                return

            proto_type = self.proto_combo.currentData()
            protocol = self._identify_protocol(data, proto_type)
            if protocol is None:
                QMessageBox.warning(self, "解析失败", "无法识别协议类型")
                return

            result = protocol.parse(data)
            formatted = self._format_parse_result(result)
            self.result_text.setPlainText(formatted)

        except Exception as e:
            QMessageBox.warning(self, "解析失败", str(e))

    def _hex_to_bytes(self, hex_text):
        """将 Hex 字符串转换为字节串"""
        clean = hex_text.replace(' ', '').replace('\n', '').replace('\r', '')
        if len(clean) % 2 != 0:
            return None
        try:
            return bytes.fromhex(clean)
        except ValueError:
            return None

    def _identify_protocol(self, data, proto_type):
        """识别协议类型"""
        if proto_type == 'auto':
            # 启发式判断：TCP 报文 >= 8 字节且 Protocol ID (bytes[2:4]) 为 0x0000
            if len(data) >= 8:
                proto_id = (data[2] << 8) | data[3]
                if proto_id == 0:
                    return ModbusProtocolFactory.create(MODBUS_TCP)
            return ModbusProtocolFactory.create(MODBUS_RTU)
        return ModbusProtocolFactory.create(proto_type)

    def _format_parse_result(self, result):
        """将解析结果字典格式化为可读文本"""
        lines = []
        proto = result.get('protocol', '?').upper()
        lines.append(f"协议类型: Modbus {proto}")
        lines.append(f"校验状态: {'通过' if result.get('valid') else '失败'}")

        if not result.get('valid'):
            lines.append(f"错误信息: {result.get('error', '未知')}")
            return '\n'.join(lines)

        # 事务 ID（仅 TCP）
        if 'txn_id' in result:
            lines.append(f"事务 ID: 0x{result['txn_id']:04X}")
        if 'unit_id' in result:
            lines.append(f"单元 ID: {result['unit_id']}")
        if 'slave_id' in result:
            lines.append(f"从站地址: {result['slave_id']}")

        func_code = result.get('func_code', 0)
        is_exc = result.get('is_exception', False)
        func_name = FUNC_NAMES.get(func_code & 0x7F, f"未知(0x{func_code:02X})")
        lines.append(f"功能码: 0x{func_code:02X} ({func_name})")
        lines.append(f"报文类型: {'异常响应' if is_exc else '正常'}")

        if is_exc:
            exc_code = result.get('exception_code', 0)
            exc_name = _EXCEPTION_NAMES.get(exc_code, f"0x{exc_code:02X}")
            lines.append(f"异常码: 0x{exc_code:02X} ({exc_name})")
        else:
            data = result.get('data', {})
            direction = result.get('direction', '')
            if direction:
                lines.append(f"报文方向: {direction}")
            if 'start_address' in data:
                lines.append(f"起始地址: {data['start_address']}")
            if 'quantity' in data:
                lines.append(f"数量: {data['quantity']}")
            if 'value' in data:
                lines.append(f"值: {data['value']}")
            if 'values' in data:
                vals = data['values']
                if len(vals) <= 20:
                    lines.append(f"数据值: {vals}")
                else:
                    lines.append(f"数据值（前20个）: {vals[:20]}...")

        return '\n'.join(lines)
