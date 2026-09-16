# -*- coding: utf-8 -*-
"""协议测试工具插件。

参考 sscom 串口工具的排版与功能，支持串口、TCP 客户端、TCP 服务端三种连接类型，
接收区与发送区分离，支持十六进制/字符串收发、CRC-16/MODBUS 校验、定时发送与
日志记录。所有控件样式通过 ConfigManager 统一管理，主题切换时自动刷新。
"""

import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QPlainTextEdit,
    QComboBox, QGroupBox, QMessageBox, QCheckBox,
    QSpinBox, QFileDialog, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QTextCursor

from .connections import (
    SerialConnection, TCPClientConnection, TCPServerConnection,
    list_serial_ports, append_crc16_modbus, crc16_modbus
)
from .modbus_protocol import ModbusProtocolFactory, FUNC_NAMES

# 下拉框三角形箭头图片路径（与项目其他模块保持一致）
_DOWN_ARROW_IMG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'assets', 'down_arrow.png'
).replace('\\', '/')

# 项目根目录（用于解析相对路径的 log_dir）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 常用波特率
_BAUD_RATES = ['9600', '19200', '38400', '57600', '115200', '230400', '460800', '921600']

# 连接类型常量
_CONN_SERIAL = 0
_CONN_TCP_CLIENT = 1
_CONN_TCP_SERVER = 2

# 接收区分隔符
_SEP_NONE = 0
_SEP_SPACE = 1
_SEP_NEWLINE = 2


class HexPlainTextEdit(QPlainTextEdit):
    """支持十六进制输入校验的多行编辑框。

    在 hex_mode 下仅允许输入 0-9A-Fa-f 与空格，过滤非法字符；控制键（退格、
    方向键、复制粘贴快捷键等无 text 的按键）不受影响。
    """

    _ALLOWED_CHARS = set('0123456789ABCDEFabcdef ')

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hex_mode = False

    def set_hex_mode(self, on):
        self._hex_mode = bool(on)

    def _is_text_allowed(self, text):
        return all(c in self._ALLOWED_CHARS for c in text)

    def keyPressEvent(self, event):
        if self._hex_mode:
            text = event.text()
            # 仅对有可见文本输入的按键做过滤；控制键（退格、删除、方向键等
            # text 为空或为控制字符的按键）一律放行，避免 hex 模式下无法删除
            if text and text.isprintable() and not self._is_text_allowed(text):
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        if self._hex_mode:
            text = source.text()
            if text and not self._is_text_allowed(text):
                return
        super().insertFromMimeData(source)


class ProtocolToolPlugin:
    """协议测试工具插件"""

    def __init__(self, config, config_manager=None, plugin_manager=None):
        self.config = config
        self._config_manager = config_manager
        self._plugin_manager = plugin_manager
        self.name = config['name']
        self.display_name = config.get('display_name', config['name'])
        self.widget = None

    def get_widget(self):
        if self.widget is None:
            self.widget = ProtocolToolWidget(self.config, self._config_manager, self._plugin_manager)
        return self.widget

    def activate(self):
        pass

    def deactivate(self):
        pass


class ProtocolToolWidget(QWidget):
    """协议测试工具主组件"""

    def __init__(self, config=None, config_manager=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._config_manager = config_manager
        # 插件管理器引用（用于向主窗体状态栏上报状态）
        self._plugin_manager_ref = plugin_manager

        # 运行时状态
        self._connection = None
        self._is_connected = False
        self._closing = False
        self._rx_bytes = 0
        self._tx_bytes = 0
        # 缓存当前连接类型名称（用于状态上报）
        self._conn_type_text = '串口'

        # ========== 寄存器操作（Modbus 协议封装） ==========
        self.modbus_rtu = ModbusProtocolFactory.create('rtu')
        self.modbus_tcp = ModbusProtocolFactory.create('tcp')
        # 寄存器请求缓存：{ 请求数据hex: {'func': func_code, 'qty': 数量} }
        #   用于在收到响应时解析并回填 value 框
        self._pending_reg_requests = {}
        # 当前寄存器请求是否是读操作（当响应且 qty==1 时回填 value）
        self._pending_reg_read = False
        self._pending_reg_func = 0
        self._pending_reg_qty = 0

        self.init_ui()
        self._apply_conn_type_visibility()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_send)
        self._update_status()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ========== 样式接口（参考 calc_tool_widget 模式）==========
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
                background-color: #3a8fd4;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4a9fe4; }
            QPushButton:pressed { background-color: #2a7fc4; }
        """

    def _get_group_box_style(self):
        text_primary = self._get_style('text', '#ffffff')
        border_light = self._get_style('border-light', '#4a4a4d')
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

    def _get_combo_box_style(self):
        bg_input = self._get_style('bg-input', '#3c3c3c')
        text_primary = self._get_style('text', '#ffffff')
        border_light = self._get_style('border-light', '#4a4a4d')
        border_focus = self._get_style('border-focus', '#007acc')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        selection = self._get_style('selection', '#007acc')
        selection_text = self._get_style('selection-text', '#ffffff')
        border_radius = self._get_border_radius('sm', '4px')
        font_size = self._get_font_size('size-md', '12px')
        return f"""
            QComboBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 0px 10px;
                min-width: 80px;
                min-height: 28px;
                height: 28px;
                border-radius: {border_radius};
                font-size: {font_size};
            }}
            QComboBox:hover {{ border-color: {border_focus}; background-color: {bg_input_focus}; }}
            QComboBox:focus {{ border-color: {border_focus}; background-color: {bg_input_focus}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{ image: url({_DOWN_ARROW_IMG}); }}
            QComboBox QAbstractItemView {{
                background-color: {bg_tertiary};
                color: {text_primary};
                selection-background-color: {selection};
                selection-color: {selection_text};
                border: 1px solid {border_light};
                border-radius: {border_radius};
                min-height: 24px;
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
                min-height: 28px;
                height: 28px;
                border-radius: {border_radius};
                font-size: {font_size};
            }}
            QLineEdit:focus {{ border-color: {border_focus}; background-color: {bg_input_focus}; }}
        """

    def _get_spinbox_style(self):
        bg_input = self._get_style('bg-input', '#3c3c3c')
        text_primary = self._get_style('text', '#ffffff')
        border_light = self._get_style('border-light', '#4a4a4d')
        border_focus = self._get_style('border-focus', '#007acc')
        bg_input_focus = self._get_style('bg-input-focus', '#4c4c4c')
        border_radius = self._get_border_radius('sm', '4px')
        font_size = self._get_font_size('size-md', '12px')
        return f"""
            QSpinBox {{
                background-color: {bg_input};
                color: {text_primary};
                border: 1px solid {border_light};
                padding: 0px 10px;
                border-radius: {border_radius};
                font-size: {font_size};
                min-width: 80px;
                min-height: 28px;
                height: 28px;
            }}
            QSpinBox:focus {{ border-color: {border_focus}; background-color: {bg_input_focus}; }}
            /* 隐藏增减箭头按钮（按项目之前要求：取消输入框的增加和减小功能）*/
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 0px;
                height: 0px;
                border: none;
            }}
            QSpinBox::up-arrow, QSpinBox::down-arrow {{
                width: 0px;
                height: 0px;
            }}
        """

    def _get_checkbox_style(self):
        text_primary = self._get_style('text', '#ffffff')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border_light = self._get_style('border-light', '#4a4a4d')
        primary = self._get_style('primary', '#3a8fd4')
        font_size = self._get_font_size('size-md', '12px')
        return f"""
            QCheckBox {{
                color: {text_primary};
                font-size: {font_size};
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {border_light};
                border-radius: 3px;
                background-color: {bg_input};
            }}
            QCheckBox::indicator:checked {{
                background-color: {primary};
                border-color: {primary};
            }}
        """

    def _get_plain_text_edit_style(self, read_only=False):
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_input = self._get_style('bg-input', '#454545')
        text_primary = self._get_style('text', '#e0e0e0')
        border = self._get_style('border', '#3c3c3c')
        border_focus = self._get_style('border-focus', '#007acc')
        border_radius = self._get_border_radius('sm', '4px')
        font_size = self._get_font_size('size-md', '12px')
        bg = bg_main if read_only else bg_input
        focus_block = "" if read_only else f"""
            QPlainTextEdit:focus {{ border-color: {border_focus}; }}
        """
        return f"""
            QPlainTextEdit {{
                background-color: {bg};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: {border_radius};
                font-family: Consolas;
                font-size: {font_size};
                padding: 4px;
            }}
            {focus_block}
        """

    def _get_label_style(self, secondary=False):
        text = self._get_style('text-secondary', '#b0b0b0') if secondary else self._get_style('text', '#e0e0e0')
        font_size = self._get_font_size('size-md', '12px')
        return f"color: {text}; font-size: {font_size}; font-weight: 500;"

    def _get_status_bar_style(self):
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        border = self._get_style('border', '#3c3c3c')
        text_primary = self._get_style('text', '#e0e0e0')
        font_size = self._get_font_size('size-sm', '11px')
        return f"""
            QFrame#protocol_status_bar {{
                background-color: {bg_tertiary};
                border-top: 1px solid {border};
            }}
            QLabel {{
                color: {text_primary};
                font-size: {font_size};
            }}
        """

    # ========== UI 构建 ==========
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 顶部：连接配置区
        main_layout.addWidget(self._create_connection_panel())

        # 中部：接收区与发送区（垂直分割，接收在上发送在下）
        splitter = self._create_io_panels()
        main_layout.addWidget(splitter, 1)

        # 底部：状态栏
        main_layout.addWidget(self._create_status_bar())

        # 默认刷新一次样式
        self.refresh_theme_styles()

    def _create_connection_panel(self):
        group = QGroupBox("连接配置")
        group.setStyleSheet(self._get_group_box_style())
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        text_primary = self._get_style('text', '#ffffff')
        font_size = self._get_font_size('size-md', '12px')
        label_style = f"color: {text_primary}; font-size: {font_size}; font-weight: 500;"

        # 连接类型
        type_label = QLabel("类型:")
        type_label.setStyleSheet(label_style)
        type_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(type_label)

        self.conn_type_combo = QComboBox()
        self.conn_type_combo.addItems(["串口", "TCP客户端", "TCP服务端"])
        self.conn_type_combo.setStyleSheet(self._get_combo_box_style())
        self.conn_type_combo.currentIndexChanged.connect(self._on_conn_type_changed)
        layout.addWidget(self.conn_type_combo)

        # 串口相关控件
        self.port_label = QLabel("串口:")
        self.port_label.setStyleSheet(label_style)
        self.port_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.port_label)

        self.serial_port_combo = QComboBox()
        self.serial_port_combo.setStyleSheet(self._get_combo_box_style())
        self.serial_port_combo.setMinimumWidth(120)
        layout.addWidget(self.serial_port_combo)

        self.refresh_port_btn = QPushButton("刷新")
        self.refresh_port_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.refresh_port_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.refresh_port_btn.clicked.connect(self._on_refresh_ports)
        layout.addWidget(self.refresh_port_btn)

        self.baud_label = QLabel("波特率:")
        self.baud_label.setStyleSheet(label_style)
        self.baud_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.baud_label)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(_BAUD_RATES)
        self.baud_combo.setStyleSheet(self._get_combo_box_style())
        self.baud_combo.setMinimumWidth(100)
        layout.addWidget(self.baud_combo)

        # TCP 相关控件
        self.host_label = QLabel("主机:")
        self.host_label.setStyleSheet(label_style)
        self.host_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.host_label)

        self.host_input = QLineEdit()
        self.host_input.setText("127.0.0.1")
        self.host_input.setStyleSheet(self._get_line_edit_style())
        self.host_input.setMinimumWidth(120)
        layout.addWidget(self.host_input)

        self.port_input_label = QLabel("端口:")
        self.port_input_label.setStyleSheet(label_style)
        self.port_input_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.port_input_label)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(self.config.get('settings', {}).get('default_tcp_port', 8080))
        self.port_spin.setStyleSheet(self._get_spinbox_style())
        layout.addWidget(self.port_spin)

        # 弹性间隔
        layout.addStretch()

        # 连接/断开按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setStyleSheet(self._get_button_css('button-success'))
        self.connect_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.connect_btn.setMinimumWidth(80)
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self.connect_btn)

        # 设置默认波特率
        default_baud = str(self.config.get('settings', {}).get('default_baud', 115200))
        idx = self.baud_combo.findText(default_baud)
        if idx >= 0:
            self.baud_combo.setCurrentIndex(idx)

        # 初始填充串口列表
        self._on_refresh_ports()

        # 保存需要刷新样式的控件引用
        self._style_widgets = {
            'conn_type_combo': self.conn_type_combo,
            'serial_port_combo': self.serial_port_combo,
            'baud_combo': self.baud_combo,
            'host_input': self.host_input,
            'port_spin': self.port_spin,
        }

        return group

    def _create_io_panels(self):
        from PyQt6.QtWidgets import QSplitter
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(4)

        # 接收区
        recv_widget = QWidget()
        recv_layout = QVBoxLayout(recv_widget)
        recv_layout.setContentsMargins(0, 0, 0, 0)
        recv_layout.setSpacing(2)
        recv_layout.addLayout(self._create_recv_toolbar())
        self.recv_text = QPlainTextEdit()
        self.recv_text.setReadOnly(True)
        self.recv_text.setMaximumBlockCount(10000)
        self.recv_text.setStyleSheet(self._get_plain_text_edit_style(read_only=True))
        recv_layout.addWidget(self.recv_text)
        splitter.addWidget(recv_widget)

        # 寄存器操作区（Get/Put 方式，位于接收区与发送区之间）
        register_panel = self._create_register_panel()
        register_panel.setMaximumHeight(72)
        splitter.addWidget(register_panel)

        # 发送区
        send_widget = QWidget()
        send_layout = QVBoxLayout(send_widget)
        send_layout.setContentsMargins(0, 0, 0, 0)
        send_layout.setSpacing(2)
        # 先创建发送文本框，再创建工具栏：工具栏默认勾选 Hex发送 会立即触发
        # _on_send_hex_toggled 访问 send_text，必须保证控件已存在
        self.send_text = HexPlainTextEdit()
        self.send_text.setStyleSheet(self._get_plain_text_edit_style(read_only=False))
        self.send_text.setPlaceholderText("输入要发送的内容（字符串或十六进制，如 01 03 00 01）...")
        send_layout.addLayout(self._create_send_toolbar())
        send_layout.addWidget(self.send_text)
        splitter.addWidget(send_widget)

        # 接收区占最大比例，寄存器区固定高度，发送区适中
        splitter.setStretchFactor(0, 3)  # 接收区
        splitter.setStretchFactor(1, 0)  # 寄存器区（不拉伸）
        splitter.setStretchFactor(2, 2)  # 发送区
        splitter.setSizes([300, 55, 200])

        return splitter

    # ==================================================================
    # 寄存器操作面板：Get/Put 方式
    # 通过 Modbus 协议组件封装报文后发送，与"直接发送"方式独立
    # ==================================================================
    def _create_register_panel(self):
        """寄存器操作面板（从站地址、功能码、寄存器地址、数量/值、Get/Put按钮）"""
        group = QGroupBox("寄存器操作")
        group.setStyleSheet(self._get_group_box_style())
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        text_primary = self._get_style('text', '#ffffff')
        font_size = self._get_font_size('size-md', '12px')
        label_style = f"color: {text_primary}; font-size: {font_size}; font-weight: 500;"

        # 1. 从站地址
        slave_label = QLabel("从站:")
        slave_label.setStyleSheet(label_style)
        slave_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slave_label.setMinimumWidth(45)
        layout.addWidget(slave_label)
        self.reg_slave_spin = QSpinBox()
        self.reg_slave_spin.setRange(1, 247)
        self.reg_slave_spin.setValue(1)
        self.reg_slave_spin.setMinimumWidth(70)
        self.reg_slave_spin.setStyleSheet(self._get_spinbox_style())
        layout.addWidget(self.reg_slave_spin)

        # 2. 功能码
        func_label = QLabel("功能:")
        func_label.setStyleSheet(label_style)
        func_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        func_label.setMinimumWidth(45)
        layout.addWidget(func_label)
        self.reg_func_combo = QComboBox()
        for code, name in sorted(FUNC_NAMES.items()):
            self.reg_func_combo.addItem(name, code)
        self.reg_func_combo.setStyleSheet(self._get_combo_box_style())
        self.reg_func_combo.setMinimumWidth(140)
        self.reg_func_combo.currentIndexChanged.connect(self._on_reg_func_changed)
        layout.addWidget(self.reg_func_combo)

        # 3. 寄存器地址（支持 16进制 0x1A / 1Ah / 十进制 26）
        addr_label = QLabel("地址:")
        addr_label.setStyleSheet(label_style)
        addr_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        addr_label.setMinimumWidth(45)
        layout.addWidget(addr_label)
        self.reg_addr_input = QLineEdit()
        self.reg_addr_input.setPlaceholderText("0x1A 或 26")
        self.reg_addr_input.setText("0")
        self.reg_addr_input.setMinimumWidth(90)
        self.reg_addr_input.setStyleSheet(self._get_line_edit_style())
        layout.addWidget(self.reg_addr_input)

        # 4. 数量（读操作使用）
        self.reg_qty_label = QLabel("数量:")
        self.reg_qty_label.setStyleSheet(label_style)
        self.reg_qty_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.reg_qty_label.setMinimumWidth(45)
        layout.addWidget(self.reg_qty_label)
        self.reg_qty_spin = QSpinBox()
        self.reg_qty_spin.setRange(1, 2000)
        self.reg_qty_spin.setValue(1)
        self.reg_qty_spin.setMinimumWidth(70)
        self.reg_qty_spin.setStyleSheet(self._get_spinbox_style())
        layout.addWidget(self.reg_qty_spin)

        # 5. 值（写操作使用 + 读操作结果显示）
        self.reg_value_label = QLabel("值:")
        self.reg_value_label.setStyleSheet(label_style)
        self.reg_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.reg_value_label.setMinimumWidth(35)
        layout.addWidget(self.reg_value_label)
        self.reg_value_input = QLineEdit()
        self.reg_value_input.setPlaceholderText("写入值或读取结果")
        self.reg_value_input.setMinimumWidth(150)
        self.reg_value_input.setStyleSheet(self._get_line_edit_style())
        layout.addWidget(self.reg_value_input)

        # 6. Get / Put 按钮
        self.reg_get_btn = QPushButton("Get")
        self.reg_get_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.reg_get_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reg_get_btn.setMinimumWidth(60)
        self.reg_get_btn.clicked.connect(self._on_reg_get)
        layout.addWidget(self.reg_get_btn)

        self.reg_put_btn = QPushButton("Put")
        self.reg_put_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.reg_put_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reg_put_btn.setMinimumWidth(60)
        self.reg_put_btn.clicked.connect(self._on_reg_put)
        layout.addWidget(self.reg_put_btn)

        # 初始化：根据当前功能码切换 数量/值 显示
        QTimer.singleShot(0, self._on_reg_func_changed)
        return group

    def _on_reg_func_changed(self):
        """寄存器功能码变化：读操作显示"数量"，写操作显示"值"输入"""
        func_code = self.reg_func_combo.currentData()
        if func_code is None:
            return
        # 功能码 0x01~0x04 为"读"，显示数量；其余为"写"，显示值
        is_read = 0x01 <= func_code <= 0x04
        self.reg_qty_label.setVisible(is_read)
        self.reg_qty_spin.setVisible(is_read)
        # 写操作显示值输入；读操作也保留值输入（用于显示单寄存器读取结果）
        self.reg_value_label.setVisible(not is_read or True)
        self.reg_value_input.setVisible(not is_read or True)

    def _parse_reg_addr(self, text):
        """解析寄存器地址字符串为 int（支持 0x1A / 1Ah / 26 格式）

        返回 (address_int, None) 成功；或 (None, 错误信息) 失败。
        """
        s = text.strip()
        if not s:
            return None, "寄存器地址不能为空"
        lower = s.lower()
        try:
            if lower.startswith('0x'):
                return int(lower, 16), None
            if lower.endswith('h'):
                return int(lower[:-1], 16), None
            # 默认为十进制
            return int(s, 10), None
        except ValueError:
            return None, f"寄存器地址格式错误：{text}"

    def _current_modbus_protocol(self):
        """根据连接类型返回当前使用的 Modbus 协议实例：串口→RTU，TCP→TCP"""
        idx = self.conn_type_combo.currentIndex()
        if idx == _CONN_SERIAL:
            return self.modbus_rtu
        return self.modbus_tcp  # TCP Client/Server 都用 TCP 头

    def _send_bytes_via_connection(self, data: bytes):
        """通过当前连接发送字节数据，同时在接收区打印 SEND 日志"""
        if self._connection is None or not self._connection.is_connected():
            self._show_error("未连接，无法发送寄存器请求")
            return False
        try:
            self._connection.send_cmd(data)
        except Exception as e:
            self._show_error(f"发送失败：{e}")
            return False
        self._tx_bytes = self._connection.get_tx_bytes()
        # 在接收区显示 SEND 日志（与直接发送一致的格式：时间戳 + SEND : + hex）
        formatted = self._format_send(data)
        self.recv_text.moveCursor(QTextCursor.MoveOperation.End)
        self.recv_text.insertPlainText(formatted)
        self.recv_text.ensureCursorVisible()
        self._update_status()
        return True

    def _on_reg_get(self):
        """Get 按钮：构造读请求报文发送"""
        slave = self.reg_slave_spin.value()
        func_code = self.reg_func_combo.currentData()
        addr, err = self._parse_reg_addr(self.reg_addr_input.text())
        if err:
            self._show_error(err)
            return
        qty = self.reg_qty_spin.value()

        if not (0x01 <= func_code <= 0x04):
            self._show_error("当前功能码不是读操作，请使用 Put")
            return

        protocol = self._current_modbus_protocol()
        try:
            data = protocol.build_request(func_code, addr, quantity=qty, slave_id=slave)
        except Exception as e:
            self._show_error(f"构造读请求失败：{e}")
            return

        # 缓存请求信息，以便收到响应时解析 & 回填（qty==1 时回填 value）
        self._pending_reg_read = True
        self._pending_reg_func = func_code
        self._pending_reg_qty = qty

        if not self._send_bytes_via_connection(data):
            return

    def _on_reg_put(self):
        """Put 按钮：构造写请求报文发送"""
        slave = self.reg_slave_spin.value()
        func_code = self.reg_func_combo.currentData()
        addr, err = self._parse_reg_addr(self.reg_addr_input.text())
        if err:
            self._show_error(err)
            return

        protocol = self._current_modbus_protocol()

        # 线圈类写操作（0x05 / 0x0F）：值可以是 0/1 或 0x...，多个时用逗号或空格分隔
        # 寄存器类写操作（0x06 / 0x10）：单写读取 value；多写读取 value + 数量
        if func_code == 0x05:  # 写单个线圈
            raw = self.reg_value_input.text().strip()
            coil_val = raw.lower() in ('1', 'true', 'on', '0xff', '0xff00')
            try:
                data = protocol.build_request(func_code, addr, values=[coil_val], slave_id=slave)
            except Exception as e:
                self._show_error(f"构造写线圈请求失败：{e}")
                return
        elif func_code == 0x0F:  # 写多个线圈
            raw = self.reg_value_input.text().strip()
            import re as _re
            bits_text = _re.split(r'[,\s]+', raw)
            bits = []
            for t in bits_text:
                if not t:
                    continue
                bits.append(t.lower() in ('1', 'true', 'on', '0xff'))
            if not bits:
                self._show_error("写多个线圈需要在值中输入 0/1 序列（逗号或空格分隔）")
                return
            try:
                data = protocol.build_request(func_code, addr, values=bits, slave_id=slave)
            except Exception as e:
                self._show_error(f"构造写多线圈请求失败：{e}")
                return
        elif func_code == 0x06:  # 写单个寄存器
            raw = self.reg_value_input.text().strip()
            try:
                val, _ = self._parse_reg_addr(raw) if ('x' in raw.lower() or raw.lower().endswith('h')) else (int(raw, 10), None)
            except Exception:
                val = None
            if val is None:
                self._show_error("写单个寄存器需要输入合法的数值或十六进制")
                return
            try:
                data = protocol.build_request(func_code, addr, values=[val], slave_id=slave)
            except Exception as e:
                self._show_error(f"构造写单寄存器请求失败：{e}")
                return
        elif func_code == 0x10:  # 写多个寄存器
            qty = self.reg_qty_spin.value()
            raw = self.reg_value_input.text().strip()
            import re as _re2
            parts = _re2.split(r'[,\s]+', raw)
            values = []
            for p in parts:
                if not p:
                    continue
                try:
                    if 'x' in p.lower() or p.lower().endswith('h'):
                        v, _ = self._parse_reg_addr(p)
                    else:
                        v = int(p, 10)
                    values.append(v)
                except Exception:
                    self._show_error(f"寄存器值格式错误：{p}")
                    return
            if not values:
                self._show_error("写多个寄存器需要输入值序列（逗号或空格分隔）")
                return
            if len(values) != qty:
                self._show_error(f"输入的寄存器值数量 {len(values)} 与设定数量 {qty} 不一致")
                return
            try:
                data = protocol.build_request(func_code, addr, values=values, quantity=qty, slave_id=slave)
            except Exception as e:
                self._show_error(f"构造写多寄存器请求失败：{e}")
                return
        else:
            self._show_error("当前功能码不支持写操作，请使用 Get")
            return

        self._pending_reg_read = False
        self._pending_reg_func = func_code
        self._pending_reg_qty = 0

        self._send_bytes_via_connection(data)

    # ==================================================================

    def _make_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(self._get_label_style())
        return lbl

    def _create_recv_toolbar(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.recv_clear_btn = QPushButton("清空")
        self.recv_clear_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.recv_clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.recv_clear_btn.clicked.connect(self._on_recv_clear)
        layout.addWidget(self.recv_clear_btn)

        self.recv_save_btn = QPushButton("保存日志")
        self.recv_save_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.recv_save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.recv_save_btn.clicked.connect(self._on_save_log)
        layout.addWidget(self.recv_save_btn)

        layout.addStretch()

        self.recv_hex_chk = QCheckBox("Hex显示")
        self.recv_hex_chk.setStyleSheet(self._get_checkbox_style())
        self.recv_hex_chk.setChecked(True)  # 默认 Hex 显示
        self.recv_hex_chk.toggled.connect(self._update_status)
        layout.addWidget(self.recv_hex_chk)

        self.recv_timestamp_chk = QCheckBox("时间戳")
        self.recv_timestamp_chk.setStyleSheet(self._get_checkbox_style())
        self.recv_timestamp_chk.setChecked(True)
        layout.addWidget(self.recv_timestamp_chk)

        layout.addWidget(self._make_label("分隔:"))
        self.recv_sep_combo = QComboBox()
        self.recv_sep_combo.addItems(["无", "空格", "换行"])
        self.recv_sep_combo.setCurrentIndex(_SEP_NEWLINE)
        self.recv_sep_combo.setStyleSheet(self._get_combo_box_style())
        self.recv_sep_combo.setMinimumWidth(70)
        layout.addWidget(self.recv_sep_combo)

        layout.addStretch()
        layout.addWidget(self._make_label("接收区"))
        return layout

    def _create_send_toolbar(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.send_hex_chk = QCheckBox("Hex发送")
        self.send_hex_chk.setStyleSheet(self._get_checkbox_style())
        self.send_hex_chk.toggled.connect(self._on_send_hex_toggled)
        self.send_hex_chk.setChecked(True)  # 默认 Hex 发送（在 connect 之后，触发初始化）
        layout.addWidget(self.send_hex_chk)

        layout.addWidget(self._make_label("CRC:"))
        self.crc_combo = QComboBox()
        self.crc_combo.addItems(["无", "CRC-16/MODBUS"])
        self.crc_combo.setStyleSheet(self._get_combo_box_style())
        self.crc_combo.setMinimumWidth(130)
        layout.addWidget(self.crc_combo)

        self.add_crc_btn = QPushButton("添加CRC")
        self.add_crc_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.add_crc_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_crc_btn.clicked.connect(self._on_add_crc)
        layout.addWidget(self.add_crc_btn)

        self.send_clear_btn = QPushButton("清空")
        self.send_clear_btn.setStyleSheet(self._get_button_css('button-secondary'))
        self.send_clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.send_clear_btn.clicked.connect(self._on_send_clear)
        layout.addWidget(self.send_clear_btn)

        layout.addStretch()

        layout.addWidget(self._make_label("定时(ms):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 60000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setValue(1000)
        self.interval_spin.setStyleSheet(self._get_spinbox_style())
        layout.addWidget(self.interval_spin)

        self.auto_send_chk = QCheckBox("定时发送")
        self.auto_send_chk.setStyleSheet(self._get_checkbox_style())
        self.auto_send_chk.toggled.connect(self._on_auto_send_toggled)
        layout.addWidget(self.auto_send_chk)

        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(self._get_button_css('button'))
        self.send_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.send_btn.setMinimumWidth(80)
        self.send_btn.clicked.connect(self._on_send)
        layout.addWidget(self.send_btn)

        layout.addStretch()
        layout.addWidget(self._make_label("发送区"))
        return layout

    def _create_status_bar(self):
        frame = QFrame()
        frame.setObjectName('protocol_status_bar')
        frame.setStyleSheet(self._get_status_bar_style())
        frame.setFixedHeight(26)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(12)

        self.rx_label = QLabel("接收: 0 字节")
        self.tx_label = QLabel("发送: 0 字节")
        self.conn_status_label = QLabel("状态: 未连接")
        self.auto_status_label = QLabel("定时: 关闭")

        for lbl in (self.rx_label, self.tx_label, self.conn_status_label, self.auto_status_label):
            layout.addWidget(lbl)
        layout.addStretch()
        return frame

    # ========== 主题刷新 ==========
    def refresh_theme_styles(self):
        """主题切换时刷新所有控件样式"""
        if not hasattr(self, '_style_widgets'):
            return
        # GroupBox
        for group in self.findChildren(QGroupBox):
            group.setStyleSheet(self._get_group_box_style())
        # ComboBox
        combo_style = self._get_combo_box_style()
        for combo in self.findChildren(QComboBox):
            combo.setStyleSheet(combo_style)
        # LineEdit
        line_style = self._get_line_edit_style()
        for le in self.findChildren(QLineEdit):
            le.setStyleSheet(line_style)
        # SpinBox
        spin_style = self._get_spinbox_style()
        for sb in self.findChildren(QSpinBox):
            sb.setStyleSheet(spin_style)
        # CheckBox
        chk_style = self._get_checkbox_style()
        for chk in self.findChildren(QCheckBox):
            chk.setStyleSheet(chk_style)
        # 接收/发送文本框
        if hasattr(self, 'recv_text'):
            self.recv_text.setStyleSheet(self._get_plain_text_edit_style(read_only=True))
        if hasattr(self, 'send_text'):
            self.send_text.setStyleSheet(self._get_plain_text_edit_style(read_only=False))
        # 标签
        label_style = self._get_label_style()
        for lbl in self.findChildren(QLabel):
            # 状态栏标签由状态栏样式统一管理，避免覆盖
            if lbl.parent() is not None and isinstance(lbl.parent(), QFrame) and lbl.parent().objectName() == 'protocol_status_bar':
                continue
            lbl.setStyleSheet(label_style)
        # 状态栏
        for frame in self.findChildren(QFrame):
            if frame.objectName() == 'protocol_status_bar':
                frame.setStyleSheet(self._get_status_bar_style())
        # 按钮（按类型刷新）
        btn_css = self._get_button_css('button-secondary')
        for btn in self.findChildren(QPushButton):
            text = btn.text()
            if text == "发送":
                btn.setStyleSheet(self._get_button_css('button'))
            elif text == "连接":
                btn.setStyleSheet(self._get_button_css('button-success' if not self._is_connected else 'button-danger'))
                btn.setText("断开" if self._is_connected else "连接")
            else:
                btn.setStyleSheet(btn_css)

    # ========== 连接类型切换 ==========
    def _apply_conn_type_visibility(self):
        conn_type = self.conn_type_combo.currentIndex()
        self._conn_type_text = self.conn_type_combo.currentText()
        # 串口控件
        serial_widgets = [self.port_label, self.serial_port_combo, self.refresh_port_btn,
                          self.baud_label, self.baud_combo]
        # TCP 控件
        tcp_widgets = [self.host_label, self.host_input, self.port_input_label, self.port_spin]

        if conn_type == _CONN_SERIAL:
            for w in serial_widgets:
                w.show()
            for w in tcp_widgets:
                w.hide()
        elif conn_type == _CONN_TCP_CLIENT:
            for w in serial_widgets:
                w.hide()
            for w in tcp_widgets:
                w.show()
            # 客户端需要主机与端口
            self.host_label.show()
            self.host_input.show()
        else:  # TCP 服务端
            for w in serial_widgets:
                w.hide()
            # 服务端只需端口，隐藏主机
            self.host_label.hide()
            self.host_input.hide()
            self.port_input_label.show()
            self.port_spin.show()

    def _on_conn_type_changed(self, _index):
        self._apply_conn_type_visibility()
        self._update_status()

    def _on_refresh_ports(self):
        """刷新可用串口列表"""
        self.serial_port_combo.blockSignals(True)
        current = self.serial_port_combo.currentText()
        self.serial_port_combo.clear()
        ports = list_serial_ports()
        if ports:
            self.serial_port_combo.addItems(ports)
            # 尝试恢复之前选择
            idx = self.serial_port_combo.findText(current)
            if idx >= 0:
                self.serial_port_combo.setCurrentIndex(idx)
        else:
            self.serial_port_combo.addItem("（无可用串口）")
        self.serial_port_combo.blockSignals(False)

    # ========== 连接 / 断开 ==========
    def _on_connect_clicked(self):
        if self._is_connected:
            self._do_disconnect()
        else:
            self._do_connect()

    def _do_connect(self):
        conn_type = self.conn_type_combo.currentIndex()
        if conn_type == _CONN_SERIAL:
            conn = SerialConnection(self)
            port = self.serial_port_combo.currentText()
            if port in ('', '（无可用串口）'):
                self._show_error("没有可用的串口，请检查设备或刷新串口列表")
                conn.deleteLater()
                return
            baud = int(self.baud_combo.currentText())
            config = {'port': port, 'baud': baud}
        elif conn_type == _CONN_TCP_CLIENT:
            conn = TCPClientConnection(self)
            host = self.host_input.text().strip() or '127.0.0.1'
            config = {'host': host, 'port': self.port_spin.value()}
        else:
            conn = TCPServerConnection(self)
            config = {'port': self.port_spin.value()}

        # 连接信号（在 open_connection 之前连接，确保能收到内部发出的状态信号）
        conn.data_received.connect(self._on_data_received)
        conn.status_changed.connect(self._on_conn_status_changed)
        conn.error_occurred.connect(self._on_conn_error)

        if not conn.open_connection(config):
            # 失败时清理信号连接
            try:
                conn.data_received.disconnect()
                conn.status_changed.disconnect()
                conn.error_occurred.disconnect()
            except Exception:
                pass
            conn.deleteLater()
            return

        self._connection = conn
        self._is_connected = True
        self._closing = False
        self.connect_btn.setText("断开")
        self.connect_btn.setStyleSheet(self._get_button_css('button-danger'))
        self._update_status()

    def _do_disconnect(self):
        if self._connection is None:
            self._is_connected = False
            self._reset_connect_button()
            self._update_status()
            return

        self._closing = True
        # 停止定时发送
        if self.auto_send_chk.isChecked():
            self.auto_send_chk.blockSignals(True)
            self.auto_send_chk.setChecked(False)
            self.auto_send_chk.blockSignals(False)
            self._timer.stop()

        conn = self._connection
        conn.close_connection()
        try:
            conn.data_received.disconnect()
            conn.status_changed.disconnect()
            conn.error_occurred.disconnect()
        except Exception:
            pass
        self._connection = None
        conn.deleteLater()

        self._is_connected = False
        self._closing = False
        self._reset_connect_button()
        self._update_status()

    def _reset_connect_button(self):
        self.connect_btn.setText("连接")
        self.connect_btn.setStyleSheet(self._get_button_css('button-success'))

    # ========== 数据接收 ==========
    def _timestamp(self):
        """生成 [HH:MM:SS.mmm] 格式的时间戳"""
        now = datetime.now()
        return now.strftime('[%H:%M:%S.') + f'{now.microsecond // 1000:03d}]'

    def _on_data_received(self, data):
        """主线程槽：处理接收到的原始字节"""
        if not data:
            return
        self._rx_bytes += len(data)
        # 若连接对象统计了接收字节，以其为准
        if self._connection is not None:
            self._rx_bytes = self._connection.get_rx_bytes()
        formatted = self._format_recv(data)
        self.recv_text.moveCursor(QTextCursor.MoveOperation.End)
        self.recv_text.insertPlainText(formatted)
        # 滚动到末尾
        self.recv_text.ensureCursorVisible()
        self._update_status()
        # 尝试解析寄存器响应并回填（读1个寄存器时回填到值框）
        self._try_parse_and_fill_reg_response(data)

    def _format_recv(self, data):
        """将原始字节格式化为显示文本（含 Hex/字符串、时间戳、分隔符）

        显示格式：时间戳 + RECV : + 报文（与项目记忆一致，只显示收发包）
        """
        if self.recv_hex_chk.isChecked():
            text = ' '.join(f'{b:02X}' for b in data)
        else:
            text = data.decode('utf-8', errors='replace')
        prefix = ''
        if self.recv_timestamp_chk.isChecked():
            prefix = self._timestamp() + ' RECV : '
        else:
            prefix = 'RECV : '
        sep_index = self.recv_sep_combo.currentIndex()
        sep = '' if sep_index == _SEP_NONE else (' ' if sep_index == _SEP_SPACE else '\n')
        return prefix + text + sep

    def _format_send(self, data):
        """将发送字节格式化为显示文本（格式与 RECV 对称）

        显示格式：时间戳 + SEND : + 报文（只显示十六进制包）
        """
        text = ' '.join(f'{b:02X}' for b in data)
        if self.recv_timestamp_chk.isChecked():
            prefix = self._timestamp() + ' SEND : '
        else:
            prefix = 'SEND : '
        sep_index = self.recv_sep_combo.currentIndex()
        sep = '' if sep_index == _SEP_NONE else (' ' if sep_index == _SEP_SPACE else '\n')
        return prefix + text + sep

    def _try_parse_and_fill_reg_response(self, data):
        """尝试解析接收到的字节为寄存器响应，若为读操作且 qty==1 则回填 value 输入框"""
        if not getattr(self, '_pending_reg_read', False):
            return
        func_code = self._pending_reg_func
        qty = self._pending_reg_qty
        protocol = self._current_modbus_protocol()
        try:
            parsed = protocol.parse_response(data, func_code)
        except Exception:
            return  # 解析失败（可能不是响应，或异常帧），静默忽略

        # 读操作 & 数量=1 → 回填第一个值到 value 框
        values = parsed.get('values') or []
        if qty == 1 and values:
            v = values[0]
            if isinstance(v, bool):
                self.reg_value_input.setText('1' if v else '0')
            else:
                self.reg_value_input.setText(str(v))
        # 清理挂起状态
        self._pending_reg_read = False
        self._pending_reg_func = 0
        self._pending_reg_qty = 0

    def _on_conn_status_changed(self, text, connected):
        """连接状态变化：更新状态栏并记录到接收区"""
        self.conn_status_label.setText(f"状态: {text}")
        # 将状态消息记录到接收区（带时间戳与 >> 前缀）
        ts = self._timestamp()
        self.recv_text.moveCursor(QTextCursor.MoveOperation.End)
        self.recv_text.insertPlainText(f"{ts} >> {text}\n")
        self.recv_text.ensureCursorVisible()

        if not connected and not self._closing:
            # 连接意外断开，异步清理避免在信号处理中重入
            QTimer.singleShot(0, self._do_disconnect)
        else:
            self._update_status()

    def _on_conn_error(self, text):
        """致命错误：记录到接收区"""
        ts = self._timestamp()
        self.recv_text.moveCursor(QTextCursor.MoveOperation.End)
        self.recv_text.insertPlainText(f"{ts} !! {text}\n")
        self.recv_text.ensureCursorVisible()

    # ========== 数据发送 ==========
    def _parse_send_data(self):
        """解析发送区文本为字节，返回 (data, error)"""
        text = self.send_text.toPlainText()
        if self.send_hex_chk.isChecked():
            clean = ''.join(text.split())
            if not clean:
                return None, "发送内容为空"
            if len(clean) % 2 != 0:
                return None, "十六进制数据长度必须为偶数"
            try:
                data = bytes.fromhex(clean)
            except ValueError:
                return None, "十六进制格式错误（仅允许 0-9A-Fa-f）"
        else:
            if not text:
                return None, "发送内容为空"
            data = text.encode('utf-8')
        return data, None

    def _on_send(self):
        data, err = self._parse_send_data()
        if data is None:
            # 定时发送模式下静默失败，手动发送时提示
            if not self._timer.isActive() or not self.auto_send_chk.isChecked():
                self._show_error(err)
            return
        # CRC 校验：在发送前追加 CRC
        if self.crc_combo.currentIndex() == 1:
            data = append_crc16_modbus(data)
        if self._connection is None or not self._connection.is_connected():
            self._show_error("未连接，无法发送")
            return
        if self._connection.send_cmd(data):
            self._tx_bytes = self._connection.get_tx_bytes()
            # 在接收区显示 SEND 日志（与寄存器操作发送格式一致）
            formatted = self._format_send(data)
            self.recv_text.moveCursor(QTextCursor.MoveOperation.End)
            self.recv_text.insertPlainText(formatted)
            self.recv_text.ensureCursorVisible()
            self._update_status()

    def _on_add_crc(self):
        """将 CRC-16/MODBUS 校验码追加到发送区文本（仅 Hex 模式有意义）"""
        data, err = self._parse_send_data()
        if data is None:
            self._show_error(err)
            return
        crc = crc16_modbus(data)
        crc_hex = f'{crc & 0xFF:02X} {(crc >> 8) & 0xFF:02X}'
        text = self.send_text.toPlainText().rstrip()
        # 切换到 Hex 模式以便追加
        if not self.send_hex_chk.isChecked():
            self.send_hex_chk.setChecked(True)
        new_text = (text + ' ' + crc_hex) if text else crc_hex
        self.send_text.setPlainText(new_text)

    def _on_send_hex_toggled(self, checked):
        """切换发送区十六进制输入模式"""
        self.send_text.set_hex_mode(checked)
        self.send_text.setFocus()

    def _on_send_clear(self):
        """清空发送区内容"""
        self.send_text.clear()
        self.send_text.setFocus()

    def _on_auto_send_toggled(self, checked):
        if checked:
            if self._connection is None or not self._connection.is_connected():
                self._show_error("未连接，无法定时发送")
                self.auto_send_chk.blockSignals(True)
                self.auto_send_chk.setChecked(False)
                self.auto_send_chk.blockSignals(False)
                return
            self._timer.start(self.interval_spin.value())
        else:
            self._timer.stop()
        self._update_status()

    # ========== 接收区操作 ==========
    def _on_recv_clear(self):
        self.recv_text.clear()

    def _on_save_log(self):
        """保存接收区内容到日志文件"""
        content = self.recv_text.toPlainText()
        if not content:
            self._show_error("接收区为空，无内容可保存")
            return
        # 解析默认日志目录
        log_dir_rel = self.config.get('settings', {}).get('log_dir', 'logs/protocol_tool')
        if os.path.isabs(log_dir_rel):
            default_dir = log_dir_rel
        else:
            default_dir = os.path.join(_PROJECT_ROOT, log_dir_rel)
        try:
            os.makedirs(default_dir, exist_ok=True)
        except Exception:
            pass

        chosen = QFileDialog.getExistingDirectory(
            self, "选择日志保存目录", default_dir
        )
        if not chosen:
            return
        filename = f"protocol_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        filepath = os.path.join(chosen, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            ts = self._timestamp()
            self.recv_text.moveCursor(QTextCursor.MoveOperation.End)
            self.recv_text.insertPlainText(f"{ts} >> 日志已保存: {filepath}\n")
            self.recv_text.ensureCursorVisible()
        except Exception as e:
            self._show_error(f"保存日志失败: {e}")

    # ========== 状态上报 ==========
    def _update_status(self):
        """更新底部状态栏并上报主窗体状态"""
        self.rx_label.setText(f"接收: {self._rx_bytes} 字节")
        self.tx_label.setText(f"发送: {self._tx_bytes} 字节")
        if self._is_connected and self._connection is not None:
            conn_name = self._conn_type_text
            self.conn_status_label.setText(f"状态: {conn_name} 已连接")
            summary = f"{conn_name} 已连接 | RX:{self._rx_bytes} TX:{self._tx_bytes}"
        else:
            self.conn_status_label.setText("状态: 未连接")
            summary = "未连接"
        if self.auto_send_chk.isChecked() and self._timer.isActive():
            self.auto_status_label.setText(f"定时: {self.interval_spin.value()}ms")
            summary += " | 定时发送"
        else:
            self.auto_status_label.setText("定时: 关闭")
        self._report_status(summary)

    def _report_status(self, status_text):
        if self._plugin_manager_ref and hasattr(self._plugin_manager_ref, 'set_tool_status'):
            self._plugin_manager_ref.set_tool_status('ProtocolTool', status_text)

    def _show_error(self, message):
        QMessageBox.warning(self, "协议测试", message)

    # ========== 清理 ==========
    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def _cleanup(self):
        if self._timer.isActive():
            self._timer.stop()
        if self._connection is not None:
            try:
                self._connection.close_connection()
            except Exception:
                pass
            self._connection = None
