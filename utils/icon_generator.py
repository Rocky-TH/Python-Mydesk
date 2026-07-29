"""应用图标生成器 - 生成默认的 MyDesk 图标"""
import os
from PyQt6.QtCore import Qt, QRect, QSize
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QFontMetrics,
    QIcon, QBrush, QPen, QRadialGradient, QLinearGradient
)


def generate_default_icon(size=256):
    """生成默认的 MyDesk 应用图标
    
    Args:
        size: 图标尺寸（像素）
    
    Returns:
        QPixmap 对象
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    
    # 绘制渐变背景 - 深蓝到浅蓝
    bg_rect = QRect(0, 0, size, size)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor(30, 60, 120))      # 深蓝
    gradient.setColorAt(0.5, QColor(58, 143, 212))      # MyDesk 蓝
    gradient.setColorAt(1.0, QColor(100, 180, 240))     # 浅蓝
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(bg_rect, int(size * 0.2), int(size * 0.2))
    
    # 绘制内框
    inner_margin = int(size * 0.12)
    inner_rect = QRect(inner_margin, inner_margin, 
                       int(size - 2 * inner_margin), int(size - 2 * inner_margin))
    inner_gradient = QLinearGradient(inner_margin, inner_margin, 
                                     int(size - inner_margin), int(size - inner_margin))
    inner_gradient.setColorAt(0.0, QColor(45, 55, 75))
    inner_gradient.setColorAt(1.0, QColor(30, 40, 60))
    painter.setBrush(QBrush(inner_gradient))
    painter.drawRoundedRect(inner_rect, int(size * 0.15), int(size * 0.15))
    
    # 绘制 "MD" 文字
    text = "MD"
    text_font = QFont("Segoe UI", int(size * 0.35), QFont.Weight.Bold)
    painter.setFont(text_font)
    painter.setPen(QPen(QColor(255, 255, 255)))
    
    text_rect = QRect(inner_margin, inner_margin, 
                      int(size - 2 * inner_margin), int(size - 2 * inner_margin))
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
    
    # 绘制底部文字 "MyDesk"
    bottom_font = QFont("Segoe UI", int(size * 0.08), QFont.Weight.Normal)
    painter.setFont(bottom_font)
    painter.setPen(QPen(QColor(200, 220, 255, 200)))
    
    bottom_rect = QRect(inner_margin, int(size * 0.72), 
                        int(size - 2 * inner_margin), int(size * 0.2))
    painter.drawText(bottom_rect, Qt.AlignmentFlag.AlignCenter, "MyDesk")
    
    painter.end()
    return pixmap


def generate_simple_icon(size=256):
    """生成简单风格的图标（单色背景 + 文字）
    
    Args:
        size: 图标尺寸（像素）
    
    Returns:
        QPixmap 对象
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    
    # 绘制纯色背景
    bg_color = QColor(58, 143, 212)  # MyDesk 蓝
    painter.setBrush(QBrush(bg_color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, size, size, int(size * 0.15), int(size * 0.15))
    
    # 绘制 "MD" 文字
    text_font = QFont("Segoe UI", int(size * 0.4), QFont.Weight.Bold)
    painter.setFont(text_font)
    painter.setPen(QPen(QColor(255, 255, 255)))
    
    text_rect = QRect(0, 0, size, size)
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "MD")
    
    painter.end()
    return pixmap


def create_default_icon(size=256):
    """创建默认图标（返回 QIcon 对象）
    
    Args:
        size: 图标尺寸
    
    Returns:
        QIcon 对象
    """
    pixmap = generate_default_icon(size)
    return QIcon(pixmap)


def create_simple_icon(size=256):
    """创建简单风格图标（返回 QIcon 对象）
    
    Args:
        size: 图标尺寸
    
    Returns:
        QIcon 对象
    """
    pixmap = generate_simple_icon(size)
    return QIcon(pixmap)


def load_app_icon(icon_path=None):
    """加载应用图标
    
    如果提供了图标路径且文件存在，则加载该图标；
    否则自动生成默认图标。
    
    Args:
        icon_path: 图标文件路径（可选）
    
    Returns:
        QIcon 对象
    """
    if icon_path and os.path.exists(icon_path):
        icon = QIcon(icon_path)
        if not icon.isNull():
            return icon
    
    # 返回默认生成的图标
    return create_default_icon(256)
