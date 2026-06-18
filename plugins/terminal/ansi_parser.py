import re
from PyQt6.QtGui import QColor, QTextCharFormat, QFont


class ANSIParser:
    """ANSI转义序列解析器，用于处理终端颜色和格式"""

    # ANSI转义序列正则表达式
    ANSI_PATTERN = re.compile(r'\x1B\[[0-9;]*[mK]')

    # ANSI颜色代码映射
    COLOR_MAP = {
        30: QColor(0, 0, 0),           # 黑色
        31: QColor(205, 0, 0),         # 红色
        32: QColor(0, 205, 0),         # 绿色
        33: QColor( 205, 205, 0),      # 黄色
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

    # 背景色代码映射
    BG_COLOR_MAP = {
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

    def __init__(self):
        self.current_format = QTextCharFormat()
        self.default_foreground = QColor(204, 204, 204)  # #cccccc
        self.default_background = QColor(12, 12, 12)     # #0c0c0c
        self.reset_format()

    def reset_format(self):
        """重置格式为默认值"""
        self.current_format = QTextCharFormat()
        self.current_format.setForeground(self.default_foreground)
        self.current_format.setBackground(self.default_background)

    def parse(self, text):
        """解析包含ANSI转义序列的文本，返回(纯文本, 格式列表)"""
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
        # 提取数字部分
        code_str = ansi_code[2:-1]  # 去掉 \x1B[ 和结尾字符
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
                # 取消反色
                self.current_format.setForeground(self.default_foreground)
                self.current_format.setBackground(self.default_background)
            elif code in self.COLOR_MAP:
                # 前景色
                self.current_format.setForeground(self.COLOR_MAP[code])
            elif code in self.BG_COLOR_MAP:
                # 背景色
                self.current_format.setBackground(self.BG_COLOR_MAP[code])

    def get_current_format(self):
        """获取当前格式"""
        return QTextCharFormat(self.current_format)