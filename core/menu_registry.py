"""菜单注册机制

框架提供的菜单注册器，允许插件按需向主窗口的「设置」菜单注册设置项。

设计要点：
- 每个插件通过实现 ``register_settings(registry)`` 方法声明自身设置项。
- 插件调用 ``registry.add_settings_menu(plugin_name, title)`` 声明
  「设置 → <工具名>」分组，之后的 ``add_action/add_submenu/add_separator``
  都作用于该分组；框架统一挂载，插件不再占用菜单栏顶层。
- ``MenuRegistry`` 收集的是结构化数据（不依赖 Qt 对象），由 MainWindow 在
  构建菜单栏时统一转换为 QMenu/QAction，便于主题切换时重建。
- 支持普通 action、可勾选 action（checkable）、子菜单（submenu，可包含互斥项组）、
  分隔符。

示例::

    def register_settings(self, registry):
        widget = self.get_widget()
        registry.add_settings_menu(self.name, self.display_name) \
            .add_action("刷新列表", widget.load_connections, shortcut="F5") \
            .add_separator() \
            .add_submenu("字体大小", items=[
                {"label": "12", "callback": lambda checked: widget.set_font_size(12),
                 "checkable": True, "checked": widget.current_font_size == 12, "group": "font_size"},
            ]) \
            .add_action("颜色显示", widget.toggle_color_display,
                        checkable=True, checked=widget.color_enabled)
"""


class MenuRegistry:
    """设置注册器：收集插件注册的设置分组。

    注册结果为纯数据结构（list of dict），不持有任何 Qt 对象，
    以便在主题切换重建菜单栏时重新收集并构建。
    """

    def __init__(self):
        # 已注册的设置分组列表（「设置 → <工具名>」），每项格式：
        # {
        #     'plugin_name': str,         # 注册方插件名
        #     'title': str,               # 分组标题（如 "终端"）
        #     'items': [item_dict, ...]   # 设置项定义列表
        # }
        self._settings = []
        # 当前正在构建的菜单引用（用于链式 add_action/add_submenu/add_separator）
        self._current_menu = None

    def add_settings_menu(self, plugin_name, title):
        """声明「设置 → <title>」分组，并设为当前活动菜单。

        同一插件重复调用时复用已有分组，方便插件分批注册设置项。

        Args:
            plugin_name: 注册方插件名（用于分组去重）。
            title: 设置子菜单标题，一般为插件的 display_name，如 "终端"。

        Returns:
            self（支持链式调用）。
        """
        for menu_def in self._settings:
            if menu_def['plugin_name'] == plugin_name:
                self._current_menu = menu_def
                return self
        menu_def = {
            'plugin_name': plugin_name,
            'title': title,
            'items': []
        }
        self._settings.append(menu_def)
        self._current_menu = menu_def
        return self

    def add_action(self, label, callback, checkable=False, checked=False,
                   shortcut=None, group=None, enabled=True):
        """向当前菜单添加一个 action。

        Args:
            label: 菜单项显示文本。
            callback: 触发回调，签名 callback(checked: bool) -> None。
            checkable: 是否可勾选。
            checked: 初始是否勾选。
            shortcut: 快捷键字符串，如 "F5" 或 "Ctrl+Shift+F"。
            group: 互斥组名（同组内的 checkable action 在 UI 上表现为单选）。
            enabled: 是否可用。

        Returns:
            self。
        """
        self._ensure_current_menu()
        self._current_menu['items'].append({
            'type': 'action',
            'label': label,
            'callback': callback,
            'checkable': checkable,
            'checked': checked,
            'shortcut': shortcut,
            'group': group,
            'enabled': enabled,
        })
        return self

    def add_submenu(self, label, items=None):
        """向当前菜单添加一个子菜单。

        Args:
            label: 子菜单标题。
            items: 子菜单项列表，每项为 dict，支持 add_action 的所有字段。
                   若为 None 则返回子菜单 builder 以便继续链式调用。

        Returns:
            若 items 为 None，返回 _SubmenuBuilder 以便继续链式添加；
            否则返回 self。
        """
        self._ensure_current_menu()
        submenu_def = {
            'type': 'submenu',
            'label': label,
            'items': items or []
        }
        self._current_menu['items'].append(submenu_def)
        if items is None:
            return _SubmenuBuilder(self, submenu_def)
        return self

    def add_separator(self):
        """向当前菜单添加分隔符。

        Returns:
            self。
        """
        self._ensure_current_menu()
        self._current_menu['items'].append({'type': 'separator'})
        return self

    def get_settings(self):
        """获取所有已注册的设置分组定义（「设置 → <工具名>」）。"""
        return self._settings

    def clear(self):
        """清空所有已注册的设置分组。"""
        self._settings.clear()
        self._current_menu = None

    def _ensure_current_menu(self):
        if self._current_menu is None:
            raise RuntimeError(
                "必须先调用 add_settings_menu() 声明设置分组后再添加设置项"
            )


class _SubmenuBuilder:
    """子菜单构建器：支持以链式调用向子菜单添加项。

    由 MenuRegistry.add_submenu(items=None) 返回，调用 end() 后返回父 registry。
    """

    def __init__(self, registry, submenu_def):
        self._registry = registry
        self._submenu_def = submenu_def

    def add_action(self, label, callback, checkable=False, checked=False,
                   shortcut=None, group=None, enabled=True):
        self._submenu_def['items'].append({
            'type': 'action',
            'label': label,
            'callback': callback,
            'checkable': checkable,
            'checked': checked,
            'shortcut': shortcut,
            'group': group,
            'enabled': enabled,
        })
        return self

    def add_separator(self):
        self._submenu_def['items'].append({'type': 'separator'})
        return self

    def add_submenu(self, label, items=None):
        nested = {'type': 'submenu', 'label': label, 'items': items or []}
        self._submenu_def['items'].append(nested)
        if items is None:
            return _SubmenuBuilder(self._registry, nested)
        return self

    def end(self):
        """结束子菜单构建，返回父 registry。"""
        return self._registry
