# -*- coding: utf-8 -*-
"""Modbus 协议解析组件。

采用策略模式 + 工厂模式设计：
- ``ModbusProtocol``：抽象基类（策略接口），定义封装/解析的统一接口
- ``ModbusRTUProtocol``：Modbus RTU 策略（[Slave Addr][Func][Data][CRC16]）
- ``ModbusTCPProtocol``：Modbus TCP 策略（[Txn ID][Proto ID][Len][Unit ID][Func][Data]）
- ``ModbusProtocolFactory``：工厂，按协议类型创建策略实例
- ``ModbusServerSimulator``：基于 XML 配置的从站模拟器，构造响应报文

报文构造与解析覆盖常用功能码：
    0x01 读线圈          0x02 读离散输入
    0x03 读保持寄存器     0x04 读输入寄存器
    0x05 写单个线圈       0x06 写单个寄存器
    0x0F 写多个线圈       0x10 写多个寄存器

异常响应统一使用 0x80 + 功能码，异常码通过 ``exception_code`` 字段返回。
"""

import struct
from abc import ABC, abstractmethod
from xml.etree import ElementTree as ET

from .connections import crc16_modbus


# ========== 协议常量 ==========

# 协议类型
MODBUS_RTU = 'rtu'
MODBUS_TCP = 'tcp'

# 功能码
FUNC_READ_COILS = 0x01               # 读线圈
FUNC_READ_DISCRETE_INPUTS = 0x02      # 读离散输入
FUNC_READ_HOLDING_REGISTERS = 0x03    # 读保持寄存器
FUNC_READ_INPUT_REGISTERS = 0x04     # 读输入寄存器
FUNC_WRITE_SINGLE_COIL = 0x05        # 写单个线圈
FUNC_WRITE_SINGLE_REGISTER = 0x06    # 写单个寄存器
FUNC_WRITE_MULTIPLE_COILS = 0x0F     # 写多个线圈
FUNC_WRITE_MULTIPLE_REGISTERS = 0x10 # 写多个寄存器

# 异常码
EXC_ILLEGAL_FUNCTION = 0x01          # 非法功能码
EXC_ILLEGAL_DATA_ADDRESS = 0x02      # 非法数据地址
EXC_ILLEGAL_DATA_VALUE = 0x03        # 非法数据值
EXC_SLAVE_DEVICE_FAILURE = 0x04      # 从站设备故障

# 线圈 ON 值（写单个线圈时固定 0xFF00）
COIL_ON = 0xFF00
COIL_OFF = 0x0000


# ========== 数据类型映射 ==========

# 功能码 -> (数据区是否为位、是否为读操作)
# 位操作：线圈/离散输入；字操作：保持/输入寄存器
_FUNC_IS_BIT = {
    FUNC_READ_COILS: True,
    FUNC_READ_DISCRETE_INPUTS: True,
    FUNC_READ_HOLDING_REGISTERS: False,
    FUNC_READ_INPUT_REGISTERS: False,
    FUNC_WRITE_SINGLE_COIL: True,
    FUNC_WRITE_SINGLE_REGISTER: False,
    FUNC_WRITE_MULTIPLE_COILS: True,
    FUNC_WRITE_MULTIPLE_REGISTERS: False,
}

# 功能码 -> 是否为读操作
_FUNC_IS_READ = {
    FUNC_READ_COILS: True,
    FUNC_READ_DISCRETE_INPUTS: True,
    FUNC_READ_HOLDING_REGISTERS: True,
    FUNC_READ_INPUT_REGISTERS: True,
    FUNC_WRITE_SINGLE_COIL: False,
    FUNC_WRITE_SINGLE_REGISTER: False,
    FUNC_WRITE_MULTIPLE_COILS: False,
    FUNC_WRITE_MULTIPLE_REGISTERS: False,
}


class ModbusProtocol(ABC):
    """策略接口：Modbus 协议封装与解析基类。

    子类需实现 ``_build_adu`` 与 ``_parse_adu``，负责各自的传输层封装
    （RTU 的 CRC、TCP 的 MBAP 头）。PDU（协议数据单元）部分由本基类统一处理。
    """

    def __init__(self):
        self._txn_id = 0  # Modbus TCP 事务 ID，RTU 不使用

    # ----- 公共接口 -----
    def build_request(self, func_code, start_addr, quantity=1, values=None, slave_id=1):
        """构造请求报文

        Args:
            func_code: 功能码（0x01-0x10）
            start_addr: 起始地址（0-based）
            quantity: 读/写数量（读操作为读取数量，写操作为写入数量）
            values: 写操作的值列表（线圈为 [0/1,...]，寄存器为 [int,...]）
            slave_id: 从站地址（RTU）或单元标识符（TCP）

        Returns:
            bytes：完整 ADU 报文
        """
        pdu = self._build_pdu_request(func_code, start_addr, quantity, values)
        return self._build_adu(slave_id, pdu)

    def build_response(self, func_code, slave_id, values=None, txn_id=None, exception_code=None):
        """构造响应报文（server 端使用）

        Args:
            func_code: 功能码
            slave_id: 从站地址/单元标识符
            values: 响应数据列表（读操作返回的数据）
            txn_id: Modbus TCP 事务 ID（None 时使用内部自增计数）
            exception_code: 异常码（非 None 时构造异常响应）

        Returns:
            bytes：完整 ADU 报文
        """
        pdu = self._build_pdu_response(func_code, values, exception_code)
        return self._build_adu(slave_id, pdu, txn_id=txn_id)

    def parse(self, adu):
        """解析报文（请求或响应均可）

        Args:
            adu: 完整 ADU 字节串

        Returns:
            dict：解析结果，包含：
                - protocol: 'rtu' / 'tcp'
                - slave_id / unit_id
                - func_code: 原始功能码
                - is_exception: 是否异常响应
                - exception_code: 异常码（异常时）
                - data: 解析出的数据（地址/数量/值等，结构因功能码而异）
                - txn_id: 事务 ID（仅 TCP）
                - valid: 校验是否通过
                - error: 错误信息（校验失败时）
        """
        return self._parse_adu(adu)

    # ----- PDU 构造（基类统一处理）-----
    def _build_pdu_request(self, func_code, start_addr, quantity, values):
        """构造请求 PDU"""
        if func_code in (FUNC_READ_COILS, FUNC_READ_DISCRETE_INPUTS,
                         FUNC_READ_HOLDING_REGISTERS, FUNC_READ_INPUT_REGISTERS):
            # 读请求：[Func(1)][Start Addr(2)][Quantity(2)]
            return struct.pack('>BHH', func_code, start_addr, quantity)

        if func_code == FUNC_WRITE_SINGLE_COIL:
            # 写单个线圈：[Func(1)][Addr(2)][Value(2)]  ON=0xFF00 OFF=0x0000
            value = COIL_ON if (values and values[0]) else COIL_OFF
            return struct.pack('>BHH', func_code, start_addr, value)

        if func_code == FUNC_WRITE_SINGLE_REGISTER:
            # 写单个寄存器：[Func(1)][Addr(2)][Value(2)]
            value = values[0] if values else 0
            return struct.pack('>BHH', func_code, start_addr, value)

        if func_code == FUNC_WRITE_MULTIPLE_COILS:
            # 写多个线圈：[Func(1)][Start Addr(2)][Quantity(2)][Byte Count(1)][Data(N)]
            byte_count = (len(values) + 7) // 8
            data_bytes = bytearray(byte_count)
            for i, v in enumerate(values):
                if v:
                    data_bytes[i // 8] |= (1 << (i % 8))
            return struct.pack('>BHHB', func_code, start_addr, len(values), byte_count) + bytes(data_bytes)

        if func_code == FUNC_WRITE_MULTIPLE_REGISTERS:
            # 写多个寄存器：[Func(1)][Start Addr(2)][Quantity(2)][Byte Count(1)][Data(N*2)]
            byte_count = len(values) * 2
            data = b''.join(struct.pack('>H', v) for v in values)
            return struct.pack('>BHHB', func_code, start_addr, len(values), byte_count) + data

        raise ValueError(f"不支持的功能码: 0x{func_code:02X}")

    def _build_pdu_response(self, func_code, values, exception_code):
        """构造响应 PDU"""
        # 异常响应：[Func | 0x80(1)][Exception Code(1)]
        if exception_code is not None:
            return struct.pack('>BB', func_code | 0x80, exception_code)

        if func_code in (FUNC_READ_COILS, FUNC_READ_DISCRETE_INPUTS):
            # 读位响应：[Func(1)][Byte Count(1)][Data(N)]
            byte_count = (len(values) + 7) // 8
            data_bytes = bytearray(byte_count)
            for i, v in enumerate(values):
                if v:
                    data_bytes[i // 8] |= (1 << (i % 8))
            return struct.pack('>BB', func_code, byte_count) + bytes(data_bytes)

        if func_code in (FUNC_READ_HOLDING_REGISTERS, FUNC_READ_INPUT_REGISTERS):
            # 读字响应：[Func(1)][Byte Count(1)][Data(N*2)]
            byte_count = len(values) * 2
            data = b''.join(struct.pack('>H', v) for v in values)
            return struct.pack('>BB', func_code, byte_count) + data

        if func_code == FUNC_WRITE_SINGLE_COIL:
            # 写单个线圈响应（回显请求）：[Func(1)][Addr(2)][Value(2)]
            addr = values[0] if values else 0
            val = values[1] if len(values) > 1 else COIL_OFF
            return struct.pack('>BHH', func_code, addr, val)

        if func_code == FUNC_WRITE_SINGLE_REGISTER:
            # 写单个寄存器响应（回显请求）：[Func(1)][Addr(2)][Value(2)]
            addr = values[0] if values else 0
            val = values[1] if len(values) > 1 else 0
            return struct.pack('>BHH', func_code, addr, val)

        if func_code == FUNC_WRITE_MULTIPLE_COILS:
            # 写多个线圈响应：[Func(1)][Start Addr(2)][Quantity(2)]
            addr = values[0] if values else 0
            qty = values[1] if len(values) > 1 else 0
            return struct.pack('>BHH', func_code, addr, qty)

        if func_code == FUNC_WRITE_MULTIPLE_REGISTERS:
            # 写多个寄存器响应：[Func(1)][Start Addr(2)][Quantity(2)]
            addr = values[0] if values else 0
            qty = values[1] if len(values) > 1 else 0
            return struct.pack('>BHH', func_code, addr, qty)

        raise ValueError(f"不支持的功能码: 0x{func_code:02X}")

    def _parse_pdu(self, func_code, pdu, is_request):
        """解析 PDU 数据区（基类统一处理）

        Args:
            func_code: 功能码（已去除异常标志）
            pdu: PDU 数据区（功能码之后的部分）
            is_request: True=请求报文，False=响应报文

        Returns:
            dict：解析出的数据
        """
        # 读请求：[Start Addr(2)][Quantity(2)]
        if is_request and func_code in (FUNC_READ_COILS, FUNC_READ_DISCRETE_INPUTS,
                                        FUNC_READ_HOLDING_REGISTERS, FUNC_READ_INPUT_REGISTERS):
            addr, qty = struct.unpack('>HH', pdu[:4])
            return {'start_address': addr, 'quantity': qty}

        # 写单个线圈/寄存器请求：[Addr(2)][Value(2)]
        if is_request and func_code in (FUNC_WRITE_SINGLE_COIL, FUNC_WRITE_SINGLE_REGISTER):
            addr, value = struct.unpack('>HH', pdu[:4])
            if func_code == FUNC_WRITE_SINGLE_COIL:
                return {'start_address': addr, 'value': 1 if value == COIL_ON else 0}
            return {'start_address': addr, 'value': value}

        # 写多个线圈/寄存器请求：[Start Addr(2)][Quantity(2)][Byte Count(1)][Data]
        if is_request and func_code in (FUNC_WRITE_MULTIPLE_COILS, FUNC_WRITE_MULTIPLE_REGISTERS):
            addr, qty, byte_count = struct.unpack('>HHB', pdu[:5])
            data = pdu[5:5 + byte_count]
            if func_code == FUNC_WRITE_MULTIPLE_COILS:
                values = [(data[i // 8] >> (i % 8)) & 1 for i in range(qty)]
            else:
                values = list(struct.unpack(f'>{qty}H', data[:qty * 2]))
            return {'start_address': addr, 'quantity': qty, 'values': values}

        # 读位响应：[Byte Count(1)][Data(N)]
        if not is_request and func_code in (FUNC_READ_COILS, FUNC_READ_DISCRETE_INPUTS):
            byte_count = pdu[0]
            data = pdu[1:1 + byte_count]
            qty = byte_count * 8  # 最多，实际由上层 quantity 截断
            values = [(data[i // 8] >> (i % 8)) & 1 for i in range(qty)]
            return {'values': values}

        # 读字响应：[Byte Count(1)][Data(N*2)]
        if not is_request and func_code in (FUNC_READ_HOLDING_REGISTERS, FUNC_READ_INPUT_REGISTERS):
            byte_count = pdu[0]
            data = pdu[1:1 + byte_count]
            count = byte_count // 2
            values = list(struct.unpack(f'>{count}H', data))
            return {'values': values}

        # 写单个线圈/寄存器响应（回显）：[Addr(2)][Value(2)]
        if not is_request and func_code in (FUNC_WRITE_SINGLE_COIL, FUNC_WRITE_SINGLE_REGISTER):
            addr, value = struct.unpack('>HH', pdu[:4])
            if func_code == FUNC_WRITE_SINGLE_COIL:
                return {'start_address': addr, 'value': 1 if value == COIL_ON else 0}
            return {'start_address': addr, 'value': value}

        # 写多个线圈/寄存器响应：[Start Addr(2)][Quantity(2)]
        if not is_request and func_code in (FUNC_WRITE_MULTIPLE_COILS, FUNC_WRITE_MULTIPLE_REGISTERS):
            addr, qty = struct.unpack('>HH', pdu[:4])
            return {'start_address': addr, 'quantity': qty}

        return {'raw': pdu.hex().upper()}

    # ----- 子类实现的传输层封装 -----
    @abstractmethod
    def _build_adu(self, slave_id, pdu, txn_id=None):
        """将 PDU 封装为完整 ADU"""

    @abstractmethod
    def _parse_adu(self, adu):
        """解析完整 ADU，返回解析结果字典"""

    @abstractmethod
    def get_protocol_type(self):
        """返回协议类型标识"""


class ModbusRTUProtocol(ModbusProtocol):
    """Modbus RTU 策略

    帧格式：[Slave Address(1)][Function Code(1)][Data][CRC16(2, 低字节在前)]
    """

    def get_protocol_type(self):
        return MODBUS_RTU

    def _build_adu(self, slave_id, pdu, txn_id=None):
        # RTU 不使用事务 ID
        frame = bytes([slave_id]) + pdu
        crc = crc16_modbus(frame)
        # CRC 低字节在前
        return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    def _parse_adu(self, adu):
        if len(adu) < 4:
            return {'protocol': MODBUS_RTU, 'valid': False, 'error': '报文过短（RTU 最小 4 字节）'}

        # 校验 CRC
        frame = adu[:-2]
        crc_recv = (adu[-2] | (adu[-1] << 8))
        crc_calc = crc16_modbus(frame)
        if crc_recv != crc_calc:
            return {
                'protocol': MODBUS_RTU,
                'valid': False,
                'error': f'CRC 校验失败：接收 0x{crc_recv:04X}，计算 0x{crc_calc:04X}',
            }

        slave_id = adu[0]
        func_byte = adu[1]
        is_exception = bool(func_byte & 0x80)
        func_code = func_byte & 0x7F
        pdu = adu[1:-2]  # 功能码 + 数据区

        result = {
            'protocol': MODBUS_RTU,
            'slave_id': slave_id,
            'func_code': func_byte,
            'is_exception': is_exception,
            'valid': True,
        }

        if is_exception:
            result['exception_code'] = pdu[1] if len(pdu) > 1 else 0
            result['data'] = {'exception': _EXCEPTION_NAMES.get(pdu[1], f'0x{pdu[1]:02X}')}
            return result

        # 判断是请求还是响应：依据功能码与数据区长度启发判断
        is_request = self._guess_is_request(func_code, pdu[1:])
        result['direction'] = 'request' if is_request else 'response'
        result['data'] = self._parse_pdu(func_code, pdu[1:], is_request)
        return result

    @staticmethod
    def _guess_is_request(func_code, data):
        """启发式判断报文方向（无上下文时无法精确区分请求/响应）

        规则：
        - 读功能码(0x01-0x04)：请求为 4 字节(addr+qty)，响应以 byte_count 开头
        - 写功能码(0x05/0x06)：请求与响应均为 4 字节，无法区分，默认按请求处理
        - 写多个(0x0F/0x10)：请求含 byte_count 字段，响应为 4 字节
        """
        if func_code in (FUNC_READ_COILS, FUNC_READ_DISCRETE_INPUTS,
                         FUNC_READ_HOLDING_REGISTERS, FUNC_READ_INPUT_REGISTERS):
            # 请求：[addr(2)][qty(2)] = 4 字节
            # 响应：[byte_count(1)][data...] >= 2 字节，byte_count == len(data)
            if len(data) == 4:
                return True
            if len(data) >= 2 and data[0] == len(data) - 1:
                return False
            return True

        if func_code in (FUNC_WRITE_SINGLE_COIL, FUNC_WRITE_SINGLE_REGISTER):
            # 请求与响应相同，默认请求
            return True

        if func_code in (FUNC_WRITE_MULTIPLE_COILS, FUNC_WRITE_MULTIPLE_REGISTERS):
            # 请求：[addr(2)][qty(2)][byte_count(1)][data]
            # 响应：[addr(2)][qty(2)] = 4 字节
            if len(data) >= 5 and data[2] == len(data) - 3:
                return True
            if len(data) == 4:
                return False
            return True

        return True


class ModbusTCPProtocol(ModbusProtocol):
    """Modbus TCP 策略

    帧格式：[Transaction ID(2)][Protocol ID(2=0x0000)][Length(2)][Unit ID(1)][PDU]
    Length = Unit ID(1) + PDU 长度
    """

    def get_protocol_type(self):
        return MODBUS_TCP

    def _next_txn_id(self):
        """生成自增事务 ID"""
        self._txn_id = (self._txn_id + 1) & 0xFFFF
        return self._txn_id

    def _build_adu(self, slave_id, pdu, txn_id=None):
        if txn_id is None:
            txn_id = self._next_txn_id()
        # MBAP 头：[Txn ID(2)][Proto ID(2=0x0000)][Length(2)][Unit ID(1)]
        # Length = Unit ID(1) + PDU 长度
        length = 1 + len(pdu)
        header = struct.pack('>HHH', txn_id, 0x0000, length) + bytes([slave_id & 0xFF])
        return header + pdu

    def _parse_adu(self, adu):
        if len(adu) < 8:
            return {'protocol': MODBUS_TCP, 'valid': False, 'error': '报文过短（TCP 最小 8 字节）'}

        txn_id, proto_id, length = struct.unpack('>HHH', adu[:6])
        unit_id = adu[6]
        func_byte = adu[7]
        pdu = adu[7:7 + length - 1]  # 功能码 + 数据区

        result = {
            'protocol': MODBUS_TCP,
            'txn_id': txn_id,
            'unit_id': unit_id,
            'func_code': func_byte,
            'is_exception': bool(func_byte & 0x80),
            'proto_id': proto_id,
            'length': length,
            'valid': True,
        }

        # 校验 Protocol ID 必须为 0
        if proto_id != 0:
            result['valid'] = False
            result['error'] = f'Protocol ID 不为 0：0x{proto_id:04X}'
            return result

        # 校验 Length 字段
        if length != len(adu) - 6:
            result['valid'] = False
            result['error'] = f'Length 字段不匹配：声明 {length}，实际 {len(adu) - 6}'
            return result

        is_exception = bool(func_byte & 0x80)
        func_code = func_byte & 0x7F

        if is_exception:
            result['exception_code'] = pdu[1] if len(pdu) > 1 else 0
            result['data'] = {'exception': _EXCEPTION_NAMES.get(pdu[1], f'0x{pdu[1]:02X}')}
            return result

        is_request = self._guess_is_request(func_code, pdu[1:])
        result['direction'] = 'request' if is_request else 'response'
        result['data'] = self._parse_pdu(func_code, pdu[1:], is_request)
        return result

    @staticmethod
    def _guess_is_request(func_code, data):
        """与 RTU 相同的启发式判断逻辑"""
        return ModbusRTUProtocol._guess_is_request(func_code, data)


# ========== 工厂模式 ==========

class ModbusProtocolFactory:
    """协议工厂：按类型创建策略实例"""

    _PROTOCOLS = {
        MODBUS_RTU: ModbusRTUProtocol,
        MODBUS_TCP: ModbusTCPProtocol,
    }

    @classmethod
    def create(cls, protocol_type):
        """创建协议策略实例

        Args:
            protocol_type: 'rtu' / 'tcp' / MODBUS_RTU / MODBUS_TCP

        Returns:
            ModbusProtocol 实例

        Raises:
            ValueError: 不支持的协议类型
        """
        key = protocol_type.lower() if isinstance(protocol_type, str) else protocol_type
        proto_cls = cls._PROTOCOLS.get(key)
        if proto_cls is None:
            raise ValueError(f"不支持的 Modbus 协议类型: {protocol_type}")
        return proto_cls()

    @classmethod
    def supported_types(cls):
        return list(cls._PROTOCOLS.keys())


# ========== 异常码名称映射 ==========

_EXCEPTION_NAMES = {
    EXC_ILLEGAL_FUNCTION: '非法功能码',
    EXC_ILLEGAL_DATA_ADDRESS: '非法数据地址',
    EXC_ILLEGAL_DATA_VALUE: '非法数据值',
    EXC_SLAVE_DEVICE_FAILURE: '从站设备故障',
}


# ========== 功能码名称映射 ==========

FUNC_NAMES = {
    FUNC_READ_COILS: '读线圈(0x01)',
    FUNC_READ_DISCRETE_INPUTS: '读离散输入(0x02)',
    FUNC_READ_HOLDING_REGISTERS: '读保持寄存器(0x03)',
    FUNC_READ_INPUT_REGISTERS: '读输入寄存器(0x04)',
    FUNC_WRITE_SINGLE_COIL: '写单个线圈(0x05)',
    FUNC_WRITE_SINGLE_REGISTER: '写单个寄存器(0x06)',
    FUNC_WRITE_MULTIPLE_COILS: '写多个线圈(0x0F)',
    FUNC_WRITE_MULTIPLE_REGISTERS: '写多个寄存器(0x10)',
}


# ========== Server 端：基于 XML 配置的从站模拟器 ==========

class ModbusServerSimulator:
    """Modbus 从站模拟器

    加载 XML 配置文件，在内存中建立线圈/离散输入/保持寄存器/输入寄存器的数据映射，
    当收到客户端请求时构造对应的响应报文。

    XML 配置格式示例：
        <modbus>
            <coil address="0" value="1"/>
            <coil address="1" value="0"/>
            <discrete_input address="0" value="0"/>
            <holding_register address="0" value="100"/>
            <holding_register address="100" value="200"/>
            <input_register address="0" value="300"/>
        </modbus>

    标签名映射：
        coil              -> 线圈（可读写，功能码 0x01/0x05/0x0F）
        discrete_input    -> 离散输入（只读，功能码 0x02）
        holding_register  -> 保持寄存器（可读写，功能码 0x03/0x06/0x10）
        input_register    -> 输入寄存器（只读，功能码 0x04）
    """

    # XML 标签 -> 数据区类型
    _TAG_MAP = {
        'coil': 'coils',
        'discrete_input': 'discrete_inputs',
        'holding_register': 'holding_registers',
        'input_register': 'input_registers',
    }

    # 功能码 -> 可访问的数据区 + 是否为读操作
    _FUNC_DATA_MAP = {
        FUNC_READ_COILS: ('coils', True),
        FUNC_READ_DISCRETE_INPUTS: ('discrete_inputs', True),
        FUNC_READ_HOLDING_REGISTERS: ('holding_registers', True),
        FUNC_READ_INPUT_REGISTERS: ('input_registers', True),
        FUNC_WRITE_SINGLE_COIL: ('coils', False),
        FUNC_WRITE_SINGLE_REGISTER: ('holding_registers', False),
        FUNC_WRITE_MULTIPLE_COILS: ('coils', False),
        FUNC_WRITE_MULTIPLE_REGISTERS: ('holding_registers', False),
    }

    def __init__(self, protocol_type=MODBUS_RTU, slave_id=1):
        """初始化从站模拟器

        Args:
            protocol_type: 协议类型 'rtu'/'tcp'
            slave_id: 默认从站地址/单元标识符
        """
        self._protocol = ModbusProtocolFactory.create(protocol_type)
        self._slave_id = slave_id
        # 数据区：地址 -> 值
        self._data = {
            'coils': {},
            'discrete_inputs': {},
            'holding_registers': {},
            'input_registers': {},
        }

    @property
    def protocol(self):
        return self._protocol

    @property
    def slave_id(self):
        return self._slave_id

    def load_xml(self, xml_path):
        """从 XML 文件加载从站配置

        Args:
            xml_path: XML 文件路径

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: XML 格式错误
        """
        tree = ET.parse(xml_path)
        root = tree.getroot()
        if root.tag != 'modbus':
            raise ValueError(f"根节点必须为 <modbus>，实际为 <{root.tag}>")

        # 清空现有数据
        for key in self._data:
            self._data[key].clear()

        for elem in root:
            tag = elem.tag
            data_key = self._TAG_MAP.get(tag)
            if data_key is None:
                continue  # 忽略未知标签
            try:
                addr = int(elem.get('address', '0'))
                value = int(elem.get('value', '0'))
            except ValueError:
                raise ValueError(f"节点 <{tag}> 的 address/value 必须为整数")
            self._data[data_key][addr] = value

    def load_xml_string(self, xml_string):
        """从 XML 字符串加载配置（用于测试或内存配置）"""
        root = ET.fromstring(xml_string)
        if root.tag != 'modbus':
            raise ValueError(f"根节点必须为 <modbus>，实际为 <{root.tag}>")
        for key in self._data:
            self._data[key].clear()
        for elem in root:
            tag = elem.tag
            data_key = self._TAG_MAP.get(tag)
            if data_key is None:
                continue
            addr = int(elem.get('address', '0'))
            value = int(elem.get('value', '0'))
            self._data[data_key][addr] = value

    def get_value(self, data_area, address):
        """获取指定数据区的值"""
        return self._data[data_area].get(address, 0)

    def set_value(self, data_area, address, value):
        """设置指定数据区的值"""
        self._data[data_area][address] = value

    def handle_request(self, adu):
        """处理客户端请求，返回响应报文

        Args:
            adu: 客户端请求的完整 ADU 报文

        Returns:
            bytes：响应报文（正常或异常响应）
        """
        parsed = self._protocol.parse(adu)
        if not parsed.get('valid'):
            # 报文校验失败，返回设备故障异常
            return self._protocol.build_response(
                0x00, self._slave_id, exception_code=EXC_SLAVE_DEVICE_FAILURE)

        # TCP 模式下回响需要保持事务 ID
        txn_id = parsed.get('txn_id')

        func_code = parsed['func_code']
        if parsed.get('is_exception'):
            # 请求本身就是异常报文，不处理
            return b''

        data = parsed.get('data', {})
        data_area_info = self._FUNC_DATA_MAP.get(func_code)

        # 未知功能码 -> 异常响应
        if data_area_info is None:
            return self._protocol.build_response(
                func_code, self._slave_id, txn_id=txn_id,
                exception_code=EXC_ILLEGAL_FUNCTION)

        data_area, is_read = data_area_info

        # ----- 读操作 -----
        if is_read:
            start_addr = data.get('start_address', 0)
            quantity = data.get('quantity', 1)
            values = []
            for i in range(quantity):
                values.append(self._data[data_area].get(start_addr + i, 0))
            return self._protocol.build_response(
                func_code, self._slave_id, values=values, txn_id=txn_id)

        # ----- 写操作 -----
        if func_code == FUNC_WRITE_SINGLE_COIL:
            addr = data.get('start_address', 0)
            value = data.get('value', 0)
            self._data[data_area][addr] = value
            # 响应回显 addr + value
            return self._protocol.build_response(
                func_code, self._slave_id,
                values=[addr, COIL_ON if value else COIL_OFF], txn_id=txn_id)

        if func_code == FUNC_WRITE_SINGLE_REGISTER:
            addr = data.get('start_address', 0)
            value = data.get('value', 0)
            self._data[data_area][addr] = value
            return self._protocol.build_response(
                func_code, self._slave_id, values=[addr, value], txn_id=txn_id)

        if func_code == FUNC_WRITE_MULTIPLE_COILS:
            addr = data.get('start_address', 0)
            values = data.get('values', [])
            for i, v in enumerate(values):
                self._data[data_area][addr + i] = 1 if v else 0
            return self._protocol.build_response(
                func_code, self._slave_id,
                values=[addr, len(values)], txn_id=txn_id)

        if func_code == FUNC_WRITE_MULTIPLE_REGISTERS:
            addr = data.get('start_address', 0)
            values = data.get('values', [])
            for i, v in enumerate(values):
                self._data[data_area][addr + i] = v
            return self._protocol.build_response(
                func_code, self._slave_id,
                values=[addr, len(values)], txn_id=txn_id)

        return self._protocol.build_response(
            func_code, self._slave_id, txn_id=txn_id,
            exception_code=EXC_SLAVE_DEVICE_FAILURE)
