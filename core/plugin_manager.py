import importlib
import os
import sys

from .menu_registry import MenuRegistry
from utils.logger import Logger


class PluginManager:
    def __init__(self, config_manager=None):
        self.plugins = {}
        self.plugin_configs = {}
        self._config_manager = config_manager
        # 统一状态接口：插件通过此回调向框架汇报自身状态
        self._status_callback = None
        # 保存每个插件最新上报的状态文本
        self._plugin_status = {}
        self._logger = Logger.get_instance()

    def load_plugins(self, plugin_configs, config_manager=None):
        if config_manager:
            self._config_manager = config_manager
        for config in plugin_configs:
            try:
                self.load_plugin(config)
            except Exception as e:
                self._logger.error(
                    f"加载插件失败: {config.get('name', 'unknown')}: {e}",
                    exc_info=True
                )

    def load_plugin(self, config):
        name = config['name']
        module_name = config['module']
        class_name = config['main_class']

        # Add plugin directory to path
        plugin_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "plugins"
        )
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        # Import module and get class
        module = importlib.import_module(module_name)
        plugin_class = getattr(module, class_name)

        # Instantiate plugin with config and config_manager
        if self._config_manager:
            plugin_instance = plugin_class(config, self._config_manager, self)
        else:
            plugin_instance = plugin_class(config, None, self)

        self.plugins[name] = plugin_instance
        self.plugin_configs[name] = config
        self._logger.info(f"插件已加载: {name} ({module_name}.{class_name})")

    def get_plugin(self, name):
        return self.plugins.get(name)

    def get_all_plugins(self):
        return self.plugins

    def reload_plugin(self, name):
        if name in self.plugin_configs:
            config = self.plugin_configs[name]
            if name in self.plugins:
                del self.plugins[name]
            self.load_plugin(config)

    # ========== 统一状态接口 ==========
    def set_status_callback(self, callback):
        """设置状态更新回调，由 MainWindow 注册

        Args:
            callback: 回调函数，签名 callback(plugin_name: str, status_text: str)
        """
        self._status_callback = callback

    def set_tool_status(self, plugin_name, status_text):
        """工具插件通过此接口更新自身状态

        Args:
            plugin_name: 插件名称
            status_text: 状态文本
        """
        self._plugin_status[plugin_name] = status_text
        if self._status_callback:
            try:
                self._status_callback(plugin_name, status_text)
            except Exception as e:
                self._logger.error(
                    f"插件状态回调执行失败: {plugin_name}: {e}",
                    exc_info=True
                )

    def get_tool_status(self, plugin_name):
        """获取指定插件的最新状态文本"""
        return self._plugin_status.get(plugin_name, '')

    def clear_tool_status(self, plugin_name):
        """清除指定插件的状态文本"""
        self._plugin_status.pop(plugin_name, None)
        if self._status_callback:
            self._status_callback(plugin_name, '')

    # ========== 菜单注册接口 ==========
    def collect_plugin_menus(self):
        """收集所有插件注册的菜单定义。

        遍历所有已加载插件，调用其 ``register_menus(registry)`` 方法（若存在），
        插件通过 registry 注册自身的菜单项。最终返回一个包含所有菜单定义的列表。

        Returns:
            list[dict]: 菜单定义列表，每项为
            ``{'plugin_name': str, 'title': str, 'items': [...]}``。
            按插件加载顺序排列。
        """
        registry = MenuRegistry()
        for plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            register_fn = getattr(plugin, 'register_menus', None)
            if register_fn is None:
                continue
            try:
                register_fn(registry)
            except Exception as e:
                self._logger.error(
                    f"收集插件菜单失败: {plugin_name}: {e}",
                    exc_info=True
                )
        return registry.get_menus()
