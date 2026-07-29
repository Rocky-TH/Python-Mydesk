"""菜单注册机制

框架提供的菜单注册器，允许插件按需向主窗口菜单栏注册菜单项。

设计要点：
- 每个插件通过实现 ``register_menus(registry)`` 方法注册自身的菜单。
- ``MenuRegistry`` 收集所有插件注册的菜单定义（结构化数据，不依赖 Qt 对象），
  由 MainWindow 在构建菜单栏时统一转换为 QMenu/QAction，便于主题切换时重建。
- 支持普通 action、可勾选 action（checkable）、子菜单（submenu，可包含互斥项组）、分隔符。

示例::

    def register_menus(self, registry):
        widget = self.get_widget()
        registry.add_menu(self.name, "终端(&T)") \
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
    """菜单注册器：收集插件注册的菜单定义。

    注册结果为纯数据结构（list of dict），不持有任何 Qt 对象，
    以便在主题切换重建菜单栏时重新收集并构建。
    """

    def __init__(self):
        # 已注册的顶级菜单列表，每项格式：
        # {
        #     'plugin_name': str,         # 注册方插件名
        #     'title': str,               # 菜单标题（如 "终端(&T)"）
        #     'items': [item_dict, ...]   # 菜单项定义列表
        # }
        self._menus = []
        # 当前正在构建的菜单引用（用于链式 add_action/add_submenu/add_separator）
        self._current_menu = None

    def add_menu(self, plugin_name, title):
        """注册一个顶级菜单，并设为当前活动菜单（后续 add_* 将作用于该菜单）。

        Args:
            plugin_name: 注册方插件名（用于日志/去重/排序）。
            title: 菜单标题，建议包含助记符，如 "终端(&T)"。

        Returns:
            self（支持链式调用）。
        """
        menu_def = {
            'plugin_name': plugin_name,
            'title': title,
            'items': []
        }
        self._menus.append(menu_def)
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

    def get_menus(self):
        """获取所有已注册的顶级菜单定义。"""
        return self._menus

    def clear(self):
        """清空所有注册的菜单。"""
        self._menus.clear()
        self._current_menu = None

    def _ensure_current_menu(self):
        if self._current_menu is None:
            raise RuntimeError("必须先调用 add_menu() 注册顶级菜单后再添加菜单项")


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
