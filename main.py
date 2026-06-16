import sys
from PyQt6.QtWidgets import QApplication
from core.main_window import MainWindow
from core.plugin_manager import PluginManager


def main():
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