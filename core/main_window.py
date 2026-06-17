import os
import json
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget,
    QMenuBar, QMenu, QStatusBar, QLabel,
    QToolBar, QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction
from utils.config_manager import ConfigManager


class MainWindow(QMainWindow):
    def __init__(self, plugin_manager, config_manager=None, parent=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.config_manager = config_manager or ConfigManager(
            ConfigManager.get_default_config_dir()
        )
        self.plugin_widgets = {}
        self.current_plugin_name = None

        self.init_ui()
        self.load_plugins()

    def init_ui(self):
        self.setWindowTitle("MyDesk - 终端管理器")
        self.setGeometry(100, 100, 1200, 800)

        # Central widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Plugin tabs at top for switching
        self.plugin_tabs = QTabWidget()
        self.plugin_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.plugin_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px 20px;
                border: 1px solid #3d3d40;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #007acc;
                color: white;
                border-color: #007acc;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3d3d40;
            }
        """)
        self.plugin_tabs.currentChanged.connect(self.on_plugin_tab_changed)
        layout.addWidget(self.plugin_tabs)

        self.create_menu_bar()
        self.create_tool_bar()
        self.create_status_bar()

    def create_menu_bar(self):
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #2d2d30;
                color: #cccccc;
            }
            QMenuBar::item:selected {
                background-color: #007acc;
            }
            QMenu {
                background-color: #2d2d30;
                color: #cccccc;
            }
            QMenu::item:selected {
                background-color: #007acc;
            }
        """)

        # 文件菜单
        self.file_menu = menubar.addMenu("文件(&F)")

        new_session_action = QAction("新建会话", self)
        new_session_action.setShortcut("Ctrl+N")
        new_session_action.triggered.connect(self.show_first_plugin)
        self.file_menu.addAction(new_session_action)

        self.file_menu.addSeparator()

        settings_action = QAction("设置", self)
        self.file_menu.addAction(settings_action)

        self.file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.file_menu.addAction(exit_action)

        # 视图菜单
        self.view_menu = menubar.addMenu("视图(&V)")

        fullscreen_action = QAction("全屏", self)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.view_menu.addAction(fullscreen_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_tool_bar(self):
        self.toolbar = QToolBar("主工具栏")
        self.toolbar.setMovable(False)
        self.toolbar.setStyleSheet("""
            QToolBar {
                background-color: #2d2d30;
                border: none;
                spacing: 5px;
            }
            QToolBar::separator {
                background-color: #3d3d40;
                width: 1px;
            }
        """)
        self.addToolBar(self.toolbar)

    def build_plugin_actions(self):
        """根据插件配置文件动态构建菜单和工具栏"""
        self.toolbar.clear()

        # 工具栏按钮根据插件配置生成
        for plugin_info in self.config_manager.get_plugins():
            plugin_name = plugin_info.get("name", "")
            plugin_config = self.config_manager.get_plugin_config(plugin_name)
            
            if not plugin_config:
                continue
                
            toolbar_items = plugin_config.get("toolbar", [])
            for item in toolbar_items:
                label = item.get("label", "")
                action_type = item.get("action", "")
                params = item.get("params", "")

                action = QAction(label, self)
                action.setStyleSheet("""
                    QAction {
                        color: #cccccc;
                    }
                """)
                if action_type == "quick_connect":
                    action.triggered.connect(
                        lambda checked, p=params, pn=plugin_name: self.quick_connect(p, pn)
                    )
                elif action_type == "switch_to_plugin":
                    action.triggered.connect(
                        lambda checked, p=params: self.switch_to_plugin(p)
                    )
                self.toolbar.addAction(action)

            if toolbar_items:
                self.toolbar.addSeparator()

    def create_status_bar(self):
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #007acc;
                color: white;
            }
        """)
        self.setStatusBar(self.status_bar)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: white;")
        self.status_bar.addWidget(self.status_label)

        self.status_bar.addPermanentWidget(QLabel("MyDesk v1.0.0"))

    def load_plugins(self):
        # 使用 ConfigManager 加载插件，传递 config_manager 给 PluginManager
        plugin_configs = self.config_manager.get_plugins()
        self.plugin_manager.load_plugins(plugin_configs, self.config_manager)

        self.status_label.setText(f"已加载 {len(self.plugin_manager.plugins)} 个插件")

        # 清空插件标签页
        self.plugin_tabs.clear()

        # 为每个插件创建标签页
        for plugin_info in plugin_configs:
            plugin_name = plugin_info.get("name", "")
            
            # 从插件单独配置文件获取 display_name
            plugin_config = self.config_manager.get_plugin_config(plugin_name)
            display_name = plugin_config.get("display_name", plugin_name) if plugin_config else plugin_name
            
            if plugin_name in self.plugin_manager.plugins:
                # 创建插件widget
                plugin = self.plugin_manager.plugins[plugin_name]
                widget = plugin.get_widget()
                self.plugin_widgets[plugin_name] = widget
                
                # 添加到标签页
                self.plugin_tabs.addTab(widget, display_name)

        # 根据插件配置动态构建菜单和工具栏
        self.build_plugin_actions()

    def on_plugin_tab_changed(self, index):
        """插件标签页切换"""
        if index >= 0:
            # 获取当前标签页对应的插件名称
            widget = self.plugin_tabs.widget(index)
            for plugin_name, w in self.plugin_widgets.items():
                if w == widget:
                    self.current_plugin_name = plugin_name
                    plugin_config = self.config_manager.get_plugin_config(plugin_name)
                    display_name = plugin_config.get("display_name", plugin_name) if plugin_config else plugin_name
                    self.status_label.setText(f"当前插件: {display_name}")
                    break

    def switch_to_plugin(self, plugin_name):
        """切换到指定插件"""
        if plugin_name in self.plugin_widgets:
            widget = self.plugin_widgets[plugin_name]
            index = self.plugin_tabs.indexOf(widget)
            if index >= 0:
                self.plugin_tabs.setCurrentIndex(index)

    def show_first_plugin(self):
        """显示配置文件中的第一个插件"""
        if self.plugin_tabs.count() > 0:
            self.plugin_tabs.setCurrentIndex(0)

    def quick_connect(self, connection_type, plugin_name="Terminal"):
        """快速连接（用于插件内部功能）"""
        if plugin_name in self.plugin_manager.plugins:
            # 切换到对应插件
            self.switch_to_plugin(plugin_name)
            
            # 设置连接类型
            if plugin_name in self.plugin_widgets:
                widget = self.plugin_widgets[plugin_name]
                if hasattr(widget, 'set_connection_type'):
                    widget.set_connection_type(connection_type)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_about(self):
        QMessageBox.about(
            self,
            "关于 MyDesk",
            "MyDesk - 终端管理器\n\n"
            "版本: 1.0.0\n\n"
            "参照MobaXterm设计的终端管理工具"
        )

    def set_status(self, message):
        self.status_label.setText(message)