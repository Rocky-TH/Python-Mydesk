import os
import json
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget,
    QMenuBar, QMenu, QStatusBar, QLabel,
    QToolBar, QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction
from utils.config_manager import ConfigManager


class ThemeSwitchWorker(QThread):
    theme_switched = pyqtSignal(bool)
    
    def __init__(self, config_manager, theme_id):
        super().__init__()
        self._config_manager = config_manager
        self._theme_id = theme_id
    
    def run(self):
        success = self._config_manager.set_current_theme(self._theme_id)
        self.theme_switched.emit(success)


class MainWindow(QMainWindow):
    def __init__(self, plugin_manager, config_manager=None, parent=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.config_manager = config_manager or ConfigManager(
            ConfigManager.get_default_config_dir()
        )
        self._color_scheme = self.config_manager.get_color_scheme()
        self.plugin_widgets = {}
        self.current_plugin_name = None
        self._theme_worker = None

        self.init_ui()
        self.load_plugins()
    
    def _get_style(self, key, default=None):
        """获取样式配置（支持新旧两种格式）"""
        value = self._color_scheme.get(key)
        if value is not None:
            return value
        old_key_map = {
            'background_main': 'bg-main',
            'background_secondary': 'bg-secondary',
            'background_tertiary': 'bg-tertiary',
            'background_input': 'bg-input',
            'background_input_focus': 'bg-input-focus',
            'text_primary': 'text',
            'text_secondary': 'text-secondary',
            'border_light': 'border-light',
            'border_focus': 'border-focus',
            'selection_text': 'selection-text',
            'primary_hover': 'primary-hover',
            'primary_pressed': 'primary-pressed',
            'success_hover': 'success-hover',
            'text_success': 'text-success',
            'text_danger': 'text-danger'
        }
        if key in old_key_map:
            return self._color_scheme.get(old_key_map[key], default)
        return default
    
    def _get_font_size(self, key, default='12px'):
        """获取字体大小"""
        return self.config_manager.get_font_size(key, default)
    
    def _get_border_radius(self, key, default='4px'):
        """获取边框圆角"""
        return self.config_manager.get_border_radius(key, default)

    def init_ui(self):
        self.setWindowTitle("MyDesk - 终端管理器")
        self.setGeometry(100, 100, 1200, 800)

        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border = self._get_style('border', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        primary = self._get_style('primary', '#007acc')
        selection = self._get_style('selection', '#007acc')
        font_size_medium = self._get_font_size('size-lg', '13px')
        font_size_normal = self._get_font_size('size-md', '12px')
        border_radius_small = self._get_border_radius('sm', '4px')
        border_radius_normal = self._get_border_radius('md', '6px')

        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {bg_main};
            }}
        """)

        self.central_widget = QWidget()
        self.central_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_main};
            }}
        """)
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.plugin_tabs = QTabWidget()
        self.plugin_tabs.setTabPosition(QTabWidget.TabPosition.North)
        
        # 定义插件标签页的默认背景色
        tab1_bg = "#1a4d6e"  # QuicklyCmd - 深蓝
        tab1_border = "#007acc"
        tab1_selected = "#007acc"
        
        tab2_bg = "#1a5d3e"  # 终端 - 深绿
        tab2_border = "#28a745"
        tab2_selected = "#28a745"
        
        self.plugin_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {bg_main};
            }}
            QTabBar::tab {{
                background-color: {bg_tertiary};
                color: {text_secondary};
                padding: 10px 24px;
                border: 1px solid {border};
                border-bottom: none;
                margin-right: 2px;
                margin-top: 4px;
                border-top-left-radius: {border_radius_normal};
                border-top-right-radius: {border_radius_normal};
                font-size: {font_size_medium};
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {primary};
                color: {text_primary};
                border-color: {primary};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {bg_input};
                color: {text_primary};
            }}
            
            /* 第一个标签页 - QuicklyCmd */
            QTabBar::tab:first {{
                background-color: {tab1_bg};
                border-color: {tab1_border};
            }}
            QTabBar::tab:first:selected {{
                background-color: {tab1_selected};
                border-color: {tab1_selected};
            }}
            QTabBar::tab:first:hover:!selected {{
                background-color: {tab1_border};
            }}
            
            /* 第二个标签页 - 终端 */
            QTabBar::tab:nth-child(2) {{
                background-color: {tab2_bg};
                border-color: {tab2_border};
            }}
            QTabBar::tab:nth-child(2):selected {{
                background-color: {tab2_selected};
                border-color: {tab2_selected};
            }}
            QTabBar::tab:nth-child(2):hover:!selected {{
                background-color: {tab2_border};
            }}
        """)
        self.plugin_tabs.currentChanged.connect(self.on_plugin_tab_changed)
        layout.addWidget(self.plugin_tabs)

        self.create_menu_bar()
        self.create_tool_bar()
        self.create_status_bar()

    def create_menu_bar(self):
        menubar = self.menuBar()
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        text_primary = self._get_style('text', '#ffffff')
        border = self._get_style('border', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        primary = self._get_style('primary', '#007acc')
        border_radius_small = self._get_border_radius('sm', '4px')
        border_radius_normal = self._get_border_radius('md', '6px')
        
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {bg_tertiary};
                color: {text_primary};
                border-bottom: 1px solid {border};
                padding: 2px;
            }}
            QMenuBar::item:selected {{
                background-color: {primary};
                border-radius: {border_radius_small};
                padding: 4px 8px;
            }}
            QMenu {{
                background-color: {bg_tertiary};
                color: {text_primary};
                border: 1px solid {border_light};
                border-radius: {border_radius_normal};
                padding: 4px;
            }}
            QMenu::item:selected {{
                background-color: {primary};
                border-radius: {border_radius_small};
                padding: 4px 20px;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {border_light};
                margin: 4px 8px;
            }}
        """)

        # 文件菜单
        self.file_menu = menubar.addMenu("文件(&F)")

        new_session_action = QAction("新建会话", self)
        new_session_action.setShortcut("Ctrl+N")
        new_session_action.triggered.connect(self.show_first_plugin)
        self.file_menu.addAction(new_session_action)

        self.file_menu.addSeparator()

        # 设置菜单
        settings_menu = QMenu("设置", self)
        self.file_menu.addMenu(settings_menu)

        # 主题设置子菜单
        self.theme_menu = QMenu("主题", self)
        settings_menu.addMenu(self.theme_menu)
        self._theme_actions = {}
        
        # 获取可用主题列表
        themes = self.config_manager.get_theme_list()
        current_theme = self.config_manager.get_current_theme()
        
        # 添加主题选项
        for theme_info in themes:
            theme_action = QAction(theme_info['name'], self)
            theme_action.setCheckable(True)
            theme_action.setChecked(theme_info['id'] == current_theme)
            theme_action.triggered.connect(
                lambda checked, tid=theme_info['id']: self.change_theme(tid)
            )
            self.theme_menu.addAction(theme_action)
            self._theme_actions[theme_info['id']] = theme_action

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
        
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        text_primary = self._get_style('text', '#ffffff')
        primary = self._get_style('primary', '#007acc')
        font_size_normal = self._get_font_size('size-md', '12px')
        border_radius_small = self._get_border_radius('sm', '4px')
        
        self.toolbar.setStyleSheet(f"""
            QToolBar {{
                background-color: {bg_tertiary};
                border: none;
                spacing: 6px;
                padding: 4px;
            }}
            QToolBar::separator {{
                background-color: {border_light};
                width: 1px;
                margin: 4px 8px;
            }}
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {border_radius_small};
                padding: 6px 12px;
                color: {text_primary};
                font-size: {font_size_normal};
            }}
            QToolButton:hover {{
                background-color: {bg_input};
                border-color: {border_light};
            }}
            QToolButton:pressed {{
                background-color: {primary};
                border-color: {primary};
            }}
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
                text_secondary = self._get_style('text-secondary', '#cccccc')
                action.setStyleSheet(f"""
                    QAction {{
                        color: {text_secondary};
                    }}
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
        primary = self._get_style('primary', '#007acc')
        text_primary = self._get_style('text', '#ffffff')
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {primary};
                color: {text_primary};
            }}
        """)
        self.setStatusBar(self.status_bar)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(f"color: {text_primary};")
        self.status_bar.addWidget(self.status_label)

        self.status_bar.addPermanentWidget(QLabel("MyDesk v1.0.0"))

    def load_plugins(self):
        # 使用 ConfigManager 加载插件，传递 config_manager 给 PluginManager
        plugin_configs = self.config_manager.get_plugins()
        self.plugin_manager.load_plugins(plugin_configs, self.config_manager)

        self.status_label.setText(f"已加载 {len(self.plugin_manager.plugins)} 个插件")

        # 清空插件标签页
        self.plugin_tabs.clear()
        self.plugin_widgets.clear()

        # 定义插件标签页的颜色方案
        plugin_tab_colors = [
            {"bg": "#1a4d6e", "border": "#007acc"},  # QuicklyCmd - 深蓝
            {"bg": "#1a5d3e", "border": "#28a745"},  # 终端 - 深绿
        ]

        # 为每个插件创建标签页
        for index, plugin_info in enumerate(plugin_configs):
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
                tab_index = self.plugin_tabs.addTab(widget, display_name)
                
                # 为标签页设置不同的颜色
                if index < len(plugin_tab_colors):
                    color_info = plugin_tab_colors[index]
                    bg_color = color_info["bg"]
                    border_color = color_info["border"]
                    
                    # 设置标签样式
                    self.plugin_tabs.tabBar().setTabData(tab_index, {
                        "bg": bg_color,
                        "border": border_color
                    })

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

    def change_theme(self, theme_id):
        """异步切换主题"""
        if self._theme_worker and self._theme_worker.isRunning():
            return
        
        self._theme_worker = ThemeSwitchWorker(self.config_manager, theme_id)
        self._theme_worker.theme_switched.connect(
            lambda success, tid=theme_id: self._on_theme_switched(success, tid)
        )
        self._theme_worker.start()
    
    def _on_theme_switched(self, success, theme_id):
        """主题切换完成后的回调"""
        if success:
            QTimer.singleShot(0, lambda: self._update_theme_ui(theme_id))
    
    def _update_theme_ui(self, theme_id):
        """更新主题UI（在主线程中执行）"""
        self._color_scheme = self.config_manager.get_color_scheme()
        
        self.init_ui()
        self.load_plugins()
        
        if hasattr(self, '_theme_actions'):
            current_theme = self.config_manager.get_current_theme()
            for tid, action in self._theme_actions.items():
                action.setChecked(tid == current_theme)
    
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