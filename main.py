import sys
import warnings
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
from PyQt6.QtWidgets import QApplication
from core.main_window import MainWindow
from core.plugin_manager import PluginManager
from utils.logger import Logger


def _qt_message_handler(msg_type, context, message):
    """过滤 Qt 良性警告，保留有意义的警告输出

    过滤的警告：
    - QFont::setPointSize: Point size <= 0 — Qt 内部样式表处理时的良性警告
    - libpng warning: iCCP — PNG 图片 sRGB 配置元数据警告，不影响显示

    同时将 Critical/Fatal 消息和未过滤的 Warning 通过 Logger 记录，
    便于通过调测工具 UI 回溯 Qt 层面的错误。
    """
    logger = Logger.get_instance()
    if msg_type == QtMsgType.QtWarningMsg:
        if 'setPointSize' in message and 'Point size <= 0' in message:
            return
        if 'libpng warning' in message and 'iCCP' in message:
            return
        logger.warning(f"[Qt] {message}")
        sys.stderr.write(f"{message}\n")
        return
    if msg_type == QtMsgType.QtCriticalMsg:
        logger.error(f"[Qt Critical] {message}")
        sys.stderr.write(f"{message}\n")
        return
    if msg_type == QtMsgType.QtFatalMsg:
        logger.critical(f"[Qt Fatal] {message}")
        sys.stderr.write(f"{message}\n")
        return
    # DebugMsg / InfoMsg：输出到 stderr，不落盘
    sys.stderr.write(f"{message}\n")


def _install_exception_hook():
    """安装全局未捕获异常 hook

    捕获所有未处理的 Python 异常（包括终端工具崩溃），记录完整 traceback 到
    日志文件，然后调用默认 hook 保持原有行为（打印到 stderr）。
    """
    logger = Logger.get_instance()

    def _excepthook(exc_type, exc_value, exc_tb):
        logger.critical(
            f"未捕获异常: {exc_type.__name__}: {exc_value}",
            exc_info=True
        )
        # 调用默认 hook，保持 stderr 输出
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook


def main():
    # 抑制第三方库的弃用警告
    warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')
    warnings.filterwarnings('ignore', category=DeprecationWarning, module='cryptography')

    # 安装 Qt 消息处理器，过滤良性警告并记录有意义的 Qt 消息
    qInstallMessageHandler(_qt_message_handler)

    # 安装全局未捕获异常 hook（在 Qt 消息处理器之后）
    _install_exception_hook()

    logger = Logger.get_instance()
    logger.info("MyDesk 应用启动")

    app = QApplication(sys.argv)
    app.setApplicationName("MyDesk")
    app.setOrganizationName("MyDesk")

    # Initialize plugin manager
    plugin_manager = PluginManager()

    # Create and show main window
    window = MainWindow(plugin_manager)
    window.show()

    logger.info("MyDesk 主窗口已显示，进入事件循环")

    exit_code = app.exec()
    logger.info(f"MyDesk 应用退出，退出码: {exit_code}")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()