# -*- coding: utf-8 -*-
"""统一的弹窗与文件选择封装。

项目没有全局样式表与 Qt 中文翻译，直接使用 QMessageBox / QFileDialog 时
会呈现 Windows 原生外观（深色主题下白底）以及英文 Yes/No。本模块集中
提供带主题样式、中文按钮的信息/警告/确认框与非原生目录选择对话框，
各插件只需传入自身的 ConfigManager 即可保持与主题一致。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout
)


def _dialog_qss(config_manager):
    """生成对话框通用样式（背景、文本、输入控件、列表与焦点边框）。"""
    def color(key, default):
        return config_manager.get_color(key, default) if config_manager else default

    def font(key, default):
        return config_manager.get_font_size(key, default) if config_manager else default

    def radius(key, default):
        return config_manager.get_border_radius(key, default) if config_manager else default

    bg_main = color('bg-main', '#1e1e1e')
    bg_input = color('bg-input', '#454545')
    bg_tertiary = color('bg-tertiary', '#2d2d30')
    text = color('text', '#e0e0e0')
    border = color('border', '#3c3c3c')
    border_focus = color('border-focus', '#007acc')
    selection = color('selection', '#264f78')
    selection_text = color('selection-text', '#ffffff')
    font_size = font('size-md', '12px')
    radius_sm = radius('sm', '4px')
    arrow_css = config_manager.get_combo_arrow_css() if config_manager else ''

    return f"""
        QDialog, QMessageBox {{
            background-color: {bg_main};
        }}
        QLabel {{
            color: {text};
            font-size: {font_size};
        }}
        QLineEdit, QComboBox, QSpinBox {{
            background-color: {bg_input};
            color: {text};
            border: 1px solid {border};
            border-radius: {radius_sm};
            padding: 4px 8px;
            font-size: {font_size};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
            border-color: {border_focus};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        {arrow_css}
        QComboBox QAbstractItemView {{
            background-color: {bg_tertiary};
            color: {text};
            selection-background-color: {selection};
            selection-color: {selection_text};
            border: 1px solid {border};
        }}
        QTreeView, QListView {{
            background-color: {bg_input};
            color: {text};
            border: 1px solid {border};
            border-radius: {radius_sm};
        }}
        QTreeView::item:selected, QListView::item:selected {{
            background-color: {selection};
            color: {selection_text};
        }}
        QHeaderView::section {{
            background-color: {bg_tertiary};
            color: {text};
            border: none;
            border-right: 1px solid {border};
            border-bottom: 1px solid {border};
            padding: 4px 6px;
        }}
        QToolButton {{
            background-color: transparent;
            color: {text};
            border: none;
            padding: 2px 6px;
        }}
        QToolButton:hover {{
            background-color: {bg_tertiary};
            border-radius: {radius_sm};
        }}
    """


def apply_dialog_theme(dialog, config_manager=None):
    """对任意 QDialog 应用统一的主题样式。"""
    dialog.setStyleSheet(_dialog_qss(config_manager))


def _style_button(button, config_manager, button_type='button'):
    """按按钮类型应用主题样式。"""
    if button is not None and config_manager:
        button.setStyleSheet(config_manager.get_button_css(button_type))


def _build_message_box(parent, icon, title, text, config_manager=None, rich_text=False):
    """构建一个带主题样式、中文按钮的 QMessageBox（不调用 exec）。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(icon)
    if rich_text:
        box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(text)
    box.setStyleSheet(_dialog_qss(config_manager))
    box.setStandardButtons(QMessageBox.StandardButton.NoButton)
    ok_btn = box.addButton('确定', QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(ok_btn)
    box.setEscapeButton(ok_btn)
    _style_button(ok_btn, config_manager, 'button')
    return box


def show_info(parent, title, text, config_manager=None, rich_text=False):
    """显示信息提示框。"""
    _build_message_box(
        parent, QMessageBox.Icon.Information, title, text, config_manager, rich_text
    ).exec()


def show_warning(parent, title, text, config_manager=None, rich_text=False):
    """显示警告提示框。"""
    _build_message_box(
        parent, QMessageBox.Icon.Warning, title, text, config_manager, rich_text
    ).exec()


def show_error(parent, title, text, config_manager=None, rich_text=False):
    """显示错误提示框。"""
    _build_message_box(
        parent, QMessageBox.Icon.Critical, title, text, config_manager, rich_text
    ).exec()


def confirm(parent, title, text, config_manager=None,
            confirm_text='确定', cancel_text='取消', danger=False):
    """显示中文确认框，返回是否点击了确认按钮。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.setStyleSheet(_dialog_qss(config_manager))
    box.setStandardButtons(QMessageBox.StandardButton.NoButton)
    ok_btn = box.addButton(confirm_text, QMessageBox.ButtonRole.AcceptRole)
    cancel_btn = box.addButton(cancel_text, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(ok_btn)
    box.setEscapeButton(cancel_btn)
    _style_button(ok_btn, config_manager, 'button-danger' if danger else 'button')
    _style_button(cancel_btn, config_manager, 'button-secondary')
    box.exec()
    return box.clickedButton() is ok_btn


def get_text(parent, title, label, default='', config_manager=None, placeholder=''):
    """显示中文主题化单行输入框。

    返回输入的文本；用户取消时返回 None（与 QInputDialog 的 ok 标记区分）。
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(360)
    dialog.setStyleSheet(_dialog_qss(config_manager))

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    label_widget = QLabel(label)
    layout.addWidget(label_widget)

    line_edit = QLineEdit(default)
    if placeholder:
        line_edit.setPlaceholderText(placeholder)
    layout.addWidget(line_edit)

    button_layout = QHBoxLayout()
    button_layout.addStretch()
    cancel_btn = QPushButton('取消')
    ok_btn = QPushButton('确定')
    ok_btn.setDefault(True)
    _style_button(cancel_btn, config_manager, 'button-secondary')
    _style_button(ok_btn, config_manager, 'button')
    cancel_btn.clicked.connect(dialog.reject)
    ok_btn.clicked.connect(dialog.accept)
    button_layout.addWidget(cancel_btn)
    button_layout.addWidget(ok_btn)
    layout.addLayout(button_layout)

    line_edit.setFocus()
    line_edit.selectAll()

    if dialog.exec() == QDialog.DialogCode.Accepted:
        return line_edit.text()
    return None


def get_existing_directory(parent, caption, directory='', config_manager=None):
    """非原生目录选择对话框（主题样式 + 中文按钮），返回目录路径。"""
    dialog = QFileDialog(parent, caption, directory)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    # setLabelText 会触发非原生对话框的控件创建，之后才可找到按钮
    dialog.setLabelText(QFileDialog.DialogLabel.LookIn, '查看')
    dialog.setLabelText(QFileDialog.DialogLabel.FileName, '文件夹:')
    dialog.setLabelText(QFileDialog.DialogLabel.FileType, '文件类型:')
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, '选择')
    dialog.setLabelText(QFileDialog.DialogLabel.Reject, '取消')
    dialog.setStyleSheet(_dialog_qss(config_manager))

    button_box = dialog.findChild(QDialogButtonBox)
    if button_box is not None:
        _style_button(
            button_box.button(QDialogButtonBox.StandardButton.Open),
            config_manager, 'button'
        )
        _style_button(
            button_box.button(QDialogButtonBox.StandardButton.Cancel),
            config_manager, 'button-secondary'
        )

    if dialog.exec() == QDialog.DialogCode.Accepted:
        selected = dialog.selectedFiles()
        return selected[0] if selected else ''
    return ''
