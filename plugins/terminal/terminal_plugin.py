"""终端插件入口

``TerminalPlugin`` 的实现位于 ``terminal_widget.py``。本文件只负责把终端原有
菜单内容迁移到平台级「设置 → 终端」下，不再占用菜单栏顶层。
"""

from .terminal_widget import TerminalPlugin as _BaseTerminalPlugin

__all__ = ['TerminalPlugin']


class _SettingsRegistryProxy:
    """把插件的顶层菜单注册重定向到已激活的设置分组。

    ``TerminalWidget.register_menus`` 以 ``registry.add_menu(...)`` 开头，
    这里返回真实 registry（当前活动菜单已由 ``add_settings_menu`` 指向
    「设置 → 终端」分组），从而复用现有菜单定义，避免重复维护一份。
    """

    def __init__(self, registry):
        self._registry = registry

    def add_menu(self, plugin_name, title):
        return self._registry


class TerminalPlugin(_BaseTerminalPlugin):
    """终端插件：原有菜单内容改为注册到「设置 → 终端」。"""

    def register_menus(self, registry):
        """终端不再占用菜单栏顶层菜单，设置项见 ``register_settings``。"""

    def register_settings(self, registry):
        """把终端现有菜单内容注册到「设置 → 终端」。

        终端各项设置（字号、保活、颜色、工具栏、日志、侧边栏）均即时生效，
        并已由 TerminalWidget 持久化到 ``terminal_settings``，重启后自动恢复。
        """
        registry.add_settings_menu(self.name, self.display_name)
        super().register_menus(_SettingsRegistryProxy(registry))
