import re
from PyQt6.QtGui import QColor, QTextCharFormat, QFont


class ANSIParser:
    """ANSI转义序列解析器，用于处理终端颜色和格式"""

    # ANSI转义序列正则表达式（预编译）- 支持更多类型
    # CSI序列: \x1b[... 后跟各种控制字符
    # OSC序列: \x1b]...
    # 其他序列: \x1b 后跟其他字符
    ANSI_PATTERN = re.compile(
        r'\x1B\[[0-9;]*[a-zA-Z@!A-Za-z]|'  # CSI 序列 (包括各种控制字符)
        r'\x1B\][^\x07\x1b]*(?:\x07|\x1B\\)|'  # OSC 序列
        r'\x1B[><=]*[a-zA-Z]|'  # 其他转义序列
        r'\x1B[()][AB012]'  # 字符集选择序列
    )

    # ANSI颜色代码映射（使用缓存）
    _color_cache = {}

    # 深色主题ANSI颜色代码映射（浅色文字在深色背景上可见）
    COLOR_MAP_DARK = {
        30: QColor(0, 0, 0),           # 黑色
        31: QColor(205, 0, 0),         # 红色
        32: QColor(0, 205, 0),         # 绿色
        33: QColor(205, 205, 0),       # 黄色
        34: QColor(0, 0, 238),         # 蓝色
        35: QColor(205, 0, 205),       # 品红
        36: QColor(0, 205, 205),       # 青色
        37: QColor(229, 229, 229),     # 白色
        90: QColor(102, 102, 102),     # 亮黑（灰色）
        91: QColor(255, 85, 85),       # 亮红
        92: QColor(85, 255, 85),       # 亮绿
        93: QColor(255, 255, 85),      # 亮黄
        94: QColor(85, 85, 255),       # 亮蓝
        95: QColor(255, 85, 255),      # 亮品红
        96: QColor(85, 255, 255),      # 亮青
        97: QColor(255, 255, 255),     # 亮白
    }

    # 浅色主题ANSI颜色代码映射（加深浅色文字，使其在浅色背景上可见）
    # 关键变化：白色(37/97)映射为深色，黄色/亮绿/亮青等加深
    COLOR_MAP_LIGHT = {
        30: QColor(0, 0, 0),           # 黑色（深色背景上可见）
        31: QColor(205, 0, 0),         # 红色
        32: QColor(0, 152, 0),         # 绿色（加深）
        33: QColor(153, 102, 0),       # 黄色（加深为琥珀色）
        34: QColor(0, 0, 238),         # 蓝色
        35: QColor(205, 0, 205),       # 品红
        36: QColor(0, 120, 152),       # 青色（加深）
        37: QColor(85, 85, 85),        # 白色→深灰色（关键：浅色背景上可见）
        90: QColor(118, 118, 118),     # 亮黑（灰色）
        91: QColor(205, 49, 49),       # 亮红（加深）
        92: QColor(9, 134, 88),        # 亮绿（加深）
        93: QColor(153, 102, 0),       # 亮黄（加深为琥珀色）
        94: QColor(4, 81, 165),        # 亮蓝（加深）
        95: QColor(188, 5, 188),       # 亮品红（加深）
        96: QColor(5, 152, 188),       # 亮青（加深）
        97: QColor(30, 30, 30),        # 亮白→近黑色（关键：浅色背景上可见）
    }

    # 深色主题背景色代码映射
    BG_COLOR_MAP_DARK = {
        40: QColor(0, 0, 0),           # 黑色背景
        41: QColor(205, 0, 0),         # 红色背景
        42: QColor(0, 205, 0),         # 绿色背景
        43: QColor(205, 205, 0),       # 黄色背景
        44: QColor(0, 0, 238),         # 蓝色背景
        45: QColor(205, 0, 205),       # 品红背景
        46: QColor(0, 205, 205),       # 青色背景
        47: QColor(229, 229, 229),     # 白色背景
        100: QColor(102, 102, 102),    # 亮黑背景
        101: QColor(255, 85, 85),      # 亮红背景
        102: QColor(85, 255, 85),      # 亮绿背景
        103: QColor(255, 255, 85),     # 亮黄背景
        104: QColor(85, 85, 255),      # 亮蓝背景
        105: QColor(255, 85, 255),     # 亮品红背景
        106: QColor(85, 255, 255),     # 亮青背景
        107: QColor(255, 255, 255),    # 亮白背景
    }

    # 浅色主题背景色代码映射（黑色背景反转为浅色，白色背景保持）
    BG_COLOR_MAP_LIGHT = {
        40: QColor(85, 85, 85),        # 黑色背景→深灰色（浅色主题上可见）
        41: QColor(205, 0, 0),         # 红色背景
        42: QColor(0, 152, 0),         # 绿色背景（加深）
        43: QColor(153, 102, 0),       # 黄色背景（加深）
        44: QColor(0, 0, 238),         # 蓝色背景
        45: QColor(205, 0, 205),       # 品红背景
        46: QColor(0, 120, 152),       # 青色背景（加深）
        47: QColor(229, 229, 229),     # 白色背景（保持浅色）
        100: QColor(118, 118, 118),    # 亮黑背景
        101: QColor(205, 49, 49),      # 亮红背景（加深）
        102: QColor(9, 134, 88),       # 亮绿背景（加深）
        103: QColor(153, 102, 0),      # 亮黄背景（加深）
        104: QColor(4, 81, 165),       # 亮蓝背景（加深）
        105: QColor(188, 5, 188),      # 亮品红背景（加深）
        106: QColor(5, 152, 188),      # 亮青背景（加深）
        107: QColor(245, 245, 245),    # 亮白背景（保持浅色）
    }

    # 向后兼容：默认使用深色主题颜色映射
    COLOR_MAP = COLOR_MAP_DARK
    BG_COLOR_MAP = BG_COLOR_MAP_DARK

    def __init__(self, enable_color=False, default_foreground=None, is_dark=True):
        self.current_format = QTextCharFormat()
        self.default_foreground = default_foreground or QColor(204, 204, 204)
        self.default_background = QColor(30, 30, 30)
        self.enable_color = enable_color
        self.is_dark = is_dark
        self._update_color_maps()
        self.reset_format()

    def _update_color_maps(self):
        """根据主题模式更新颜色映射（实例级别，不影响类常量）"""
        if self.is_dark:
            self.color_map = self.COLOR_MAP_DARK
            self.bg_color_map = self.BG_COLOR_MAP_DARK
        else:
            self.color_map = self.COLOR_MAP_LIGHT
            self.bg_color_map = self.BG_COLOR_MAP_LIGHT

    def set_theme_mode(self, is_dark):
        """切换主题模式并更新颜色映射"""
        self.is_dark = is_dark
        self._update_color_maps()

    def reset_format(self):
        """重置格式为默认值（不设置背景色，使用控件透明背景）"""
        self.current_format = QTextCharFormat()
        self.current_format.setForeground(self.default_foreground)

    def parse_fast(self, text):
        """快速解析：仅提取纯文本，忽略ANSI序列（用于大量输出）"""
        return self.ANSI_PATTERN.sub('', text)

    def parse(self, text):
        """解析包含ANSI转义序列的文本，返回(纯文本, 格式列表)"""
        # 快速检查是否包含ANSI序列
        if '\x1b' not in text:
            return [(text, QTextCharFormat(self.current_format))]
        
        parts = []
        last_end = 0

        for match in self.ANSI_PATTERN.finditer(text):
            # 添加转义序列前的纯文本
            if match.start() > last_end:
                plain_text = text[last_end:match.start()]
                parts.append((plain_text, QTextCharFormat(self.current_format)))

            # 解析ANSI序列
            ansi_code = match.group()
            self.apply_ansi_code(ansi_code)
            last_end = match.end()

        # 添加剩余的纯文本
        if last_end < len(text):
            plain_text = text[last_end:]
            parts.append((plain_text, QTextCharFormat(self.current_format)))

        return parts

    def apply_ansi_code(self, ansi_code):
        """应用ANSI转义序列到当前格式"""
        if not self.enable_color:
            return
        
        # 检查是否是 CSI 序列 (\x1b[...)
        if ansi_code.startswith('\x1b['):
            # 提取数字部分和结尾字符
            code_str = ansi_code[2:-1]  # 去掉 \x1B[ 和结尾字符
            end_char = ansi_code[-1]  # 结尾字符
            
            # 光标移动和屏幕清除命令 - 这些不改变格式，直接忽略
            # CSI序列可能的结尾字符列表
            format_chars = {'m'}  # 只有 'm' (SGR) 会改变文本格式
            ignore_chars = {
                'H', 'f', 'A', 'B', 'C', 'D', 'E', 'F', 'G',  # 光标移动
                'J', 'K', 'L', 'M', 'P', 'X', 'Z',  # 屏幕/行操作
                '@', 'r', 's', 'u', 'c', 'n',  # 其他CSI命令
                '>', '=', '!', 'g', 'h', 'l', 'o', 'q', 't', 'x', 'y'
            }
            
            # 如果是光标移动或其他非格式命令，忽略
            if end_char in ignore_chars:
                return
            
            # 只有颜色/格式命令 (m) 才继续处理
            if end_char != 'm':
                return
            
            # 处理颜色和格式命令
            if not code_str:
                return

            codes = [int(c) for c in code_str.split(';') if c.isdigit()]

            for code in codes:
                if code == 0:
                    # 重置所有属性
                    self.reset_format()
                elif code == 1:
                    # 加粗
                    self.current_format.setFontWeight(QFont.Weight.Bold)
                elif code == 2:
                    # 变暗
                    self.current_format.setFontWeight(QFont.Weight.Light)
                elif code == 4:
                    # 下划线
                    self.current_format.setFontUnderline(True)
                elif code == 7:
                    # 反色
                    fg = self.current_format.foreground()
                    bg = self.current_format.background()
                    self.current_format.setForeground(bg)
                    self.current_format.setBackground(fg)
                elif code == 22:
                    # 取消加粗/变暗
                    self.current_format.setFontWeight(QFont.Weight.Normal)
                elif code == 24:
                    # 取消下划线
                    self.current_format.setFontUnderline(False)
                elif code == 27:
                    # 取消反色（仅恢复前景色，不设置背景色）
                    self.current_format.setForeground(self.default_foreground)
                    self.current_format.clearBackground()
                elif code in self.color_map:
                    # 前景色
                    self.current_format.setForeground(self.color_map[code])
                elif code in self.bg_color_map:
                    # 背景色
                    self.current_format.setBackground(self.bg_color_map[code])
        
        # OSC 序列 (\x1b]...) - 用于设置窗口标题等，直接忽略
        elif ansi_code.startswith('\x1b]'):
            return
        
        # 其他转义序列 - 直接忽略
        else:
            return

    def get_current_format(self):
        """获取当前格式"""
        return QTextCharFormat(self.current_format)