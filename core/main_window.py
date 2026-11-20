import json
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget,
    QMenuBar, QMenu, QStatusBar, QLabel,
    QToolBar,
    QDialog, QTextEdit, QPushButton
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QRectF
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QColor, QPainter
from utils import dialog_helper
from utils.config_manager import ConfigManager
from utils.logger import Logger
from utils.icon_generator import load_app_icon


class ToolMenuBar(QMenuBar):
    """带工具选中高亮的菜单栏。

    Qt6 的 ``QMenuBar::item:checked`` 在 Windows 样式下不生效，这里在菜单栏
    绘制完成后，按当前工具项的 actionGeometry 补画主色背景并重绘白色文字，
    保证深色/浅色主题下选中态都清晰可见。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlight_action = None
        self._highlight_color = '#007acc'
        self._highlight_text_color = '#ffffff'

    def set_highlight(self, action, color, text_color='#ffffff'):
        """设置需要高亮的工具项（None 表示不高亮）。"""
        self._highlight_action = action
        self._highlight_color = color
        self._highlight_text_color = text_color
        self.update()

    def clear_highlight(self):
        self._highlight_action = None
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        action = self._highlight_action
        if action is None or not action.isVisible():
            return
        rect = self.actionGeometry(action)
        if rect.isNull() or rect.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._highlight_color))
        painter.drawRoundedRect(QRectF(rect).adjusted(1, 3, -1, -3), 4, 4)
        font = action.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(self._highlight_text_color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, action.iconText())
        painter.end()


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
        # 暴露主窗口给插件（如调测工具按需显示/隐藏自身视图）
        self.plugin_manager.main_window = self
        self.config_manager = config_manager or ConfigManager(
            ConfigManager.get_default_config_dir()
        )
        self._color_scheme = self.config_manager.get_color_scheme()
        self.plugin_widgets = {}
        self.current_plugin_name = None
        # 工具项：按 plugin.json 顺序维护可见工具，QActionGroup 保证单选
        self._tool_plugin_order = []
        self._tool_actions = {}
        self._tool_action_group = None
        self._tool_separator_action = None
        self._menu_bar = None
        self._theme_worker = None
        self._menu_bar_created = False
        self._tool_bar_created = False
        self._status_bar_created = False
        # MyDesk 版本号（统一管理，用于「关于」与状态栏显示）
        self._app_version = "1.0.0"

        # 工具切换项直接展开在菜单栏上，使用支持选中高亮的自定义菜单栏
        self.setMenuBar(ToolMenuBar(self))

        self.init_ui()
        self.load_plugins()
    
    def _get_style(self, key, default=None):
        """获取样式配置（直接从 config_manager 实时获取，避免缓存不一致）"""
        if self.config_manager:
            return self.config_manager.get_color(key, default)
        return default

    def _status_bar_colors(self):
        """状态栏配色（深色主色底白字，浅色浅底深字），来自主题组件 status-bar"""
        if self.config_manager:
            bg = self.config_manager.get_component_style_value(
                'status-bar', 'bg', self._get_style('primary', '#007acc'))
            fg = self.config_manager.get_component_style_value(
                'status-bar', 'color', '#ffffff')
            return bg, fg
        return '#007acc', '#ffffff'
    
    def _get_font_size(self, key, default='12px'):
        """获取字体大小"""
        return self.config_manager.get_font_size(key, default)
    
    def _get_border_radius(self, key, default='4px'):
        """获取边框圆角"""
        return self.config_manager.get_border_radius(key, default)

    def _get_on_primary_color(self, default='#ffffff'):
        """主色背景上的文字颜色，取主题 components.button.color"""
        if self.config_manager:
            return self.config_manager.get_component_style_value(
                'button', 'color', default)
        return default

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
            {self.config_manager.get_combo_arrow_css()}
        """)
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具视图容器：不再使用顶部标签栏，工具切换统一走菜单栏末尾的工具项，
        # 省掉整条标签栏高度的占用，让终端显示区更高。
        self.plugin_stack = QStackedWidget()
        self.plugin_stack.setStyleSheet(f"""
            QStackedWidget {{
                background-color: {bg_main};
            }}
        """)
        layout.addWidget(self.plugin_stack)

        self.create_menu_bar()
        self.create_tool_bar()
        self.create_status_bar()

    def create_menu_bar(self):
        menubar = self.menuBar()

        # 清掉自绘高亮引用，避免指向即将被销毁的 QAction
        if isinstance(menubar, ToolMenuBar):
            menubar.clear_highlight()

        # 如果菜单已创建，先清除旧的菜单内容（防止重复）
        if self._menu_bar_created:
            menubar.clear()
            # QMenuBar.clear() 只解除关联、不销毁菜单；显式回收上一轮构建的
            # 菜单树，菜单内的 QAction/QActionGroup 随之释放，避免主题切换反复重建时累积
            for child in menubar.children():
                if isinstance(child, QMenu):
                    child.deleteLater()

        bg_tertiary = self._get_style('bg-tertiary', '#2d2d30')
        text_primary = self._get_style('text', '#ffffff')
        border = self._get_style('border', '#3c3c3c')
        border_light = self._get_style('border-light', '#5a5a5d')
        primary = self._get_style('primary', '#007acc')
        on_primary = self._get_on_primary_color()
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
                color: {on_primary};
                border-radius: {border_radius_small};
                padding: 4px 8px;
            }}
            QMenuBar::item:disabled {{
                color: {border_light};
                background: transparent;
            }}
            {menu_css}
        """)

        # 文件菜单
        self.file_menu = menubar.addMenu("文件(&F)")

        exit_action = QAction("退出", self.file_menu)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.file_menu.addAction(exit_action)

        # 视图菜单
        self.view_menu = menubar.addMenu("视图(&V)")

        fullscreen_action = QAction("全屏", self.view_menu)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.view_menu.addAction(fullscreen_action)

        # 平台级「设置」菜单：主题设置 + 各插件设置分组
        self._build_settings_menu(menubar)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于", help_menu)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()

        license_action = QAction("开源许可", help_menu)
        license_action.triggered.connect(self.show_license_info)
        help_menu.addAction(license_action)

        # 工具切换项：位于所有菜单之后，前置一个「|」分隔符
        self._create_tool_actions(menubar)

        self._menu_bar_created = True

    def _plugin_display_name(self, plugin_name):
        """获取插件的显示名称。

        优先取 plugin.json 中的 display_name（所有插件都有），避免插件专属
        配置文件缺失时回退成内部类名；其次取插件配置，最后才用内部名。
        """
        plugin_info = self.config_manager.get_plugin(plugin_name)
        if plugin_info:
            display_name = plugin_info.get("display_name")
            if display_name:
                return display_name
        plugin_config = self.config_manager.get_plugin_config(plugin_name)
        if plugin_config and plugin_config.get("display_name"):
            return plugin_config["display_name"]
        return plugin_name

    def _create_tool_actions(self, menubar):
        """把各工具直接展开为菜单栏项，替代原来的「工具」子菜单。

        顺序与 plugin.json 的加载顺序一致，并用 QActionGroup 互斥；
        工具项之前放一个禁用状态的「|」作为菜单栏分隔符。
        """
        self._menu_bar = menubar

        # 重建菜单栏时清理上一轮的工具项、分隔符与互斥组
        if self._tool_action_group is not None:
            self._tool_action_group.deleteLater()
        for old_action in self._tool_actions.values():
            old_action.deleteLater()
        if self._tool_separator_action is not None:
            self._tool_separator_action.deleteLater()
        self._tool_action_group = QActionGroup(self)
        self._tool_action_group.setExclusive(True)

        separator = QAction("|", menubar)
        separator.setEnabled(False)
        self._tool_separator_action = separator
        menubar.addAction(separator)

        self._tool_actions = {}
        for plugin_name in self._tool_plugin_order:
            self._add_tool_action(plugin_name)

        self._sync_tool_highlight()

    def _add_tool_action(self, plugin_name):
        """在菜单栏末尾追加一个工具切换项（互斥可勾选）。"""
        if self._tool_action_group is None or plugin_name in self._tool_actions:
            return
        if self._menu_bar is None:
            return
        action = QAction(self._plugin_display_name(plugin_name), self._menu_bar)
        action.setCheckable(True)
        action.setChecked(plugin_name == self.current_plugin_name)
        action.triggered.connect(
            lambda checked, pn=plugin_name: self.switch_to_plugin(pn)
        )
        self._tool_action_group.addAction(action)
        self._menu_bar.addAction(action)
        self._tool_actions[plugin_name] = action

    def _sync_tool_highlight(self):
        """把菜单栏的选中高亮同步到当前工具。"""
        if isinstance(self._menu_bar, ToolMenuBar):
            action = self._tool_actions.get(self.current_plugin_name)
            self._menu_bar.set_highlight(
                action,
                self._get_style('primary', '#007acc'),
                self._get_on_primary_color(),
            )

    def _build_settings_menu(self, menubar):
        """构建平台级「设置」菜单。

        结构为：主题设置 → 分隔符 → 各插件设置分组（「设置 → <工具名>」）。
        插件通过 ``register_settings(registry)`` 声明设置项，框架统一挂载，
        插件不再各自占用菜单栏顶层。
        """
        settings_menu = menubar.addMenu("设置(&S)")

        # 主题设置子菜单（原有入口迁入）
        self.theme_menu = settings_menu.addMenu("主题")
        self._theme_actions = {}

        # 使用 QActionGroup 确保主题选项互斥（只能选一个）；
        # 组与项都以子菜单为父对象，随菜单重建一并释放
        self._theme_action_group = QActionGroup(self.theme_menu)
        self._theme_action_group.setExclusive(True)

        current_theme = self.config_manager.get_current_theme()
        for theme_info in self.config_manager.get_theme_list():
            theme_action = QAction(theme_info['name'], self.theme_menu)
            theme_action.setCheckable(True)
            theme_action.setChecked(theme_info['id'] == current_theme)
            theme_action.triggered.connect(
                lambda checked, tid=theme_info['id']: self.change_theme(tid)
            )
            self._theme_action_group.addAction(theme_action)
            self.theme_menu.addAction(theme_action)
            self._theme_actions[theme_info['id']] = theme_action

        # 主题设置与工具设置之间的分隔符
        settings_menu.addSeparator()

        if not self.plugin_manager:
            return
        try:
            groups = self.plugin_manager.collect_plugin_settings()
        except Exception as e:
            Logger.get_instance().error(f"收集插件设置失败: {e}", exc_info=True)
            return
        for group_def in groups:
            title = group_def.get('title', '')
            if not title:
                continue
            submenu = settings_menu.addMenu(title)
            try:
                self._build_menu_items(submenu, group_def.get('items', []))
            except Exception as e:
                Logger.get_instance().error(
                    f"构建设置菜单失败: {title}: {e}", exc_info=True
                )

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
                # 菜单项以所属菜单为父对象，随菜单重建一并释放
                action = QAction(item.get('label', ''), menu)
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
                        group = QActionGroup(menu)
                        group.setExclusive(True)
                        groups[group_name] = group
                    groups[group_name].addAction(action)
                callback = item.get('callback')
                if callback is not None:
                    # QAction.triggered 发射 checked 参数；不可勾选 action 仍可正常回调
                    action.triggered.connect(callback)
                menu.addAction(action)

    def create_tool_bar(self):
        if self._tool_bar_created:
            # 移除并回收旧工具栏（主题切换会重建工具栏，避免旧对象累积）
            self.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
        
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
        """根据插件配置文件动态构建工具栏"""
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
        status_bg, status_fg = self._status_bar_colors()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {status_bg};
                color: {status_fg};
            }}
            QStatusBar::item {{ border: none; }}
        """)
        self.status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self.status_bar)

        # 框架状态（左侧）：显示当前插件名 + 框架就绪状态
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(f"color: {status_fg};")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_bar.addWidget(self.status_label)

        # 工具状态（左侧）：显示当前工具上报的状态，紧跟框架状态之后
        self.tool_status_label = QLabel("")
        self.tool_status_label.setStyleSheet(f"color: {status_fg}; margin-left: 6px;")
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

        # 清空工具视图容器与插件缓存
        while self.plugin_stack.count():
            self.plugin_stack.removeWidget(self.plugin_stack.widget(0))
        self.plugin_widgets.clear()
        self._tool_plugin_order = []
        self.current_plugin_name = None

        # 按 plugin.json 顺序创建插件界面并加入工具容器
        for plugin_info in plugin_configs:
            plugin_name = plugin_info.get("name", "")

            if plugin_name not in self.plugin_manager.plugins:
                continue

            plugin = self.plugin_manager.plugins[plugin_name]
            widget = plugin.get_widget()

            # 无界面插件（如 RemoteCmd 基础服务）不占用工具位
            if widget is None:
                continue

            self.plugin_widgets[plugin_name] = widget

            # 调测工具默认不占工具位，通过「设置 → 调测工具」按需显示
            if plugin_name == 'DebugTool':
                continue

            self.plugin_stack.addWidget(widget)
            self._tool_plugin_order.append(plugin_name)

        # 恢复调测工具上次的显示状态（持久化在 debugtool_config.json 的 settings.visible）
        debug_plugin = self.plugin_manager.plugins.get('DebugTool')
        if debug_plugin is not None and getattr(debug_plugin, '_tab_visible', False):
            self.add_plugin_view('DebugTool')

        # 根据插件配置动态构建工具栏
        self.build_plugin_actions()
        # 插件加载完成后重建菜单栏，使工具菜单与插件注册的设置项生效
        # （init_ui 阶段构建菜单栏时插件尚未加载，collect_plugin_settings 返回空）
        if self._menu_bar_created:
            self.create_menu_bar()

        # 默认选中第一个工具（与原标签栏默认选中第一页一致）
        if self._tool_plugin_order:
            self.switch_to_plugin(self._tool_plugin_order[0])

    def _activate_plugin(self, plugin_name):
        """同步当前工具的状态：状态栏文本、工具状态缓存、菜单选中标记与焦点。"""
        if plugin_name not in self.plugin_widgets:
            return
        self.current_plugin_name = plugin_name
        if self._status_bar_created:
            self.status_label.setText(f"当前插件: {self._plugin_display_name(plugin_name)}")
            # 切换时显示该工具最新上报的状态
            self._refresh_tool_status()
        action = self._tool_actions.get(plugin_name)
        if action is not None and not action.isChecked():
            action.setChecked(True)
        self._sync_tool_highlight()
        self.plugin_widgets[plugin_name].setFocus()

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
        """切换到指定工具（工具菜单、工具栏与插件内部共用）。"""
        widget = self.plugin_widgets.get(plugin_name)
        if widget is None or self.plugin_stack.indexOf(widget) < 0:
            return
        self.plugin_stack.setCurrentWidget(widget)
        self._activate_plugin(plugin_name)

    def add_plugin_view(self, plugin_name):
        """把已加载插件加入工具区域与菜单栏工具项（调测工具按需显示时使用）。"""
        widget = self.plugin_widgets.get(plugin_name)
        if widget is None:
            return False
        if self.plugin_stack.indexOf(widget) < 0:
            self.plugin_stack.addWidget(widget)
            if plugin_name not in self._tool_plugin_order:
                self._tool_plugin_order.append(plugin_name)
            self._add_tool_action(plugin_name)
        self.switch_to_plugin(plugin_name)
        return True

    def remove_plugin_view(self, plugin_name):
        """把插件移出工具区域与菜单栏工具项（调测工具隐藏时使用）。

        仅移出视图，不从 plugin_widgets 删除，便于下次重新显示。
        """
        widget = self.plugin_widgets.get(plugin_name)
        if widget is None or self.plugin_stack.indexOf(widget) < 0:
            return False
        was_current = self.plugin_stack.currentWidget() is widget
        self.plugin_stack.removeWidget(widget)
        if plugin_name in self._tool_plugin_order:
            self._tool_plugin_order.remove(plugin_name)

        action = self._tool_actions.pop(plugin_name, None)
        if action is not None:
            if self._tool_action_group is not None:
                self._tool_action_group.removeAction(action)
            if self._menu_bar is not None:
                self._menu_bar.removeAction(action)
            action.deleteLater()

        if was_current:
            if self._tool_plugin_order:
                self.switch_to_plugin(self._tool_plugin_order[0])
            else:
                self.current_plugin_name = None
                self._sync_tool_highlight()
                if self._status_bar_created:
                    self.status_label.setText("就绪")
                    self.tool_status_label.setText("")
        return True

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
        """刷新框架控件（菜单栏、工具栏、状态栏、工具视图）的样式"""
        bg_main = self._get_style('bg-main', '#1e1e1e')

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
                {self.config_manager.get_combo_arrow_css()}
            """)

        # 工具视图容器的背景色
        if hasattr(self, 'plugin_stack'):
            self.plugin_stack.setStyleSheet(f"""
                QStackedWidget {{
                    background-color: {bg_main};
                }}
            """)
        
        # 刷新菜单栏样式（同时重建菜单栏，并同步当前工具项的选中标记）
        if self._menu_bar_created:
            self.create_menu_bar()
        
        # 刷新工具栏样式
        if self._tool_bar_created:
            self.create_tool_bar()
            self.build_plugin_actions()
        
        # 刷新状态栏样式
        if self._status_bar_created:
            status_bg, status_fg = self._status_bar_colors()
            self.status_bar.setStyleSheet(f"""
                QStatusBar {{
                    background-color: {status_bg};
                    color: {status_fg};
                }}
                QStatusBar::item {{ border: none; }}
            """)
            self.status_label.setStyleSheet(f"color: {status_fg};")
            self.tool_status_label.setStyleSheet(f"color: {status_fg}; margin-left: 6px;")
    
    def _refresh_plugin_styles(self):
        """通知所有插件控件刷新样式。

        单个插件刷新失败只记录日志并在状态栏提示，不中断其它插件的刷新。
        """
        logger = Logger.get_instance()
        failed_plugins = []
        for plugin_name, widget in self.plugin_widgets.items():
            if hasattr(widget, 'refresh_theme_styles'):
                try:
                    widget.refresh_theme_styles()
                except Exception as exc:
                    failed_plugins.append(plugin_name)
                    logger.error(
                        f"插件 {plugin_name} 主题刷新失败: {exc}", exc_info=True
                    )
        if failed_plugins:
            message = "主题刷新失败：" + "、".join(failed_plugins)
            logger.warning(message)
            if self._status_bar_created:
                self.status_bar.showMessage(message, 8000)
    
    def show_about(self):
        """显示关于对话框：仅包含版本号与主要使用场景。"""
        text_hint = self.config_manager.get_color('text-hint', '#858585')
        dialog_helper.show_info(
            self,
            "关于 MyDesk",
            f"""
            <div style='text-align:center;'>
                <h2 style='margin-bottom:0;'>MyDesk</h2>
                <p style='margin-top:2px;color:{text_hint};'>版本 {self._app_version}</p>
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
            """,
            self.config_manager,
            rich_text=True
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

        text_hint = self.config_manager.get_color('text-hint', '#858585')
        bg_input = self.config_manager.get_color('bg-input', '#454545')
        text_primary = self.config_manager.get_color('text', '#e0e0e0')
        border = self.config_manager.get_color('border', '#3c3c3c')

        lines = []
        lines.append("<div style='text-align:center;'>")
        lines.append("<h2 style='margin-bottom:2px;'>开源许可</h2>")
        lines.append(
            f"<p style='margin-top:0;color:{text_hint};'>"
            "MyDesk 使用的第三方开源组件</p>"
        )
        lines.append("</div><hr>")

        for name, lic, url in licenses:
            lines.append(
                f"<p style='margin:8px 0;'>"
                f"<b>{name}</b> — {lic}<br>"
                f"<span style='color:{text_hint};'>主页：</span>"
                f"<a href='{url}'>{url}</a>"
                f"</p>"
            )

        lines.append("<hr>")
        lines.append(
            f"<p style='color:{text_hint};font-size:11px;'>"
            "以上许可信息均来自各项目的官方元数据。各组件的完整许可文本"
            "请以对应项目源代码中的 LICENSE 文件为准。"
            "</p>"
        )

        # 使用自定义对话框以支持富文本与链接交互
        dialog = QDialog(self)
        dialog.setWindowTitle("开源许可")
        dialog.setMinimumWidth(460)
        dialog_helper.apply_dialog_theme(dialog, self.config_manager)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet(
            f"QTextEdit {{ background-color: {bg_input}; color: {text_primary}; "
            f"border: 1px solid {border}; }}"
        )
        text_edit.setHtml("".join(lines))
        layout.addWidget(text_edit)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(self.config_manager.get_button_css('button-secondary'))
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        dialog.exec()

    def set_status(self, message):
        self.status_label.setText(message)