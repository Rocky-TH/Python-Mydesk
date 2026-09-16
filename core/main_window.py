import os
import json
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget,
    QMenuBar, QMenu, QStatusBar, QLabel,
    QToolBar, QTabWidget, QMessageBox,
    QDialog, QTextEdit, QPushButton
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QActionGroup
from utils.config_manager import ConfigManager
from utils.icon_generator import load_app_icon

# 下拉框三角形箭头图片路径
_DOWN_ARROW_IMG = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'assets', 'down_arrow.png'
).replace('\\', '/')


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
        self._menu_bar_created = False
        self._tool_bar_created = False
        self._status_bar_created = False
        # MyDesk 版本号（统一管理，用于「关于」与状态栏显示）
        self._app_version = "1.0.0"

        self.init_ui()
        self.load_plugins()
    
    def _get_style(self, key, default=None):
        """获取样式配置（直接从 config_manager 实时获取，避免缓存不一致）"""
        if self.config_manager:
            return self.config_manager.get_color(key, default)
        return default
    
    def _get_font_size(self, key, default='12px'):
        """获取字体大小"""
        return self.config_manager.get_font_size(key, default)
    
    def _get_border_radius(self, key, default='4px'):
        """获取边框圆角"""
        return self.config_manager.get_border_radius(key, default)

    def init_ui(self):
        # 加载应用配置（标题、图标等）
        app_config = self.config_manager.get_app_config()
        app_title = app_config.get('title', 'MyDesk - 终端管理器')
        app_version = app_config.get('version', self._app_version)
        
        # 更新版本号
        self._app_version = app_version
        
        self.setWindowTitle(app_title)
        self.setGeometry(100, 100, 1200, 800)
        
        # 加载并设置应用图标
        icon_path = self.config_manager.get_app_icon()
        app_icon = load_app_icon(icon_path)
        self.setWindowIcon(app_icon)

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
            QComboBox::down-arrow {{
                image: url({_DOWN_ARROW_IMG});
            }}
        """)
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.plugin_tabs = QTabWidget()
        self.plugin_tabs.setTabPosition(QTabWidget.TabPosition.North)

        self.plugin_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {bg_main};
            }}
            QTabBar::tab {{
                background-color: {bg_tertiary};
                color: {text_secondary};
                padding: 3px 18px;
                border: 1px solid {border};
                border-bottom: none;
                margin-right: 2px;
                margin-top: 1px;
                border-top-left-radius: {border_radius_normal};
                border-top-right-radius: {border_radius_normal};
                font-size: {font_size_medium};
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {primary};
                color: #ffffff;
                border-color: {primary};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {bg_input};
                color: {text_primary};
            }}
        """)
        self.plugin_tabs.currentChanged.connect(self.on_plugin_tab_changed)
        layout.addWidget(self.plugin_tabs)

        self.create_menu_bar()
        self.create_tool_bar()
        self.create_status_bar()

    def create_menu_bar(self):
        menubar = self.menuBar()
        
        # 如果菜单已创建，先清除旧的菜单内容（防止重复）
        if self._menu_bar_created:
            menubar.clear()
        
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        text_primary = self._get_style('text', '#ffffff')
        border = self._get_style('border', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        primary = self._get_style('primary', '#007acc')
        border_radius_small = self._get_border_radius('sm', '4px')
        
        # 使用统一菜单 CSS
        menu_css = self.config_manager.get_menu_css()
        
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {bg_tertiary};
                color: {text_primary};
                border-bottom: 1px solid {border_light};
                padding: 2px;
            }}
            QMenuBar::item:selected {{
                background-color: {primary};
                color: #ffffff;
                border-radius: {border_radius_small};
                padding: 4px 8px;
            }}
            {menu_css}
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
        
        # 使用 QActionGroup 确保主题选项互斥（只能选一个）
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        
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
            self._theme_action_group.addAction(theme_action)
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

        # 工具注册菜单：位于「视图」与「帮助」之间，由各插件通过 register_menus 注册
        self._build_plugin_menus(menubar)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()

        license_action = QAction("开源许可", self)
        license_action.triggered.connect(self.show_license_info)
        help_menu.addAction(license_action)

        self._menu_bar_created = True

        # 工具标签栏（加载在菜单栏后）高度与菜单栏保持一致，中间以边框分隔线隔开
        if hasattr(self, 'plugin_tabs'):
            menu_bar_height = menubar.sizeHint().height()
            if menu_bar_height > 0:
                self.plugin_tabs.tabBar().setFixedHeight(menu_bar_height)

    def _build_plugin_menus(self, menubar):
        """构建插件注册的菜单。

        通过 PluginManager.collect_plugin_menus() 收集所有插件注册的菜单定义，
        并转换为 QMenu/QAction 添加到菜单栏。支持 action、submenu、separator，
        以及通过 group 字段实现单选互斥（QActionGroup）。
        """
        if not self.plugin_manager:
            return
        # 清理上一次构建遗留的 QActionGroup（主题切换重建菜单栏时）
        for old_group in getattr(self, '_plugin_menu_groups', []):
            old_group.deleteLater()
        self._plugin_menu_groups = []
        try:
            menus = self.plugin_manager.collect_plugin_menus()
        except Exception:
            return
        for menu_def in menus:
            title = menu_def.get('title', '')
            if not title:
                continue
            menu = menubar.addMenu(title)
            self._build_menu_items(menu, menu_def.get('items', []))

    def _build_menu_items(self, menu, items):
        """递归构建菜单项。

        Args:
            menu: 目标 QMenu。
            items: 菜单项定义列表，每项为 dict，type 字段区分 action/submenu/separator。
        """
        # 按组名缓存 QActionGroup，使同组 checkable action 表现为单选
        groups = {}
        for item in items:
            item_type = item.get('type')
            if item_type == 'separator':
                menu.addSeparator()
                continue
            if item_type == 'submenu':
                submenu = menu.addMenu(item.get('label', ''))
                self._build_menu_items(submenu, item.get('items', []))
                continue
            if item_type == 'action':
                action = QAction(item.get('label', ''), self)
                checkable = item.get('checkable', False)
                action.setCheckable(checkable)
                if checkable and item.get('checked', False):
                    action.setChecked(True)
                shortcut = item.get('shortcut')
                if shortcut:
                    action.setShortcut(shortcut)
                if not item.get('enabled', True):
                    action.setEnabled(False)
                # 互斥组处理：同组 checkable action 表现为单选
                group_name = item.get('group')
                if group_name:
                    if group_name not in groups:
                        group = QActionGroup(self)
                        group.setExclusive(True)
                        groups[group_name] = group
                        # 记录到实例，便于下次重建时清理
                        if not hasattr(self, '_plugin_menu_groups'):
                            self._plugin_menu_groups = []
                        self._plugin_menu_groups.append(group)
                    groups[group_name].addAction(action)
                callback = item.get('callback')
                if callback is not None:
                    # QAction.triggered 发射 checked 参数；不可勾选 action 仍可正常回调
                    action.triggered.connect(callback)
                menu.addAction(action)

    def create_tool_bar(self):
        if self._tool_bar_created:
            # 移除旧工具栏
            self.removeToolBar(self.toolbar)
        
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
                border-top: 1px solid {border_light};
                spacing: 6px;
                padding: 2px 8px;
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
                padding: 3px 10px;
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
        self._tool_bar_created = True

        # 工具栏高度与菜单栏保持一致，形成紧凑统一的顶部区域
        menubar = self.menuBar()
        if menubar is not None:
            menu_bar_height = menubar.sizeHint().height()
            if menu_bar_height > 0:
                self.toolbar.setFixedHeight(menu_bar_height)

    def build_plugin_actions(self):
        """根据插件配置文件动态构建菜单和工具栏"""
        self.toolbar.clear()

        has_actions = False
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
                has_actions = True

            if toolbar_items:
                self.toolbar.addSeparator()

        # 无工具栏项时隐藏工具栏，避免菜单栏下方出现空白行
        self.toolbar.setVisible(has_actions)

    def create_status_bar(self):
        if self._status_bar_created:
            return  # 状态栏只创建一次
        
        self.status_bar = QStatusBar()
        primary = self._get_style('primary', '#007acc')
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {primary};
                color: #ffffff;
            }}
            QStatusBar::item {{ border: none; }}
        """)
        self.status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self.status_bar)

        # 框架状态（左侧）：显示当前插件名 + 框架就绪状态
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #ffffff;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_bar.addWidget(self.status_label)

        # 工具状态（左侧）：显示当前工具上报的状态，紧跟框架状态之后
        self.tool_status_label = QLabel("")
        self.tool_status_label.setStyleSheet("color: #ffffff; margin-left: 6px;")
        self.tool_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_bar.addWidget(self.tool_status_label)

        # 注册统一状态接口回调
        self.plugin_manager.set_status_callback(self._on_tool_status_updated)
        self._status_bar_created = True

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
            {"bg": "#2a5d7e", "border": "#3a8fd4"},  # 终端 - 柔和深蓝
            {"bg": "#1a5d3e", "border": "#28a745"},  # 编译工具 - 深绿
            {"bg": "#3d2b1f", "border": "#d97706"},  # 脚本管理 - 橙色
            {"bg": "#2d3a4a", "border": "#569cd6"},  # 计算工具 - 浅蓝
            {"bg": "#3d1f2b", "border": "#f44747"},  # 远程命令 - 红色
            {"bg": "#1a3d2e", "border": "#4ec9b0"},  # 协议测试 - 青绿
            {"bg": "#3d2b4a", "border": "#a06bff"},  # 调测工具 - 紫色
        ]

        # 为每个插件创建标签页
        for index, plugin_info in enumerate(plugin_configs):
            plugin_name = plugin_info.get("name", "")
            
            # 从插件单独配置文件获取 display_name
            plugin_config = self.config_manager.get_plugin_config(plugin_name)
            display_name = plugin_config.get("display_name", plugin_name) if plugin_config else plugin_name
            
            if plugin_name in self.plugin_manager.plugins:
                # 调测工具默认不显示 tab，通过菜单使能
                if plugin_name == 'DebugTool':
                    # 只创建 widget 但不添加到 tab
                    plugin = self.plugin_manager.plugins[plugin_name]
                    widget = plugin.get_widget()
                    self.plugin_widgets[plugin_name] = widget
                    continue

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
        # 插件加载完成后重建菜单栏，使工具注册的菜单生效
        # （init_ui 阶段构建菜单栏时插件尚未加载，collect_plugin_menus 返回空）
        if self._menu_bar_created:
            self.create_menu_bar()

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
                    # 刷新工具状态显示（切换时显示当前插件最新状态）
                    self._refresh_tool_status()
                    break

    def _on_tool_status_updated(self, plugin_name, status_text):
        """工具状态更新回调：拼接工具状态与框架状态统一显示

        只有当前激活的插件状态才显示在状态栏；非激活插件的状态被缓存，
        切换到该插件时再展示。
        """
        if plugin_name == self.current_plugin_name:
            self.tool_status_label.setText(status_text)
        # 非当前插件：缓存即可，切换时由 _refresh_tool_status 刷新

    def _refresh_tool_status(self):
        """刷新当前插件的状态显示"""
        if not self.current_plugin_name:
            self.tool_status_label.setText("")
            return
        status = self.plugin_manager.get_tool_status(self.current_plugin_name)
        self.tool_status_label.setText(status)

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
        """更新主题UI（在主线程中执行）- 只刷新样式，不重建控件"""
        self._color_scheme = self.config_manager.get_color_scheme()
        
        # 刷新主窗口及框架控件样式
        self._refresh_frame_styles()
        
        # 刷新所有插件控件样式
        self._refresh_plugin_styles()
        
        # 更新主题勾选状态
        if hasattr(self, '_theme_actions'):
            current_theme = self.config_manager.get_current_theme()
            for tid, action in self._theme_actions.items():
                action.setChecked(tid == current_theme)

    def _refresh_frame_styles(self):
        """刷新框架控件（菜单栏、工具栏、状态栏、标签页）的样式"""
        bg_main = self._get_style('bg-main', '#1e1e1e')
        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        bg_input = self._get_style('bg-input', '#3c3c3c')
        border = self._get_style('border', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        text_primary = self._get_style('text', '#ffffff')
        text_secondary = self._get_style('text-secondary', '#cccccc')
        primary = self._get_style('primary', '#007acc')
        font_size_medium = self._get_font_size('size-lg', '13px')
        font_size_normal = self._get_font_size('size-md', '12px')
        border_radius_small = self._get_border_radius('sm', '4px')
        border_radius_normal = self._get_border_radius('md', '6px')
        
        # 刷新主窗口样式
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {bg_main};
            }}
        """)
        
        # 刷新中央控件
        if hasattr(self, 'central_widget'):
            self.central_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {bg_main};
                }}
            """)
        
        # 刷新插件标签页样式（统一使用主题配色，不区分标签页）
        self.plugin_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {bg_main};
            }}
            QTabBar::tab {{
                background-color: {bg_tertiary};
                color: {text_secondary};
                padding: 3px 18px;
                border: 1px solid {border};
                border-bottom: none;
                margin-right: 2px;
                margin-top: 1px;
                border-top-left-radius: {border_radius_normal};
                border-top-right-radius: {border_radius_normal};
                font-size: {font_size_medium};
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {primary};
                color: #ffffff;
                border-color: {primary};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {bg_input};
                color: {text_primary};
            }}
        """)
        
        # 刷新菜单栏样式
        if self._menu_bar_created:
            self.create_menu_bar()
        
        # 刷新工具栏样式
        if self._tool_bar_created:
            self.create_tool_bar()
            self.build_plugin_actions()
        
        # 刷新状态栏样式
        if self._status_bar_created:
            primary = self._get_style('primary', '#007acc')
            self.status_bar.setStyleSheet(f"""
                QStatusBar {{
                    background-color: {primary};
                    color: #ffffff;
                }}
                QStatusBar::item {{ border: none; }}
            """)
            self.status_label.setStyleSheet("color: #ffffff;")
            self.tool_status_label.setStyleSheet("color: #ffffff; margin-left: 6px;")
    
    def _refresh_plugin_styles(self):
        """通知所有插件控件刷新样式"""
        for plugin_name, widget in self.plugin_widgets.items():
            if hasattr(widget, 'refresh_theme_styles'):
                try:
                    widget.refresh_theme_styles()
                except Exception:
                    pass
    
    def show_about(self):
        """显示关于对话框：仅包含版本号与主要使用场景。"""
        QMessageBox.about(
            self,
            "关于 MyDesk",
            f"""
            <div style='text-align:center;'>
                <h2 style='margin-bottom:0;'>MyDesk</h2>
                <p style='margin-top:2px;color:#666;'>版本 {self._app_version}</p>
            </div>
            <hr>
            <p><b>主要使用场景</b></p>
            <ul>
                <li>远程终端管理（SSH / Telnet / Serial 串口）</li>
                <li>SFTP 文件传输与目录浏览</li>
                <li>脚本批量执行与管理</li>
                <li>远程编译与构建</li>
                <li>计算器与数制 / 字符串转换</li>
            </ul>
            """
        )

    def show_license_info(self):
        """显示开源许可信息对话框。

        基于 MyDesk 实际使用的第三方开源依赖生成简单的许可说明。
        """
        # 依赖列表：名称、许可证、官方主页
        # 注：pyserial 实际为 BSD-3-Clause（非 GPL），此处以 PyPI 元数据为准
        licenses = [
            ("PyQt6", "GPL v3 / 商业许可",
             "https://www.riverbankcomputing.com/software/pyqt/"),
            ("paramiko", "LGPL v2.1",
             "https://www.paramiko.org/"),
            ("pyserial", "BSD-3-Clause",
             "https://github.com/pyserial/pyserial"),
        ]

        lines = []
        lines.append("<div style='text-align:center;'>")
        lines.append("<h2 style='margin-bottom:2px;'>开源许可</h2>")
        lines.append("<p style='margin-top:0;color:#666;'>MyDesk 使用的第三方开源组件</p>")
        lines.append("</div><hr>")

        for name, lic, url in licenses:
            lines.append(
                f"<p style='margin:8px 0;'>"
                f"<b>{name}</b> — {lic}<br>"
                f"<span style='color:#666;'>主页：</span>"
                f"<a href='{url}'>{url}</a>"
                f"</p>"
            )

        lines.append("<hr>")
        lines.append(
            "<p style='color:#666;font-size:11px;'>"
            "以上许可信息均来自各项目的官方元数据。各组件的完整许可文本"
            "请以对应项目源代码中的 LICENSE 文件为准。"
            "</p>"
        )

        # 使用自定义对话框以支持富文本与链接交互
        dialog = QDialog(self)
        dialog.setWindowTitle("开源许可")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml("".join(lines))
        layout.addWidget(text_edit)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        dialog.exec()

    def set_status(self, message):
        self.status_label.setText(message)