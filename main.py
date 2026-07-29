import sys
import warnings
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
from PyQt6.QtWidgets import QApplication
from core.main_window import MainWindow
from core.plugin_manager import PluginManager


def _qt_message_handler(msg_type, context, message):
    """过滤 Qt 良性警告，保留有意义的警告输出

    过滤的警告：
    - QFont::setPointSize: Point size <= 0 — Qt 内部样式表处理时的良性警告
    - libpng warning: iCCP — PNG 图片 sRGB 配置元数据警告，不影响显示
    """
    if msg_type == QtMsgType.QtWarningMsg:
        if 'setPointSize' in message and 'Point size <= 0' in message:
            return
        if 'libpng warning' in message and 'iCCP' in message:
            return
    # 其他警告正常输出到 stderr
    sys.stderr.write(f"{message}\n")


def main():
    # 抑制第三方库的弃用警告
    warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')
    warnings.filterwarnings('ignore', category=DeprecationWarning, module='cryptography')

    # 安装 Qt 消息处理器，过滤良性警告
    qInstallMessageHandler(_qt_message_handler)

    app = QApplication(sys.argv)
    app.setApplicationName("MyDesk")
    app.setOrganizationName("MyDesk")

    # Initialize plugin manager
    plugin_manager = PluginManager()

    # Create and show main window
    window = MainWindow(plugin_manager)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()